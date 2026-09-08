"""Tests for ``value.const``."""

import pytest
from pydantic import ValidationError

from dirigent_blocks.values import ValueConstConfig, ValueConstOperator, ValueConstOutput
from dirigent_testing import FakeContext, call_block


async def test_the_declared_value_comes_out_unchanged(ctx: FakeContext) -> None:
    output = await call_block(ValueConstOperator(), {"value": {"stations": ["st-1"], "count": 1}}, ctx)
    assert isinstance(output, ValueConstOutput)
    assert output.value == {"stations": ["st-1"], "count": 1}


async def test_a_list_is_a_value_too(ctx: FakeContext) -> None:
    output = await call_block(ValueConstOperator(), {"value": [1, 2, 3]}, ctx)
    assert isinstance(output, ValueConstOutput)
    assert output.value == [1, 2, 3]


async def test_saying_nothing_is_refused(ctx: FakeContext) -> None:
    """A constant that declares no value is a mistake, caught at validation rather than read."""
    with pytest.raises(ValidationError):
        await call_block(ValueConstOperator(), {}, ctx)


async def test_an_explicit_null_is_a_value(ctx: FakeContext) -> None:
    output = await call_block(ValueConstOperator(), {"value": None}, ctx)
    assert isinstance(output, ValueConstOutput)
    assert output.value is None


def test_the_schema_refuses_a_key_it_does_not_know() -> None:
    schema = ValueConstConfig.model_json_schema(mode="serialization")
    assert schema["additionalProperties"] is False
