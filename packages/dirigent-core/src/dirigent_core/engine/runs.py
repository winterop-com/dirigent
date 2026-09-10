"""Creating, cancelling, and manually retrying runs -- including one run starting another."""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Final, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, JsonValue, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import (
    AttemptKind,
    AttemptStatus,
    ProvenanceSource,
    RunItemStatus,
    RunPriority,
    RunStatus,
    TriggerKind,
)
from dirigent_common import JsonMap
from dirigent_core import telemetry
from dirigent_core.database import session_scope
from dirigent_core.engine.context import (
    BufferedLogger,
    ConnectionRecord,
    EngineStepContext,
    kept_level,
    load_connections,
)
from dirigent_core.engine.definition import (
    ParameterError,
    PipelineDefinition,
    StepDefinition,
    dump_definition,
    load_definition,
)
from dirigent_core.engine.references import ReferenceScope, resolve
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import advance, lock_pipeline, lock_run
from dirigent_core.ids import uuid7
from dirigent_core.logging import get_logger
from dirigent_core.models import Pipeline, PipelineVersion, Run, RunItem, StepAttempt, utcnow
from dirigent_core.storage import scratch_prefix
from dirigent_plugin import RemoteHandle, RunRefused, RunSnapshot, RunState, StartedRun

IDEMPOTENCY_KEY = "_idempotency_key"

ACTIVE_RUN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)

_logger = get_logger("engine")


class RunCreationError(Exception):
    """A run could not be created."""


class FanOutError(RunCreationError):
    """A fan-out expression did not produce a list the engine could expand."""


class Attribution(BaseModel):
    """Who or what started a run."""

    model_config = ConfigDict(frozen=True)

    kind: TriggerKind = TriggerKind.ADHOC
    id: UUID | None = None
    label: str | None = None


class RunWindow(BaseModel):
    """The logical data interval a run covers, half-open: ``[start, end)``.

    A schedule-fired run derives it from the cadence, a backfill from the window it fills,
    and an ad hoc run carries one only if it was asked for.
    """

    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _run_forwards(self) -> "RunWindow":
        """Refuse an empty or backwards interval, which no step could read as a window."""
        if self.start >= self.end:
            raise ValueError(
                f"a window runs forwards and covers something: {self.start.isoformat()} "
                f"is not before {self.end.isoformat()}"
            )
        return self


class Provenance(BaseModel):
    """Where a pipeline version came from: who applied it, and from what."""

    model_config = ConfigDict(frozen=True)

    source: ProvenanceSource = ProvenanceSource.API
    ref: str | None = None
    """The file path, URL, or UI context the document was applied from."""

    applied_by: str | None = None


async def save_pipeline(
    session: AsyncSession,
    definition: PipelineDefinition,
    *,
    description: str | None = None,
    provenance: Provenance | None = None,
) -> PipelineVersion:
    """Insert a new immutable version of a pipeline, creating the pipeline on first sight.

    Two applies of one document at once race twice over: on the live-code index when neither
    has created the pipeline, and on the next version number when both have read the same
    current one. The attempt runs in a savepoint so the loser can be tried again against what
    the winner wrote, rather than surfacing a uniqueness violation as a 500.
    """
    try:
        async with session.begin_nested():
            return await _save_pipeline_once(session, definition, description, provenance)
    except IntegrityError:
        async with session.begin_nested():
            return await _save_pipeline_once(session, definition, description, provenance)


async def _save_pipeline_once(
    session: AsyncSession,
    definition: PipelineDefinition,
    description: str | None,
    provenance: "Provenance | None",
) -> PipelineVersion:
    """Read what exists, decide the next version, and write it."""
    from dirigent_core.documents import digest_of

    document = dump_definition(definition)
    found = await session.execute(sa.select(Pipeline).where(Pipeline.code == definition.code))
    pipeline = found.scalar_one_or_none()
    if pipeline is None:
        pipeline = Pipeline(
            code=definition.code,
            name=definition.name,
            description=description or definition.description,
            tags=list(definition.tags),
        )
        session.add(pipeline)
        await session.flush()
    else:
        # The version is read and then written, so the read has to hold until the write.
        await lock_pipeline(session, pipeline.id)
        await session.refresh(pipeline)
        pipeline.name = definition.name
        pipeline.description = description or definition.description
        pipeline.tags = list(definition.tags)
    recorded = provenance or Provenance()
    next_version = (pipeline.current_version or 0) + 1
    version = PipelineVersion(
        pipeline_id=pipeline.id,
        version=next_version,
        document=document,
        step_order=list(definition.steps),
        digest=digest_of(definition),
        provenance_source=recorded.source,
        provenance_ref=recorded.ref,
        applied_by=recorded.applied_by,
    )
    session.add(version)
    pipeline.current_version = next_version
    await session.flush()
    return version


