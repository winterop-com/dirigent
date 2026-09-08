"""Tests for ``EngineRuns``: the runs facade a block reaches through ``StepContext.runs``."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import RunStatus, TriggerKind
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import (
    MAX_CHAIN_WALK,
    Attribution,
    EngineRuns,
    chain_depth,
    create_run,
    save_pipeline,
)
from dirigent_core.models import Pipeline, Run
from dirigent_plugin import RunRefused, RunState


def document(name: str, *, params: dict[str, object] | None = None, steps: int = 1) -> PipelineDefinition:
    """Build a pipeline of a few echo steps, chained so the run has a shape to measure."""
    built: dict[str, StepDefinition] = {}
    for index in range(steps):
        built[f"step_{index}"] = StepDefinition(
            block="test.echo",
            config={"value": index},
            depends_on=[f"step_{index - 1}"] if index else [],
        )
    return PipelineDefinition(
        code=name,
        steps=built,
        params=params or {"type": "object", "properties": {}, "additionalProperties": False},
    )


async def apply(
    sessions: async_sessionmaker[AsyncSession],
    definition: PipelineDefinition,
) -> None:
    """Store one version of a pipeline, which is what a start needs to find."""
    async with session_scope(sessions) as session:
        await save_pipeline(session, definition)


async def a_run(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    definition: PipelineDefinition,
) -> Run:
    """Create the run whose step is going to start another one."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return run


def facade(
    services: EngineServices,
    sessions: async_sessionmaker[AsyncSession],
    parent: Run,
) -> EngineRuns:
    """Build the facade the way the executor builds it: its own transaction per call."""
    return EngineRuns(services, parent_run_id=parent.id, sessions=sessions)


# -- starting ---------------------------------------------------------------------


async def test_a_started_run_is_attributed_to_the_run_that_started_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    await apply(sessions, document("child"))

    started = await facade(services, sessions, parent).start("child", {}, max_depth=5)

    assert started.run_id is not None
    assert started.state is RunState.QUEUED
    async with sessions() as session:
        child = await session.get(Run, started.run_id)
    assert child is not None
    assert child.triggered_by_kind is TriggerKind.PIPELINE
    assert child.triggered_by_id == parent.id
    assert str(parent.id) in (child.triggered_by_label or "")


