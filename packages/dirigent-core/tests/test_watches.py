"""Watches: one run always waiting on a sensor, the next armed the moment it succeeds."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus, TriggerKind
from dirigent_client.schemas import ApplyResult, PlanAction
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine.definition import (
    ConcurrencyPolicy,
    PipelineDefinition,
    StepDefinition,
    TimeoutAction,
    TriggerSpecs,
    WatchSpec,
)
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import RunCreationError, cancel_run, retry_step
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import CANCELLED_BY
from dirigent_core.models import PipelineVersion, Run, StepAttempt, Watch
from dirigent_core.pipelines import apply_document, delete_pipeline, set_active
from dirigent_core.triggers import watches
from dirigent_core.triggers.watches import backoff_for, set_paused
from engineblocks import StreamSensor

#: A moment for the ticks that read no clock of the engine's.
T0 = datetime.now(UTC)


def tailing(
    *,
    downstream: bool = True,
    concurrency: ConcurrencyPolicy = ConcurrencyPolicy.ALLOW,
    paused: bool = False,
    **stream: Any,
) -> PipelineDefinition:
    """A pipeline whose root sensor tails a stream, with a step after it, watched."""
    graph = {"tail": StepDefinition(block="test.stream", config=stream, poll=timedelta(seconds=1))}
    if downstream:
        graph["load"] = StepDefinition(block="test.echo", depends_on=["tail"], config={"value": "loaded"})
    return PipelineDefinition(
        code="tailing",
        concurrency=concurrency,
        steps=graph,
        triggers=TriggerSpecs(watches=[WatchSpec(code="follow", step="tail", paused=paused)]),
    )


async def apply(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    definition: PipelineDefinition | str,
) -> ApplyResult:
    """Apply a document in its own transaction."""
    document = load_text(definition) if isinstance(definition, str) else definition
    async with session_scope(sessions) as session:
        return await apply_document(session, services, document)


async def the_watch(sessions: async_sessionmaker[AsyncSession], code: str = "follow") -> Watch:
    """Read the one watch back."""
    async with sessions() as session:
        found = await session.execute(sa.select(Watch).where(Watch.code == code))
        return found.scalar_one()


async def watch_runs(sessions: async_sessionmaker[AsyncSession]) -> list[Run]:
    """Every run a watch armed, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(Run).where(Run.triggered_by_kind == TriggerKind.WATCH).order_by(Run.created_at, Run.id)
        )
        return list(rows.scalars())


async def waiting(sessions: async_sessionmaker[AsyncSession]) -> list[Run]:
    """The runs whose watched step has not yet succeeded: the ones still waiting on the sensor."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(Run)
            .join(StepAttempt, StepAttempt.run_id == Run.id)
            .where(
                Run.triggered_by_kind == TriggerKind.WATCH,
                Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)),
                StepAttempt.step_name == "tail",
                StepAttempt.status.in_(
                    (AttemptStatus.PENDING, AttemptStatus.QUEUED, AttemptStatus.RUNNING, AttemptStatus.WAITING)
                ),
            )
        )
        return list(rows.scalars().unique())


async def batches(sessions: async_sessionmaker[AsyncSession]) -> list[list[int]]:
    """The offsets each succeeded watched step took, in the order the runs were armed."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt.output)
            .join(Run, Run.id == StepAttempt.run_id)
            .where(StepAttempt.step_name == "tail", StepAttempt.status == AttemptStatus.SUCCEEDED)
            .order_by(Run.created_at, Run.id)
        )
        return [list(output["offsets"]) for output in rows.scalars() if output is not None]


async def pump(
    engine: Engine,
    until: Callable[[], Any],
    *,
    start_at: datetime | None = None,
    step: timedelta = timedelta(seconds=2),
    limit: int = 200,
) -> datetime:
    """Claim and run units on a virtual clock until ``until`` says the state it waits for holds."""
    moment = start_at or datetime.now(UTC)
    for _ in range(limit):
        if await until():
            return moment
        unit = await engine.claim(now=moment)
        if unit is not None:
            await engine.run_unit(unit, now=moment)
        moment += step
    raise AssertionError("the state the test waited for never arrived")


# -- arming ------------------------------------------------------------------------