async def active_runs(session: AsyncSession, pipeline_id: UUID) -> list[Run]:
    """List the runs of a pipeline that still occupy its concurrency slot."""
    rows = await session.execute(
        sa.select(Run)
        .where(Run.pipeline_id == pipeline_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(Run.created_at)
    )
    return list(rows.scalars())


async def create_run(
    session: AsyncSession,
    services: EngineServices,
    version: PipelineVersion,
    *,
    params: JsonMap | None = None,
    attribution: Attribution | None = None,
    window: RunWindow | None = None,
    log_levels: JsonMap | None = None,
    priority: RunPriority | None = None,
    now: datetime | None = None,
) -> Run | None:
    """Instantiate a run from a pipeline version and validated parameters.

    ``priority`` is the trigger's or the caller's override; omitted, the run takes the
    pipeline's own. Whichever wins is pinned on the row, so a later edit of the document
    never reorders a run already in flight.

    Returns None when the pipeline's ``skip`` concurrency policy refuses the run outright.
    """
    moment = now or utcnow()
    definition = load_definition(version.document)
    resolved_params = definition.validate_params(params or {}, services.format_checker)
    _refuse_disabled_blocks(definition, services)
    who = attribution or Attribution()

    # The span the whole run hangs from. Its context is written to the row, and every
    # attempt on every worker opens under it, so one run is one trace.
    with telemetry.run_span(definition.code, trigger=who.kind.value) as span:
        # The concurrency policy is a read, a decision, and a write, and two triggers on
        # different processes can arrive at the same instant. Without this lock both read
        # "nothing is running" and both create a run, so `skip` skips nothing and `queue`
        # queues nothing.
        await lock_pipeline(session, version.pipeline_id)

        # Every fan-out is expanded before the concurrency policy decides anything, because a
        # `replace` cancellation asks operators to kill remote work and a refusal after that
        # leaves those jobs dead with their run restored. The run's id is minted here so the
        # expansion can address the run it is about to belong to.
        run_id = uuid7()
        scope = ReferenceScope(
            params=resolved_params,
            scratch=scratch_prefix(services.settings.artifact_root, run_id),
            run_id=run_id,
            window_start=window.start if window is not None else None,
            window_end=window.end if window is not None else None,
        )
        expanded = [(name, resolve_fan_out(name, step, scope)) for name, step in definition.steps.items()]

        # A run is many rows written in sequence, and a database error refuses once some of
        # them are flushed. The savepoint discards the half-written run while the caller's
        # transaction lives on, so no worker claims the attempts of a run that never landed.
        async with session.begin_nested():
            held = False
            match definition.concurrency:
                case "skip" if await active_runs(session, version.pipeline_id):
                    _logger.info("run skipped by concurrency policy", pipeline=definition.code)
                    return None
                case "queue" if await active_runs(session, version.pipeline_id):
                    held = True
                case "replace":
                    for running in await active_runs(session, version.pipeline_id):
                        await cancel_run(session, services, running, reason="replaced by a newer run", now=moment)
                case _:
                    pass

            run = Run(
                id=run_id,
                pipeline_id=version.pipeline_id,
                pipeline_version_id=version.id,
                status=RunStatus.QUEUED,
                priority=priority or definition.priority,
                params=resolved_params,
                triggered_by_kind=who.kind,
                triggered_by_id=who.id,
                triggered_by_label=who.label,
                traceparent=telemetry.current_traceparent(),
                window_start=window.start if window is not None else None,
                window_end=window.end if window is not None else None,
                log_levels=dict(log_levels) if log_levels else None,
                worker_tags=list(definition.requires.workers),
            )
            session.add(run)
            await session.flush()
            span.set_attribute("dirigent.run.id", str(run.id))

            for name, elements in expanded:
                await _create_step_rows(session, run, name, definition.steps[name], elements, moment, held=held)
            await session.flush()
            if not held:
                await advance(session, run, definition, now=moment)
            _logger.info(
                "run created",
                run_id=str(run.id),
                pipeline=definition.code,
                steps=len(definition.steps),
                held=held,
            )
            return run


async def _create_step_rows(
    session: AsyncSession,
    run: Run,
    name: str,
    step: StepDefinition,
    elements: Sequence[JsonValue],
    moment: datetime,
    *,
    held: bool,
) -> None:
    """Write the attempt rows one step needs, one per element of an already expanded fan-out."""
    if not step.is_fan_out:
        session.add(_new_attempt(run, name, step, moment, held=held))
        return
    for index, element in enumerate(elements):
        item = RunItem(
            run_id=run.id,
            step_name=name,
            item_index=index,
            item_key=str(element)[:500],
            item_value={"value": element},
            status=RunItemStatus.PENDING,
        )
        session.add(item)
        await session.flush()
        session.add(_new_attempt(run, name, step, moment, held=held, run_item_id=item.id))


def _new_attempt(
    run: Run,
    name: str,
    step: StepDefinition,
    moment: datetime,
    *,
    held: bool,
    run_item_id: UUID | None = None,
) -> StepAttempt:
    """Build one attempt row: root steps queued, everything else pending on its edges."""
    root = not step.depends_on and not held
    return StepAttempt(
        run_id=run.id,
        run_item_id=run_item_id,
        step_name=name,
        block_id=step.block,
        attempt=1,
        kind=AttemptKind.AUTOMATIC,
        status=AttemptStatus.QUEUED if root else AttemptStatus.PENDING,
        available_at=moment if root else None,
    )


def resolve_fan_out(name: str, step: StepDefinition, scope: ReferenceScope) -> list[JsonValue]:
    """Expand a step's ``for_each`` into the list of elements it maps over.

    Cardinality is fixed when the run is created, so a ``for_each`` may read parameters and
    the run, but not an upstream step's output.
    """
    expression = step.for_each
    if isinstance(expression, list):
        resolved_elements = resolve(cast("JsonValue", expression), scope)
        return list(cast("list[JsonValue]", resolved_elements))
    if expression is None:
        return []
    if "steps." in expression:
        raise FanOutError(
            f"step {name!r} maps over {expression!r}: fan-out is expanded when the run is created, "
            f"so for_each may read params, item, and run, but not another step's output"
        )
    resolved = resolve(expression, scope)
    if not isinstance(resolved, list):
        raise FanOutError(
            f"step {name!r} maps over {expression!r}, which resolved to {type(resolved).__name__}, not a list"
        )
    return resolved


def _refuse_disabled_blocks(definition: PipelineDefinition, services: EngineServices) -> None:
    """Refuse to create a run whose steps include a block the instance has not allowlisted."""
    for name, step in definition.steps.items():
        refusal = services.local_execution_refusal(step.block)
        if refusal is not None:
            raise RunCreationError(f"step {name!r}: {refusal.message}")


async def cancel_run(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    *,
    reason: str = "cancelled",
    now: datetime | None = None,
) -> Run:
    """Cancel a run: stop what has not started, and tell the remote about what has.

    Cancelling a remote is best effort by contract, so a refusal is logged rather than
    raised and the attempt reaches its terminal state either way.
    """
    moment = now or utcnow()
    # The lock comes before the terminal check, not after. Without it, a cancel racing the
    # outcome transaction that settles the run's last attempt reads "still running" and then
    # overwrites an already-succeeded run with "cancelled".
    await lock_run(session, run.id)
    await session.refresh(run)
    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.CANCELLED):
        return run
    rows = await session.execute(
        sa.select(StepAttempt).where(
            StepAttempt.run_id == run.id,
            StepAttempt.status.in_(
                (AttemptStatus.PENDING, AttemptStatus.QUEUED, AttemptStatus.RUNNING, AttemptStatus.WAITING)
            ),
        )
    )
    attempts = list(rows.scalars())
    connections = await load_connections(session)
    for attempt in attempts:
        # A handle is what says remote work exists, and it is committed one transaction
        # before the attempt is parked as waiting. Telling only a waiting attempt's remote
        # leaves a job running whenever the cancel lands inside that window.
        if attempt.remote_handle:
            await cancel_remote(session, services, run, attempt, connections)
        attempt.status = AttemptStatus.CANCELLED
        attempt.finished_at = moment
        attempt.lease_owner = None
        attempt.lease_expires_at = None
    await _cancel_items(session, run, moment)
    run.status = RunStatus.CANCELLED
    run.error = reason
    run.finished_at = moment
    # Imported here rather than at module scope: reporting reads this module's definitions.
    from dirigent_core.reporting import render_run_report

    # A cancelled run is one of the runs whose report matters most, and no step of it can
    # render one.
    await render_run_report(session, services, run, await _definition_of(session, run), now=moment)
    # A cancelled run frees the concurrency slot as a finished one does; without promoting
    # here, cancelling the active run of a `queue` pipeline wedges the queue forever.
    await promote_queued_run(session, services, run.pipeline_id)
    _logger.info("run cancelled", run_id=str(run.id), reason=reason, attempts=len(attempts))
    return run


