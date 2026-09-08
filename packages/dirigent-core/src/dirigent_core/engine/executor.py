"""The engine proper: claim, call one block, record the outcome, ready the dependents.

Two invariants carry everything here. One transaction per state transition, so there is no
window in which a step is finished but its dependents have not been told. And a remote
handle is committed on its own the moment ``execute`` returns it, so submit-then-crash
recovers into polling rather than into a duplicate job.
"""

import asyncio
import contextlib
import time
from collections.abc import Coroutine, Generator, Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptKind, AttemptStatus, LogLevel, RunStatus
from dirigent_common import JsonMap, format_duration
from dirigent_core import telemetry
from dirigent_core.artifacts import persist_output
from dirigent_core.database import session_scope, with_deadlock_retry
from dirigent_core.engine.claim import (
    MAX_SETTLED_PER_CLAIM,
    ClaimedUnit,
    is_postgres,
    select_due,
)
from dirigent_core.engine.context import (
    BufferedLogger,
    EngineStepContext,
    LogRow,
    kept_level,
    load_connections,
    load_schemas,
)
from dirigent_core.engine.definition import (
    PipelineDefinition,
    StepDefinition,
    TimeoutAction,
    load_definition,
)
from dirigent_core.engine.failure import Failure, backoff_delay, should_retry
from dirigent_core.engine.recovery import overdue_deadlines
from dirigent_core.engine.references import ReferenceScope, UnknownReference, references_in, resolve_config
from dirigent_core.engine.runs import (
    ACTIVE_RUN_STATUSES,
    EngineRuns,
    cancel_remote,
    item_value_of,
    promote_queued_run,
)
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import advance, lock_run
from dirigent_core.logging import get_logger, log_context
from dirigent_core.models import LogEntry, PipelineVersion, Run, RunItem, StepAttempt, utcnow
from dirigent_core.storage import AttemptStorage, scratch_prefix
from dirigent_plugin import AnyOperator, AnySensor, ErrorClass, NotYet, ProbeStatus, RemoteHandle, shell_string_fields

DEFAULT_PROBE_INTERVAL = timedelta(seconds=30)

#: The statuses that free a pipeline's concurrency slot and settle what the run owes.
TERMINAL_RUN_STATUSES = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.COMPLETED_WITH_ERRORS)

FIRST_PROBE_INTERVAL = timedelta(seconds=1)

MAX_PROBE_DOUBLINGS = 20

#: Serialises claims on SQLite, which has no SKIP LOCKED to do it in the database.
SQLITE_CLAIM_LOCK = asyncio.Lock()

_logger = get_logger("engine")


class Produced(BaseModel):
    """The block finished and produced its output."""

    model_config = ConfigDict(frozen=True)

    output: JsonMap


class Submitted(BaseModel):
    """The operator handed over a claim on work that continues elsewhere."""

    model_config = ConfigDict(frozen=True)

    handle: RemoteHandle
    next_poll_in: timedelta | None = None


class Waiting(BaseModel):
    """The condition does not hold yet, or the remote is still working."""

    model_config = ConfigDict(frozen=True)

    next_poll_in: timedelta | None = None
    message: str | None = None
    progress: float | None = None
    handle: RemoteHandle | None = None
    """The handle the probe advanced, to be stored with the park; None leaves it as it was."""

    cursor: JsonMap | None = None
    """The cursor the poke advanced, to be stored with the park; None leaves it as it was."""


class Vanished(BaseModel):
    """The remote no longer knows the job, which the lost-job policy counts."""

    model_config = ConfigDict(frozen=True)

    message: str


class Errored(BaseModel):
    """The block failed, already classified."""

    model_config = ConfigDict(frozen=True)

    failure: Failure


type CallResult = Produced | Submitted | Waiting | Vanished | Errored