async def test_a_start_validates_its_params_against_the_target_schema(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    await apply(
        sessions,
        document(
            "child",
            params={
                "type": "object",
                "properties": {"day": {"type": "string"}},
                "required": ["day"],
                "additionalProperties": False,
            },
        ),
    )
    runs = facade(services, sessions, parent)

    started = await runs.start("child", {"day": "2026-01-01"}, max_depth=5)
    assert started.run_id is not None

    with pytest.raises(RunRefused, match="could not be started"):
        await runs.start("child", {"nonsense": 1}, max_depth=5)


async def test_a_start_of_an_unknown_pipeline_is_refused_and_never_retried(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    with pytest.raises(RunRefused, match="no pipeline coded 'missing'"):
        await facade(services, sessions, parent).start("missing", {}, max_depth=5)


async def test_a_start_of_a_deactivated_or_unversioned_pipeline_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    await apply(sessions, document("child"))
    async with session_scope(sessions) as session:
        found = await session.execute(sa.select(Pipeline).where(Pipeline.code == "child"))
        found.scalar_one().active = False
    with pytest.raises(RunRefused, match="is deactivated"):
        await facade(services, sessions, parent).start("child", {}, max_depth=5)

    async with session_scope(sessions) as session:
        session.add(Pipeline(code="fresh"))
    with pytest.raises(RunRefused, match="has no versions yet"):
        await facade(services, sessions, parent).start("fresh", {}, max_depth=5)


async def test_a_skipped_child_reports_no_run_rather_than_failing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    child = document("child")
    await apply(sessions, child.model_copy(update={"concurrency": ConcurrencyPolicy.SKIP}))
    runs = facade(services, sessions, parent)

    first = await runs.start("child", {}, max_depth=5)
    second = await runs.start("child", {}, max_depth=5)

    assert not first.skipped
    assert second.skipped
    assert second.run_id is None


# -- the cycle and depth guards ---------------------------------------------------


async def test_a_pipeline_cannot_start_itself(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    with pytest.raises(RunRefused, match="cannot start itself"):
        await facade(services, sessions, parent).start("parent", {}, max_depth=5)


async def test_a_pipeline_already_further_up_the_chain_cannot_be_started_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A starts B starts A is a cycle that the depth bound alone would only slow down."""
    await apply(sessions, document("middle"))
    top = await a_run(sessions, services, document("top"))
    started = await facade(services, sessions, top).start("middle", {}, max_depth=5)
    assert started.run_id is not None
    async with sessions() as session:
        middle = await session.get(Run, started.run_id)
    assert middle is not None

    with pytest.raises(RunRefused, match="already running further up this chain"):
        await facade(services, sessions, middle).start("top", {}, max_depth=5)


async def test_the_depth_guard_stops_a_chain_that_has_gone_far_enough(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    for level in range(1, 5):
        await apply(sessions, document(f"level-{level}"))
    current = await a_run(sessions, services, document("root"))
    for level in range(1, 4):
        started = await facade(services, sessions, current).start(f"level-{level}", {}, max_depth=3)
        assert started.run_id is not None
        async with sessions() as session:
            found = await session.get(Run, started.run_id)
        assert found is not None
        current = found

    with pytest.raises(RunRefused, match="would be 4 pipelines deep, and max_depth is 3"):
        await facade(services, sessions, current).start("level-4", {}, max_depth=3)


async def test_the_chain_depth_counts_only_pipeline_started_ancestors(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    scheduled = await a_run(sessions, services, document("root"))
    async with session_scope(sessions) as session:
        found = await session.get(Run, scheduled.id)
        assert found is not None
        found.triggered_by_kind = TriggerKind.SCHEDULE
        found.triggered_by_id = uuid4()
        assert await chain_depth(session, found) == 0


async def test_the_chain_walk_is_bounded_even_when_the_rows_describe_a_loop(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await a_run(sessions, services, document("root"))
    async with session_scope(sessions) as session:
        found = await session.get(Run, run.id)
        assert found is not None
        found.triggered_by_kind = TriggerKind.PIPELINE
        found.triggered_by_id = found.id
        await session.flush()
        assert await chain_depth(session, found) == MAX_CHAIN_WALK


# -- observing and cancelling -----------------------------------------------------


async def test_a_snapshot_counts_the_units_of_work_a_run_still_owes(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    await apply(sessions, document("child", steps=3))
    runs = facade(services, sessions, parent)
    started = await runs.start("child", {}, max_depth=5)
    assert started.run_id is not None

    snapshot = await runs.snapshot(started.run_id)

    assert snapshot is not None
    assert snapshot.pipeline == "child"
    assert snapshot.state is RunState.QUEUED
    assert (snapshot.total_steps, snapshot.finished_steps) == (3, 0)
    assert snapshot.progress == 0.0


async def test_a_snapshot_of_a_run_this_instance_does_not_hold_is_none(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    assert await facade(services, sessions, parent).snapshot(uuid4()) is None


async def test_cancelling_a_child_settles_it_and_says_it_did(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    await apply(sessions, document("child"))
    runs = facade(services, sessions, parent)
    started = await runs.start("child", {}, max_depth=5)
    assert started.run_id is not None

    assert await runs.cancel(started.run_id, reason="the parent was cancelled") is True
    assert await runs.cancel(started.run_id, reason="again") is False
    assert await runs.cancel(uuid4(), reason="nothing there") is False

    snapshot = await runs.snapshot(started.run_id)
    assert snapshot is not None
    assert snapshot.state is RunState.CANCELLED
    assert snapshot.error == "the parent was cancelled"


# -- the two transaction shapes ---------------------------------------------------


async def test_a_bound_facade_works_inside_the_callers_transaction(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    await apply(sessions, document("child"))
    async with session_scope(sessions) as session:
        runs = EngineRuns(services, parent_run_id=parent.id, session=session)
        started = await runs.start("child", {}, max_depth=5)
        assert started.run_id is not None
        # Visible within the transaction that created it, before any commit.
        assert (await runs.snapshot(started.run_id)) is not None
    async with sessions() as session:
        assert await session.get(Run, started.run_id) is not None


async def test_a_facade_takes_a_factory_or_a_session_but_never_both_or_neither(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        EngineRuns(services, parent_run_id=uuid4())
    async with sessions() as session:
        with pytest.raises(ValueError, match="exactly one"):
            EngineRuns(services, parent_run_id=uuid4(), sessions=sessions, session=session)


async def test_a_start_from_a_run_that_no_longer_exists_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, document("child"))
    runs = EngineRuns(services, parent_run_id=uuid4(), sessions=sessions)
    with pytest.raises(RunRefused, match="no longer exists"):
        await runs.start("child", {}, max_depth=5)


def test_the_two_run_status_vocabularies_never_drift_apart() -> None:
    """``RunState`` is the block-facing copy of ``RunStatus``; nothing may be in only one."""
    assert {state.value for state in RunState} == {status.value for status in RunStatus}


async def test_an_ad_hoc_attribution_still_reads_as_depth_zero(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await a_run(sessions, services, document("parent"))
    async with session_scope(sessions) as session:
        found = await session.get(Run, parent.id)
        assert found is not None
        assert found.triggered_by_kind is Attribution().kind
        assert await chain_depth(session, found) == 0
