"""What applying a document does to a pipeline's triggers, and the rate limiter intake shares."""

from datetime import timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import ScheduleKind
from dirigent_client.schemas import PlanAction
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Run, Schedule, utcnow
from dirigent_core.pipelines import apply_document, find_pipeline
from dirigent_core.ratelimit import TokenBucket
from dirigent_core.scheduler import claim_due, tick
from dirigent_core.triggers.schedules import (
    ScheduleError,
    ScheduleRequest,
    create_schedule,
    find_schedule,
    list_schedules,
    set_paused,
)

#: A pipeline document with no triggers, which every materialization test starts from.
BASE = """
format: dirigent/v1
code: daily-load
steps:
  first:
    block: test.echo
    config: { value: one }
"""

#: The same pipeline, now declaring one schedule.
WITH_TRIGGERS = (
    BASE
    + """
triggers:
  schedules:
    - code: nightly
      cron: "0 5 * * *"
      timezone: Europe/Oslo
"""
)


async def runs_of(sessions: async_sessionmaker[AsyncSession], pipeline_id: UUID) -> list[Run]:
    """Read every run of a pipeline, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(Run).where(Run.pipeline_id == pipeline_id).order_by(Run.created_at, Run.id)
        )
        return list(rows.scalars())


async def apply(sessions: async_sessionmaker[AsyncSession], services: EngineServices, text: str) -> object:
    """Apply one document, which is where a ``triggers:`` section becomes rows."""
    async with session_scope(sessions) as session:
        return await apply_document(session, services, load_text(text))


async def schedule_named(sessions: async_sessionmaker[AsyncSession], pipeline_name: str, name: str) -> Schedule | None:
    """Find one schedule by pipeline name and schedule name."""
    async with sessions() as session:
        pipeline = await find_pipeline(session, pipeline_name)
        assert pipeline is not None
        return await find_schedule(session, pipeline.id, name)


# -- the rate limiter ------------------------------------------------------------


def test_a_bucket_allows_up_to_the_limit_and_then_refuses() -> None:
    bucket = TokenBucket()
    assert [bucket.allow("token", per_minute=3, now=0.0) for _ in range(3)] == [True, True, True]
    assert bucket.allow("token", per_minute=3, now=0.0) is False


def test_a_bucket_refills_as_time_passes() -> None:
    bucket = TokenBucket()
    for _ in range(2):
        assert bucket.allow("token", per_minute=2, now=0.0) is True
    assert bucket.allow("token", per_minute=2, now=0.0) is False
    # Two a minute is one every thirty seconds, so half a minute buys exactly one more.
    assert bucket.allow("token", per_minute=2, now=29.0) is False
    assert bucket.allow("token", per_minute=2, now=60.0) is True


def test_one_key_going_too_fast_does_not_slow_another_down() -> None:
    bucket = TokenBucket()
    assert bucket.allow("first", per_minute=1, now=0.0) is True
    assert bucket.allow("first", per_minute=1, now=0.0) is False
    assert bucket.allow("second", per_minute=1, now=0.0) is True


def test_a_forgotten_key_starts_over_with_a_full_bucket() -> None:
    bucket = TokenBucket()
    assert bucket.allow("token", per_minute=1, now=0.0) is True
    assert bucket.allow("token", per_minute=1, now=0.0) is False
    bucket.forget("token")
    assert bucket.allow("token", per_minute=1, now=0.0) is True


def test_a_bucket_left_to_its_own_clock_still_allows_the_first_call() -> None:
    assert TokenBucket().allow("token", per_minute=1) is True


# -- what an apply does to the triggers ------------------------------------------


async def test_applying_a_document_with_triggers_creates_them_and_marks_them_managed(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(WITH_TRIGGERS))

    assert result.triggers.schedules_created == ["nightly"]
    assert result.triggers.empty is False

    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.managed is True
    assert schedule.kind is ScheduleKind.CRON
    assert schedule.timezone == "Europe/Oslo"
    assert schedule.next_fire_at is not None


async def test_a_document_that_declares_no_triggers_reconciles_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(BASE))
    assert result.triggers.empty is True
    async with sessions() as session:
        assert await list_schedules(session) == []


async def test_reapplying_an_unchanged_document_changes_nothing_and_keeps_the_next_firing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    before = await schedule_named(sessions, "daily-load", "nightly")
    assert before is not None
    first_fire_at = before.next_fire_at

    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(WITH_TRIGGERS))

    assert again.triggers.empty is True
    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    # Compared field by field rather than rewritten, so re-applying does not move every
    # firing to a new grid.
    assert after.next_fire_at == first_fire_at
    assert after.id == before.id


async def test_reapplying_an_unchanged_document_restores_a_schedule_deleted_by_hand(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The digest covers the document, not the instance, so convergence cannot stop at it."""
    await apply(sessions, services, WITH_TRIGGERS)
    before = await schedule_named(sessions, "daily-load", "nightly")
    assert before is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, before.id)
        assert row is not None
        await session.delete(row)
    assert await schedule_named(sessions, "daily-load", "nightly") is None

    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(WITH_TRIGGERS))

    assert again.plan.action is PlanAction.UNCHANGED
    assert again.triggers.schedules_created == ["nightly"]
    restored = await schedule_named(sessions, "daily-load", "nightly")
    assert restored is not None
    assert restored.cron == before.cron


async def test_reapplying_a_document_leaves_a_schedule_someone_paused_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=True)

    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"', 'cron: "0 6 * * *"')
    await apply(sessions, services, changed)

    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.cron == "0 6 * * *"
    assert after.paused is True


