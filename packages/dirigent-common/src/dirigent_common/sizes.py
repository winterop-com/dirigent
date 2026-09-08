"""Humane sizes: ``64mb`` in a document, an ``int`` of bytes in the code.

Both unit families are accepted and both are powers of 1024, which is what an operator
means by "64 megabytes of memory" whatever the SI prefix says. ``64mb`` and ``64mib`` are
therefore the same number, and the canonical rendering is the short spelling.
"""

import math
import re
from typing import Annotated, Final

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, WithJsonSchema

#: Ordered largest first; the greedy rendering in :func:`format_size` depends on it.
UNITS: Final[tuple[tuple[str, int], ...]] = (
    ("tb", 1024**4),
    ("gb", 1024**3),
    ("mb", 1024**2),
    ("kb", 1024),
    ("b", 1),
)

#: The long spelling of each unit, accepted on the way in and never written on the way out.
ALIASES: Final[dict[str, str]] = {"tib": "tb", "gib": "gb", "mib": "mb", "kib": "kb"}

#: A whole size: one number and one unit. Public, because it is the grammar an export must
#: never write outside of.
SIZE_PATTERN: Final = re.compile(r"^\d+(?:\.\d+)?(?:t|g|m|k)?i?b$", re.IGNORECASE)

#: The same grammar spelled for JSON Schema, which has no portable case-insensitive flag,
#: with the bare number of bytes allowed as well.
SIZE_JSON_PATTERN: Final = r"^\d+(?:\.\d+)?(?:[TtGgMmKk]?[Ii]?[Bb])?$"

#: How a zero size is written.
ZERO: Final = "0b"


class NegativeSize(ValueError):
    """A size was negative, which the grammar has no spelling for."""

    def __init__(self, value: object) -> None:
        """Name the value, since the fix is always to drop the sign."""
        super().__init__(f"{value!r} is negative, and a size is a quantity of bytes: it cannot run backwards")


class SizeError(ValueError):
    """A size was written in a way the format does not define."""

    def __init__(self, value: object) -> None:
        """Name the value and the grammar, because the fix is always a spelling change."""
        super().__init__(
            f"{value!r} is not a size: write a number of bytes, or a unit-suffixed amount such as "
            f"'512kb', '64mb', '1.5gb' (units: b, kb, mb, gb, tb, and the kib/mib/gib/tib spelling of each, "
            f"all powers of 1024)"
        )


def parse_size(value: object) -> object:
    """Turn a humane size string into a count of bytes, passing anything else through.

    Numbers are read as bytes, so ``min_size: 4096`` means the obvious thing.
    """
    match value:
        case bool():
            raise SizeError(value)
        case int():
            return value
        case float():
            return _whole(value, value)
        case str():
            return _parse_text(value.strip())
        case _:
            return value


def _parse_text(text: str) -> int:
    """Parse the string form: a bare number of bytes, or one unit-suffixed amount."""
    if not text:
        raise SizeError(text)
    try:
        return _whole(float(text), text)
    except ValueError:
        pass
    if SIZE_PATTERN.fullmatch(text) is None:
        raise SizeError(text)
    lowered = text.lower()
    sizes: dict[str, int] = dict(UNITS)
    suffix = next(unit for unit in (*ALIASES, *sizes) if lowered.endswith(unit))
    amount = lowered[: -len(suffix)] or "0"
    return _whole(float(amount) * sizes[ALIASES.get(suffix, suffix)], text)


def _whole(value: float, written: object) -> int:
    """Refuse a size that is not a whole number of bytes, which nothing can store."""
    if not math.isfinite(value) or value != int(value):
        raise SizeError(written)
    return int(value)


def format_size(value: int) -> str:
    """Render a count of bytes the one way the canonical document writes it.

    The largest unit that divides the value exactly, so a rendered size is never a decimal
    and reading it back yields the same number of bytes.
    """
    if value < 0:
        raise NegativeSize(value)
    if value == 0:
        return ZERO
    unit, multiplier = next((unit, size) for unit, size in UNITS if value % size == 0)
    return f"{value // multiplier}{unit}"


def refuse_negative(value: int) -> int:
    """Refuse a negative size, because the grammar has no way to write one down."""
    if value < 0:
        raise NegativeSize(value)
    return value


#: A size as a document writes it and as the code uses it: a whole number of bytes.
#:
#: The published schema names both spellings, because a document may write either and the
#: catalog check is what a document is validated against before it is ever run.
type Size = Annotated[
    int,
    BeforeValidator(parse_size),
    AfterValidator(refuse_negative),
    PlainSerializer(format_size, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "string", "pattern": SIZE_JSON_PATTERN},
                {"type": "integer", "minimum": 0},
            ],
            "format": "size",
        }
    ),
]
