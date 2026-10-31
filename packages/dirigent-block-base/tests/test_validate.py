"""Tests for ``validate.schema``."""

import asyncio
import threading
import time
from collections.abc import Awaitable
from typing import Any

import pytest

from dirigent_block_base import validate
from dirigent_block_base.validate import ValidateSchemaConfig, ValidateSchemaOperator, ValidateSchemaOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

#: An object schema a payload either fits or does not, reused across the cases below.
SCHEMA = {
    "type": "object",
    "required": ["id", "level"],
    "properties": {"id": {"type": "string"}, "level": {"type": "integer"}},
}


async def test_a_value_that_fits_is_returned_unchanged(ctx: FakeContext) -> None:
    """The gate is a waypoint: what fits comes out the far side exactly as it went in."""
    ctx.schemas["ou-shape"] = SCHEMA
    payload = {"id": "OU1", "level": 2}
    output = await call_block(ValidateSchemaOperator(), {"input": payload, "schema": "ou-shape"}, ctx)
    assert isinstance(output, ValidateSchemaOutput)
    assert output.value == payload


async def test_a_schema_cannot_make_the_worker_fetch_a_url(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reference nothing local answers is the schema's fault, so retrying it cannot help."""
    asked: list[object] = []

    def recorded(request: object, *_: object, **__: object) -> None:
        asked.append(request)
        raise OSError("a schema reached for the network")

    monkeypatch.setattr("urllib.request.urlopen", recorded)
    ctx.schemas["remote"] = {"$ref": "http://169.254.169.254/latest/meta-data/"}
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": {"id": "OU1"}, "schema": "remote"}, ctx)
    assert asked == []
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "169.254.169.254" in raised.value.message


async def test_a_schema_keeps_the_references_it_holds_itself(ctx: FakeContext) -> None:
    ctx.schemas["local"] = {"$defs": {"id": {"type": "string"}}, "properties": {"id": {"$ref": "#/$defs/id"}}}
    output = await call_block(ValidateSchemaOperator(), {"input": {"id": "OU1"}, "schema": "local"}, ctx)
    assert isinstance(output, ValidateSchemaOutput)


async def test_a_missing_field_is_rejected_naming_the_root(ctx: FakeContext) -> None:
    ctx.schemas["ou-shape"] = SCHEMA
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": {"id": "OU1"}, "schema": "ou-shape"}, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == "at $: 'level' is a required property"


async def test_a_wrong_type_is_rejected_naming_the_path(ctx: FakeContext) -> None:
    ctx.schemas["ou-shape"] = SCHEMA
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": {"id": "OU1", "level": "two"}, "schema": "ou-shape"}, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == "at $.level: 'two' is not of type 'integer'"


async def test_a_format_asserts_not_merely_annotates(ctx: FakeContext) -> None:
    """A gate that asserts formats rather than annotating them.

    format: uuid7 gates -- a v4 is refused, a v7 passes. The block wires the format checker;
    without it jsonschema treats format as annotation and lets anything through.
    """
    ctx.schemas["id-shape"] = {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string", "format": "uuid7"}},
    }
    v4 = "437fd893-1202-44cf-a1a8-fe58310ef065"
    v7 = "01920000-0000-7000-8000-000000000000"
    with pytest.raises(BlockFailure) as refused:
        await call_block(ValidateSchemaOperator(), {"input": {"id": v4}, "schema": "id-shape"}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "uuid7" in str(refused.value)
    passed = await call_block(ValidateSchemaOperator(), {"input": {"id": v7}, "schema": "id-shape"}, ctx)
    assert isinstance(passed, ValidateSchemaOutput)


async def test_a_contributed_format_asserts_through_the_gate(ctx: FakeContext) -> None:
    """A format a pack contributes gates just as a base one does, once installed on the context.

    ``even-digits`` stands in for a pack's own format such as ``acme-site-id``: a value that
    fails the predicate is refused, one that passes comes through.
    """
    ctx.formats["even-digits"] = lambda value: isinstance(value, str) and len(value) % 2 == 0
    ctx.schemas["code-shape"] = {
        "type": "object",
        "required": ["code"],
        "properties": {"code": {"type": "string", "format": "even-digits"}},
    }
    with pytest.raises(BlockFailure) as refused:
        await call_block(ValidateSchemaOperator(), {"input": {"code": "abc"}, "schema": "code-shape"}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "even-digits" in str(refused.value)
    passed = await call_block(ValidateSchemaOperator(), {"input": {"code": "abcd"}, "schema": "code-shape"}, ctx)
    assert isinstance(passed, ValidateSchemaOutput)


async def test_an_uncontributed_format_only_annotates(ctx: FakeContext) -> None:
    """A format no pack contributes stays a passing annotation, so a schema is portable.

    ``format: acme-site-id`` on an instance without that pack asserts nothing: the value
    is valid, just unchecked, which is jsonschema's own behaviour for an unknown format.
    """
    ctx.schemas["site-shape"] = {
        "type": "object",
        "required": ["site"],
        "properties": {"site": {"type": "string", "format": "acme-site-id"}},
    }
    output = await call_block(
        ValidateSchemaOperator(), {"input": {"site": "not a site id at all"}, "schema": "site-shape"}, ctx
    )
    assert isinstance(output, ValidateSchemaOutput)
    assert output.value == {"site": "not a site id at all"}


async def test_a_nested_failure_names_the_deep_path(ctx: FakeContext) -> None:
    """The path into the payload is what makes a failure at the boundary worth reading."""
    ctx.schemas["units-shape"] = {
        "type": "object",
        "properties": {"units": {"type": "array", "items": {"type": "string"}}},
    }
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": {"units": ["ok", 7]}, "schema": "units-shape"}, ctx)
    assert raised.value.message == "at $.units[1]: 7 is not of type 'string'"


async def test_a_null_input_is_a_value_the_schema_judges(ctx: FakeContext) -> None:
    ctx.schemas["null-shape"] = {"type": "null"}
    output = await call_block(ValidateSchemaOperator(), {"input": None, "schema": "null-shape"}, ctx)
    assert isinstance(output, ValidateSchemaOutput)
    assert output.value is None


def test_the_document_writes_the_schema_key() -> None:
    """A document says ``schema``; the Python attribute is renamed only to dodge a pydantic clash."""
    published = ValidateSchemaConfig.model_json_schema(mode="serialization")
    assert set(published["properties"]) == {"input", "schema", "timeout"}
    assert published["additionalProperties"] is False


def test_a_gate_needs_a_schema_code() -> None:
    """The schema is a required code; a gate that names none is refused."""
    with pytest.raises(ValueError):
        ValidateSchemaConfig.model_validate({"input": None})


def test_check_config_has_nothing_to_add() -> None:
    """A named schema was validated when it was stored or applied, so check_config is empty."""
    config = ValidateSchemaConfig.model_validate({"input": None, "schema": "ou-shape"})
    assert ValidateSchemaOperator().check_config(config) == []


def test_the_schema_field_says_it_names_a_schema() -> None:
    """A form generated from this schema draws the named schema under the box holding its code."""
    published = ValidateSchemaConfig.model_json_schema(mode="serialization")
    named = str(published["properties"]["schema"]["$ref"]).removeprefix("#/$defs/")
    assert published["$defs"][named]["x-dirigent-ref"] == "schema"


@pytest.mark.parametrize(
    "items",
    [
        [1, 1],
        [1, 1.0],
        ["a", "a"],
        [None, None],
        [True, True],
        [[1], [1.0]],
        [{"a": 1, "b": 2}, {"b": 2.0, "a": 1}],
        [{"a": [1, {"b": 2}]}, {"a": [1.0, {"b": 2}]}],
        [1, "mixed", 1],
    ],
)
async def test_unique_items_refuses_what_json_schema_calls_equal(ctx: FakeContext, items: list[Any]) -> None:
    ctx.schemas["distinct"] = {"uniqueItems": True}
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": items, "schema": "distinct"}, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "non-unique" in raised.value.message


@pytest.mark.parametrize(
    "items",
    [
        [],
        [1, 2],
        [True, 1],
        [False, 0],
        ["1", 1],
        [None, 0, False, "", [], {}],
        [[True], [1]],
        [{"a": True}, {"a": 1}],
        [{"a": 1}, {"b": 1}],
        [1.5, 2.5],
        [1, 1.5, "mixed"],
    ],
)
async def test_unique_items_passes_what_json_schema_calls_different(ctx: FakeContext, items: list[Any]) -> None:
    ctx.schemas["distinct"] = {"uniqueItems": True}
    output = await call_block(ValidateSchemaOperator(), {"input": items, "schema": "distinct"}, ctx)
    assert isinstance(output, ValidateSchemaOutput)
    assert output.value == items


async def test_unique_items_passes_when_a_schema_turns_it_off(ctx: FakeContext) -> None:
    ctx.schemas["any"] = {"uniqueItems": False}
    output = await call_block(ValidateSchemaOperator(), {"input": [1, 1], "schema": "any"}, ctx)
    assert isinstance(output, ValidateSchemaOutput)


@pytest.mark.parametrize(
    "schema",
    [
        {"uniqueItems": True},
        {"properties": {"list": {"uniqueItems": True}}},
        {"$defs": {"list": {"uniqueItems": True}}, "properties": {"list": {"$ref": "#/$defs/list"}}},
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "uniqueItems": True,
            "items": {"anyOf": [{"$ref": "#"}, {"type": ["integer", "string"]}]},
        },
    ],
    ids=["at-the-root", "in-a-subschema", "behind-a-reference", "behind-a-reference-to-the-root"],
)
async def test_unique_items_never_compares_every_pair(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, schema: dict[str, Any]
) -> None:
    """The library's pairwise comparison is its ``uniq``, and an array holding one string falls back to it."""

    def refused(_: object) -> bool:
        raise AssertionError("the library's pairwise comparison ran")

    monkeypatch.setattr("jsonschema._keywords.uniq", refused)
    ctx.schemas["distinct"] = schema
    items: list[Any] = [*range(2000), "mixed"]
    value: Any = {"list": items} if "properties" in schema else items
    output = await call_block(ValidateSchemaOperator(), {"input": value, "schema": "distinct"}, ctx)
    assert isinstance(output, ValidateSchemaOutput)


async def test_a_step_timeout_fires_while_a_value_is_being_evaluated(ctx: FakeContext) -> None:
    """The evaluation is held inside a format check until the timeout has been seen to fire."""
    entered = threading.Event()
    release = threading.Event()

    def held(value: object) -> bool:
        entered.set()
        release.wait(10)
        return True

    ctx.formats["held"] = held
    ctx.schemas["slow"] = {"format": "held"}
    try:
        call = call_block(ValidateSchemaOperator(), {"input": "value", "schema": "slow"}, ctx)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(call, timeout=0.2)
        assert entered.is_set(), "the evaluation began, so what fired was the timeout over it"
        assert not release.is_set(), "and the loop turned with the evaluation still in progress"
    finally:
        release.set()


#: A pattern every engine that backtracks takes time exponential in the run of ``a`` it reads.
BACKTRACKING = "^(a|aa)+$"


def _backtracked(length: int) -> str:
    """A string ``BACKTRACKING`` reads every way it can split before it fails to match."""
    return "a" * length + "!"


async def _longest_pause(call: Awaitable[Any]) -> tuple[float, float, BaseException | None]:
    """Run ``call`` beside a ticker; return the longest the loop went without turning, the whole, and what it raised."""
    task = asyncio.ensure_future(call)
    began = time.monotonic()
    longest = 0.0
    while not task.done():
        before = time.monotonic()
        await asyncio.sleep(0.01)
        longest = max(longest, time.monotonic() - before)
    whole = time.monotonic() - began
    return longest, whole, task.exception()


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        ({"pattern": BACKTRACKING}, _backtracked(32)),
        ({"patternProperties": {BACKTRACKING: {}}}, {_backtracked(32): 1}),
        ({"patternProperties": {BACKTRACKING: {}}, "additionalProperties": False}, {_backtracked(32): 1}),
        ({"propertyNames": {"pattern": BACKTRACKING}}, {_backtracked(32): 1}),
    ],
    ids=["pattern", "patternProperties", "additionalProperties", "propertyNames"],
)
async def test_a_backtracking_pattern_leaves_the_loop_turning(ctx: FakeContext, schema: Any, value: Any) -> None:
    """A match that takes the better part of a second never stops the loop for half of it."""
    ctx.schemas["backtracks"] = schema
    longest, whole, raised = await _longest_pause(
        call_block(ValidateSchemaOperator(), {"input": value, "schema": "backtracks"}, ctx)
    )
    assert raised is None or isinstance(raised, BlockFailure)
    assert longest < whole / 2, f"the loop stood still for {longest:.2f}s of {whole:.2f}s"


