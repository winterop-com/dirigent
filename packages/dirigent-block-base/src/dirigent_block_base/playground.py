"""``playground.generate``: a node that makes something happen, anywhere in a document.

At the start of a flow it needs nothing: its knobs generate rows, take a while, fail their
first attempts, or return a payload of a chosen size. In the middle it takes an input and
works from that value. At the end it is simply the last output, so a document may finish on
it. It reaches nothing: no connection, no URL, no network, no file.

The whole of Faker is reachable through the field map, which names a provider per field. A
provider name is therefore a string from a document that selects an attribute on a library
object, so it is never looked up directly: :func:`providers` builds the set of names the
installed Faker actually offers for a locale, and a name outside that set is refused before
anything is called. Nothing with a leading underscore is ever in the set.

Seeding is per instance, never the class-wide ``Faker.seed``: two steps generating at once
must not be able to reach into each other's sequence.
"""

import asyncio
import math
import random
import string
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, ClassVar, Final, cast

from faker import Faker
from faker.config import AVAILABLE_LOCALES
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import to_jsonable_python

from dirigent_block_base.messages import (
    FAILED_ON_PURPOSE,
    PROVIDER_REFUSED,
    UNKNOWN_LOCALE,
    UNKNOWN_PROVIDER,
)
from dirigent_common import BlockModel, Duration, Size
from dirigent_plugin import BlockFailure, ErrorClass, Operator, OperatorSpec, StepContext

#: The most records one call may generate. The routes are unauthenticated, so every knob
#: that costs work is bounded rather than left to the caller.
MAX_ROWS: Final = 1000

#: The most records one page may carry.
MAX_PAGE_SIZE: Final = 500

#: The largest filler payload one call may ask for.
MAX_PAYLOAD: Final = 1024 * 1024

#: The longest a call may be asked to take before answering.
MAX_DELAY: Final = timedelta(seconds=30)

#: The locale used when none is named.
DEFAULT_LOCALE: Final = "en_US"

#: What a call with no field map generates: enough to look like a row of real data, and
#: short enough to read whole in a log line.
DEFAULT_FIELDS: Final[dict[str, "FieldSpec"]] = {"name": "name", "email": "email", "city": "city"}


class ProviderCall(BlockModel):
    """A generated field whose provider takes arguments."""

    provider: str = Field(min_length=1)
    """The Faker provider that fills this field, by the name Faker knows it under."""

    args: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    """The keyword arguments handed to the provider, as Faker's own signature names them."""


type FieldSpec = str | ProviderCall
"""One field of a generated record: a provider name, or a provider name and its arguments."""


class Drift(StrEnum):
    """How a generated record departs from the shape the field map describes.

    The point of drift is a schema gate that can be seen catching something, so each one
    breaks a different kind of rule: a type, a required field, and a closed object.
    """

    NONE = "none"
    """The records match the field map exactly."""

    STRINGS = "strings"
    """Every number and boolean is rendered as a string, so a typed schema refuses it."""

    MISSING = "missing"
    """The field map's first field is left out, so a required-field schema refuses it."""

    EXTRA = "extra"
    """A field the map never named is added, so a closed schema refuses it."""


class Knobs(BlockModel):
    """Everything the playground can be asked for.

    Every knob defaults to something quiet, so a call that sets nothing still generates one
    row and answers at once.
    """

    fields: dict[str, FieldSpec] = Field(default_factory=lambda: dict(DEFAULT_FIELDS))
    """Which Faker provider fills each field of a generated record.

    A value is a provider name, or an object naming the provider and the arguments it takes.
    Every provider the installed Faker offers for the locale is reachable; ask an instance
    for the list rather than guessing.
    """

    rows: Annotated[int, Field(ge=0, le=MAX_ROWS)] = 1
    """How many records exist. Ignored when an input is supplied: the input decides."""

    locale: str = DEFAULT_LOCALE
    """The Faker locale the providers generate in."""

    seed: int | None = None
    """Makes the answer reproducible. Unset draws one, and the answer says which it drew."""

    drift: Drift = Drift.NONE
    """How the records depart from the field map, for a document teaching a schema gate."""

    page: Annotated[int, Field(ge=1)] | None = None
    """Which page of the records to answer with, counting from one; unset answers all of them."""

    size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)] | None = None
    """How many records a page holds. Unset with a page set means ten."""

    payload: Annotated[Size, Field(le=MAX_PAYLOAD)] | None = None
    """Return filler of this size beside the records, to push an output over a threshold."""

    delay: Annotated[Duration, Field(ge=timedelta(0), le=MAX_DELAY)] = timedelta(0)
    """How long to take before answering, for a document teaching a timeout or a deadline."""

    fail_until: Annotated[int, Field(ge=0)] = 0
    """Fail this many attempts before succeeding, for a document teaching a retry."""