async def test_applying_a_watch_arms_one_run_waiting_on_its_sensor(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    result = await apply(sessions, services, tailing())

    assert result.triggers.watches_created == ["follow"]
    watch = await the_watch(sessions)
    runs = await watch_runs(sessions)
    assert len(runs) == 1
    assert runs[0].id == watch.waiting_run_id
    assert (runs[0].triggered_by_kind, runs[0].triggered_by_id) == (TriggerKind.WATCH, watch.id)
    assert runs[0].triggered_by_label == "watch follow"


async def test_a_watch_declared_paused_arms_nothing_until_it_is_resumed(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(paused=True))

    assert await watch_runs(sessions) == []
    watch = await the_watch(sessions)
    async with session_scope(sessions) as session:
        await set_paused(session, services, await session.get(Watch, watch.id) or watch, paused=False)
    assert len(await waiting(sessions)) == 1


async def test_reapplying_an_unchanged_document_arms_no_second_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())
    result = await apply(sessions, services, tailing())

    assert result.plan.action is PlanAction.UNCHANGED
    assert len(await watch_runs(sessions)) == 1


# -- carrying on -------------------------------------------------------------------


async def test_each_success_arms_the_next_run_from_where_the_batch_ended(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Three batches are one stream of offsets, with no consumer group anywhere."""
    await apply(sessions, services, tailing(batch=2))

    async def three_taken() -> bool:
        return len(await batches(sessions)) >= 3

    await pump(engine, three_taken)

    assert await batches(sessions) == [[0, 1], [2, 3], [4, 5]]
    runs = await watch_runs(sessions)
    assert len(runs) == 4, "the third success armed a fourth"
    watch = await the_watch(sessions)
    assert watch.cursor == {"offset": 6}
    assert watch.waiting_run_id == runs[-1].id
    async with sessions() as session:
        seeded = await session.execute(
            sa.select(StepAttempt.poke_cursor).where(StepAttempt.run_id == runs[-1].id, StepAttempt.step_name == "tail")
        )
        assert seeded.scalar_one() == {"offset": 6}


async def test_runs_overlap_one_carrying_on_downstream_while_the_next_waits(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())

    async def first_taken() -> bool:
        return len(await batches(sessions)) >= 1

    moment = await pump(engine, first_taken)

    first, second = await watch_runs(sessions)
    assert first.status is RunStatus.RUNNING, "its load step has not run yet"
    assert first.finished_at is None
    assert second.status in (RunStatus.QUEUED, RunStatus.RUNNING)
    assert [run.id for run in await waiting(sessions)] == [second.id]

    async def first_finished() -> bool:
        async with sessions() as session:
            run = await session.get(Run, first.id)
            return run is not None and run.status is RunStatus.SUCCEEDED

    await pump(engine, first_finished, start_at=moment)
    assert [run.id for run in await waiting(sessions)] == [second.id], "the next run is still waiting"


async def test_the_queue_policy_holds_the_next_run_until_the_one_ahead_settles(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The run is created through the ordinary path, so the concurrency policy has its say."""
    await apply(sessions, services, tailing(concurrency=ConcurrencyPolicy.QUEUE))

    async def first_taken() -> bool:
        return len(await batches(sessions)) >= 1

    await pump(engine, first_taken)

    first, second = await watch_runs(sessions)
    async with sessions() as session:
        held = await session.execute(sa.select(StepAttempt.status).where(StepAttempt.run_id == second.id))
        assert set(held.scalars()) == {AttemptStatus.PENDING}
    assert (await the_watch(sessions)).waiting_run_id == second.id
    assert first.status is RunStatus.RUNNING


# -- pausing and resuming ----------------------------------------------------------


async def test_pausing_cancels_the_waiting_run_and_keeps_the_cursor(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(downstream=False))

    async def one_taken() -> bool:
        return len(await batches(sessions)) >= 1

    await pump(engine, one_taken)
    armed = (await the_watch(sessions)).waiting_run_id

    async with session_scope(sessions) as session:
        row = await session.get(Watch, (await the_watch(sessions)).id)
        assert row is not None
        await set_paused(session, services, row, paused=True)

    watch = await the_watch(sessions)
    assert (watch.paused, watch.waiting_run_id, watch.cursor) == (True, None, {"offset": 2})
    async with sessions() as session:
        cancelled = await session.get(Run, armed)
        assert cancelled is not None
        assert cancelled.status is RunStatus.CANCELLED
        assert cancelled.error == "its watch was paused"
    assert watch.failures == 0, "a pause is not a failure"
    assert await watches.tick(sessions, services, now=T0 + timedelta(hours=1)) == []


async def test_resuming_arms_a_run_from_the_stored_cursor(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(downstream=False))

    async def two_taken() -> bool:
        return len(await batches(sessions)) >= 2

    await pump(engine, two_taken)
    watch_id = (await the_watch(sessions)).id
    async with session_scope(sessions) as session:
        row = await session.get(Watch, watch_id)
        assert row is not None
        await set_paused(session, services, row, paused=True)
    async with session_scope(sessions) as session:
        row = await session.get(Watch, watch_id)
        assert row is not None
        await set_paused(session, services, row, paused=False)

    watch = await the_watch(sessions)
    assert watch.paused is False
    async with sessions() as session:
        seeded = await session.execute(
            sa.select(StepAttempt.poke_cursor).where(
                StepAttempt.run_id == watch.waiting_run_id, StepAttempt.step_name == "tail"
            )
        )
        assert seeded.scalar_one() == {"offset": 4}


# -- failure and backoff -----------------------------------------------------------


async def test_a_failed_wait_backs_off_records_why_and_arms_again_from_the_last_good_cursor(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices, settings: Settings
) -> None:
    await apply(sessions, services, tailing(downstream=False, key="broken"))

    async def one_taken() -> bool:
        return len(await batches(sessions)) >= 1

    moment = await pump(engine, one_taken)
    StreamSensor.failing.add("broken")
    failing_run = (await the_watch(sessions)).waiting_run_id

    async def backing_off() -> bool:
        return (await the_watch(sessions)).waiting_run_id is None

    moment = await pump(engine, backing_off, start_at=moment)

    watch = await the_watch(sessions)
    assert watch.failures == 1
    assert watch.last_error is not None
    assert "the stream is down" in watch.last_error
    assert watch.last_error_at is not None
    rearm_at = watch.rearm_at
    assert rearm_at is not None
    assert rearm_at == watch.last_error_at + settings.watch_backoff
    assert watch.cursor == {"offset": 2}, "the failure moved nothing"
    async with sessions() as session:
        failed = await session.get(Run, failing_run)
        assert failed is not None
        assert failed.status is RunStatus.FAILED

    assert await watches.tick(sessions, services, now=rearm_at - timedelta(seconds=1)) == []
    StreamSensor.failing.discard("broken")
    armed = await watches.tick(sessions, services, now=rearm_at)
    assert [entry.watch for entry in armed] == ["follow"]

    async def two_taken() -> bool:
        return len(await batches(sessions)) >= 2

    await pump(engine, two_taken, start_at=rearm_at)
    assert await batches(sessions) == [[0, 1], [2, 3]]
    healed = await the_watch(sessions)
    assert (healed.failures, healed.last_error) == (0, None), "a success clears the health it recorded"


async def test_a_cancelled_wait_backs_off_like_a_failure(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())
    armed = (await the_watch(sessions)).waiting_run_id

    async with session_scope(sessions) as session:
        run = await session.get(Run, armed)
        assert run is not None
        await cancel_run(session, services, run, CANCELLED_BY, principal="somebody", now=T0)

    watch = await the_watch(sessions)
    assert watch.waiting_run_id is None
    assert watch.failures == 1
    assert watch.last_error is not None
    assert "cancelled by somebody" in watch.last_error


def test_the_backoff_doubles_up_to_its_cap(settings: Settings) -> None:
    capped = settings.model_copy(
        update={"watch_backoff": timedelta(seconds=5), "watch_backoff_max": timedelta(seconds=30)}
    )
    assert [backoff_for(count, capped) for count in range(6)] == [
        timedelta(0),
        timedelta(seconds=5),
        timedelta(seconds=10),
        timedelta(seconds=20),
        timedelta(seconds=30),
        timedelta(seconds=30),
    ]


async def test_a_sensor_that_ran_out_its_deadline_arms_again_without_backing_off(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Nothing arriving before the deadline is an empty wait, not a broken one, and ends a failure streak."""
    definition = tailing(downstream=False, parks=1_000)
    quiet = definition.model_copy(
        update={
            "steps": {
                "tail": definition.steps["tail"].model_copy(
                    update={"deadline": timedelta(seconds=3), "on_timeout": TimeoutAction.SKIP}
                )
            }
        }
    )
    await apply(sessions, services, quiet)
    first = (await the_watch(sessions)).waiting_run_id
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Watch).values(failures=2))

    async def moved_on() -> bool:
        return (await the_watch(sessions)).waiting_run_id not in (None, first)

    await pump(engine, moved_on)
    watch = await the_watch(sessions)
    assert (watch.failures, watch.last_error) == (0, None)


# -- never two -----------------------------------------------------------------------


async def test_a_tick_while_a_run_waits_arms_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())

    assert await watches.tick(sessions, services, now=T0) == []
    assert await watches.tick(sessions, services, now=T0 + timedelta(minutes=1)) == []
    assert len(await watch_runs(sessions)) == 1


async def test_ticks_racing_each_other_after_a_restart_arm_exactly_one_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A restart finds a watch with no run waiting; every armer that races for it but one loses."""
    await apply(sessions, services, tailing(paused=True))
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Watch).values(paused=False))

    armed = await asyncio.gather(*(watches.tick(sessions, services, now=T0) for _ in range(4)))

    assert sum(len(entries) for entries in armed) == 1
    assert len(await waiting(sessions)) == 1
    assert len(await watch_runs(sessions)) == 1


