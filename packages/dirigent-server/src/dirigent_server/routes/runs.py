"""Runs: the list, the detail with its DAG view model, cancellation, retry, logs, events, and a report."""

import asyncio
from collections.abc import AsyncGenerator, Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, LogLevel, RunItemStatus, RunStatus
from dirigent_client.schemas import (
    TERMINAL_RUN_STATUSES,
    ArtifactOut,
    AttemptEvent,
    AttemptOut,
    DagNode,
    DagView,
    ItemOut,
    LogEntryOut,
    Page,
    RunDetail,
    RunOut,
    RunReport,
    StepReport,
)
from dirigent_common.durations import DurationError, parse_duration
from dirigent_core import telemetry
from dirigent_core.artifacts import JSON_CONTENT_TYPE, TEXT_KEY, canonical_json
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import PipelineDefinition, load_definition
from dirigent_core.engine.runs import RunCreationError, cancel_run, retry_step
from dirigent_core.engine.state import StepCounts, attempt_counts, item_counts, step_states
from dirigent_core.models import (
    ArtifactRef,
    LogEntry,
    Pipeline,
    PipelineVersion,
    Run,
    RunItem,
    StepAttempt,
    utcnow,
)
from dirigent_core.pipelines import UNWELL, carries_tag, failing_steps
from dirigent_core.registry import unmet_worker_tags
from dirigent_core.reporting import duration_ms, items_in_order, run_facts
from dirigent_server.dependencies import ServicesDep, SessionDep, get_sessions
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, int_cursor, uuid_cursor
from dirigent_server.security import OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["runs"])

DEFAULT_LOG_PAGE = 200

FOLLOW_INTERVAL_SECONDS = 0.5
FOLLOW_MAX_INTERVAL_SECONDS = 5.0
FOLLOW_BACKOFF = 1.5
FOLLOW_MAX_SECONDS = 3600.0

#: Each open tail is a database connection's worth of periodic queries against the pool
#: every request shares.
MAX_TAILS_PER_PRINCIPAL = 8

#: The header a browser's EventSource resends on its own, carrying the last id it saw.
LAST_EVENT_ID = Annotated[
    str | None,
    Header(alias="Last-Event-ID", description="The last log id delivered; a reconnect resumes past it."),
]

#: Process-local, so a cluster's total is this times the number of servers.
OPEN_TAILS: dict[str, int] = {}


