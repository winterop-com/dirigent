"""An item of an adopting step runs once its match has settled, not once the whole grid has."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import ItemPolicy, PipelineDefinition, StepDefinition, TriggerRule
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.state import (
    Readiness,
    StepOutcome,
    StepState,
    gate_readiness,
    item_readiness,
    item_wise_parent,
)
from dirigent_core.models import RunItem, StepAttempt
from engineblocks import EchoOperator
from test_engine import drain, reload, start, steps

COUNTRIES: list[JsonValue] = ["no", "se", "dk"]


def paired(
    *,
    items: ItemPolicy = ItemPolicy.CONTINUE,
    config: dict[str, Any] | None = None,
    **collect: Any,
) -> PipelineDefinition:
    """Fan out over three countries, then map a second step over the same grid."""
    return PipelineDefinition(
        code="item-wise",
        steps=steps(
            spread=StepDefinition(block="test.echo", for_each=COUNTRIES, config={"value": "${item}"}, items=items),
            collect=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.items}",
                config=config or {"value": "paired-${steps.spread.item.output.value}"},
                **collect,
            ),
        ),
    )


async def by_index(sessions: async_sessionmaker[AsyncSession], run_id: UUID, step: str) -> list[AttemptStatus]:
    """Read the newest attempt status of each of one step's items, in grid order."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(RunItem.item_index, StepAttempt.attempt, StepAttempt.status)
            .join(RunItem, RunItem.id == StepAttempt.run_item_id)
            .where(StepAttempt.run_id == run_id, StepAttempt.step_name == step)
            .order_by(RunItem.item_index, StepAttempt.attempt)
        )
        newest: dict[int, AttemptStatus] = {}
        for index, _attempt, status in rows.all():
            newest[index] = status
        return [newest[index] for index in sorted(newest)]


async def run_one(engine: Engine) -> None:
    """Claim and run exactly one due unit, a second ahead so what it queues is due by `finish`."""
    moment = datetime.now(UTC) + timedelta(seconds=1)
    unit = await engine.claim(now=moment)
    assert unit is not None
    await engine.run_unit(unit, now=moment)


async def finish(engine: Engine) -> None:
    """Run everything left, on a clock past every unit `run_one` ran."""
    await drain(engine, start_at=datetime.now(UTC) + timedelta(seconds=2))


# -- the engine ---------------------------------------------------------------------


