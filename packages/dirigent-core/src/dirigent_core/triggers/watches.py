"""Watches: a sensor step made a continuous source, one waiting run at a time.

A watch keeps exactly one run of its pipeline waiting on one root sensor step. The
transaction that settles that step's success stores where the poke left off and arms the
next run, so runs overlap by design: the one that succeeded carries on downstream while the
next one waits. A wait that ends any other way -- the step failed after its own retries, or
the run was cancelled -- arms again after a backoff, from the cursor the last success stored.

Every write to a watch row happens under the pipeline's lock, taken before any run's.
"""

from collections.abc import Container
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus, TriggerKind
from dirigent_client.schemas import ValidationIssue
from dirigent_common import EntityName, Issue, JsonMap, Message, StepName
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, WatchSpec, load_definition
from dirigent_core.engine.runs import ACTIVE_RUN_STATUSES, Attribution, cancel_run, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.errors import DomainError
from dirigent_core.ids import uuid7
from dirigent_core.logging import get_logger
from dirigent_core.messages import (
    DUPLICATE_WATCH,
    UNKNOWN_WATCH,
    WATCH_ARM_REFUSED,
    WATCH_FANS_OUT,
    WATCH_MOVED,
    WATCH_NOT_A_ROOT,
    WATCH_NOT_A_SENSOR,
    WATCH_PAUSED,
    WATCH_PIPELINE_REAPPLIED,
    WATCH_REPLACE_POLICY,
    WATCH_RETIRED,
    WATCH_RUN_GONE,
    WATCH_UNARMABLE,
    WATCH_UNKNOWN_STEP,
    WATCH_WAIT_CANCELLED,
    WATCH_WAIT_FAILED,
    WATCH_WOULD_BREAK,
)
from dirigent_core.models import Pipeline, PipelineVersion, Run, StepAttempt, TriggerDocument, Watch, utcnow

_logger = get_logger("watches")

#: How many doublings the backoff takes before the cap is all that is left of it.
MAX_BACKOFF_DOUBLINGS: Final = 30


class WatchError(DomainError):
    """A watch could not be declared or found."""


class DuplicateWatch(WatchError):
    """A pipeline already has a watch of that code."""

    status = 409
    message = DUPLICATE_WATCH

    def __init__(self, pipeline: str, code: str) -> None:
        """Name the pipeline and the watch."""
        super().__init__(pipeline=repr(pipeline), code=repr(code))


class UnknownWatch(WatchError):
    """No watch of that code exists on this pipeline."""

    status = 404
    message = UNKNOWN_WATCH

    def __init__(self, pipeline: str, code: str) -> None:
        """Name the pipeline and the watch."""
        super().__init__(pipeline=repr(pipeline), code=repr(code))


class WatchRequest(BaseModel):
    """What it takes to declare a watch, which a document's ``triggers:`` section carries."""

    model_config = ConfigDict(frozen=True)

    code: EntityName
    name: str | None = None
    description: str | None = None
    step: StepName
    params: JsonMap = Field(default_factory=dict)

    @classmethod
    def from_spec(cls, spec: WatchSpec) -> "WatchRequest":
        """Read a document's watch declaration as a request."""
        return cls(
            code=spec.code,
            name=spec.name,
            description=spec.description,
            step=spec.step,
            params=dict(spec.params),
        )


class Armed(BaseModel):
    """What one tick did for one watch."""

    model_config = ConfigDict(frozen=True)

    watch: str
    run_id: UUID


def watch_issue(
    code: str,
    step_name: str,
    definition: PipelineDefinition,
    sensors: Container[str] | None,
) -> Issue | None:
    """Say why a step cannot be watched, or nothing when it can.

    A watched step is a root sensor that does not fan out, on a pipeline whose concurrency
    is not ``replace``. ``sensors`` unset leaves the block unchecked.
    """
    if definition.concurrency is ConcurrencyPolicy.REPLACE:
        return Issue.of(WATCH_REPLACE_POLICY, code=repr(code))
    step = definition.steps.get(step_name)
    if step is None:
        return Issue.of(
            WATCH_UNKNOWN_STEP, code=repr(code), step=repr(step_name), available=", ".join(sorted(definition.steps))
        )
    if step.depends_on:
        return Issue.of(WATCH_NOT_A_ROOT, code=repr(code), step=repr(step_name), depends=", ".join(step.depends_on))
    if step.is_fan_out:
        return Issue.of(WATCH_FANS_OUT, code=repr(code), step=repr(step_name))
    if sensors is not None and step.block not in sensors:
        return Issue.of(WATCH_NOT_A_SENSOR, code=repr(code), step=repr(step_name), block=repr(step.block))
    return None


