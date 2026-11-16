"""The one conversion every block spells a non-JSON value with."""

import datetime
import decimal
import enum
import json
import uuid
from pathlib import PurePosixPath

import pytest
from pydantic import BaseModel

from dirigent_common import loggable, spelled
from dirigent_common.values import LOGGED_BYTES, LOGGED_DEPTH, LOGGED_REPR_CHARS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime.date(2026, 9, 6), "2026-09-06"),
        (datetime.time(13, 45), "13:45:00"),
        (datetime.datetime(2026, 9, 6, 13, 45, tzinfo=datetime.UTC), "2026-09-06T13:45:00+00:00"),
        (datetime.timedelta(minutes=90), 5400.0),
        (decimal.Decimal("1.250"), "1.250"),
        (uuid.UUID("0f6dc0b6-6f4a-4a5d-9f36-5f1f0f16b2f6"), "0f6dc0b6-6f4a-4a5d-9f36-5f1f0f16b2f6"),
        (b"\x00\x01\x02", "AAEC"),
        (bytearray(b"\x00\x01\x02"), "AAEC"),
        (memoryview(b"\x00\x01\x02"), "AAEC"),
        (float("nan"), None),
        (float("inf"), None),
        (None, None),
        (True, True),
        (7, 7),
        (1.5, 1.5),
        ("already text", "already text"),
    ],
)
def test_a_value_gets_the_spelling_every_block_agrees_on(value: object, expected: object) -> None:
    assert spelled(value) == expected


def test_a_decimal_keeps_its_digits_rather_than_being_rounded_through_a_float() -> None:
    assert spelled(decimal.Decimal("0.1234567890123456789")) == "0.1234567890123456789"


def test_a_value_with_no_json_spelling_names_its_type() -> None:
    with pytest.raises(ValueError, match="object has no JSON spelling"):
        spelled(object())


class Shade(enum.Enum):
    """An enum whose values are not text."""

    DARK = 2


class Reading(BaseModel):
    """A model holding values a log field cannot hold as they are."""

    at: datetime.date
    tags: set[str]


class Opaque:
    """A value nothing knows how to spell."""

    def __repr__(self) -> str:
        """Name the value."""
        return "Opaque()"


class Loud:
    """A value whose repr goes on for a long time."""

    def __repr__(self) -> str:
        """Say a great deal."""
        return "x" * (LOGGED_REPR_CHARS * 2)


class Broken:
    """A value whose repr raises."""

    def __repr__(self) -> str:
        """Fail."""
        raise RuntimeError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (7, 7),
        (1.5, 1.5),
        ("text", "text"),
        ({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}),
        (datetime.datetime(2026, 9, 6, 13, 45, tzinfo=datetime.UTC), "2026-09-06T13:45:00+00:00"),
        (datetime.date(2026, 9, 6), "2026-09-06"),
        (decimal.Decimal("1.250"), "1.250"),
        (uuid.UUID("0f6dc0b6-6f4a-4a5d-9f36-5f1f0f16b2f6"), "0f6dc0b6-6f4a-4a5d-9f36-5f1f0f16b2f6"),
        ({3, 1, 2}, [1, 2, 3]),
        (frozenset({"b", "a"}), ["a", "b"]),
        ((1, "two"), [1, "two"]),
        (b"\x00\x01\x02", "AAEC"),
        (b"x" * (LOGGED_BYTES + 1), f"<{LOGGED_BYTES + 1} bytes>"),
        (float("nan"), "NaN"),
        (float("inf"), "Infinity"),
        (float("-inf"), "-Infinity"),
        (Reading(at=datetime.date(2026, 9, 6), tags={"a"}), {"at": "2026-09-06", "tags": ["a"]}),
        (Shade.DARK, 2),
        (PurePosixPath("/srv/data"), "/srv/data"),
        (Opaque(), "Opaque()"),
        ({1: "one", datetime.date(2026, 9, 6): "day"}, {"1": "one", "2026-09-06": "day"}),
        ([{"when": datetime.date(2026, 9, 6), "ratio": float("nan")}], [{"when": "2026-09-06", "ratio": "NaN"}]),
    ],
)
def test_a_log_field_takes_a_json_shape_whatever_it_is(value: object, expected: object) -> None:
    shaped = loggable(value)
    assert shaped == expected
    json.dumps(shaped, allow_nan=False)


def test_a_log_field_cuts_a_long_repr_and_survives_one_that_raises() -> None:
    assert loggable(Loud()) == f"{'x' * LOGGED_REPR_CHARS} [truncated, {LOGGED_REPR_CHARS * 2} characters]"
    assert loggable(Broken()) == "<Broken>"


def test_a_log_field_that_holds_itself_ends_in_a_repr() -> None:
    held: list[object] = []
    held.append(held)
    shaped = loggable(held)
    for _ in range(LOGGED_DEPTH):
        assert isinstance(shaped, list)
        shaped = shaped[0]
    assert shaped == "[[...]]"