async def _run_row(session: AsyncSession, run_id: UUID) -> Run:
    """Read a run, or say this instance has no such run."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no run {run_id}")
    return run


async def _context(session: AsyncSession, run: Run) -> tuple[Pipeline, PipelineVersion, PipelineDefinition]:
    """Read the pipeline and pinned version a run points at, plus its parsed definition."""
    pipeline = await session.get(Pipeline, run.pipeline_id)
    version = await session.get(PipelineVersion, run.pipeline_version_id)
    if pipeline is None or version is None:  # pragma: no cover - both are RESTRICT foreign keys
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="the run's definition is gone")
    return pipeline, version, load_definition(version.ordered_document)


def _render_run(run: Run, pipeline: Pipeline, version: PipelineVersion, failed_step: str | None = None) -> RunOut:
    """Render a run row with the names a client actually wants to see."""
    return RunOut(
        id=run.id,
        pipeline=pipeline.code,
        pipeline_version=version.version,
        status=run.status,
        priority=run.priority,
        params=dict(run.params),
        triggered_by_kind=run.triggered_by_kind,
        triggered_by_label=run.triggered_by_label,
        trace_id=telemetry.trace_id_of(run.traceparent),
        error=run.error,
        failed_step=failed_step,
        started_at=run.started_at,
        finished_at=run.finished_at,
        window_start=run.window_start,
        window_end=run.window_end,
        log_levels={pattern: LogLevel(str(level)) for pattern, level in run.log_levels.items()}
        if run.log_levels
        else None,
        created_at=run.created_at,
    )


def _dag(
    definition: PipelineDefinition,
    attempts: Mapping[str, StepCounts],
    items: Mapping[str, dict[RunItemStatus, int]],
) -> DagView:
    """Fold the pinned definition and the run's counts into the graph the UI draws.

    IN THE ORDER THE STEPS WERE WRITTEN, WHICH IS THE ONE ORDER THAT DOES NOT MOVE. A graph is a
    shape, and the same run read twice has to be the same shape: ordering the nodes by how the
    run went would lay the boxes out one way while it is in flight and another once it settles,
    and elk is told to respect the order it is given.
    """
    states = step_states(definition, {name: counts.latest for name, counts in attempts.items()})
    nodes: list[DagNode] = []
    edges: list[tuple[str, str]] = []
    for name, step in definition.steps.items():
        of_step = items.get(name, {})
        nodes.append(
            DagNode(
                code=name,
                name=step.name,
                block=step.block,
                outcome=states[name].outcome.value,
                depends_on=list(step.depends_on),
                rule=step.rule.value,
                fan_out=step.is_fan_out,
                items_total=sum(of_step.values()),
                items_failed=of_step.get(RunItemStatus.FAILED, 0),
                attempts=attempts[name].total if name in attempts else 0,
            )
        )
        edges.extend((dependency, name) for dependency in step.depends_on)
    return DagView(nodes=nodes, edges=edges)


@router.get("/runs", operation_id="listRuns", summary="List runs", response_model=Page[RunOut])
async def list_runs(
    session: SessionDep,
    principal: PrincipalDep,
    pipeline: Annotated[str | None, Query(description="Only runs of this pipeline.")] = None,
    run_status: Annotated[RunStatus | None, Query(alias="status", description="Only runs in this state.")] = None,
    since: Annotated[str | None, Query(description="Only runs created within this window, e.g. 24h.")] = None,
    tag: Annotated[
        list[str] | None, Query(description="Only runs whose pipeline wears this tag; repeat it to name more.")
    ] = None,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[RunOut]:
    """List runs newest first, filtered by pipeline, status, tag, and how far back to look.

    ``tag`` repeats, and repeating it narrows. It asks the pipeline the run is of what it
    wears now: a run pins its version, never its pipeline's tags, so retagging a pipeline
    changes which runs this answers with.
    """
    statement = (
        sa.select(Run, Pipeline, PipelineVersion)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .join(PipelineVersion, PipelineVersion.id == Run.pipeline_version_id)
        .order_by(Run.id.desc())
        .limit(limit + 1)
    )
    if pipeline is not None:
        statement = statement.where(Pipeline.code == pipeline)
    if run_status is not None:
        statement = statement.where(Run.status == run_status)
    if since is not None:
        statement = statement.where(Run.created_at >= utcnow() - _window(since))
    for one in tag or ():
        statement = statement.where(carries_tag(session, one))
    cursor = uuid_cursor(after)
    if cursor is not None:
        statement = statement.where(Run.id < cursor)
    rows = await session.execute(statement)
    read = rows.all()
    failing = await failing_steps(session, [run.id for run, _, _ in read if run.status in UNWELL])
    found = [_render_run(run, name, version, failing.get(run.id)) for run, name, version in read]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


def _window(since: str) -> timedelta:
    """Parse a humane window such as ``24h``, refusing anything the format does not define."""
    try:
        parsed = parse_duration(since)
    except DurationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    if not isinstance(parsed, timedelta):  # pragma: no cover - parse_duration returns one or raises
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{since!r} is not a duration")
    return parsed


@router.get("/runs/{run_id}", operation_id="getRun", summary="Read a run", response_model=RunDetail)
async def get_run(run_id: UUID, session: SessionDep, principal: PrincipalDep) -> RunDetail:
    """Read a run with the DAG view model, and how many items and attempts it has."""
    run = await _run_row(session, run_id)
    pipeline, version, definition = await _context(session, run)
    attempts = await attempt_counts(session, run_id)
    items = await item_counts(session, run_id)
    unmet = await unmet_worker_tags(session, run.worker_tags) if run.status is RunStatus.QUEUED else []
    return RunDetail(
        run=_render_run(run, pipeline, version),
        dag=_dag(definition, attempts, items),
        items_total=sum(sum(of_step.values()) for of_step in items.values()),
        attempts_total=sum(counts.total for counts in attempts.values()),
        waiting_for_workers=unmet or None,
    )


@router.get(
    "/runs/{run_id}/items",
    operation_id="listRunItems",
    summary="List a run's fan-out items",
    response_model=Page[ItemOut],
)
async def list_items(
    run_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[ItemOut]:
    """List a run's fan-out items in the order they were created, which is grid order."""
    await _run_row(session, run_id)
    statement = sa.select(RunItem).where(RunItem.run_id == run_id).order_by(RunItem.id).limit(limit + 1)
    cursor = uuid_cursor(after)
    if cursor is not None:
        statement = statement.where(RunItem.id > cursor)
    rows = list((await session.execute(statement)).scalars())
    found = [ItemOut.model_validate(row, from_attributes=True) for row in rows]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