def backoff_for(failures: int, settings: Settings) -> timedelta:
    """How long a watch waits before arming again, after this many waits in a row failed."""
    if failures <= 0:
        return timedelta(0)
    doubled = settings.watch_backoff * float(2 ** min(failures - 1, MAX_BACKOFF_DOUBLINGS))
    return min(doubled, settings.watch_backoff_max)


async def find_watch(session: AsyncSession, pipeline_id: UUID, code: str) -> Watch | None:
    """Find one watch by code within its pipeline."""
    found = await session.execute(sa.select(Watch).where(Watch.pipeline_id == pipeline_id, Watch.code == code))
    return found.scalar_one_or_none()


async def list_watches(
    session: AsyncSession,
    pipeline_id: UUID | None = None,
    *,
    after: str | None = None,
    limit: int | None = None,
) -> list[Watch]:
    """List watches in code order, for one pipeline or across the instance."""
    statement = sa.select(Watch).order_by(Watch.pipeline_id, Watch.code)
    if pipeline_id is not None:
        statement = statement.where(Watch.pipeline_id == pipeline_id)
    if after is not None:
        statement = statement.where(Watch.code > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def create_watch(
    session: AsyncSession,
    services: EngineServices,
    pipeline: Pipeline,
    request: WatchRequest,
    *,
    paused: bool = False,
    now: datetime | None = None,
) -> Watch:
    """Declare a watch on a pipeline and, unless it is created paused, arm its first run."""
    if await find_watch(session, pipeline.id, request.code) is not None:
        raise DuplicateWatch(pipeline.code, request.code)
    watch = Watch(
        pipeline_id=pipeline.id,
        code=request.code,
        name=request.name,
        description=request.description,
        step=request.step,
        params=dict(request.params),
        paused=paused,
    )
    session.add(watch)
    await session.flush()
    _logger.info("watch created", pipeline=pipeline.code, watch=watch.code, step=watch.step, paused=paused)
    if not paused:
        await arm(session, services, watch, now=now)
    return watch


async def update_watch(
    session: AsyncSession,
    services: EngineServices,
    watch: Watch,
    request: WatchRequest,
    *,
    now: datetime | None = None,
) -> Watch:
    """Redeclare a watch, keeping whether it is paused.

    Moving it to another step cancels the run it has waiting, drops its cursor, and arms
    afresh on the new step.
    """
    moved = watch.step != request.step
    watch.name = request.name
    watch.description = request.description
    watch.step = request.step
    watch.params = dict(request.params)
    await session.flush()
    if moved:
        watch.cursor = None
        await _withdraw(session, services, watch, reason=WATCH_MOVED, now=now)
        if not watch.paused:
            await arm(session, services, watch, now=now)
    _logger.info("watch updated", watch=watch.code, step=watch.step, moved=moved)
    return watch


async def delete_watch(
    session: AsyncSession, services: EngineServices, watch: Watch, *, now: datetime | None = None
) -> None:
    """Remove a watch, cancelling the run it has waiting."""
    code = watch.code
    await _withdraw(session, services, watch, reason=WATCH_RETIRED, now=now)
    await session.delete(watch)
    await session.flush()
    _logger.info("watch deleted", watch=code)


async def set_paused(
    session: AsyncSession,
    services: EngineServices,
    watch: Watch,
    *,
    paused: bool,
    now: datetime | None = None,
) -> Watch:
    """Pause a watch, cancelling the run it has waiting, or resume it and arm one.

    The cursor survives both, so a resumed watch reads on from where its last success left
    off. Resuming clears the failure count and any backoff.
    """
    await session.flush()
    await lock_pipeline(session, watch.pipeline_id)
    await session.refresh(watch)
    watch.paused = paused
    if paused:
        await _withdraw(session, services, watch, reason=WATCH_PAUSED, now=now)
    else:
        watch.rearm_at = None
        watch.failures = 0
        await session.flush()
        await arm(session, services, watch, now=now)
    await session.flush()
    _logger.info("watch paused" if paused else "watch resumed", watch=watch.code)
    return watch


async def _withdraw(
    session: AsyncSession, services: EngineServices, watch: Watch, *, reason: Message, now: datetime | None
) -> None:
    """Take away the run a watch has waiting, and cancel it if it is still in flight.

    The pointer is read under the pipeline's lock, which every settlement also holds, and
    cleared before the cancel, so the cancel's own settlement does not read as a wait that
    failed.
    """
    await session.flush()
    await lock_pipeline(session, watch.pipeline_id)
    await session.refresh(watch)
    run_id = watch.waiting_run_id
    watch.waiting_run_id = None
    await session.flush()
    if run_id is None:
        return
    run = await session.get(Run, run_id)
    if run is not None and run.status in ACTIVE_RUN_STATUSES:
        await cancel_run(session, services, run, reason, now=now)


class _Skipped(Exception):
    """The pipeline's concurrency policy created no run, so the claim is given back."""


async def arm(
    session: AsyncSession,
    services: EngineServices,
    watch: Watch,
    *,
    now: datetime | None = None,
) -> Run | None:
    """Create the run a watch has waiting, seeded with its cursor, unless it already has one.

    The claim is one conditional update that moves ``waiting_run_id`` from null to the id
    the run is about to be written under, so of two armers only one can win, whichever
    database they race on. The run is created through ``create_run``, under the pipeline's
    concurrency policy and parameter schema.

    Returns None when nothing was armed: the watch is paused, already has a run waiting, its
    pipeline cannot be run, or the run was refused, which is recorded on the watch.
    """
    moment = now or utcnow()
    await lock_pipeline(session, watch.pipeline_id)
    await session.flush()
    await session.refresh(watch)
    if watch.paused or watch.waiting_run_id is not None:
        return None
    version = await _current_version(session, watch.pipeline_id)
    if version is None:
        return None
    definition = load_definition(version.document)
    refusal = watch_issue(watch.code, watch.step, definition, services.host.sensors)
    if refusal is not None:
        _failed(
            watch,
            WATCH_UNARMABLE.render(code=repr(watch.code), version=version.version, detail=refusal.message),
            moment,
            services.settings,
        )
        await session.flush()
        return None
    run_id = uuid7()
    try:
        async with session.begin_nested():
            claimed = await session.execute(
                sa.update(Watch)
                .where(Watch.id == watch.id, Watch.waiting_run_id.is_(None), Watch.paused.is_(False))
                .values(waiting_run_id=run_id, last_armed_at=moment, rearm_at=None)
                .returning(Watch.id)
            )
            if claimed.scalar_one_or_none() is None:
                return None
            run = await create_run(
                session,
                services,
                version,
                params=dict(watch.params),
                attribution=Attribution(kind=TriggerKind.WATCH, id=watch.id, label=f"watch {watch.code}"),
                cursors={watch.step: watch.cursor} if watch.cursor is not None else None,
                run_id=run_id,
                now=moment,
            )
            if run is None:
                raise _Skipped
    except _Skipped:
        await session.refresh(watch)
        watch.rearm_at = moment + services.settings.watch_backoff
        await session.flush()
        _logger.info("watch not armed: the concurrency policy skipped its run", watch=watch.code)
        return None
    except (DomainError, ValueError) as error:
        await session.refresh(watch)
        _failed(watch, WATCH_ARM_REFUSED.render(detail=str(error)), moment, services.settings)
        await session.flush()
        return None
    await session.refresh(watch)
    _logger.info("watch armed", watch=watch.code, run_id=str(run.id), cursor=watch.cursor is not None)
    return run


async def _current_version(session: AsyncSession, pipeline_id: UUID) -> PipelineVersion | None:
    """Read the version an armed run pins, or None when the pipeline cannot be run."""
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None or not pipeline.active or pipeline.current_version is None:
        return None
    found = await session.execute(
        sa.select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id,
            PipelineVersion.version == pipeline.current_version,
        )
    )
    return found.scalar_one_or_none()


