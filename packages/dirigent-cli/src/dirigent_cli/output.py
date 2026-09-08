"""How the CLI prints: a rich table for a person, and exact JSON for a script.

``--json`` must emit the server's own response, not a rendering of the table.
"""

import json
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel
from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.table import Table

from dirigent_client.schemas.common import Problem
from dirigent_core.protocol import Format, Record, as_json, make

#: Whether the environment asked for no colour. Rich decides colour when a console is built,
#: so the answer is read once here and every console is built from it.
NO_COLOUR = "NO_COLOR" in os.environ


def build_console(*, stderr: bool = False) -> Console:
    """Build a console that writes no escape sequence at all where NO_COLOR asked for none.

    Rich's ``no_color`` drops colour and keeps every other attribute, so bold would still
    reach a terminal that asked for a plain stream; naming no colour system drops all of it.
    """
    return Console(stderr=stderr, no_color=NO_COLOUR, color_system=None if NO_COLOUR else "auto")


console = build_console()
error_console = build_console(stderr=True)


class Detail(StrEnum):
    """How much of a value the invocation asked to see."""

    SUMMARY = "summary"
    """A container's shape rather than its content: the default view."""

    VALUES = "values"
    """The values, each scalar cut short and each collection shown to a small depth."""

    FULL = "full"
    """The whole value, pretty-printed and untruncated."""


#: The verbosity count at which ``-vv`` means the same thing as ``-d``.
FULL_VERBOSITY = 2

_output: "Format" = "json"

_detail: Detail = Detail.SUMMARY


def configure(*, output: Format = "json", detail: Detail = Detail.SUMMARY) -> None:
    """Fix the spelling this invocation writes in, before any command runs.

    Only the console rendering is decorated. Under ``json`` nothing may reach stdout that is
    not one record per line, so the rich consoles are muted here rather than every call site
    being asked to remember.

    The detail level is fixed here too, because a formatter renders a record without being
    handed the invocation that asked for it.
    """
    global _output, _detail  # noqa: PLW0603 - one process-wide output mode, set once per invocation
    _output = output
    _detail = detail
    from dirigent_cli.stream import use_scratch_prefix

    use_scratch_prefix(None)
    console.quiet = output != "console"
    console.no_color = NO_COLOUR or output != "console"
    error_console.quiet = output != "console"


def json_mode() -> bool:
    """Report whether this invocation speaks a machine spelling rather than a rendered one."""
    return _output != "console"


def output_mode() -> "Format":
    """Report which spelling this invocation writes in."""
    return _output


def detail_mode() -> Detail:
    """Report how much of a value this invocation asked to see."""
    return _detail


def emit_rendered(item: "RenderableType") -> None:
    """Print one rendered record, live from a run or read back by ``dg format``.

    A line is soft-wrapped, so a wide value pushes the line out rather than being folded or
    cut to the window it happened to be read in. A table measures itself against the
    terminal instead, so a record that renders as both is printed a piece at a time.
    """
    for part in item.renderables if isinstance(item, Group) else [item]:
        if isinstance(part, str):
            console.print(part, soft_wrap=True, highlight=False)
        else:
            console.print(part)


STATUS_STYLES: Mapping[str, str] = {
    "succeeded": "green",
    "running": "cyan",
    "queued": "blue",
    "pending": "dim",
    "waiting": "cyan",
    "completed_with_errors": "yellow",
    "failed": "red",
    "cancelled": "magenta",
    "skipped": "dim",
    "create": "green",
    "update": "yellow",
    "unchanged": "dim",
    "invalid": "red",
    "healthy": "green",
    "unhealthy": "red",
}


def emit_json(payload: object) -> None:
    """Print a response exactly as the server sent it, on one line, for a script to parse.

    Writes to plain stdout, not through rich: rich wraps to the terminal width, and a
    JSON document with a newline inserted mid-token is neither JSON nor NDJSON.
    """
    sys.stdout.write(json.dumps(payload, default=str, separators=(",", ":")) + "\n")


def emit_record(kind: str, /, **fields: Any) -> None:
    """Write one record of a command's answer and flush it."""
    sys.stdout.write(as_json(make(kind, at=datetime.now(UTC), **fields)) + "\n")
    sys.stdout.flush()


def emit_one(kind: str, row: BaseModel) -> None:
    """Write one read as the record its listing would carry it in."""
    emit_record(kind, fields=row.model_dump(mode="json"))