@router.get(
    "/runs/{run_id}/attempts",
    operation_id="listRunAttempts",
    summary="List a run's attempts",
    response_model=Page[AttemptOut],
)
async def list_attempts(
    run_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
    step: Annotated[str | None, Query(description="Only attempts of this step.")] = None,
    attempt_status: Annotated[
        AttemptStatus | None, Query(alias="status", description="Only attempts in this state.")
    ] = None,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[AttemptOut]:
    """List a run's attempts in the order they were created, filtered by step and by state."""
    await _run_row(session, run_id)
    statement = sa.select(StepAttempt).where(StepAttempt.run_id == run_id).order_by(StepAttempt.id).limit(limit + 1)
    if step is not None:
        statement = statement.where(StepAttempt.step_name == step)
    if attempt_status is not None:
        statement = statement.where(StepAttempt.status == attempt_status)
    cursor = uuid_cursor(after)
    if cursor is not None:
        statement = statement.where(StepAttempt.id > cursor)
    rows = list((await session.execute(statement)).scalars())
    spilled = await _spilled(session, run_id, [row.id for row in rows])
    found = [_render_attempt(row, spilled) for row in rows]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


@router.get(
    "/runs/{run_id}/artifacts",
    operation_id="listRunArtifacts",
    summary="List a run's artifacts",
    response_model=Page[ArtifactOut],
)
async def list_artifacts(
    run_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[ArtifactOut]:
    """List what a run wrote down: each step's stored output, and the run's report document."""
    await _run_row(session, run_id)
    statement = sa.select(ArtifactRef).where(ArtifactRef.run_id == run_id).order_by(ArtifactRef.id).limit(limit + 1)
    cursor = uuid_cursor(after)
    if cursor is not None:
        statement = statement.where(ArtifactRef.id > cursor)
    rows = list((await session.execute(statement)).scalars())
    found = [ArtifactOut.model_validate(row, from_attributes=True) for row in rows]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


@router.get(
    "/artifacts/{artifact_id}",
    operation_id="readArtifact",
    summary="Read an artifact's content",
    response_class=Response,
)
async def read_artifact(
    artifact_id: UUID, session: SessionDep, services: ServicesDep, principal: PrincipalDep
) -> Response:
    """Answer with an artifact's own content, in the content type it was stored as.

    A document that inlined is answered from the row; one that went to storage is streamed
    back out of it, so a large output never passes through the server whole.
    """
    reference = await session.get(ArtifactRef, artifact_id)
    if reference is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no artifact {artifact_id}")
    content_type = reference.content_type or JSON_CONTENT_TYPE
    if reference.inline_value is not None:
        inlined = reference.inline_value.get(TEXT_KEY)
        if isinstance(inlined, str):
            return PlainTextResponse(inlined, media_type=content_type)
        return Response(canonical_json(reference.inline_value), media_type=JSON_CONTENT_TYPE)
    if reference.uri is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"artifact {artifact_id} holds no content")
    return StreamingResponse(services.storage.open_read(reference.uri), media_type=content_type)


async def _spilled(
    session: AsyncSession, run_id: UUID, only: Sequence[UUID] | None = None
) -> dict[UUID, tuple[str, int | None]]:
    """Map each attempt whose output went to storage to the URI and size it went as.

    An artifact that inlined is not in here: the attempt row already carries its value.
    """
    statement = sa.select(ArtifactRef.step_attempt_id, ArtifactRef.uri, ArtifactRef.size_bytes).where(
        ArtifactRef.run_id == run_id, ArtifactRef.uri.is_not(None)
    )
    if only is not None:
        statement = statement.where(ArtifactRef.step_attempt_id.in_(only))
    rows = await session.execute(statement)
    return {found: (uri, size) for found, uri, size in rows.all() if found is not None and uri is not None}


def _render_attempt(attempt: StepAttempt, spilled: dict[UUID, tuple[str, int | None]]) -> AttemptOut:
    """Render one attempt, naming the artifact its output was written to when there is one."""
    uri, size = spilled.get(attempt.id, (None, None))
    return AttemptOut.model_validate(attempt, from_attributes=True).model_copy(
        update={"output_uri": uri, "output_bytes": size}
    )


@router.post("/runs/{run_id}/$cancel", operation_id="cancelRun", summary="Cancel a run", response_model=RunOut)
async def cancel(run_id: UUID, session: SessionDep, services: ServicesDep, principal: OperatorDep) -> RunOut:
    """Stop what has not started, and tell the remote about what has."""
    run = await _run_row(session, run_id)
    pipeline, version, _ = await _context(session, run)
    await cancel_run(session, services, run, reason=f"cancelled by {principal.label}")
    return _render_run(run, pipeline, version)


@router.post(
    "/attempts/{attempt_id}/$retry",
    operation_id="retryAttempt",
    summary="Retry a failed step",
    response_model=AttemptOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry(
    attempt_id: UUID,
    session: SessionDep,
    services: ServicesDep,
    principal: OperatorDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Required, so a retried request creates one attempt."),
    ] = None,
) -> AttemptOut:
    """Create one manual attempt of a failed step, reading its upstream stored outputs."""
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an Idempotency-Key header is required, so a retried request creates one attempt",
        )
    attempt = await session.get(StepAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no attempt {attempt_id}")
    run = await _run_row(session, attempt.run_id)
    try:
        created = await retry_step(
            session,
            services,
            run,
            attempt.step_name,
            idempotency_key=idempotency_key,
            run_item_id=attempt.run_item_id,
        )
    except RunCreationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return AttemptOut.model_validate(created, from_attributes=True)


async def _log_page(session: AsyncSession, run_id: UUID, after: int, limit: int, step: str | None) -> Page[LogEntryOut]:
    """Read one page of a run's log entries, in write order."""
    statement = (
        sa.select(LogEntry).where(LogEntry.run_id == run_id, LogEntry.id > after).order_by(LogEntry.id).limit(limit + 1)
    )
    if step is not None:
        statement = statement.where(LogEntry.step_name == step)
    rows = list((await session.execute(statement)).scalars())
    found = [LogEntryOut.model_validate(row, from_attributes=True) for row in rows]
    items, following = clip(found, limit, lambda entry: entry.id)
    return Page(items=items, next=following)


@router.get(
    "/runs/{run_id}/$logs",
    operation_id="getRunLogs",
    summary="Read a run's log entries",
    response_model=Page[LogEntryOut],
    responses={200: {"content": {"text/event-stream": {}}, "description": "A page, or an SSE tail."}},
)
async def read_logs(
    run_id: UUID,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_LOG_PAGE,
    step: Annotated[str | None, Query(description="Only entries from this step.")] = None,
    follow: Annotated[str | None, Query(description="Set to sse to stream new entries as they land.")] = None,
    last_event_id: LAST_EVENT_ID = None,
) -> Page[LogEntryOut] | StreamingResponse:
    """Serve a page of log entries, or an SSE tail that follows the run to its end."""
    await _run_row(session, run_id)
    start = _resume_from(after, last_event_id)
    if follow != "sse":
        return await _log_page(session, run_id, start, limit, step)
    watcher = _claim(principal.user_id)
    return StreamingResponse(
        _tail(get_sessions(request), run_id, start, step, watcher),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


def _resume_from(after: str | None, last_event_id: str | None) -> int:
    """Name the log id a stream starts past: an explicit cursor, else the one a reconnect resent."""
    if after is not None:
        return int_cursor(after) or 0
    return int_cursor(last_event_id, name="Last-Event-ID") or 0


def next_interval(current: float) -> float:
    """Widen a quiet stream's poll interval, up to the ceiling."""
    return min(current * FOLLOW_BACKOFF, FOLLOW_MAX_INTERVAL_SECONDS)


def _claim(user_id: UUID) -> str:
    """Name the principal a stream is opened by, refusing one that already holds the cap.

    Log tails and event streams draw on one budget: what a principal costs this instance is
    the number of poll loops it holds open, not what they carry.
    """
    watcher = str(user_id)
    if OPEN_TAILS.get(watcher, 0) >= MAX_TAILS_PER_PRINCIPAL:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"you already have {MAX_TAILS_PER_PRINCIPAL} streams open on this server",
            headers={"retry-after": "5"},
        )
    return watcher


@contextmanager
def _held(watcher: str) -> Generator[None]:
    """Count one open stream against a principal's budget for as long as it runs."""
    OPEN_TAILS[watcher] = OPEN_TAILS.get(watcher, 0) + 1
    try:
        yield
    finally:
        remaining = OPEN_TAILS.get(watcher, 1) - 1
        if remaining > 0:
            OPEN_TAILS[watcher] = remaining
        else:
            OPEN_TAILS.pop(watcher, None)


async def _tail_read(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    cursor: int,
    step: str | None,
) -> tuple[Page[LogEntryOut], bool]:
    """One poll's reads, whole or not at all.

    A watcher that disconnects cancels its generator wherever it happens to be, and a
    driver await torn down mid-read leaves the pooled connection broken for whoever draws
    it next. Shielded by the caller, the read runs to its own end and closes its session,
    so a cancellation only ever lands between polls.
    """
    async with session_scope(sessions) as session:
        page = await _log_page(session, run_id, cursor, DEFAULT_LOG_PAGE, step)
        run = await session.get(Run, run_id)
        return page, run is not None and run.status in TERMINAL_RUN_STATUSES


async def _tail(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    after: int,
    step: str | None,
    watcher: str,
) -> AsyncGenerator[str]:
    """Stream a run's log entries as server-sent events until the run settles.

    ``end`` says the run settled and there is nothing more to read. At the wall-clock limit
    the stream says ``expired`` instead, which a client reopens from the last id it saw.
    """
    with _held(watcher):
        cursor = after
        waited = 0.0
        interval = FOLLOW_INTERVAL_SECONDS
        while waited < FOLLOW_MAX_SECONDS:
            page, settled = await asyncio.shield(_tail_read(sessions, run_id, cursor, step))
            for entry in page.items:
                yield f"id: {entry.id}\nevent: log\ndata: {entry.model_dump_json()}\n\n"
                cursor = entry.id
            if page.next is not None:
                interval = FOLLOW_INTERVAL_SECONDS
                continue
            if settled:
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(interval)
            waited += interval
            interval = next_interval(interval)
        yield "event: expired\ndata: {}\n\n"


@router.get(
    "/runs/{run_id}/$events",
    operation_id="getRunEvents",
    summary="Stream a run's story",
    response_model=None,
    responses={200: {"content": {"text/event-stream": {}}, "description": "The run's story, as SSE."}},
)
async def read_events(
    run_id: UUID,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    last_event_id: LAST_EVENT_ID = None,
) -> StreamingResponse:
    """Stream one run's story: its attempts as they move, its log entries, and how it ended.

    Each cycle reads the run's whole attempt grid, which is the read a polling client caused
    once per poll; it is made once per watcher here and goes out as the states that changed.
    """
    await _run_row(session, run_id)
    watcher = _claim(principal.user_id)
    return StreamingResponse(
        _story(get_sessions(request), run_id, _resume_from(after, last_event_id), watcher),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


#: What an attempt looks like from outside: a change to any of it is news to a watcher.
type Fingerprint = tuple[AttemptStatus, int, datetime | None, str | None, float | None]


def _fingerprint(attempt: StepAttempt) -> Fingerprint:
    """State the observable part of an attempt."""
    return (attempt.status, attempt.attempt, attempt.finished_at, attempt.waiting_message, attempt.waiting_progress)


#: What a run looks like from outside: a change to any of it is news to a watcher.
type RunFingerprint = tuple[RunStatus, datetime | None, datetime | None, str | None]


def _run_fingerprint(run: RunOut) -> RunFingerprint:
    """State the observable part of a run."""
    return (run.status, run.started_at, run.finished_at, run.error)


def _moment(when: datetime | None) -> datetime:
    """Read a timestamp for ordering, treating a missing one as the beginning of time."""
    return when if when is not None else datetime.min.replace(tzinfo=UTC)


async def _attempt_rows(session: AsyncSession, run_id: UUID) -> list[StepAttempt]:
    """Read every attempt of a run by id, which is the order they were created in."""
    rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run_id).order_by(StepAttempt.id))
    return list(rows.scalars())