class Engine:
    """One process's view of the engine: claim a unit, run it, record what happened."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        services: EngineServices,
        *,
        owner: str,
        tags: Sequence[str] = (),
    ) -> None:
        """Bind the engine to a session factory, the shared services, a lease owner, and its tags."""
        self.sessions = session_factory
        self.services = services
        self.owner = owner
        self.tags = list(tags)
        """The capability tags this process carries, which the claim routes on."""

    # -- claiming ----------------------------------------------------------------

    async def claim(self, *, now: datetime | None = None) -> ClaimedUnit | None:
        """Claim the next due unit of work, settling anything unclaimable on the way."""
        async with self.sessions() as probe_session:
            postgres = is_postgres(probe_session)
        if postgres:
            return await with_deadlock_retry(lambda: self._claim_once(now))
        async with SQLITE_CLAIM_LOCK:
            return await self._claim_once(now)

    async def _claim_once(self, now: datetime | None) -> ClaimedUnit | None:
        """Run one claim transaction: take a lease, or settle rows that cannot be run."""
        moment = now or utcnow()
        async with session_scope(self.sessions) as session:
            for _ in range(MAX_SETTLED_PER_CLAIM):
                attempt = await select_due(session, moment, self.tags)
                if attempt is None:
                    return None
                unit = await self._prepare(session, attempt, moment)
                if unit is not None:
                    _logger.debug(
                        "attempt claimed",
                        worker=self.owner,
                        step=unit.step_name,
                        block=unit.block_id,
                        attempt=unit.attempt_number,
                        from_status=unit.previous_status.value,
                        lease_expires_at=attempt.lease_expires_at.isoformat() if attempt.lease_expires_at else None,
                    )
                    return unit
        return None

    async def _prepare(self, session: AsyncSession, attempt: StepAttempt, now: datetime) -> ClaimedUnit | None:
        """Take the lease and resolve the step, or settle the attempt and step over it."""
        run = await session.get(Run, attempt.run_id)
        if run is None:  # pragma: no cover - the foreign key makes this unreachable
            return None
        await lock_run(session, run.id)
        version = await session.get(PipelineVersion, run.pipeline_version_id)
        if version is None:  # pragma: no cover - the foreign key makes this unreachable
            return None
        definition = load_definition(version.document)
        step = definition.steps.get(attempt.step_name)
        if step is None:
            await self._settle_and_advance(
                session,
                run,
                definition,
                attempt,
                Failure.rejected(f"step {attempt.step_name!r} is not in the pinned pipeline version"),
                now,
            )
            return None

        if attempt.deadline_at is not None and attempt.deadline_at <= now:
            await self._settle_deadline(session, run, definition, attempt, step, now)
            return None

        refusal = self.services.local_execution_refusal(attempt.block_id)
        if refusal is not None:
            await self._settle_and_advance(session, run, definition, attempt, refusal, now)
            return None

        item = await session.get(RunItem, attempt.run_item_id) if attempt.run_item_id else None
        item_value, has_item = item_value_of(item)
        scratch = scratch_prefix(self.services.settings.artifact_root, run.id)
        scope = ReferenceScope(
            params=dict(run.params),
            outputs=await collect_outputs(session, run.id, definition),
            item=item_value,
            has_item=has_item,
            scratch=scratch,
            run_id=run.id,
            window_start=run.window_start,
            window_end=run.window_end,
        )
        try:
            block = self.services.block(attempt.block_id)
            config = resolve_config(step.config, scope, shell_fields=shell_string_fields(block.config_model))
            block.config_model.model_validate(config)
            _logger.debug(
                "references resolved",
                step=attempt.step_name,
                reads=sorted(set(references_in(cast("JsonValue", step.config)))),
                upstream=sorted(scope.outputs),
                item=item_value if has_item else None,
            )
        except (UnknownReference, ValidationError) as error:
            await self._settle_and_advance(session, run, definition, attempt, Failure.rejected(str(error)), now)
            return None
        except Exception as error:
            await self._settle_and_advance(
                session, run, definition, attempt, Failure.rejected(f"{type(error).__name__}: {error}"), now
            )
            return None

        previous = attempt.status
        attempt.status = AttemptStatus.RUNNING
        started = attempt.started_at or now
        attempt.started_at = started
        attempt.lease_owner = self.owner
        attempt.lease_expires_at = now + self.services.settings.lease
        attempt.heartbeat_at = now
        attempt.input = {**(attempt.input or {}), "config": config}
        if attempt.deadline_at is None:
            attempt.deadline_at = self._deadline_for(step, block, now)
        if run.status is RunStatus.QUEUED:
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or now

        return ClaimedUnit(
            attempt_id=attempt.id,
            run_id=run.id,
            run_item_id=attempt.run_item_id,
            step_name=attempt.step_name,
            block_id=attempt.block_id,
            attempt_number=attempt.attempt,
            started_at=started,
            previous_status=previous,
            step=step,
            config=config,
            params=dict(run.params),
            log_levels=dict(run.log_levels) if run.log_levels else None,
            scratch=scratch,
            item=item_value,
            has_item=has_item,
            connections=await load_connections(session),
            schemas=await load_schemas(session),
            traceparent=run.traceparent,
            remote_handle=RemoteHandle.model_validate(attempt.remote_handle) if attempt.remote_handle else None,
            poke_cursor=attempt.poke_cursor,
            deadline_at=attempt.deadline_at,
            gone_probes=attempt.gone_probes,
        )

    def _deadline_for(self, step: StepDefinition, block: AnyOperator | AnySensor, now: datetime) -> datetime | None:
        """Compute when a wait must end: the step's deadline, or a sensor's own default."""
        if step.deadline is not None:
            return now + step.deadline
        default = getattr(block.spec, "default_deadline", None)
        return now + default if isinstance(default, timedelta) else None

    # -- execution ---------------------------------------------------------------

    async def run_unit(self, unit: ClaimedUnit, *, now: datetime | None = None) -> None:
        """Call the block for one claimed unit and record whatever it did."""
        with (
            telemetry.attempt_span(
                run_id=str(unit.run_id),
                step=unit.step_name,
                block=unit.block_id,
                attempt=unit.attempt_number,
                parent=telemetry.context_from(unit.traceparent),
            ) as span,
            log_context(
                run_id=str(unit.run_id),
                run_item_id=str(unit.run_item_id) if unit.run_item_id else None,
                step=unit.step_name,
                attempt=unit.attempt_number,
                block=unit.block_id,
                worker=self.owner,
            ),
        ):
            logger = BufferedLogger(
                run_id=unit.run_id,
                step_name=unit.step_name,
                step_attempt_id=unit.attempt_id,
                run_item_id=unit.run_item_id,
                keep=kept_level(unit.log_levels, unit.block_id),
                limit=self.services.settings.log_entries_per_attempt,
                batch=self.services.settings.log_flush_batch,
            )
            context = self._context(unit, logger)
            started = time.monotonic()
            stop = asyncio.Event()
            flusher = asyncio.create_task(self._flush_while_running(logger, stop))
            try:
                result = await self._call_block(unit, context)
            finally:
                stop.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await flusher
            if isinstance(result, Errored):
                telemetry.record_failure(span, result.failure.message)
            if isinstance(result, Submitted):
                await self.record_handle(unit, result.handle)
            await self._record(
                unit,
                result,
                logger,
                now or utcnow(),
                storage=context.storage,
                seconds=time.monotonic() - started,
            )

    def _context(self, unit: ClaimedUnit, logger: BufferedLogger) -> EngineStepContext:
        """Build the context one unit's call and the outcome of that call both work through.

        Its storage is the one the step's own writes went through, so an output too large to
        inline is persisted by the same configured backend rather than the unconfigured one.
        """
        return EngineStepContext(
            run_id=unit.run_id,
            step=unit.step_name,
            run_item_id=unit.run_item_id,
            attempt=unit.attempt_number,
            started_at=unit.started_at,
            inline_capture=self.services.settings.inline_capture,
            params=unit.params,
            log=logger,
            storage=self.services.storage,
            scratch=unit.scratch,
            work_root=self.services.settings.work_root,
            connections=unit.connections,
            connection_models=self.services.connection_models,
            schemas=unit.schemas,
            secrets=self.services.secrets,
            runs=EngineRuns(self.services, parent_run_id=unit.run_id, sessions=self.sessions),
            format_checker=self.services.format_checker,
            storage_connections=self.services.settings.storage_connections,
            cursor=unit.poke_cursor,
        )

    async def _call_block(self, unit: ClaimedUnit, context: EngineStepContext) -> CallResult:
        """Make exactly one block call, under the step's timeout, and classify what came back."""
        operator = self.services.host.operators.get(unit.block_id)
        sensor = self.services.host.sensors.get(unit.block_id)
        block: AnyOperator | AnySensor = operator or self.services.block(unit.block_id)
        config = block.config_model.model_validate(unit.config)
        try:
            async with asyncio.timeout(unit.step.timeout.total_seconds() if unit.step.timeout else None):
                if sensor is not None:
                    with self._timed(unit.block_id, "poke"):
                        return _read_poke(await sensor.poke(config, context))
                if operator is None:  # pragma: no cover - the host resolved it above
                    return Errored(failure=Failure.rejected(f"block {unit.block_id!r} is not installed"))
                return await self._call_operator(operator, config, context, unit)
        except TimeoutError:
            return Errored(failure=timeout_failure(unit.step.timeout))
        except Exception as error:
            return Errored(failure=Failure.of(block, error))

    async def _call_operator(
        self,
        operator: AnyOperator,
        config: BaseModel,
        context: EngineStepContext,
        unit: ClaimedUnit,
    ) -> CallResult:
        """Drive an operator's half of the contract: execute once, then probe and fetch."""
        if not unit.is_probe or unit.remote_handle is None:
            with self._timed(unit.block_id, "execute"):
                produced = await operator.execute(config, context)
            if isinstance(produced, RemoteHandle):
                return Submitted(handle=produced)
            return Produced(output=produced.model_dump(mode="json"))
        with self._timed(unit.block_id, "probe"):
            probe = await operator.probe(unit.remote_handle, config, context)
        advanced = None if probe.meta is None else unit.remote_handle.model_copy(update={"meta": probe.meta})
        handle = advanced or unit.remote_handle
        match probe.status:
            case ProbeStatus.RUNNING:
                return Waiting(
                    next_poll_in=probe.next_poll_in,
                    message=probe.message,
                    progress=probe.progress,
                    handle=advanced,
                )
            case ProbeStatus.SUCCEEDED:
                with self._timed(unit.block_id, "fetch"):
                    fetched = await operator.fetch(handle, config, context)
                return Produced(output=fetched.model_dump(mode="json"))
            case ProbeStatus.FAILED:
                return Errored(
                    failure=Failure(message=probe.message or "the remote job failed", error_class=ErrorClass.UNKNOWN)
                )
            case ProbeStatus.GONE:
                return Vanished(message=probe.message or "the remote no longer knows this job")

    @contextlib.contextmanager
    def _timed(self, block_id: str, call: str) -> Generator[None]:
        """Wrap one block call in its own span and record how long it took."""
        started = time.monotonic()
        with telemetry.block_span(block_id, call):
            try:
                yield
            finally:
                telemetry.record_block_call(block_id, call, time.monotonic() - started)

    # -- recording ---------------------------------------------------------------

    def _holds_lease(self, attempt: StepAttempt) -> bool:
        """Report whether this worker may still write the outcome of an attempt.

        The lease is a fence, not a hint. If the sweeper decided this worker was dead and
        handed the attempt to somebody else, the row belongs to that other worker, and
        writing into it would clobber a live attempt with the result of an abandoned one.
        """
        return attempt.status is AttemptStatus.RUNNING and attempt.lease_owner == self.owner

    def _log_lost_lease(self, unit: ClaimedUnit, attempt: StepAttempt | None, what: str) -> None:
        """Log that an outcome was dropped, which means the work may have run twice."""
        _logger.warning(
            "lease lost, outcome discarded",
            discarded=what,
            attempt_id=str(unit.attempt_id),
            run_id=str(unit.run_id),
            step=unit.step_name,
            holder=None if attempt is None else attempt.lease_owner,
            attempt_status=None if attempt is None else attempt.status.value,
        )

    async def record_handle(self, unit: ClaimedUnit, handle: RemoteHandle) -> None:
        """Commit the remote handle on its own, the moment execute returned it."""
        await with_deadlock_retry(lambda: self._record_handle_once(unit, handle))

    async def _record_handle_once(self, unit: ClaimedUnit, handle: RemoteHandle) -> None:
        """Run that transaction once; the caller runs it again after a deadlock.

        It locks the run and then writes the attempt, the order every outcome uses and the
        opposite of the claim's. Nothing of it survives a rollback, so it is safe to repeat.
        """
        async with session_scope(self.sessions) as session:
            await lock_run(session, unit.run_id)
            attempt = await session.get(StepAttempt, unit.attempt_id)
            if attempt is not None and attempt.status is AttemptStatus.CANCELLED:
                await self._cancel_what_was_just_submitted(session, unit, attempt, handle)
                return
            if attempt is None or not self._holds_lease(attempt):
                self._log_lost_lease(unit, attempt, "remote handle")
                return
            attempt.remote_handle = handle.model_dump(mode="json")

    async def _cancel_what_was_just_submitted(
        self,
        session: AsyncSession,
        unit: ClaimedUnit,
        attempt: StepAttempt,
        handle: RemoteHandle,
    ) -> None:
        """Cancel remote work that was submitted while the attempt was being cancelled.

        The cancel cleared the lease, so the ordinary path would discard the handle and the
        job would run on with nothing recording that it exists. The handle is kept because it
        is the only evidence of the job, and the remote is told straight away.
        """
        attempt.remote_handle = handle.model_dump(mode="json")
        run = await session.get(Run, unit.run_id)
        if run is None:  # pragma: no cover - the attempt was just read from this run
            return
        await cancel_remote(session, self.services, run, attempt, await load_connections(session))
        _logger.info(
            "remote work submitted into a cancelled attempt was cancelled",
            attempt_id=str(unit.attempt_id),
            run_id=str(unit.run_id),
            step=unit.step_name,
        )

    async def _flush_while_running(self, logger: BufferedLogger, stop: asyncio.Event) -> None:
        """Write what an attempt has logged to the run for as long as the attempt runs.

        On the interval, and the moment the buffer reaches its size gate, whichever comes
        first. It runs beside the block's own coroutine on the executor's session factory,
        never the session a block was handed, and the caller stops it rather than cancelling
        it, so a flush is never torn down mid-commit.
        """
        interval = self.services.settings.log_flush_interval.total_seconds()
        while not stop.is_set():
            await _first_of((stop.wait(), logger.full.wait()), interval)
            await self._flush(logger)

    async def _flush(self, logger: BufferedLogger) -> None:
        """Append what the buffer holds to the run, in a transaction of its own.

        Committed entries leave the buffer for good, so the outcome cannot write them twice;
        a flush that failed puts them back, for the next flush or for the outcome.
        """
        entries = logger.drain()
        if not entries:
            return
        try:
            async with session_scope(self.sessions) as session:
                await session.execute(sa.insert(LogEntry), entries)
        except Exception as error:
            logger.restore(entries)
            _logger.debug("a log flush failed; its entries stay buffered", error=str(error))

    async def _record(
        self,
        unit: ClaimedUnit,
        result: CallResult,
        logger: BufferedLogger,
        now: datetime,
        *,
        storage: AttemptStorage,
        seconds: float | None = None,
    ) -> None:
        """Record an outcome and everything it implies, in one transaction."""
        # Drained here rather than inside: draining empties the buffer, and a transaction the
        # database aborted to break a deadlock is run again with the same entries.
        entries = logger.drain()
        logged = logger.recorded > 0
        await with_deadlock_retry(
            lambda: self._record_once(unit, result, entries, now, storage=storage, seconds=seconds, logged=logged)
        )

    async def _record_once(
        self,
        unit: ClaimedUnit,
        result: CallResult,
        entries: list[LogRow],
        now: datetime,
        *,
        storage: AttemptStorage,
        seconds: float | None = None,
        logged: bool = False,
    ) -> None:
        """Run the outcome transaction once; the caller runs it again after a deadlock."""
        async with session_scope(self.sessions) as session:
            run = await session.get(Run, unit.run_id)
            if run is None:  # pragma: no cover - foreign keys prevent this
                return
            # Take the run's lock before anything reads or writes: an outcome transaction
            # that inserted a log row first would hold a share lock on the run and then have
            # to upgrade it, which is how two workers finishing at once deadlock. The lock
            # also orders this transaction against the claim and the lease sweeper, which
            # is what makes the lease check below a fence rather than a guess.
            await lock_run(session, run.id)
            attempt = await session.get(StepAttempt, unit.attempt_id)
            if attempt is None:  # pragma: no cover - foreign keys prevent this
                return
            if not self._holds_lease(attempt):
                self._log_lost_lease(unit, attempt, "attempt outcome")
                return
            if entries:
                await session.execute(sa.insert(LogEntry), entries)
            if run.status is RunStatus.CANCELLED:
                attempt.status = AttemptStatus.CANCELLED
                attempt.finished_at = now
                _release(attempt)
                return
            version = await session.get(PipelineVersion, run.pipeline_version_id)
            definition = load_definition(version.document) if version else None
            if definition is None:  # pragma: no cover - foreign keys prevent this
                return

            output_bytes: int | None = None
            match result:
                case Produced(output=output):
                    output_bytes = await self._succeed(session, storage, attempt, output, now)
                case Submitted(handle=handle, next_poll_in=interval):
                    _park(attempt, now, interval or probe_interval(self._poll_for(unit), 0))
                    attempt.remote_handle = handle.model_dump(mode="json")
                case Waiting(next_poll_in=interval, message=message, progress=progress, handle=advanced, cursor=cursor):
                    attempt.poke_count += 1
                    attempt.gone_probes = 0
                    if advanced is not None:
                        attempt.remote_handle = advanced.model_dump(mode="json")
                    if cursor is not None:
                        attempt.poke_cursor = cursor
                    _note_waiting(session, attempt, message, progress)
                    _park(attempt, now, interval or self._wait_for(unit, attempt))
                case Vanished(message=message):
                    await self._record_gone(session, run, definition, attempt, unit, message, now)
                case Errored(failure=failure):
                    await self._settle_failure(session, run, definition, attempt, failure, now)

            if not logged:
                _trace_settlement(session, attempt, seconds=seconds, output_bytes=output_bytes)

            status = await self._advance(session, run, definition, now)
            telemetry.record_step(attempt.status.value, unit.block_id, seconds)
            _logger.info("attempt settled", status=attempt.status.value, run_status=status.value)

    async def _advance(
        self,
        session: AsyncSession,
        run: Run,
        definition: PipelineDefinition,
        now: datetime,
    ) -> RunStatus:
        """Walk the DAG, and settle everything a run that reached a terminal status owes."""
        status = await advance(session, run, definition, now=now)
        if status in TERMINAL_RUN_STATUSES:
            # Imported here rather than at module scope: alerting imports this module back,
            # so naming it at import time closes a cycle.
            from dirigent_core.alerting import raise_for_status

            # Queued in the same commit that settles the run, so a run cannot reach a
            # terminal state without the alerts it owes having been written down.
            await raise_for_status(session, self.services, run, status, now=now)
            await promote_queued_run(session, self.services, run.pipeline_id)
            telemetry.record_run(status.value, definition.code)
        return status

    def _poll_for(self, unit: ClaimedUnit) -> timedelta:
        """Choose the cadence for the next probe: the step's, the block's, or the default."""
        if unit.step.poll is not None:
            return unit.step.poll
        default = getattr(self.services.block(unit.block_id).spec, "default_poll", None)
        return default if isinstance(default, timedelta) else DEFAULT_PROBE_INTERVAL

    def _wait_for(self, unit: ClaimedUnit, attempt: StepAttempt) -> timedelta:
        """Choose how long to park a wait that has already been probed at least once.

        A sensor's ``poll`` is a promise about how often the world is checked, so its cadence
        is used exactly; an operator probing its own remote job widens toward the cadence.
        """
        cadence = self._poll_for(unit)
        if attempt.remote_handle is None:
            return cadence
        return probe_interval(cadence, attempt.poke_count)

    async def _succeed(
        self,
        session: AsyncSession,
        storage: AttemptStorage,
        attempt: StepAttempt,
        output: JsonMap,
        now: datetime,
    ) -> int | None:
        """Persist an output as an artifact reference, mark the attempt succeeded, and size it."""
        reference = await persist_output(
            session,
            storage,
            attempt,
            output,
            inline_max_bytes=self.services.settings.inline_artifact_max,
        )
        attempt.status = AttemptStatus.SUCCEEDED
        attempt.finished_at = now
        attempt.error = None
        attempt.error_class = None
        attempt.waiting_message = None
        attempt.waiting_progress = None
        _release(attempt)
        return reference.size_bytes

    async def _record_gone(
        self,
        session: AsyncSession,
        run: Run,
        definition: PipelineDefinition,
        attempt: StepAttempt,
        unit: ClaimedUnit,
        message: str,
        now: datetime,
    ) -> None:
        """Apply the lost-job policy: count consecutive GONE probes, then fail cleanly."""
        attempt.gone_probes += 1
        limit = self.services.settings.lost_job_max_gone
        if attempt.gone_probes < limit:
            _park(attempt, now, self._poll_for(unit))
            return
        await self._settle_failure(
            session,
            run,
            definition,
            attempt,
            Failure.transient(f"{message} (after {attempt.gone_probes} consecutive GONE probes)"),
            now,
        )

    async def settle_overdue_deadlines(self, session: AsyncSession, *, now: datetime | None = None) -> list[UUID]:
        """Settle attempts whose deadline passed while they were parked between pokes.

        The claim path checks a deadline, which is enough for work that is claimable. An
        attempt waiting on a poll an hour away is not, so its deadline would be honoured an
        hour late and a person would watch a step sit past a deadline it was given.
        """
        moment = now or utcnow()
        settled: list[UUID] = []
        for attempt in await overdue_deadlines(session, now=moment):
            # The sweep competes with the worker claiming this attempt and with a cancel of
            # its run, so the lock comes before the checks and not after. Both rows are read
            # again under it: the select above ran without the lock, and the attempt it
            # returned sits in this session's identity map, which is what a plain read hands
            # back.
            await lock_run(session, attempt.run_id)
            run = await session.get(Run, attempt.run_id)
            if run is None:  # pragma: no cover - the foreign key makes this unreachable
                continue
            await session.refresh(run)
            if run.status not in ACTIVE_RUN_STATUSES:
                continue
            await session.refresh(attempt)
            if attempt.status not in (AttemptStatus.PENDING, AttemptStatus.QUEUED, AttemptStatus.WAITING):
                continue
            if attempt.deadline_at is None or attempt.deadline_at > moment:
                continue
            version = await session.get(PipelineVersion, run.pipeline_version_id)
            if version is None:  # pragma: no cover - the foreign key makes this unreachable
                continue
            definition = load_definition(version.document)
            step = definition.steps.get(attempt.step_name)
            if step is None:
                continue
            await self._settle_deadline(session, run, definition, attempt, step, moment)
            _logger.info(
                "a deadline passed while the attempt waited",
                attempt_id=str(attempt.id),
                run_id=str(run.id),
                step=attempt.step_name,
                deadline_at=attempt.deadline_at.isoformat() if attempt.deadline_at else None,
                on_timeout=step.on_timeout.value,
            )
            settled.append(attempt.id)
        return settled

    async def _settle_deadline(
        self,
        session: AsyncSession,
        run: Run,
        definition: PipelineDefinition,
        attempt: StepAttempt,
        step: StepDefinition,
        now: datetime,
    ) -> None:
        """Apply the step's timeout outcome, which is configuration and not a block decision."""
        if step.on_timeout is TimeoutAction.SKIP:
            attempt.status = AttemptStatus.SKIPPED
            attempt.finished_at = now
            attempt.error = f"the deadline {attempt.deadline_at} passed; the step is skipped"
            _release(attempt)
        else:
            await self._settle_failure(
                session,
                run,
                definition,
                attempt,
                Failure.rejected(f"the deadline {attempt.deadline_at} passed before the step finished"),
                now,
                allow_retry=False,
            )
        await self._advance(session, run, definition, now)

    async def _settle_failure(
        self,
        session: AsyncSession,
        run: Run,
        definition: PipelineDefinition,
        attempt: StepAttempt,
        failure: Failure,
        now: datetime,
        *,
        allow_retry: bool = True,
    ) -> None:
        """Fail an attempt, and schedule the next one when the retry policy earns it."""
        attempt.status = AttemptStatus.FAILED
        attempt.finished_at = now
        attempt.error = failure.message
        attempt.error_class = failure.error_class.value
        _release(attempt)

        step = definition.steps.get(attempt.step_name)
        if step is None or not allow_retry or attempt.kind is AttemptKind.MANUAL:
            return
        retrying = should_retry(failure.error_class, attempt=attempt.attempt, policy=step.retry)
        _logger.debug(
            "failure classified",
            step=attempt.step_name,
            error_class=failure.error_class.value,
            attempt=attempt.attempt,
            max_attempts=step.retry.max_attempts,
            retrying=retrying,
        )
        if not retrying:
            return
        delay = backoff_delay(step.retry, attempt.attempt)
        session.add(
            StepAttempt(
                run_id=attempt.run_id,
                run_item_id=attempt.run_item_id,
                step_name=attempt.step_name,
                block_id=attempt.block_id,
                attempt=attempt.attempt + 1,
                kind=AttemptKind.AUTOMATIC,
                status=AttemptStatus.QUEUED,
                available_at=now + delay,
                deadline_at=attempt.deadline_at,
            )
        )
        _logger.info(
            "attempt will be retried",
            step=attempt.step_name,
            next_attempt=attempt.attempt + 1,
            delay_seconds=round(delay.total_seconds(), 3),
            error_class=failure.error_class.value,
        )

    async def _settle_and_advance(
        self,
        session: AsyncSession,
        run: Run,
        definition: PipelineDefinition,
        attempt: StepAttempt,
        failure: Failure,
        now: datetime,
    ) -> None:
        """Fail an attempt the claim path refused, and walk the DAG in the same transaction."""
        await self._settle_failure(session, run, definition, attempt, failure, now)
        await self._advance(session, run, definition, now)

    # -- leases ------------------------------------------------------------------

    async def heartbeat(self, attempt_ids: Sequence[UUID], *, now: datetime | None = None) -> set[UUID]:
        """Refresh the leases this worker holds, and say which ones it still holds.

        An attempt that does not come back was taken away by the sweeper, and the caller has
        to stop working on it: its outcome will be refused by :meth:`_holds_lease` anyway.
        """
        if not attempt_ids:
            return set()
        moment = now or utcnow()
        expires = moment + self.services.settings.lease
        async with session_scope(self.sessions) as session:
            refreshed = await session.execute(
                sa.update(StepAttempt)
                .where(
                    StepAttempt.id.in_(attempt_ids),
                    StepAttempt.lease_owner == self.owner,
                    StepAttempt.status == AttemptStatus.RUNNING,
                )
                .values(heartbeat_at=moment, lease_expires_at=expires)
                .returning(StepAttempt.id)
            )
            held = set(refreshed.scalars())
            _logger.debug(
                "leases refreshed",
                worker=self.owner,
                held=len(held),
                lost=len(attempt_ids) - len(held),
                expires_at=expires.isoformat(),
            )
            return held


