"""Wake-ups on SQLite: the in-process hub, the flush observer, and the fallback behind them."""

import asyncio
import threading
import time
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus, TriggerKind
from dirigent_core import wakeups
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import Attribution, create_run, save_pipeline
from dirigent_core.models import Run, StepAttempt, utcnow
from dirigent_core.plugins import PluginHost
from dirigent_core.worker import Worker
from dirigent_plugin import RemoteHandle

#: Long enough that a run finishing inside the test's patience was woken, not polled.
SLOW_POLL = timedelta(seconds=30)

PATIENCE = 5.0


def one_step(code: str = "woken") -> PipelineDefinition:
    """A pipeline of one echo, the smallest unit of work a worker can be woken for."""
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


async def start(sessions: Any, services: EngineServices, definition: PipelineDefinition, **extra: Any) -> Run:
    """Save a pipeline and create one run of it in its own transaction."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version, **extra)
    assert run is not None
    return run


async def status_of(sessions: async_sessionmaker[AsyncSession], run_id: Any) -> RunStatus:
    """Read a run's status fresh."""
    async with sessions() as session:
        stored = await session.get(Run, run_id)
        assert stored is not None
        return stored.status


async def until_settled(sessions: async_sessionmaker[AsyncSession], run_id: Any, *, timeout: float) -> float:
    """Wait for a run to succeed, and say how long it took."""
    began = time.monotonic()
    async with asyncio.timeout(timeout):
        while await status_of(sessions, run_id) is not RunStatus.SUCCEEDED:
            await asyncio.sleep(0.01)
    return time.monotonic() - began


async def test_a_mark_hears_a_publish_made_after_it() -> None:
    mark = wakeups.hub.mark("test_channel")

    wakeups.hub.deliver("test_channel")

    assert await wakeups.hub.wait(mark, timeout=0.01) is True


async def test_a_mark_with_nothing_published_times_out() -> None:
    mark = wakeups.hub.mark("test_channel")

    assert await wakeups.hub.wait(mark, timeout=0.01) is False


async def test_a_keyed_publish_wakes_its_key_and_the_whole_channel_but_not_another_key() -> None:
    mine = wakeups.hub.mark("test_channel", "mine")
    theirs = wakeups.hub.mark("test_channel", "theirs")
    everyone = wakeups.hub.mark("test_channel")

    wakeups.hub.deliver("test_channel", "mine")

    assert await wakeups.hub.wait(mine, timeout=0.01) is True
    assert await wakeups.hub.wait(everyone, timeout=0.01) is True
    assert await wakeups.hub.wait(theirs, timeout=0.01) is False


async def test_a_waiter_already_waiting_is_woken_by_a_publish() -> None:
    mark = wakeups.hub.mark("test_channel")
    waiting = asyncio.create_task(wakeups.hub.wait(mark, timeout=PATIENCE))
    await asyncio.sleep(0)

    wakeups.hub.deliver("test_channel")

    assert await asyncio.wait_for(waiting, timeout=1.0) is True


async def test_a_publish_from_another_thread_wakes_a_waiter_on_this_loop() -> None:
    mark = wakeups.hub.mark("test_channel")
    waiting = asyncio.create_task(wakeups.hub.wait(mark, timeout=PATIENCE))
    await asyncio.sleep(0)

    thread = threading.Thread(target=wakeups.hub.deliver, args=("test_channel",))
    thread.start()
    thread.join()

    assert await asyncio.wait_for(waiting, timeout=1.0) is True


async def test_delivering_everything_wakes_every_topic() -> None:
    first = wakeups.hub.mark("test_channel", "one")
    second = wakeups.hub.mark("other_channel")

    wakeups.hub.deliver_everything()

    assert await wakeups.hub.wait(first, timeout=0.01) is True
    assert await wakeups.hub.wait(second, timeout=0.01) is True


async def test_a_committed_run_wakes_a_waiter_for_work(sessions: Any, services: EngineServices) -> None:
    mark = wakeups.hub.mark(wakeups.WORK)

    await start(sessions, services, one_step())

    assert await wakeups.hub.wait(mark, timeout=0.01) is True


async def test_a_rolled_back_run_wakes_nobody(sessions: Any, services: EngineServices) -> None:
    mark = wakeups.hub.mark(wakeups.WORK)

    with pytest.raises(RuntimeError):
        async with session_scope(sessions) as session:
            version = await save_pipeline(session, one_step())
            await create_run(session, services, version)
            await session.flush()
            raise RuntimeError("abandon the transaction")

    assert await wakeups.hub.wait(mark, timeout=0.05) is False