def _failed(watch: Watch, error: str, moment: datetime, settings: Settings) -> None:
    """Record a wait that ended without the sensor succeeding, and when to try again."""
    watch.waiting_run_id = None
    watch.failures += 1
    watch.last_error = error
    watch.last_error_at = moment
    watch.rearm_at = moment + backoff_for(watch.failures, settings)
    _logger.warning("watch backing off", watch=watch.code, failures=watch.failures, error=error)


async def _watch_of(session: AsyncSession, run: Run) -> Watch | None:
    """Find the watch a run is the waiting run of, or None when it is not one.

    The first read takes no lock and is trusted only to say no: a run is made the waiting run
    in the transaction that creates it, before any of its attempts can settle.
    """
    if run.triggered_by_kind is not TriggerKind.WATCH or run.triggered_by_id is None:
        return None
    watch = await session.get(Watch, run.triggered_by_id)
    if watch is None or watch.waiting_run_id != run.id:
        return None
    await lock_pipeline(session, run.pipeline_id)
    await session.refresh(watch)
    return watch if watch.waiting_run_id == run.id else None


async def rearm_after_success(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    attempt: StepAttempt,
    *,
    now: datetime | None = None,
) -> Run | None:
    """Store where the watched step's success left off, and arm the next run from there.

    Called by the transaction that settles the attempt, so the cursor, the success and the
    next run commit together: a crash can neither lose the batch's place nor arm twice.
    """
    if attempt.run_item_id is not None:
        return None
    watch = await _watch_of(session, run)
    if watch is None or attempt.step_name != watch.step:
        return None
    watch.cursor = dict(attempt.poke_cursor) if attempt.poke_cursor is not None else None
    watch.failures = 0
    watch.last_error = None
    watch.last_error_at = None
    watch.waiting_run_id = None
    await session.flush()
    return await arm(session, services, watch, now=now)


