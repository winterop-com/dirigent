"""The scheduler on SQLite: clock arithmetic, the misfire policy, and what a tick writes."""

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import dirigent_core.scheduler as scheduler_module
from dirigent_client.enums import AttemptStatus, FiringOutcome, RunStatus, ScheduleKind, TriggerKind
from dirigent_core import telemetry
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import Attribution, create_run, save_pipeline
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Pipeline, PipelineVersion, Run, Schedule, ScheduleFiring, StepAttempt, utcnow
from dirigent_core.scheduler import (
    MAX_PER_TICK,
    Fired,
    claim_due,
    fire,
    install_signal_handlers,
    is_postgres,
    tick,
    try_lead,
)
from dirigent_core.scheduler import Scheduler as SchedulerProcess
from dirigent_core.triggers.backfill import (
    BACKFILL_CAP,
    COUNT_CEILING,
    BackfillError,
    backfill,
    windows_of,
)
from dirigent_core.triggers.schedules import (
    ScheduleError,
    ScheduleRequest,
    advance_clock,
    check_schedule,
    create_schedule,
    delete_schedule,
    find_schedule,
    list_firings,
    list_schedules,
    next_fire_after,
    next_fire_for,
    occurrences_between,
    set_paused,
    update_schedule,
    window_for,
)

#: The non-UTC zone every timezone assertion here is written against.
OSLO = ZoneInfo("Europe/Oslo")

#: The default misfire grace, spelled out so each assertion says which side of it it is on.
GRACE = timedelta(minutes=5)


def cron_after(expression: str, after: datetime, *, timezone: str = "Europe/Oslo") -> datetime:
    """Compute one cron firing, asserting the clock has not run out."""
    fired = next_fire_after(
        kind=ScheduleKind.CRON,
        cron=expression,
        interval_seconds=None,
        run_at=None,
        timezone=timezone,
        after=after,
    )
    assert fired is not None
    return fired


def one_step(name: str, *, concurrency: ConcurrencyPolicy = ConcurrencyPolicy.ALLOW) -> PipelineDefinition:
    """A one-step pipeline built from the fake blocks."""
    return PipelineDefinition(
        code=name,
        concurrency=concurrency,
        steps={"first": StepDefinition(block="test.echo", config={"value": "one"})},
    )


async def declare(
    sessions: async_sessionmaker[AsyncSession],
    definition: PipelineDefinition,
    request: ScheduleRequest,
    *,
    now: datetime | None = None,
) -> tuple[UUID, UUID]:
    """Save a pipeline version and declare one schedule on it, returning both ids."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        pipeline = await session.get(Pipeline, version.pipeline_id)
        assert pipeline is not None
        schedule = await create_schedule(session, pipeline, request, now=now)
        return pipeline.id, schedule.id


async def load_schedule(sessions: async_sessionmaker[AsyncSession], schedule_id: UUID) -> Schedule:
    """Read a schedule back from the database."""
    async with sessions() as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        return schedule


async def set_columns(sessions: async_sessionmaker[AsyncSession], schedule_id: UUID, **values: object) -> None:
    """Write columns straight onto a schedule row, the way a stale clock would look."""
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Schedule).where(Schedule.id == schedule_id).values(**values))


async def firings_of(sessions: async_sessionmaker[AsyncSession], schedule_id: UUID) -> list[ScheduleFiring]:
    """Read every firing a schedule has recorded, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(ScheduleFiring).where(ScheduleFiring.schedule_id == schedule_id).order_by(ScheduleFiring.id)
        )
        return list(rows.scalars())


