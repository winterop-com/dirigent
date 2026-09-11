"""Tests for ``log.write``: one entry on the run's timeline, and the value carried on."""

import pytest
from pydantic import ValidationError

from dirigent_blocks.logging import LogWriteOperator, LogWriteOutput
from dirigent_testing import FakeContext, call_block


async def test_the_entry_lands_on_the_run_with_its_value(ctx: FakeContext) -> None:
    output = await call_block(LogWriteOperator(), {"message": "the report", "value": {"rows": 3}}, ctx)
    assert isinstance(output, LogWriteOutput)
    assert ctx.log.entries == [("info", "the report", {"value": {"rows": 3}})]


async def test_the_level_decides_which_entry_is_written(ctx: FakeContext) -> None:
    await call_block(LogWriteOperator(), {"message": "nothing arrived", "level": "warning"}, ctx)
    assert ctx.log.entries == [("warning", "nothing arrived", {"value": None})]


async def test_the_value_passes_through_for_the_next_step(ctx: FakeContext) -> None:
    output = await call_block(LogWriteOperator(), {"message": "read", "value": [1, 2]}, ctx)
    assert isinstance(output, LogWriteOutput)
    assert output.value == [1, 2]


async def test_a_level_that_is_not_one_of_the_four_is_refused_at_validation(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError):
        await call_block(LogWriteOperator(), {"message": "hm", "level": "critical"}, ctx)


def test_the_operator_declares_itself_idempotent() -> None:
    assert LogWriteOperator.spec.idempotent is True
