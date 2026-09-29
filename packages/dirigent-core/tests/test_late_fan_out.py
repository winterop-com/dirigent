"""A fan-out over a step's output: one gate at creation, the grid written when the step is ready."""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunItemStatus, RunStatus
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import (
    ConcurrencyPolicy,
    ItemPolicy,
    PipelineDefinition,
    StepDefinition,
    TriggerSpecs,
    WatchSpec,
)
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import EngineRuns, FanOutError, RunCreationError, cancel_run, retry_step
from dirigent_core.engine.state import StepOutcome, build_step_states, load_attempts
from dirigent_core.models import LogEntry, Run, RunItem, StepAttempt
from dirigent_core.plugins import PluginHost
from engineblocks import EchoOperator
from test_engine import drain, reload, start, statuses, steps

LISTED = ["no", "se", "dk"]


def listing(
    values: list[Any] | None = None,
    *,
    for_each: str = "${steps.list.output.values}",
    after: bool = True,
    **fan: Any,
) -> PipelineDefinition:
    """List three countries, fan out over what was listed, and join the batch afterwards."""
    graph = steps(
        list=StepDefinition(block="test.list", config={"values": LISTED if values is None else values}),
        push=StepDefinition(
            block="test.echo", depends_on=["list"], for_each=for_each, config={"value": "${item}"}, **fan
        ),
    )
    if after:
        graph["after"] = StepDefinition(block="test.echo", depends_on=["push"], config={"value": "joined"})
    return PipelineDefinition(code="listing", steps=graph)


async def items_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID, step: str) -> list[RunItem]:
    """Read one step's run items in grid order."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(RunItem).where(RunItem.run_id == run_id, RunItem.step_name == step).order_by(RunItem.item_index)
        )
        return list(rows.scalars())


async def step_rows(sessions: async_sessionmaker[AsyncSession], run_id: UUID, step: str) -> list[StepAttempt]:
    """Read one step's attempts, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt)
            .where(StepAttempt.run_id == run_id, StepAttempt.step_name == step)
            .order_by(StepAttempt.created_at, StepAttempt.id)
        )
        return list(rows.scalars())


