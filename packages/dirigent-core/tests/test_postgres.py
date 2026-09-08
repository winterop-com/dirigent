"""The concurrency lane: the claims that only a real PostgreSQL can prove."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import (
    AlertEvent,
    AlertScope,
    AttemptKind,
    AttemptStatus,
    NotificationStatus,
    RunItemStatus,
    RunPriority,
    RunStatus,
    ScheduleKind,
    WorkerStatus,
)
from dirigent_core import migrations, pipelines
from dirigent_core.alerting import raise_for_stuck, recover_notifications, renew_lease
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.engine import EngineServices, executor, recovery
from dirigent_core.engine.claim import ClaimedUnit, due_attempt_statement, is_postgres, select_due
from dirigent_core.engine.definition import (
    ConcurrencyPolicy,
    PipelineDefinition,
    Requirements,
    ScheduleSpec,
    StepDefinition,
    TimeoutAction,
    TriggerSpecs,
    load_definition,
)
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.recovery import detect_stuck_runs, sweep_leases
from dirigent_core.engine.runs import RunCreationError, cancel_run, create_run, retry_step, save_pipeline
from dirigent_core.engine.state import StepOutcome, attempt_counts, item_counts, lock_run
from dirigent_core.models import (
    AlertRule,
    Base,
    Notification,
    Pipeline,
    PipelineVersion,
    Run,
    RunItem,
    Schedule,
    StepAttempt,
    WebhookTrigger,
    utcnow,
)
from dirigent_core.models import Worker as WorkerRow
from dirigent_core.pipelines import (
    PipelineCounts,
    PipelineInUse,
    apply_document,
    get_version,
    last_runs,
    listing_counts,
    require_pipeline,
)
from dirigent_core.plugins import PluginHost
from dirigent_plugin import RemoteHandle
from engineblocks import EchoOperator, EngineTestPlugin, RemoteOperator, reset_blocks

pytestmark = pytest.mark.postgres

WORKERS = 8

UNITS = 24


@pytest.fixture
def pg_settings(postgres_url: str, tmp_path: Any) -> Settings:
    """Settings pointed at the container, with short leases so recovery is testable."""
    return Settings(
        database_url=postgres_url,
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        lease=timedelta(seconds=5),
        lost_job_max_gone=3,
    )


@pytest.fixture
def pg_host() -> PluginHost:
    """The same test blocks the SQLite lane drives."""
    return PluginHost({"engine-tests": EngineTestPlugin().contribute()})


@pytest.fixture
def pg_services(pg_settings: Settings, pg_host: PluginHost) -> EngineServices:
    """Engine services bound to the container."""
    return EngineServices.build(pg_settings, pg_host)


@pytest.fixture
async def pg_engine(pg_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A clean schema per test, so contention tests cannot see each other's rows."""
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


def batch(count: int, block: str = "test.echo") -> PipelineDefinition:
    """A pipeline whose one step fans out, giving N workers N units to fight over."""
    return PipelineDefinition(
        code="contended",
        steps={
            "push": StepDefinition(
                block=block,
                for_each=[f"item-{index}" for index in range(count)],
                config={"value": "${item}"} if block == "test.echo" else {},
                poll=timedelta(seconds=1),
            )
        },
    )


def a_worker(name: str) -> WorkerRow:
    """A registry row, which is the durable side effect a sweep has besides recovery."""
    return WorkerRow(
        name=name,
        hostname=name,
        version="test",
        plugins={},
        tags=[],
        concurrency=1,
        status=WorkerStatus.RUNNING,
    )


