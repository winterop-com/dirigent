"""Wake-ups on a real PostgreSQL: NOTIFY on commit, one listener per process, and what they buy."""

import asyncio
import json
import random
import statistics
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import RunStatus
from dirigent_core import wakeups
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.claim import ClaimedUnit
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Base, Run, StepAttempt
from dirigent_core.plugins import PluginHost
from dirigent_core.worker import Worker
from engineblocks import EchoOperator, EngineTestPlugin, reset_blocks

pytestmark = pytest.mark.postgres

#: Long enough that anything finishing inside the test's patience was woken, not polled.
SLOW_POLL = timedelta(seconds=30)

PATIENCE = 5.0

#: How many runs each shape is measured over.
SAMPLES = 20


@pytest.fixture
def pg_settings(postgres_url: str, tmp_path: Any) -> Settings:
    """Settings pointed at the container."""
    return Settings(database_url=postgres_url, artifact_root=f"file://{tmp_path / 'artifacts'}")


@pytest.fixture
def pg_host() -> PluginHost:
    """The test blocks the rest of the lane drives."""
    return PluginHost({"engine-tests": EngineTestPlugin().contribute()})


@pytest.fixture
async def pg_engine(pg_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A clean schema per test."""
    engine = create_engine(pg_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    reset_blocks()
    yield engine
    await engine.dispose()


@pytest.fixture
def pg_sessions(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory every worker in a test shares."""
    return create_session_factory(pg_engine)


@pytest.fixture
async def listener(pg_settings: Settings) -> AsyncIterator[wakeups.Listener]:
    """This process's listener, connected before the test begins."""
    async with wakeups.listening(pg_settings.database_url) as held:
        assert held is not None
        await asyncio.wait_for(held.connected.wait(), timeout=PATIENCE)
        yield held


def one_step(code: str = "woken") -> PipelineDefinition:
    """A pipeline of one echo."""
    return PipelineDefinition(code=code, steps={"say": StepDefinition(block="test.echo", config={"value": "hi"})})


def chain(code: str = "chained") -> PipelineDefinition:
    """Three echoes in a row, each queued by the settle of the one before it."""
    return PipelineDefinition(
        code=code,
        steps={
            "first": StepDefinition(block="test.echo", config={"value": "a"}),
            "second": StepDefinition(block="test.echo", config={"value": "b"}, depends_on=["first"]),
            "third": StepDefinition(block="test.echo", config={"value": "c"}, depends_on=["second"]),
        },
    )


def unheard(channel: str, key: str | None = None) -> None:
    """Stand in for a delivery that never arrives."""


def deafen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discard every wake-up this process would hand its waiters."""
    monkeypatch.setattr(wakeups.hub, "deliver", unheard)
    monkeypatch.setattr(wakeups.hub, "deliver_everything", lambda: None)


async def start(sessions: Any, services: EngineServices, definition: PipelineDefinition) -> Run:
    """Save a pipeline and create one run of it in its own transaction."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return run


async def until_settled(sessions: async_sessionmaker[AsyncSession], run_id: Any, *, timeout: float) -> Run:
    """Wait for a run to succeed, and hand back its settled row."""
    async with asyncio.timeout(timeout):
        while True:
            async with sessions() as session:
                stored = await session.get(Run, run_id)
                assert stored is not None
                if stored.status is RunStatus.SUCCEEDED:
                    return stored
            await asyncio.sleep(0.005)


async def test_a_committed_run_notifies_the_listener(
    pg_sessions: Any, pg_settings: Settings, pg_host: PluginHost, listener: wakeups.Listener
) -> None:
    services = EngineServices.build(pg_settings, pg_host)
    mark = wakeups.hub.mark(wakeups.WORK)

    await start(pg_sessions, services, one_step())

    assert await wakeups.hub.wait(mark, timeout=PATIENCE) is True


async def test_a_rolled_back_run_notifies_nobody(
    pg_sessions: Any, pg_settings: Settings, pg_host: PluginHost, listener: wakeups.Listener
) -> None:
    services = EngineServices.build(pg_settings, pg_host)
    mark = wakeups.hub.mark(wakeups.WORK)

    with pytest.raises(RuntimeError):
        async with session_scope(pg_sessions) as session:
            version = await save_pipeline(session, one_step())
            await create_run(session, services, version)
            await session.flush()
            raise RuntimeError("abandon the transaction")

    assert await wakeups.hub.wait(mark, timeout=1.0) is False


async def test_an_explicit_publish_is_delivered_with_its_key_on_commit(
    pg_sessions: Any, listener: wakeups.Listener
) -> None:
    mark = wakeups.hub.mark(wakeups.SOURCES, "a-source")

    async with session_scope(pg_sessions) as session:
        await wakeups.publish(session, wakeups.SOURCES, "a-source")

    assert await wakeups.hub.wait(mark, timeout=PATIENCE) is True


async def test_two_workers_woken_by_one_notification_claim_it_once(
    pg_sessions: Any, pg_settings: Settings, pg_host: PluginHost
) -> None:
    services = EngineServices.build(pg_settings.model_copy(update={"claim_idle": SLOW_POLL}), pg_host)
    workers = [Worker(pg_sessions, services, name=f"woken-{index}", concurrency=1, sweeper=False) for index in (1, 2)]
    claims: dict[str, list[ClaimedUnit | None]] = {worker.name: [] for worker in workers}
    for worker in workers:
        claim = worker.engine.claim

        async def counted(
            *, now: Any = None, claim: Callable[..., Awaitable[ClaimedUnit | None]] = claim, name: str = worker.name
        ) -> ClaimedUnit | None:
            unit = await claim(now=now)
            claims[name].append(unit)
            return unit

        worker.engine.claim = counted  # type: ignore[method-assign]
    tasks = [asyncio.create_task(worker.run()) for worker in workers]
    try:
        async with asyncio.timeout(PATIENCE):
            while not all(claims.values()):
                await asyncio.sleep(0.01)
        for made in claims.values():
            made.clear()

        run = await start(pg_sessions, services, one_step())
        await until_settled(pg_sessions, run.id, timeout=PATIENCE)
        async with asyncio.timeout(PATIENCE):
            while not all(claims.values()):
                await asyncio.sleep(0.01)
    finally:
        for worker in workers:
            worker.request_stop()
        await asyncio.gather(*tasks)

    assert all(claims.values()), "one notification wakes every idle worker"
    taken = [unit for made in claims.values() for unit in made if unit is not None]
    assert len(taken) == 1, "SKIP LOCKED hands the one attempt to one of them"
    assert EchoOperator.calls == ["hi"]


async def test_the_listener_reconnects_after_its_connection_is_killed(
    pg_sessions: Any, pg_settings: Settings, pg_host: PluginHost, listener: wakeups.Listener
) -> None:
    async with pg_sessions() as session:
        pids = (
            await session.execute(
                sa.text("SELECT pid FROM pg_stat_activity WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()")
            )
        ).scalars()
        killed = [
            (await session.execute(sa.text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})).scalar_one()
            for pid in list(pids)
        ]
    assert killed == [True]
    async with asyncio.timeout(PATIENCE):
        while listener.connected.is_set():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(listener.connected.wait(), timeout=PATIENCE)
    services = EngineServices.build(pg_settings, pg_host)
    mark = wakeups.hub.mark(wakeups.WORK)

    await start(pg_sessions, services, one_step())

    assert await wakeups.hub.wait(mark, timeout=PATIENCE) is True


