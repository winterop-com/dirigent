"""The load lane: what the log path costs, measured against a real PostgreSQL.

Fifty attempts log five thousand lines each while a reader tails the run, and every number
this file produces is written to stdout as one NDJSON record of kind ``load``. Nothing here
is part of the gate: it is run on purpose, with ``make load``, and read.
"""

import asyncio
import platform
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, MutableMapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool

from dirigent_cli.local import (
    LOCAL_LOG_PAGE,
    _new_logs,  # pyright: ignore[reportPrivateUsage] - the read the lane measures
)
from dirigent_client.enums import RunStatus
from dirigent_core import protocol, telemetry
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.engine import EngineServices, context
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Base, LogEntry, Run
from dirigent_core.plugins import PluginHost
from dirigent_core.worker import Worker
from dirigent_server.routes.runs import (
    _log_page,  # pyright: ignore[reportPrivateUsage] - the read the lane measures
    _story_read,  # pyright: ignore[reportPrivateUsage] - the read the lane measures
)
from loadblocks import ChattyOperator, LoadTestPlugin

pytestmark = pytest.mark.load

#: The one step's fan-out, and what each of its elements logs.
ITEMS: Final = 50
LINES: Final = 5_000
PACE: Final = timedelta(milliseconds=1)

#: The same pace, as the step's config spells it.
PACE_TERM: Final = "1ms"

STEP: Final = "chat"

#: How often the reader, the pool sampler and the gauge sampler look. Every latency this
#: file reports is granular to this interval.
SAMPLE_SECONDS: Final = 0.05

#: How wide a page the reader pulls, and how wide the page the API's own default serves.
READER_PAGE: Final = 1_000
API_PAGE: Final = 200

#: How many times each settled read is timed.
READS: Final = 10

#: How long the run is given before the lane gives up on it.
RUN_DEADLINE_SECONDS: Final = 600.0

#: What SQLAlchemy's pool timeout says, which is what a starved pool looks like in the log.
POOL_TIMEOUT_MARK: Final = "QueuePool limit"


def _percentile(values: Sequence[float], fraction: float) -> float:
    """The value at a fraction of the sorted sample, or zero when there is no sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _emit(name: str, value: float, unit: str, **data: Any) -> None:
    """Write one measurement to stdout as an NDJSON record."""
    print(protocol.as_json(protocol.make("load", name=name, value=value, unit=unit, **data)), flush=True)


def _emit_pair(name: str, values: Sequence[float], unit: str, **data: Any) -> tuple[float, float]:
    """Write the p50 and the p95 of one sample, and hand both back."""
    p50, p95 = _percentile(values, 0.5), _percentile(values, 0.95)
    _emit(f"{name}_p50", p50, unit, samples=len(values), **data)
    _emit(f"{name}_p95", p95, unit, samples=len(values), **data)
    return p50, p95


class PoolWatch:
    """What the connection pools of the worker processes did during the burst."""

    def __init__(self) -> None:
        """Start with nothing watched and every count at zero."""
        self.pools: list[QueuePool] = []
        self.checkouts = 0
        self.checked_out_max = 0
        self.overflow_max = 0

    def watch(self, engine: AsyncEngine) -> None:
        """Count every checkout on one engine's pool, and sample that pool from now on."""
        pool = engine.sync_engine.pool
        assert isinstance(pool, QueuePool)
        self.pools.append(pool)
        event.listen(pool, "checkout", self._checkout)

    def _checkout(self, _connection: Any, _record: Any, _proxy: Any) -> None:
        """Count one connection handed to a caller."""
        self.checkouts += 1

    def sample(self) -> None:
        """Read every watched pool's level once."""
        for pool in self.pools:
            self.checked_out_max = max(self.checked_out_max, pool.checkedout())
            self.overflow_max = max(self.overflow_max, pool.overflow())


