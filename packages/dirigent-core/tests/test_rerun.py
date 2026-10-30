"""Running a settled run again: same parameters, same input at a source, attributed to the original."""

from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptKind, RunStatus, TriggerKind
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import RunCreationError, create_run, pause_run, rerun, save_pipeline
from dirigent_core.messages import RERUN_IN_FLIGHT, RUN_PIPELINE_INACTIVE
from dirigent_core.models import Pipeline, Run, StepAttempt
from dirigent_core.sources.entries import hand_entry
from test_engine import drain, reload, steps
from test_sources import GREET, RECEIVED_AT, attempts, document, start

PARAMS = {"type": "object", "properties": {"greeting": {"type": "string", "default": "hello"}}}


def greeting(version: str, *, concurrency: ConcurrencyPolicy = ConcurrencyPolicy.ALLOW) -> PipelineDefinition:
    """A one-step pipeline whose step says the greeting it was given, tagged with ``version``."""
    return PipelineDefinition(
        code="rerun-me",
        params=PARAMS,
        concurrency=concurrency,
        steps=steps(say=StepDefinition(block="test.echo", config={"value": f"${{params.greeting}} {version}"})),
    )


async def settled(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, engine: Engine, **params: Any
) -> Run:
    """Run the first version of the pipeline to the end, with ``params``."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, greeting("v1"))
        run = await create_run(session, services, version, params=params)
    assert run is not None
    await drain(engine)
    return await reload(sessions, run.id)


async def rerun_of(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, run_id: UUID, **options: Any
) -> Run | None:
    """Rerun one run in a transaction of its own, as a route would."""
    async with session_scope(sessions) as session:
        original = await session.get(Run, run_id)
        assert original is not None
        return await rerun(session, services, original, **options)


async def said(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> object:
    """Read what the one step of a run said."""
    async with sessions() as session:
        output = await session.scalar(sa.select(StepAttempt.output).where(StepAttempt.run_id == run_id))
    assert isinstance(output, dict)
    return output.get("value")


async def test_a_rerun_takes_the_parameters_and_the_pinned_version_and_names_its_original(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    original = await settled(sessions, services, engine, greeting="hei")
    async with session_scope(sessions) as session:
        await save_pipeline(session, greeting("v2"))

    again = await rerun_of(sessions, services, original.id, label="tester")
    assert again is not None
    await drain(engine)
    stored = await reload(sessions, again.id)
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.params == {"greeting": "hei"}
    assert stored.pipeline_version_id == original.pipeline_version_id
    assert (stored.triggered_by_kind, stored.triggered_by_id) == (TriggerKind.RERUN, original.id)
    assert stored.triggered_by_label == f"rerun of {original.id} by tester"
    assert await said(sessions, again.id) == "hei v1"

    current = await rerun_of(sessions, services, original.id, version="current")
    assert current is not None
    await drain(engine)
    assert await said(sessions, current.id) == "hei v2", "the current version, with the same parameters"


async def test_a_run_queued_or_paused_is_not_rerun(sessions: Any, services: EngineServices) -> None:
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, greeting("v1"))
        run = await create_run(session, services, version)
    assert run is not None

    with pytest.raises(RunCreationError) as raised:
        await rerun_of(sessions, services, run.id)
    assert raised.value.code == RERUN_IN_FLIGHT.code
    assert raised.value.status == 409

    async with session_scope(sessions) as session:
        held = await session.get(Run, run.id)
        assert held is not None
        await pause_run(session, held)
    with pytest.raises(RunCreationError) as paused:
        await rerun_of(sessions, services, run.id)
    assert paused.value.code == RERUN_IN_FLIGHT.code, "a paused run has not settled"
    assert paused.value.params["status"] == "paused"


async def test_a_deactivated_pipeline_is_not_rerun(engine: Engine, sessions: Any, services: EngineServices) -> None:
    original = await settled(sessions, services, engine)
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Pipeline).values(active=False))

    with pytest.raises(RunCreationError) as raised:
        await rerun_of(sessions, services, original.id)
    assert raised.value.code == RUN_PIPELINE_INACTIVE.code


async def test_the_concurrency_policy_decides_a_rerun_as_it_does_any_run(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    original = await settled(sessions, services, engine)
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, greeting("v1", concurrency=ConcurrencyPolicy.SKIP))
        blocking = await create_run(session, services, version)
    assert blocking is not None

    assert await rerun_of(sessions, services, original.id, version="current") is None


async def test_a_run_entered_at_a_source_is_replayed_with_the_same_input(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    given: JsonValue = {"path_params": {"name": "Bergen"}, "body": {"mood": "wet"}}
    entry = hand_entry(document(GREET), services.sources, "ask", given, received_at=RECEIVED_AT)
    original = await start(sessions, services, GREET, entry)
    await drain(engine)
    first = await attempts(sessions, original.id)

    again = await rerun_of(sessions, services, original.id)
    assert again is not None
    await drain(engine)
    replayed = await attempts(sessions, again.id)
    stored = await reload(sessions, again.id)
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.source_step == "ask"
    assert replayed["ask"].kind is AttemptKind.RECEIVED
    assert replayed["ask"].output == first["ask"].output
    assert replayed["shape"].output is not None
    assert replayed["shape"].output["value"] == "hello Bergen"
