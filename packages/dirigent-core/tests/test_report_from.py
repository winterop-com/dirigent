"""``report: {from: <step>}``: a step's text as the run's report, and the checks a report gets before it runs."""

from typing import Any

import pytest

from dirigent_client.schemas import ValidationIssue
from dirigent_core.documents import DocumentError, load_text, validate_against_catalog
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.plugins import PluginHost, load_plugin_host
from dirigent_core.reportchecks import report_warnings
from test_engine import drain, start
from test_reporting import documents_of, only_document, warnings_of


@pytest.fixture
def host() -> PluginHost:
    """The installed blocks, ``report.render`` among them."""
    return load_plugin_host()


def document(report: str = "", *, template: str = "# {{ title }}", values: str = "{title: Weekly}") -> str:
    """A pipeline whose one step renders a page, and the report section given."""
    return (
        "format: dirigent/v1\ncode: paged\n"
        "params: {type: object, properties: {period: {type: string, default: '202601'}}}\n"
        f"steps:\n  summary:\n    block: report.render\n    config: {{template: '{template}', values: {values}}}\n"
        f"{report}"
    )


def pipeline(text: str) -> PipelineDefinition:
    """Load a pipeline document, insisting it is one."""
    loaded = load_text(text)
    assert isinstance(loaded, PipelineDefinition)
    return loaded


def codes(issues: list[ValidationIssue]) -> list[tuple[str, str]]:
    """Each issue by where it is and what it is."""
    return [(issue.location, issue.code) for issue in issues]


async def test_a_report_from_a_step_is_that_steps_text(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = pipeline(document("report: {from: summary}\n"))
    run = await start(sessions, services, definition)
    await drain(engine)

    stored = await only_document(sessions, run.id)
    assert stored.inline_value == {"text": "# Weekly"}
    assert stored.content_type == "text/markdown"


async def test_a_report_from_a_step_that_left_no_text_warns_and_stores_nothing(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = pipeline(
        "format: dirigent/v1\ncode: valued\nreport: {from: one}\n"
        "steps:\n  one: {block: value.const, config: {value: 1}}\n"
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    assert await documents_of(sessions, run.id) == []
    [warning] = await warnings_of(sessions, run.id)
    assert "left no `text`" in warning.fields["reason"]


def test_a_report_is_rendered_or_taken_from_a_step_never_both() -> None:
    with pytest.raises(DocumentError, match="not both"):
        load_text(document("report: {from: summary, template: '# x'}\n"))


def test_a_report_from_a_step_that_is_not_there_or_has_no_text_is_refused() -> None:
    catalog = load_plugin_host().catalog()
    missing = validate_against_catalog(pipeline(document("report: {from: sumary}\n")), catalog)
    assert codes(missing) == [("report.from", "document.report_no_such_step")]

    textless = pipeline(
        "format: dirigent/v1\ncode: valued\nreport: {from: one}\n"
        "steps:\n  one: {block: value.const, config: {value: 1}}\n"
    )
    assert codes(validate_against_catalog(textless, catalog)) == [("report.from", "document.report_step_no_text")]

    assert validate_against_catalog(pipeline(document("report: {from: summary}\n")), catalog) == []


def test_a_report_render_step_with_no_report_section_is_warned_about() -> None:
    [warning] = report_warnings(pipeline(document()))
    assert (warning.location, warning.code) == ("steps.summary", "document.report_render_unseen")
    assert "report: {from: summary}" in warning.message
    assert report_warnings(pipeline(document("report: {from: summary}\n"))) == []


def test_a_name_a_report_template_is_not_given_is_warned_about() -> None:
    text = document(
        "report:\n  template: '{{ step.sumary.outcome }} {{ params.perod }} {{ runn.id }} "
        "{{ step.summary.outcome }} {{ params.period }} {% for name, one in step.items() %}{{ one }}{% endfor %}'\n"
    )
    warned = {issue.params["name"] for issue in report_warnings(pipeline(text))}
    assert warned == {"step.sumary", "params.perod", "runn"}


def test_a_name_a_report_render_template_is_not_given_is_warned_about() -> None:
    text = document(template="# {{ title }} {{ titel }}")
    warned = [issue for issue in report_warnings(pipeline(text)) if issue.code == "document.template_name_unknown"]
    assert [(issue.location, issue.params["name"]) for issue in warned] == [("steps.summary.config.template", "titel")]
