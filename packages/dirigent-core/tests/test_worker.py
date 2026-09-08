"""Tests for the worker loop: claiming, draining, heartbeating, and the registry row."""

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from dirigent_client.enums import AttemptStatus, RunStatus, WorkerStatus
from dirigent_core import telemetry
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.claim import ClaimedUnit
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.recovery import reap_workers
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Run, StepAttempt, utcnow
from dirigent_core.models import Worker as WorkerRow
from dirigent_core.plugins import PluginHost
from dirigent_core.worker import Chore, Worker, default_worker_name
from engineblocks import EchoOperator


def fan_out(count: int) -> PipelineDefinition:
    """A pipeline whose one step maps over a list, so a worker has parallel work to do."""
    return PipelineDefinition(
        code="worker-batch",
        steps={
            "push": StepDefinition(
                block="test.echo",
                for_each=[f"item-{index}" for index in range(count)],
                config={"value": "${item}"},
            )
        },
    )


async def create(sessions: Any, services: EngineServices, definition: PipelineDefinition) -> Run:
    """Save a pipeline and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return run


async def until(condition: Any, *, timeout: float = 10.0) -> None:
    """Wait for a condition to hold, failing the test rather than hanging forever."""
    async with asyncio.timeout(timeout):
        while not await condition():
            await asyncio.sleep(0.01)


def fast(settings: Settings) -> Settings:
    """Shorten every cadence a worker loop runs on."""
    return settings.model_copy(
        update={
            "claim_idle": timedelta(milliseconds=10),
            "heartbeat": timedelta(seconds=1),
            "sweep_interval": timedelta(milliseconds=50),
            "lease": timedelta(seconds=5),
        }
    )


async def test_a_worker_drains_a_run_and_then_stops(sessions: Any, settings: Settings, host: PluginHost) -> None:
    services = EngineServices.build(fast(settings), host)
    run = await create(sessions, services, fan_out(4))
    worker = Worker(sessions, services, name="drainer", concurrency=2, sweeper=False)

    task = asyncio.create_task(worker.run())

    async def finished() -> bool:
        async with sessions() as session:
            stored = await session.get(Run, run.id)
            return stored is not None and stored.status is RunStatus.SUCCEEDED

    await until(finished)
    worker.request_stop()
    await task

    assert sorted(EchoOperator.calls) == ["item-0", "item-1", "item-2", "item-3"]
    assert worker.in_flight == set()


async def test_the_worker_registers_and_then_marks_itself_stopped(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(fast(settings), host)
    worker = Worker(sessions, services, name="registered", concurrency=3, tags=["docker"], sweeper=False)
    task = asyncio.create_task(worker.run())

    async def registered() -> bool:
        async with sessions() as session:
            found = await session.execute(sa.select(WorkerRow).where(WorkerRow.name == "registered"))
            row = found.scalar_one_or_none()
            return row is not None and row.status is WorkerStatus.RUNNING

    await until(registered)
    async with sessions() as session:
        found = await session.execute(sa.select(WorkerRow).where(WorkerRow.name == "registered"))
        row = found.scalar_one()
    assert row.concurrency == 3
    assert row.tags == ["docker"]
    assert row.plugins == {"engine-tests": 11}
    assert row.catalog_digest == services.host.catalog().digest
    assert row.hostname

    worker.request_stop()
    await task
    async with sessions() as session:
        found = await session.execute(sa.select(WorkerRow).where(WorkerRow.name == "registered"))
        assert found.scalar_one().status is WorkerStatus.STOPPED


async def test_a_draining_worker_claims_nothing_new(sessions: Any, settings: Settings, host: PluginHost) -> None:
    services = EngineServices.build(fast(settings), host)
    await create(sessions, services, fan_out(3))
    worker = Worker(sessions, services, name="stopped-early", sweeper=False)
    worker.request_stop()
    await worker.run()
    assert EchoOperator.calls == []


async def test_the_heartbeat_keeps_a_lease_alive(sessions: Any, settings: Settings, host: PluginHost) -> None:
    services = EngineServices.build(fast(settings), host)
    await create(sessions, services, fan_out(1))
    worker = Worker(sessions, services, name="beating", sweeper=False)
    unit = await worker.engine.claim()
    assert unit is not None

    async with sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        before = attempt.lease_expires_at
    assert before is not None

    later = before + timedelta(seconds=30)
    assert await worker.engine.heartbeat([unit.attempt_id], now=later) == {unit.attempt_id}
    async with sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.lease_expires_at is not None
        assert attempt.lease_expires_at > before


async def test_a_lease_held_by_another_worker_is_not_refreshed(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(fast(settings), host)
    await create(sessions, services, fan_out(1))
    mine = Worker(sessions, services, name="mine", sweeper=False)
    unit = await mine.engine.claim()
    assert unit is not None
    theirs = Worker(sessions, services, name="theirs", sweeper=False)
    assert await theirs.engine.heartbeat([unit.attempt_id]) == set()
    assert await theirs.engine.heartbeat([]) == set()


async def test_a_worker_abandons_a_unit_whose_heartbeat_returns_zero(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """A heartbeat that comes back empty means the work is somebody else's now."""
    services = EngineServices.build(fast(settings), host)
    await create(sessions, services, fan_out(1))
    worker = Worker(sessions, services, name="losing", sweeper=False)
    unit = await worker.engine.claim()
    assert unit is not None

    started = asyncio.Event()
    release = asyncio.Event()

    async def never_finishes(_unit: ClaimedUnit, *, now: datetime | None = None) -> None:
        started.set()
        await release.wait()

    worker.engine.run_unit = never_finishes  # type: ignore[assignment]
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    worker.in_flight.add(unit.attempt_id)
    # Driving the worker's own bookkeeping directly: the test plugin has no block that
    # blocks forever.
    task = asyncio.create_task(worker._execute(unit, semaphore))  # pyright: ignore[reportPrivateUsage]
    worker._tasks.add(task)  # pyright: ignore[reportPrivateUsage]
    worker._running[unit.attempt_id] = task  # pyright: ignore[reportPrivateUsage]
    await started.wait()

    # Somebody else took the lease while this worker was mid-call.
    async with session_scope(sessions) as session:
        stolen = await session.get(StepAttempt, unit.attempt_id)
        assert stolen is not None
        stolen.lease_owner = "the other worker"

    claimed = set(worker.in_flight)
    held = await worker.engine.heartbeat(list(claimed))
    assert held == set()
    worker._abandon(claimed - held)  # pyright: ignore[reportPrivateUsage]

    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert unit.attempt_id not in worker.in_flight
    release.set()


