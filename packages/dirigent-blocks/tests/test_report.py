"""Tests for ``report.render``: text out of a template, and nothing saved anywhere."""

import pytest

from dirigent_blocks.report import ReportRenderConfig, ReportRenderOperator, ReportRenderOutput
from dirigent_common import TEMPLATE_MEDIA_TYPE
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block


async def test_the_template_renders_against_the_values(ctx: FakeContext) -> None:
    output = await call_block(
        ReportRenderOperator(),
        {
            "template": "# {{ day }}\n\n{{ rows | length }} rows, {{ total }} total.\n",
            "values": {"day": "2026-01-01", "rows": [1, 2, 3], "total": 42},
        },
        ctx,
    )
    assert isinstance(output, ReportRenderOutput)
    assert output.text == "# 2026-01-01\n\n3 rows, 42 total.\n"
    assert output.content_type == "text/markdown"


async def test_a_name_the_values_do_not_carry_renders_empty(ctx: FakeContext) -> None:
    output = await call_block(ReportRenderOperator(), {"template": "total: {{ missing }}.", "values": {}}, ctx)
    assert isinstance(output, ReportRenderOutput)
    assert output.text == "total: ."


async def test_the_step_says_how_many_bytes_the_text_is(ctx: FakeContext) -> None:
    output = await call_block(ReportRenderOperator(), {"template": "{{ name }}", "values": {"name": "Ærø"}}, ctx)
    assert isinstance(output, ReportRenderOutput)
    assert output.text_bytes == len(output.text.encode()) == 5, "counted in utf-8 bytes, not characters"


async def test_a_content_type_the_step_names_is_carried_to_the_sink(ctx: FakeContext) -> None:
    output = await call_block(ReportRenderOperator(), {"template": "a,b\n1,2\n", "content_type": "text/csv"}, ctx)
    assert isinstance(output, ReportRenderOutput)
    assert output.content_type == "text/csv"


def test_a_template_that_does_not_compile_is_refused_at_apply_with_its_line() -> None:
    refusals = ReportRenderOperator().check_config(ReportRenderConfig(template="ok\n{% for row in rows %}\n"))
    assert len(refusals) == 1
    assert refusals[0].startswith("line 2: Unexpected end of template")


async def test_more_text_than_the_cap_is_rejected_rather_than_retried(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure, match="exceeded") as raised:
        await call_block(
            ReportRenderOperator(),
            {"template": "{% for n in range(10000) %}a long line of report text\n{% endfor %}", "max_size": "1kb"},
            ctx,
        )
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_render_that_fails_is_rejected_rather_than_retried(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(ReportRenderOperator(), {"template": "{{ rows.sort() }}", "values": {"rows": []}}, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED


def test_the_schema_publishes_the_template_as_a_program() -> None:
    schema = ReportRenderConfig.model_json_schema(mode="serialization")
    assert schema["properties"]["template"]["contentMediaType"] == TEMPLATE_MEDIA_TYPE


def test_the_operator_declares_itself_idempotent() -> None:
    assert ReportRenderOperator.spec.idempotent is True
