"""Rendering text from a Jinja template: what degrades, what is refused, and what is capped."""

import asyncio
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from dirigent_common import templating
from dirigent_common.templating import (
    RenderTooLarge,
    TemplateError,
    TemplateTooCostly,
    compile_template,
    render,
    render_off_loop,
)

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
    assert not isinstance(raised.value, TemplateError), "the cap is its own answer, not a broken template"


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


def test_an_arithmetic_error_while_rendering_is_a_template_error() -> None:
    """A template that compiles can still raise, and a raise here is never the caller's to catch."""
    with pytest.raises(TemplateError) as raised:
        render("{{ 1 / 0 }}", {}, max_bytes=CAP)
    assert str(raised.value) == "division by zero"


def test_a_context_value_that_raises_when_it_is_read_is_a_template_error() -> None:
    class Awkward:
        @property
        def label(self) -> str:
            raise RuntimeError("this fact is not there")

    with pytest.raises(TemplateError) as raised:
        render("{{ thing.label }}", {"thing": Awkward()}, max_bytes=CAP)
    assert str(raised.value) == "this fact is not there"


def test_a_test_that_is_only_named_at_render_is_a_template_error() -> None:
    """An unknown filter is caught at compile; an unknown test inside select is not."""
    with pytest.raises(TemplateError) as raised:
        render("{{ rows | select('nope') | list }}", {"rows": [1]}, max_bytes=CAP)
    assert "nope" in str(raised.value)


def test_a_macro_that_recurses_forever_is_a_template_error() -> None:
    with pytest.raises(TemplateError) as raised:
        render("{% macro tail(n) %}{{ tail(n + 1) }}{% endmacro %}{{ tail(0) }}", {}, max_bytes=CAP)
    assert "maximum recursion depth exceeded" in str(raised.value)


def test_a_list_or_object_prints_as_compact_json_not_a_repr() -> None:
    context = {"rows": [{"value": "42", "ok": True}], "one": {"a": None}}
    assert render("{{ rows }} {{ one }}", context, max_bytes=CAP) == '[{"value":"42","ok":true}] {"a":null}'


def test_a_boolean_and_null_print_as_json_reads_them() -> None:
    context = {"yes": True, "no": False, "nothing": None}
    assert render("{{ yes }} {{ no }} [{{ nothing }}]", context, max_bytes=CAP) == "true false []"


def test_the_tojson_filter_still_indents_on_request() -> None:
    assert render("{{ one | tojson(indent=2) }}", {"one": {"a": 1}}, max_bytes=CAP) == '{\n  "a": 1\n}'


# -- the render budget -------------------------------------------------------------

#: The time a render that must stop itself is given in these tests.
BRIEF = timedelta(seconds=2)

#: How much longer than its time a bounded render may take before the bound counts as missing.
SLACK = 2.0


def refused(source: str, context: dict[str, object] | None = None) -> TemplateTooCostly:
    """Render a template that must stop itself, and hand back the refusal once it has."""
    start = time.monotonic()
    with pytest.raises(TemplateTooCostly) as raised:
        render(source, context or {}, max_bytes=16, within=BRIEF)
    assert time.monotonic() - start < BRIEF.total_seconds() + SLACK
    return raised.value


def test_nested_loops_that_print_nothing_stop_at_the_step_budget() -> None:
    """Three nested full ranges are 10^15 passes and never reach the output cap."""
    refused(
        "{% for a in range(100000) %}{% for b in range(100000) %}{% for c in range(100000) %}"
        "{% endfor %}{% endfor %}{% endfor %}"
    )


def test_a_loop_over_a_context_value_counts_its_passes_too() -> None:
    refused("{% for a in rows %}{% for b in rows %}{% endfor %}{% endfor %}", {"rows": list(range(2000))})


def test_a_macro_that_branches_stops_at_the_time_budget() -> None:
    refused("{% macro f(n) %}{% if n %}{{ f(n - 1) }}{{ f(n - 1) }}{% endif %}{% endmacro %}{{ f(60) }}")


def test_a_huge_power_is_refused_before_it_is_computed() -> None:
    refused("{{ 3 ** 30000000 }}")