async def test_a_plain_apply_creates_a_schedule_that_is_not_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)

    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.paused is False


async def test_a_paused_apply_creates_the_schedule_already_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(WITH_TRIGGERS), paused=True)

    assert result.triggers.schedules_created == ["nightly"]
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.paused is True
    assert schedule.next_fire_at is not None


async def test_a_paused_apply_leaves_no_moment_in_which_a_due_schedule_could_fire(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The row is inserted paused, so the first tick that could see it already cannot fire it."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(WITH_TRIGGERS), paused=True)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.next_fire_at is not None
    due = schedule.next_fire_at

    assert await tick(sessions, services, now=due) == []
    async with sessions() as session:
        assert await claim_due(session, due) == []
    assert await runs_of(sessions, schedule.pipeline_id) == []

    # The clock was genuinely due: resuming it makes the same tick fire.
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=False)
    resumed = await schedule_named(sessions, "daily-load", "nightly")
    assert resumed is not None
    assert resumed.next_fire_at is not None
    fired = await tick(sessions, services, now=resumed.next_fire_at)
    assert [entry.schedule for entry in fired] == ["nightly"]


async def test_reapplying_without_the_flag_leaves_a_resumed_schedule_running(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(WITH_TRIGGERS), paused=True)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=False)

    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"', 'cron: "0 6 * * *"')
    await apply(sessions, services, changed)

    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.cron == "0 6 * * *"
    assert after.paused is False


async def test_reapplying_with_the_flag_does_not_re_pause_a_schedule_that_already_exists(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """--paused governs what an apply brings into being, never what already runs."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(WITH_TRIGGERS), paused=True)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=False)

    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"', 'cron: "0 7 * * *"')
    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(changed), paused=True)

    assert again.triggers.schedules_updated == ["nightly"]
    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.paused is False


async def test_a_schedule_dropped_from_the_document_is_retired(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)

    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(BASE))

    assert result.triggers.schedules_removed == ["nightly"]
    assert await schedule_named(sessions, "daily-load", "nightly") is None


async def test_a_dry_run_names_a_schedule_the_document_stopped_declaring_and_keeps_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)

    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(BASE), dry_run=True)

    assert result.triggers.schedules_removed == ["nightly"]
    assert await schedule_named(sessions, "daily-load", "nightly") is not None


async def test_a_schedule_created_by_hand_survives_an_apply_that_does_not_mention_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        by_hand = await create_schedule(
            session, pipeline, ScheduleRequest(code="operators-own", interval=timedelta(minutes=15))
        )
        assert by_hand.managed is False

    await apply(sessions, services, WITH_TRIGGERS)

    survivor = await schedule_named(sessions, "daily-load", "operators-own")
    assert survivor is not None
    assert survivor.managed is False
    assert survivor.kind is ScheduleKind.INTERVAL
    assert await schedule_named(sessions, "daily-load", "nightly") is not None


async def test_changing_a_schedules_clock_in_the_document_redeclares_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"\n      timezone: Europe/Oslo', "interval: 30m")

    before = utcnow()
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(changed))

    assert result.triggers.schedules_updated == ["nightly"]
    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.kind is ScheduleKind.INTERVAL
    assert after.interval_seconds == 1800
    assert after.cron is None
    assert after.timezone == "UTC"
    assert after.next_fire_at is not None
    assert before + timedelta(minutes=30) <= after.next_fire_at <= utcnow() + timedelta(minutes=30)


def test_a_long_key_is_held_as_a_short_one_and_still_limits() -> None:
    bucket = TokenBucket()
    key = "user:" + "x" * 100_000
    assert bucket.allow(key, per_minute=1, now=0.0) is True
    assert bucket.allow(key, per_minute=1, now=0.0) is False
    assert bucket.allow(key + "y", per_minute=1, now=0.0) is True, "a different long key is its own bucket"
    assert max(len(held) for held in bucket.buckets) < 128
    bucket.forget(key)
    assert bucket.allow(key, per_minute=1, now=0.0) is True


def test_a_bucket_evicts_rather_than_growing_for_every_key_a_stranger_invents() -> None:
    """Every user of this limiter keys on something the caller chooses."""
    bucket = TokenBucket(max_keys=8)
    for index in range(100):
        assert bucket.allow(f"key-{index}", per_minute=60) is True
    assert len(bucket.buckets) == 8
    assert "key-99" in bucket.buckets
    assert "key-0" not in bucket.buckets


async def test_an_interval_of_less_than_whole_seconds_is_refused_at_declaration_time(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The row holds whole seconds, so a fraction would be silently shortened or lost."""
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        with pytest.raises(ScheduleError, match="whole number of seconds") as fractional:
            await create_schedule(session, pipeline, ScheduleRequest(code="too-fine", interval=timedelta(seconds=1.5)))
        assert "1.5s" in str(fractional.value)
        with pytest.raises(ScheduleError, match="at least one") as sub_second:
            await create_schedule(
                session, pipeline, ScheduleRequest(code="too-short", interval=timedelta(milliseconds=500))
            )
        assert "0.5s" in str(sub_second.value)


async def test_a_whole_second_interval_is_stored_as_the_seconds_it_names(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        schedule = await create_schedule(
            session, pipeline, ScheduleRequest(code="every-ninety", interval=timedelta(seconds=90))
        )
    assert schedule.kind is ScheduleKind.INTERVAL
    assert schedule.interval_seconds == 90
