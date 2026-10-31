"""Tests for ``validate.schema``."""

import asyncio
import threading
from typing import Any

import pytest

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
    assert set(published["properties"]) == {"input", "schema"}
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
