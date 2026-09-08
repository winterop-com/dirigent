"""Humane durations: what a document may write, and how it comes back out."""

import random
from datetime import timedelta
from typing import cast

import pytest
from pydantic import BaseModel, Field, ValidationError
from pydantic.json_schema import JsonSchemaMode

from dirigent_common.durations import (
    DURATION_JSON_PATTERN,
    DURATION_PATTERN,
    Duration,
    DurationError,
    HumaneJsonSchema,
    NegativeDuration,
    format_duration,
    parse_duration,
)
from dirigent_core.engine.definition import RetryPolicy, ScheduleSpec, StepDefinition


class Timed(BaseModel):
    every: Duration


class Budgeted(BaseModel):
    """The three shapes a duration field takes: bounded, bare, and optional."""

    timeout: Duration = Field(default=timedelta(minutes=5), gt=timedelta(0))
    grace: Duration = timedelta(seconds=10)
    recycle: Duration | None = timedelta(minutes=30)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", timedelta(seconds=30)),
        ("5m", timedelta(minutes=5)),
        ("6h", timedelta(hours=6)),
        ("2d", timedelta(days=2)),
        ("1w", timedelta(weeks=1)),
        ("250ms", timedelta(milliseconds=250)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("1d2h3m4s", timedelta(days=1, hours=2, minutes=3, seconds=4)),
        ("0s", timedelta()),
        ("90", timedelta(seconds=90)),
        ("1.5s", timedelta(milliseconds=1500)),
    ],
)
def test_durations_a_document_may_write(text: str, expected: timedelta) -> None:
    assert Timed(every=text).every == expected  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("text", ["", "later", "5 minutes", "5x", "m5", "PT5M", "-"])
def test_durations_the_format_refuses(text: str) -> None:
    with pytest.raises(ValidationError):
        Timed(every=text)  # pyright: ignore[reportArgumentType]


def test_a_number_is_read_as_seconds_so_the_obvious_thing_works() -> None:
    assert Timed(every=30).every == timedelta(seconds=30)  # pyright: ignore[reportArgumentType]
    assert Timed(every=timedelta(minutes=2)).every == timedelta(minutes=2)


def test_a_boolean_is_not_a_duration() -> None:
    with pytest.raises(DurationError):
        parse_duration(True)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (timedelta(), "0s"),
        (timedelta(seconds=30), "30s"),
        (timedelta(seconds=90), "1m30s"),
        (timedelta(hours=6), "6h"),
        (timedelta(days=8), "1w1d"),
        (timedelta(milliseconds=250), "250ms"),
    ],
)
def test_a_duration_has_exactly_one_spelling(value: timedelta, text: str) -> None:
    assert format_duration(value) == text


@pytest.mark.parametrize(
    "text",
    ["30s", "5m", "6h", "2d", "1w", "250ms", "1h30m", "1d2h3m4s", "0s"],
)
def test_rendering_is_the_inverse_of_parsing(text: str) -> None:
    parsed = Timed(every=text).every  # pyright: ignore[reportArgumentType]
    assert Timed(every=format_duration(parsed)).every == parsed  # pyright: ignore[reportArgumentType]


def test_a_duration_serializes_to_the_humane_form_in_json() -> None:
    assert Timed(every=timedelta(minutes=90)).model_dump(mode="json") == {"every": "1h30m"}
    assert Timed(every=timedelta(minutes=90)).model_dump() == {"every": timedelta(minutes=90)}


#: The document format's six duration-typed fields.
DURATION_FIELDS = ("backoff", "max_backoff", "timeout", "poll", "deadline", "interval")


def duration_samples(count: int = 3000) -> list[timedelta]:
    """Build the values the round-trip property is checked over: edges, then a seeded sweep."""
    edges = [
        timedelta(0),
        timedelta(milliseconds=1),
        timedelta(milliseconds=999),
        timedelta(seconds=1),
        timedelta(seconds=59),
        timedelta(seconds=60),
        timedelta(minutes=59, seconds=59),
        timedelta(hours=1),
        timedelta(hours=23, minutes=59),
        timedelta(days=1),
        timedelta(days=6, hours=23),
        timedelta(weeks=1),
        timedelta(weeks=52),
    ]
    generator = random.Random(20260829)
    sweep = [timedelta(seconds=round(generator.uniform(0.0, 60 * 60 * 24 * 400), 3)) for _ in range(count)]
    return [*edges, *sweep]


def test_every_duration_the_export_writes_can_be_read_back() -> None:
    """The canonical export is only byte-stable if rendering is the exact inverse of parsing."""
    for original in duration_samples():
        rendered = format_duration(original)
        assert DURATION_PATTERN.match(rendered), f"{original!r} rendered as {rendered!r}, which is not in the grammar"
        assert parse_duration(rendered) == original, f"{rendered!r} did not read back as {original!r}"
        assert format_duration(cast("timedelta", parse_duration(rendered))) == rendered


@pytest.mark.parametrize("field", DURATION_FIELDS)
def test_every_duration_field_accepts_what_the_renderer_writes(field: str) -> None:
    """The six fields share one type, so this is what says which fields that type reaches."""
    owners: dict[str, tuple[type[BaseModel], dict[str, object]]] = {
        "backoff": (RetryPolicy, {}),
        "max_backoff": (RetryPolicy, {}),
        "timeout": (StepDefinition, {"block": "test.echo"}),
        "poll": (StepDefinition, {"block": "test.echo"}),
        "deadline": (StepDefinition, {"block": "test.echo"}),
        "interval": (ScheduleSpec, {"code": "nightly"}),
    }
    model, base = owners[field]
    validated = model.model_validate({**base, field: format_duration(timedelta(seconds=5430.25))})
    assert getattr(validated, field) == timedelta(seconds=5430.25)


def test_a_negative_duration_is_refused_rather_than_rendered_unreadably() -> None:
    """A minus sign is not in the grammar, so a negative duration could not round trip."""
    with pytest.raises(NegativeDuration):
        format_duration(timedelta(seconds=-30))
    with pytest.raises(ValidationError, match="is negative"):
        RetryPolicy(backoff=timedelta(seconds=-1))


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_the_published_schema_is_the_humane_grammar(mode: JsonSchemaMode) -> None:
    """A form built from the schema has to offer the spelling the document writes."""
    schema = Budgeted.model_json_schema(mode=mode, schema_generator=HumaneJsonSchema)
    assert schema["$defs"]["Duration"] == {
        "type": "string",
        "pattern": DURATION_JSON_PATTERN,
        "format": "humane-duration",
    }


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_a_published_default_is_written_the_way_a_document_writes_it(mode: JsonSchemaMode) -> None:
    """Whatever shape the field takes, its default is a duration a person could have typed."""
    properties = Budgeted.model_json_schema(mode=mode, schema_generator=HumaneJsonSchema)["properties"]
    assert properties["timeout"]["default"] == "5m"
    assert properties["grace"]["default"] == "10s"
    assert properties["recycle"]["default"] == "30m"


def test_a_bound_on_a_duration_is_not_published_as_a_keyword() -> None:
    """JSON Schema has no keyword for one, and pydantic's leftover ``gt`` is not one either."""
    published = Budgeted.model_json_schema(schema_generator=HumaneJsonSchema)["properties"]["timeout"]
    assert "gt" not in published