async def _cancel_items(session: AsyncSession, run: Run, moment: datetime) -> None:
    """Mark every unfinished run item of a cancelled run as skipped."""
    rows = await session.execute(
        sa.select(RunItem).where(
            RunItem.run_id == run.id,
            RunItem.status.in_((RunItemStatus.PENDING, RunItemStatus.RUNNING)),
        )
    )
    for item in rows.scalars():
        item.status = RunItemStatus.SKIPPED
        item.finished_at = moment


async def cancel_remote(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    attempt: StepAttempt,
    connections: Mapping[str, ConnectionRecord],
) -> None:
    """Ask an operator to cancel the remote work an attempt holds a handle on.

    The runs facade handed over is bound to the cancelling transaction, so an operator that
    cancels by cancelling another run settles the parent and the child in one commit.
    """
    block = services.host.operators.get(attempt.block_id)
    if block is None or not attempt.remote_handle:
        return
    context = EngineStepContext(
        run_id=run.id,
        step=attempt.step_name,
        run_item_id=attempt.run_item_id,
        attempt=attempt.attempt,
        started_at=attempt.started_at or utcnow(),
        inline_capture=services.settings.inline_capture,
        params=dict(run.params),
        log=BufferedLogger(
            run_id=run.id,
            step_name=attempt.step_name,
            step_attempt_id=attempt.id,
            keep=kept_level(run.log_levels, attempt.block_id),
            limit=services.settings.log_entries_per_attempt,
            batch=services.settings.log_flush_batch,
        ),
        storage=services.storage,
        scratch=scratch_prefix(services.settings.artifact_root, run.id),
        work_root=services.settings.work_root,
        connections=dict(connections),
        connection_models=services.connection_models,
        secrets=services.secrets,
        runs=EngineRuns(services, parent_run_id=run.id, session=session),
        format_checker=services.format_checker,
        storage_connections=services.settings.storage_connections,
    )
    try:
        config = block.config_model.model_validate((attempt.input or {}).get("config", {}))
        accepted = await block.cancel(RemoteHandle.model_validate(attempt.remote_handle), config, context)
    except Exception as error:  # best effort by contract: a refusal must not block the cancel
        _logger.warning("remote cancellation failed", attempt_id=str(attempt.id), error=str(error))
        return
    _logger.info("remote cancellation requested", attempt_id=str(attempt.id), accepted=accepted)