async def test_the_sweeper_recovers_what_a_dead_worker_left_behind(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    brief = fast(settings).model_copy(
        update={"lease": timedelta(seconds=5), "sweep_interval": timedelta(milliseconds=20)}
    )
    services = EngineServices.build(brief, host)
    await create(sessions, services, fan_out(1))
    dead = Worker(sessions, services, name="dead", sweeper=False)
    unit = await dead.engine.claim()
    assert unit is not None

    # The dead worker's lease is backdated, which is what the sweeper looks for.
    async with session_scope(sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = attempt.lease_expires_at - timedelta(hours=1) if attempt.lease_expires_at else None

    alive = Worker(sessions, services, name="alive", sweeper=True)
    task = asyncio.create_task(alive.run())

    async def recovered() -> bool:
        async with sessions() as session:
            attempt = await session.get(StepAttempt, unit.attempt_id)
            return attempt is not None and attempt.status is AttemptStatus.SUCCEEDED

    await until(recovered)
    alive.request_stop()
    await task


async def register(sessions: Any, name: str, *, age: timedelta) -> None:
    """Put a registry row in the database as a worker of a given age would have left it."""
    async with session_scope(sessions) as session:
        session.add(
            WorkerRow(
                name=name,
                hostname=f"host-of-{name}",
                version="0.0.0",
                status=WorkerStatus.RUNNING,
                last_seen_at=utcnow() - age,
            )
        )


async def names_in_registry(sessions: Any) -> list[str]:
    """Read the registry the way an operator's listing does."""
    async with sessions() as session:
        rows = await session.execute(sa.select(WorkerRow).order_by(WorkerRow.name))
        return [row.name for row in rows.scalars()]


async def test_a_stale_registry_row_is_reaped_and_a_fresh_one_is_left_alone(sessions: Any) -> None:
    """A worker that was killed rather than drained leaves a row that says ``running`` forever."""
    age = timedelta(seconds=900)
    await register(sessions, "still-beating", age=timedelta(seconds=5))
    await register(sessions, "sigkilled", age=age + timedelta(seconds=1))

    async with session_scope(sessions) as session:
        assert await reap_workers(session, older_than=age) == ["sigkilled"]
    assert await names_in_registry(sessions) == ["still-beating"]

    # And the next sweep finds nothing.
    async with session_scope(sessions) as session:
        assert await reap_workers(session, older_than=age) == []
    assert await names_in_registry(sessions) == ["still-beating"]


async def test_the_sweeper_reaps_the_registry_without_reaping_the_worker_running_it(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """The sweep loop is where reaping actually happens, and it must spare its own row."""
    # Five seconds rather than one: an age shorter than the heartbeat cadence would make
    # this test race its own worker.
    services = EngineServices.build(fast(settings).model_copy(update={"stale_worker": timedelta(seconds=5)}), host)
    await register(sessions, "long-gone", age=timedelta(seconds=30))

    sweeper = Worker(sessions, services, name="the-sweeper", sweeper=True)
    task = asyncio.create_task(sweeper.run())

    async def gone() -> bool:
        return "long-gone" not in await names_in_registry(sessions)

    await until(gone)
    sweeper.request_stop()
    await task

    assert "the-sweeper" in await names_in_registry(sessions), "a sweeper must not reap the row it keeps fresh"


async def test_the_sweeper_reports_every_registered_worker_heartbeat_age(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """A worker that stopped reporting is only visible as an age, so every sweeper reports all of them."""
    telemetry.gauges.observe(heartbeat_ages={})
    await register(sessions, "long-quiet", age=timedelta(minutes=5))

    sweeper = Worker(sessions, EngineServices.build(fast(settings), host), name="the-sweeper", sweeper=True)
    task = asyncio.create_task(sweeper.run())

    async def both_reported() -> bool:
        return {"the-sweeper", "long-quiet"} <= set(telemetry.gauges.heartbeat_ages)

    await until(both_reported)
    sweeper.request_stop()
    await task

    ages = telemetry.gauges.heartbeat_ages
    assert ages["the-sweeper"] < 60
    assert 300 <= ages["long-quiet"] < 360


def test_a_worker_names_itself_after_where_it_runs() -> None:
    name = default_worker_name()
    assert "-" in name
    assert name.rsplit("-", 1)[1].isdigit()


def test_settings_supply_the_defaults_a_worker_does_not_override(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    configured = settings.model_copy(
        update={"worker_name": "from-config", "worker_concurrency": 5, "worker_tags": ["gpu"]}
    )
    worker = Worker(sessions, EngineServices.build(configured, host))
    assert worker.name == "from-config"
    assert worker.concurrency == 5
    assert worker.tags == ["gpu"]


async def test_a_stopping_worker_ends_its_loops_by_agreement_not_cancellation(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """The background loops wake on the stop flag and return; nothing is cancelled mid-await.

    The cadences sit far beyond the test's patience, so a prompt return proves the wake came
    from the flag rather than a timer -- a cancel landing inside a database await is what
    used to leak a rollback traceback into a run's output.
    """
    slow = settings.model_copy(
        update={
            "heartbeat": timedelta(minutes=5),
            "sweep_interval": timedelta(minutes=5),
            "claim_idle": timedelta(minutes=5),
        }
    )
    services = EngineServices.build(slow, host)
    worker = Worker(sessions, services, name="drains-quietly", sweeper=True)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.2)
    worker.request_stop()
    done, _pending = await asyncio.wait({task}, timeout=10.0)
    assert task in done, "the worker did not stop inside the graceful window"
    assert task.exception() is None


async def test_the_pause_wakes_on_the_halt_flag_not_the_clock(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(settings, host)
    worker = Worker(sessions, services, name="pauses", sweeper=False)
    loop = asyncio.get_running_loop()
    started = loop.time()
    pause = asyncio.create_task(worker._pause(300.0))  # pyright: ignore[reportPrivateUsage]
    await asyncio.sleep(0.05)
    worker._halting.set()  # pyright: ignore[reportPrivateUsage]
    await asyncio.wait_for(pause, timeout=5.0)
    assert loop.time() - started < 5.0, "the pause slept the clock out instead of waking on the flag"


async def test_the_heartbeat_refreshes_leases_all_through_a_drain(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """A drain longer than a lease must not let another worker's sweeper reclaim the attempt."""
    services = EngineServices.build(
        fast(settings).model_copy(update={"heartbeat": timedelta(milliseconds=50), "lease": timedelta(seconds=1)}), host
    )
    await create(sessions, services, fan_out(1))
    worker = Worker(sessions, services, name="slow-drainer", sweeper=False)

    in_flight = asyncio.Event()
    release = asyncio.Event()
    run_unit = worker.engine.run_unit

    async def held_open(unit: ClaimedUnit, *, now: datetime | None = None) -> None:
        in_flight.set()
        await release.wait()
        await run_unit(unit, now=now)

    worker.engine.run_unit = held_open  # type: ignore[method-assign]
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(in_flight.wait(), timeout=10.0)
    attempt_id = next(iter(worker.in_flight))

    async def lease_of(identifier: Any) -> datetime | None:
        async with sessions() as session:
            attempt = await session.get(StepAttempt, identifier)
            assert attempt is not None
            expires: datetime | None = attempt.lease_expires_at
            return expires

    before = await lease_of(attempt_id)
    assert before is not None
    worker.request_stop()

    async def refreshed() -> bool:
        current = await lease_of(attempt_id)
        return current is not None and current > before

    await until(refreshed)

    async def reported_draining() -> bool:
        async with sessions() as session:
            found = await session.execute(sa.select(WorkerRow).where(WorkerRow.name == "slow-drainer"))
            return found.scalar_one().status is WorkerStatus.DRAINING

    await until(reported_draining)

    release.set()
    await asyncio.wait_for(task, timeout=10.0)
    assert worker.in_flight == set()
    async with sessions() as session:
        found = await session.execute(sa.select(WorkerRow).where(WorkerRow.name == "slow-drainer"))
        assert found.scalar_one().status is WorkerStatus.STOPPED


async def test_a_chore_runs_on_its_own_cadence_until_the_worker_stops(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(fast(settings), host)
    passes = 0

    async def count() -> None:
        nonlocal passes
        passes += 1

    chore = Chore(name="counting", interval=timedelta(seconds=0.01), run=count)
    worker = Worker(sessions, services, name="chored", sweeper=False, chores=[chore])
    task = asyncio.create_task(worker.run())

    async def ran() -> bool:
        return passes > 0

    await until(ran)
    worker.request_stop()
    await task


async def test_a_chore_that_raises_does_not_end_the_worker(sessions: Any, settings: Settings, host: PluginHost) -> None:
    services = EngineServices.build(fast(settings), host)
    attempts = 0

    async def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("the daemon is not there")

    chore = Chore(name="failing", interval=timedelta(seconds=0.01), run=fail)
    worker = Worker(sessions, services, name="chore-failing", sweeper=False, chores=[chore])
    task = asyncio.create_task(worker.run())

    async def tried_twice() -> bool:
        return attempts >= 2

    await until(tried_twice)
    worker.request_stop()
    await task
    assert not task.cancelled()