async def runs_of(sessions: async_sessionmaker[AsyncSession], pipeline_id: UUID) -> list[Run]:
    """Read every run of a pipeline, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(Run).where(Run.pipeline_id == pipeline_id).order_by(Run.created_at, Run.id)
        )
        return list(rows.scalars())


async def fire_once(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    schedule_id: UUID,
    *,
    now: datetime,
) -> Fired:
    """Fire one schedule in one transaction, the way a tick does."""
    async with session_scope(sessions) as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        return await fire(session, services, schedule, now=now)


async def start_a_run(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    pipeline_id: UUID,
) -> Run:
    """Put one run of a pipeline in flight, for a concurrency policy to decide about."""
    async with session_scope(sessions) as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        assert pipeline is not None
        found = await session.execute(
            sa.select(PipelineVersion).where(
                PipelineVersion.pipeline_id == pipeline.id,
                PipelineVersion.version == pipeline.current_version,
            )
        )
        version = found.scalar_one()
        run = await create_run(session, services, version, attribution=Attribution())
        assert run is not None
        return run


# -- the three clocks ------------------------------------------------------------


def test_a_cron_expression_is_evaluated_in_the_schedules_own_zone_not_in_utc() -> None:
    fired = cron_after("0 5 * * *", datetime(2026, 6, 1, 0, 0, tzinfo=UTC))
    assert fired == datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
    assert fired.astimezone(OSLO).hour == 5


def test_a_cron_schedule_keeps_its_wall_clock_time_across_the_spring_forward() -> None:
    # 2026-03-29 is the Oslo spring-forward: 02:00 becomes 03:00, so 02:30 does not exist
    # that morning. The DST-correct answer keeps the intended local wall time and lets the
    # UTC offset move.
    moment = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
    fired: list[datetime] = []
    for _ in range(3):
        moment = cron_after("30 2 * * *", moment)
        fired.append(moment)

    assert [instant.astimezone(OSLO).isoformat() for instant in fired] == [
        "2026-03-28T02:30:00+01:00",
        "2026-03-29T03:00:00+02:00",
        "2026-03-30T02:30:00+02:00",
    ]
    assert [instant.isoformat() for instant in fired] == [
        "2026-03-28T01:30:00+00:00",
        "2026-03-29T01:00:00+00:00",
        "2026-03-30T00:30:00+00:00",
    ]


def test_a_cron_schedule_fires_once_across_spring_forward_and_once_across_fall_back() -> None:
    """The two mornings a daily schedule can fire twice or not at all."""
    for start, transition in (
        (datetime(2026, 3, 26, 12, 0, tzinfo=UTC), "spring forward"),
        (datetime(2026, 10, 22, 12, 0, tzinfo=UTC), "fall back"),
    ):
        moment = start
        fired: list[datetime] = []
        for _ in range(7):
            moment = cron_after("30 2 * * *", moment)
            fired.append(moment)

        local_days = [instant.astimezone(OSLO).date() for instant in fired]
        assert len(set(local_days)) == len(local_days), f"a day fired twice across {transition}: {local_days}"
        assert local_days == sorted(local_days)
        assert (local_days[-1] - local_days[0]).days == len(local_days) - 1, (
            f"a day was skipped across {transition}: {local_days}"
        )


def test_an_interval_schedule_fires_a_fixed_span_after_the_instant_it_is_given() -> None:
    after = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    fired = next_fire_after(
        kind=ScheduleKind.INTERVAL,
        cron=None,
        interval_seconds=900,
        run_at=None,
        timezone="Europe/Oslo",
        after=after,
    )
    assert fired == after + timedelta(minutes=15)


def test_a_one_time_schedule_fires_once_ahead_and_never_once_it_is_behind() -> None:
    instant = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    ahead = next_fire_after(
        kind=ScheduleKind.ONE_TIME,
        cron=None,
        interval_seconds=None,
        run_at=instant,
        timezone="UTC",
        after=instant - timedelta(hours=1),
    )
    behind = next_fire_after(
        kind=ScheduleKind.ONE_TIME,
        cron=None,
        interval_seconds=None,
        run_at=instant,
        timezone="UTC",
        after=instant + timedelta(seconds=1),
    )
    assert ahead == instant
    assert behind is None


def test_a_cron_expression_that_cannot_be_read_says_so_when_it_is_advanced() -> None:
    with pytest.raises(ScheduleError, match="names no time after"):
        next_fire_after(
            kind=ScheduleKind.CRON,
            cron="not a cron",
            interval_seconds=None,
            run_at=None,
            timezone="UTC",
            after=utcnow(),
        )


# -- what a declaration is refused for -------------------------------------------


def test_a_schedule_that_names_no_clock_at_all_is_refused() -> None:
    with pytest.raises(ScheduleError, match=r"exactly one of cron, interval, or at \(none\)") as refusal:
        check_schedule(ScheduleRequest(code="clockless"))
    assert "exactly one" in str(refusal.value)


def test_a_schedule_that_names_two_clocks_is_refused_naming_both() -> None:
    request = ScheduleRequest(code="two-clocks", cron="* * * * *", interval=timedelta(minutes=5))
    with pytest.raises(ScheduleError, match=r"\(cron, interval\)"):
        check_schedule(request)


def test_a_timezone_this_host_does_not_know_is_refused_with_a_suggestion() -> None:
    request = ScheduleRequest(code="offworld", cron="* * * * *", timezone="Mars/Phobos")
    with pytest.raises(ScheduleError, match="not an IANA timezone this host knows") as refusal:
        check_schedule(request)
    assert "Mars/Phobos" in str(refusal.value)
    assert "Europe/Oslo" in str(refusal.value)


def test_a_malformed_cron_expression_is_refused_at_declaration_time() -> None:
    with pytest.raises(ScheduleError, match="is not a cron expression") as refusal:
        check_schedule(ScheduleRequest(code="wrong", cron="every tuesday please"))
    assert "'every tuesday please'" in str(refusal.value)


def test_an_interval_that_does_not_move_the_clock_forward_is_refused() -> None:
    with pytest.raises(ScheduleError, match="whole number of seconds"):
        check_schedule(ScheduleRequest(code="frozen", interval=timedelta(0)))
    # A negative interval never reaches check_schedule: the grammar has no spelling for a
    # duration that runs backwards, so the Duration type refuses it first.
    with pytest.raises(ValidationError, match="is negative"):
        ScheduleRequest(code="backwards", interval=timedelta(seconds=-30))


# -- the misfire policy ----------------------------------------------------------


async def test_a_firing_inside_the_grace_advances_from_the_slot_it_owed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    owed = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    _, schedule_id = await declare(
        sessions, one_step("on-the-grid"), ScheduleRequest(code="minutely", cron="* * * * *")
    )
    await set_columns(sessions, schedule_id, next_fire_at=owed)

    schedule = await load_schedule(sessions, schedule_id)
    advance = advance_clock(schedule, now=owed + timedelta(minutes=3, seconds=30), grace=GRACE)

    assert advance.misfired is False
    assert advance.lateness == timedelta(minutes=3, seconds=30)
    # From the slot it owed, not from now: a cron schedule keeps its own grid.
    assert advance.next_fire_at == owed + timedelta(minutes=1)
    assert advance.exhausted is False


async def test_a_firing_past_the_grace_is_a_misfire_that_advances_from_now(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    owed = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    now = owed + timedelta(hours=1)
    _, schedule_id = await declare(sessions, one_step("late-riser"), ScheduleRequest(code="minutely", cron="* * * * *"))
    await set_columns(sessions, schedule_id, next_fire_at=owed)

    schedule = await load_schedule(sessions, schedule_id)
    advance = advance_clock(schedule, now=now, grace=GRACE)

    assert advance.misfired is True
    assert advance.lateness == timedelta(hours=1)
    # From now, so the sixty slots that were missed are abandoned rather than caught up.
    assert advance.next_fire_at == now + timedelta(minutes=1)


async def test_an_hour_late_cron_fires_exactly_once_rather_than_sixty_times(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    pipeline_id, schedule_id = await declare(
        sessions, one_step("no-catchup-storm"), ScheduleRequest(code="minutely", cron="* * * * *")
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(hours=1))

    fired = await tick(sessions, services, now=now)

    assert len(fired) == 1
    assert fired[0].misfired is True
    assert len(await firings_of(sessions, schedule_id)) == 1
    assert len(await runs_of(sessions, pipeline_id)) == 1
    schedule = await load_schedule(sessions, schedule_id)
    assert schedule.next_fire_at is not None
    assert timedelta(0) < schedule.next_fire_at - now <= timedelta(minutes=1)


async def test_a_one_time_clock_that_has_run_out_reports_itself_exhausted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    instant = utcnow() - timedelta(minutes=1)
    _, schedule_id = await declare(
        sessions,
        one_step("once-only"),
        ScheduleRequest(code="the-migration", at=instant + timedelta(minutes=2)),
    )
    await set_columns(sessions, schedule_id, run_at=instant, next_fire_at=instant)

    schedule = await load_schedule(sessions, schedule_id)
    advance = advance_clock(schedule, now=instant + timedelta(seconds=1), grace=GRACE)

    assert advance.next_fire_at is None
    assert advance.exhausted is True


# -- declaring, redeclaring, pausing, deleting -----------------------------------


async def test_creating_a_schedule_computes_the_first_firing_up_front(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    _, schedule_id = await declare(
        sessions,
        one_step("declared"),
        ScheduleRequest(code="nightly", cron="0 5 * * *", timezone="Europe/Oslo", params={"day": "today"}),
        now=now,
    )
    schedule = await load_schedule(sessions, schedule_id)
    assert schedule.kind is ScheduleKind.CRON
    assert schedule.next_fire_at == datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
    assert schedule.params == {"day": "today"}
    assert schedule.paused is False


async def test_a_second_schedule_of_the_same_name_on_one_pipeline_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    request = ScheduleRequest(code="nightly", cron="0 5 * * *")
    _, _ = await declare(sessions, one_step("twice-named"), request)
    async with session_scope(sessions) as session:
        pipeline = await session.execute(sa.select(Pipeline).where(Pipeline.code == "twice-named"))
        found = pipeline.scalar_one()
        with pytest.raises(ScheduleError, match="already has a schedule coded 'nightly'"):
            await create_schedule(session, found, request)


async def test_resuming_a_schedule_starts_its_clock_from_now_rather_than_replaying(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, schedule_id = await declare(
        sessions, one_step("paused-a-while"), ScheduleRequest(code="minutely", cron="* * * * *")
    )
    stale = utcnow() - timedelta(days=2)

    async with session_scope(sessions) as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        await set_paused(session, schedule, paused=True)
        schedule.next_fire_at = stale

    assert (await load_schedule(sessions, schedule_id)).paused is True

    async with session_scope(sessions) as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        resumed = await set_paused(session, schedule, paused=False)
        next_fire_at = resumed.next_fire_at

    assert next_fire_at is not None
    assert next_fire_at > stale
    assert next_fire_at > utcnow() - timedelta(minutes=1)
    assert (await load_schedule(sessions, schedule_id)).paused is False


async def test_redeclaring_a_schedule_changes_its_clock_and_leaves_it_paused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    _, schedule_id = await declare(sessions, one_step("redeclared"), ScheduleRequest(code="nightly", cron="0 5 * * *"))
    async with session_scope(sessions) as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        await set_paused(session, schedule, paused=True)

    async with session_scope(sessions) as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        await update_schedule(
            session,
            schedule,
            ScheduleRequest(code="nightly", interval=timedelta(minutes=30), params={"mode": "fast"}),
            now=now,
        )

    schedule = await load_schedule(sessions, schedule_id)
    assert schedule.kind is ScheduleKind.INTERVAL
    assert schedule.interval_seconds == 1800
    assert schedule.cron is None
    assert schedule.params == {"mode": "fast"}
    assert schedule.next_fire_at == now + timedelta(minutes=30)
    assert schedule.paused is True


async def test_deleting_a_schedule_removes_it_from_its_pipeline(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    pipeline_id, schedule_id = await declare(
        sessions, one_step("temporary"), ScheduleRequest(code="nightly", cron="0 5 * * *")
    )
    async with session_scope(sessions) as session:
        schedule = await session.get(Schedule, schedule_id)
        assert schedule is not None
        await delete_schedule(session, schedule)

    async with sessions() as session:
        assert await find_schedule(session, pipeline_id, "nightly") is None
        assert await list_schedules(session, pipeline_id) == []
        assert await list_schedules(session) == []


# -- what a tick is allowed to claim ---------------------------------------------


async def due_schedule(
    sessions: async_sessionmaker[AsyncSession],
    name: str,
    *,
    now: datetime,
) -> tuple[UUID, UUID]:
    """Declare a schedule on its own pipeline whose clock came due a minute ago."""
    pipeline_id, schedule_id = await declare(
        sessions, one_step(name), ScheduleRequest(code="minutely", cron="* * * * *")
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))
    return pipeline_id, schedule_id


async def test_claim_due_returns_a_schedule_whose_clock_has_come_due(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "is-due", now=now)
    async with sessions() as session:
        assert [schedule.id for schedule in await claim_due(session, now)] == [schedule_id]


async def test_claim_due_leaves_a_schedule_whose_clock_has_not_come_due(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "not-yet", now=now)
    await set_columns(sessions, schedule_id, next_fire_at=now + timedelta(minutes=1))
    async with sessions() as session:
        assert await claim_due(session, now) == []


async def test_claim_due_leaves_a_paused_schedule_alone(sessions: async_sessionmaker[AsyncSession]) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "resting", now=now)
    await set_columns(sessions, schedule_id, paused=True)
    async with sessions() as session:
        assert await claim_due(session, now) == []


async def test_claim_due_leaves_a_schedule_with_no_clock_left_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "spent", now=now)
    await set_columns(sessions, schedule_id, next_fire_at=None)
    async with sessions() as session:
        assert await claim_due(session, now) == []


async def test_claim_due_leaves_a_deactivated_pipelines_schedule_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = utcnow()
    pipeline_id, _ = await due_schedule(sessions, "switched-off", now=now)
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Pipeline).where(Pipeline.id == pipeline_id).values(active=False))
    async with sessions() as session:
        assert await claim_due(session, now) == []


async def test_claim_due_honours_the_limit_it_is_given(sessions: async_sessionmaker[AsyncSession]) -> None:
    now = utcnow()
    await due_schedule(sessions, "first-of-two", now=now)
    await due_schedule(sessions, "second-of-two", now=now)
    async with sessions() as session:
        assert len(await claim_due(session, now)) == 2
        assert len(await claim_due(session, now, limit=1)) == 1


# -- firing, and the concurrency policy ------------------------------------------


async def test_an_allow_policy_fires_and_records_the_run_it_created(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    pipeline_id, schedule_id = await due_schedule(sessions, "allowed", now=now)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FIRED
    assert fired.run_id is not None
    assert fired.detail is None
    runs = await runs_of(sessions, pipeline_id)
    assert [str(run.id) for run in runs] == [fired.run_id]
    assert runs[0].triggered_by_kind is TriggerKind.SCHEDULE
    assert runs[0].triggered_by_label == "schedule minutely"

    firings = await firings_of(sessions, schedule_id)
    assert len(firings) == 1
    assert firings[0].outcome is FiringOutcome.FIRED
    assert firings[0].run_id == runs[0].id
    assert firings[0].scheduled_for == now - timedelta(minutes=1)
    assert firings[0].created_at == now
    assert firings[0].misfired is False


async def test_a_schedule_copies_its_log_levels_onto_the_runs_it_fires(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The 3am debugging story: the schedule holds the map, and every firing carries it."""
    now = utcnow()
    pipeline_id, schedule_id = await declare(
        sessions,
        one_step("nightly-loud"),
        ScheduleRequest(code="minutely", cron="* * * * *", log_levels={"*": "debug"}),
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FIRED
    runs = await runs_of(sessions, pipeline_id)
    assert runs[0].log_levels == {"*": "debug"}


async def test_a_skip_policy_with_a_run_in_flight_records_a_skip_and_creates_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    pipeline_id, schedule_id = await declare(
        sessions,
        one_step("skipper", concurrency=ConcurrencyPolicy.SKIP),
        ScheduleRequest(code="minutely", cron="* * * * *"),
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))
    in_flight = await start_a_run(sessions, services, pipeline_id)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.SKIPPED
    assert fired.run_id is None
    assert fired.detail == "a run of this pipeline is already in flight"
    assert [run.id for run in await runs_of(sessions, pipeline_id)] == [in_flight.id]

    firings = await firings_of(sessions, schedule_id)
    assert len(firings) == 1
    assert firings[0].outcome is FiringOutcome.SKIPPED
    assert firings[0].run_id is None


