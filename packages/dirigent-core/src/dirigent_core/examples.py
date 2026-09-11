"""The installed example corpus: every document a plugin ships, read once on first use.

The walk is not part of startup. A worker never asks for an example, so it never pays for
the read; a CLI or an API request that asks pays once, for the life of the process.
"""

import logging
from collections.abc import Iterator, Sequence
from importlib.resources.abc import Traversable
from typing import Final, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dirigent_common import JsonMap
from dirigent_core.documents import CARRIED, SUFFIXES, is_document, safe_load
from dirigent_core.engine.definition import Requirements

#: The tag a document wears to say it may be copied into a project as a starting point.
STARTER_TAG: Final = "starter"

logger = logging.getLogger(__name__)


class ExampleEntry(BaseModel):
    """One document of the installed corpus, as every reader of the catalogue sees it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    requires: Requirements = Field(default_factory=Requirements)
    plugin: str
    """The distribution the shelves came from, named as the plugin host names a contributor."""

    shelf: str
    """The directory the file sits in, relative to the shelves root; empty at the root."""

    path: str
    """The file, relative to the shelves root."""

    source: str
    """The document's text, verbatim, which is what a copy of it copies."""

    starter: bool = False
    carries: list[str] = Field(default_factory=list[str])
    """The top-level sections this document carries rather than requires, which an instance
    refuses to store: ``connections``, ``schemas``."""


def collect(shelves: Sequence[tuple[str, Sequence[Traversable]]]) -> list[ExampleEntry]:
    """Read every document under each plugin's shelves, in plugin, shelf, code order."""
    entries: list[ExampleEntry] = []
    for plugin, roots in shelves:
        seen: set[str] = set()
        for root in roots:
            for path, node in _walk(root):
                entry = _entry(plugin, path, node)
                if entry is None:
                    continue
                if entry.code in seen:
                    logger.warning(
                        "plugin %s carries two examples with the code %r; %s is passed over",
                        plugin,
                        entry.code,
                        path,
                    )
                    continue
                seen.add(entry.code)
                entries.append(entry)
    return sorted(entries, key=lambda one: (one.plugin, one.shelf, one.code))


def _walk(root: Traversable) -> Iterator[tuple[str, Traversable]]:
    """Yield every readable file under a directory, deepest last, by relative path."""
    if not root.is_dir():
        return
    for node in sorted(root.iterdir(), key=lambda one: one.name):
        if node.is_dir():
            for path, found in _walk(node):
                yield f"{node.name}/{path}", found
        elif node.name.endswith(SUFFIXES):
            yield node.name, node


def _entry(plugin: str, path: str, node: Traversable) -> ExampleEntry | None:
    """Read one file as a catalogue entry, passing over anything that is not a document."""
    try:
        source = node.read_text()
        parsed = safe_load(source)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        logger.warning("plugin %s carries %s, which does not parse; it is passed over", plugin, path)
        return None
    if not isinstance(parsed, dict) or not is_document(cast("JsonMap", parsed)):
        logger.warning("plugin %s carries %s, which is not a dirigent document; it is passed over", plugin, path)
        return None
    raw = cast("JsonMap", parsed)
    code = raw.get("code")
    if not isinstance(code, str):
        logger.warning("plugin %s carries %s, which declares no code; it is passed over", plugin, path)
        return None
    declared_tags = raw.get("tags")
    tags = (
        [one for one in cast("list[object]", declared_tags) if isinstance(one, str)]
        if isinstance(declared_tags, list)
        else []
    )
    shelf, _, _ = path.rpartition("/")
    return ExampleEntry(
        code=code,
        name=raw.get("name") if isinstance(raw.get("name"), str) else None,
        description=raw.get("description") if isinstance(raw.get("description"), str) else None,
        tags=tags,
        requires=_requires(raw),
        plugin=plugin,
        shelf=shelf,
        path=path,
        source=source,
        starter=STARTER_TAG in tags,
        carries=[section for section in CARRIED if raw.get(section)],
    )


def _requires(raw: JsonMap) -> Requirements:
    """Read a document's ``requires:`` section, answering with an empty one it does not parse."""
    declared = raw.get("requires")
    if not isinstance(declared, dict):
        return Requirements()
    try:
        return Requirements.model_validate(declared)
    except ValueError:
        return Requirements()
