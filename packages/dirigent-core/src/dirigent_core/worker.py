"""The worker: a claim loop, a semaphore, a lease heartbeat, and a registry row.

On SIGTERM the loop stops claiming and waits for what is already in flight, so a rolling
restart never leaves an attempt to be reclaimed by lease expiry.
"""

import asyncio
import contextlib
import os
import signal
import socket
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, WorkerStatus
from dirigent_client.schemas import Catalog
from dirigent_core import retention, telemetry
from dirigent_core.alerting import NotificationDispatcher, raise_for_stuck, recover_notifications
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine.claim import ClaimedUnit
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.recovery import detect_stuck_runs, reap_workers, sweep_leases
from dirigent_core.engine.services import EngineServices
from dirigent_core.logging import get_logger, log_context
from dirigent_core.models import StepAttempt, utcnow
from dirigent_core.models import Worker as WorkerRow

#: How long a stopping worker lets its background loops finish the pass they are in.
GRACEFUL_STOP_SECONDS = 5.0

_logger = get_logger("worker")


class Chore(NamedTuple):
    """One periodic job a worker runs beside the sweeper, on a cadence of its own.

    The worker owns the loop -- its cadence, its halt flag and its failure handling -- and
    knows nothing about what the job does. A chore that raises is logged and tried again on
    its next tick, exactly as the sweeper is.
    """

    name: str
    interval: timedelta
    run: Callable[[], Awaitable[None]]


def default_worker_name() -> str:
    """Name a worker after where it runs."""
    return f"{socket.gethostname()}-{os.getpid()}"


