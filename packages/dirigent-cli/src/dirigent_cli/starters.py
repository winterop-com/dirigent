"""Copying a starter: the lines a copy rewrites, and nothing else.

A starter is a plain ``dirigent/v1`` document, not a template, so instantiating one is a
verbatim copy of its text with the top-level ``code:`` changed, ``starter`` taken off the
top-level ``tags:``, and every section the document carried named under ``requires:``
instead. A document carries its connections and its schemas so that it runs alone under
``dg run --local``, and an instance refuses to store one that does, so a copy names them.
The edit is at text level rather than through a parser because the teaching comments, the
blank lines and the quoting are the point of copying a document instead of generating one.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Final, cast

from dirigent_client import Requirements
from dirigent_common import JsonMap
from dirigent_core.documents import CARRIED, safe_load
from dirigent_core.examples import STARTER_TAG

#: The top-level ``code:`` line: no indentation, so a step's own ``code`` is never touched.
_CODE = re.compile(r"^code:[^\S\n]*(.*)$", re.MULTILINE)

#: The top-level ``tags:`` line, and whatever it carries on the same line.
_TAGS = re.compile(r"^tags:[^\S\n]*(.*)$", re.MULTILINE)

#: One entry of a block list under ``tags:``: two spaces, a dash, the value.
_TAG_ITEM = re.compile(r"^[^\S\n]*-[^\S\n]*(\S.*?)[^\S\n]*$")

#: A mapping key on its own line: its indentation, its name, and what follows the colon.
_KEY = re.compile(r"^([^\S\n]*)([^\s#][^:]*):[^\S\n]*(.*)$")

#: One entry of an indented block list: its indentation, and the value.
_ITEM = re.compile(r"^([^\S\n]+)-[^\S\n]+(\S.*?)[^\S\n]*$")

#: Where a ``requires:`` section goes in a document that has none: after the first of these.
_ANCHORS: Final = ("tags", "description", "code")

_FLOW: Final = ("[", "]")


def instantiate(source: str, code: str) -> str:
    """Copy a starter's text under a new code, naming what the original carried."""
    return _uncarry(_retag(_recode(source, code)))


def _recode(source: str, code: str) -> str:
    """Rewrite the one top-level ``code:`` line, leaving every other line alone."""
    return _CODE.sub(lambda _: f"code: {code}", source, count=1)


def _retag(source: str) -> str:
    """Take ``starter`` off the top-level ``tags:``, whichever shape the list is written in.

    A document whose only tag was ``starter`` loses the whole ``tags:`` entry: an empty list
    says less than no list at all.
    """
    found = _TAGS.search(source)
    if found is None:
        return source
    rest = found.group(1).strip()
    if rest.startswith(_FLOW[0]):
        return _rewrite_flow(source, found.start(), found.end(), rest)
    if rest:
        return source
    return _rewrite_block(source, found.start(), found.end())


def _rewrite_flow(source: str, start: int, end: int, rest: str) -> str:
    """Rewrite ``tags: [a, b, starter]``, dropping the entry when nothing is left."""
    inner = rest.removeprefix(_FLOW[0]).removesuffix(_FLOW[1])
    kept = [tag for tag in (one.strip() for one in inner.split(",")) if tag and tag != STARTER_TAG]
    if not kept:
        return _drop_line(source, start, end)
    return source[:start] + f"tags: [{', '.join(kept)}]" + source[end:]


def _rewrite_block(source: str, start: int, end: int) -> str:
    """Rewrite a block list under ``tags:``, dropping the whole entry when nothing is left."""
    lines = source[end:].split("\n")
    items: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if index == 0 and not line.strip():
            continue
        matched = _TAG_ITEM.match(line)
        if matched is None:
            break
        items.append((index, matched.group(1)))
    if not items:
        return source
    dropped = [index for index, tag in items if tag == STARTER_TAG]
    if not dropped:
        return source
    if len(dropped) == len(items):
        return _drop_line(source, start, end + len("\n".join(lines[: items[-1][0] + 1])))
    kept = [line for index, line in enumerate(lines) if index not in dropped]
    return source[:end] + "\n".join(kept)


def _drop_line(source: str, start: int, end: int) -> str:
    """Remove a whole entry, including the newline that ended it."""
    tail = source[end:]
    return source[:start] + tail.removeprefix("\n")


def _uncarry(source: str) -> str:
    """Take each carried section out and name the codes it held under ``requires:``."""
    for section in CARRIED:
        codes = _carried(source, section)
        if not codes:
            continue
        source = _require(_strip(source, section), section, codes)
    return source


def _top(lines: list[str], name: str) -> int | None:
    """Where a top-level key sits, or ``None`` when the document has no such section."""
    for index, line in enumerate(lines):
        matched = _KEY.match(line)
        if matched is not None and not matched.group(1) and matched.group(2) == name:
            return index
    return None


def _extent(lines: list[str], at: int) -> tuple[int, int, int]:
    """What a top-level key owns: its comment run, its last line, and where it stops.

    The first index is the comment run written immediately above the key, the second is the
    key's last indented line, and the third is the first line it does not own -- the next
    key, or the comment run written above that key.
    """
    start = at
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1
    last = at
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1].isspace()):
        if lines[end].strip():
            last = end
        end += 1
    return start, last, end


def _carried(source: str, section: str) -> list[str]:
    """The codes a carried section holds, read from the keys one level under it."""
    lines = source.split("\n")
    at = _top(lines, section)
    if at is None:
        return []
    _, last, _ = _extent(lines, at)
    codes: list[str] = []
    indent: str | None = None
    for line in lines[at + 1 : last + 1]:
        matched = _KEY.match(line)
        if matched is None:
            continue
        if indent is None:
            indent = matched.group(1)
        if matched.group(1) == indent:
            codes.append(matched.group(2).strip())
    return codes