async def promote_queued_run(session: AsyncSession, services: EngineServices, pipeline_id: UUID) -> Run | None:
    """Release the oldest run held behind a ``queue`` concurrency policy, if the slot is free.

    A run settling frees the slot only if it held it: cancelling a held run settles a run that
    never did, and releasing there would run two of a ``queue`` pipeline at once.
    """
    # The caller's own writes decide whether the slot is free, and the session does not
    # autoflush, so the run and attempts read below would otherwise be the ones on disk.
    await session.flush()
    held: list[Run] = []
    for run in await active_runs(session, pipeline_id):
        if await _occupies_slot(session, run):
            return None
        held.append(run)
    for run in held:
        version = await session.get(PipelineVersion, run.pipeline_version_id)
        if version is None:
            continue
        await advance(session, run, load_definition(version.document))
        _logger.info("held run released", run_id=str(run.id))
        return run
    return None


async def _occupies_slot(session: AsyncSession, run: Run) -> bool:
    """Say whether an active run holds the pipeline's slot rather than waiting behind it.

    A held run is queued with nothing started and every attempt still pending; once released
    its root attempts are queued, which is what tells the two apart.
    """
    if run.status is not RunStatus.QUEUED or run.started_at is not None:
        return True
    attempts = await session.execute(sa.select(StepAttempt.status).where(StepAttempt.run_id == run.id))
    return any(status is not AttemptStatus.PENDING for status in attempts.scalars())