class PoolTimeouts:
    """Counts the pool timeouts the process logged, and swallows the process log itself.

    Rendering what two workers say under the burst costs more than what is being measured,
    so the processor chain is replaced by one that counts and drops.
    """

    def __init__(self) -> None:
        """Start with no timeouts seen."""
        self.count = 0

    def __enter__(self) -> "PoolTimeouts":
        """Take over the structlog configuration for the length of the run."""
        structlog.configure(processors=[self._count], logger_factory=structlog.ReturnLoggerFactory())
        return self

    def __exit__(self, *_exception: object) -> None:
        """Give structlog back the configuration the rest of the suite runs on."""
        structlog.reset_defaults()

    def _count(self, _logger: Any, _name: str, event: MutableMapping[str, Any]) -> Mapping[str, Any]:
        """Count an event that names a starved pool, then drop every event."""
        if any(isinstance(value, str) and POOL_TIMEOUT_MARK in value for value in event.values()):
            self.count += 1
        raise structlog.DropEvent


@pytest.fixture
def load_settings(postgres_url: str, tmp_path: Path) -> Settings:
    """One worker process's settings: concurrency 25, a pool that covers it, and a wide quota.

    The quota is per attempt, and the lane measures the whole of what each one logs.
    """
    return Settings(
        database_url=postgres_url,
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        worker_concurrency=25,
        database_pool_size=29,
        database_max_overflow=4,
        sweep_interval=timedelta(seconds=5),
        log_entries_per_attempt=10_000,
    )


@pytest.fixture
def load_services(load_settings: Settings) -> EngineServices:
    """Engine services carrying the one block the lane runs."""
    return EngineServices.build(load_settings, PluginHost({"load-tests": LoadTestPlugin().contribute()}))