async def test_a_waiting_run_that_settled_unnoticed_is_replaced_once(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Recovery reads a settled or vanished waiting run as the end of its wait, and arms one more."""
    await apply(sessions, services, tailing())
    lost = (await the_watch(sessions)).waiting_run_id
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Run).where(Run.id == lost).values(status=RunStatus.CANCELLED, error="lost"))

    later = T0 + timedelta(hours=1)
    assert await watches.tick(sessions, services, now=later) == [], "a lost wait backs off first"
    watch = await the_watch(sessions)
    assert watch.rearm_at is not None
    first = await watches.tick(sessions, services, now=watch.rearm_at)
    again = await watches.tick(sessions, services, now=watch.rearm_at + timedelta(minutes=1))

    assert len(first) == 1
    assert again == []
    assert len(await waiting(sessions)) == 1


async def test_arming_twice_in_one_transaction_arms_once(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(paused=True))
    async with session_scope(sessions) as session:
        watch = (await session.execute(sa.select(Watch))).scalar_one()
        watch.paused = False
        await session.flush()
        assert await watches.arm(session, services, watch, now=T0) is not None
        assert await watches.arm(session, services, watch, now=T0) is None
    assert len(await watch_runs(sessions)) == 1


# -- the document ------------------------------------------------------------------


async def test_retiring_a_watch_cancels_the_run_it_had_waiting(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())
    armed = (await the_watch(sessions)).waiting_run_id
    bare = tailing().model_copy(update={"triggers": TriggerSpecs()})

    result = await apply(sessions, services, bare)

    assert result.triggers.watches_removed == ["follow"]
    async with sessions() as session:
        run = await session.get(Run, armed)
        assert run is not None
        assert run.status is RunStatus.CANCELLED


@pytest.mark.parametrize(
    ("step", "graph", "code"),
    [
        ("tail", {"tail": StepDefinition(block="test.echo")}, "document.watch_not_a_sensor"),
        (
            "second",
            {
                "tail": StepDefinition(block="test.stream"),
                "second": StepDefinition(block="test.stream", depends_on=["tail"]),
            },
            "document.watch_not_a_root",
        ),
        ("nowhere", {"tail": StepDefinition(block="test.stream")}, "document.watch_unknown_step"),
        ("tail", {"tail": StepDefinition(block="test.stream", for_each=["a", "b"])}, "document.watch_fans_out"),
    ],
)
async def test_a_watch_on_anything_but_one_root_sensor_is_refused_at_apply(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    step: str,
    graph: dict[str, StepDefinition],
    code: str,
) -> None:
    definition = PipelineDefinition(
        code="refused", steps=graph, triggers=TriggerSpecs(watches=[WatchSpec(code="w", step=step)])
    )

    result = await apply(sessions, services, definition)

    assert result.plan.action is PlanAction.INVALID
    assert [(issue.code, issue.location) for issue in result.plan.issues] == [(code, "triggers.watches[0].step")]
    assert await watch_runs(sessions) == []


async def test_a_watch_whose_pins_the_schema_refuses_is_refused_at_apply(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    definition = tailing().model_copy(
        update={
            "params": {"type": "object", "properties": {"topic": {"type": "string"}}, "additionalProperties": False},
            "triggers": TriggerSpecs(watches=[WatchSpec(code="follow", step="tail", params={"nope": 1})]),
        }
    )

    result = await apply(sessions, services, definition)

    assert [issue.code for issue in result.plan.issues] == ["document.watch_params_refused"]


async def test_a_triggers_document_declares_a_watch_over_another_documents_pipeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing().model_copy(update={"triggers": TriggerSpecs()}))

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: ops-watches\npipeline: tailing\n"
        "triggers:\n  watches:\n    - { code: ops-follow, step: tail }\n",
    )

    assert result.triggers.watches_created == ["ops-follow"]
    watch = await the_watch(sessions, "ops-follow")
    assert watch.trigger_document_id is not None
    assert len(await waiting(sessions)) == 1


async def test_a_triggers_document_watching_an_operator_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing().model_copy(update={"triggers": TriggerSpecs()}))

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: ops-watches\npipeline: tailing\n"
        "triggers:\n  watches:\n    - { code: ops-follow, step: load }\n",
    )

    assert [issue.code for issue in result.plan.issues] == ["document.watch_not_a_root"]


# -- the review round ----------------------------------------------------------------

#: A triggers document declaring one watch on the tailing pipeline's sensor.
OPS_WATCH = (
    "format: dirigent/v1\nkind: triggers\ncode: ops-watches\npipeline: tailing\n"
    "triggers:\n  watches:\n    - { code: ops-follow, step: tail }\n"
)


def unwatched(**changes: Any) -> PipelineDefinition:
    """The tailing pipeline with no watch of its own, and whatever else a test changes."""
    return tailing().model_copy(update={"triggers": TriggerSpecs(), **changes})


async def status_of(sessions: async_sessionmaker[AsyncSession], run_id: Any) -> RunStatus:
    """Read one run's status."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return run.status


async def test_a_watch_on_a_replace_pipeline_is_refused_at_apply(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    result = await apply(sessions, services, tailing(concurrency=ConcurrencyPolicy.REPLACE))

    assert [issue.code for issue in result.plan.issues] == ["document.watch_replace_policy"]
    assert await watch_runs(sessions) == []


async def test_a_version_that_switches_a_watched_pipeline_to_replace_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())

    result = await apply(sessions, services, tailing(concurrency=ConcurrencyPolicy.REPLACE))

    assert result.plan.action is PlanAction.INVALID
    assert [issue.code for issue in result.plan.issues] == ["document.watch_replace_policy"]


async def test_a_version_that_breaks_a_triggers_documents_watch_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, unwatched())
    await apply(sessions, services, OPS_WATCH)

    renamed = unwatched(
        steps={
            "tap": StepDefinition(block="test.stream", poll=timedelta(seconds=1)),
            "load": StepDefinition(block="test.echo", depends_on=["tap"]),
        }
    )
    switched = unwatched(concurrency=ConcurrencyPolicy.REPLACE)

    for broken in (renamed, switched):
        result = await apply(sessions, services, broken)
        assert result.plan.action is PlanAction.INVALID
        assert [issue.code for issue in result.plan.issues] == ["document.watch_would_break"]


