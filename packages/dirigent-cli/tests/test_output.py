"""The end-of-run table's ladder, and the spelling the CLI writes in."""

import json
from typing import Any

import pytest
from pydantic import BaseModel
from rich.text import Text
from typer.testing import CliRunner

from clisupport import asking_for_the_rendering
from dirigent_cli.context import CliState
from dirigent_cli.main import app, hoist_globals
from dirigent_cli.output import Detail, emit_records, prioritised, render_output
from dirigent_core.protocol import PROTOCOL_VERSION

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})


class Row(BaseModel):
    """A listing row with a ``kind`` of its own, which is what a record's own kind collides with."""

    code: str
    kind: str


LONG_URL = "https://example.org/" + "x" * 120

OUTPUT: dict[str, Any] = {
    "status": 200,
    "headers": {f"header-{index}": f"value-{index}" for index in range(12)},
    "json_body": {"args": {"dataset": "temperature"}, "url": LONG_URL},
    "text": None,
}


def plain(rendered: str) -> str:
    """The text a terminal shows, with the colour markup resolved away."""
    return Text.from_markup(rendered).plain


def invoke(*argv: str) -> Any:
    """Run one command and return its result, hoisting global options as the entry point does."""
    return runner.invoke(app, asking_for_the_rendering(hoist_globals(list(argv))))


def test_the_default_table_view_shows_a_containers_shape_rather_than_its_content() -> None:
    """The end-of-run table is a summary of what the stream already said in full."""
    rendered = plain(render_output(OUTPUT, Detail.SUMMARY))
    assert "status=200" in rendered
    assert "headers={12 keys}" in rendered
    assert "example.org" not in rendered
    assert "text" not in rendered, "a field the block left empty says nothing"


def test_one_v_shows_the_values_bounded_by_element_count() -> None:
    rendered = plain(render_output(OUTPUT, Detail.VALUES))
    assert "header-0: value-0" in rendered, "-v is the level that shows values"
    assert "+7 more" in rendered, "a collection is shown to an element count, and says what it left"
    assert "dataset: temperature" in rendered, "-v descends a level into a nested value"
    assert LONG_URL in rendered, "and a scalar is not cut"


def test_debug_shows_the_whole_value_pretty_printed() -> None:
    rendered = render_output(OUTPUT, Detail.FULL)
    assert LONG_URL in rendered, "-d is asked for the actual values"
    assert '"status": 200' in rendered
    assert "{12 keys}" not in rendered


def test_a_spilled_output_names_its_artifact_rather_than_pretending_to_show_it() -> None:
    rendered = plain(render_output(OUTPUT, Detail.SUMMARY, uri="file:///tmp/outputs/a.json", size_bytes=24576))
    assert "file:///tmp/outputs/a.json" in rendered
    assert "24.0 kB" in rendered
    assert rendered.count("\n") == 0, "a cell says what the artifact is and nothing else"


def test_an_empty_output_renders_as_a_dash() -> None:
    assert render_output(None, Detail.FULL) == "-"


def test_the_flags_resolve_onto_the_ladder() -> None:
    assert CliState().detail is Detail.SUMMARY
    assert CliState(verbose=1).detail is Detail.VALUES
    assert CliState(verbose=2).detail is Detail.FULL
    assert CliState(debug=True).detail is Detail.FULL
    assert CliState(debug_all=True).detail is Detail.FULL


def test_the_output_does_not_decide_how_much_is_emitted() -> None:
    """The same flags produce the same records, whether they are written or rendered.

    That is what makes ``dg run | dg format`` the same thing as ``dg run -o console``, and
    it is why NDJSON could become the default without ``-v`` quietly changing meaning.
    """
    for output in ("json", "console"):
        assert CliState(output=output).detail is Detail.SUMMARY
        assert CliState(output=output, verbose=1).detail is Detail.VALUES


def test_a_machine_spelling_is_not_a_rendering() -> None:
    assert CliState(output="console").json_output is False
    assert CliState(output="json").json_output is True


def test_a_command_that_would_prompt_fails_with_a_problem_object_under_json() -> None:
    """A pipe cannot answer a prompt, so the refusal has to be the answer."""
    result = invoke("--json", "auth", "login")
    assert result.exit_code == 1
    problem = json.loads(result.stdout)
    assert problem["kind"] == "error"
    assert "username" in problem["message"], "the detail is the record's message"
    assert problem["level"] == "error"
    assert problem["status"] == 1
    assert result.stdout.count("\n") == 1, "one refusal, one JSON object"


def test_the_ordinary_priority_is_not_drawn_at_all() -> None:
    """A column that is almost always the same word is a column saying nothing."""
    assert prioritised("normal") == ""
    assert prioritised(None) == ""


def test_the_two_priorities_that_are_not_ordinary_are_marked() -> None:
    """The mark is read with the colour resolved away, because a pipe has no colour."""
    assert plain(prioritised("high")).strip() == "!"
    assert plain(prioritised("low")).strip() == "low"


def test_a_listing_is_written_as_one_record_per_row(capsys: pytest.CaptureFixture[str]) -> None:
    """A row keeps its own fields, ``kind`` included, under the record's ``fields``."""
    emit_records("schedule", [Row(code="nightly", kind="cron"), Row(code="hourly", kind="interval")])

    written = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]

    assert [record["kind"] for record in written] == ["schedule", "schedule"]
    assert [record["fields"] for record in written] == [
        {"code": "nightly", "kind": "cron"},
        {"code": "hourly", "kind": "interval"},
    ]
    assert all(record["v"] == PROTOCOL_VERSION for record in written)
