"""Rendering text from a Jinja template: what degrades, what is refused, and what is capped."""

from datetime import UTC, datetime

import pytest

from dirigent_common.templating import RenderTooLarge, TemplateError, compile_template, render

CAP = 1024 * 1024


def test_an_undefined_name_renders_as_nothing() -> None:
    assert render("[{{ missing }}]", {}, max_bytes=CAP) == "[]"


def test_an_undefined_name_chains_through_attributes() -> None:
    assert render("[{{ a.b.c }}]", {}, max_bytes=CAP) == "[]"


def test_an_undefined_name_chains_through_items() -> None:
    assert render("[{{ a['b']['c'] }}]", {}, max_bytes=CAP) == "[]"


def test_arithmetic_on_an_undefined_name_renders_as_nothing() -> None:
    """An operator on an undefined carries the undefined through rather than failing."""
    assert render("[{{ missing + 1 }}][{{ 1 + missing }}][{{ -missing }}]", {}, max_bytes=CAP) == "[][][]"


def test_an_undefined_name_in_a_for_loop_renders_nothing() -> None:
    assert render("[{% for x in missing %}{{ x }}{% endfor %}]", {}, max_bytes=CAP) == "[]"


def test_an_undefined_name_is_falsy_and_empty() -> None:
    assert render("{% if missing %}yes{% else %}no{% endif %}/{{ missing | length }}", {}, max_bytes=CAP) == "no/0"


def test_the_duration_filter_reads_milliseconds() -> None:
    assert render("{{ took | duration }}", {"took": 90_000}, max_bytes=CAP) == "1m30s"


def test_the_duration_filter_renders_nothing_for_a_missing_value() -> None:
    assert render("[{{ took | duration }}][{{ missing | duration }}]", {"took": None}, max_bytes=CAP) == "[][]"


def test_the_bytes_filter_reads_a_count_of_bytes() -> None:
    assert render("{{ size | bytes }}", {"size": 16 * 1024}, max_bytes=CAP) == "16kb"


def test_the_bytes_filter_renders_nothing_for_a_missing_value() -> None:
    assert render("[{{ size | bytes }}][{{ missing | bytes }}]", {"size": None}, max_bytes=CAP) == "[][]"


def test_the_iso_filter_reads_a_datetime_and_a_string() -> None:
    when = datetime(2026, 9, 10, 8, 30, tzinfo=UTC)
    rendered = render("{{ a | iso }}|{{ b | iso }}", {"a": when, "b": "2026-09-10T08:30:00+00:00"}, max_bytes=CAP)
    assert rendered == "2026-09-10T08:30:00+00:00|2026-09-10T08:30:00+00:00"


def test_the_iso_filter_renders_nothing_for_a_missing_value() -> None:
    assert render("[{{ a | iso }}][{{ missing | iso }}]", {"a": None}, max_bytes=CAP) == "[][]"


def test_a_template_cannot_include_another() -> None:
    with pytest.raises(TemplateError):
        render('{% include "other" %}', {}, max_bytes=CAP)


def test_a_template_cannot_import_another() -> None:
    with pytest.raises(TemplateError):
        render('{% import "other" as other %}', {}, max_bytes=CAP)


def test_the_sandbox_refuses_reaching_into_an_object() -> None:
    with pytest.raises(TemplateError):
        render("{{ ''.__class__ }}", {}, max_bytes=CAP)


def test_the_sandbox_refuses_mutating_what_it_was_handed() -> None:
    with pytest.raises(TemplateError):
        render("{{ rows.append(1) }}", {"rows": []}, max_bytes=CAP)


def test_a_render_stops_at_the_cap() -> None:
    with pytest.raises(RenderTooLarge) as raised:
        render("{% for i in range(100000) %}xxxxxxxx{% endfor %}", {}, max_bytes=1024)
    assert raised.value.limit == 1024
    assert "1kb" in str(raised.value)


def test_a_syntax_error_names_its_line() -> None:
    with pytest.raises(TemplateError) as raised:
        compile_template("fine\nalso fine\n{% for %}\n")
    assert str(raised.value).startswith("line 3: ")


def test_a_block_tag_on_its_own_line_leaves_no_blank_line() -> None:
    """trim_blocks and lstrip_blocks, so a table's rows are not spaced out by its loop."""
    template = "head\n{% for row in rows %}\n{{ row }}\n{% endfor %}\ntail"
    assert render(template, {"rows": ["a", "b"]}, max_bytes=CAP) == "head\na\nb\ntail"


def test_a_trailing_newline_is_kept() -> None:
    assert render("done\n", {}, max_bytes=CAP) == "done\n"


def test_a_compiled_template_can_be_rendered_again() -> None:
    template = compile_template("{{ greeting }}")
    assert render(template, {"greeting": "hei"}, max_bytes=CAP) == "hei"
    assert render(template, {"greeting": "hallo"}, max_bytes=CAP) == "hallo"


def test_a_type_error_in_an_expression_is_reported_as_itself() -> None:
    with pytest.raises(TemplateError) as raised:
        render('{{ 1 + "a" }}', {}, max_bytes=1024)
    assert "include" not in str(raised.value)