async def test_deleting_a_triggers_document_withdraws_the_run_waiting_now_not_a_stale_one(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A session that read the watch before its wait moved on still cancels only the new wait."""
    from dirigent_core.trigger_documents import delete_trigger_document, find_trigger_document

    await apply(sessions, services, unwatched())
    await apply(sessions, services, OPS_WATCH)
    first = (await the_watch(sessions, "ops-follow")).waiting_run_id

    stale = sessions()
    try:
        held = (await stale.execute(sa.select(Watch))).scalar_one()
        assert held.waiting_run_id == first
        await stale.commit()

        async def first_taken() -> bool:
            return len(await batches(sessions)) >= 1

        await pump(engine, first_taken)
        second = (await the_watch(sessions, "ops-follow")).waiting_run_id
        assert second not in (None, first)

        row = await find_trigger_document(stale, "ops-watches")
        assert row is not None
        await delete_trigger_document(stale, services, row)
        await stale.commit()
    finally:
        await stale.close()

    assert await status_of(sessions, first) is RunStatus.RUNNING, "the run whose batch arrived carries on"
    assert await status_of(sessions, second) is RunStatus.CANCELLED


async def test_a_new_version_moves_the_waiting_run_onto_it_from_the_same_cursor(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(downstream=False))

    async def one_taken() -> bool:
        return len(await batches(sessions)) >= 1

    await pump(engine, one_taken)
    before = await the_watch(sessions)
    old_wait = before.waiting_run_id

    changed = tailing(downstream=False, batch=3)
    result = await apply(sessions, services, changed)
    assert result.version == 2

    after = await the_watch(sessions)
    assert after.cursor == before.cursor == {"offset": 2}
    assert await status_of(sessions, old_wait) is RunStatus.CANCELLED
    async with sessions() as session:
        run = await session.get(Run, after.waiting_run_id)
        assert run is not None
        version = await session.get(PipelineVersion, run.pipeline_version_id)
        assert version is not None
        assert version.version == 2
        seeded = await session.execute(
            sa.select(StepAttempt.poke_cursor).where(StepAttempt.run_id == run.id, StepAttempt.step_name == "tail")
        )
        assert seeded.scalar_one() == {"offset": 2}


async def test_a_manual_retry_of_the_waiting_runs_watched_step_starts_from_its_cursor(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A second root keeps the run in flight, so the failed watched step is still the wait."""
    definition = tailing(downstream=False, key="flaky").model_copy(
        update={
            "steps": {
                "tail": StepDefinition(block="test.stream", config={"key": "flaky"}, poll=timedelta(seconds=1)),
                "wait": StepDefinition(block="test.stream", config={"key": "wait", "parks": 1_000}),
            }
        }
    )
    await apply(sessions, services, definition)
    run_id = (await the_watch(sessions)).waiting_run_id

    async def watched(status: AttemptStatus) -> bool:
        async with sessions() as session:
            found = await session.execute(
                sa.select(StepAttempt.status).where(StepAttempt.run_id == run_id, StepAttempt.step_name == "tail")
            )
            return status in set(found.scalars())

    async def parked() -> bool:
        return await watched(AttemptStatus.WAITING)

    moment = await pump(engine, parked)
    StreamSensor.failing.add("flaky")

    async def failed() -> bool:
        return await watched(AttemptStatus.FAILED)

    await pump(engine, failed, start_at=moment)
    assert (await the_watch(sessions)).waiting_run_id == run_id

    async with session_scope(sessions) as session:
        run = await session.get(Run, run_id)
        assert run is not None
        retried = await retry_step(session, services, run, "tail", idempotency_key="again")
        assert retried.poke_cursor == {"offset": 0, "parked": 1}


async def test_a_manual_retry_of_a_watched_step_the_watch_moved_past_is_refused(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(downstream=False, key="gone"))
    StreamSensor.failing.add("gone")
    run_id = (await the_watch(sessions)).waiting_run_id

    async def backing_off() -> bool:
        return (await the_watch(sessions)).waiting_run_id is None

    await pump(engine, backing_off)

    async with session_scope(sessions) as session:
        run = await session.get(Run, run_id)
        assert run is not None
        with pytest.raises(RunCreationError) as refused:
            await retry_step(session, services, run, "tail", idempotency_key="again")
    assert refused.value.code == "run.retry_watch_moved_on"


async def test_deactivating_cancels_the_waiting_run_and_activating_arms_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())
    first = (await the_watch(sessions)).waiting_run_id

    async with session_scope(sessions) as session:
        await set_active(session, services, "tailing", active=False)
    assert await status_of(sessions, first) is RunStatus.CANCELLED
    watch = await the_watch(sessions)
    assert (watch.waiting_run_id, watch.failures) == (None, 0)

    async with session_scope(sessions) as session:
        await set_active(session, services, "tailing", active=True)
    assert (await the_watch(sessions)).waiting_run_id not in (None, first)