def _release(attempt: StepAttempt) -> None:
    """Drop the lease from an attempt that is no longer being worked on."""
    attempt.lease_owner = None
    attempt.lease_expires_at = None


def timeout_failure(timeout: timedelta | None) -> Failure:
    """Say that a call ran out of time, spelling the budget the way the step wrote it down."""
    if timeout is None:
        return Failure.transient("the block call timed out")
    return Failure.transient(f"the block call exceeded the step timeout {format_duration(timeout)}")


def probe_interval(cadence: timedelta, probes: int) -> timedelta:
    """Widen a remote job's probe interval geometrically, from the first probe to the cadence."""
    if cadence <= FIRST_PROBE_INTERVAL:
        return cadence
    widened = FIRST_PROBE_INTERVAL * float(2 ** min(probes, MAX_PROBE_DOUBLINGS))
    return min(widened, cadence)


def _park(attempt: StepAttempt, now: datetime, interval: timedelta) -> None:
    """Park an attempt as a durable wait with a due time, releasing the worker."""
    attempt.status = AttemptStatus.WAITING
    due = now + interval
    attempt.next_poll_at = due
    _release(attempt)
    _logger.debug(
        "parked until the next probe",
        step=attempt.step_name,
        probes=attempt.poke_count,
        interval_seconds=round(interval.total_seconds(), 3),
        next_poll_at=due.isoformat(),
    )


