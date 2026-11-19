"""Where a JSON Schema ``$ref`` may lead: its own document, the shipped drafts, and held schemas.

A validator built without a registry retrieves a ``$ref`` it cannot resolve over HTTP, on
whichever process is validating. A schema is written by whoever can apply a document, so that
is a request from the server's network to an address they chose. Every validator here is built
with a registry that retrieves nothing from anywhere: ``LOCAL_REFERENCES`` holds no schema of
its own, and ``held_references`` answers only from the schemas the caller hands it. The library
adds its bundled metaschemas to either.

A ``$ref`` NAMES A HELD SCHEMA BY ITS CODE, OR BY ITS EXACT ``$id``. The reference is resolved
against the referring schema's ``$id`` first, as the validator resolves it. What that gives is
either a bare code -- ``station-code``, or ``station-code.json``, with any fragment pointing
inside it -- which reaches the schema held under that code, or an address, which reaches a held
schema only when that schema's own ``$id`` is that same address. An address to some other
schema that merely ends in a held code reaches nothing, so it is refused rather than quietly
checked against a local shape it never meant.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any, Final, cast
from urllib.parse import urljoin

from jsonschema_specifications import REGISTRY as SPECIFICATIONS
from referencing import Registry, Resource
from referencing._core import Resolver
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

LOCAL_REFERENCES: Final[Registry[Any]] = Registry()

#: A schema code: what the last path segment of a ``$ref`` or an ``$id`` has to be to name one.
_CODE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")


def schema_code_of(uri: str) -> str | None:
    """The schema code a URI names: its last path segment, minus a fragment and any extension.

    ``https://example.org/schemas/org-unit.json``, ``org-unit#/properties/id`` and ``org-unit``
    all name ``org-unit``. A segment that is not a usable code names nothing.
    """
    tail = uri.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\.(json|yaml|yml)$", "", tail)
    return tail if _CODE.match(tail) else None


def _address(uri: str) -> bool:
    """Whether a resolved reference is an address rather than a bare code."""
    return "://" in uri or uri.startswith(("/", "urn:"))


def held_target(uri: str, lookup: Callable[[str], Any | None]) -> tuple[str, Any] | None:
    """The held schema a resolved reference reaches, as its code and body, or None.

    A bare code reaches the schema held under it. An address reaches the held schema whose own
    ``$id`` is that address, and nothing else.
    """
    target = uri.split("#", 1)[0].rstrip("/")
    code = schema_code_of(target)
    body: Any = None if code is None else lookup(code)
    if code is None or body is None:
        return None
    if _address(target):
        own = _own_id(body)
        if own is None or own.split("#", 1)[0].rstrip("/") != target:
            return None
    return code, body


def _own_id(schema: Any) -> str | None:
    """A schema's own ``$id``, where it declares one."""
    if not isinstance(schema, dict):
        return None
    own = cast("dict[str, Any]", schema).get("$id")
    return own if isinstance(own, str) else None


def held_references(lookup: Callable[[str], Any | None]) -> Registry[Any]:
    """A registry resolving a ``$ref`` to a held schema through ``lookup``, and to nothing else.

    ``lookup`` answers the body held under a code, or None for a code it does not hold; a
    reference that reaches none raises ``Unresolvable`` as the evaluation reaches it.
    """

    def retrieve(uri: str) -> Resource[Any]:
        reached = held_target(uri, lookup)
        if reached is None:
            raise NoSuchResource(ref=uri)  # type: ignore[call-arg]
        return DRAFT202012.create_resource(reached[1])

    return Registry(retrieve=retrieve)  # type: ignore[call-arg]


def outward_references(schema: Any) -> set[str]:
    """Every reference a schema makes to something outside itself, resolved against its ``$id``.

    A reference that stays inside the schema (``#/$defs/...``) is not one, and neither is one
    back to the schema's own ``$id``. Each is answered without its fragment.
    """
    own = _own_id(schema)
    base = own.split("#", 1)[0] if own is not None else ""
    found: set[str] = set()
    for ref in _refs(schema):
        if ref.startswith("#"):
            continue
        resolved = urljoin(base, ref).split("#", 1)[0].rstrip("/")
        if resolved and resolved != base.rstrip("/"):
            found.add(resolved)
    return found


def reference_targets(schema: Any, lookup: Callable[[str], Any | None]) -> tuple[set[str], set[str]]:
    """The held codes a schema's references reach, and the references that reach nothing held."""
    reached: set[str] = set()
    unreached: set[str] = set()
    for uri in outward_references(schema):
        target = held_target(uri, lookup)
        if target is None:
            unreached.add(uri)
        else:
            reached.add(target[0])
    return reached, unreached


#: The 2020-12 keywords whose value is one subschema, a list of them, or a map of them.
_ONE_SUBSCHEMA: Final = frozenset(
    {
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_LIST_OF_SUBSCHEMAS: Final = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_MAP_OF_SUBSCHEMAS: Final = frozenset({"$defs", "definitions", "dependentSchemas", "patternProperties", "properties"})


def unresolved_references(schema: Any, registry: Registry[Any] = LOCAL_REFERENCES) -> list[tuple[str, str]]:
    """Every ``$ref`` in a schema that ``registry`` cannot resolve, as where it sits and what it says.

    Each reference is looked up as a validator built over ``registry`` looks it up when an
    evaluation reaches it: against the ``$id`` of the schema around it, with the bundled drafts
    beside what the registry holds. Nothing is retrieved from the network. Where is the
    slash-joined path of the subschema holding the ``$ref``, or ``(root)``.
    """
    root = DRAFT202012.create_resource(schema)
    resolver = SPECIFICATIONS.combine(registry).resolver_with_root(root)
    found: list[tuple[str, str]] = []
    _collect_unresolved(schema, (), resolver, found)
    return found


def _collect_unresolved(
    node: Any, path: tuple[str, ...], resolver: Resolver[Any], found: list[tuple[str, str]]
) -> None:
    """Add each unresolvable ``$ref`` under one subschema to ``found``."""
    if not isinstance(node, dict):
        return
    schema = cast("dict[str, Any]", node)
    resolver = resolver.in_subresource(DRAFT202012.create_resource(schema))
    ref = schema.get("$ref")
    if isinstance(ref, str):
        try:
            resolver.lookup(ref)
        except (Unresolvable, ValueError):
            found.append(("/".join(path) or "(root)", ref))
    for keyword, value in schema.items():
        if keyword in _ONE_SUBSCHEMA:
            _collect_unresolved(value, (*path, keyword), resolver, found)
        elif keyword in _LIST_OF_SUBSCHEMAS and isinstance(value, list):
            for index, item in enumerate(cast("list[Any]", value)):  # type: ignore[redundant-cast]
                _collect_unresolved(item, (*path, keyword, str(index)), resolver, found)
        elif keyword in _MAP_OF_SUBSCHEMAS and isinstance(value, dict):
            for name, item in cast("dict[str, Any]", value).items():
                _collect_unresolved(item, (*path, keyword, name), resolver, found)


def _refs(node: Any) -> Iterator[str]:
    """Every ``$ref`` string under a node, depth first."""
    if isinstance(node, dict):
        for key, value in cast("dict[str, Any]", node).items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in cast("list[Any]", node):  # type: ignore[redundant-cast]
            yield from _refs(item)


__all__ = [
    "LOCAL_REFERENCES",
    "Unresolvable",
    "held_references",
    "held_target",
    "outward_references",
    "reference_targets",
    "schema_code_of",
    "unresolved_references",
]