async def note_settled(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    *,
    now: datetime | None = None,
) -> None:
    """End the wait of a watch whose waiting run settled without its sensor succeeding."""
    watch = await _watch_of(session, run)
    if watch is None:
        return
    await _end_wait(session, services, watch, run, now or utcnow())


async def _end_wait(
    session: AsyncSession, services: EngineServices, watch: Watch, run: Run | None, moment: datetime
) -> Run | None:
    """Decide what a wait that ended amounts to, and arm again now or after a backoff.

    A sensor that ran out its deadline under ``on_timeout: skip`` found nothing, which is not
    a failure: the watch arms again straight away. A failure or a cancel backs off.
    """
    watched = await _watched_attempt(session, run.id, watch.step) if run is not None else None
    if run is None:
        _failed(watch, WATCH_RUN_GONE.render(run=watch.waiting_run_id), moment, services.settings)
    elif watched is not None and watched.status is AttemptStatus.SUCCEEDED:
        watch.cursor = dict(watched.poke_cursor) if watched.poke_cursor is not None else None
        watch.failures = 0
        watch.last_error = None
        watch.last_error_at = None
        watch.waiting_run_id = None
    elif run.status is RunStatus.CANCELLED:
        _failed(
            watch,
            WATCH_WAIT_CANCELLED.render(run=run.id, reason=run.error or "cancelled"),
            moment,
            services.settings,
        )
    elif watched is not None and watched.status is AttemptStatus.SKIPPED:
        watch.waiting_run_id = None
        watch.rearm_at = None
        watch.failures = 0
    else:
        detail = (watched.error if watched is not None else None) or run.error or run.status.value
        _failed(
            watch,
            WATCH_WAIT_FAILED.render(step=repr(watch.step), run=run.id, detail=detail),
            moment,
            services.settings,
        )
    await session.flush()
    if watch.rearm_at is not None:
        return None
    return await arm(session, services, watch, now=moment)


async def _watched_attempt(session: AsyncSession, run_id: UUID, step: str) -> StepAttempt | None:
    """Read the newest attempt of the watched step in one run."""
    found = await session.execute(
        sa.select(StepAttempt)
        .where(StepAttempt.run_id == run_id, StepAttempt.step_name == step, StepAttempt.run_item_id.is_(None))
        .order_by(StepAttempt.attempt.desc())
        .limit(1)
    )
    return found.scalar_one_or_none()