async def start(sessions: Any, services: EngineServices, definition: PipelineDefinition) -> Run:
    """Save a pipeline version and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return run


async def test_the_dialect_split_takes_the_postgres_branch(pg_sessions: Any) -> None:
    async with pg_sessions() as session:
        assert is_postgres(session) is True


#: The instants the counted run is settled at, so the earliest one is a fact and not a clock read.
COUNTED = datetime(2026, 3, 1, tzinfo=UTC)


async def test_the_run_detail_counts_fold_the_same_way_on_postgresql(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """The rank, the conditional sum and the earliest instant are one query, on either dialect."""
    run = await start(pg_sessions, pg_services, batch(3))
    async with session_scope(pg_sessions) as session:
        items = list((await session.execute(sa.select(RunItem).order_by(RunItem.item_index))).scalars())
        attempts = {
            attempt.run_item_id: attempt for attempt in (await session.execute(sa.select(StepAttempt))).scalars()
        }
        attempts[items[0].id].status = AttemptStatus.SUCCEEDED
        attempts[items[0].id].started_at = COUNTED
        attempts[items[0].id].finished_at = COUNTED + timedelta(seconds=1)
        attempts[items[1].id].status = AttemptStatus.FAILED
        attempts[items[1].id].started_at = COUNTED + timedelta(seconds=2)
        attempts[items[1].id].finished_at = COUNTED + timedelta(seconds=3)
        # The second try of the one element that failed, which the rank must be the one to keep.
        session.add(
            StepAttempt(
                run_id=run.id,
                run_item_id=items[1].id,
                step_name="push",
                block_id="test.echo",
                attempt=2,
                status=AttemptStatus.SUCCEEDED,
                started_at=COUNTED + timedelta(seconds=4),
                finished_at=COUNTED + timedelta(seconds=5),
            )
        )
        items[0].status = RunItemStatus.SUCCEEDED
        items[1].status = RunItemStatus.SUCCEEDED

    async with session_scope(pg_sessions) as session:
        counted = await attempt_counts(session, run.id)
        grid = await item_counts(session, run.id)

    assert list(counted) == ["push"]
    assert counted["push"].total == 4, "every try, not only the newest of each element"
    assert sorted(counted["push"].latest) == sorted(
        [StepOutcome.SUCCEEDED, StepOutcome.SUCCEEDED, StepOutcome.RUNNING]
    ), "the retry replaces the failure it retried; the element nobody claimed is still running"
    assert counted["push"].started_at == COUNTED, "the earliest instant across every status group"
    assert counted["push"].finished_at == COUNTED + timedelta(seconds=1)
    assert grid == {"push": {RunItemStatus.SUCCEEDED: 2, RunItemStatus.RUNNING: 1}}


async def test_the_pipeline_listing_counts_and_last_run_fold_the_same_way_on_postgresql(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """The three correlated counts and the two windowed selects are one shape on either dialect."""
    older = await start(pg_sessions, pg_services, batch(1))
    pipeline_id = older.pipeline_id
    async with session_scope(pg_sessions) as session:
        session.add(Schedule(pipeline_id=pipeline_id, code="nightly", kind=ScheduleKind.CRON, cron="0 3 * * *"))
        session.add(WebhookTrigger(pipeline_id=pipeline_id, code="inbound", token_hash="a" * 64))
        await session.execute(
            sa.update(StepAttempt).where(StepAttempt.run_id == older.id).values(status=AttemptStatus.FAILED)
        )
        await session.execute(sa.update(Run).where(Run.id == older.id).values(status=RunStatus.FAILED))

    newer = await start(pg_sessions, pg_services, batch(1))
    async with session_scope(pg_sessions) as session:
        await session.execute(
            sa.update(StepAttempt).where(StepAttempt.run_id == newer.id).values(status=AttemptStatus.SUCCEEDED)
        )
        session.add(
            StepAttempt(
                run_id=newer.id,
                step_name="publish",
                block_id="test.echo",
                attempt=1,
                status=AttemptStatus.FAILED,
            )
        )
        await session.execute(sa.update(Run).where(Run.id == newer.id).values(status=RunStatus.FAILED))

    async with session_scope(pg_sessions) as session:
        counts = await listing_counts(session, [pipeline_id])
        latest = await last_runs(session, [pipeline_id])

    assert counts[pipeline_id] == PipelineCounts(active_runs=0, schedules=1, webhooks=1)
    assert latest[pipeline_id].id == newer.id, "the newest run, which is the greatest uuid7"
    assert latest[pipeline_id].status is RunStatus.FAILED
    assert latest[pipeline_id].failed_step == "publish", "that run's own failure, not the older run's"


async def test_parallel_workers_never_execute_the_same_unit_twice(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    run = await start(pg_sessions, pg_services, batch(UNITS))
    claimed: list[ClaimedUnit] = []
    lock = asyncio.Lock()

    async def worker(name: str) -> None:
        engine = Engine(pg_sessions, pg_services, owner=name)
        while True:
            unit = await engine.claim()
            if unit is None:
                return
            async with lock:
                claimed.append(unit)
            await engine.run_unit(unit)

    await asyncio.gather(*(worker(f"worker-{index}") for index in range(WORKERS)))

    assert len({unit.attempt_id for unit in claimed}) == UNITS, "SKIP LOCKED handed each attempt out once"
    assert len(claimed) == UNITS
    assert sorted(EchoOperator.calls) == sorted(f"item-{index}" for index in range(UNITS))

    async with pg_sessions() as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert stored.status is RunStatus.SUCCEEDED
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))
        attempts = list(rows.scalars())
    assert len(attempts) == UNITS, "no unit was retried, so none was executed twice"
    assert {attempt.status for attempt in attempts} == {AttemptStatus.SUCCEEDED}


async def test_workers_claiming_an_empty_queue_all_get_nothing(pg_sessions: Any, pg_services: EngineServices) -> None:
    engines = [Engine(pg_sessions, pg_services, owner=f"idle-{index}") for index in range(WORKERS)]
    results = await asyncio.gather(*(engine.claim() for engine in engines))
    assert results == [None] * WORKERS


async def test_an_expired_lease_with_no_submission_requeues_and_runs_once(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    await start(pg_sessions, pg_services, batch(1))
    dead = Engine(pg_sessions, pg_services, owner="dead-worker")
    unit = await dead.claim()
    assert unit is not None  # the worker dies here, having recorded nothing

    async with session_scope(pg_sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = attempt.lease_expires_at - timedelta(hours=1) if attempt.lease_expires_at else None

    async with session_scope(pg_sessions) as session:
        assert await sweep_leases(session) == [unit.attempt_id]

    alive = Engine(pg_sessions, pg_services, owner="alive-worker")
    recovered = await alive.claim()
    assert recovered is not None
    assert recovered.attempt_id == unit.attempt_id
    await alive.run_unit(recovered)

    assert EchoOperator.calls == ["item-0"], "the replay ran the work exactly once"
    async with pg_sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.status is AttemptStatus.SUCCEEDED


async def test_an_expired_lease_with_a_recorded_submission_never_submits_again(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    await start(pg_sessions, pg_services, batch(1, block="test.remote"))
    dead = Engine(pg_sessions, pg_services, owner="dead-worker")
    unit = await dead.claim()
    assert unit is not None

    # execute() ran and its handle committed, then the worker died before parking.
    handle = RemoteHandle(block_id="test.remote", ref="job-1", meta={"result": "done"})
    await dead.record_handle(unit, handle)
    RemoteOperator.submissions.append("job-1")

    async with session_scope(pg_sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = attempt.lease_expires_at - timedelta(hours=1) if attempt.lease_expires_at else None

    async with session_scope(pg_sessions) as session:
        assert await sweep_leases(session) == [unit.attempt_id]
    async with pg_sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.status is AttemptStatus.WAITING

    alive = Engine(pg_sessions, pg_services, owner="alive-worker")
    probed = await alive.claim()
    assert probed is not None
    assert probed.is_probe is True
    await alive.run_unit(probed)

    assert RemoteOperator.submissions == ["job-1"], "recovery probed instead of resubmitting"
    assert RemoteOperator.fetches == ["job-1"]


async def test_a_replay_never_adopts_a_settled_siblings_submission(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    run = await start(pg_sessions, pg_services, batch(1, block="test.remote"))
    dead = Engine(pg_sessions, pg_services, owner="dead-worker")
    unit = await dead.claim()
    assert unit is not None

    async with session_scope(pg_sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = attempt.lease_expires_at - timedelta(hours=1) if attempt.lease_expires_at else None
        session.add(
            StepAttempt(
                run_id=run.id,
                run_item_id=unit.run_item_id,
                step_name="push",
                block_id="test.remote",
                attempt=99,
                status=AttemptStatus.CANCELLED,
                remote_handle={"block_id": "test.remote", "ref": "job-1", "meta": {"result": "done"}},
            )
        )

    async with session_scope(pg_sessions) as session:
        await sweep_leases(session)
    async with pg_sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.status is AttemptStatus.QUEUED
        assert attempt.remote_handle is None, "a settled attempt's handle is not this attempt's work"


async def test_probes_stay_scheduled_under_contention(pg_sessions: Any, pg_services: EngineServices) -> None:
    count = 6
    await start(pg_sessions, pg_services, batch(count, block="test.remote"))

    async def worker(name: str) -> int:
        engine = Engine(pg_sessions, pg_services, owner=name)
        handled = 0
        while True:
            unit = await engine.claim()
            if unit is None:
                return handled
            await engine.run_unit(unit)
            handled += 1

    for _ in range(4):
        await asyncio.gather(*(worker(f"prober-{index}") for index in range(WORKERS)))
        await asyncio.sleep(1.1)

    assert RemoteOperator.submissions == ["job-1"] * count
    assert len(RemoteOperator.fetches) == count, "each remote job was fetched exactly once"
    async with pg_sessions() as session:
        rows = await session.execute(sa.select(StepAttempt))
        assert {attempt.status for attempt in rows.scalars()} == {AttemptStatus.SUCCEEDED}


async def test_a_crash_between_claim_and_outcome_replays_safely(pg_sessions: Any, pg_services: EngineServices) -> None:
    run = await start(pg_sessions, pg_services, batch(1))
    crashing = Engine(pg_sessions, pg_services, owner="crashing-worker")
    unit = await crashing.claim()
    assert unit is not None

    # The claim committed but the outcome transaction never did: the row is still RUNNING.
    async with pg_sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.status is AttemptStatus.RUNNING
        assert attempt.lease_owner == "crashing-worker"

    async with session_scope(pg_sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = attempt.lease_expires_at - timedelta(hours=1) if attempt.lease_expires_at else None

    async with session_scope(pg_sessions) as session:
        assert await sweep_leases(session) == [unit.attempt_id]
    async with session_scope(pg_sessions) as session:
        assert await sweep_leases(session) == [], "sweeping twice recovers nothing twice"

    replayed = Engine(pg_sessions, pg_services, owner="replay-worker")
    recovered = await replayed.claim()
    assert recovered is not None
    await replayed.run_unit(recovered)

    assert EchoOperator.calls == ["item-0"], "the replay executed the work exactly once"
    async with pg_sessions() as session:
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))
        attempts = list(rows.scalars())
        stored = await session.get(Run, run.id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.SUCCEEDED
    assert stored is not None
    assert stored.status is RunStatus.SUCCEEDED


DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: jsonb-round-trip
description: Everything whose key order jsonb is free to rearrange.
concurrency: skip
params:
  type: object
  required: [day]
  properties:
    zebra: { type: string, default: last-alphabetically }
    day: { type: string, format: date }
    aardvark: { type: integer, default: 1 }
steps:
  zzz_last:
    block: test.echo
    depends_on: [aaa_first]
    config: { value: "second", upper: true }
  aaa_first:
    block: test.echo
    config: { value: "first", labels: { zzz: "z", aaa: "a" } }
    retry: { max_attempts: 3, backoff: 45s }
triggers:
  schedules:
    - code: nightly
      cron: "0 5 * * *"
      timezone: Europe/Oslo
      params: { zebra: z, day: "2026-01-01" }
requires:
  blocks: [test.echo]
"""


