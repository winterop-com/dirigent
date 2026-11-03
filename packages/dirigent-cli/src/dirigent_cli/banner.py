"""The banner a serving process's ``ready`` record renders as at a terminal.

``dg dev`` and ``dg server`` announce themselves with two ``process`` records, ``starting``
and ``ready``. A person reading a terminal gets one banner for the pair, drawn when the
instance answers: the mark, the version, where it answers, how to sign in, and what it
loaded. Everything the banner draws is a field of the ``ready`` record, so a stream read back
by ``dg format`` draws the same banner, and a pipe carries the same facts as records.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.table import Table
from rich.text import Text

from dirigent_cli import summaries
from dirigent_core.protocol import Record

#: The processes that announce themselves with a banner.
SERVING: Final = frozenset({"dev", "server"})

#: The brand's amber, darkened enough to read on a light terminal as well as a dark one.
BRAND: Final = "#d29a2a"

#: The mark: the logo's chain of steps under its arc, three lines tall.
MARK: Final = (" ╭──────•", " ●──●──●╮", "        ●")

#: The same mark for a terminal that cannot draw box characters.
ASCII_MARK: Final = (" .------.", " o--o--o.", "        o")

#: Below this width the mark is left off, and the words stand alone.
MARK_WIDTH: Final = 60

#: How a process is named on the banner.
CALLED: Final = {"dev": "dev instance", "server": "server"}


def announces(record: Record) -> bool:
    """Report whether this is a serving process's record of the kind the banner stands for.

    Only a record that carries the version does: an older stream's ``starting`` and
    ``ready`` keep their lines.
    """
    return record.get("kind") == "process" and record.get("process") in SERVING and "version" in record


def render(record: Record) -> RenderableType | None:
    """Render a serving process's ``starting`` or ``ready`` record, or None for any other record.

    ``ready`` is the banner. ``starting`` hands over a token it minted, which is shown once
    and never on the banner, and is otherwise silent: the banner says everything it said.
    """
    if not announces(record):
        return None
    if record.get("message") == "ready":
        return Banner(record)
    if record.get("message") == "starting":
        handed = summaries.beneath(record)
        return Group() if handed is None else handed
    return None


class Banner:
    """The banner itself, which measures the terminal it is printed to before it decides on the mark."""

    def __init__(self, record: Record) -> None:
        """Hold the record the banner is read off."""
        self.record = record

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Draw the head beside the mark where there is room, then the facts beneath it."""
        head = self._head()
        if options.max_width >= MARK_WIDTH:
            mark = MARK if options.encoding.lower().startswith("utf") else ASCII_MARK
            lockup = Table.grid(padding=(0, 3))
            lockup.add_column(no_wrap=True, style=BRAND)
            lockup.add_column()
            for drawn, said in zip(mark, head, strict=True):
                lockup.add_row(drawn, said)
            yield Text("")
            yield lockup
        else:
            yield Text("")
            yield from head
        yield Text("")
        yield self._facts()
        yield Text("")

    def _head(self) -> list[Text]:
        """Say what is running, that it is ready, and where to open it."""
        record = self.record
        called = CALLED.get(str(record.get("process")), str(record.get("process")))
        served = "UI and API" if record.get("ui") else "API only"
        first = Text.assemble(("dirigent", "bold"), " ", (str(record.get("version")), "dim"))
        second = Text.assemble(f"{called} ready", (f", {served}", "dim"))
        third = Text(str(record.get("ui") or record.get("api") or ""), style="bold")
        return [first, second, third]

    def _facts(self) -> Table:
        """Lay the rest out as labelled rows, each value whole and folded rather than cut."""
        record = self.record
        rows: list[tuple[str, Text]] = []
        for label, field in (("docs", "docs"), ("mcp", "mcp")):
            if record.get(field):
                rows.append((label, Text(str(record[field]))))
        if record.get("admin"):
            password = record.get("password")
            rows.append(
                (
                    "sign in",
                    Text.assemble(str(record["admin"]), (" / ", "dim"), str(password))
                    if password
                    else Text(str(record["admin"])),
                )
            )
        for label, field in (("state", "state"), ("log", "log")):
            if record.get(field):
                rows.append((label, Text(str(record[field]))))
        rows.append(("loaded", Text(_contributed(record))))
        packs = _packs(record)
        if packs is not None:
            rows.append(("packs", packs))
        table = Table.grid(padding=(0, 2))
        table.add_column(no_wrap=True, style="dim")
        table.add_column(overflow="fold")
        for label, value in rows:
            table.add_row(f"  {label}", value)
        return table


def _counted(count: object, one: str, many: str) -> str:
    """Spell a count with the noun it counts."""
    return f"{count} {one if count == 1 else many}"


def _contributed(record: Record) -> str:
    """Say how much the installed packs contribute."""
    return ", ".join(
        (
            _counted(record.get("blocks", 0), "block", "blocks"),
            _counted(record.get("connection_kinds", 0), "connection kind", "connection kinds"),
            _counted(record.get("source_kinds", 0), "source kind", "source kinds"),
        )
    )


def _packs(record: Record) -> Text | None:
    """Name every pack, saying a version once for those that share dirigent's own."""
    raw = record.get("packs")
    if not isinstance(raw, list) or not raw:
        return None
    packs = [cast("Mapping[str, Any]", one) for one in cast("Sequence[object]", raw) if isinstance(one, Mapping)]
    version = record.get("version")
    shared = [str(pack.get("name")) for pack in packs if pack.get("version") == version]
    others = [pack for pack in packs if pack.get("version") != version]
    text = Text()
    if shared:
        text.append(f"{len(shared)} at {version}", style="dim")
        text.append(": " + ", ".join(shared))
    for pack in others:
        if text:
            text.append("; " if shared and pack is others[0] else ", ")
        text.append(str(pack.get("name")))
        text.append(f" {pack.get('version') or 'unversioned'}", style="dim")
    return text
