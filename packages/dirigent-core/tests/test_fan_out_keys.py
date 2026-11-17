"""A fan-out's ``key``: each item named by a field of its element, and an adopted grid named alike."""

from typing import Any

import pytest

from dirigent_client.enums import AttemptStatus
from dirigent_core.documents import DocumentError, load_pipeline_text
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import ItemPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import FanOutError
from test_engine import start, steps
from test_late_fan_out import items_of, step_rows

TARGETS = [
    {"code": "eu", "site": {"code": "chap-eu"}, "url": "https://eu.example.org"},
    {"code": "af", "site": {"code": "chap-af"}, "url": "https://af.example.org"},
]


def checks(targets: list[Any], *, key: str = "code") -> PipelineDefinition:
    """Two checks over the targets: the foundation keyed by ``key``, and one mapping over its grid."""
    return PipelineDefinition(
        code="checks",
        steps=steps(
            reachable=StepDefinition(
                block="test.echo", for_each=targets, key=key, items=ItemPolicy.CONTINUE, config={"value": "${item.url}"}
            ),
            answers=StepDefinition(
                block="test.echo",
                depends_on=["reachable"],
                for_each="${steps.reachable.items}",
                config={"value": "${item.url}"},
            ),
        ),
    )


async def test_an_item_is_named_by_the_field_its_step_keys_by(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, checks(TARGETS))
    assert [item.item_key for item in await items_of(sessions, run.id, "reachable")] == ["eu", "af"]


async def test_a_dotted_key_reaches_a_nested_field(sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, checks(TARGETS, key="site.code"))
    assert [item.item_key for item in await items_of(sessions, run.id, "reachable")] == ["chap-eu", "chap-af"]


async def test_a_grid_that_adopts_another_takes_its_names(sessions: Any, services: EngineServices) -> None:
    """A target keeps one name across every check that maps over it."""
    run = await start(sessions, services, checks(TARGETS))
    assert [item.item_key for item in await items_of(sessions, run.id, "answers")] == ["eu", "af"]


async def test_without_a_key_an_item_is_named_by_its_whole_element(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="unkeyed", steps=steps(spread=StepDefinition(block="test.echo", for_each=["oslo", "bergen"]))
    )
    run = await start(sessions, services, definition)
    assert [item.item_key for item in await items_of(sessions, run.id, "spread")] == ["oslo", "bergen"]


@pytest.mark.parametrize(
    ("targets", "code", "params"),
    [
        (
            [{"code": "eu"}, {"url": "https://af.example.org"}],
            "run.fan_out_key_unreadable",
            {"step": "'reachable'", "key": "code", "index": 1},
        ),
        (
            [{"code": {"nested": True}}],
            "run.fan_out_key_unreadable",
            {"step": "'reachable'", "key": "code", "index": 0},
        ),
        ([{"code": True}], "run.fan_out_key_unreadable", {"step": "'reachable'", "key": "code", "index": 0}),
        (
            [{"code": "eu"}, {"code": "af"}, {"code": "eu"}],
            "run.fan_out_key_repeated",
            {"step": "'reachable'", "key": "code", "first": 0, "second": 2, "value": "'eu'"},
        ),
    ],
    ids=["missing", "not-a-scalar", "a-boolean", "repeated"],
)
async def test_a_grid_its_key_cannot_name_refuses_the_run(
    sessions: Any, services: EngineServices, targets: list[Any], code: str, params: dict[str, Any]
) -> None:
    with pytest.raises(FanOutError) as refused:
        await start(sessions, services, checks(targets))
    assert (refused.value.code, refused.value.params) == (code, params)


def late(listed: list[Any]) -> PipelineDefinition:
    """List the targets in a step, fan out over what was listed by code, and map a check over that."""
    return PipelineDefinition(
        code="late",
        steps=steps(
            list=StepDefinition(block="test.list", config={"values": listed}),
            reachable=StepDefinition(
                block="test.echo",
                depends_on=["list"],
                for_each="${steps.list.output.values}",
                key="code",
                config={"value": "${item.url}"},
            ),
            answers=StepDefinition(
                block="test.echo",
                depends_on=["reachable"],
                for_each="${steps.reachable.items}",
                config={"value": "${item.url}"},
            ),
        ),
    )


async def test_a_late_grid_is_named_by_its_key_and_an_adopting_one_inherits_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, late(TARGETS))
    while (unit := await engine.claim()) is not None:
        await engine.run_unit(unit)
    assert [item.item_key for item in await items_of(sessions, run.id, "reachable")] == ["eu", "af"]
    assert [item.item_key for item in await items_of(sessions, run.id, "answers")] == ["eu", "af"]


async def test_a_late_grid_its_key_cannot_name_fails_its_step_as_rejected(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, late([{"code": "eu"}, {"code": "eu"}]))
    unit = await engine.claim()
    assert unit is not None and unit.step_name == "list"
    await engine.run_unit(unit)
    (gate,) = await step_rows(sessions, run.id, "reachable")
    assert (gate.status, gate.error_code, gate.error_class) == (
        AttemptStatus.FAILED,
        "run.fan_out_key_repeated",
        "rejected",
    )
    assert await items_of(sessions, run.id, "reachable") == []


DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: keyed
steps:
  reachable:
    block: test.echo
    for_each: ${params.targets}
    key: code
  answers:
    block: test.echo
    depends_on: [reachable]
    for_each: ${steps.reachable.items}
"""


def test_a_document_round_trips_its_key() -> None:
    assert load_pipeline_text(DOCUMENT).steps["reachable"].key == "code"


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (("    key: code\n", ""), None),
        (("    for_each: ${params.targets}\n    key: code\n", "    key: code\n"), "only a step with for_each"),
        (
            ("    for_each: ${steps.reachable.items}\n", "    for_each: ${steps.reachable.items}\n    key: code\n"),
            "takes no key of its own",
        ),
        (("    key: code\n", "    key: code.\n"), "a key is a field of each element"),
        (("    key: code\n", '    key: "${item.code}"\n'), "a key is a field of each element"),
    ],
    ids=["no-key", "without-fan-out", "on-an-adopted-grid", "trailing-dot", "a-reference"],
)
def test_a_key_is_checked_when_the_document_loads(change: tuple[str, str], said: str | None) -> None:
    text = DOCUMENT.replace(*change)
    if said is None:
        assert load_pipeline_text(text).steps["reachable"].key is None
        return
    with pytest.raises(DocumentError, match=said):
        load_pipeline_text(text)
