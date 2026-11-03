"""Bounds on a humane duration or size, published in a schema and enforced from it.

JSON Schema has no keyword that bounds a ``5m`` or a ``16KB``, so a field's ``ge``/``le``
travels as ``x-dirigent-bounds``: the kind of value it bounds and each bound in the spelling a
document writes, ``{"kind": "duration", "maximum": "30s"}``. A validator extended with
:data:`BOUNDS_KEYWORD` enforces it, so a document is refused where it is checked rather than
where it runs.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any, Final, cast

from jsonschema import ValidationError
from pydantic import TypeAdapter

from dirigent_common.durations import DurationError, format_duration, to_timedelta
from dirigent_common.messages import ABOVE, AT_LEAST, AT_MOST, BELOW, Message
from dirigent_common.sizes import SizeError, format_size, parse_size

#: The keyword a bounded duration or size carries in a published schema.
BOUNDS_KEYWORD: Final = "x-dirigent-bounds"

#: Pydantic's constraint names, and the name each bound is published under.
_BOUND_NAMES: Final = {
    "ge": "minimum",
    "gt": "exclusiveMinimum",
    "le": "maximum",
    "lt": "exclusiveMaximum",
}

_TIMEDELTA: Final = TypeAdapter(timedelta)


def publish_bounds(node: object) -> object:
    """Walk a generated schema, turning each bound pydantic left as a stray key into ``x-dirigent-bounds``.

    Pydantic writes a duration's bound in ISO 8601 and a size's as an integer, beside the
    reference to the type, so the spelling of the bound says which of the two it bounds.
    """
    if isinstance(node, list):
        return [publish_bounds(item) for item in cast("list[object]", node)]
    if not isinstance(node, dict):
        return node
    entries = cast("dict[str, object]", node)
    walked = {key: publish_bounds(value) for key, value in entries.items() if key not in _BOUND_NAMES}
    stray = {key: entries[key] for key in _BOUND_NAMES if key in entries}
    if not stray:
        return walked
    durations = all(isinstance(value, str) for value in stray.values())
    bounds: dict[str, object] = {"kind": "duration" if durations else "size"}
    for key, value in stray.items():
        if durations:
            bounds[_BOUND_NAMES[key]] = format_duration(_TIMEDELTA.validate_python(value))
        elif isinstance(value, int) and not isinstance(value, bool):
            bounds[_BOUND_NAMES[key]] = format_size(value)
    walked[BOUNDS_KEYWORD] = bounds
    return walked


def _measure(kind: str, value: object) -> float | None:
    """Read a value as seconds or bytes, or nothing when it is not one; its pattern refuses that."""
    try:
        if kind == "duration":
            return to_timedelta(value).total_seconds()
        parsed = parse_size(value)
    except (DurationError, SizeError, ValueError):
        return None
    return float(parsed) if isinstance(parsed, int) and not isinstance(parsed, bool) else None


#: The refusal each bound is missed under: the same ``validation.*`` message a model's own
#: bound on the field is, so a schema check and a model check say one thing one way.
_REFUSED: Final[tuple[tuple[str, Message], ...]] = (
    ("minimum", AT_LEAST),
    ("exclusiveMinimum", ABOVE),
    ("maximum", AT_MOST),
    ("exclusiveMaximum", BELOW),
)


def _holds(name: str, measured: float, limit: float) -> bool:
    """Say whether a measured value keeps one bound."""
    match name:
        case "minimum":
            return measured >= limit
        case "exclusiveMinimum":
            return measured > limit
        case "maximum":
            return measured <= limit
        case _:
            return measured < limit


def missed_bound(bounds: object, instance: object) -> tuple[Message, str] | None:
    """The refusal a value outside its published bounds is answered with, and the bound as written."""
    if not isinstance(bounds, dict):
        return None
    written_bounds = cast("dict[str, object]", bounds)
    kind = str(written_bounds.get("kind", "duration"))
    measured = _measure(kind, instance)
    if measured is None:
        return None
    for name, message in _REFUSED:
        written = written_bounds.get(name)
        limit = None if written is None else _measure(kind, written)
        if limit is not None and not _holds(name, measured, limit):
            return message, str(written)
    return None


def bounds_keyword(validator: Any, bounds: Any, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Refuse a duration or size outside the bounds its field publishes."""
    missed = missed_bound(bounds, instance)
    if missed is not None:
        message, limit = missed
        yield ValidationError(message.render(limit=limit))