async def follow_version(
    session: AsyncSession, services: EngineServices, pipeline_id: UUID, *, now: datetime | None = None
) -> list[Run]:
    """Move every live watch of a pipeline onto its current version.

    A waiting run pins the version it was created from, so one armed before an apply is
    cancelled and armed again from the same cursor. A run whose watched step already succeeded
    is no longer the waiting run, and is left to carry on.
    """
    await lock_pipeline(session, pipeline_id)
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None or pipeline.current_version is None:
        return []
    current = await _current_version(session, pipeline_id)
    armed: list[Run] = []
    for watch in await list_watches(session, pipeline_id):
        await session.refresh(watch)
        if watch.paused or watch.waiting_run_id is None:
            continue
        waiting = await session.get(Run, watch.waiting_run_id)
        if waiting is None or current is None or waiting.pipeline_version_id == current.id:
            continue
        await _withdraw(session, services, watch, reason=WATCH_PIPELINE_REAPPLIED, now=now)
        run = await arm(session, services, watch, now=now)
        if run is not None:
            armed.append(run)
    return armed


async def withdraw_all(
    session: AsyncSession, services: EngineServices, pipeline_id: UUID, *, reason: Message, now: datetime | None = None
) -> None:
    """Cancel the run every watch of a pipeline has waiting, leaving each watch as it is."""
    await lock_pipeline(session, pipeline_id)
    for watch in await list_watches(session, pipeline_id):
        await _withdraw(session, services, watch, reason=reason, now=now)


async def arm_all(
    session: AsyncSession, services: EngineServices, pipeline_id: UUID, *, now: datetime | None = None
) -> list[Run]:
    """Arm every unpaused watch of a pipeline that has no run waiting."""
    await lock_pipeline(session, pipeline_id)
    armed: list[Run] = []
    for watch in await list_watches(session, pipeline_id):
        run = await arm(session, services, watch, now=now)
        if run is not None:
            armed.append(run)
    return armed


async def held_watch_issues(
    session: AsyncSession,
    pipeline: Pipeline,
    definition: PipelineDefinition,
    sensors: Container[str] | None,
) -> list[ValidationIssue]:
    """Refuse a pipeline version that a watch another document declares could not wait on."""
    rows = await session.execute(
        sa.select(Watch, TriggerDocument.code)
        .join(TriggerDocument, TriggerDocument.id == Watch.trigger_document_id)
        .where(Watch.pipeline_id == pipeline.id)
        .order_by(Watch.code)
    )
    issues: list[ValidationIssue] = []
    for watch, owner in rows.all():
        refusal = watch_issue(watch.code, watch.step, definition, sensors)
        if refusal is None:
            continue
        issues.append(
            ValidationIssue.of(
                WATCH_WOULD_BREAK,
                location="steps",
                code=repr(watch.code),
                owner=f"the triggers document {owner!r}",
                detail=refusal.message,
            )
        )
    return issues


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    *,
    now: datetime | None = None,
) -> list[Armed]:
    """Arm every live watch that has no run waiting and is not backing off.

    This is what arms a watch on a server's start, after a backoff runs out, and after a
    settlement nothing reported: a waiting run that has settled or gone is read as the end of
    its wait here. One transaction per watch, so one that cannot arm holds up none of the rest.
    """
    moment = now or utcnow()
    async with session_scope(sessions) as session:
        rows = await session.execute(
            sa.select(Watch.id)
            .join(Pipeline, Pipeline.id == Watch.pipeline_id)
            .where(Watch.paused.is_(False), Pipeline.active.is_(True))
            .order_by(Watch.id)
        )
        live = list(rows.scalars())
    armed: list[Armed] = []
    for watch_id in live:
        async with session_scope(sessions) as session:
            tended = await _tend(session, services, watch_id, moment)
            if tended is not None:
                armed.append(tended)
    return armed


async def _tend(session: AsyncSession, services: EngineServices, watch_id: UUID, moment: datetime) -> Armed | None:
    """Bring one watch back to one waiting run, if it has none and is due one."""
    watch = await session.get(Watch, watch_id)
    if watch is None:
        return None
    await lock_pipeline(session, watch.pipeline_id)
    await session.refresh(watch)
    if watch.paused:
        return None
    if watch.waiting_run_id is not None:
        waiting = await session.get(Run, watch.waiting_run_id)
        if waiting is not None and waiting.status in ACTIVE_RUN_STATUSES:
            return None
        run = await _end_wait(session, services, watch, waiting, moment)
    elif watch.rearm_at is not None and watch.rearm_at > moment:
        return None
    else:
        run = await arm(session, services, watch, now=moment)
    return None if run is None else Armed(watch=watch.code, run_id=run.id)
