"""The run's story, as protocol records encoded or rendered for this invocation.

One renderer serves all of it: the events a run emits here, and the same events read back
off a stored stream by ``dg format``. Verbosity decides which events are emitted; it
never changes the shape of a line.
"""

import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final, cast

from rich.markup import escape
from rich.style import Style

from dirigent_core.protocol import Format, Record, make, render

#: Supporting text is grey rather than rich's dim attribute, which many terminals render at
#: too little contrast to read on a dark background.
MUTED: Final = "grey58"

#: Colours a step is tracked by, assigned in document order and reused for every line it
#: writes. Colour is the fast path for the eye; the fixed column is what makes the stream
#: readable where there is no colour at all.
STEP_COLOURS: Final[tuple[str, ...]] = (
    "cyan",
    "magenta",
    "green",
    "yellow",
    "blue",
    "bright_cyan",
    "bright_magenta",
)

#: How each role of a console line is coloured. A level that is routine is left unmarked:
#: marking every line is the noise that marking exists to cut through.
ROLES: Final[Mapping[str, str]] = {
    "time": MUTED,
    "kind": MUTED,
    "key": "cyan",
    "step.": "blue",
    "level.info": "green",
    "level.warning": "bold yellow",
    "level.error": "bold red",
    "level.critical": "bold red",
    "level.debug": MUTED,
}

_step_colours: dict[str, str] = {}

_scratch: str | None = None


def track_steps(names: Iterable[str]) -> None:
    """Give each step a colour, in the order the document wrote them.

    Concurrent steps interleave, so a reader following one step down the page has only its
    name to go on; a stable colour makes that one glance instead of one search.
    """
    _step_colours.clear()
    for index, name in enumerate(names):
        _step_colours[name] = STEP_COLOURS[index % len(STEP_COLOURS)]


def use_scratch_prefix(prefix: str | None) -> None:
    """Name the prefix this run's URIs share, so the console rendering can leave it out.

    The prefix is stated once, on the run's own opening event, which is what makes the
    shorter form a spelling rather than a truncation: it round-trips.
    """
    global _scratch  # noqa: PLW0603 - one process-wide run context, set once per invocation
    _scratch = prefix.rstrip("/") if prefix else None


def paint(role: str, text: str) -> str:
    """Colour one part of a console line, escaping it so rich reads none of it as markup."""
    style = ROLES.get(role)
    if style is None and role.startswith("step."):
        # A stored stream has no tracked colours: dg format never saw the document.
        style = _step_colours.get(role.removeprefix("step.")) or ROLES.get("step.")
    safe = escape(text)
    return f"[{style}]{safe}[/]" if style else safe


def ansi(role: str, text: str) -> str:
    """Colour one part of a line for a stream that is written to rather than printed.

    The logging handler writes to its stream directly, so rich markup would arrive as the
    literal brackets that spell it. The roles and their colours are the ones the rendered
    stream uses, resolved to escape sequences here.
    """
    style = _style_for(role)
    if style is None or not _colouring():
        return text
    return Style.parse(style).render(text)


def _style_for(role: str) -> str | None:
    """Resolve one role to its style, tracked colours included."""
    style = ROLES.get(role)
    if style is None and role.startswith("step."):
        style = _step_colours.get(role.removeprefix("step.")) or ROLES.get("step.")
    return style


def _colouring() -> bool:
    """Report whether the diagnostic stream may be sent colour at all."""
    from dirigent_cli.output import error_console

    return not error_console.no_color and error_console.is_terminal


def relative(value: str) -> str:
    """Spell one URI relative to the prefix this run's URIs share, when it is under it."""
    return str(_relative(value))


def shorten(record: Record) -> Record:
    """Spell this run's own URIs relative to the prefix they all share.

    Rendering only, and only where the prefix was already stated: two URIs that differ must
    still read differently, so nothing else about a value is touched.
    """
    if _scratch is None:
        return record
    return {name: _relative(value) for name, value in record.items()}


def _relative(value: Any) -> Any:
    """Drop the shared scratch prefix from a URI, leaving every other value alone."""
    if isinstance(value, Mapping):
        nested = cast("Mapping[str, Any]", value)
        return {name: _relative(item) for name, item in nested.items()}
    if isinstance(value, str) and _scratch is not None and value.startswith(f"{_scratch}/"):
        return value[len(_scratch) + 1 :]
    return value


class Sink:
    """Where a run's story goes: stdout, in one output, for the whole invocation."""

    def __init__(self, output: Format = "console") -> None:
        """Fix the output this invocation writes."""
        self.output: Format = output

    @property
    def rendered(self) -> bool:
        """Report whether this invocation is being read by a person."""
        return self.output == "console"

    def write(self, record: Record) -> None:
        """Write one record and flush it, so a reader sees it as it happens.

        A rendered invocation goes through the same formatter ``dg format`` uses, so a run
        watched live and the same run read back off a file look the same.
        """
        if self.rendered:
            _emit(_formatter().render(record))
        else:
            sys.stdout.write(render(record, self.output) + "\n")
        sys.stdout.flush()

    def event(self, kind: str, /, **kwargs: Any) -> None:
        """Build one record and write it, stamped now when the event carries no moment."""
        kwargs.setdefault("at", datetime.now(UTC))
        self.write(make(kind, **kwargs))


def _emit(item: Any) -> None:
    """Print one rendered record, reaching the shared console late to avoid a cycle."""
    from dirigent_cli.output import emit_rendered

    emit_rendered(item)


def _formatter() -> Any:
    """Reach the console formatter late: it imports this module for the painting."""
    from dirigent_cli.formatters import Console

    return Console()