@pytest.fixture
async def load_engine(load_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A clean schema, and the engine the lane's own reads go through."""
    engine = create_engine(load_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    ChattyOperator.elapsed.clear()
    yield engine
    await engine.dispose()


@pytest.fixture
def load_sessions(load_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory the reader, the poller and the settled reads share."""
    return create_session_factory(load_engine)


@pytest.fixture
def spy_on_flushes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[int, float]]]:
    """Record how many entries each flush carried and how long its transaction took."""
    flushes: list[tuple[int, float]] = []
    original = Engine._flush  # pyright: ignore[reportPrivateUsage] - the seam every flush goes through

    async def flush(self: Engine, logger: context.BufferedLogger) -> None:
        buffered = len(logger.entries)
        started = time.monotonic()
        await original(self, logger)
        if buffered:
            flushes.append((buffered, time.monotonic() - started))

    monkeypatch.setattr(Engine, "_flush", flush)
    yield flushes


def chatty_pipeline() -> PipelineDefinition:
    """One step, fanned out over the items, each element logging its lines at the pace."""
    return PipelineDefinition(
        code="load-chatty",
        steps={
            STEP: StepDefinition(
                block="load.chatty",
                for_each=[f"item-{index}" for index in range(ITEMS)],
                config={"lines": LINES, "pace": PACE_TERM},
            )
        },
    )


async def _read_lines(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, stop: asyncio.Event, lags: list[float]
) -> None:
    """Tail the run the way the API's stream does, recording how old each row was when seen.

    A tick drains what is there rather than taking one page, so what the lag measures is how
    long a line took to land and not how fast a single page can be pulled.
    """
    cursor = 0
    async with sessions() as session:
        while not stop.is_set():
            while True:
                page = await _log_page(session, run_id, cursor, READER_PAGE, None)
                seen_at = datetime.now(UTC)
                for entry in page.items:
                    lags.append((seen_at - entry.created_at).total_seconds())
                    cursor = max(cursor, entry.id)
                await session.rollback()
                if len(page.items) < READER_PAGE:
                    break
            await asyncio.sleep(SAMPLE_SECONDS)


async def _sample(watch: PoolWatch, stop: asyncio.Event, peaks: dict[str, int]) -> None:
    """Read the pools and the engine's gauges on the sampling interval."""
    while not stop.is_set():
        watch.sample()
        peaks["queue_depth"] = max(peaks["queue_depth"], telemetry.gauges.queue_depth)
        peaks["waiting"] = max(peaks["waiting"], telemetry.gauges.waiting)
        peaks["in_flight"] = max(peaks["in_flight"], telemetry.gauges.in_flight)
        await asyncio.sleep(SAMPLE_SECONDS)


async def _await_terminal(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> Run:
    """Poll the run until it settles, and hand back the settled row."""
    deadline = time.monotonic() + RUN_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        async with sessions() as session:
            stored = await session.get(Run, run_id)
            assert stored is not None
            if stored.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
                return stored
        await asyncio.sleep(0.25)
    raise AssertionError(f"the run did not settle within {RUN_DEADLINE_SECONDS:.0f}s")


async def _timed(work: Callable[[], Awaitable[object]], times: int) -> list[float]:
    """Run one read a number of times, and hand back what each one took."""
    seconds: list[float] = []
    for _ in range(times):
        started = time.monotonic()
        await work()
        seconds.append(time.monotonic() - started)
    return seconds


async def _paged_local_read(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> int:
    """Read a run's whole log the way ``dg run --local`` does, and say how many lines it took."""
    cursor, seen, more = 0, 0, True
    while more:
        lines, cursor, more = await _new_logs(sessions, run_id, cursor, {})
        seen += len(lines)
    return seen


async def _explain(session: AsyncSession, run_id: UUID) -> list[str]:
    """Ask PostgreSQL what the step-filtered page costs, and hand back the plan's lines."""
    statement = (
        sa.select(LogEntry)
        .where(LogEntry.run_id == run_id, LogEntry.id > 0, LogEntry.step_name == STEP)
        .order_by(LogEntry.id)
        .limit(API_PAGE + 1)
    )
    compiled = statement.compile(dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True})
    rows = await session.execute(sa.text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}"))
    return [str(line) for line in rows.scalars()]


def _revision() -> str:
    """The commit the numbers were measured on."""
    found = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False)
    return found.stdout.strip() or "unknown"


async def test_fifty_chatty_attempts_on_two_workers(
    load_settings: Settings,
    load_services: EngineServices,
    load_sessions: async_sessionmaker[AsyncSession],
    spy_on_flushes: list[tuple[int, float]],
) -> None:
    """Fifty attempts logging five thousand lines each, across two workers on one database."""
    worker_engines = [create_engine(load_settings) for _ in range(2)]
    worker_sessions = [create_session_factory(engine) for engine in worker_engines]
    watch = PoolWatch()
    for engine in worker_engines:
        watch.watch(engine)
    workers = [
        Worker(worker_sessions[0], load_services, name="load-a", sweeper=True),
        Worker(worker_sessions[1], load_services, name="load-b", sweeper=False),
    ]

    async with session_scope(load_sessions) as session:
        version = await save_pipeline(session, chatty_pipeline())
        created = await create_run(session, load_services, version)
    assert created is not None

    stop = asyncio.Event()
    lags: list[float] = []
    peaks = {"queue_depth": 0, "waiting": 0, "in_flight": 0}
    with PoolTimeouts() as timeouts:
        running = [asyncio.create_task(worker.run()) for worker in workers]
        watching = [
            asyncio.create_task(_read_lines(load_sessions, created.id, stop, lags)),
            asyncio.create_task(_sample(watch, stop, peaks)),
        ]
        try:
            run = await _await_terminal(load_sessions, created.id)
        finally:
            for worker in workers:
                worker.request_stop()
            await asyncio.gather(*running)
            stop.set()
            await asyncio.gather(*watching)

    async with load_sessions() as session:
        counted = await session.execute(
            sa.select(sa.func.count()).select_from(LogEntry).where(LogEntry.run_id == run.id)
        )
        rows = int(counted.scalar_one())
        highest = await session.execute(sa.select(sa.func.max(LogEntry.id)).where(LogEntry.run_id == run.id))
        last = int(highest.scalar_one())

    assert run.started_at is not None
    assert run.finished_at is not None
    span = (run.finished_at - run.started_at).total_seconds()

    _emit("rows_per_second", rows / span, "rows/s", rows=rows, seconds=span)

    _emit("flush_count", len(spy_on_flushes), "flushes")
    _emit_pair("rows_per_flush", [float(entries) for entries, _ in spy_on_flushes], "rows")
    _emit_pair("flush_seconds", [seconds for _, seconds in spy_on_flushes], "seconds")

    _, visible_p95 = _emit_pair(
        "visible_seconds",
        lags,
        "seconds",
        fields={"granularity_ms": int(SAMPLE_SECONDS * 1000), "page": READER_PAGE},
    )

    _emit("checkouts_total", watch.checkouts, "checkouts", fields={"pools": len(watch.pools)})
    _emit(
        "checked_out_max", watch.checked_out_max, "connections", fields={"pool_size": load_settings.database_pool_size}
    )
    _emit(
        "overflow_max", watch.overflow_max, "connections", fields={"max_overflow": load_settings.database_max_overflow}
    )
    _emit("pool_timeouts", timeouts.count, "timeouts", fields={"seen_as": POOL_TIMEOUT_MARK})

    _emit("queue_depth_peak", peaks["queue_depth"], "attempts")
    _emit("waiting_peak", peaks["waiting"], "attempts")
    _emit("in_flight_peak", peaks["in_flight"], "calls", fields={"workers": len(workers)})

    cold = await _timed(lambda: _story_read(load_sessions, run.id, 0, True), READS)
    warm = await _timed(lambda: _story_read(load_sessions, run.id, last, None), READS)
    _emit("story_read_seconds_cold_p50", _percentile(cold, 0.5), "seconds", samples=len(cold))
    _emit("story_read_seconds_cold_max", max(cold), "seconds", samples=len(cold))
    _emit("story_read_seconds_warm_p50", _percentile(warm, 0.5), "seconds", samples=len(warm))
    _emit("story_read_seconds_warm_max", max(warm), "seconds", samples=len(warm))

    async with load_sessions() as session:
        pages = await _timed(lambda: _log_page(session, run.id, 0, API_PAGE, None), READS)
        step_pages = await _timed(lambda: _log_page(session, run.id, 0, API_PAGE, STEP), READS)
        plan = await _explain(session, run.id)
    _emit("log_page_seconds", _percentile(pages, 0.5), "seconds", samples=len(pages), fields={"limit": API_PAGE})
    _emit(
        "log_page_step_seconds",
        _percentile(step_pages, 0.5),
        "seconds",
        samples=len(step_pages),
        fields={"limit": API_PAGE, "step": STEP},
    )
    print(protocol.as_json(protocol.make("load.plan", name="log_page_step", plan=plan)), flush=True)

    local = await _timed(lambda: _paged_local_read(load_sessions, run.id), 1)
    _emit("local_new_logs_seconds", local[0], "seconds", fields={"rows": rows, "page": LOCAL_LOG_PAGE})

    paced = LINES * PACE.total_seconds()
    recording = [max(0.0, seconds - paced) for seconds in ChattyOperator.elapsed]
    _emit(
        "record_seconds",
        _percentile(recording, 0.5),
        "seconds",
        samples=len(recording),
        fields={"lines": LINES, "pace_ms": int(PACE.total_seconds() * 1000)},
    )

    print(
        protocol.as_json(
            protocol.make(
                "load.summary",
                message="the log path under fifty chatty attempts",
                revision=_revision(),
                host=f"{platform.node()} {platform.machine()} {platform.system()} {platform.release()}",
                python=platform.python_version(),
                rows=rows,
                items=ITEMS,
                lines=LINES,
                seconds=span,
                settings={
                    "worker_concurrency": load_settings.worker_concurrency,
                    "database_pool_size": load_settings.database_pool_size,
                    "database_max_overflow": load_settings.database_max_overflow,
                    "log_flush_interval": str(load_settings.log_flush_interval),
                    "sweep_interval": str(load_settings.sweep_interval),
                    "workers": len(workers),
                    "log_entries_per_attempt": load_settings.log_entries_per_attempt,
                    "log_flush_batch": load_settings.log_flush_batch,
                },
            )
        ),
        flush=True,
    )

    for engine in worker_engines:
        await engine.dispose()

    assert run.status is RunStatus.SUCCEEDED, run.error
    assert rows == ITEMS * LINES, "an attempt lost lines it logged"
    assert timeouts.count == 0, "a worker went without a connection under the burst"
    assert visible_p95 < load_settings.log_flush_interval.total_seconds() + 2.0, (
        "a line took longer to become visible than a flush interval and its slack"
    )
