"""The one conversion every block spells a non-JSON value with."""

import datetime
import decimal
import uuid

import pytest

from dirigent_common import spelled


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
