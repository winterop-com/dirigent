"""The scheduler: an asyncio loop that turns clock time into run rows.

Leadership is a PostgreSQL advisory lock, and each tick claims due schedules with ``FOR
UPDATE SKIP LOCKED``. SQLite has neither, so leadership there is a no-op and the guardrail
is that only the all-in-one standalone mode starts a scheduler at all.

Firing and advancing the clock commit together, so a crash can neither double-fire nor skip.
"""

import asyncio
import contextlib
import math
import signal
import time
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, FiringOutcome, RunStatus, TriggerKind
from dirigent_core import retention, telemetry
from dirigent_core.database import create_lock_engine, create_session_factory, session_scope
from dirigent_core.engine.definition import ConcurrencyPolicy, load_definition
from dirigent_core.engine.runs import Attribution, RunCreationError, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.logging import get_logger, log_context
from dirigent_core.models import Pipeline, PipelineVersion, Run, Schedule, ScheduleFiring, StepAttempt, utcnow
from dirigent_core.triggers.schedules import ScheduleError, advance_clock, window_for

#: How many due schedules one tick will fire before yielding.
MAX_PER_TICK = 100

_logger = get_logger("scheduler")


def is_postgres(session: AsyncSession) -> bool:
    """Report whether this session speaks PostgreSQL."""
    return session.get_bind().dialect.name == "postgresql"


async def try_lead(session: AsyncSession, key: int) -> bool:
    """Try to become the leader without blocking, so a replica can report and retry.

    ``pg_try_advisory_lock`` is session-scoped: the lock is held for as long as this
    connection lives, and PostgreSQL releases it when the connection dies.
    """
    if not is_postgres(session):
        return True
    held = await session.execute(sa.select(sa.func.pg_try_advisory_lock(key)))
    return bool(held.scalar_one())


async def release_lead(session: AsyncSession, key: int) -> None:
    """Give up leadership, so a graceful stop hands over immediately."""
    if not is_postgres(session):
        return
    await session.execute(sa.select(sa.func.pg_advisory_unlock(key)))


async def claim_due(session: AsyncSession, now: datetime, *, limit: int = MAX_PER_TICK) -> list[Schedule]:
    """Claim the schedules whose clock has come due, locking them against a second leader.

    The ``SKIP LOCKED`` is a second guard beyond leadership, so a moment of two leaders
    during a failover produces no double firing. PostgreSQL only; SQLite has no such clause.
    """
    statement = (
        sa.select(Schedule)
        .join(Pipeline, Pipeline.id == Schedule.pipeline_id)
        .where(
            Schedule.paused.is_(False),
            Schedule.next_fire_at.is_not(None),
            Schedule.next_fire_at <= now,
            Pipeline.active.is_(True),
        )
        .order_by(Schedule.next_fire_at)
        .limit(limit)
    )
    if is_postgres(session):
        statement = statement.with_for_update(skip_locked=True, of=Schedule)
    rows = await session.execute(statement)
    return list(rows.scalars())


class Fired(BaseModel):
    """What one schedule's firing amounted to."""

    model_config = ConfigDict(frozen=True)

    schedule: str
    outcome: FiringOutcome
    misfired: bool
    run_id: str | None = None
    detail: str | None = None
    next_fire_at: datetime | None = None