class Generated(BlockModel):
    """What the playground made, and the knobs that decided it.

    Every knob comes back resolved: what the call actually ran with, after defaults and
    after the seed was drawn. The records are the answer; everything beside them says how
    the answer came to be.
    """

    records: list[JsonValue]
    """The records this answer carries: all of them, or one page when a page was asked for."""

    rows: int
    """How many records exist in total, which is more than ``records`` on a paged answer."""

    seed: int
    """The seed these records came from. Sending it back reproduces them exactly."""

    locale: str
    """The locale the providers generated in."""

    fields: dict[str, FieldSpec]
    """The field map the records were generated from."""

    drift: Drift
    """The drift applied to the records."""

    page: int | None = None
    """Which page this is, when one was asked for."""

    size: int | None = None
    """How many records a page holds, when one was asked for."""

    pages: int | None = None
    """How many pages there are in total, when one was asked for."""

    delay_ms: int = 0
    """How long this call waited before answering, in milliseconds."""

    attempt: int = 1
    """Which attempt produced this answer."""

    fail_until: int = 0
    """How many attempts were set to fail before this one was allowed to succeed."""

    payload: str | None = None
    """The filler that was asked for, when a payload size was set."""

    payload_bytes: int | None = None
    """How large that filler is, in bytes."""


class Providers(BaseModel):
    """Every provider name one locale offers, for a reader who cannot guess 250 of them."""

    locale: str
    """The locale these providers belong to."""

    providers: list[str]
    """Every name a field map may use, in alphabetical order."""


#: How many records a page holds when a page was asked for and no size was.
DEFAULT_PAGE_SIZE: Final = 10

#: The field a drifted record gains under ``extra``.
DRIFT_FIELD: Final = "drifted"

#: What fills a requested payload: a fixed repeating pattern, so a payload of a given size
#: is the same bytes on every run and a seed has nothing to decide about it.
FILLER: Final = string.ascii_lowercase + string.digits

#: Names a provider object carries that generate nothing: Faker's own plumbing, and the
#: seeding entry points a field map must never reach.
NOT_GENERATORS: Final = frozenset(
    {
        "add_provider",
        "format",
        "generator",
        "get_formatter",
        "get_providers",
        "locales",
        "optional",
        "passthrough",
        "provider",
        "random",
        "seed",
        "seed_instance",
        "seed_locale",
        "unique",
        "weights",
    }
)


class PlaygroundRefusal(BlockFailure):
    """A knob the playground cannot honour, which no retry would change.

    Carries the catalogued message as well as its rendering, so an HTTP route can answer
    with the same refusal envelope every other route answers with.
    """

    def __init__(self, message: Any, /, **params: Any) -> None:
        """Refuse with a catalogued message, classified so the engine never retries it."""
        super().__init__(message, error_class=ErrorClass.REJECTED, **params)
        self.catalogued = message


def locales() -> list[str]:
    """Every locale the installed Faker ships, in alphabetical order."""
    return sorted(AVAILABLE_LOCALES)


@lru_cache(maxsize=64)
def _catalogue(locale: str) -> frozenset[str]:
    """Every provider name one locale offers, read off the provider objects themselves.

    This is the allowlist a field map is checked against. It is built from the providers a
    Faker carries rather than from any attribute of the Faker object, so a name that is not
    a provider cannot be in it.
    """
    fake = _build(locale)
    names: set[str] = set()
    for provider in fake.get_providers():
        for name in dir(provider):
            if name.startswith("_") or name in NOT_GENERATORS:
                continue
            if callable(getattr(provider, name, None)):
                names.add(name)
    return frozenset(names)


def providers(locale: str = DEFAULT_LOCALE) -> Providers:
    """Every provider name a field map may use for one locale."""
    return Providers(locale=locale, providers=sorted(_catalogue(_checked(locale))))