async def test_a_run_queued_for_later_wakes_nobody_for_work(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, one_step())
    mark = wakeups.hub.mark(wakeups.WORK)

    async with session_scope(sessions) as session:
        attempt = (await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))).scalar_one()
        attempt.available_at = utcnow() + timedelta(hours=1)

    assert await wakeups.hub.wait(mark, timeout=0.01) is False


async def test_settling_an_attempt_publishes_its_run(sessions: Any, engine: Engine, services: EngineServices) -> None:
    run = await start(sessions, services, one_step())
    unit = await engine.claim()
    assert unit is not None
    mark = wakeups.settled_mark(run.id)

    await engine.run_unit(unit)

    assert await wakeups.wait_settled(mark, timeout=0.01) is True


async def test_a_publish_outside_the_observer_is_held_until_commit(sessions: Any) -> None:
    mark = wakeups.hub.mark(wakeups.SOURCES, "a-source")

    async with session_scope(sessions) as session:
        await wakeups.publish(session, wakeups.SOURCES, "a-source")
        assert await wakeups.hub.wait(mark, timeout=0.01) is False

    assert await wakeups.hub.wait(mark, timeout=0.01) is True


async def test_an_idle_worker_is_woken_by_a_run_rather_than_its_poll(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(settings.model_copy(update={"claim_idle": SLOW_POLL}), host)
    worker = Worker(sessions, services, name="woken", sweeper=False)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.sleep(0.2)
        run = await start(sessions, services, chain())

        took = await until_settled(sessions, run.id, timeout=PATIENCE)
    finally:
        worker.request_stop()
        await asyncio.wait_for(task, timeout=PATIENCE)

    assert took < PATIENCE


async def test_a_worker_that_hears_nothing_still_finds_the_work_on_its_poll(
    sessions: Any, settings: Settings, host: PluginHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    deafen(monkeypatch)
    services = EngineServices.build(settings.model_copy(update={"claim_idle": timedelta(milliseconds=100)}), host)
    worker = Worker(sessions, services, name="deaf", sweeper=False)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.sleep(0.2)
        run = await start(sessions, services, chain())

        await until_settled(sessions, run.id, timeout=PATIENCE)
    finally:
        worker.request_stop()
        await asyncio.wait_for(task, timeout=PATIENCE)


async def test_a_child_settling_brings_its_waiting_parent_probe_forward(
    sessions: Any, engine: Engine, services: EngineServices
) -> None:
    parent = await start(sessions, services, one_step("parent"))
    later = utcnow() + timedelta(hours=1)
    async with session_scope(sessions) as session:
        waiting = (await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == parent.id))).scalar_one()
        waiting.status = AttemptStatus.WAITING
        waiting.next_poll_at = later
    child = await start(
        sessions,
        services,
        one_step("child"),
        attribution=Attribution(kind=TriggerKind.PIPELINE, id=parent.id, label="parent"),
    )
    async with session_scope(sessions) as session:
        stored = await session.get(StepAttempt, waiting.id)
        assert stored is not None
        stored.remote_handle = RemoteHandle(block_id="pipeline.run", ref=str(child.id)).model_dump(mode="json")
    unit = await engine.claim()
    assert unit is not None
    assert unit.run_id == child.id
    mark = wakeups.hub.mark(wakeups.WORK)

    await engine.run_unit(unit)

    async with sessions() as session:
        probed = await session.get(StepAttempt, waiting.id)
        assert probed is not None
        assert probed.next_poll_at is not None
        assert probed.next_poll_at < later
    assert await wakeups.hub.wait(mark, timeout=0.01) is True


async def test_a_parent_waiting_on_another_run_is_left_alone(sessions: Any, services: EngineServices) -> None:
    parent = await start(sessions, services, one_step("parent"))
    later = utcnow() + timedelta(hours=1)
    async with session_scope(sessions) as session:
        waiting = (await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == parent.id))).scalar_one()
        waiting.status = AttemptStatus.WAITING
        waiting.next_poll_at = later
        waiting.remote_handle = RemoteHandle(block_id="pipeline.run", ref="somebody-else").model_dump(mode="json")
    child = await start(
        sessions,
        services,
        one_step("child"),
        attribution=Attribution(kind=TriggerKind.PIPELINE, id=parent.id, label="parent"),
    )

    async with session_scope(sessions) as session:
        await wakeups.hasten_parent(session, child, utcnow())

    async with sessions() as session:
        untouched = await session.get(StepAttempt, waiting.id)
        assert untouched is not None
        assert untouched.next_poll_at == later


async def test_a_run_nobody_started_hastens_nothing(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, one_step())

    async with session_scope(sessions) as session:
        await wakeups.hasten_parent(session, run, utcnow())


async def test_sqlite_needs_no_listener() -> None:
    async with wakeups.listening("sqlite+aiosqlite:///somewhere.db") as listener:
        assert listener is None
