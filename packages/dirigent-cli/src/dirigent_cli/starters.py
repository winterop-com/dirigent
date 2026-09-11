"""Copying a starter: the two lines a copy rewrites, and nothing else.

A starter is a plain ``dirigent/v1`` document, not a template, so instantiating one is a
verbatim copy of its text with the top-level ``code:`` changed and ``starter`` taken off the
top-level ``tags:``. The edit is at text level rather than through a parser because the
teaching comments, the blank lines and the quoting are the point of copying a document
instead of generating one.
"""

import re
from typing import Final

from dirigent_client import Requirements
from dirigent_core.examples import STARTER_TAG

#: The top-level ``code:`` line: no indentation, so a step's own ``code`` is never touched.
_CODE = re.compile(r"^code:[^\S\n]*(.*)$", re.MULTILINE)

#: The top-level ``tags:`` line, and whatever it carries on the same line.
_TAGS = re.compile(r"^tags:[^\S\n]*(.*)$", re.MULTILINE)

#: One entry of a block list under ``tags:``: two spaces, a dash, the value.
_TAG_ITEM = re.compile(r"^[^\S\n]*-[^\S\n]*(\S.*?)[^\S\n]*$")

_FLOW: Final = ("[", "]")


def instantiate(source: str, code: str) -> str:
    """Copy a starter's text under a new code, with the ``starter`` tag dropped."""
    return _retag(_recode(source, code))


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


def preflight(requires: Requirements) -> list[str]:
    """List what has to exist on the instance before a copy of this document will apply."""
    steps = [f"dg connection create KIND {code}" for code in requires.connections]
    steps += [f"dg schema create {code}.json --code {code}" for code in requires.schemas]
    steps += [f"apply the pipeline {code} it starts" for code in requires.pipelines]
    steps += [f"a storage backend claiming {scheme}://" for scheme in requires.storage]
    steps += [f"a pack contributing {block}" for block in requires.blocks]
    steps += [f"a worker carrying the {tag} tag" for tag in requires.workers]
    return steps
