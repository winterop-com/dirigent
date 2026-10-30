"""The end-of-run table's ladder, and the spelling the CLI writes in."""

import io
import json
from typing import Any, Literal

import pytest
from pydantic import BaseModel
from rich.console import Group, RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from typer.testing import CliRunner

from clisupport import asking_for_the_rendering
from dirigent_cli import stream
from dirigent_cli.context import CliState
from dirigent_cli.formatters import registry, rendered
from dirigent_cli.main import app, hoist_globals
from dirigent_cli.output import (
    Detail,
    TerminalConsole,
    build_fields,
    emit_json,
    emit_records,
    printable,
    prioritised,
    render_output,
)
from dirigent_cli.summaries import beneath
from dirigent_core.protocol import PROTOCOL_VERSION

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})


#: A value carrying what a terminal acts on: clears the screen, sets the clipboard, and a C1 CSI.
HOSTILE = "a\x1b[2Jb\x1b]52;c;aGk=\x07c\x9b31md\x00e\x7ff"

#: What a person should see of it: everything printable, including what followed each control.
SHOWN = "a[2Jb]52;c;aGk=c31mdef"


def terminal(*, color_system: Literal["truecolor"] | None = None) -> tuple[TerminalConsole, io.StringIO]:
    """A console writing as it does to a terminal, with its colour chosen rather than detected."""
    written = io.StringIO()
    console = TerminalConsole(file=written, force_terminal=True, no_color=False, color_system=color_system, width=200)
    return console, written


def test_a_control_character_in_a_value_does_not_reach_the_terminal() -> None:
    console, written = terminal()
    console.print(HOSTILE, highlight=False, soft_wrap=True, markup=False)
    assert written.getvalue() == f"{SHOWN}\n"


def test_a_table_cell_does_not_carry_a_control_character_to_the_terminal() -> None:
    """A table renders its cells apart from the line, so it is a path of its own."""
    console, written = terminal()
    table = Table()
    table.add_column("name")
    table.add_row(Text(HOSTILE))
    console.print(table)
    assert "\x1b" not in written.getvalue()
    assert SHOWN in written.getvalue()
    assert len({len(line) for line in written.getvalue().splitlines()}) == 1, "the table's columns no longer line up"


def test_the_colour_a_console_writes_itself_survives() -> None:
    """The value's escapes go and the console's stay, or the filter would have cost the colour."""
    console, written = terminal(color_system="truecolor")
    console.print(Text("value\x1b[2J", style="red"))
    assert "\x1b[31m" in written.getvalue()
    assert "\x1b[2J" not in written.getvalue()
    assert "value[2J" in written.getvalue()


def test_tab_and_newline_are_shown_as_a_person_wrote_them() -> None:
    assert printable("a\tb\nc") == "a\tb\nc"


def test_a_control_character_does_not_reach_the_log_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """The logging handler writes to its stream directly, with no console to filter it."""
    monkeypatch.setattr(stream, "_colouring", lambda: True)
    painted = stream.ansi("message", HOSTILE)
    assert "\x1b[2J" not in painted
    assert "\x9b" not in painted
    monkeypatch.setattr(stream, "_colouring", lambda: False)
    assert stream.ansi("message", HOSTILE) == SHOWN


def test_a_record_keeps_a_control_character_as_the_data_it_is(capsys: pytest.CaptureFixture[str]) -> None:
    """Only what is shown is filtered: a record says exactly what the server said."""
    emit_json({"message": HOSTILE})
    assert json.loads(capsys.readouterr().out) == {"message": HOSTILE}


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


def test_a_link_in_a_style_never_reaches_the_terminal() -> None:
    """A style's link is written as it stands, so controls in one would pass the text's filter."""
    console, written = terminal(color_system="truecolor")
    console.print(Text("click", style=Style(color="red", link="https://example.org/\x1bc")))
    assert "\x1b]8" not in written.getvalue()
    assert "\x1bc" not in written.getvalue()
    assert "\x1b[31m" in written.getvalue(), "the rest of the style stays"
    assert "click" in written.getvalue()


def test_markup_that_does_not_parse_is_shown_as_it_was_written() -> None:
    console, written = terminal()
    console.print("failed with [/nope]", highlight=False)
    assert written.getvalue() == "failed with [/nope]\n"


PAYLOAD = "[link=https://attacker.example/\x1bc]open me[/link] [/nope]"


def rendered_on_a_terminal(item: RenderableType) -> str:
    """Print what a formatter answered with on a colour terminal, the way a command prints it."""
    console, written = terminal(color_system="truecolor")
    for part in item.renderables if isinstance(item, Group) else [item]:
        console.print(part, soft_wrap=True, highlight=False)
    return written.getvalue()


def assert_shown_literally(drawn: str) -> None:
    """Assert a hostile value reached the screen as its own characters and nothing else."""
    assert "\x1b]8" not in drawn
    assert "\x1bc" not in drawn
    assert "[link=https://attacker.example/c]open me[/link]" in drawn
    assert "[/nope]" in drawn


def test_a_failed_runs_error_and_logs_are_shown_literally() -> None:
    drawn = rendered_on_a_terminal(
        beneath(
            {
                "kind": "run",
                "failures": [{"step": "s", "block": "b", "attempt": 1, "error": PAYLOAD, "logs": [PAYLOAD]}],
            }
        )
        or ""
    )
    assert drawn.count("[/nope]") == 2
    assert_shown_literally(drawn)


def test_a_watched_runs_step_error_is_shown_literally() -> None:
    drawn = rendered_on_a_terminal(
        beneath(
            {
                "kind": "run",
                "duration_ms": 1000,
                "steps": [{"step": "s", "block": "b", "status": "failed", "error": "[bold]held[/bold]"}],
            }
        )
        or ""
    )
    assert "[bold]held[/bold]" in drawn


def test_a_stored_line_that_is_not_a_record_is_shown_literally() -> None:
    formatter = registry()["console"]
    assert_shown_literally(rendered_on_a_terminal(next(iter(rendered([PAYLOAD], formatter)))))


def test_a_value_in_a_fields_table_is_shown_literally() -> None:
    drawn = rendered_on_a_terminal(build_fields("run", {"error": "[bold]held[/bold]"}))
    assert "[bold]held[/bold]" in drawn