async def test_a_backtracking_pattern_fails_the_step_at_its_timeout(ctx: FakeContext) -> None:
    """A match that would run for minutes ends at the gate's timeout, refused rather than retried."""
    ctx.schemas["backtracks"] = {"pattern": BACKTRACKING}
    began = time.monotonic()
    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ValidateSchemaOperator(), {"input": _backtracked(44), "schema": "backtracks", "timeout": "200ms"}, ctx
        )
    assert time.monotonic() - began < 10
    assert raised.value.code == "base.value_unchecked"
    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == "the value was not checked against the schema within its timeout of 200ms"


async def test_a_schema_whose_cost_doubles_with_depth_fails_the_step_at_its_timeout(ctx: FakeContext) -> None:
    """Each level of this schema evaluates the level below twice, so forty levels never finish."""
    ctx.schemas["tree"] = {"additionalProperties": {"$ref": "#"}, "unevaluatedProperties": False}
    value: Any = {}
    for _ in range(40):
        value = {"child": value}
    began = time.monotonic()
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": value, "schema": "tree", "timeout": "300ms"}, ctx)
    assert time.monotonic() - began < 10
    assert raised.value.code == "base.value_unchecked"


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        ({"prefixItems": [True], "unevaluatedItems": False}, [*range(2000)]),
        ({"properties": {"k0": {}}, "unevaluatedProperties": False}, {f"k{index}": index for index in range(2000)}),
    ],
    ids=["unevaluatedItems", "unevaluatedProperties"],
)
async def test_unevaluated_keywords_never_scan_a_list_per_element(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, schema: Any, value: Any
) -> None:
    """The library's ``unevaluated*`` look each element up in a list its own helpers build."""

    def refused(*_: object) -> list[object]:
        raise AssertionError("the library's unevaluated lookup ran")

    monkeypatch.setattr("jsonschema._keywords.find_evaluated_item_indexes_by_schema", refused)
    monkeypatch.setattr("jsonschema._keywords.find_evaluated_property_keys_by_schema", refused)
    ctx.schemas["closed"] = schema
    with pytest.raises(BlockFailure) as raised:
        await call_block(ValidateSchemaOperator(), {"input": value, "schema": "closed"}, ctx)
    assert raised.value.code == "base.value_refused"
    assert "Unevaluated" in raised.value.message


async def test_a_cancelled_step_stops_its_check_at_the_next_keyword(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check held in its first format is cancelled; released, it checks nothing more."""
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    checked: list[object] = []

    def held(value: object) -> bool:
        checked.append(value)
        entered.set()
        release.wait(10)
        return True

    evaluate = validate._earliest_error  # pyright: ignore[reportPrivateUsage]

    def observed(*arguments: Any) -> Any:
        try:
            return evaluate(*arguments)
        finally:
            finished.set()

    monkeypatch.setattr(validate, "_earliest_error", observed)
    ctx.formats["held"] = held
    ctx.schemas["slow"] = {"items": {"format": "held"}}
    task = asyncio.ensure_future(
        call_block(ValidateSchemaOperator(), {"input": ["first", "second", "third"], "schema": "slow"}, ctx)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert await asyncio.to_thread(finished.wait, 10)
    assert checked == ["first"]