async def retry_step(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    step_name: str,
    *,
    idempotency_key: str,
    run_item_id: UUID | None = None,
    now: datetime | None = None,
) -> StepAttempt:
    """Create one manual attempt for a failed step, reading upstream stored outputs.

    Nothing upstream re-executes; steps skipped only because this one failed are returned to
    pending so the ordinary readiness walk carries the run onward.
    """
    moment = now or utcnow()
    definition = await _definition_of(session, run)
    # The pipeline lock comes before the run lock, which is the order run creation takes them
    # in, and the run lock makes two retries of one step serial: the second reads the attempt
    # the first wrote instead of writing the same attempt number again.
    await lock_pipeline(session, run.pipeline_id)
    await lock_run(session, run.id)
    await session.refresh(run)
    scoped = idempotency_scope(step_name, run_item_id, idempotency_key)
    existing = await _attempt_with_key(session, run.id, scoped)
    if existing is not None:
        return existing

    rows = await session.execute(
        sa.select(StepAttempt)
        .where(
            StepAttempt.run_id == run.id,
            StepAttempt.step_name == step_name,
            StepAttempt.run_item_id == run_item_id if run_item_id else StepAttempt.run_item_id.is_(None),
        )
        .order_by(StepAttempt.attempt.desc())
    )
    attempts = list(rows.scalars())
    if not attempts:
        raise RunCreationError(f"run {run.id} has no attempt of step {step_name!r} to retry")
    latest = attempts[0]
    if latest.status not in (AttemptStatus.FAILED, AttemptStatus.SKIPPED, AttemptStatus.CANCELLED):
        raise RunCreationError(
            f"step {step_name!r} is {latest.status.value}, and only a settled failure can be retried"
        )

    await _admit_retry(session, services, run, definition, moment)

    retried = StepAttempt(
        run_id=run.id,
        run_item_id=latest.run_item_id,
        step_name=step_name,
        block_id=latest.block_id,
        attempt=latest.attempt + 1,
        kind=AttemptKind.MANUAL,
        status=AttemptStatus.QUEUED,
        available_at=moment,
        idempotency_key=scoped,
        input={IDEMPOTENCY_KEY: idempotency_key},
    )
    session.add(retried)
    await _reopen_propagated_skips(session, run.id)
    run.status = RunStatus.RUNNING
    run.finished_at = None
    run.error = None
    await session.flush()
    _logger.info("manual retry created", run_id=str(run.id), step=step_name, attempt=retried.attempt)
    return retried


async def _definition_of(session: AsyncSession, run: Run) -> PipelineDefinition:
    """Read the pipeline definition of the version a run pins."""
    version = await session.get(PipelineVersion, run.pipeline_version_id)
    if version is None:  # pragma: no cover - a run always pins a version that exists
        raise RunCreationError(f"run {run.id} pins a pipeline version that is gone")
    return load_definition(version.document)


async def _admit_retry(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    moment: datetime,
) -> None:
    """Apply the pipeline's concurrency policy to a retry that reopens a settled run.

    Reopening a settled run puts a second run of the pipeline in flight, which is the thing
    the policy exists to decide. A run that is still active took its slot when it was created
    and keeps it.
    """
    if run.status in ACTIVE_RUN_STATUSES:
        return
    others = [other for other in await active_runs(session, run.pipeline_id) if other.id != run.id]
    match definition.concurrency:
        case "skip" | "queue":
            for other in others:
                if await _occupies_slot(session, other):
                    raise RunCreationError(
                        f"another run of pipeline {definition.code!r} is in flight; retry once it has finished"
                    )
        case "replace":
            for other in others:
                await cancel_run(session, services, other, reason="replaced by a manual retry", now=moment)
        case _:
            pass


def idempotency_scope(step_name: str, run_item_id: UUID | None, key: str) -> str:
    """Render the key a manual retry is stored under: the caller's key, scoped to its target.

    This rendering is what the unique constraint is on, so a change here changes what the
    database enforces.
    """
    return f"{step_name}\x1f{run_item_id or '-'}\x1f{key}"


