"""Pausing a run: nothing more of it is claimed, its deadlines stand still, and a resume goes on."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import RunStateError, cancel_run, create_run, pause_run, resume_run, retry_step
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import CANCELLED
from dirigent_core.models import PipelineVersion, Run
from dirigent_plugin import ErrorClass
from test_engine import attempts_of, drain, reload, start, statuses, steps


def chain() -> PipelineDefinition:
    """Two steps, one after the other."""
    return PipelineDefinition(
        code="pausable",
        steps=steps(
            first=StepDefinition(block="test.echo", config={"value": "one"}),
            second=StepDefinition(block="test.echo", depends_on=["first"], config={"value": "two"}),
        ),
    )


async def pause(sessions: Any, run_id: Any, *, now: datetime | None = None) -> Run:
    """Pause a run in its own transaction."""
    async with session_scope(sessions) as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return await pause_run(session, run, now=now)


async def resume(sessions: Any, services: EngineServices, run_id: Any, *, now: datetime | None = None) -> Run:
    """Resume a run in its own transaction."""
    async with session_scope(sessions) as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return await resume_run(session, services, run, now=now)


async def test_a_paused_run_is_never_claimed_and_a_resumed_one_finishes(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, chain())
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    assert (await statuses(sessions, run.id)) == {"first": [AttemptStatus.SUCCEEDED], "second": [AttemptStatus.QUEUED]}

    paused = await pause(sessions, run.id)
    assert (paused.status, paused.paused_at is not None) == (RunStatus.PAUSED, True)
    assert await engine.claim() is None, "nothing of a paused run is claimed"

    resumed = await resume(sessions, services, run.id)
    assert (resumed.status, resumed.paused_at) == (RunStatus.RUNNING, None)
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_a_run_paused_before_it_started_resumes_as_queued(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, chain())
    await pause(sessions, run.id)
    assert (await resume(sessions, services, run.id)).status is RunStatus.QUEUED


async def test_a_resume_moves_the_open_deadlines_on_by_the_pause(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="waits",
        steps=steps(wait=StepDefinition(block="test.tick", config={"ready_after": 1000}, deadline=timedelta(hours=1))),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    [before] = await attempts_of(sessions, run.id)
    assert before.status is AttemptStatus.WAITING
    assert before.deadline_at is not None
    moment = datetime.now(UTC)
    await pause(sessions, run.id, now=moment)

    async with session_scope(sessions) as session:
        settled = await engine.settle_overdue_deadlines(session, now=moment + timedelta(hours=2))
    assert settled == [], "a paused run's deadline does not fire"
    assert (await reload(sessions, run.id)).status is RunStatus.PAUSED

    await resume(sessions, services, run.id, now=moment + timedelta(minutes=30))
    [after] = await attempts_of(sessions, run.id)
    assert after.deadline_at == before.deadline_at + timedelta(minutes=30)


async def test_a_paused_run_can_be_cancelled(engine: Engine, sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, chain())
    await pause(sessions, run.id)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored, CANCELLED)
    assert (await reload(sessions, run.id)).status is RunStatus.CANCELLED


@pytest.mark.parametrize("twice", ["pause", "resume"])
async def test_a_run_in_the_wrong_state_is_refused(
    engine: Engine, sessions: Any, services: EngineServices, twice: str
) -> None:
    run = await start(sessions, services, chain())
    if twice == "pause":
        await pause(sessions, run.id)
        with pytest.raises(RunStateError) as refused:
            await pause(sessions, run.id)
        assert refused.value.code == "run.not_pausable"
    else:
        with pytest.raises(RunStateError) as refused:
            await resume(sessions, services, run.id)
        assert refused.value.code == "run.not_paused"


async def queued_behind(sessions: Any, services: EngineServices) -> tuple[Run, Run]:
    """Start one run of a ``queue`` pipeline and a second held behind it."""
    definition = PipelineDefinition(
        code="queued",
        concurrency=ConcurrencyPolicy.QUEUE,
        steps=steps(only=StepDefinition(block="test.echo", config={"value": "x"})),
    )
    first = await start(sessions, services, definition)
    async with session_scope(sessions) as session:
        version = await session.get(PipelineVersion, first.pipeline_version_id)
        assert version is not None
        held = await create_run(session, services, version)
    assert held is not None
    return first, held


async def test_a_held_run_paused_and_resumed_after_the_slot_came_free_is_released(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    first, held = await queued_behind(sessions, services)
    await pause(sessions, held.id)

    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    assert (await reload(sessions, first.id)).status is RunStatus.SUCCEEDED
    assert await engine.claim() is None, "a paused held run keeps its place in the queue"

    await resume(sessions, services, held.id)
    assert (await statuses(sessions, held.id)) == {"only": [AttemptStatus.QUEUED]}, "the resume did not release it"
    await drain(engine)
    assert (await reload(sessions, held.id)).status is RunStatus.SUCCEEDED


async def test_a_held_run_resumed_while_the_slot_is_taken_stays_held(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    first, held = await queued_behind(sessions, services)
    await pause(sessions, held.id)
    await resume(sessions, services, held.id)
    assert (await statuses(sessions, held.id)) == {"only": [AttemptStatus.PENDING]}

    await drain(engine)
    assert (await reload(sessions, first.id)).status is RunStatus.SUCCEEDED
    assert (await reload(sessions, held.id)).status is RunStatus.SUCCEEDED


async def test_a_manual_retry_leaves_a_paused_run_paused(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="two-branches",
        steps=steps(
            broken=StepDefinition(block="test.fail", config={"error_class": ErrorClass.REJECTED.value}),
            wait=StepDefinition(block="test.tick", config={"ready_after": 1000}),
        ),
    )
    run = await start(sessions, services, definition)
    for _ in range(2):
        unit = await engine.claim()
        assert unit is not None
        await engine.run_unit(unit)
    assert (await statuses(sessions, run.id)) == {"broken": [AttemptStatus.FAILED], "wait": [AttemptStatus.WAITING]}
    await pause(sessions, run.id)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await retry_step(session, services, stored, "broken", idempotency_key="again")
    retried = await reload(sessions, run.id)
    assert (retried.status, retried.paused_at is not None) == (RunStatus.PAUSED, True)
    assert await engine.claim(now=datetime.now(UTC) + timedelta(hours=1)) is None, "a paused run was claimed"
