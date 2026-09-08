"""Humane durations: ``30s`` and ``5m`` in a document, ``timedelta`` in the engine."""

import re
from datetime import timedelta
from typing import Annotated, Any, Final, cast

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, WithJsonSchema
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, JsonSchemaValue
from pydantic_core import CoreSchema

#: Ordered largest first; the greedy decomposition in :func:`format_duration` depends on it.
UNITS: Final[tuple[tuple[str, float], ...]] = (
    ("w", 604800.0),
    ("d", 86400.0),
    ("h", 3600.0),
    ("m", 60.0),
    ("s", 1.0),
    ("ms", 0.001),
)

_TERM: Final = re.compile(r"(\d+(?:\.\d+)?)(ms|[wdhms])")

#: A whole duration: one or more suffixed terms. Public, because it is the grammar an export
#: must never write outside of.
DURATION_PATTERN: Final = re.compile(r"^(?:\d+(?:\.\d+)?(?:ms|[wdhms]))+$")

#: The same grammar spelled for JSON Schema, with the bare number of seconds allowed as well.
DURATION_JSON_PATTERN: Final = r"^(?:(?:\d+(?:\.\d+)?(?:ms|[wdhms]))+|\d+(?:\.\d+)?)$"

ZERO: Final = "0s"


class NegativeDuration(ValueError):
    """A duration was negative, which the grammar has no spelling for."""

    def __init__(self, value: object) -> None:
        """Name the offending value."""
        super().__init__(
            f"{value!r} is negative, and a duration is a delay, a cadence, or a budget: "
            "the format has no way to write one that runs backwards"
        )


class DurationError(ValueError):
    """A duration was written in a way the format does not define."""

    def __init__(self, value: object) -> None:
        """Name the value and the grammar it failed."""
        super().__init__(
            f"{value!r} is not a duration: write a number of seconds, or unit-suffixed terms "
            f"such as '30s', '5m', '6h', '1h30m', '250ms' (units: w, d, h, m, s, ms)"
        )


def parse_duration(value: object) -> object:
    """Turn a humane duration string into a timedelta, passing anything else through."""
    match value:
        case timedelta():
            return value
        case bool():
            raise DurationError(value)
        case int() | float():
            return timedelta(seconds=float(value))
        case str():
            return _parse_text(value.strip())
        case _:
            return value


def _parse_text(text: str) -> timedelta:
    """Parse the string form: a bare number of seconds, or a sequence of suffixed terms."""
    if not text:
        raise DurationError(text)
    try:
        return timedelta(seconds=float(text))
    except ValueError:
        pass
    if DURATION_PATTERN.fullmatch(text) is None:
        raise DurationError(text)
    lengths = dict(UNITS)
    seconds = sum(float(amount) * lengths[unit] for amount, unit in _TERM.findall(text))
    return timedelta(seconds=seconds)


def to_timedelta(value: object) -> timedelta:
    """Read a humane duration as a timedelta, refusing anything the grammar does not define."""
    parsed = parse_duration(value)
    if not isinstance(parsed, timedelta):
        raise DurationError(value)
    return parsed


def format_duration(value: timedelta) -> str:
    """Render a timedelta the one way the canonical document writes it.

    Every duration must have exactly one spelling, or an export stops being byte-stable.
    """
    total = value.total_seconds()
    if total < 0:
        raise NegativeDuration(value)
    if total == 0:
        return ZERO
    remaining = round(total * 1000) / 1000
    parts: list[str] = []
    for unit, length in UNITS:
        if length > remaining and unit != "ms":
            continue
        count = int(remaining / length) if unit != "ms" else round(remaining / length)
        if count == 0:
            continue
        parts.append(f"{count}{unit}")
        remaining = round((remaining - count * length) * 1000) / 1000
        if remaining <= 0:
            break
    return "".join(parts) or ZERO


def refuse_negative(value: timedelta) -> timedelta:
    """Refuse a negative duration, because the grammar has no way to write one down."""
    if value < timedelta(0):
        raise NegativeDuration(value)
    return value


def is_duration(value: object) -> bool:
    """Whether the value is a duration as a document writes one: humane spelling, not negative."""
    if not isinstance(value, str):
        return False
    try:
        return to_timedelta(value) >= timedelta(0)
    except DurationError:
        return False


#: A duration as a document writes it and as the code uses it: a timedelta.
#:
#: The published schema is the humane grammar, because a document writes ``5m`` and never
#: ``PT5M``, and the catalog check is what a document is validated against before it is
#: ever run. The format is named ``humane-duration`` rather than the standard ``duration``,
#: which names ISO 8601 and would refuse every value this type accepts.
type Duration = Annotated[
    timedelta,
    BeforeValidator(parse_duration),
    AfterValidator(refuse_negative),
    PlainSerializer(format_duration, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": DURATION_JSON_PATTERN, "format": "humane-duration"}),
]

#: Bounds pydantic leaves on a field it could not express in JSON Schema, which is every
#: bound on a duration: JSON Schema has no keyword for one.
_UNEXPRESSED_BOUNDS: Final = ("gt", "ge", "lt", "le")


class HumaneJsonSchema(GenerateJsonSchema):
    """The schema generator every schema dirigent publishes is built with.

    A default reaches JSON Schema through pydantic's own encoder, which renders a timedelta
    in ISO 8601 whatever the field's serializer says, so a schema built without this writes
    ``PT5M`` where the document it describes writes ``5m``.
    """

    def encode_default(self, dft: Any) -> Any:
        """Encode a default, writing a duration the one way a document spells it."""
        if isinstance(dft, timedelta):
            return format_duration(dft)
        return super().encode_default(dft)

    def generate(self, schema: CoreSchema, mode: JsonSchemaMode = "validation") -> JsonSchemaValue:
        """Generate the schema, dropping the bounds JSON Schema has no keyword for."""
        return cast("JsonSchemaValue", _without_unexpressed_bounds(super().generate(schema, mode=mode)))


def _without_unexpressed_bounds(node: object) -> object:
    """Walk a schema, dropping every bound pydantic could not express as a keyword."""
    if isinstance(node, dict):
        entries = cast("dict[str, object]", node)
        return {
            key: _without_unexpressed_bounds(value) for key, value in entries.items() if key not in _UNEXPRESSED_BOUNDS
        }
    if isinstance(node, list):
        return [_without_unexpressed_bounds(item) for item in cast("list[object]", node)]
    return node