async def test_an_item_is_queued_once_its_match_succeeded(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, paired())
    await run_one(engine)

    spread = await by_index(sessions, run.id, "spread")
    collect = await by_index(sessions, run.id, "collect")
    done = spread.index(AttemptStatus.SUCCEEDED)
    assert spread.count(AttemptStatus.SUCCEEDED) == 1
    assert collect[done] is AttemptStatus.QUEUED
    assert [status for index, status in enumerate(collect) if index != done] == [AttemptStatus.PENDING] * 2

    await finish(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert sorted(call for call in EchoOperator.calls if call.startswith("paired-")) == [
        "paired-dk",
        "paired-no",
        "paired-se",
    ]


async def test_a_fail_fast_parent_holds_every_item_until_it_settles(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, paired(items=ItemPolicy.FAIL_FAST))
    await run_one(engine)

    assert (await by_index(sessions, run.id, "spread")).count(AttemptStatus.SUCCEEDED) == 1
    assert await by_index(sessions, run.id, "collect") == [AttemptStatus.PENDING] * 3

    await finish(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_an_item_reading_the_parents_whole_output_waits_for_all_of_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, paired(config={"value": "last-${steps.spread.output.2.value}"}))
    await run_one(engine)
    assert await by_index(sessions, run.id, "collect") == [AttemptStatus.PENDING] * 3

    await finish(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    read = [call for call in EchoOperator.calls if call.startswith("last-")]
    assert read == ["last-dk"] * 3, "every item read the batch once it was whole"


async def test_an_item_under_all_done_waits_for_the_whole_grid(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, paired(rule=TriggerRule.ALL_DONE))
    await run_one(engine)
    assert await by_index(sessions, run.id, "collect") == [AttemptStatus.PENDING] * 3

    await finish(engine)
    assert await by_index(sessions, run.id, "collect") == [AttemptStatus.SUCCEEDED] * 3


# -- which steps go item by item ----------------------------------------------------


def test_a_step_adopting_a_continue_grid_goes_item_by_item() -> None:
    assert item_wise_parent(paired(), "collect") == "spread"


def test_a_step_with_its_own_grid_waits_for_its_prerequisites_whole() -> None:
    assert item_wise_parent(paired(), "spread") is None


def test_a_fail_fast_parent_keeps_the_step_waiting_for_all_of_it() -> None:
    assert item_wise_parent(paired(items=ItemPolicy.FAIL_FAST), "collect") is None


def test_a_rule_other_than_all_success_keeps_the_step_waiting() -> None:
    assert item_wise_parent(paired(rule=TriggerRule.ALL_DONE), "collect") is None
    assert item_wise_parent(paired(rule=TriggerRule.ALWAYS), "collect") is None


def test_reading_the_parents_output_keeps_the_step_waiting() -> None:
    assert item_wise_parent(paired(config={"value": "${steps.spread.output.0.value}"}), "collect") is None


def test_reading_a_step_outside_the_grid_does_not_keep_the_step_waiting() -> None:
    definition = PipelineDefinition(
        code="item-wise",
        steps=steps(
            setup=StepDefinition(block="test.echo", config={"value": "ready"}),
            spread=StepDefinition(
                block="test.echo", for_each=COUNTRIES, config={"value": "${item}"}, items=ItemPolicy.CONTINUE
            ),
            collect=StepDefinition(
                block="test.echo",
                depends_on=["spread", "setup"],
                for_each="${steps.spread.items}",
                config={"value": "${steps.setup.output.value}-${steps.spread.item.output.value}"},
            ),
        ),
    )
    assert item_wise_parent(definition, "collect") == "spread"


def chained(last_config: dict[str, Any]) -> PipelineDefinition:
    """Three steps over one grid, the last adopting the middle that adopts the first."""
    return PipelineDefinition(
        code="chained",
        steps=steps(
            spread=StepDefinition(
                block="test.echo", for_each=COUNTRIES, config={"value": "${item}"}, items=ItemPolicy.CONTINUE
            ),
            middle=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.items}",
                config={"value": "${steps.spread.item.output.value}"},
                items=ItemPolicy.CONTINUE,
            ),
            last=StepDefinition(
                block="test.echo", depends_on=["middle"], for_each="${steps.middle.items}", config=last_config
            ),
        ),
    )


def test_a_chain_goes_item_by_item_through_its_nearest_parent() -> None:
    definition = chained({"value": "${steps.spread.item.output.value}${steps.middle.item.output.value}"})
    assert item_wise_parent(definition, "middle") == "spread"
    assert item_wise_parent(definition, "last") == "middle"


def test_reading_a_grandparents_whole_output_keeps_the_step_waiting() -> None:
    assert item_wise_parent(chained({"value": "${steps.spread.output}"}), "last") is None


# -- one item's readiness -----------------------------------------------------------


def states(**outcomes: StepOutcome) -> dict[str, StepState]:
    """Fold named outcomes into the step states readiness reads."""
    return {name: StepState(name=name, outcome=outcome) for name, outcome in outcomes.items()}


def with_setup() -> PipelineDefinition:
    """An adopting step that also waits on a step outside the grid."""
    return PipelineDefinition(
        code="item-wise",
        steps=steps(
            setup=StepDefinition(block="test.echo"),
            spread=StepDefinition(block="test.echo", for_each=COUNTRIES, items=ItemPolicy.CONTINUE),
            collect=StepDefinition(block="test.echo", depends_on=["spread", "setup"], for_each="${steps.spread.items}"),
        ),
    )


def test_an_item_waits_while_its_match_is_in_flight() -> None:
    folded = states(setup=StepOutcome.SUCCEEDED, spread=StepOutcome.RUNNING)
    assert item_readiness(with_setup(), "collect", folded, StepOutcome.RUNNING) is Readiness.WAIT
    assert item_readiness(with_setup(), "collect", folded, None) is Readiness.WAIT


def test_an_item_is_ready_once_its_match_succeeded_whatever_its_siblings_do() -> None:
    folded = states(setup=StepOutcome.SUCCEEDED, spread=StepOutcome.RUNNING)
    assert item_readiness(with_setup(), "collect", folded, StepOutcome.SUCCEEDED) is Readiness.READY


def test_an_item_whose_match_settled_otherwise_is_ready_to_be_skipped_as_unpaired() -> None:
    folded = states(setup=StepOutcome.SUCCEEDED, spread=StepOutcome.RUNNING)
    for outcome in (StepOutcome.FAILED, StepOutcome.SKIPPED, StepOutcome.CANCELLED):
        assert item_readiness(with_setup(), "collect", folded, outcome) is Readiness.READY


