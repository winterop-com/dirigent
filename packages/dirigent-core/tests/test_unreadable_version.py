"""A run whose pinned version this code can no longer read fails, and holds nothing else up."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import cancel_run, create_run, save_pipeline
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import PipelineVersion, Run, utcnow
from engineblocks import RemoteOperator
from test_engine import attempts_of, drain, reload, start, statuses, steps

UNREADABLE = "run.version_unreadable"


async def make_unreadable(sessions: Any, version_id: UUID) -> None:
    """Store a field the model forbids, as an upgrade that dropped one leaves a version."""
    async with session_scope(sessions) as session:
        version = await session.get(PipelineVersion, version_id)
        assert version is not None
        version.document = {**version.document, "retired_field": True}


def echo(code: str, **extra: Any) -> PipelineDefinition:
    """A one-step pipeline."""
    return PipelineDefinition(
        code=code, steps=steps(only=StepDefinition(block="test.echo", config={"value": "x"})), **extra
    )


async def test_a_claim_fails_an_unreadable_run_and_hands_out_the_next_unit(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    old = await start(sessions, services, echo("old"))
    await make_unreadable(sessions, old.pipeline_version_id)
    healthy = await start(sessions, services, echo("healthy"))

    unit = await engine.claim()
    assert unit is not None, "the unreadable run held up the claim"
    assert unit.run_id == healthy.id
    stored = await reload(sessions, old.id)
    assert (stored.status, stored.error_code) == (RunStatus.FAILED, UNREADABLE)
    assert "retired_field" in (stored.error or "")
    [attempt] = await attempts_of(sessions, old.id)
    assert (attempt.status, attempt.error_code, attempt.error_class) == (AttemptStatus.FAILED, UNREADABLE, "rejected")


async def test_a_deadline_sweep_fails_an_unreadable_run_instead_of_raising(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="waits",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
            )
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    assert (await statuses(sessions, run.id)) == {"job": [AttemptStatus.WAITING]}
    await make_unreadable(sessions, run.pipeline_version_id)

    async with session_scope(sessions) as session:
        settled = await engine.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1))
    assert settled == [unit.attempt_id]
    assert (await reload(sessions, run.id)).error_code == UNREADABLE
    [attempt] = await attempts_of(sessions, run.id)
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.remote_cancel_since is not None, "the remote job is left for the sweep to cancel"
    assert RemoteOperator.cancellations == []


async def test_an_outcome_for_an_unreadable_run_fails_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, echo("upgraded-mid-call"))
    unit = await engine.claim()
    assert unit is not None
    await make_unreadable(sessions, run.pipeline_version_id)
    await engine.run_unit(unit)
    assert (await reload(sessions, run.id)).error_code == UNREADABLE


async def test_an_unreadable_run_can_be_cancelled(engine: Engine, sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, echo("cancel-me"))
    await make_unreadable(sessions, run.pipeline_version_id)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)
    assert (await reload(sessions, run.id)).status is RunStatus.CANCELLED


async def test_an_unreadable_held_run_is_failed_and_the_next_one_released(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    first = await start(sessions, services, echo("queued", concurrency=ConcurrencyPolicy.QUEUE))
    async with session_scope(sessions) as session:
        newer = await save_pipeline(session, echo("queued", concurrency=ConcurrencyPolicy.QUEUE, description="v2"))
        unreadable = await create_run(session, services, newer)
        version = await session.get(PipelineVersion, first.pipeline_version_id)
        assert version is not None
        behind = await create_run(session, services, version)
    assert unreadable is not None
    assert behind is not None
    await make_unreadable(sessions, newer.id)

    await drain(engine)
    assert (await reload(sessions, first.id)).status is RunStatus.SUCCEEDED
    assert (await reload(sessions, unreadable.id)).error_code == UNREADABLE
    assert (await reload(sessions, behind.id)).status is RunStatus.SUCCEEDED
