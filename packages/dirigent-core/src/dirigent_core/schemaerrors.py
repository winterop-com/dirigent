"""How a JSON Schema refusal of a value is said to the person who wrote the value.

jsonschema says a value that fits no branch of an ``anyOf`` "is not valid under any of the
given schemas", which names neither the shape wanted nor what to change. A YAML scalar written
bare where text is wanted, a period such as ``202501``, is the common case, and the fix is to
quote it.
"""

from collections.abc import Sequence
from typing import Final, cast

from jsonschema import SchemaError, ValidationError

#: The keywords a value fits one of several branches under.
BRANCHING: Final = frozenset({"anyOf", "oneOf"})

#: The keywords a refusal says the value itself is the wrong shape under.
SHAPE_KEYWORDS: Final = frozenset({"type", "enum", "const"})

#: How each JSON Schema type is named in a sentence.
TYPE_NAMES: Final = {
    "string": "a string",
    "array": "a list",
    "object": "a mapping",
    "integer": "an integer",
    "number": "a number",
    "boolean": "a boolean",
    "null": "null",
}

#: How many bare values a sentence names before it counts the rest.
NAMED_AT_MOST: Final = 3


def describe(error: ValidationError | SchemaError) -> str:
    """Say why a value was refused: what to quote, the shapes it could have had, or jsonschema's own sentence."""
    unquoted = _unquoted(error)
    if unquoted:
        return _quote_them(unquoted)
    if error.validator in BRANCHING and error.context:
        return _none_of(error)
    return error.message


def _unquoted(error: ValidationError | SchemaError) -> list[bool | int | float] | None:
    """The bare scalars that, written quoted, would clear this refusal, or None when quoting would not."""
    if error.validator == "type":
        instance = error.instance
        if "string" in _types(error.validator_value) and isinstance(instance, bool | int | float):
            return [instance]
        return None
    if error.validator not in BRANCHING or not error.context:
        return None
    for branch in _branches(error):
        found: list[bool | int | float] = []
        for inner in branch:
            values = _unquoted(inner)
            if values is None:
                break
            found.extend(values)
        else:
            return found
    return None


def _types(wanted: object) -> list[str]:
    """The types a ``type`` keyword names, written as one or as a list."""
    if isinstance(wanted, str):
        return [wanted]
    return [str(one) for one in cast("list[object]", wanted)] if isinstance(wanted, list) else []


def _branches(error: ValidationError | SchemaError) -> list[list[ValidationError]]:
    """The errors of each branch of an ``anyOf`` or ``oneOf``, in the order the schema writes them."""
    grouped: dict[object, list[ValidationError]] = {}
    for inner in error.context or ():
        key = inner.relative_schema_path[0] if inner.relative_schema_path else None
        grouped.setdefault(key, []).append(inner)
    return list(grouped.values())


def _quote_them(values: Sequence[bool | int | float]) -> str:
    """Say which bare values to quote, and how one of them is written quoted."""
    first = _bare(values[0])
    if len(values) == 1:
        return f"{first} is {_kind(values[0])}; write it quoted, '{first}'"
    named = [_bare(value) for value in values[:NAMED_AT_MOST]]
    rest = len(values) - len(named)
    listed = f"{', '.join(named)} and {rest} more" if rest else f"{', '.join(named[:-1])} and {named[-1]}"
    kinds = {_kind(value) for value in values}
    plural = {"a number": "numbers", "a boolean": "booleans"}[kinds.pop()] if len(kinds) == 1 else "not text"
    return f"{listed} are {plural}; write each quoted, as '{first}'"


def _kind(value: bool | int | float) -> str:
    """Name what a bare scalar was read as."""
    return "a boolean" if isinstance(value, bool) else "a number"


def _bare(value: bool | int | float) -> str:
    """Write a scalar the way YAML reads it back."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _none_of(error: ValidationError | SchemaError) -> str:
    """Say what a value that fits no branch could have been, or where the nearest branch refused it."""
    shown = _shown(error.instance)
    branches = _branches(error)
    shapes: list[str] = []
    for branch in branches:
        shape = _shape(branch)
        if shape is None:
            nearest = branch[0]
            where = ".".join(str(part) for part in nearest.relative_path)
            said = describe(nearest)
            return f"{said} (at {where})" if where else said
        shapes.append(shape)
    if len(shapes) == 1:
        return f"{shown} is not {shapes[0]}"
    return f"{shown} is none of what this field takes: {', '.join(shapes[:-1])} or {shapes[-1]}"


def _shape(branch: list[ValidationError]) -> str | None:
    """Name the shape a branch wanted, when it refused the value itself for being another shape."""
    for inner in branch:
        if inner.relative_path or inner.validator not in SHAPE_KEYWORDS:
            continue
        wanted: object = inner.validator_value
        match inner.validator:
            case "type":
                return " or ".join(TYPE_NAMES.get(one, one) for one in _types(wanted))
            case "enum" if isinstance(wanted, list):
                return f"one of {', '.join(_shown(one) for one in cast('list[object]', wanted))}"
            case _:
                return _shown(wanted)
    return None


def _shown(value: object) -> str:
    """Write a value the way a refusal quotes one, with YAML's spelling of true, false and null."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return repr(value)