async def fire(
    session: AsyncSession,
    services: EngineServices,
    schedule: Schedule,
    *,
    now: datetime | None = None,
) -> Fired:
    """Fire one due schedule and advance its clock, in the caller's single transaction.

    The run, the firing row, and ``next_fire_at`` commit together, which is what makes a
    crash unable to double-fire or skip.
    """
    moment = now or utcnow()
    scheduled_for = schedule.next_fire_at or moment
    grace = services.settings.scheduler_misfire_grace
    advance = advance_clock(schedule, now=moment, grace=grace)

    outcome, run, detail = await _create(session, services, schedule, moment, scheduled_for)
    schedule.next_fire_at = advance.next_fire_at
    schedule.last_fired_at = moment
    if advance.exhausted:
        schedule.paused = True
    session.add(
        ScheduleFiring(
            schedule_id=schedule.id,
            run_id=run.id if run is not None else None,
            scheduled_for=scheduled_for,
            created_at=moment,
            outcome=outcome,
            misfired=advance.misfired,
            detail=detail,
        )
    )
    await session.flush()
    fired = Fired(
        schedule=schedule.code,
        outcome=outcome,
        misfired=advance.misfired,
        run_id=str(run.id) if run is not None else None,
        detail=detail,
        next_fire_at=advance.next_fire_at,
    )
    _logger.info(
        "schedule fired",
        schedule=schedule.code,
        outcome=outcome.value,
        misfired=advance.misfired,
        late_seconds=round(advance.lateness.total_seconds(), 1),
        run_id=fired.run_id,
        next_fire_at=advance.next_fire_at.isoformat() if advance.next_fire_at else None,
    )
    return fired


async def _create(
    session: AsyncSession,
    services: EngineServices,
    schedule: Schedule,
    moment: datetime,
    scheduled_for: datetime,
) -> tuple[FiringOutcome, Run | None, str | None]:
    """Create the run a firing owes, letting the pipeline's concurrency policy decide.

    The run's window is derived from the cadence and the firing's logical due time, not from
    the instant the tick happened to claim it, so a late firing still covers the slot it owed.
    """
    version = await _current_version(session, schedule)
    if version is None:
        return FiringOutcome.FAILED, None, "the pipeline has no current version to run"
    definition = load_definition(version.document)
    replacing = definition.concurrency is ConcurrencyPolicy.REPLACE and await _has_active(session, schedule.pipeline_id)
    try:
        run = await create_run(
            session,
            services,
            version,
            params=dict(schedule.params),
            attribution=Attribution(kind=TriggerKind.SCHEDULE, id=schedule.id, label=f"schedule {schedule.code}"),
            window=window_for(schedule, scheduled_for),
            log_levels=dict(schedule.log_levels) if schedule.log_levels else None,
            priority=schedule.priority,
            now=moment,
        )
    except (RunCreationError, ValueError) as error:
        return FiringOutcome.FAILED, None, str(error)
    if run is None:
        return FiringOutcome.SKIPPED, None, "a run of this pipeline is already in flight"
    if replacing:
        return FiringOutcome.REPLACED, run, "the run in flight was cancelled and replaced"
    if run.status is RunStatus.QUEUED and not await _has_started_attempts(session, run):
        return FiringOutcome.QUEUED, run, None
    return FiringOutcome.FIRED, run, None


async def _current_version(session: AsyncSession, schedule: Schedule) -> PipelineVersion | None:
    """Read the version a scheduled run pins, which is always the pipeline's current one."""
    pipeline = await session.get(Pipeline, schedule.pipeline_id)
    if pipeline is None or pipeline.current_version is None:
        return None
    found = await session.execute(
        sa.select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id,
            PipelineVersion.version == pipeline.current_version,
        )
    )
    return found.scalar_one_or_none()


async def _has_active(session: AsyncSession, pipeline_id: UUID) -> bool:
    """Report whether a pipeline already has a run occupying its concurrency slot."""
    found = await session.execute(
        sa.select(sa.func.count())
        .select_from(Run)
        .where(Run.pipeline_id == pipeline_id, Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)))
    )
    return int(found.scalar_one()) > 0