async def test_a_queue_policy_holds_the_run_it_creates_behind_the_one_in_flight(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    pipeline_id, schedule_id = await declare(
        sessions,
        one_step("queuer", concurrency=ConcurrencyPolicy.QUEUE),
        ScheduleRequest(code="minutely", cron="* * * * *"),
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))
    in_flight = await start_a_run(sessions, services, pipeline_id)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.QUEUED
    assert fired.run_id is not None and fired.run_id != str(in_flight.id)
    held = [run for run in await runs_of(sessions, pipeline_id) if str(run.id) == fired.run_id]
    assert len(held) == 1
    assert held[0].status is RunStatus.QUEUED
    async with sessions() as session:
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == held[0].id))
        assert [attempt.status for attempt in rows.scalars()] == [AttemptStatus.PENDING]

    assert (await firings_of(sessions, schedule_id))[0].outcome is FiringOutcome.QUEUED


async def test_a_replace_policy_cancels_the_run_in_flight_and_says_so(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    pipeline_id, schedule_id = await declare(
        sessions,
        one_step("replacer", concurrency=ConcurrencyPolicy.REPLACE),
        ScheduleRequest(code="minutely", cron="* * * * *"),
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))
    in_flight = await start_a_run(sessions, services, pipeline_id)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.REPLACED
    assert fired.detail == "the run in flight was cancelled and replaced"
    runs = {str(run.id): run for run in await runs_of(sessions, pipeline_id)}
    assert runs[str(in_flight.id)].status is RunStatus.CANCELLED
    assert runs[str(in_flight.id)].error == "replaced by a newer run"
    assert fired.run_id is not None
    assert runs[fired.run_id].status is RunStatus.QUEUED
    assert (await firings_of(sessions, schedule_id))[0].outcome is FiringOutcome.REPLACED