async def test_a_worker_that_hears_nothing_still_finds_the_work_on_its_poll(
    pg_sessions: Any, pg_settings: Settings, pg_host: PluginHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    deafen(monkeypatch)
    services = EngineServices.build(pg_settings.model_copy(update={"claim_idle": timedelta(milliseconds=100)}), pg_host)
    worker = Worker(pg_sessions, services, name="deaf", sweeper=False)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.sleep(0.2)
        run = await start(pg_sessions, services, chain())

        await until_settled(pg_sessions, run.id, timeout=PATIENCE)
    finally:
        worker.request_stop()
        await task


async def _measure(
    sessions: Any, services: EngineServices, definition: PipelineDefinition, idle: float
) -> tuple[list[float], list[float]]:
    """Run one pipeline repeatedly on an idle worker, and read each run's claim and end-to-end times in ms."""
    claimed: list[float] = []
    ended: list[float] = []
    worker = Worker(sessions, services, name="measured", sweeper=False)
    task = asyncio.create_task(worker.run())
    rng = random.Random(7)
    try:
        await start(sessions, services, definition.model_copy(update={"code": "warm-up"}))
        await asyncio.sleep(idle)
        for _ in range(SAMPLES):
            # A random phase against the worker's poll, so the poll-only numbers are a fair average.
            await asyncio.sleep(rng.uniform(0.0, idle))
            run = await start(sessions, services, definition)
            settled = await until_settled(sessions, run.id, timeout=PATIENCE * 4)
            async with sessions() as session:
                first = (
                    await session.execute(
                        sa.select(sa.func.min(StepAttempt.started_at)).where(StepAttempt.run_id == run.id)
                    )
                ).scalar_one()
            assert first is not None
            assert settled.finished_at is not None
            claimed.append((first - settled.created_at).total_seconds() * 1000)
            ended.append((settled.finished_at - settled.created_at).total_seconds() * 1000)
    finally:
        worker.request_stop()
        await task
    return claimed, ended


def _summary(samples: list[float]) -> dict[str, int]:
    """Reduce a list of milliseconds to what the docs state."""
    ordered = sorted(samples)
    return {
        "median_ms": round(statistics.median(ordered)),
        "p90_ms": round(ordered[int(len(ordered) * 0.9) - 1]),
        "max_ms": round(ordered[-1]),
    }


@pytest.mark.parametrize("heard", [True, False], ids=["wake-ups", "polling-only"])
async def test_the_latency_a_run_waits_for_its_worker(
    pg_sessions: Any, pg_settings: Settings, pg_host: PluginHost, monkeypatch: pytest.MonkeyPatch, heard: bool
) -> None:
    """Measure queue-to-claim for one step and end-to-end for three, with and without wake-ups.

    The records go to stdout, which ``pytest -s`` shows.
    """
    if not heard:
        deafen(monkeypatch)
    services = EngineServices.build(pg_settings, pg_host)
    idle = pg_settings.claim_idle.total_seconds()

    one_claimed, one_ended = await _measure(pg_sessions, services, one_step(), idle)
    _, three_ended = await _measure(pg_sessions, services, chain(), idle)

    measured = {
        "kind": "wakeup_latency",
        "mode": "wake-ups" if heard else "polling-only",
        "claim_idle_ms": round(idle * 1000),
        "samples": SAMPLES,
        "one_step_queue_to_claim": _summary(one_claimed),
        "one_step_end_to_end": _summary(one_ended),
        "three_step_end_to_end": _summary(three_ended),
    }
    print(json.dumps(measured))
    if heard:
        assert statistics.median(one_claimed) < idle * 1000 / 4
        assert statistics.median(three_ended) < idle * 1000
