"""Humane sizes: what a document may write, and how it comes back out."""

import random
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError

from dirigent_common.sizes import (
    SIZE_PATTERN,
    NegativeSize,
    Size,
    SizeError,
    format_size,
    parse_size,
    refuse_negative,
)


class Bounded(BaseModel):
    cap: Size


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0b", 0),
        ("1b", 1),
        ("512kb", 512 * 1024),
        ("64mb", 64 * 1024 * 1024),
        ("2gb", 2 * 1024**3),
        ("1tb", 1024**4),
        ("64mib", 64 * 1024 * 1024),
        ("2gib", 2 * 1024**3),
        ("512kib", 512 * 1024),
        ("1tib", 1024**4),
        ("64MB", 64 * 1024 * 1024),
        ("2GiB", 2 * 1024**3),
        ("1.5gb", 1536 * 1024 * 1024),
        ("0.5kb", 512),
        ("4096", 4096),
        ("0", 0),
    ],
)
def test_a_size_a_document_may_write_reads_as_that_many_bytes(text: str, expected: int) -> None:
    assert parse_size(text) == expected
    assert Bounded(cap=cast("Size", text)).cap == expected


def test_the_two_unit_families_are_the_same_number() -> None:
    """Kb and kib both mean 1024 bytes, which is what an operator means by either."""
    for short, long in (("kb", "kib"), ("mb", "mib"), ("gb", "gib"), ("tb", "tib")):
        assert parse_size(f"7{short}") == parse_size(f"7{long}")


@pytest.mark.parametrize("value", [0, 1, 4096, 67108864])
def test_a_bare_number_is_a_count_of_bytes(value: int) -> None:
    assert parse_size(value) == value
    assert Bounded(cap=value).cap == value


@pytest.mark.parametrize(
    "text",
    ["", "abc", "mb", "64 mb", "64m", "1pb", "1.5b", "0.5b", "nan", "inf", "-1kb", "64mb64kb"],
)
def test_a_size_the_grammar_does_not_define_is_refused(text: str) -> None:
    with pytest.raises(SizeError):
        parse_size(text)
    with pytest.raises(ValidationError):
        Bounded(cap=cast("Size", text))


def test_a_boolean_is_not_a_size() -> None:
    """True is an int in Python, and a document that wrote one meant something else."""
    with pytest.raises(SizeError):
        parse_size(True)


def test_a_negative_size_is_refused_wherever_it_arrives() -> None:
    """Parsing is the permissive half and the validator is the gate, exactly as durations are."""
    with pytest.raises(NegativeSize):
        format_size(-1)
    with pytest.raises(NegativeSize):
        refuse_negative(cast("int", parse_size("-1")))
    with pytest.raises(ValidationError):
        Bounded(cap=-4096)
    with pytest.raises(ValidationError):
        Bounded(cap=cast("Size", "-1"))


def test_a_fraction_of_a_byte_is_refused() -> None:
    with pytest.raises(SizeError):
        parse_size(1.5)


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        (0, "0b"),
        (1, "1b"),
        (1023, "1023b"),
        (1024, "1kb"),
        (1536, "1536b"),
        (64 * 1024 * 1024, "64mb"),
        (1536 * 1024 * 1024, "1536mb"),
        (1024**4, "1tb"),
        (16384, "16kb"),
    ],
)
def test_a_size_renders_in_the_largest_unit_that_divides_it_exactly(value: int, rendered: str) -> None:
    assert format_size(value) == rendered


def size_samples(count: int = 400) -> list[int]:
    """Edge cases plus a deterministic sweep, so the round trip is exercised broadly."""
    edges = [0, 1, 1023, 1024, 1025, 1024**2, 1024**2 + 1, 1024**3, 1024**4, 6 * 1024**2, 16384]
    generator = random.Random(20260829)
    return [*edges, *[generator.randrange(0, 8 * 1024**3) for _ in range(count)]]


def test_every_size_the_export_writes_can_be_read_back() -> None:
    """The canonical export is only byte-stable if rendering is the exact inverse of parsing."""
    for original in size_samples():
        rendered = format_size(original)
        assert SIZE_PATTERN.match(rendered), f"{original!r} rendered as {rendered!r}, which is not in the grammar"
        assert parse_size(rendered) == original, f"{rendered!r} did not read back as {original!r}"
        assert format_size(cast("int", parse_size(rendered))) == rendered


def test_a_size_serialises_as_the_humane_string_and_stays_an_int_in_python() -> None:
    held = Bounded(cap=cast("Size", "64mb"))
    assert held.cap == 67108864
    assert held.model_dump(mode="json") == {"cap": "64mb"}
    assert held.model_dump() == {"cap": 67108864}


def test_the_published_schema_names_both_spellings() -> None:
    """A document may write either form, so the catalog check has to accept either."""
    schema = Bounded.model_json_schema(mode="serialization")
    published = schema["$defs"]["Size"]["anyOf"]
    assert {entry["type"] for entry in published} == {"string", "integer"}
    assert schema["$defs"]["Size"]["format"] == "size", "what tells a form to speak of sizes, not of types"