def _render_event(
    attempt: StepAttempt,
    spilled: dict[UUID, tuple[str, int | None]],
    labels: dict[UUID, tuple[str, int]],
) -> AttemptEvent:
    """Render one attempt for the event stream, naming the fan-out element it ran for.

    The element's label and its index both go out: the label is what a reader reads, and the
    index is the fan-out order a list of the elements is put back into.
    """
    uri, size = spilled.get(attempt.id, (None, None))
    named = labels.get(attempt.run_item_id) if attempt.run_item_id is not None else None
    item, index = named if named is not None else (None, None)
    return AttemptEvent.model_validate(attempt, from_attributes=True).model_copy(
        update={"output_uri": uri, "output_bytes": size, "item": item, "item_index": index}
    )


async def _story_read(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    cursor: int,
    want_labels: bool | None,
) -> tuple[
    list[StepAttempt],
    dict[UUID, tuple[str, int | None]],
    Page[LogEntryOut],
    RunOut | None,
    dict[UUID, tuple[str, int]] | None,
]:
    """One story poll's reads, whole or not at all; see ``_tail_read`` for why.

    The run is rendered on every poll, not only once it has settled: a watcher learns that a
    run started the same way it learns that one ended.
    """
    async with session_scope(sessions) as session:
        read_labels = None
        if want_labels:
            read_labels = {
                item.id: (item.item_key.strip() or str(item.item_index), item.item_index)
                for item in await items_in_order(session, run_id)
            }
        attempts = await _attempt_rows(session, run_id)
        spilled = await _spilled(session, run_id)
        page = await _log_page(session, run_id, cursor, DEFAULT_LOG_PAGE, None)
        found = (
            await session.execute(
                sa.select(Run, Pipeline, PipelineVersion)
                .join(Pipeline, Pipeline.id == Run.pipeline_id)
                .join(PipelineVersion, PipelineVersion.id == Run.pipeline_version_id)
                .where(Run.id == run_id)
            )
        ).all()
        rendered = next((_render_run(run, pipeline, version) for run, pipeline, version in found), None)
    return attempts, spilled, page, rendered, read_labels