class Worker:
    """One worker process: claim, execute under a semaphore, heartbeat, and drain on demand."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        services: EngineServices,
        *,
        name: str | None = None,
        concurrency: int | None = None,
        tags: list[str] | None = None,
        sweeper: bool = True,
        chores: Sequence[Chore] = (),
    ) -> None:
        """Bind the worker to the database, the services, and its own identity."""
        self.settings: Settings = services.settings
        self.name = name or self.settings.worker_name or default_worker_name()
        # The in-flight gauge is a process-local level, so it carries this worker's name
        # from construction: an idle worker reports a zero under its own name.
        telemetry.gauges.worker = self.name
        self.concurrency = concurrency or self.settings.worker_concurrency
        self.tags = tags if tags is not None else list(self.settings.worker_tags)
        self.sessions = sessions
        self.services = services
        self.engine = Engine(sessions, services, owner=self.name, tags=self.tags)
        self.alerts = NotificationDispatcher(sessions=sessions, services=services, owner=self.name)
        self.sweeper = sweeper
        self.chores = list(chores)
        self.in_flight: set[UUID] = set()
        self._stopping = asyncio.Event()
        self._halting = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._running: dict[UUID, asyncio.Task[None]] = {}

    @property
    def draining(self) -> bool:
        """Report whether the worker has been asked to stop claiming."""
        return self._stopping.is_set()

    def request_stop(self) -> None:
        """Stop claiming; work already in flight is allowed to finish."""
        if not self._stopping.is_set():
            _logger.info("worker draining", worker=self.name, in_flight=len(self.in_flight))
            self._stopping.set()

    async def run(self) -> None:
        """Run the claim loop until asked to stop, then drain what is in flight."""
        await self._register(WorkerStatus.RUNNING)
        _logger.info("worker started", worker=self.name, concurrency=self.concurrency, tags=self.tags)
        semaphore = asyncio.Semaphore(self.concurrency)
        background = [asyncio.create_task(self._heartbeat_loop()), asyncio.create_task(self._alert_loop())]
        if self.sweeper:
            background.append(asyncio.create_task(self._sweep_loop()))
            background.append(asyncio.create_task(self._work_loop()))
        background.extend(asyncio.create_task(self._chore_loop(chore)) for chore in self.chores)
        try:
            await self._claim_loop(semaphore)
        finally:
            self._stopping.set()
            # Draining happens while the heartbeat is still running: an attempt whose lease
            # is not refreshed for the length of the drain is reclaimed by another worker's
            # sweeper and executed twice.
            await self._drain()
            # The loops exit on the halt flag at their next wake, mid-transaction work
            # allowed to finish -- a cancel landing inside a database await makes the
            # rollback itself raise, and that traceback has no business in a run's output.
            self._halting.set()
            _done, pending = await asyncio.wait(background, timeout=GRACEFUL_STOP_SECONDS)
            for task in pending:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            await self._register(WorkerStatus.STOPPED)
            _logger.info("worker stopped", worker=self.name)

    async def _claim_loop(self, semaphore: asyncio.Semaphore) -> None:
        """Claim units while there is capacity, and idle briefly when the queue is empty."""
        while not self.draining:
            await semaphore.acquire()
            if self.draining:
                semaphore.release()
                break
            unit = await self._claim_safely()
            if unit is None:
                semaphore.release()
                await self._idle()
                continue
            self.in_flight.add(unit.attempt_id)
            telemetry.gauges.in_flight = len(self.in_flight)
            task = asyncio.create_task(self._execute(unit, semaphore))
            self._tasks.add(task)
            self._running[unit.attempt_id] = task
            task.add_done_callback(self._tasks.discard)

    async def _claim_safely(self) -> ClaimedUnit | None:
        """Claim, pausing rather than dying when the database is briefly unreachable."""
        try:
            return await self.engine.claim()
        except Exception as error:  # a transient database failure must not end the process
            _logger.error("claim failed", worker=self.name, error=str(error))
            await asyncio.sleep(self.settings.claim_idle.total_seconds())
            return None

    async def _execute(self, unit: ClaimedUnit, semaphore: asyncio.Semaphore) -> None:
        """Run one claimed unit, always releasing its slot and its in-flight record."""
        try:
            await self.engine.run_unit(unit)
        except Exception as error:  # the outcome transaction owns failures; this is a bug
            _logger.error("executing an attempt raised", attempt_id=str(unit.attempt_id), error=str(error))
        finally:
            self.in_flight.discard(unit.attempt_id)
            self._running.pop(unit.attempt_id, None)
            telemetry.gauges.in_flight = len(self.in_flight)
            semaphore.release()

    async def _idle(self) -> None:
        """Wait a moment for work to appear, returning early when asked to stop."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=self.settings.claim_idle.total_seconds())

    async def _pause(self, seconds: float) -> None:
        """Sleep one cadence out, waking at once when the background loops are told to halt."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._halting.wait(), timeout=seconds)

    async def _heartbeat_loop(self) -> None:
        """Refresh the leases this worker holds, and its registry row, on a fixed cadence.

        It runs through the drain: an in-flight attempt keeps its lease until it finishes.
        """
        while not self._halting.is_set():
            await self._pause(self.settings.heartbeat.total_seconds())
            if self._halting.is_set():
                return
            try:
                claimed = set(self.in_flight)
                held = await self.engine.heartbeat(list(claimed))
                self._abandon(claimed - held)
                await self._register(WorkerStatus.DRAINING if self.draining else WorkerStatus.RUNNING)
            except Exception as error:  # a missed heartbeat is recoverable; a dead task is not
                _logger.warning("heartbeat failed", worker=self.name, error=str(error))

    def _abandon(self, lost: set[UUID]) -> None:
        """Stop working on attempts whose lease this worker no longer holds.

        A heartbeat that does not come back means the sweeper handed the attempt to somebody
        else: the outcome will be refused by the engine's lease fence anyway, and continuing
        is duplicate work against whatever the block talks to.
        """
        for attempt_id in lost:
            task = self._running.pop(attempt_id, None)
            _logger.warning(
                "lease lost, abandoning attempt",
                worker=self.name,
                attempt_id=str(attempt_id),
                cancelled=task is not None and not task.done(),
            )
            if task is not None and not task.done():
                task.cancel()

    async def _sweep_loop(self) -> None:
        """Recover what a dead worker left, settle passed deadlines, reap what stopped reporting."""
        while not self._halting.is_set():
            await self._pause(self.settings.sweep_interval.total_seconds())
            if self._halting.is_set():
                return
            try:
                async with session_scope(self.sessions) as session:
                    recovered = await sweep_leases(session)
                    overdue = await self.engine.settle_overdue_deadlines(session)
                    stuck = await detect_stuck_runs(session, after=self.settings.stuck_run)
                    await raise_for_stuck(session, self.services, stuck)
                    await recover_notifications(session)
                    # This worker's own row was refreshed by the heartbeat well inside the
                    # age below, so a sweeper never reaps the process running it.
                    reaped = await reap_workers(session, older_than=self.settings.stale_worker)
                    await self._observe_levels(session)
                if recovered:
                    _logger.info("recovered abandoned attempts", worker=self.name, count=len(recovered))
                if overdue:
                    _logger.info("settled attempts past their deadline", worker=self.name, count=len(overdue))
                if reaped:
                    _logger.info("reaped worker registry rows", worker=self.name, count=len(reaped))
            except Exception as error:  # the sweeper retries on its next tick
                _logger.warning("sweep failed", worker=self.name, error=str(error))

    async def _work_loop(self) -> None:
        """Remove the work directories of runs the retention policy has outlived.

        The database sweep runs on the scheduler alone and a work directory is on this
        worker's own filesystem, so this is the worker's half of the same policy.
        """
        policy = retention.policy_from(self.settings)
        while not self._halting.is_set():
            await self._pause(self.settings.retention_interval.total_seconds())
            if self._halting.is_set():
                return
            try:
                async with session_scope(self.sessions) as session:
                    swept = await retention.sweep_work(session, self.settings.work_root, policy)
                if swept:
                    _logger.info("swept work directories", worker=self.name, count=swept)
            except Exception as error:  # it retries on its next tick, like the sweeper
                _logger.warning("work directory sweep failed", worker=self.name, error=str(error))

    async def _chore_loop(self, chore: Chore) -> None:
        """Run one periodic job on its own cadence until the worker halts."""
        while not self._halting.is_set():
            await self._pause(chore.interval.total_seconds())
            if self._halting.is_set():
                return
            try:
                await chore.run()
            except Exception as error:  # a chore retries on its next tick, like the sweeper
                _logger.warning("a periodic chore failed", worker=self.name, chore=chore.name, error=str(error))

    async def _alert_loop(self) -> None:
        """Deliver whatever alerting has queued, on the same cadence as claiming."""
        while not self._halting.is_set():
            try:
                sent = await self.alerts.drain()
            except Exception as error:  # the queue is durable; this pass retries on the next tick
                _logger.warning("alert delivery pass failed", worker=self.name, error=str(error))
                sent = 0
            if not sent:
                await self._pause(self.settings.claim_idle.total_seconds())

    async def _observe_levels(self, session: AsyncSession) -> None:
        """Read the levels an operator watches, on the sweeper's cadence."""
        depth = await session.execute(
            sa.select(sa.func.count()).select_from(StepAttempt).where(StepAttempt.status == AttemptStatus.QUEUED)
        )
        waiting = await session.execute(
            sa.select(sa.func.count()).select_from(StepAttempt).where(StepAttempt.status == AttemptStatus.WAITING)
        )
        now = utcnow()
        heartbeats = await session.execute(
            sa.select(WorkerRow.name, WorkerRow.last_seen_at).where(WorkerRow.status != WorkerStatus.STOPPED)
        )
        telemetry.gauges.observe(
            queue_depth=int(depth.scalar_one()),
            waiting=int(waiting.scalar_one()),
            heartbeat_ages={name: max((now - seen).total_seconds(), 0.0) for name, seen in heartbeats},
        )

    async def _drain(self) -> None:
        """Wait for everything already claimed to finish before the process exits."""
        if not self._tasks:
            return
        with log_context(worker=self.name):
            _logger.info("draining", in_flight=len(self._tasks))
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _register(self, status: WorkerStatus) -> None:
        """Upsert this worker's registry row."""
        catalog = self.services.host.catalog()
        async with session_scope(self.sessions) as session:
            found = await session.execute(sa.select(WorkerRow).where(WorkerRow.name == self.name))
            row = found.scalar_one_or_none()
            if row is None:
                row = WorkerRow(name=self.name, hostname=socket.gethostname(), version=_version())
                session.add(row)
            row.status = status
            row.version = _version()
            row.plugins = _plugin_counts(catalog)
            row.tags = list(self.tags)
            row.concurrency = self.concurrency
            row.catalog_digest = catalog.digest
            row.last_seen_at = utcnow()


def _plugin_counts(catalog: Catalog) -> dict[str, int]:
    """Record how many blocks each installed plugin contributed."""
    counts = dict.fromkeys(catalog.plugins, 0)
    for block in catalog.blocks:
        counts[block.plugin] = counts.get(block.plugin, 0) + 1
    return counts


def _version() -> str:
    """Report the code version a worker is running."""
    from dirigent_core import __version__

    return __version__


def install_signal_handlers(worker: Worker) -> None:
    """Ask the worker to drain on SIGTERM and SIGINT."""
    loop = asyncio.get_running_loop()
    for received in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(received, worker.request_stop)
        except NotImplementedError:  # pragma: no cover - only on platforms without loop signals
            signal.signal(received, lambda _signal, _frame: worker.request_stop())