def _checked(locale: str) -> str:
    """The locale, or a refusal naming it."""
    if locale not in AVAILABLE_LOCALES:
        raise PlaygroundRefusal(UNKNOWN_LOCALE, locale=locale)
    return locale


def _build(locale: str) -> Faker:
    """One Faker for one generation, never shared: seeding is per instance."""
    return Faker(locale)


def _jsonable(value: Any) -> JsonValue:
    """Render what a provider returned as JSON: many of them answer with Python objects.

    A ``Decimal`` keeps its precision and so comes back as a string; a provider whose value
    a schema reads as a number wants ``pyfloat`` or ``pyint``.
    """
    return cast("JsonValue", to_jsonable_python(value, fallback=str))


def _call(fake: Faker, spec: FieldSpec, locale: str) -> JsonValue:
    """Fill one field, having first checked that its provider is one this locale offers."""
    provider = spec.provider if isinstance(spec, ProviderCall) else spec
    args = dict(spec.args) if isinstance(spec, ProviderCall) else {}
    if provider not in _catalogue(locale):
        raise PlaygroundRefusal(UNKNOWN_PROVIDER, provider=provider, locale=locale)
    try:
        return _jsonable(fake.format(provider, **args))
    except PlaygroundRefusal:
        raise
    except Exception as error:
        raise PlaygroundRefusal(PROVIDER_REFUSED, provider=provider, detail=str(error)) from error


def _record(fake: Faker, fields: dict[str, FieldSpec], locale: str) -> dict[str, JsonValue]:
    """One generated record, in the field map's own order."""
    return {name: _call(fake, spec, locale) for name, spec in fields.items()}


def _stringify(value: JsonValue) -> JsonValue:
    """Render every number and boolean as a string, however deeply it sits."""
    match value:
        case bool() | int() | float():
            return str(value)
        case dict():
            return {key: _stringify(item) for key, item in value.items()}
        case list():
            return [_stringify(item) for item in value]
        case _:
            return value


def _drifted(record: JsonValue, drift: Drift, first: str | None) -> JsonValue:
    """Apply one drift to one record, leaving a record that is not a mapping alone."""
    if drift is Drift.NONE or not isinstance(record, dict):
        return record
    match drift:
        case Drift.STRINGS:
            return _stringify(record)
        case Drift.MISSING:
            return {key: value for key, value in record.items() if key != first}
        case Drift.EXTRA:
            return {**record, DRIFT_FIELD: True}
        case _:  # pragma: no cover - the enum has no fourth member
            return record


def filler(size: int) -> str:
    """A payload of exactly this many bytes, from a fixed repeating pattern."""
    repeats = size // len(FILLER) + 1
    return (FILLER * repeats)[:size]


def _base(knobs: Knobs, fake: Faker, supplied: JsonValue | None, extend: bool) -> list[JsonValue]:
    """The records before drift and paging: generated from the knobs, or built from an input.

    An input is the data, so it decides how many records there are and ``rows`` is not
    consulted. Generated fields are added to each element only when the caller named them.
    """
    if supplied is None:
        return [_record(fake, knobs.fields, knobs.locale) for _ in range(knobs.rows)]
    elements = supplied if isinstance(supplied, list) else [supplied]
    if not extend:
        return list(elements)
    return [_extended(fake, knobs, element) for element in elements]


def _extended(fake: Faker, knobs: Knobs, element: JsonValue) -> JsonValue:
    """One element of a supplied input, with the named fields generated onto it."""
    generated = _record(fake, knobs.fields, knobs.locale)
    if isinstance(element, dict):
        return {**element, **generated}
    return {"value": element, **generated}


def build(knobs: Knobs, *, supplied: JsonValue | None = None, extend: bool = False, attempt: int = 1) -> Generated:
    """Generate one answer from one set of knobs, and say which knobs produced it.

    ``extend`` says whether a supplied input has generated fields added to it, which is what
    distinguishes a document that named a field map from one that only passed a value
    through.
    """
    locale = _checked(knobs.locale)
    seed = knobs.seed if knobs.seed is not None else random.randrange(2**31)
    fake = _build(locale)
    fake.seed_instance(seed)

    records = _base(knobs, fake, supplied, extend)
    first = next(iter(knobs.fields), None)
    records = [_drifted(record, knobs.drift, first) for record in records]
    rows = len(records)

    page, size, pages = _paging(knobs, rows)
    if page is not None and size is not None:
        records = records[(page - 1) * size : page * size]

    payload = filler(knobs.payload) if knobs.payload is not None else None
    return Generated(
        records=records,
        rows=rows,
        seed=seed,
        locale=locale,
        fields=knobs.fields,
        drift=knobs.drift,
        page=page,
        size=size,
        pages=pages,
        delay_ms=round(knobs.delay.total_seconds() * 1000),
        attempt=attempt,
        fail_until=knobs.fail_until,
        payload=payload,
        payload_bytes=None if payload is None else len(payload),
    )