async def _attempt_with_key(session: AsyncSession, run_id: UUID, scoped: str) -> StepAttempt | None:
    """Find the attempt a previous call with this idempotency key already created."""
    found = await session.execute(
        sa.select(StepAttempt).where(StepAttempt.run_id == run_id, StepAttempt.idempotency_key == scoped)
    )
    return found.scalar_one_or_none()


async def _reopen_propagated_skips(session: AsyncSession, run_id: UUID) -> None:
    """Return skipped-by-propagation attempts to pending, so the walk can decide again.

    A step skipped because a prerequisite failed never ran, so it has no start time; a
    sensor that skipped on its own timeout does, and stays settled.
    """
    rows = await session.execute(
        sa.select(StepAttempt).where(
            StepAttempt.run_id == run_id,
            StepAttempt.status == AttemptStatus.SKIPPED,
            StepAttempt.started_at.is_(None),
        )
    )
    for attempt in rows.scalars():
        attempt.status = AttemptStatus.PENDING
        attempt.finished_at = None


def item_value_of(item: RunItem | None) -> tuple[JsonValue, bool]:
    """Unwrap the element a run item maps, and say whether there is one at all."""
    if item is None or item.item_value is None:
        return None, False
    return item.item_value.get("value"), True


def attempts_of(run_id: UUID, attempts: Sequence[StepAttempt]) -> list[StepAttempt]:
    """Filter a list of attempts down to one run."""
    return [attempt for attempt in attempts if attempt.run_id == run_id]


# -- one run starting another ----------------------------------------------------

UNSETTLED_STATUSES: Final = (
    AttemptStatus.PENDING,
    AttemptStatus.QUEUED,
    AttemptStatus.RUNNING,
    AttemptStatus.WAITING,
)

#: A second bound beyond ``max_depth``, so rows that describe a loop cannot make the walk
#: unbounded.
MAX_CHAIN_WALK: Final = 64