async def test_a_pipeline_with_no_current_version_records_a_failed_firing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    async with session_scope(sessions) as session:
        pipeline = Pipeline(code="versionless")
        session.add(pipeline)
        await session.flush()
        schedule = await create_schedule(session, pipeline, ScheduleRequest(code="minutely", cron="* * * * *"))
        schedule_id = schedule.id
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FAILED
    assert fired.detail == "the pipeline has no current version to run"
    assert fired.run_id is None
    assert (await firings_of(sessions, schedule_id))[0].outcome is FiringOutcome.FAILED


async def test_a_run_the_instance_refuses_to_create_records_a_failed_firing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    definition = PipelineDefinition(code="gated", steps={"run": StepDefinition(block="test.unsafe")})
    _, schedule_id = await declare(sessions, definition, ScheduleRequest(code="minutely", cron="* * * * *"))
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FAILED
    assert fired.detail is not None
    assert "executes code on the worker and is disabled" in fired.detail


async def test_a_firing_whose_fan_out_refuses_leaves_no_run_rows_behind(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The run row and its queued root attempts are written before the fan-out refuses."""
    now = utcnow()
    definition = PipelineDefinition(
        code="bad-fan-out",
        steps={
            "first": StepDefinition(block="test.echo", config={"value": "one"}),
            "spread": StepDefinition(block="test.echo", for_each="${params.items}", depends_on=["first"]),
        },
    )
    pipeline_id, schedule_id = await declare(
        sessions,
        definition,
        ScheduleRequest(code="minutely", cron="* * * * *", params={"items": "not-a-list"}),
    )
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(minutes=1))

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FAILED
    assert fired.detail is not None
    assert "not a list" in fired.detail
    assert fired.run_id is None
    assert await runs_of(sessions, pipeline_id) == []
    async with sessions() as session:
        attempts = list((await session.execute(sa.select(StepAttempt))).scalars())
    assert attempts == [], "the trigger was rejected, and a worker could still claim its attempts"
    assert (await firings_of(sessions, schedule_id))[0].outcome is FiringOutcome.FAILED


async def test_a_pipeline_whose_parameter_schema_is_broken_fails_the_firing_and_still_advances(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A schema jsonschema cannot use must not wedge the clock: the tick would never advance."""
    now = utcnow()
    definition = PipelineDefinition(
        code="mistyped",
        params={"type": "objcet"},
        steps={"first": StepDefinition(block="test.echo")},
    )
    _, schedule_id = await declare(sessions, definition, ScheduleRequest(code="minutely", cron="* * * * *"))
    owed = now - timedelta(minutes=1)
    await set_columns(sessions, schedule_id, next_fire_at=owed)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FAILED
    assert fired.detail is not None
    assert "parameter schema is not itself valid JSON Schema" in fired.detail
    assert fired.run_id is None
    assert (await firings_of(sessions, schedule_id))[0].outcome is FiringOutcome.FAILED
    advanced = await load_schedule(sessions, schedule_id)
    assert advanced.next_fire_at is not None
    assert advanced.next_fire_at > owed, "a schedule that cannot run must not stay due forever"
    assert advanced.paused is False


async def test_the_run_and_the_advanced_clock_become_visible_in_one_commit(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    owed = now - timedelta(minutes=1)
    pipeline_id, schedule_id = await due_schedule(sessions, "atomic", now=now)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    # One commit later, the run, the firing, and the moved clock are all there.
    schedule = await load_schedule(sessions, schedule_id)
    assert schedule.last_fired_at == now
    assert schedule.next_fire_at == fired.next_fire_at
    assert schedule.next_fire_at is not None and schedule.next_fire_at > owed
    assert len(await runs_of(sessions, pipeline_id)) == 1
    assert len(await firings_of(sessions, schedule_id)) == 1

    async with sessions() as session:
        recent = await list_firings(session, schedule_id)
        assert [firing.outcome for firing in recent] == [FiringOutcome.FIRED]


async def test_a_one_time_schedule_pauses_itself_once_its_instant_has_passed(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    instant = now - timedelta(seconds=30)
    _, schedule_id = await declare(
        sessions,
        one_step("once-then-done"),
        ScheduleRequest(code="the-migration", at=now + timedelta(hours=1)),
    )
    await set_columns(sessions, schedule_id, run_at=instant, next_fire_at=instant)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FIRED
    assert fired.next_fire_at is None
    schedule = await load_schedule(sessions, schedule_id)
    assert schedule.next_fire_at is None
    assert schedule.paused is True


# -- the tick --------------------------------------------------------------------


async def test_a_tick_fires_everything_due_and_writes_one_firing_each(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    _, first = await due_schedule(sessions, "first-due", now=now)
    _, second = await due_schedule(sessions, "second-due", now=now)
    _, later = await due_schedule(sessions, "much-later", now=now)
    await set_columns(sessions, later, next_fire_at=now + timedelta(hours=1))

    fired = await tick(sessions, services, now=now)

    assert len(fired) == 2
    assert {entry.outcome for entry in fired} == {FiringOutcome.FIRED}
    assert len(await firings_of(sessions, first)) == 1
    assert len(await firings_of(sessions, second)) == 1
    assert await firings_of(sessions, later) == []


async def test_a_tick_with_nothing_due_does_nothing_at_all(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    assert await tick(sessions, services) == []


async def test_a_tick_reports_how_late_the_oldest_due_schedule_was(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "ninety-late", now=now)
    await set_columns(sessions, schedule_id, next_fire_at=now - timedelta(seconds=90))

    await tick(sessions, services, now=now)
    assert telemetry.gauges.scheduler_lag == 90.0

    await set_columns(sessions, schedule_id, next_fire_at=now + timedelta(hours=1))
    await tick(sessions, services, now=now)
    assert telemetry.gauges.scheduler_lag == 0.0


async def test_a_schedule_whose_clock_cannot_be_read_pauses_itself_and_records_a_failure(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = utcnow()
    _, unreadable = await due_schedule(sessions, "unreadable", now=now)
    _, healthy = await due_schedule(sessions, "healthy", now=now)
    # A zone that was valid when it was declared and is not on this host any more, which is
    # what a restore onto a different image looks like.
    await set_columns(sessions, unreadable, timezone="Mars/Phobos")

    fired = await tick(sessions, services, now=now)

    assert [entry.schedule for entry in fired] == ["minutely"]
    assert len(await firings_of(sessions, healthy)) == 1

    broken = await load_schedule(sessions, unreadable)
    assert broken.paused is True
    firings = await firings_of(sessions, unreadable)
    assert len(firings) == 1
    assert firings[0].outcome is FiringOutcome.FAILED
    assert firings[0].run_id is None
    assert firings[0].detail is not None
    assert "not an IANA timezone" in firings[0].detail
    assert "paused until it is corrected" in firings[0].detail


# -- the process ------------------------------------------------------------------


async def test_leadership_is_a_no_op_on_sqlite(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session:
        assert is_postgres(session) is False
        assert await try_lead(session, 0x64_69_72_67) is True


async def test_a_scheduler_asked_to_stop_before_it_leads_never_takes_leadership(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    scheduler = SchedulerProcess(sessions, services, tick_seconds=0.01)
    scheduler.request_stop()
    scheduler.request_stop()  # asking twice is not an error, and says nothing twice

    await scheduler.run()

    assert scheduler.stopping is True
    assert scheduler.leading is False


async def test_the_scheduler_loop_leads_ticks_and_exits_when_asked_to_stop(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "loop-fed", now=now)
    scheduler = SchedulerProcess(sessions, services, tick_seconds=0.01)
    assert scheduler.tick_seconds == 0.01

    # Driven off the tick itself rather than off the clock: polling for a firing and then
    # asking the loop to stop races a real tick against a wall-clock budget.
    ticked = asyncio.Event()
    real_tick = scheduler_module.tick

    async def tick_once(*args: object, **kwargs: object) -> list[Fired]:
        fired = await real_tick(*args, **kwargs)  # type: ignore[arg-type]
        ticked.set()
        scheduler.request_stop()
        return fired

    monkeypatch.setattr(scheduler_module, "tick", tick_once)

    task = asyncio.create_task(scheduler.run())
    await asyncio.wait_for(ticked.wait(), timeout=10)
    await asyncio.wait_for(task, timeout=10)

    assert scheduler.leading is False
    assert len(await firings_of(sessions, schedule_id)) == 1


async def test_a_failing_tick_pauses_the_loop_rather_than_ending_the_process(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted: list[datetime] = []

    async def failing(*_args: object, **_kwargs: object) -> list[Fired]:
        attempted.append(utcnow())
        raise RuntimeError("the database went away")

    monkeypatch.setattr(scheduler_module, "tick", failing)
    scheduler = SchedulerProcess(sessions, services, tick_seconds=0.01)

    task = asyncio.create_task(scheduler.run())
    for _ in range(500):
        if len(attempted) >= 2:
            break
        await asyncio.sleep(0.01)
    scheduler.request_stop()
    await asyncio.wait_for(task, timeout=10)

    # A transient database failure is a pause, not an exit: the loop kept ticking.
    assert len(attempted) >= 2


async def test_the_listing_is_advisory_and_the_row_lock_decides_what_is_fired(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = utcnow()
    _, schedule_id = await due_schedule(sessions, "second-thoughts", now=now)
    # Paused after the listing was taken, so the re-read inside the firing transaction is
    # what drops it.
    await set_columns(sessions, schedule_id, paused=True)

    async def listed(session: AsyncSession, moment: datetime, *, limit: int = MAX_PER_TICK) -> list[Schedule]:
        schedule = await session.get(Schedule, schedule_id)
        return [schedule] if schedule is not None else []

    monkeypatch.setattr(scheduler_module, "claim_due", listed)

    assert await tick(sessions, services, now=now) == []
    assert await firings_of(sessions, schedule_id) == []


async def test_signal_handlers_ask_a_running_scheduler_to_stop(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    scheduler = SchedulerProcess(sessions, services, tick_seconds=0.01)
    loop = asyncio.get_running_loop()
    install_signal_handlers(scheduler)
    try:
        signal.raise_signal(signal.SIGTERM)
        for _ in range(500):
            if scheduler.stopping:
                break
            await asyncio.sleep(0.01)
        assert scheduler.stopping is True
    finally:
        for received in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(received)


# -- the window a firing covers --------------------------------------------------


def a_schedule(**values: object) -> Schedule:
    """One unsaved schedule row, which is all the cadence arithmetic ever reads."""
    values.setdefault("timezone", "Europe/Oslo")
    return Schedule(code="nightly", **values)


def local(moment: datetime) -> str:
    """Render an instant in Oslo, which is the zone every window assertion here is written in."""
    return moment.astimezone(OSLO).isoformat()


def test_a_cron_firing_covers_the_interval_that_just_closed() -> None:
    schedule = a_schedule(kind=ScheduleKind.CRON, cron="30 2 * * *")
    window = window_for(schedule, datetime(2026, 6, 10, 0, 30, tzinfo=UTC))
    assert window is not None
    assert (local(window.start), local(window.end)) == ("2026-06-09T02:30:00+02:00", "2026-06-10T02:30:00+02:00")


def test_a_cron_window_is_wall_clock_so_it_shortens_and_lengthens_across_a_dst_boundary() -> None:
    """A nightly window is a day of Oslo's clock, not a fixed 24 hours.

    2026-03-29 is the Oslo spring-forward, where 02:30 does not exist and the firing lands at
    03:00; 2026-10-25 is the fall-back. The window between two firings is the wall-clock
    cadence, so it loses an hour across one boundary and gains one across the other.
    """
    schedule = a_schedule(kind=ScheduleKind.CRON, cron="30 2 * * *")
    covered: list[tuple[str, str, str]] = []
    moment = datetime(2026, 3, 26, 12, 0, tzinfo=UTC)
    for _ in range(4):
        fired = next_fire_for(schedule, moment)
        assert fired is not None
        window = window_for(schedule, fired)
        assert window is not None
        covered.append((local(window.start), local(window.end), str(window.end - window.start)))
        moment = fired

    assert covered == [
        ("2026-03-26T02:30:00+01:00", "2026-03-27T02:30:00+01:00", "1 day, 0:00:00"),
        ("2026-03-27T02:30:00+01:00", "2026-03-28T02:30:00+01:00", "1 day, 0:00:00"),
        # The morning the hour disappears: the firing moves to 03:00 and the window it closes
        # is half an hour short of a day.
        ("2026-03-28T02:30:00+01:00", "2026-03-29T03:00:00+02:00", "23:30:00"),
        ("2026-03-29T03:00:00+02:00", "2026-03-30T02:30:00+02:00", "23:30:00"),
    ]

    autumn = window_for(schedule, datetime(2026, 10, 26, 1, 30, tzinfo=UTC))
    assert autumn is not None
    # The morning the hour happens twice, which is a day and an hour of real time.
    assert (local(autumn.start), local(autumn.end)) == ("2026-10-25T02:30:00+02:00", "2026-10-26T02:30:00+01:00")
    assert autumn.end - autumn.start == timedelta(hours=25)


def test_an_interval_firing_covers_exactly_one_interval_before_it() -> None:
    schedule = a_schedule(kind=ScheduleKind.INTERVAL, interval_seconds=3600)
    window = window_for(schedule, datetime(2026, 6, 10, 9, 0, tzinfo=UTC))
    assert window is not None
    assert window.start == datetime(2026, 6, 10, 8, 0, tzinfo=UTC)
    assert window.end == datetime(2026, 6, 10, 9, 0, tzinfo=UTC)


def test_a_one_time_firing_covers_no_window_because_it_has_no_cadence() -> None:
    schedule = a_schedule(kind=ScheduleKind.ONE_TIME, run_at=datetime(2026, 6, 10, tzinfo=UTC))
    assert window_for(schedule, datetime(2026, 6, 10, tzinfo=UTC)) is None


async def test_a_fired_run_carries_the_window_the_firing_owed_not_the_one_it_was_claimed_in(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A late firing still covers its own slot, because the window comes from the due time."""
    now = datetime(2026, 6, 10, 5, 30, tzinfo=UTC)
    due = datetime(2026, 6, 10, 5, 0, tzinfo=UTC)
    pipeline_id, schedule_id = await declare(
        sessions, one_step("windowed"), ScheduleRequest(code="hourly", interval=timedelta(hours=1))
    )
    await set_columns(sessions, schedule_id, next_fire_at=due)

    fired = await fire_once(sessions, services, schedule_id, now=now)

    assert fired.outcome is FiringOutcome.FIRED
    runs = await runs_of(sessions, pipeline_id)
    assert runs[0].window_start == datetime(2026, 6, 10, 4, 0, tzinfo=UTC)
    assert runs[0].window_end == due


async def test_a_one_time_firing_creates_a_run_with_no_window(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    now = datetime(2026, 6, 10, 5, 0, tzinfo=UTC)
    pipeline_id, schedule_id = await declare(
        sessions, one_step("once"), ScheduleRequest(code="launch", at=datetime(2026, 6, 10, 5, 0, tzinfo=UTC))
    )
    await set_columns(sessions, schedule_id, next_fire_at=now)

    await fire_once(sessions, services, schedule_id, now=now)

    runs = await runs_of(sessions, pipeline_id)
    assert runs[0].window_start is None
    assert runs[0].window_end is None


# -- enumerating the occurrences a backfill fills --------------------------------


def test_enumeration_includes_the_lower_bound_and_excludes_the_upper() -> None:
    schedule = a_schedule(kind=ScheduleKind.CRON, cron="0 5 * * *", timezone="UTC")
    found = list(
        occurrences_between(
            schedule,
            start=datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
            end=datetime(2026, 6, 4, 5, 0, tzinfo=UTC),
        )
    )
    assert found == [
        datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
        datetime(2026, 6, 2, 5, 0, tzinfo=UTC),
        datetime(2026, 6, 3, 5, 0, tzinfo=UTC),
    ]


def test_an_interval_enumeration_is_anchored_on_the_lower_bound_it_was_given() -> None:
    schedule = a_schedule(kind=ScheduleKind.INTERVAL, interval_seconds=1800)
    found = list(
        occurrences_between(
            schedule,
            start=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
            end=datetime(2026, 6, 1, 1, 30, tzinfo=UTC),
        )
    )
    assert found == [
        datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
        datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    ]


def test_an_interval_enclosing_no_occurrence_enumerates_nothing() -> None:
    schedule = a_schedule(kind=ScheduleKind.CRON, cron="0 5 * * *", timezone="UTC")
    found = list(
        occurrences_between(
            schedule,
            start=datetime(2026, 6, 1, 6, 0, tzinfo=UTC),
            end=datetime(2026, 6, 2, 4, 0, tzinfo=UTC),
        )
    )
    assert found == []


# -- backfill: filling the windows the cadence has gone past ---------------------


async def a_backfillable_pipeline(
    sessions: async_sessionmaker[AsyncSession],
    name: str,
    request: ScheduleRequest,
) -> tuple[PipelineVersion, Schedule]:
    """Save a pipeline and one schedule, and hand back the two rows a backfill needs."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, one_step(name))
        pipeline = await session.get(Pipeline, version.pipeline_id)
        assert pipeline is not None
        schedule = await create_schedule(session, pipeline, request)
        return version, schedule


NIGHTLY = ScheduleRequest(code="nightly", cron="0 5 * * *", timezone="UTC")


async def test_a_backfill_creates_one_run_per_window_oldest_first(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    version, schedule = await a_backfillable_pipeline(sessions, "filled", NIGHTLY)

    async with session_scope(sessions) as session:
        filled = await backfill(
            session,
            services,
            version,
            schedule,
            start=datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
            end=datetime(2026, 6, 4, 5, 0, tzinfo=UTC),
        )

    assert [one.window.end for one in filled] == [
        datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
        datetime(2026, 6, 2, 5, 0, tzinfo=UTC),
        datetime(2026, 6, 3, 5, 0, tzinfo=UTC),
    ]
    assert all(one.run_id is not None for one in filled)
    runs = await runs_of(sessions, version.pipeline_id)
    assert [run.window_end for run in runs] == [one.window.end for one in filled], "oldest first"
    assert {run.triggered_by_kind for run in runs} == {TriggerKind.BACKFILL}
    assert {run.triggered_by_label for run in runs} == {"backfill nightly"}


async def test_a_backfill_leaves_the_schedules_own_clock_exactly_where_it_was(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """These firings never happened, so nothing about the schedule may move."""
    version, schedule = await a_backfillable_pipeline(sessions, "untouched", NIGHTLY)
    before = (schedule.next_fire_at, schedule.last_fired_at, schedule.paused)

    async with session_scope(sessions) as session:
        await backfill(
            session,
            services,
            version,
            schedule,
            start=datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
            end=datetime(2026, 6, 3, 5, 0, tzinfo=UTC),
        )

    after = await load_schedule(sessions, schedule.id)
    assert (after.next_fire_at, after.last_fired_at, after.paused) == before
    assert await firings_of(sessions, schedule.id) == []


async def test_a_dry_run_plans_the_windows_and_writes_no_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    version, schedule = await a_backfillable_pipeline(sessions, "planned", NIGHTLY)

    async with session_scope(sessions) as session:
        planned = await backfill(
            session,
            services,
            version,
            schedule,
            start=datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
            end=datetime(2026, 6, 4, 5, 0, tzinfo=UTC),
            dry_run=True,
        )

    assert len(planned) == 3
    assert [one.run_id for one in planned] == [None, None, None]
    assert await runs_of(sessions, version.pipeline_id) == []


async def test_a_backfill_of_a_skip_pipeline_says_which_windows_the_policy_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, one_step("skipper", concurrency=ConcurrencyPolicy.SKIP))
        pipeline = await session.get(Pipeline, version.pipeline_id)
        assert pipeline is not None
        schedule = await create_schedule(session, pipeline, NIGHTLY)

    async with session_scope(sessions) as session:
        filled = await backfill(
            session,
            services,
            version,
            schedule,
            start=datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
            end=datetime(2026, 6, 4, 5, 0, tzinfo=UTC),
        )

    assert len(filled) == 3, "every window is enumerated and reported on"
    assert filled[0].run_id is not None
    assert [one.run_id for one in filled[1:]] == [None, None]
    assert all(one.detail == "a run of this pipeline is already in flight" for one in filled[1:])


async def test_a_backfill_takes_the_schedules_pins_unless_it_is_handed_others(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    version, schedule = await a_backfillable_pipeline(
        sessions, "pinned", ScheduleRequest(code="nightly", cron="0 5 * * *", timezone="UTC")
    )
    schedule.params = {}

    async with session_scope(sessions) as session:
        filled = await backfill(
            session,
            services,
            version,
            schedule,
            start=datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
            end=datetime(2026, 6, 2, 5, 0, tzinfo=UTC),
        )

    assert len(filled) == 1
    runs = await runs_of(sessions, version.pipeline_id)
    assert runs[0].params == {}


def test_a_one_time_schedule_has_no_cadence_a_backfill_could_enumerate() -> None:
    schedule = a_schedule(kind=ScheduleKind.ONE_TIME, run_at=datetime(2026, 6, 10, tzinfo=UTC))
    with pytest.raises(BackfillError, match="no cadence to enumerate"):
        windows_of(schedule, start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 2, 1, tzinfo=UTC))


def test_a_backfill_past_the_cap_is_refused_naming_the_cap_and_the_count() -> None:
    schedule = a_schedule(kind=ScheduleKind.CRON, cron="0 5 * * *", timezone="UTC")
    with pytest.raises(BackfillError, match=f"at most {BACKFILL_CAP} runs") as refusal:
        windows_of(schedule, start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2027, 1, 1, tzinfo=UTC))
    assert "enumerates 365" in str(refusal.value)


def test_a_backfill_far_past_the_ceiling_says_more_than_it_bothered_to_count() -> None:
    """A minutely schedule over a month is 44 640 firings; the walk stops rather than counting."""
    schedule = a_schedule(kind=ScheduleKind.INTERVAL, interval_seconds=60)
    with pytest.raises(BackfillError, match=f"more than {COUNT_CEILING}"):
        windows_of(schedule, start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 2, 1, tzinfo=UTC))


def test_a_backfill_exactly_at_the_cap_is_allowed() -> None:
    schedule = a_schedule(kind=ScheduleKind.INTERVAL, interval_seconds=3600)
    windows = windows_of(
        schedule,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=BACKFILL_CAP),
    )
    assert len(windows) == BACKFILL_CAP