def _paging(knobs: Knobs, rows: int) -> tuple[int | None, int | None, int | None]:
    """The page, its size, and how many pages there are, or three nulls when unpaged."""
    if knobs.page is None and knobs.size is None:
        return None, None, None
    page = knobs.page if knobs.page is not None else 1
    size = knobs.size if knobs.size is not None else DEFAULT_PAGE_SIZE
    return page, size, math.ceil(rows / size) if rows else 0


def check_attempt(knobs: Knobs, attempt: int) -> None:
    """Fail on purpose while the attempt is inside the failing window.

    Classified transient, because the point of the knob is a retry example, and a retry is
    what the engine does with a transient failure.
    """
    if attempt <= knobs.fail_until:
        raise BlockFailure(
            FAILED_ON_PURPOSE,
            error_class=ErrorClass.TRANSIENT,
            attempt=attempt,
            fail_until=knobs.fail_until,
            next_attempt=knobs.fail_until + 1,
        )


async def wait(knobs: Knobs) -> None:
    """Take as long as the delay knob asks for, without holding the loop."""
    if knobs.delay > timedelta(0):
        await asyncio.sleep(knobs.delay.total_seconds())


class PlaygroundConfig(Knobs):
    """The knobs, plus the value this node works from when there is one upstream.

    ``input`` is the field every transform names for the same idea, and it means the same
    thing here -- except that it is optional, because this node is often a document's first
    step and has only its knobs to work from.
    """

    input: JsonValue = None
    """The value to work on, written inline or referenced from an earlier step's output.

    Left out, the node generates from its knobs alone, which is what a first step does. A
    list arrives as one record per element and an object or a scalar as a single record. An
    element gains the generated fields only when ``fields`` is named, so a node that names
    no fields passes its input through unchanged."""


class PlaygroundOutput(Generated):
    """The records, and every knob that produced them.

    The knobs come back resolved rather than as written, so the seed a run drew is on the
    output and the run can be reproduced by sending it back.
    """

    input_rows: int | None = None
    """How many elements the input carried, or null when the node generated its own records.

    The values themselves are in ``records``, so they are not repeated here."""


class PlaygroundOperator(Operator[PlaygroundConfig, PlaygroundOutput]):
    """Generates rows, takes a while, fails on purpose, or pads its output, on demand.

    Every knob is deterministic given a seed, so a document that verifies gets the same
    answer on every run. With no seed the node draws one and reports it, so a surprising
    answer can be reproduced.

    It is not idempotent, because ``fail_until`` deliberately answers differently on a
    later attempt of the same step.
    """

    spec = OperatorSpec(
        id="playground.generate",
        summary="Generate rows, a delay, a failure, or a payload, with nothing to call.",
        local_execution=False,
    )
    config_model: ClassVar[type[BaseModel]] = PlaygroundConfig
    output_model: ClassVar[type[BaseModel]] = PlaygroundOutput

    async def execute(self, config: PlaygroundConfig, ctx: StepContext) -> PlaygroundOutput:
        """Wait, decide whether this attempt is one of the failing ones, and then generate."""
        await wait(config)
        check_attempt(config, ctx.attempt)
        generated = build(
            config,
            supplied=config.input,
            extend="fields" in config.model_fields_set,
            attempt=ctx.attempt,
        )
        ctx.log.info(
            "playground generated",
            rows=generated.rows,
            seed=generated.seed,
            locale=generated.locale,
            drift=generated.drift.value,
        )
        return PlaygroundOutput(
            **generated.model_dump(),
            input_rows=_input_rows(config.input),
        )


def _input_rows(supplied: JsonValue) -> int | None:
    """How many elements an input carried, counting a non-list as one and nothing as none."""
    if supplied is None:
        return None
    return len(supplied) if isinstance(supplied, list) else 1