async def _has_started_attempts(session: AsyncSession, run: Run) -> bool:
    """Report whether a newly created run has anything claimable, which a held one does not."""
    found = await session.execute(
        sa.select(sa.func.count())
        .select_from(StepAttempt)
        .where(StepAttempt.run_id == run.id, StepAttempt.status != AttemptStatus.PENDING)
    )
    return int(found.scalar_one()) > 0


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    *,
    now: datetime | None = None,
) -> list[Fired]:
    """Run one scheduler tick: claim what is due, and fire each one in its own transaction.

    One transaction per schedule, so a bad document cannot roll back the firings beside it.
    """
    moment = now or utcnow()
    async with session_scope(sessions) as session:
        claimed = await claim_due(session, moment)
        due = [schedule.id for schedule in claimed]
        oldest = claimed[0].next_fire_at if claimed else None
    telemetry.gauges.observe(scheduler_lag=max((moment - oldest).total_seconds(), 0.0) if oldest else 0.0)
    fired: list[Fired] = []
    for schedule_id in due:
        async with session_scope(sessions) as session:
            schedule = await _claim_one(session, schedule_id, moment)
            if schedule is None:
                continue
            try:
                fired.append(await fire(session, services, schedule, now=moment))
            except ScheduleError as error:
                schedule.paused = True
                session.add(
                    ScheduleFiring(
                        schedule_id=schedule.id,
                        scheduled_for=schedule.next_fire_at or moment,
                        created_at=moment,
                        outcome=FiringOutcome.FAILED,
                        detail=f"{error}; the schedule is paused until it is corrected",
                    )
                )
                _logger.error("schedule paused after a clock error", schedule=schedule.code, error=str(error))
    return fired


async def _claim_one(session: AsyncSession, schedule_id: UUID, now: datetime) -> Schedule | None:
    """Re-read and lock one schedule, confirming it is still due before it is fired.

    The listing in :func:`tick` is advisory; only this row lock decides that this process,
    and no other, owes the firing.
    """
    statement = sa.select(Schedule).where(Schedule.id == schedule_id)
    if is_postgres(session):
        statement = statement.with_for_update(skip_locked=True)
    found = await session.execute(statement)
    schedule = found.scalar_one_or_none()
    if schedule is None or schedule.paused or schedule.next_fire_at is None or schedule.next_fire_at > now:
        return None
    return schedule


async def prune(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    policy: retention.Policy | None = None,
    *,
    now: datetime | None = None,
    max_batches: int = 200,
) -> retention.Swept:
    """Sweep until nothing is left to delete, one committed batch at a time.

    A batch is bounded so no single transaction holds locks over a year's backlog, and the
    number of batches is bounded too: a sweep that would never finish yields to the next one
    rather than running forever.
    """
    chosen = policy if policy is not None else retention.policy_from(services.settings)
    limit = services.settings.retention_batch
    total = retention.Swept()
    for _ in range(max_batches):
        async with session_scope(sessions) as session:
            swept = await retention.sweep(session, chosen, storage=services.storage, now=now, limit=limit)
        for family, count in swept.counts.items():
            total.record(family, count)
        total.scratch_deleted += swept.scratch_deleted
        total.scratch_failed += swept.scratch_failed
        if not swept.total:
            break
    return total