async def outcome_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID, step: str) -> StepOutcome:
    """Fold one step's attempts the way the engine does."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        attempts = await load_attempts(session, run_id)
    definition = listing()
    return build_step_states(definition, attempts)[step].outcome


def narrow(settings: Settings, host: PluginHost, maximum: int) -> EngineServices:
    """Services on an instance that allows at most ``maximum`` items in one grid."""
    return EngineServices.build(settings.model_copy(update={"fan_out_max_items": maximum}), host)


# -- the gate --------------------------------------------------------------------


async def test_a_late_step_is_created_as_one_pending_gate(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, listing())

    gate = await step_rows(sessions, run.id, "push")
    assert [(one.status, one.run_item_id) for one in gate] == [(AttemptStatus.PENDING, None)]
    assert await items_of(sessions, run.id, "push") == []


async def test_before_expanding_the_step_is_pending_and_the_run_does_not_settle(
    sessions: Any, services: EngineServices
) -> None:
    """A fan-out with no rows at all folds to skipped; the gate is what keeps this one pending."""
    run = await start(sessions, services, listing())

    assert await outcome_of(sessions, run.id, "push") is StepOutcome.PENDING
    assert (await statuses(sessions, run.id))["after"] == [AttemptStatus.PENDING]
    assert (await reload(sessions, run.id)).status is RunStatus.QUEUED


async def test_a_late_grid_expands_in_list_order_once_its_source_succeeds(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listing())
    unit = await engine.claim()
    assert unit is not None and unit.step_name == "list"
    await engine.run_unit(unit)

    items = await items_of(sessions, run.id, "push")
    assert [(item.item_index, item.item_key) for item in items] == [(0, "no"), (1, "se"), (2, "dk")]
    rows = await step_rows(sessions, run.id, "push")
    assert [(one.status, one.run_item_id) for one in rows] == [(AttemptStatus.QUEUED, item.id) for item in items], (
        "the gate is gone and every item is queued"
    )
    async with sessions() as session:
        logged = await session.execute(
            sa.select(LogEntry.message).where(LogEntry.run_id == run.id, LogEntry.step_name == "push")
        )
        assert list(logged.scalars()) == ["expanded into 3 items from list"]

    await drain(engine)
    assert EchoOperator.calls == [*LISTED, "joined"], "each item reads its own ${item}"
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_a_gate_that_somehow_became_claimable_is_refused_rather_than_run(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listing())
    async with session_scope(sessions) as session:
        await session.execute(
            sa.update(StepAttempt)
            .where(StepAttempt.run_id == run.id, StepAttempt.step_name == "list")
            .values(status=AttemptStatus.SKIPPED)
        )
        await session.execute(
            sa.update(StepAttempt)
            .where(StepAttempt.run_id == run.id, StepAttempt.step_name == "push")
            .values(status=AttemptStatus.QUEUED, available_at=run.created_at)
        )

    assert await engine.claim() is None, "a gate is never handed to a block"
    (gate,) = await step_rows(sessions, run.id, "push")
    assert (gate.status, gate.error_code) == (AttemptStatus.FAILED, "run.fan_out_without_item")
    assert EchoOperator.calls == []


# -- what the list can be ---------------------------------------------------------


async def test_an_empty_list_skips_the_step_and_what_needs_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listing([]))
    await drain(engine)

    (gate,) = await step_rows(sessions, run.id, "push")
    assert (gate.status, gate.error_code) == (AttemptStatus.SKIPPED, "run.fan_out_empty")
    assert (await statuses(sessions, run.id))["after"] == [AttemptStatus.SKIPPED]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


@pytest.mark.parametrize(
    ("for_each", "code"),
    [
        ("${steps.list.output.count}", "run.fan_out_not_a_list"),
        ("${steps.list.output.missing}", "reference.no_field"),
    ],
)
async def test_a_list_that_cannot_be_read_fails_the_gate_as_rejected(
    engine: Engine, sessions: Any, services: EngineServices, for_each: str, code: str
) -> None:
    run = await start(sessions, services, listing(for_each=for_each))
    await drain(engine)

    (gate,) = await step_rows(sessions, run.id, "push")
    assert (gate.status, gate.error_code, gate.error_class) == (AttemptStatus.FAILED, code, "rejected")
    assert (await statuses(sessions, run.id))["after"] == [AttemptStatus.SKIPPED]
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED


async def test_a_late_grid_wider_than_the_instance_allows_fails_its_gate(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = narrow(settings, host, 2)
    run = await start(sessions, services, listing())
    await drain(Engine(sessions, services, owner="narrow"))

    (gate,) = await step_rows(sessions, run.id, "push")
    assert (gate.status, gate.error_code) == (AttemptStatus.FAILED, "run.fan_out_too_wide")
    assert gate.error_params == {"step": "'push'", "count": 3, "maximum": 2}
    assert await items_of(sessions, run.id, "push") == []


async def test_a_grid_fixed_at_creation_wider_than_the_instance_allows_refuses_the_run(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    definition = PipelineDefinition(
        code="wide", steps=steps(push=StepDefinition(block="test.echo", for_each=["a", "b", "c"]))
    )
    with pytest.raises(FanOutError) as refused:
        await start(sessions, narrow(settings, host, 2), definition)
    assert refused.value.code == "run.fan_out_too_wide"


async def test_the_grid_reads_only_the_succeeded_items_of_a_fan_out_source(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="survivors",
        steps=steps(
            spread=StepDefinition(
                block="test.fail",
                for_each=[{"key": "a", "fail": 0}, {"key": "b", "fail": 9}, {"key": "c", "fail": 0}],
                items=ItemPolicy.CONTINUE,
                config={"key": "${item.key}", "fail_times": "${item.fail}", "error_class": "rejected"},
            ),
            push=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.output}",
                config={"value": "tried ${item.attempts}"},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    assert len(await items_of(sessions, run.id, "push")) == 2, "the failed item contributed nothing"
    assert EchoOperator.calls == ["tried 1", "tried 1"]
    assert (await reload(sessions, run.id)).status is RunStatus.COMPLETED_WITH_ERRORS


# -- adopting a late grid ---------------------------------------------------------


async def test_an_adopter_of_a_late_grid_expands_with_matching_indices(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = listing(after=False)
    graph = dict(definition.steps)
    graph["collect"] = StepDefinition(
        block="test.echo",
        depends_on=["push"],
        for_each="${steps.push.items}",
        config={"value": "paired-${steps.push.item.output.value}"},
    )
    run = await start(sessions, services, definition.model_copy(update={"steps": graph}))
    assert [(one.status, one.run_item_id) for one in await step_rows(sessions, run.id, "collect")] == [
        (AttemptStatus.PENDING, None)
    ], "an adopter of a late grid is late too"

    await drain(engine)

    collected = await items_of(sessions, run.id, "collect")
    assert [(item.item_index, item.item_key) for item in collected] == [(0, "no"), (1, "se"), (2, "dk")]
    assert EchoOperator.calls[3:] == ["paired-no", "paired-se", "paired-dk"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


# -- retries ----------------------------------------------------------------------


def failing_source() -> PipelineDefinition:
    """A fan-out source whose second item fails once and for good, then the late grid over it."""
    return PipelineDefinition(
        code="flaky-source",
        steps=steps(
            spread=StepDefinition(
                block="test.fail",
                for_each=["a", "b"],
                config={"key": "${item}", "fail_times": 1, "error_class": "rejected"},
            ),
            push=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.output}",
                config={"value": "after ${item.attempts}"},
            ),
        ),
    )


async def test_a_gate_skipped_behind_a_failed_source_expands_once_the_source_is_retried(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, failing_source())
    await drain(engine)
    assert (await statuses(sessions, run.id))["push"] == [AttemptStatus.SKIPPED]
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED

    spread = await items_of(sessions, run.id, "spread")
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        for item in spread:
            await retry_step(
                session, services, stored, "spread", idempotency_key=f"again-{item.item_index}", run_item_id=item.id
            )
    await drain(engine)

    assert len(await items_of(sessions, run.id, "push")) == 2
    assert EchoOperator.calls == ["after 2", "after 2"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_retrying_a_gate_is_refused(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, listing())
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        with pytest.raises(RunCreationError) as refused:
            await retry_step(session, services, stored, "push", idempotency_key="nope")
    assert refused.value.code == "run.gate_not_retryable"
    assert refused.value.params == {"step": "'push'", "source": "'list'"}


async def test_an_item_of_an_expanded_grid_can_still_be_retried(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="late-retry",
        steps=steps(
            list=StepDefinition(block="test.list", config={"values": ["x", "y"]}),
            push=StepDefinition(
                block="test.fail",
                depends_on=["list"],
                for_each="${steps.list.output.values}",
                config={"key": "${item}", "fail_times": 1, "error_class": "rejected"},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED

    first = (await items_of(sessions, run.id, "push"))[0]
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        retried = await retry_step(session, services, stored, "push", idempotency_key="again", run_item_id=first.id)
    assert retried.run_item_id == first.id
    await drain(engine)
    assert len(await items_of(sessions, run.id, "push")) == 2, "the grid stays as it was expanded"
    assert [item.status for item in await items_of(sessions, run.id, "push")] == [
        RunItemStatus.SUCCEEDED,
        RunItemStatus.FAILED,
    ]


# -- cancelling and holding -------------------------------------------------------


async def test_cancelling_before_the_grid_expands_cancels_the_gate(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, listing())
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)

    assert (await statuses(sessions, run.id))["push"] == [AttemptStatus.CANCELLED]
    assert await outcome_of(sessions, run.id, "push") is StepOutcome.CANCELLED
    assert (await reload(sessions, run.id)).status is RunStatus.CANCELLED


async def test_cancelling_after_the_grid_expands_skips_its_items(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listing())
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)

    assert {item.status for item in await items_of(sessions, run.id, "push")} == {RunItemStatus.SKIPPED}
    assert (await statuses(sessions, run.id))["push"] == [AttemptStatus.CANCELLED] * 3


async def test_a_held_run_keeps_its_gate_pending_until_it_is_released(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = listing(after=False).model_copy(update={"concurrency": ConcurrencyPolicy.QUEUE})
    first = await start(sessions, services, definition)
    held = await start(sessions, services, definition)
    assert await statuses(sessions, held.id) == {"list": [AttemptStatus.PENDING], "push": [AttemptStatus.PENDING]}

    await drain(engine)

    assert (await reload(sessions, first.id)).status is RunStatus.SUCCEEDED
    assert (await reload(sessions, held.id)).status is RunStatus.SUCCEEDED
    assert len(await items_of(sessions, held.id, "push")) == 3


# -- what a caller reads ----------------------------------------------------------


async def test_a_snapshot_counts_the_gate_as_one_unit_and_then_each_item(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listing(after=False))
    runs = EngineRuns(services, parent_run_id=run.id, sessions=sessions)

    before = await runs.snapshot(run.id)
    assert before is not None
    assert (before.total_steps, before.finished_steps) == (2, 0)

    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    after = await runs.snapshot(run.id)
    assert after is not None
    assert (after.total_steps, after.finished_steps) == (4, 1)


# -- a watch ----------------------------------------------------------------------


async def test_a_watch_armed_run_fans_out_over_its_sensors_batch(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    from test_watches import apply, pump, watch_runs

    definition = PipelineDefinition(
        code="tail-and-spread",
        steps=steps(
            tail=StepDefinition(block="test.stream", config={"batch": 3}, poll=timedelta(seconds=1)),
            load=StepDefinition(
                block="test.echo",
                depends_on=["tail"],
                for_each="${steps.tail.output.offsets}",
                config={"value": "offset ${item}"},
            ),
        ),
        triggers=TriggerSpecs(watches=[WatchSpec(code="follow", step="tail")]),
    )
    await apply(sessions, services, definition)

    async def two_batches_expanded() -> bool:
        armed = await watch_runs(sessions)
        return len(armed) >= 2 and len(await items_of(sessions, armed[1].id, "load")) == 3

    await pump(engine, two_batches_expanded)

    first, second = (await watch_runs(sessions))[:2]
    assert [item.item_key for item in await items_of(sessions, first.id, "load")] == ["0", "1", "2"]
    assert [item.item_key for item in await items_of(sessions, second.id, "load")] == ["3", "4", "5"]