def test_an_item_still_waits_for_the_steps_other_prerequisites() -> None:
    running = states(setup=StepOutcome.RUNNING, spread=StepOutcome.RUNNING)
    assert item_readiness(with_setup(), "collect", running, StepOutcome.SUCCEEDED) is Readiness.WAIT
    failed = states(setup=StepOutcome.FAILED, spread=StepOutcome.RUNNING)
    assert item_readiness(with_setup(), "collect", failed, StepOutcome.SUCCEEDED) is Readiness.NEVER


# -- late grids ---------------------------------------------------------------------


def listed_then_paired(*, items: ItemPolicy = ItemPolicy.CONTINUE) -> PipelineDefinition:
    """List three countries, fan out over the listing, and map a second step over that grid."""
    return PipelineDefinition(
        code="late-item-wise",
        steps=steps(
            list=StepDefinition(block="test.list", config={"values": COUNTRIES}),
            spread=StepDefinition(
                block="test.echo",
                depends_on=["list"],
                for_each="${steps.list.output.values}",
                config={"value": "${item}"},
                items=items,
            ),
            collect=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.items}",
                config={"value": "paired-${steps.spread.item.output.value}"},
            ),
        ),
    )


async def gate_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID, step: str) -> list[AttemptStatus]:
    """Read the status of the gate a late grid still stands behind, empty once it is expanded."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt.status).where(
                StepAttempt.run_id == run_id, StepAttempt.step_name == step, StepAttempt.run_item_id.is_(None)
            )
        )
        return list(rows.scalars())


async def test_an_adopter_of_a_late_grid_expands_once_the_grid_exists(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listed_then_paired())
    await run_one(engine)

    assert await by_index(sessions, run.id, "spread") == [AttemptStatus.QUEUED] * 3
    assert await gate_of(sessions, run.id, "collect") == []
    assert await by_index(sessions, run.id, "collect") == [AttemptStatus.PENDING] * 3


async def test_an_item_of_a_late_adopter_runs_once_its_match_succeeded(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listed_then_paired())
    await run_one(engine)
    await run_one(engine)

    spread = await by_index(sessions, run.id, "spread")
    collect = await by_index(sessions, run.id, "collect")
    done = spread.index(AttemptStatus.SUCCEEDED)
    assert spread.count(AttemptStatus.SUCCEEDED) == 1
    assert collect[done] is AttemptStatus.QUEUED
    assert [status for index, status in enumerate(collect) if index != done] == [AttemptStatus.PENDING] * 2

    await finish(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert sorted(call for call in EchoOperator.calls if call.startswith("paired-")) == [
        "paired-dk",
        "paired-no",
        "paired-se",
    ]


async def test_a_late_adopter_of_a_fail_fast_grid_expands_once_the_grid_has_settled(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, listed_then_paired(items=ItemPolicy.FAIL_FAST))
    await run_one(engine)
    await run_one(engine)

    assert (await by_index(sessions, run.id, "spread")).count(AttemptStatus.SUCCEEDED) == 1
    assert await gate_of(sessions, run.id, "collect") == [AttemptStatus.PENDING]

    await finish(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert await by_index(sessions, run.id, "collect") == [AttemptStatus.SUCCEEDED] * 3


async def test_a_late_adopter_of_an_empty_listing_is_skipped(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = listed_then_paired()
    empty = definition.model_copy(
        update={
            "steps": {
                **definition.steps,
                "list": StepDefinition(block="test.list", config={"values": []}),
            }
        }
    )
    run = await start(sessions, services, empty)
    await finish(engine)
    assert await gate_of(sessions, run.id, "collect") == [AttemptStatus.SKIPPED]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


def test_a_late_gate_reads_its_prerequisites_whole_until_the_parent_grid_exists() -> None:
    definition = listed_then_paired()
    folded = states(list=StepOutcome.SUCCEEDED, spread=StepOutcome.RUNNING, collect=StepOutcome.PENDING)
    assert gate_readiness(definition, "collect", folded, expanded=False) is Readiness.WAIT
    assert gate_readiness(definition, "collect", folded, expanded=True) is Readiness.READY
    settled = states(list=StepOutcome.SUCCEEDED, spread=StepOutcome.FAILED, collect=StepOutcome.PENDING)
    assert gate_readiness(definition, "collect", settled, expanded=True) is Readiness.NEVER
