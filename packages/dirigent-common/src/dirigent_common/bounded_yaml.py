"""Reading YAML whose aliases cannot expand past a bound once something writes them out.

PyYAML builds an alias as a second reference to one object, so loading a few hundred bytes of
nested aliases is cheap, and the cost arrives later: a pydantic dump, a digest or ``json.dumps``
walks every path and expands them to billions of values. So a document is measured before it is
built, and refused here rather than wherever it is first written out.
"""

from typing import Any, Final, cast

import yaml
from pydantic import BaseModel

from dirigent_common.messages import (
    YAML_ALIAS_CYCLE,
    YAML_ALIASES_EXPAND_TOO_FAR,
    YAML_ALIASES_WRITE_TOO_MUCH,
    YAML_NESTED_TOO_DEEP,
)

#: How many values a YAML stream's aliases may add once each is written out in place.
ALIAS_EXPANSION_LIMIT: Final = 100_000

#: How many bytes of scalar text a YAML stream's aliases may add once each is written out in place.
ALIAS_EXPANSION_BYTES: Final = 16 * 1024 * 1024


class YamlExpansionError(yaml.YAMLError):
    """A YAML stream's aliases go past a bound, a node contains itself, or it nests too deeply."""


class _Added(BaseModel):
    """What the aliases of a YAML stream add once written out, across its documents so far."""

    values: int = 0
    scalar_bytes: int = 0


class BoundedLoader(yaml.SafeLoader):
    """The safe loader, refusing a document before it is built when its aliases expand too far.

    A document is refused when the aliases of the stream so far would add more than
    ``ALIAS_EXPANSION_LIMIT`` values or ``ALIAS_EXPANSION_BYTES`` bytes of scalar text once
    written out. A document's own text is not counted: it is already in the input.
    """

    def __init__(self, stream: str) -> None:
        """Start the stream with nothing added by its aliases."""
        super().__init__(stream)
        self.added = _Added()

    def construct_document(self, node: yaml.Node) -> Any:
        """Build the document once its written-out size is known to be bounded."""
        _hold_expansion(node, self.added)
        return super().construct_document(node)  # pyright: ignore[reportUnknownMemberType]


def _scalar_bytes(node: yaml.Node) -> int:
    """How many bytes of text one node itself holds, which is nothing unless it is a scalar."""
    if not isinstance(node, yaml.ScalarNode):
        return 0
    return len(cast("str", node.value).encode(errors="replace"))


def _hold_expansion(root: yaml.Node, added: _Added) -> None:
    """Refuse a node graph whose aliases take the stream past a limit, or that contains itself."""
    sizes: dict[int, tuple[int, int]] = {}
    open_nodes: set[int] = set()
    distinct_bytes = 0

    def size(node: yaml.Node) -> tuple[int, int]:
        nonlocal distinct_bytes
        key = id(node)
        if key in sizes:
            return sizes[key]
        if key in open_nodes:
            raise YamlExpansionError(YAML_ALIAS_CYCLE.render())
        open_nodes.add(key)
        children: list[yaml.Node] = []
        if isinstance(node, yaml.SequenceNode):
            children = cast("list[yaml.Node]", node.value)
        elif isinstance(node, yaml.MappingNode):
            pairs = cast("list[tuple[yaml.Node, yaml.Node]]", node.value)
            children = [child for pair in pairs for child in pair]
        measured = [size(child) for child in children]
        own = _scalar_bytes(node)
        values = 1 + sum(child[0] for child in measured)
        scalar_bytes = own + sum(child[1] for child in measured)
        open_nodes.discard(key)
        sizes[key] = (values, scalar_bytes)
        distinct_bytes += own
        if added.values + values - len(sizes) > ALIAS_EXPANSION_LIMIT:
            raise YamlExpansionError(YAML_ALIASES_EXPAND_TOO_FAR.render(limit=f"{ALIAS_EXPANSION_LIMIT:,}"))
        if added.scalar_bytes + scalar_bytes - distinct_bytes > ALIAS_EXPANSION_BYTES:
            raise YamlExpansionError(YAML_ALIASES_WRITE_TOO_MUCH.render(limit=f"{ALIAS_EXPANSION_BYTES:,}"))
        return sizes[key]

    values, scalar_bytes = size(root)
    added.values += values - len(sizes)
    added.scalar_bytes += scalar_bytes - distinct_bytes


def bounded_load(text: str, loader: type[BoundedLoader] = BoundedLoader) -> Any:
    """Read one YAML document, refusing what expands too far or nests past Python's own stack."""
    try:
        return yaml.load(text, Loader=loader)  # noqa: S506 - a BoundedLoader is a SafeLoader
    except RecursionError as error:
        raise YamlExpansionError(YAML_NESTED_TOO_DEEP.render()) from error


def bounded_load_all(text: str, loader: type[BoundedLoader] = BoundedLoader) -> list[Any]:
    """Read every document of a YAML stream under one bound, refusing as ``bounded_load`` does."""
    try:
        return list(yaml.load_all(text, Loader=loader))  # noqa: S506 - a BoundedLoader is a SafeLoader
    except RecursionError as error:
        raise YamlExpansionError(YAML_NESTED_TOO_DEEP.render()) from error
