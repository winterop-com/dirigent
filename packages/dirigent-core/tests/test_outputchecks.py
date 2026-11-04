"""Plan warns on a read of an output field the step's block says its output never has."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.schemas import Catalog, PlanAction
from dirigent_core.database import session_scope
from dirigent_core.documents import load_pipeline_text
from dirigent_core.engine.services import EngineServices
from dirigent_core.outputchecks import output_field_warnings
from dirigent_core.pipelines import apply_document
from dirigent_core.plugins import load_plugin_host

HEAD = "format: dirigent/v1\ncode: misread\n"

PRODUCER = "  made:\n    block: value.const\n    config: {value: {count: 3}}\n"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_plugin_host().catalog()


def warned(text: str, catalog: Catalog | None) -> list[tuple[str, str, object]]:
    found = output_field_warnings(load_pipeline_text(HEAD + text), catalog)
    return [(issue.code, issue.location, issue.params.get("field")) for issue in found]


def reader(reference: str) -> str:
    return (
        f"steps:\n{PRODUCER}"
        "  used:\n    block: log.write\n    depends_on: [made]\n"
        f"    config: {{message: '{reference}'}}\n"
    )


def test_a_reference_to_a_field_the_output_does_not_have_is_warned_on_naming_what_it_has(catalog: Catalog) -> None:
    [issue] = output_field_warnings(load_pipeline_text(HEAD + reader("${steps.made.output.valu}")), catalog)
    assert (issue.code, issue.location) == ("document.output_field_unknown", "steps.used.config")
    assert issue.params["field"] == "'valu'"
    assert issue.params["fields"] == "value"
    assert issue.params["block"] == "value.const"


@pytest.mark.parametrize(
    "reference",
    [
        "${steps.made.output.value}",
        "${steps.made.output.value.count}",
        "${steps.made.output.value.anything.at.all}",
        "${steps.made.output}",
        "${params.x}",
    ],
    ids=["declared", "into-an-open-value", "deep-into-an-open-value", "whole", "not-an-output"],
)
def test_a_read_the_schema_does_not_rule_out_is_not_warned_on(catalog: Catalog, reference: str) -> None:
    assert warned(reader(reference), catalog) == []


def test_a_read_through_an_open_mapping_is_not_judged(catalog: Catalog) -> None:
    text = (
        "steps:\n  fetched:\n    block: http.request\n    config: {connection: api, path: /}\n"
        "  used:\n    block: log.write\n    depends_on: [fetched]\n"
        "    config: {message: '${steps.fetched.output.headers.etag} ${steps.fetched.output.statuss}'}\n"
    )
    assert warned(text, catalog) == [("document.output_field_unknown", "steps.used.config", "'statuss'")]


def test_a_fan_out_s_output_is_a_list_and_is_not_judged_while_its_item_output_is(catalog: Catalog) -> None:
    text = (
        "steps:\n  made:\n    block: value.const\n    for_each: [1, 2]\n    config: {value: '${item}'}\n"
        "  used:\n    block: log.write\n    depends_on: [made]\n    for_each: '${steps.made.items}'\n"
        "    config: {message: '${steps.made.output.0.valu} ${steps.made.item.output.valu}'}\n"
    )
    assert warned(text, catalog) == [("document.output_field_unknown", "steps.used.config", "'valu'")]


def test_a_report_template_reading_a_field_the_output_does_not_have_is_warned_on_once(catalog: Catalog) -> None:
    text = (
        f"steps:\n{PRODUCER}"
        "report:\n  template: |\n"
        "    {{ step.made.output.valu }} {{ step.made.output.valu.deeper }} {{ step['made'].output.value.count }}\n"
        "    {% for key, value in step.made.output.items() %}{{ key }}{% endfor %}\n"
    )
    assert warned(text, catalog) == [("document.output_field_unknown", "report.template", "'valu'")]


def test_nothing_is_judged_without_a_catalog() -> None:
    assert warned(reader("${steps.made.output.valu}"), None) == []


async def test_plan_carries_the_warning_and_still_applies(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    text = (
        "steps:\n  a: {block: test.echo, config: {value: hi}}\n"
        "  b: {block: test.echo, depends_on: [a], config: {value: '${steps.a.output.lenght}'}}\n"
    )
    async with session_scope(sessions) as session:
        applied = await apply_document(session, services, load_pipeline_text(HEAD + text), dry_run=True)
    assert applied.plan.action is PlanAction.CREATE
    assert [(issue.code, issue.params["fields"]) for issue in applied.plan.warnings] == [
        ("document.output_field_unknown", "length, value")
    ]
