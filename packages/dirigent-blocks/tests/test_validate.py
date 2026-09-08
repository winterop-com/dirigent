"""Tests for ``validate.schema``."""

import pytest

from dirigent_blocks.validate import ValidateSchemaConfig, ValidateSchemaOperator, ValidateSchemaOutput
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

    ``even-digits`` stands in for a pack's own format such as ``dhis2-uid``: a value that
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

    ``format: dhis2-uid`` on an instance without the dhis2 pack asserts nothing: the value is
    valid, just unchecked, which is jsonschema's own behaviour for an unknown format.
    """
    ctx.schemas["dhis2-shape"] = {
        "type": "object",
        "required": ["ou"],
        "properties": {"ou": {"type": "string", "format": "dhis2-uid"}},
    }
    output = await call_block(
        ValidateSchemaOperator(), {"input": {"ou": "not a uid at all"}, "schema": "dhis2-shape"}, ctx
    )
    assert isinstance(output, ValidateSchemaOutput)
    assert output.value == {"ou": "not a uid at all"}


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