def _strip(source: str, section: str) -> str:
    """Remove a whole top-level section, the comment lines written above it included."""
    lines = source.split("\n")
    at = _top(lines, section)
    if at is None:
        return source
    start, _, end = _extent(lines, at)
    return "\n".join(lines[:start] + lines[end:])


def _require(source: str, section: str, codes: Sequence[str]) -> str:
    """Name each code under ``requires:``, extending the list there or writing the section."""
    lines = source.split("\n")
    at = _top(lines, "requires")
    if at is None:
        return _write_requires(lines, section, codes)
    _, last, _ = _extent(lines, at)
    indent = _indent(lines, at, last)
    for index in range(at + 1, last + 1):
        matched = _KEY.match(lines[index])
        if matched is not None and matched.group(1) == indent and matched.group(2).strip() == section:
            return _extend(lines, index, section, codes)
    return "\n".join(lines[: last + 1] + _entry(indent, section, codes) + lines[last + 1 :])


def _indent(lines: list[str], at: int, last: int) -> str:
    """The indentation the keys under a section are written at, two spaces when it has none."""
    for line in lines[at + 1 : last + 1]:
        matched = _KEY.match(line)
        if matched is not None:
            return matched.group(1)
    return "  "


def _entry(indent: str, section: str, codes: Sequence[str]) -> list[str]:
    """A section under ``requires:``, written as a block list of the codes it names."""
    return [f"{indent}{section}:", *(f"{indent}{indent}- {code}" for code in codes)]


def _extend(lines: list[str], at: int, section: str, codes: Sequence[str]) -> str:
    """Add every code that is not already there to a list under ``requires:``."""
    matched = _KEY.match(lines[at])
    indent = matched.group(1) if matched is not None else "  "
    rest = matched.group(3).strip() if matched is not None else ""
    if rest.startswith(_FLOW[0]):
        inner = rest.removeprefix(_FLOW[0]).removesuffix(_FLOW[1])
        held = [one.strip() for one in inner.split(",") if one.strip()]
        listed = held + [code for code in codes if code not in held]
        lines[at] = f"{indent}{section}: [{', '.join(listed)}]"
        return "\n".join(lines)
    if rest:
        return "\n".join(lines)
    items: list[tuple[int, str, str]] = []
    for index in range(at + 1, len(lines)):
        found = _ITEM.match(lines[index])
        if found is None:
            break
        items.append((index, found.group(1), found.group(2)))
    held = [value for _, _, value in items]
    item_indent = items[0][1] if items else indent + indent
    written = [f"{item_indent}- {code}" for code in codes if code not in held]
    after = items[-1][0] + 1 if items else at + 1
    return "\n".join(lines[:after] + written + lines[after:])


def _write_requires(lines: list[str], section: str, codes: Sequence[str]) -> str:
    """Write the ``requires:`` a document has none of, under the header it follows."""
    for name in _ANCHORS:
        at = _top(lines, name)
        if at is None:
            continue
        _, _, end = _extent(lines, at)
        before = [] if end == 0 or not lines[end - 1].strip() else [""]
        block = ["requires:", *_entry("  ", section, codes)]
        return "\n".join(lines[:end] + before + block + [""] + lines[end:])
    return "\n".join(lines)


def carried_kinds(source: str) -> dict[str, str]:
    """The kind each connection a document carries declares, keyed by its code."""
    parsed = safe_load(source)
    if not isinstance(parsed, dict):
        return {}
    carried = cast("JsonMap", parsed).get("connections")
    if not isinstance(carried, dict):
        return {}
    kinds: dict[str, str] = {}
    for code, definition in cast("JsonMap", carried).items():
        if not isinstance(definition, dict):
            continue
        kind = cast("JsonMap", definition).get("kind")
        if isinstance(kind, str):
            kinds[code] = kind
    return kinds


#: How a requirement's field is named when a summary counts it, singular and plural.
_COUNTED: Final = (
    ("connections", "connection", "connections"),
    ("schemas", "schema", "schemas"),
    ("pipelines", "pipeline", "pipelines"),
    ("storage", "storage scheme", "storage schemes"),
    ("blocks", "block", "blocks"),
    ("workers", "worker tag", "worker tags"),
)


def summary(requires: Requirements) -> str:
    """Say what a document needs in one line: the counts, or nothing when it needs nothing."""
    counted = [
        f"{len(held)} {one if len(held) == 1 else many}"
        for name, one, many in _COUNTED
        if (held := getattr(requires, name))
    ]
    return ", ".join(counted) or "-"


def preflight(requires: Requirements, kinds: Mapping[str, str]) -> list[str]:
    """List what has to exist on the instance before a copy of this document will apply.

    ``kinds`` names the kind of each connection the source carried, which is the one thing
    a ``dg connection create`` line cannot be written without.
    """
    steps = [f"dg connection create {kinds.get(code, 'KIND')} {code}" for code in requires.connections]
    steps += [f"dg schema create {code}.json --code {code}" for code in requires.schemas]
    steps += [f"apply the pipeline {code} it starts" for code in requires.pipelines]
    steps += [f"a storage backend claiming {scheme}://" for scheme in requires.storage]
    steps += [f"a pack contributing {block}" for block in requires.blocks]
    steps += [f"a worker carrying the {tag} tag" for tag in requires.workers]
    return steps