def _trace_settlement(
    session: AsyncSession,
    attempt: StepAttempt,
    *,
    seconds: float | None,
    output_bytes: int | None,
) -> None:
    """Write the one line an attempt leaves behind when its call logged nothing of its own.

    A block that kept its own account keeps it, so a step never says it finished twice. An
    attempt that only parked writes nothing: a sensor poked once a second for an hour would
    otherwise leave thirty-six hundred lines saying it is still waiting.
    """
    fields: JsonMap = {}
    if seconds is not None:
        fields["duration_ms"] = round(seconds * 1000)
    match attempt.status:
        case AttemptStatus.SUCCEEDED:
            level, message = LogLevel.INFO, "finished"
            if output_bytes is not None:
                fields["output_bytes"] = output_bytes
        case AttemptStatus.FAILED:
            level, message = LogLevel.ERROR, "failed"
            fields["error_class"] = attempt.error_class
            if attempt.error:
                # The line has to say what failed on its own: the attempt row is not always
                # beside it, and a log read tomorrow has only what was written today.
                fields["error"] = attempt.error[:500]
        case _:
            return
    session.add(
        LogEntry(
            run_id=attempt.run_id,
            run_item_id=attempt.run_item_id,
            step_attempt_id=attempt.id,
            step_name=attempt.step_name,
            level=level,
            message=message,
            fields=fields,
        )
    )