class EngineRuns:
    """The engine's implementation of the block-facing ``Runs`` facade, scoped to one run.

    Given a session factory it commits its own transaction per call, which is what ``execute``
    and ``probe`` need: an uncommitted child run is one the workers never see. Given a session
    it joins the caller's transaction, so cancelling a parent and its child commits as one.
    """

    def __init__(
        self,
        services: EngineServices,
        *,
        parent_run_id: UUID,
        sessions: async_sessionmaker[AsyncSession] | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Bind the facade to the run whose step is calling it, and to how it reaches the database."""
        if (sessions is None) == (session is None):
            raise ValueError("EngineRuns takes either a session factory or one bound session, and exactly one")
        self.services = services
        self.parent_run_id = parent_run_id
        self._sessions = sessions
        self._session = session

    @asynccontextmanager
    async def _scope(self) -> AsyncGenerator[AsyncSession]:
        """Yield the session one call works in: the caller's, or one of this facade's own."""
        bound = self._session
        if bound is not None:
            yield bound
            return
        factory = self._sessions
        if factory is None:  # pragma: no cover - the constructor already refused this shape
            raise RuntimeError("EngineRuns has neither a bound session nor a session factory")
        async with session_scope(factory) as session:
            yield session

    async def start(
        self,
        pipeline: str,
        params: Mapping[str, JsonValue],
        *,
        max_depth: int,
    ) -> StartedRun:
        """Start a run of a named pipeline, attributed to the run whose step asked for it."""
        async with self._scope() as session:
            parent = await session.get(Run, self.parent_run_id)
            if parent is None:  # pragma: no cover - the calling run exists by construction
                raise RunRefused(f"run {self.parent_run_id} no longer exists")
            await self._refuse_a_bad_chain(session, parent, pipeline, max_depth)
            version = await self._current_version(session, pipeline)
            try:
                run = await create_run(
                    session,
                    self.services,
                    version,
                    params=dict(params),
                    attribution=Attribution(
                        kind=TriggerKind.PIPELINE,
                        id=parent.id,
                        label=f"a step of run {parent.id}",
                    ),
                    # A parent that waits on its child gains nothing from being urgent while
                    # the child queues behind everything, so the child inherits its priority.
                    priority=parent.priority,
                )
            except (RunCreationError, ParameterError) as error:
                raise RunRefused(f"a run of pipeline {pipeline!r} could not be started: {error}") from error
        if run is None:
            return StartedRun(pipeline=pipeline)
        return StartedRun(pipeline=pipeline, run_id=run.id, state=RunState(run.status.value))

    async def snapshot(self, run_id: UUID) -> RunSnapshot | None:
        """Describe a run this instance holds: where it is, and how much of it is done."""
        async with self._scope() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return None
            pipeline = await session.get(Pipeline, run.pipeline_id)
            rows = await session.execute(
                sa.select(StepAttempt.step_name, StepAttempt.run_item_id, StepAttempt.status).where(
                    StepAttempt.run_id == run_id
                )
            )
            units: dict[tuple[str, UUID | None], bool] = {}
            for step_name, run_item_id, status in rows:
                key = (step_name, run_item_id)
                units[key] = units.get(key, True) and status not in UNSETTLED_STATUSES
            return RunSnapshot(
                run_id=run.id,
                pipeline=pipeline.code if pipeline else "",
                state=RunState(run.status.value),
                total_steps=len(units),
                finished_steps=sum(1 for settled in units.values() if settled),
                error=run.error,
            )

    async def cancel(self, run_id: UUID, *, reason: str) -> bool:
        """Cancel a run; False means it had already settled and there was nothing to stop."""
        async with self._scope() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return False
            before = run.status
            await cancel_run(session, self.services, run, reason=reason)
            return before in ACTIVE_RUN_STATUSES

    async def _refuse_a_bad_chain(
        self,
        session: AsyncSession,
        parent: Run,
        pipeline: str,
        max_depth: int,
    ) -> None:
        """Refuse a step that would start a pipeline already in this chain, or one hop too many."""
        own = await session.get(Pipeline, parent.pipeline_id)
        if own is not None and own.code == pipeline:
            raise RunRefused(
                f"pipeline {pipeline!r} cannot start itself; a step that targets its own pipeline is a cycle, "
                f"not a loop"
            )
        depth, ancestry = await chain_ancestry(session, parent)
        target = await session.execute(sa.select(Pipeline.id).where(Pipeline.code == pipeline))
        target_id = target.scalar_one_or_none()
        if target_id is not None and target_id in ancestry:
            raise RunRefused(
                f"pipeline {pipeline!r} is already running further up this chain, so starting it here is a cycle"
            )
        if depth + 1 > max_depth:
            raise RunRefused(
                f"a run of pipeline {pipeline!r} would be {depth + 1} pipelines deep, and max_depth is {max_depth}"
            )

    async def _current_version(self, session: AsyncSession, code: str) -> PipelineVersion:
        """Read the version a started child pins, which is always the target's current one."""
        found = await session.execute(sa.select(Pipeline).where(Pipeline.code == code))
        pipeline = found.scalar_one_or_none()
        if pipeline is None:
            raise RunRefused(f"this instance has no pipeline coded {code!r}")
        if not pipeline.active:
            raise RunRefused(f"pipeline {code!r} is deactivated")
        if pipeline.current_version is None:
            raise RunRefused(f"pipeline {code!r} has no versions yet")
        rows = await session.execute(
            sa.select(PipelineVersion).where(
                PipelineVersion.pipeline_id == pipeline.id,
                PipelineVersion.version == pipeline.current_version,
            )
        )
        version = rows.scalar_one_or_none()
        if version is None:  # pragma: no cover - current_version always names a row
            raise RunRefused(f"pipeline {code!r} has no readable current version")
        return version


async def chain_ancestry(session: AsyncSession, run: Run) -> tuple[int, set[UUID]]:
    """Follow a run's attribution chain, returning its depth and every pipeline along it."""
    depth = 0
    ancestry: set[UUID] = {run.pipeline_id}
    current: Run | None = run
    while current is not None and depth < MAX_CHAIN_WALK:
        if current.triggered_by_kind is not TriggerKind.PIPELINE or current.triggered_by_id is None:
            break
        depth += 1
        current = await session.get(Run, current.triggered_by_id)
        if current is not None:
            ancestry.add(current.pipeline_id)
    return depth, ancestry


async def chain_depth(session: AsyncSession, run: Run) -> int:
    """Count how many pipelines deep a run already is, by following its attribution chain."""
    depth, _ = await chain_ancestry(session, run)
    return depth