class Scheduler:
    """One scheduler process: take leadership, then tick until asked to stop."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        services: EngineServices,
        *,
        tick_seconds: float | None = None,
        lock_sessions: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Bind the scheduler to the database and the services every engine path shares.

        The lock session comes from its own engine unless a caller supplies one: the advisory
        lock is held for the process's lifetime, so taking it from the request pool would
        permanently consume one of the connections the server answers requests with.
        """
        self.sessions = sessions
        self.services = services
        self.tick_seconds = tick_seconds or services.settings.scheduler_tick.total_seconds()
        self.key = services.settings.scheduler_lock_key
        self.leading = False
        self._stopping = asyncio.Event()
        self._lock_session: AsyncSession | None = None
        # Never pruned yet, so the first sweep is due as soon as leadership is taken.
        self._pruned_at = -math.inf
        self._lock_sessions = lock_sessions
        self._lock_engine: AsyncEngine | None = None

    def _lock_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory the lock connection comes from, building one if needed.

        SQLite has no advisory lock to hold, and a second engine on an in-memory SQLite URL
        would be a second database entirely, so the dedicated engine is PostgreSQL-only.
        """
        if self._lock_sessions is None:
            if self.services.settings.is_sqlite:
                self._lock_sessions = self.sessions
            else:
                self._lock_engine = create_lock_engine(self.services.settings)
                self._lock_sessions = create_session_factory(self._lock_engine)
        return self._lock_sessions

    @property
    def stopping(self) -> bool:
        """Report whether the scheduler has been asked to stop."""
        return self._stopping.is_set()

    def request_stop(self) -> None:
        """Ask the loop to finish the tick it is in and then exit."""
        if not self._stopping.is_set():
            _logger.info("scheduler stopping")
            self._stopping.set()

    async def run(self) -> None:
        """Block until this process is the leader, then tick until it is asked to stop."""
        with log_context(role="scheduler"):
            try:
                await self._acquire()
                if self.stopping:
                    return
                _logger.info("scheduler leading", tick_seconds=self.tick_seconds, key=self.key)
                await self._loop()
            finally:
                await self._release()

    async def _acquire(self) -> None:
        """Wait for leadership, reporting once that it is held elsewhere."""
        session = self._lock_factory()()
        self._lock_session = session
        announced = False
        while not self.stopping:
            if await try_lead(session, self.key):
                self.leading = True
                return
            if not announced:
                _logger.info("another scheduler is the leader; standing by", key=self.key)
                announced = True
            await self._wait(self.tick_seconds)

    async def _release(self) -> None:
        """Give leadership back and close the session holding it."""
        session, self._lock_session = self._lock_session, None
        if session is None:
            return
        try:
            if self.leading:
                await release_lead(session, self.key)
                await session.commit()
        finally:
            self.leading = False
            await session.close()
            engine, self._lock_engine = self._lock_engine, None
            if engine is not None:
                await engine.dispose()
            _logger.info("scheduler stopped")

    async def _loop(self) -> None:
        """Tick on a fixed cadence until asked to stop."""
        while not self.stopping:
            if not await self._still_leading():
                await self._reacquire()
                continue
            try:
                await tick(self.sessions, self.services)
            except Exception as error:  # a transient database failure must not end the process
                _logger.error("scheduler tick failed", error=str(error))
            await self._prune_if_due()
            await self._wait(self.tick_seconds)

    async def _prune_if_due(self) -> None:
        """Sweep whatever the retention ages have outlived, on its own much slower clock.

        It runs here rather than on a worker because the leader is the one process there is
        exactly one of: every worker sweeping would have them deleting each other's batches.
        """
        policy = retention.policy_from(self.services.settings)
        if not retention.configured(policy):
            return
        interval = self.services.settings.retention_interval.total_seconds()
        moment = time.monotonic()
        if moment - self._pruned_at < interval:
            return
        self._pruned_at = moment
        try:
            swept = await prune(self.sessions, self.services, policy)
        except Exception as error:  # a prune that fails is retried next time it is due
            _logger.error("retention sweep failed", error=str(error))
            return
        if swept.total or swept.scratch_deleted:
            _logger.info(
                "retention swept",
                rows=swept.total,
                artifacts=swept.scratch_deleted,
                **swept.counts,
            )

    async def _still_leading(self) -> bool:
        """Confirm the connection holding the lock is still there, before firing anything.

        The only way to stop being the leader unknowingly is for the lock connection to die,
        at which point PostgreSQL releases the lock and another process takes it. A statement
        on that session is what turns ``self.leading`` from a startup flag back into a fact.
        """
        session = self._lock_session
        if session is None:  # pragma: no cover - _acquire always sets one
            return False
        if not is_postgres(session):
            return True
        try:
            await session.execute(sa.select(sa.literal(1)))
        except Exception as error:
            _logger.warning("the connection holding leadership is gone", error=str(error))
            return False
        return True

    async def _reacquire(self) -> None:
        """Drop the dead lock session and queue up for leadership again."""
        self.leading = False
        session, self._lock_session = self._lock_session, None
        if session is not None:
            with contextlib.suppress(Exception):
                await session.close()
        await self._acquire()
        if self.leading:
            _logger.info("scheduler leading again", key=self.key)

    async def _wait(self, seconds: float) -> None:
        """Sleep between ticks, returning early when asked to stop."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)


def install_signal_handlers(scheduler: Scheduler) -> None:
    """Ask the scheduler to stop on SIGTERM and SIGINT."""
    loop = asyncio.get_running_loop()
    for received in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(received, scheduler.request_stop)
        except NotImplementedError:  # pragma: no cover - only on platforms without loop signals
            signal.signal(received, lambda _signal, _frame: scheduler.request_stop())