async def _first_of(waits: Sequence[Coroutine[Any, Any, object]], timeout: float) -> None:
    """Wait for the first of some events, or for the timeout, and drop the rest."""
    tasks = [asyncio.ensure_future(wait) for wait in waits]
    try:
        await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _note_waiting(session: AsyncSession, attempt: StepAttempt, message: str | None, progress: float | None) -> None:
    """Keep what a waiting attempt last saw, and log the message once per change.

    Progress moves on every poll and only updates the row: a log line per poll would be a
    thousand copies of the same sentence.
    """
    said = message[:500] if message is not None else None
    if said is not None and said != attempt.waiting_message:
        session.add(
            LogEntry(
                run_id=attempt.run_id,
                run_item_id=attempt.run_item_id,
                step_attempt_id=attempt.id,
                step_name=attempt.step_name,
                level=LogLevel.INFO,
                message=said,
            )
        )
    attempt.waiting_message = said
    attempt.waiting_progress = progress


def _read_poke(observed: BaseModel | NotYet) -> CallResult:
    """Turn a sensor's return value into an outcome; NotYet is not a failure."""
    if isinstance(observed, NotYet):
        return Waiting(
            next_poll_in=observed.next_poll_in,
            message=observed.message,
            progress=observed.progress,
            cursor=observed.cursor,
        )
    return Produced(output=observed.model_dump(mode="json"))


async def collect_outputs(session: AsyncSession, run_id: UUID, definition: PipelineDefinition) -> dict[str, JsonValue]:
    """Gather the stored outputs a step's references may read.

    A fan-out step's output is the list of its items' outputs in item order.
    """
    rows = await session.execute(
        sa.select(StepAttempt, RunItem.item_index)
        .join(RunItem, RunItem.id == StepAttempt.run_item_id, isouter=True)
        .where(StepAttempt.run_id == run_id, StepAttempt.status == AttemptStatus.SUCCEEDED)
        .order_by(StepAttempt.step_name, RunItem.item_index, StepAttempt.attempt)
    )
    collected: dict[str, JsonValue] = {}
    fanned: dict[str, list[JsonValue]] = {}
    for attempt, _index in rows:
        step = definition.steps.get(attempt.step_name)
        if step is not None and step.is_fan_out:
            fanned.setdefault(attempt.step_name, []).append(attempt.output)
        else:
            collected[attempt.step_name] = attempt.output
    collected.update(fanned)
    return collected