def _in_order(transitions: Sequence[tuple[datetime, str]], entries: Sequence[tuple[datetime, str]]) -> list[str]:
    """Merge one cycle's attempt transitions into its log entries, leaving the entries in id order.

    LOG ENTRIES GO OUT IN ASCENDING ID, ALWAYS. A client resumes from the highest id it has
    been sent, so an entry delivered after a higher one is dropped and never asked for again.
    Lines are buffered per attempt and written on a flush and again when that attempt settles,
    so two attempts running at once commit theirs out of timestamp order: sorting a cycle by
    timestamp is exactly what loses them.

    A transition is placed before the first entry written no earlier than it, which keeps a
    state change ahead of the lines it caused.
    """
    ordered = sorted(transitions, key=lambda one: one[0])
    merged: list[str] = []
    placed = 0
    for when, payload in entries:
        while placed < len(ordered) and ordered[placed][0] <= when:
            merged.append(ordered[placed][1])
            placed += 1
        merged.append(payload)
    merged.extend(payload for _, payload in ordered[placed:])
    return merged


async def _story(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    after: int,
    watcher: str,
) -> AsyncGenerator[str]:
    """Stream a run's own state and its attempt transitions and log entries, in order.

    Every attempt is reported once on connect, so a watcher that joined late reads the same
    story as one that was there from the start, without the states it missed in between.

    The run goes out on connect and again whenever its own state changes, ahead of that
    cycle's attempt transitions and log entries, so a state change leads the lines it caused.
    Once the run settles it goes out on the settled path below instead, after the last drain.

    Only a log frame carries an ``id``. The attempt and run frames are replayed on connect by
    that same rule, so an id on one would make a reconnect resume past a state it is about to
    be told again; the log cursor is the only position a reconnect can restore, and a client
    dedupes the replayed attempts by their own ids.

    ``end`` says the run settled and follows the ``run`` frame. At the wall-clock limit the
    stream says ``expired`` instead, which a client reopens from the last id it saw.
    """
    with _held(watcher):
        cursor = after
        reported: dict[UUID, Fingerprint] = {}
        reported_run: RunFingerprint | None = None
        labels: dict[UUID, tuple[str, int]] = {}
        loaded = False
        drained = False
        waited = 0.0
        interval = FOLLOW_INTERVAL_SECONDS
        while waited < FOLLOW_MAX_SECONDS:
            # Shielded for the same reason _tail_read is: a disconnect lands between polls,
            # never inside a driver await holding the pooled connection.
            attempts, spilled, page, rendered, read_labels = await asyncio.shield(
                _story_read(sessions, run_id, cursor, None if loaded else True)
            )
            if read_labels is not None:
                labels = read_labels
                loaded = True
            settled = rendered is not None and rendered.status in TERMINAL_RUN_STATUSES
            if rendered is not None and not settled and _run_fingerprint(rendered) != reported_run:
                reported_run = _run_fingerprint(rendered)
                yield f"event: run\ndata: {rendered.model_dump_json()}\n\n"
            moved = [row for row in attempts if reported.get(row.id) != _fingerprint(row)]
            reported.update({row.id: _fingerprint(row) for row in moved})
            transitions = [
                (
                    _moment(row.finished_at or row.started_at),
                    f"event: attempt\ndata: {_render_event(row, spilled, labels).model_dump_json()}\n\n",
                )
                for row in moved
            ]
            entries = [
                (
                    _moment(entry.created_at),
                    f"id: {entry.id}\nevent: log\ndata: {entry.model_dump_json()}\n\n",
                )
                for entry in page.items
            ]
            for payload in _in_order(transitions, entries):
                yield payload
            if page.items:
                cursor = page.items[-1].id
            if page.next is not None:
                interval = FOLLOW_INTERVAL_SECONDS
                continue
            if settled and rendered is not None:
                # One more pass after the run settles, for the lines a block wrote on its way out.
                if drained:
                    yield f"event: run\ndata: {rendered.model_dump_json()}\n\n"
                    yield "event: end\ndata: {}\n\n"
                    return
                drained = True
                continue
            await asyncio.sleep(interval)
            waited += interval
            interval = next_interval(interval)
        yield "event: expired\ndata: {}\n\n"


@router.get(
    "/runs/{run_id}/$report",
    operation_id="getRunReport",
    summary="Summarise a run",
    response_model=RunReport,
)
async def report(run_id: UUID, session: SessionDep, principal: PrincipalDep) -> RunReport:
    """Summarise a run: what each step amounted to, and how long the whole thing took."""
    run = await _run_row(session, run_id)
    pipeline, version, definition = await _context(session, run)
    facts = await run_facts(session, run, pipeline, version, definition, base_url=None)
    return RunReport(
        run_id=run.id,
        pipeline=facts.pipeline.code,
        pipeline_version=facts.pipeline.version,
        status=run.status,
        triggered_by=run.triggered_by_label,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=duration_ms(run.started_at, run.finished_at),
        steps=[
            StepReport(
                step=step.step,
                block=step.block,
                outcome=step.outcome,
                attempts=step.attempts,
                depends_on=list(step.depends_on),
                warnings=step.warnings,
                duration_ms=step.duration_ms,
                error=step.error,
            )
            for step in facts.steps
        ],
        items_total=facts.items_total,
        items_failed=facts.items_failed,
        error=run.error,
    )