def test_a_huge_product_is_refused_before_it_is_computed() -> None:
    refused("{% set n = 2 ** 4000 %}{{ n * n }}")


@pytest.mark.parametrize(
    "source",
    [
        "{{ 'x' * 1000000000 }}",
        "{{ ['y' * 1000000] * 1000 }}",
        "{% set ns = namespace(s='x') %}{% for i in range(60) %}{% set ns.s = ns.s ~ ns.s %}{% endfor %}",
        "{% set ns = namespace(s='x') %}{% for i in range(60) %}{% set ns.s = ns.s + ns.s %}{% endfor %}",
        "{{ 'a' | center(1000000000) }}",
        "{{ 'a'.ljust(1000000000) }}",
        "{{ '{:>999999999}'.format(1) }}",
        "{{ '%999999999d' % 1 }}",
        "{{ '%*d' % (5, 1) }}",
        "{{ ('x' * 1000) | replace('', 'y' * 2000) }}",
        "{{ range(100000) | join('y' * 1000) }}",
        "{{ ('x\\n' * 100000) | indent('y' * 100) }}",
        "{{ [[1]] | sum(start=[]) }}",
    ],
)
def test_a_value_past_the_value_cap_is_refused_before_it_is_built(source: str) -> None:
    refused(source)


def test_a_render_stops_when_its_caller_stops_waiting() -> None:
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(TemplateTooCostly):
        render("{% for a in range(10) %}{% endfor %}", {}, max_bytes=CAP, stopped=stopped)


async def test_a_render_off_the_loop_stops_once_its_caller_is_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thread a render runs on cannot be killed, so the render ends itself at its next step."""
    monkeypatch.setattr(templating, "RENDER_STEPS", 10**12)
    passes = 0

    def counted() -> Iterator[int]:
        nonlocal passes
        while True:
            passes += 1
            yield passes

    rendering = asyncio.create_task(
        render_off_loop(
            "{% for a in endless %}{% endfor %}", {"endless": counted()}, max_bytes=CAP, within=timedelta(hours=1)
        )
    )
    await asyncio.sleep(0.2)
    rendering.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rendering
    await asyncio.sleep(0.2)
    settled = passes
    await asyncio.sleep(0.3)
    assert passes == settled, "the render went on after its caller stopped waiting"


async def test_the_event_loop_runs_on_while_a_template_renders_off_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(templating, "RENDER_STEPS", 10**12)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    ticking = asyncio.create_task(ticker())
    with pytest.raises(TemplateTooCostly):
        await render_off_loop(
            "{% for a in range(100000) %}{% for b in range(100000) %}{% endfor %}{% endfor %}",
            {},
            max_bytes=CAP,
            within=timedelta(seconds=1),
        )
    ticking.cancel()
    assert ticks > 2, "a loop held for the whole render ticks once, before the render starts"


@pytest.mark.parametrize(
    "source",
    ["{{ 3 ** 30000000 }}", "{{ 3 ** 3e6 }}", "{{ 'x' * 1000000000 }}", "{{ 'a' | center(1000000000) }}"],
)
def test_compiling_a_template_evaluates_none_of_its_expressions(source: str) -> None:
    """A constant expression is computed at render, under the budget, never folded at compile."""
    start = time.monotonic()
    compile_template(source)
    assert time.monotonic() - start < 0.5


def test_an_honest_template_renders_as_jinja_would() -> None:
    context = {"rows": ["a", "b"], "one": {"k": [1]}}
    source = (
        "{{ rows | join(', ') }}|{{ 2 ** 10 }}|{{ 'a' ~ 'b' }}|{{ '%3d' % 7 }}|{{ '{:>3}'.format(1) }}|"
        "{% for row in rows %}{{ loop.index }}{{ row | upper }}{{ loop.length }}{% endfor %}|"
        "{{ rows | map('upper') | join }}|{{ one | tojson }}|{{ [1, 2] | sum }}|{{ 'ab' | center(4) }}|"
        "{% filter upper %}low{% endfilter %}|{{ 'x' * 3 }}|{{ [1] + [2] }}"
    )
    assert render(source, context, max_bytes=CAP) == 'a, b|1024|ab|  7|  1|1A22B2|AB|{"k": [1]}|3| ab |LOW|xxx|[1,2]'