def emit_records(kind: str, rows: Iterable[BaseModel]) -> None:
    """Write a listing as NDJSON: one record per row, each carrying the row whole.

    A listing is a record stream like every other command's output, so ``dg pipeline list``
    and a run's events are read the same way: one object per line, each naming its kind.

    The row rides under ``fields``, which the console line spreads under the row's own names:
    a row of its own has a ``kind`` -- a schedule is cron or interval, a block is an operator
    or a sensor -- and that is not the record kind a reader dispatches on.
    """
    for row in rows:
        emit_record(kind, fields=row.model_dump(mode="json"))


def emit_event(event: BaseModel) -> None:
    """Print one NDJSON record and flush it, so a reader sees it as it happens.

    One object per line and no indentation: a record split across lines is not NDJSON.
    """
    sys.stdout.write(json.dumps(event.model_dump(mode="json"), default=str, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def problem_record(problem: Problem) -> "Record":
    """Build the record one refusal is written as, carrying the problem body it came from.

    The problem's own fields ride along, so a reader that wants the API's shape still has
    all of it.
    """
    body = problem.model_dump(mode="json")
    # The detail is the message, so it is not also a field: a line does not say one thing twice.
    detail = body.pop("detail", None)
    return make(
        "error",
        at=datetime.now(UTC),
        level="error",
        message=str(detail or body.get("title") or "the command was refused"),
        **body,
    )


def emit_refusal(problem: Problem) -> None:
    """Write one refusal as a record, carrying the problem body it was built from.

    A refusal is written to the same stream as everything else a command says, so it is a
    record like everything else: ``dg runs list | dg format`` renders why it failed rather
    than passing a line of JSON through as somebody else's text.
    """
    sys.stdout.write(as_json(problem_record(problem)) + "\n")
    sys.stdout.flush()


def emit_problem(detail_text: str, *, status: int = 1, title: str = "Error", problems: Sequence[str] = ()) -> None:
    """Print a refusal the CLI itself decided on, in the shape the server's own would take."""
    emit_refusal(Problem(status=status, title=title, detail=detail_text, problems=list(problems)))


def emit_fact(kind: str, /, **fields: Any) -> None:
    """Write one record in the spelling this invocation asked for: NDJSON, or rendered.

    A command states a fact once, as a record; whether that reaches the reader as a line of
    JSON or as the formatter's drawing of it is the invocation's business and not the
    command's.
    """
    from dirigent_cli.stream import Sink

    Sink(_output).event(kind, **fields)


def write_refusal(problem: Problem) -> None:
    """Write one refusal as a record, rendered where the invocation asked for a rendering."""
    from dirigent_cli.stream import Sink

    Sink(_output).write(problem_record(problem))


def refuse(detail_text: str, *, status: int = 1, title: str = "Error", problems: Sequence[str] = ()) -> None:
    """Write a refusal the CLI decided on as a record, rendered where one was asked for."""
    write_refusal(Problem(status=status, title=title, detail=detail_text, problems=list(problems)))


#: How long one field's value may be before the summary *table* renders its shape instead.
#: The stream never uses it: a line carries whole values or it is not a protocol.
FIELD_WIDTH = 40

#: How many elements of a collection ``-v`` shows before saying how many are left.
VALUE_ELEMENTS = 5

#: How far into a nested value ``-v`` descends before falling back to its shape.
VALUE_DEPTH = 2

#: Output fields worth nothing to a reader: the block produced no value there.
EMPTY: tuple[object, ...] = (None, "", [], {})

#: What separates two rendered fields on one line. Two spaces, so a parser splitting on
#: whitespace and a person reading columns both get what they came for.
SEPARATOR = "  "

#: Supporting text is grey rather than rich's dim attribute, which many terminals render at
#: too little contrast to read on a dark background.
MUTED = "grey58"

#: A leading ``scheme://``, which is what makes a string a URI rather than prose.
URI_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

#: A value holding any of these reads as more than one token unless it is quoted.
_NEEDS_QUOTES = re.compile(r'[\s"\\]')


def is_uri(text: str) -> bool:
    """Report whether a value is a URI, and so has a prefix worth leaving out."""
    return URI_SCHEME.match(text) is not None


def render_uri(uri: str) -> str:
    """Render a URI the way the stream spells it: relative to the run's shared prefix."""
    from dirigent_cli.stream import relative

    return relative(uri)


def stream_line(text: str, *, level: Detail = Detail.SUMMARY) -> None:
    """Print one line of a run's stream, whole.

    A line wider than the terminal wraps, and that is the right trade: a stream that cuts at
    the terminal's width is a stream whose content depends on the window it was read in, and
    a value cut in half is a value nobody can parse or paste.
    """
    console.print(text, highlight=False, soft_wrap=True)


def muted(text: str) -> str:
    """Render supporting text in a grey that stays legible where rich's dim does not."""
    return f"[{MUTED}]{text}[/]"


def _styled_part(part: str) -> str:
    """Colour one part: its name muted, its value at full contrast."""
    name, separator, value = part.partition("=")
    if not separator:
        return escape(part)
    return muted(escape(name) + separator) + escape(value)


def _compact(value: object, depth: int) -> str:
    """Render one value with its content visible but bounded: short scalars, shallow collections."""
    if isinstance(value, dict):
        entries = list(cast("dict[str, Any]", value).items())
        if depth <= 0 or not entries:
            return f"{{{len(entries)} keys}}"
        shown = ", ".join(f"{name}: {_compact(item, depth - 1)}" for name, item in entries[:VALUE_ELEMENTS])
        return "{" + shown + _more(len(entries)) + "}"
    if isinstance(value, list):
        elements = cast("list[object]", value)
        if depth <= 0 or not elements:
            return f"[{len(elements)} items]"
        shown = ", ".join(_compact(item, depth - 1) for item in elements[:VALUE_ELEMENTS])
        return "[" + shown + _more(len(elements)) + "]"
    if isinstance(value, str):
        return render_uri(value) if is_uri(value) else value
    return _shape(value)


def _more(count: int) -> str:
    """Say how many elements a bounded rendering left out, or nothing when it left out none."""
    return f", +{count - VALUE_ELEMENTS} more" if count > VALUE_ELEMENTS else ""


def summarise(output: Mapping[str, Any]) -> str:
    """Render a step's output as one readable line.

    A scalar is shown whole; a container is shown as its shape, because one response's
    headers would otherwise fill the line and say nothing. A field the block left empty is
    dropped, since "it produced nothing there" is not what a reader is looking for.
    """
    parts = [f"{name}={_shape(value)}" for name, value in output.items() if value not in EMPTY]
    return SEPARATOR.join(_styled_part(part) for part in parts) or "-"


def render_output(
    output: Mapping[str, Any] | None,
    level: Detail = Detail.SUMMARY,
    *,
    uri: str | None = None,
    size_bytes: int | None = None,
) -> str:
    """Render a step's output or input at the level the invocation asked for.

    An output too large to inline was written to storage, so the default and ``-v`` views
    name the artifact rather than showing a value the reader cannot tell apart from an
    inlined one; ``-d`` prints what was stored, which the help says and a table need not.
    """
    if uri is not None:
        note = f"{muted('artifact')} {escape(render_uri(uri))}{_size(size_bytes)}"
        if level is not Detail.FULL or not output:
            return note
        return f"{note}\n{_rendered(output, level)}"
    if not output:
        return "-"
    return _rendered(output, level)


def _rendered(output: Mapping[str, Any], level: Detail) -> str:
    """Render an inlined value: its shape, its bounded values, or the whole of it."""
    if level is Detail.FULL:
        return escape(json.dumps(dict(output), indent=2, default=str))
    if level is Detail.VALUES:
        parts = [f"{name}={_compact(value, VALUE_DEPTH)}" for name, value in output.items() if value not in EMPTY]
        return SEPARATOR.join(_styled_part(part) for part in parts) or "-"
    return summarise(output)


def _size(size_bytes: int | None) -> str:
    """Render an artifact's size, or nothing when it was not recorded."""
    if size_bytes is None:
        return ""
    if size_bytes < 1024:  # noqa: PLR2004 - the byte/kilobyte boundary
        return " " + muted(f"({size_bytes} B)")
    return " " + muted(f"({size_bytes / 1024:.1f} kB)")


def _shape(value: object) -> str:
    """Render one output field: the value when it is small, its shape when it is not."""
    if isinstance(value, dict):
        return f"{{{len(cast('dict[str, Any]', value))} keys}}"
    if isinstance(value, list):
        return f"[{len(cast('list[object]', value))} items]"
    if isinstance(value, str):
        if is_uri(value):
            return render_uri(value)
        return value if len(value) <= FIELD_WIDTH else f"<{len(value)} chars>"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return json.dumps(value, default=str)


def labelled(step: str, item: object) -> str:
    """Name a step, with the fan-out element it is working on when there is one.

    Escaped, because rich reads square brackets as markup and would eat the label.
    """
    return escape(f"{step}[{item}]") if item is not None else escape(step)


def styled(value: object) -> str:
    """Render a value, colouring the ones that are a status."""
    text = "-" if value is None else str(value)
    style = STATUS_STYLES.get(text)
    return f"[{style}]{text}[/]" if style else text


STATUS_WIDTH = 15

#: How wide the step column is, so names line up down the page rather than floating with the
#: message before them.
STEP_WIDTH = 22

#: Colours a step is tracked by, assigned in document order and reused for every line it
#: writes. Colour is the fast path for the eye; the column is what makes the stream readable
#: where there is no colour at all.
STEP_COLOURS: tuple[str, ...] = ("cyan", "magenta", "green", "yellow", "blue", "bright_cyan", "bright_magenta")

#: What a level is called in a line, and how wide that column is. One word each, so the
#: column is a token and not a sentence.
LEVEL_NAMES: Mapping[str, str] = {"warning": "warn", "critical": "error"}

LEVEL_WIDTH = 5

#: Colour is decoration: it says the same thing the level word already says.
LEVEL_COLOURS: Mapping[str, str] = {"warning": "bold yellow", "error": "bold red", "critical": "bold red"}

#: How wide the event column is, and which event is worth a weight of its own.
EVENT_WIDTH = 6

EVENT_STYLE: Mapping[str, str] = {"step": "[bold]"}

#: What stands in an empty column, so a line never has fewer tokens than the grammar says.
NOTHING = "-"

_step_colours: dict[str, str] = {}


def flagged(warnings: int) -> str:
    """Mark a step that logged something worth reading, whatever it settled as.

    Beside the name rather than in the outcome column: the outcome is the terminal status
    and stays it, but a succeeded step that warned twice is the moment to decide to look.
    """
    if warnings <= 0:
        return ""
    return f"  [bold yellow]{warnings} warn[/]"


def prioritised(priority: object) -> str:
    """Mark a run the claim does not treat like every other one.

    Almost every run is ``normal``, so a column of the word would say nothing; the mark is
    drawn only where the answer is not the default.
    """
    match str(priority):
        case "high":
            return "  [bold red]![/]"
        case "low":
            return f"  {muted('low')}"
        case _:
            return ""


def status_cell(value: object, width: int = STATUS_WIDTH) -> str:
    """Render a status padded to a fixed width, then coloured.

    Pad before colouring: rich markup counts as characters, so padding the marked-up
    string makes every colour a different column width.
    """
    text = "-" if value is None else str(value)
    style = STATUS_STYLES.get(text)
    padded = f"{text:<{width}}"
    return f"[{style}]{padded}[/]" if style else padded


def render_bool(value: object) -> str:
    """Render a boolean as a word rather than as Python's spelling of it."""
    if value is None:
        return "-"
    return "[green]yes[/]" if value else "[dim]no[/]"


def moment(value: object) -> str:
    """Render a timestamp compactly, in the local time an operator is reading it in."""
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def elapsed(value: object) -> str:
    """Render a duration in milliseconds the way a person reads it."""
    if value is None:
        return "-"
    seconds = float(str(value)) / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m{int(rest)}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h{int(minutes)}m"


def build_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> RenderableType:
    """Build one rich table, or the quiet line that stands in for an empty one."""
    built = Table(title=title, show_header=True, header_style="bold", title_justify="left")
    for column in columns:
        built.add_column(column)
    count = 0
    for row in rows:
        built.add_row(*row)
        count += 1
    return built if count else f"[dim]{title}: nothing to show.[/]"


def table(title: str, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Print one rich table, or a quiet line when there is nothing in it."""
    console.print(build_table(title, columns, rows))


def build_fields(title: str, values: Mapping[str, Any]) -> RenderableType:
    """Build one record as a two-column table."""
    built = Table(title=title, show_header=False, box=None, title_justify="left", padding=(0, 2, 0, 0))
    built.add_column(style="bold")
    built.add_column()
    for name, value in values.items():
        built.add_row(name, styled(value))
    return built


def fields(title: str, values: Mapping[str, Any]) -> None:
    """Print one record as a two-column table."""
    console.print(build_fields(title, values))


def age(value: object) -> str:
    """Render how long ago something happened."""
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return elapsed((datetime.now(UTC) - parsed).total_seconds() * 1000) + " ago"