async def test_a_live_watch_does_not_hold_up_deleting_its_pipeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing())

    async with session_scope(sessions) as session:
        await delete_pipeline(session, services, "tailing")

    async with sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Watch))).scalar_one() == 0


async def test_a_watch_run_settles_under_the_pipeline_lock_before_the_run_lock(
    engine: Engine,
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline then run, the order a pause and a cancel take them in, so the two cannot cycle."""
    from dirigent_core.engine import executor

    await apply(sessions, services, tailing(downstream=False, parks=0))
    unit = await engine.claim()
    assert unit is not None

    taken: list[str] = []
    real_run, real_pipeline = executor.lock_run, executor.lock_pipeline

    async def run_lock(session: AsyncSession, run_id: Any) -> None:
        taken.append("run")
        await real_run(session, run_id)

    async def pipeline_lock(session: AsyncSession, pipeline_id: Any) -> None:
        taken.append("pipeline")
        await real_pipeline(session, pipeline_id)

    monkeypatch.setattr(executor, "lock_run", run_lock)
    monkeypatch.setattr(executor, "lock_pipeline", pipeline_lock)
    await engine.run_unit(unit)

    assert taken[:2] == ["pipeline", "run"]


async def test_resuming_clears_the_failure_count(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, tailing(paused=True))
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Watch).values(failures=4))

    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Watch))).scalar_one()
        await set_paused(session, services, row, paused=False)

    assert (await the_watch(sessions)).failures == 0
