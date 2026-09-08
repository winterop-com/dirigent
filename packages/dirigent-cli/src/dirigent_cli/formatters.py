"""The formatters ``dg format`` dispatches on: a name, a version, and one render method.

The registry holds the built-ins and whatever a plugin in the ``dirigent.formatters`` entry
point group contributes, so a third party ships a formatter without touching the CLI. A
formatter renders a record kind it has never heard of rather than failing, because a record
from a newer dirigent or from a plugin's own event still has to read.
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Final, cast

from pluginkit import PluginManager
from rich.console import Group, RenderableType

from dirigent_cli import summaries
from dirigent_cli.stream import paint, shorten, use_scratch_prefix
from dirigent_common import Formatter
from dirigent_core.protocol import Record, console, parse
from dirigent_plugin import PROJECT_NAME, markers

#: Where a third party registers a formatter of its own.
ENTRY_POINT_GROUP: Final = "dirigent.formatters"

#: The formatter an omitted positional means.
DEFAULT: Final = "console"

#: The owner recorded for the built-in names, which a plugin may not claim either.
BUILT_IN: Final = "dirigent-cli"


class DuplicateFormatter(Exception):
    """Two plugins claimed the same formatter name."""

    def __init__(self, name: str, first: str, second: str) -> None:
        """Name the formatter and both plugins."""
        super().__init__(
            f"formatter {name!r} is contributed by both {first!r} and {second!r}, and a formatter name is "
            f"what `dg format` dispatches on, so one of the two packages must be uninstalled or renamed."
        )
        self.name = name
        self.plugins = (first, second)


class Console:
    """The fixed-grammar rendering: padded columns, then every field the record carries.

    Columns are padded and never cut, so a value wider than its column pushes the line out
    rather than losing the half that says which one it is.
    """

    name = "console"
    version = "1"

    def render(self, record: Record) -> RenderableType:
        """Render one record as a padded line, plus whatever its kind renders beneath."""
        return _with_summary(record, console(shorten(summaries.line(record)), paint=paint))


class Compact:
    """The same grammar with no column padding.

    Every field still goes out whole: this trades the columns a wide terminal can afford,
    not any of the record's content.
    """

    name = "compact"
    version = "1"

    def render(self, record: Record) -> str:
        """Render one record as an unpadded line, whole.

        What ``console`` renders as a table beneath a line stays on the line here: a table
        is column padding, and this formatter spends none. One record is still one line.
        """
        return console(shorten(record), paint=paint, pad=False)


def _with_summary(record: Record, line: str) -> RenderableType:
    """Put a kind's own rendering under its line, where the kind has one.

    The line keeps the whole-line spelling it has on its own: a record's line is not cut or
    folded to a terminal's width, whatever is rendered beneath it.
    """
    beneath = summaries.beneath(record)
    return line if beneath is None else Group(line, beneath)


#: What a template looks like, so the habit `docker --format` teaches gets a real answer.
TEMPLATE = re.compile(r"\{\{.*\}\}")


def looks_like_a_template(named: str) -> bool:
    """Report whether this argument is a template rather than a formatter's name."""
    return bool(TEMPLATE.search(named))


def registry(
    *,
    group: str = ENTRY_POINT_GROUP,
    extra: Mapping[str, object] | None = None,
) -> dict[str, Formatter]:
    """Build the registry: the built-ins, then whatever an installed plugin contributes.

    ``extra`` registers plugin objects that are not installed as distributions.
    """
    found: dict[str, Formatter] = {}
    origins: dict[str, str] = {}
    for built_in in (Console(), Compact()):
        found[built_in.name] = built_in
        origins[built_in.name] = BUILT_IN
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.load_entrypoints(group)
    for name, plugin in (extra or {}).items():
        manager.register(plugin, name=name)
    # The hook's return annotation is a declaration, not an enforcement: a plugin may answer
    # with anything, and anything that is not a formatter is not registered.
    for plugin_name, contributed in manager.caller(markers.formatters).collect_with_plugins():
        for formatter in contributed:
            if not isinstance(formatter, Formatter):  # pyright: ignore[reportUnnecessaryIsInstance]
                continue
            owner = origins.get(formatter.name)
            if owner is not None:
                raise DuplicateFormatter(formatter.name, owner, plugin_name)
            origins[formatter.name] = plugin_name
            found[formatter.name] = formatter
    return found


def names() -> tuple[str, ...]:
    """List the registered formatter names, the default first."""
    registered = registry()
    rest = sorted(name for name in registered if name != DEFAULT)
    return (DEFAULT, *rest) if DEFAULT in registered else tuple(rest)


def rendered(lines: Iterable[str], formatter: Formatter) -> Iterator[RenderableType]:
    """Render a stored stream, passing through anything that is not a record."""
    for line in lines:
        text = line.rstrip("\n")
        record = parse(text)
        if record is None:
            yield text
            continue
        _adopt_scratch(record)
        # The protocol leaves the answer open; what this prints it with is rich's console.
        yield cast("RenderableType", formatter.render(record))


def _adopt_scratch(record: Record) -> None:
    """Take the prefix a run's URIs share off the run's own opening record.

    The live rendering is told the prefix by the run; a stream read back has only what the
    stream says, and the run states it once so that the shorter spelling round-trips.
    """
    if record.get("kind") == "run" and isinstance(record.get("scratch"), str):
        use_scratch_prefix(str(record["scratch"]))