async def test_the_canonical_export_survives_a_jsonb_round_trip(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """The document format's byte-identity claim is only true if jsonb cannot break it."""
    from dirigent_core.documents import digest_of, load_text, to_yaml
    from dirigent_core.pipelines import apply_document, export_pipeline

    definition = load_text(DOCUMENT)
    expected = to_yaml(definition)

    async with session_scope(pg_sessions) as session:
        result = await apply_document(session, pg_services, definition)
    assert result.version == 1

    async with session_scope(pg_sessions) as session:
        exported = await export_pipeline(session, "jsonb-round-trip")
    assert exported == expected, "a document stored in jsonb must export exactly as it went in"

    async with session_scope(pg_sessions) as session:
        again = await apply_document(session, pg_services, load_text(exported))
    assert again.plan.action.value == "unchanged"
    assert again.plan.digest == digest_of(definition)


async def test_deleting_a_pipeline_cascades_its_history_and_frees_the_code(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """The run family is deleted in dependency order, and PostgreSQL is where the keys bite."""
    from dirigent_core.documents import load_text
    from dirigent_core.models import Run
    from dirigent_core.pipelines import apply_document, delete_pipeline, find_pipeline, get_version, list_pipelines

    definition = load_text(DOCUMENT)
    async with session_scope(pg_sessions) as session:
        await apply_document(session, pg_services, definition)
        pipeline = await find_pipeline(session, "jsonb-round-trip")
        assert pipeline is not None
        run = await create_run(session, pg_services, await get_version(session, pipeline), params={"day": "2026-01-01"})
        assert run is not None
        run.status = RunStatus.SUCCEEDED

    async with session_scope(pg_sessions) as session:
        await delete_pipeline(session, "jsonb-round-trip")

    async with session_scope(pg_sessions) as session:
        assert await list_pipelines(session) == []
        left = await session.execute(sa.select(sa.func.count()).select_from(Run))
        assert left.scalar_one() == 0, "no run may outlive the pipeline it was attributed to"

    async with session_scope(pg_sessions) as session:
        fresh = await apply_document(session, pg_services, definition)
    assert fresh.version == 1, "the deleted row must not block a fresh pipeline of the same code"


async def test_the_migrations_run_on_postgresql(pg_settings: Settings) -> None:
    """Both dialects share one migration history, and this is the half CI cannot skip."""
    from dirigent_core import migrations

    engine = create_engine(pg_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    await migrations.upgrade_async(settings=pg_settings)
    assert await migrations.current_revision_async(pg_settings) == migrations.head_revision(pg_settings)
    await migrations.downgrade_async("base", settings=pg_settings)
    assert await migrations.current_revision_async(pg_settings) is None


# -- the scheduler, which is the other thing only a real PostgreSQL can prove ---------
#
# Leadership is a session-scoped advisory lock, and the tick's claim is FOR UPDATE SKIP
# LOCKED. Neither exists on SQLite.

SCHEDULED = """
format: dirigent/v1
kind: pipeline
code: clocked
description: A pipeline that exists to be fired at.
steps:
  tick:
    block: test.echo
    config: { value: fired }
"""


async def _clocked(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> Any:
    """Apply the one-step pipeline the scheduler tests fire, and hand back its row."""
    from dirigent_core.documents import load_text
    from dirigent_core.pipelines import apply_document, find_pipeline

    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(SCHEDULED))
        return await find_pipeline(session, "clocked")


async def _due_schedule(
    sessions: async_sessionmaker[AsyncSession],
    pipeline: Any,
    *,
    late: timedelta = timedelta(seconds=1),
    cron: str = "0 5 * * *",
    timezone: str = "UTC",
) -> Any:
    """Create a schedule and drag its next firing into the past by a given amount."""
    from dirigent_core.models import Schedule, utcnow
    from dirigent_core.triggers import ScheduleRequest, create_schedule

    async with session_scope(sessions) as session:
        fresh = await session.merge(pipeline)
        schedule = await create_schedule(session, fresh, ScheduleRequest(code="nightly", cron=cron, timezone=timezone))
        schedule.next_fire_at = utcnow() - late
        schedule_id = schedule.id
    async with sessions() as session:
        return await session.get(Schedule, schedule_id)


async def _firings(sessions: async_sessionmaker[AsyncSession], schedule_id: Any) -> list[Any]:
    """Read every firing a schedule has recorded, oldest first."""
    from dirigent_core.models import ScheduleFiring

    async with sessions() as session:
        rows = await session.execute(
            sa.select(ScheduleFiring).where(ScheduleFiring.schedule_id == schedule_id).order_by(ScheduleFiring.id)
        )
        return list(rows.scalars())


async def test_only_one_scheduler_takes_leadership(pg_sessions: async_sessionmaker[AsyncSession]) -> None:
    """The advisory lock is what makes "exactly one scheduler" a database guarantee."""
    from dirigent_core.scheduler import release_lead, try_lead

    key = 0x5C_4E_D0_01
    leader = pg_sessions()
    replica = pg_sessions()
    try:
        assert await try_lead(leader, key) is True
        assert await try_lead(replica, key) is False, "the second scheduler must stand by, not fire"

        # Leadership is held by the connection, so giving it back hands over immediately
        # rather than on a timeout.
        await release_lead(leader, key)
        await leader.commit()
        assert await try_lead(replica, key) is True
    finally:
        await release_lead(replica, key)
        await replica.commit()
        await leader.close()
        await replica.close()


async def test_two_schedulers_ticking_at_once_never_double_fire(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Even with leadership bypassed entirely, SKIP LOCKED plus the re-check fires once."""
    from dirigent_core.scheduler import tick

    pipeline = await _clocked(pg_sessions, pg_services)
    schedule = await _due_schedule(pg_sessions, pipeline)

    first, second = await asyncio.gather(
        tick(pg_sessions, pg_services),
        tick(pg_sessions, pg_services),
    )

    fired = [*first, *second]
    assert len(fired) == 1, f"two schedulers produced {len(fired)} firings"
    assert await _firings(pg_sessions, schedule.id) != []
    assert len(await _firings(pg_sessions, schedule.id)) == 1

    async with pg_sessions() as session:
        runs = await session.execute(sa.select(sa.func.count()).select_from(Run))
        assert int(runs.scalar_one()) == 1, "one due firing is one run, however many schedulers looked at it"


async def test_a_second_tick_after_the_first_finds_nothing_due(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Firing and advancing commit together, so the next tick sees an advanced clock."""
    from dirigent_core.models import Schedule
    from dirigent_core.scheduler import tick

    pipeline = await _clocked(pg_sessions, pg_services)
    schedule = await _due_schedule(pg_sessions, pipeline)

    assert len(await tick(pg_sessions, pg_services)) == 1
    assert await tick(pg_sessions, pg_services) == []

    async with pg_sessions() as session:
        stored = await session.get(Schedule, schedule.id)
        assert stored is not None
        assert stored.last_fired_at is not None
        assert stored.next_fire_at is not None
        assert stored.next_fire_at > stored.last_fired_at


async def test_a_late_firing_inside_the_grace_keeps_the_cron_grid(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """An ordinary late firing advances from the slot it owed, not from now."""
    from dirigent_client.enums import ScheduleKind
    from dirigent_core.scheduler import tick
    from dirigent_core.triggers import next_fire_after

    pipeline = await _clocked(pg_sessions, pg_services)
    schedule = await _due_schedule(pg_sessions, pipeline, late=timedelta(seconds=30))
    owed = schedule.next_fire_at

    fired = await tick(pg_sessions, pg_services)
    assert len(fired) == 1
    assert fired[0].misfired is False

    expected = next_fire_after(
        kind=ScheduleKind.CRON, cron="0 5 * * *", interval_seconds=None, run_at=None, timezone="UTC", after=owed
    )
    assert fired[0].next_fire_at == expected, "inside the grace, the clock advances from the slot it owed"

    rows = await _firings(pg_sessions, schedule.id)
    assert len(rows) == 1
    assert rows[0].misfired is False
    assert rows[0].scheduled_for == owed


async def test_a_firing_past_the_grace_misfires_once_and_abandons_the_missed_slots(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """The catchup storm, prevented: a week of missed nightly firings produces one run."""
    from dirigent_core.models import utcnow
    from dirigent_core.scheduler import tick

    pipeline = await _clocked(pg_sessions, pg_services)
    schedule = await _due_schedule(pg_sessions, pipeline, cron="* * * * *", late=timedelta(days=7))

    fired = await tick(pg_sessions, pg_services)
    assert len(fired) == 1, "a week of missed minutes is one firing, not ten thousand"
    assert fired[0].misfired is True
    assert fired[0].next_fire_at is not None
    assert fired[0].next_fire_at > utcnow(), "the clock was advanced from now, abandoning what was missed"
    assert fired[0].next_fire_at - utcnow() <= timedelta(minutes=1)

    rows = await _firings(pg_sessions, schedule.id)
    assert [row.misfired for row in rows] == [True]

    async with pg_sessions() as session:
        runs = await session.execute(sa.select(sa.func.count()).select_from(Run))
        assert int(runs.scalar_one()) == 1

    # And the tick right after it is quiet, rather than working through a backlog.
    assert await tick(pg_sessions, pg_services) == []


async def test_a_cron_schedule_fires_on_its_own_zone_not_the_process_zone(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """A non-UTC schedule stored through timestamptz still means what it said."""
    from zoneinfo import ZoneInfo

    from dirigent_core.models import Schedule
    from dirigent_core.scheduler import tick

    pipeline = await _clocked(pg_sessions, pg_services)
    schedule = await _due_schedule(pg_sessions, pipeline, cron="30 2 * * *", timezone="Europe/Oslo")

    fired = await tick(pg_sessions, pg_services)
    assert len(fired) == 1

    async with pg_sessions() as session:
        stored = await session.get(Schedule, schedule.id)
    assert stored is not None
    assert stored.timezone == "Europe/Oslo"
    assert stored.next_fire_at is not None

    local = stored.next_fire_at.astimezone(ZoneInfo("Europe/Oslo"))
    assert (local.hour, local.minute) == (2, 30), (
        f"02:30 Oslo came back as {local.isoformat()}; the stored instant lost its zone"
    )


async def test_a_paused_schedule_is_not_claimed_and_resuming_starts_from_now(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Pausing is operational state, and resuming is a fresh start rather than a replay."""
    from dirigent_core.models import Schedule, utcnow
    from dirigent_core.scheduler import claim_due, tick
    from dirigent_core.triggers import set_paused

    pipeline = await _clocked(pg_sessions, pg_services)
    schedule = await _due_schedule(pg_sessions, pipeline, cron="* * * * *", late=timedelta(days=2))

    async with session_scope(pg_sessions) as session:
        stored = await session.get(Schedule, schedule.id)
        assert stored is not None
        await set_paused(session, stored, paused=True)

    async with pg_sessions() as session:
        assert await claim_due(session, utcnow()) == []
    assert await tick(pg_sessions, pg_services) == []

    async with session_scope(pg_sessions) as session:
        stored = await session.get(Schedule, schedule.id)
        assert stored is not None
        await set_paused(session, stored, paused=False)
        resumed = stored.next_fire_at

    assert resumed is not None
    assert resumed > utcnow(), "resuming must not replay the two days of slots that went by"


async def test_a_deactivated_pipeline_stops_its_schedules_firing(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Deactivating a pipeline pauses its clocks without anyone having to pause them."""
    from dirigent_core.pipelines import set_active
    from dirigent_core.scheduler import tick

    pipeline = await _clocked(pg_sessions, pg_services)
    await _due_schedule(pg_sessions, pipeline)

    async with session_scope(pg_sessions) as session:
        await set_active(session, "clocked", active=False)

    assert await tick(pg_sessions, pg_services) == []

    async with session_scope(pg_sessions) as session:
        await set_active(session, "clocked", active=True)
    assert len(await tick(pg_sessions, pg_services)) == 1


async def test_two_concurrent_creates_under_skip_produce_exactly_one_run(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """``skip`` is read-then-decide-then-write, and the two triggers that collide are processes."""
    definition = PipelineDefinition(
        code="skipping",
        concurrency=ConcurrencyPolicy.SKIP,
        steps={"only": StepDefinition(block="test.echo", config={"value": "once"})},
    )
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, definition)
        version_id = version.id

    async def create_one() -> Run | None:
        async with session_scope(pg_sessions) as session:
            stored = await session.get(PipelineVersion, version_id)
            assert stored is not None
            return await create_run(session, pg_services, stored)

    created = await asyncio.gather(*(create_one() for _ in range(WORKERS)), return_exceptions=True)
    runs = [run for run in created if isinstance(run, Run)]

    assert len(runs) == 1, f"skip let {len(runs)} runs through"
    async with pg_sessions() as session:
        rows = await session.execute(sa.select(Run).where(Run.pipeline_version_id == version_id))
        assert len(list(rows.scalars())) == 1


async def test_two_concurrent_creates_under_queue_hold_all_but_one(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """``queue`` has the same race, with a quieter symptom: two runs in flight at once."""
    definition = PipelineDefinition(
        code="queueing",
        concurrency=ConcurrencyPolicy.QUEUE,
        steps={"only": StepDefinition(block="test.echo", config={"value": "once"})},
    )
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, definition)
        version_id = version.id

    async def create_one() -> Run | None:
        async with session_scope(pg_sessions) as session:
            stored = await session.get(PipelineVersion, version_id)
            assert stored is not None
            return await create_run(session, pg_services, stored)

    await asyncio.gather(*(create_one() for _ in range(WORKERS)), return_exceptions=True)

    async with pg_sessions() as session:
        rows = await session.execute(sa.select(StepAttempt))
        statuses = [attempt.status for attempt in rows.scalars()]
    queued = [status for status in statuses if status is not AttemptStatus.PENDING]
    assert len(queued) == 1, f"queue released {len(queued)} runs at once"


async def a_failed_run(pg_sessions: Any, pg_services: EngineServices) -> Run:
    """One run of a one-step pipeline, settled as a failure with nothing else in flight."""
    definition = PipelineDefinition(code="retried", steps={"only": StepDefinition(block="test.echo")})
    run = await start(pg_sessions, pg_services, definition)
    settled = utcnow()
    async with session_scope(pg_sessions) as session:
        await session.execute(
            sa.update(StepAttempt)
            .where(StepAttempt.run_id == run.id)
            .values(status=AttemptStatus.FAILED, finished_at=settled)
        )
        await session.execute(
            sa.update(Run).where(Run.id == run.id).values(status=RunStatus.FAILED, finished_at=settled)
        )
    return run


async def retry_once(pg_sessions: Any, pg_services: EngineServices, run_id: Any, key: str) -> Any:
    """Retry one step from a session of its own, the way one API request does."""
    async with session_scope(pg_sessions) as session:
        stored = await session.get(Run, run_id)
        assert stored is not None
        return (await retry_step(session, pg_services, stored, "only", idempotency_key=key)).id


async def test_two_concurrent_retries_of_one_step_create_one_attempt(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """Two requests both read the failed attempt, and the constraint lets both insert N+1.

    Gathering two retries does not reliably get both to read before either writes, so this
    holds the invariant rather than demonstrating the interleaving; the locks are what make it
    hold when the reads really do overlap.
    """
    run = await a_failed_run(pg_sessions, pg_services)

    outcomes = await asyncio.gather(
        retry_once(pg_sessions, pg_services, run.id, "one"),
        retry_once(pg_sessions, pg_services, run.id, "two"),
        return_exceptions=True,
    )

    created = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    refused = [outcome for outcome in outcomes if isinstance(outcome, RunCreationError)]
    assert len(created) == 1, "both requests queued the same step"
    assert len(refused) == 1, "the second request saw the first's attempt and refused"
    async with pg_sessions() as session:
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))
        attempts = list(rows.scalars())
    assert [attempt.attempt for attempt in attempts] == [1, 2]


async def test_two_concurrent_retries_with_one_key_return_the_same_attempt(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """One key is one attempt, and a replay racing itself must not be a uniqueness violation."""
    run = await a_failed_run(pg_sessions, pg_services)

    outcomes = await asyncio.gather(
        retry_once(pg_sessions, pg_services, run.id, "click"),
        retry_once(pg_sessions, pg_services, run.id, "click"),
    )

    assert outcomes[0] == outcomes[1]
    async with pg_sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run.id, StepAttempt.kind == AttemptKind.MANUAL)
        )
        assert len(list(rows.scalars())) == 1


async def test_the_tag_filter_narrows_by_containment_on_postgresql(
    pg_sessions: Any, pg_services: EngineServices
) -> None:
    """The `@>` half of the fork, asserted by the body the SQLite lane runs over `json_each`."""
    from test_pipelines import assert_the_tag_filter_narrows_by_containment

    await assert_the_tag_filter_narrows_by_containment(pg_sessions, pg_services)


async def test_the_migrations_leave_no_drift_against_the_models_on_postgres(pg_settings: Settings) -> None:
    """The dialect the migrations actually run on, checked the same way SQLite is."""
    from test_schema import metadata_drift

    engine = create_engine(pg_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()

    await migrations.upgrade_async(settings=pg_settings)
    engine = create_engine(pg_settings)
    try:
        assert await metadata_drift(engine) == []
    finally:
        await engine.dispose()


async def test_two_sweepers_raising_the_same_stuck_run_do_not_abort_lease_recovery(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Every worker sweeps, so two of them reach the same stuck run in the same second."""
    run = await start(pg_sessions, pg_services, batch(1))
    dead = Engine(pg_sessions, pg_services, owner="dead-worker")
    unit = await dead.claim()
    assert unit is not None

    async with session_scope(pg_sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = utcnow() - timedelta(hours=1)
        attempt.updated_at = utcnow() - timedelta(hours=1)
        stored = await session.get(Run, run.id)
        assert stored is not None
        stored.status = RunStatus.RUNNING
        session.add(
            AlertRule(
                code="page-ops",
                event=AlertEvent.RUN_STUCK,
                scope=AlertScope.GLOBAL,
                notifier="log",
                throttle_seconds=0,
                active=True,
            )
        )

    async with pg_sessions() as session:
        stuck = await detect_stuck_runs(session, after=timedelta(seconds=1))
    assert stuck == [run.id]

    started = asyncio.Barrier(2)
    inserted = asyncio.Event()

    async def first() -> int:
        async with session_scope(pg_sessions) as session:
            await started.wait()
            queued = await raise_for_stuck(session, pg_services, stuck)
            # Announced before the commit, so the other sweeper's check runs against a
            # notification that exists and is not yet visible to it.
            inserted.set()
            await sweep_leases(session)
            return queued

    async def second() -> tuple[int, int]:
        async with session_scope(pg_sessions) as session:
            session.add(a_worker("second-sweeper"))
            await session.flush()
            await started.wait()
            await inserted.wait()
            queued = await raise_for_stuck(session, pg_services, stuck)
            recovered = await sweep_leases(session)
            return queued, len(recovered)

    raised_first, (raised_second, _) = await asyncio.gather(first(), second())
    assert raised_first + raised_second == 1, "the constraint let exactly one alert through"

    async with pg_sessions() as session:
        notifications = await session.execute(sa.select(sa.func.count()).select_from(Notification))
        assert notifications.scalar_one() == 1
        registered = await session.execute(sa.select(WorkerRow.name))
        assert "second-sweeper" in list(registered.scalars()), "work done before the conflict survived it"
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.status is AttemptStatus.QUEUED, "the expired lease was recovered"
        assert attempt.lease_owner is None


async def test_a_deadline_sweep_that_waited_for_the_lock_leaves_the_claim_alone(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every worker sweeps, and one of them reaches an attempt another is claiming right then.

    A worker computes one moment for a whole claim loop, so an attempt whose deadline falls
    inside that loop is claimed and leased while the sweeper, on a later clock, holds it as
    overdue. The sweeper queues behind the claim on the run lock; settling what it selected
    before that lock fails a running attempt, clears the lease its holder is about to check,
    and orphans the remote job the claim submitted.
    """
    definition = PipelineDefinition(
        code="deadline-races-a-claim",
        steps={
            "job": StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
                on_timeout=TimeoutAction.FAIL,
            )
        },
    )
    run = await start(pg_sessions, pg_services, definition)
    sweeper = Engine(pg_sessions, pg_services, owner="sweeping-worker")
    unit = await sweeper.claim()
    assert unit is not None
    await sweeper.run_unit(unit)

    selected = asyncio.Event()
    claiming = asyncio.Event()
    leased_until = utcnow() + timedelta(minutes=1)

    async def select_then_wait(session: AsyncSession, *, now: datetime | None = None) -> list[StepAttempt]:
        overdue = await recovery.overdue_deadlines(session, now=now)
        selected.set()
        await claiming.wait()
        return overdue

    async def sweep() -> list[Any]:
        async with session_scope(pg_sessions) as session:
            return await sweeper.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1))

    async def claim() -> None:
        await selected.wait()
        async with session_scope(pg_sessions) as session:
            await lock_run(session, run.id)
            attempt = await session.get(StepAttempt, unit.attempt_id)
            assert attempt is not None
            attempt.status = AttemptStatus.RUNNING
            attempt.lease_owner = "the-faster-worker"
            attempt.lease_expires_at = leased_until
            await session.flush()
            # Released before the commit, so the sweeper reaches the run lock while this
            # claim still holds it and only sees the row once the claim lands.
            claiming.set()

    monkeypatch.setattr(executor, "overdue_deadlines", select_then_wait)
    settled, _ = await asyncio.gather(sweep(), claim())

    assert settled == [], "the sweep failed an attempt a worker had claimed"
    async with pg_sessions() as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        assert attempt.status is AttemptStatus.RUNNING
        assert attempt.lease_owner == "the-faster-worker", "the lease was released under its holder"
        assert attempt.lease_expires_at == leased_until


async def test_two_first_applies_of_one_name_do_not_collide(pg_sessions: Any) -> None:
    """Planning and saving are separate reads, so two applies can both decide to create.

    The live-name index refuses the second, and a uniqueness violation reaching the caller is
    a 500 where the right answer is version 2 of what the winner wrote.
    """
    definition = PipelineDefinition(code="raced", steps={"a": StepDefinition(block="test.echo")})

    async def apply() -> int:
        async with session_scope(pg_sessions) as session:
            version = await save_pipeline(session, definition)
            return version.version

    first, second = await asyncio.gather(apply(), apply())

    assert sorted((first, second)) == [1, 2], "one apply lost its version to the other"


async def test_two_updates_of_one_pipeline_take_different_versions(pg_sessions: Any) -> None:
    """Two applies of an existing pipeline give it two versions, not one number twice.

    This does not demonstrate the interleaving it guards against: gathering two applies does
    not reliably get both to read before either writes, and it passes with the row lock
    removed. It holds the invariant; ``lock_pipeline`` is what makes it hold when the reads
    really do overlap.
    """
    definition = PipelineDefinition(code="racing-versions", steps={"a": StepDefinition(block="test.echo")})
    async with session_scope(pg_sessions) as session:
        await save_pipeline(session, definition)

    async def apply() -> int:
        async with session_scope(pg_sessions) as session:
            version = await save_pipeline(session, definition)
            return version.version

    second, third = await asyncio.gather(apply(), apply())

    assert sorted((second, third)) == [2, 3], "two versions of one pipeline share a number"


async def test_a_held_apply_lock_makes_the_second_applier_skip(
    pg_sessions: Any, pg_services: EngineServices, tmp_path: Any
) -> None:
    """Two servers booting together elect one applier; the other skips and applies nothing."""
    from dirigent_core.directory import apply_directory

    key = 0x64_69_72_61
    (tmp_path / "a.yaml").write_text("format: dirigent/v1\ncode: locked-out\nsteps:\n  only:\n    block: test.echo\n")
    async with session_scope(pg_sessions) as holder:
        held = await holder.execute(sa.select(sa.func.pg_try_advisory_lock(key)))
        assert held.scalar_one() is True

        summary = await apply_directory(pg_sessions, pg_services, tmp_path, lock_key=key)

        assert summary.skipped is True
        assert summary.applied == []
        await holder.execute(sa.select(sa.func.pg_advisory_unlock(key)))

    retried = await apply_directory(pg_sessions, pg_services, tmp_path, lock_key=key)
    assert retried.skipped is False
    assert retried.applied == ["locked-out"]


#: How long the losing side of a lock race is given to reach the lock and block on it.
BLOCKED_ON_THE_LOCK = 0.5


async def test_a_delete_and_a_run_started_beside_it_cannot_both_win(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trigger firing while a delete counts what is in flight must not lose its run to it.

    The delete counts, then deletes the pipeline and everything attributed to it. A run
    created in between is invisible to the count and swept away with the history, under the
    lease a worker is holding. Both take the pipeline lock, so one of them sees the other.
    """
    definition = PipelineDefinition(code="deleted-mid-flight", steps={"a": StepDefinition(block="test.echo")})
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, definition)
    version_id = version.id

    counting = asyncio.Event()
    attempted = asyncio.Event()
    counted = asyncio.Event()
    count_runs = pipelines.count_runs

    async def count_once_the_run_has_tried(
        session: AsyncSession, pipeline_id: Any, *narrow: sa.ColumnElement[bool]
    ) -> int:
        if not counting.is_set():
            counting.set()
            await attempted.wait()
        live = await count_runs(session, pipeline_id, *narrow)
        counted.set()
        return live

    monkeypatch.setattr(pipelines, "count_runs", count_once_the_run_has_tried)

    async def delete() -> None:
        async with session_scope(pg_sessions) as session:
            await pipelines.delete_pipeline(session, definition.code)

    async def create() -> Run | None:
        await counting.wait()
        async with session_scope(pg_sessions) as session:
            stored = await session.get(PipelineVersion, version_id)
            assert stored is not None
            creating = asyncio.ensure_future(create_run(session, pg_services, stored))
            # Nothing observable says "queued on a row lock", so the creation is given a
            # moment to reach it before the delete is let go.
            await asyncio.sleep(BLOCKED_ON_THE_LOCK)
            attempted.set()
            # The transaction stays open until the delete has counted, which is what makes
            # this the interleaving rather than two turns that happen not to overlap.
            await counted.wait()
            return await creating

    deleted, created = await asyncio.gather(delete(), create(), return_exceptions=True)

    if isinstance(deleted, BaseException):
        assert isinstance(deleted, PipelineInUse), "the delete failed for a reason of its own"

    async with pg_sessions() as session:
        if isinstance(created, Run):
            assert await session.get(Run, created.id) is not None, "a created run was deleted under its creator"
            assert await session.get(Pipeline, created.pipeline_id) is not None
        else:
            assert isinstance(created, BaseException), "the concurrency policy refused a run nothing else held"
        orphans = await session.execute(
            sa.select(sa.func.count())
            .select_from(Run)
            .where(~sa.select(1).where(Pipeline.id == Run.pipeline_id).exists())
        )
        assert orphans.scalar_one() == 0, "a run outlived the pipeline it belongs to"


def scheduled(code: str, step: str, schedule: str, cron: str) -> PipelineDefinition:
    """One pipeline document under a shared code, declaring one schedule of its own."""
    return PipelineDefinition(
        code=code,
        steps={step: StepDefinition(block="test.echo")},
        triggers=TriggerSpecs(schedules=[ScheduleSpec(code=schedule, cron=cron)]),
    )


async def test_two_applies_of_one_code_leave_the_triggers_of_the_version_that_stands(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An apply plans and then reconciles triggers, and both happen under the pipeline lock.

    An unchanged apply writes no version but still materializes the triggers its document
    declares. Planned before another apply's version lands and reconciled after, it deletes
    the new version's schedules and restores its own, leaving the pipeline on one document
    and its triggers on another.
    """
    standing = scheduled("racing-triggers", "a", "nightly", "0 5 * * *")
    incoming = scheduled("racing-triggers", "b", "hourly", "0 * * * *")
    async with session_scope(pg_sessions) as session:
        await apply_document(session, pg_services, standing)

    planned = asyncio.Event()
    landed = asyncio.Event()
    plan_apply = pipelines.plan_apply

    async def plan_then_wait(session: AsyncSession, services: EngineServices, definition: PipelineDefinition) -> Any:
        plan = await plan_apply(session, services, definition)
        if not planned.is_set():
            planned.set()
            await landed.wait()
        return plan

    monkeypatch.setattr(pipelines, "plan_apply", plan_then_wait)

    async def apply(definition: PipelineDefinition) -> None:
        async with session_scope(pg_sessions) as session:
            await apply_document(session, pg_services, definition)

    async def apply_after_the_plan() -> None:
        await planned.wait()
        applying = asyncio.ensure_future(apply(incoming))
        await asyncio.sleep(BLOCKED_ON_THE_LOCK)
        landed.set()
        await applying

    await asyncio.gather(apply(standing), apply_after_the_plan())

    async with pg_sessions() as session:
        pipeline = await require_pipeline(session, "racing-triggers")
        current = await get_version(session, pipeline)
        rows = await session.execute(sa.select(Schedule.code).where(Schedule.pipeline_id == pipeline.id))
        held = set(rows.scalars())

    declared = {spec.code for spec in load_definition(current.document).triggers.schedules}
    assert held == declared, "the pipeline's schedules belong to a document it is not on"


async def test_a_notification_lease_renewed_while_recovery_sweeps_is_not_lost_to_it(
    pg_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A worker that renews mid-sweep either keeps the notification or is told it lost it.

    Recovery reads expired leases and requeues them. Written as a read and then a write, a
    renewal that commits in between is overwritten: the sweep hands the notification to
    somebody else while its holder has just been told the lease is still theirs.
    """
    moment = utcnow()
    async with session_scope(pg_sessions) as session:
        notification = Notification(
            event=AlertEvent.RUN_FAILED,
            notifier="log",
            subject="delivered by whoever holds it",
            status=NotificationStatus.SENDING,
            available_at=moment - timedelta(minutes=1),
            lease_owner="live-worker",
            lease_expires_at=moment - timedelta(seconds=30),
        )
        session.add(notification)
        await session.flush()
    notification_id = notification.id

    swept = asyncio.Event()
    renewal_landed = asyncio.Event()

    async def sweep() -> int:
        async with session_scope(pg_sessions) as session:
            recovered = await recover_notifications(session, now=moment)
            swept.set()
            await renewal_landed.wait()
            return recovered

    async def renew_once() -> bool:
        async with session_scope(pg_sessions) as session:
            return await renew_lease(session, notification_id, owner="live-worker", lease_seconds=300, now=moment)

    async def renew() -> bool:
        await swept.wait()
        renewing = asyncio.ensure_future(renew_once())
        # Long enough to commit if nothing is holding the row, which is the interleaving
        # this guards against.
        await asyncio.sleep(BLOCKED_ON_THE_LOCK)
        renewal_landed.set()
        return await renewing

    _, renewed = await asyncio.gather(sweep(), renew())

    async with pg_sessions() as session:
        row = await session.get(Notification, notification_id)
    assert row is not None
    if renewed:
        assert row.status is NotificationStatus.SENDING, "the lease was renewed and requeued at once"
        assert row.lease_owner == "live-worker"
        assert row.lease_expires_at == moment + timedelta(seconds=300)
    else:
        assert row.status is NotificationStatus.PENDING, "the sweep won the race and left the row claimed"
        assert row.lease_owner is None


def routed(*tags: str) -> PipelineDefinition:
    """A one-step pipeline requiring the given worker tags."""
    return PipelineDefinition(
        code="routed",
        steps={"only": StepDefinition(block="test.echo")},
        requires=Requirements(workers=list(tags)),
    )


async def test_the_claim_routes_by_tag_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """``jsonb`` containment is the subset test, and it holds the way SQLite's walk does."""
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, routed("docker"))
        assert await create_run(session, pg_services, version) is not None

    assert await Engine(pg_sessions, pg_services, owner="plain").claim() is None
    assert await Engine(pg_sessions, pg_services, owner="half", tags=["gpu"]).claim() is None
    assert await Engine(pg_sessions, pg_services, owner="capable", tags=["docker", "gpu"]).claim() is not None


async def test_an_unrouted_run_is_claimable_by_any_worker_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """An empty pinned list is contained by every worker's tags, tagged or not."""
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, routed())
        assert await create_run(session, pg_services, version) is not None

    assert await Engine(pg_sessions, pg_services, owner="plain").claim() is not None


async def test_the_routed_claim_stays_an_indexed_lookup(pg_sessions: async_sessionmaker[AsyncSession]) -> None:
    """The tag filter narrows a row the join already found, never a scan of the queue."""
    statement = due_attempt_statement(utcnow(), ["docker"], postgres=True).with_for_update(
        skip_locked=True, of=StepAttempt
    )
    async with pg_sessions() as session:
        compiled = statement.compile(session.get_bind(), compile_kwargs={"literal_binds": True})
        rows = await session.execute(sa.text(f"EXPLAIN {compiled}"))
        plan = "\n".join(str(line) for line in rows.scalars())
    assert "Seq Scan on runs" not in plan


async def test_two_runs_interleave_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Both dialects have window functions, and both order the claim the same way."""
    big = await start(pg_sessions, pg_services, batch(8).model_copy(update={"code": "big"}))
    small = await start(pg_sessions, pg_services, batch(2).model_copy(update={"code": "small"}))

    taken: list[Any] = []
    for _ in range(4):
        async with session_scope(pg_sessions) as session:
            attempt = await select_due(session, utcnow())
            assert attempt is not None
            taken.append(attempt.run_id)
            attempt.status = AttemptStatus.SUCCEEDED

    assert all(first != second for first, second in zip(taken, taken[1:], strict=False)), taken
    assert set(taken) == {big.id, small.id}


async def test_a_high_run_is_claimed_first_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Priority sorts ahead of fairness on the dialect the claim actually runs on."""
    await start(pg_sessions, pg_services, batch(3).model_copy(update={"code": "ordinary"}))
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, batch(3).model_copy(update={"code": "urgent"}))
        urgent = await create_run(session, pg_services, version, priority=RunPriority.HIGH)
    assert urgent is not None

    async with pg_sessions() as session:
        first = await select_due(session, utcnow())
    assert first is not None
    assert first.run_id == urgent.id


async def test_a_low_run_is_claimed_last_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """Low is last, whichever run's attempts were queued first."""
    async with session_scope(pg_sessions) as session:
        version = await save_pipeline(session, batch(3).model_copy(update={"code": "bulk"}))
        assert await create_run(session, pg_services, version, priority=RunPriority.LOW) is not None
    ordinary = await start(pg_sessions, pg_services, batch(3).model_copy(update={"code": "ordinary"}))

    async with pg_sessions() as session:
        first = await select_due(session, utcnow())
    assert first is not None
    assert first.run_id == ordinary.id


async def test_the_ranked_claim_stays_an_indexed_lookup(pg_sessions: async_sessionmaker[AsyncSession]) -> None:
    """The window ranks the attempts of the runs in flight, never a scan of every run."""
    statement = due_attempt_statement(utcnow(), postgres=True).with_for_update(skip_locked=True, of=StepAttempt)
    async with pg_sessions() as session:
        compiled = statement.compile(session.get_bind(), compile_kwargs={"literal_binds": True})
        rows = await session.execute(sa.text(f"EXPLAIN {compiled}"))
        plan = "\n".join(str(line) for line in rows.scalars())
    assert "Seq Scan on runs" not in plan
    assert "Seq Scan on step_attempts" not in plan


async def test_an_attempt_claimed_while_the_sweeper_waited_is_left_alone(
    pg_sessions: Any, pg_services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep selects without a lock, so a worker can claim the attempt before it settles.

    A worker computes one moment for a whole claim loop, so an attempt whose deadline falls
    inside that loop is claimed and leased while the sweeper, on a later clock, holds it as
    overdue. Settling it there fails a running attempt: the lease is cleared, the worker's
    fence discards its outcome, and a submitted remote job is orphaned with nothing recording
    it.

    This lane, because the interleaving is two transactions open at once: SQLite has one
    write lock and takes it at BEGIN, so the claim below could not commit while the sweep is
    open, and two workers on one SQLite file are refused anyway.
    """
    definition = PipelineDefinition(
        code="deadline-races-a-claim",
        steps={
            "job": StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
                on_timeout=TimeoutAction.FAIL,
            )
        },
    )
    await start(pg_sessions, pg_services, definition)
    engine = Engine(pg_sessions, pg_services, owner="the-sweeping-worker")
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    leased_until = utcnow() + timedelta(minutes=1)

    async def claim_between_the_select_and_the_lock(
        session: AsyncSession, *, now: datetime | None = None
    ) -> list[StepAttempt]:
        overdue = await recovery.overdue_deadlines(session, now=now)
        # A second session, so the claim is committed and invisible to the object the sweep
        # is holding until it re-reads under the lock.
        async with session_scope(pg_sessions) as other:
            claimed = await other.get(StepAttempt, unit.attempt_id)
            assert claimed is not None
            claimed.status = AttemptStatus.RUNNING
            claimed.lease_owner = "the-faster-worker"
            claimed.lease_expires_at = leased_until
        return overdue

    monkeypatch.setattr(executor, "overdue_deadlines", claim_between_the_select_and_the_lock)
    async with session_scope(pg_sessions) as session:
        assert await engine.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1)) == []

    async with pg_sessions() as session:
        running = await session.get(StepAttempt, unit.attempt_id)
    assert running is not None
    assert running.status is AttemptStatus.RUNNING, "the sweep failed an attempt a worker was running"
    assert running.lease_owner == "the-faster-worker", "and released the lease out from under it"
    assert running.lease_expires_at == leased_until


async def test_a_run_cancelled_before_the_lock_is_not_resurrected(
    pg_sessions: Any, pg_services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep reads the run status before its lock, so a cancel can land in between.

    Here for the same reason as the claim above: it is two transactions open at once.
    """
    definition = PipelineDefinition(
        code="deadline-races-a-cancel",
        steps={
            "job": StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
                on_timeout=TimeoutAction.FAIL,
            )
        },
    )
    run = await start(pg_sessions, pg_services, definition)
    engine = Engine(pg_sessions, pg_services, owner="the-sweeping-worker")
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    async def cancel_between_the_select_and_the_lock(
        session: AsyncSession, *, now: datetime | None = None
    ) -> list[StepAttempt]:
        overdue = await recovery.overdue_deadlines(session, now=now)
        async with session_scope(pg_sessions) as other:
            stored = await other.get(Run, run.id)
            assert stored is not None
            await cancel_run(other, pg_services, stored)
        return overdue

    monkeypatch.setattr(executor, "overdue_deadlines", cancel_between_the_select_and_the_lock)
    async with session_scope(pg_sessions) as session:
        # A sweep tick reads before it settles, so the run is in the session's identity map by
        # the time the deadlines are swept, and only a re-read under the lock sees the cancel.
        held = await session.get(Run, run.id)
        assert held is not None
        assert await engine.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1)) == []

    async with pg_sessions() as session:
        cancelled = await session.get(StepAttempt, unit.attempt_id)
        assert cancelled is not None
        assert cancelled.status is AttemptStatus.CANCELLED, "the sweep resurrected an attempt to fail it"
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert stored.status is RunStatus.CANCELLED
