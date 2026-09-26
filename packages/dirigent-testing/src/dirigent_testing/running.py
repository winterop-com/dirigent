"""Making one block call from a test, through the validation the engine puts in front of it."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from dirigent_plugin import AnyOperator, AnySensor, NotYet, Operator, StepContext
from dirigent_testing.doubles import FakeContext


async def call_block(
    block: AnyOperator | AnySensor,
    config: Mapping[str, Any],
    ctx: StepContext | FakeContext,
) -> BaseModel:
    """Validate the config the way the engine would, then make the block's first call.

    An operator's execute or a sensor's poke, with the validated config -- so a test
    exercises the same validation path a real run does, and a config the schema refuses
    fails here rather than silently succeeding with defaults.
    """
    context = ctx.as_context() if isinstance(ctx, FakeContext) else ctx
    validated = block.config_model.model_validate(config)
    if isinstance(block, Operator):
        return await block.execute(validated, context)
    return await block.poke(validated, context)


def carry_cursor(sensor: AnySensor, answer: BaseModel, ctx: FakeContext) -> None:
    """Hand the next poke the cursor the engine would, after one poke answered this.

    A park that returned a cursor replaces the one the context held, and one that returned
    none leaves it. A success hands on what :meth:`Sensor.resume_cursor` says, as a watch
    hands it to the first poke of its next run.
    """
    if isinstance(answer, NotYet):
        if answer.cursor is not None:
            ctx.cursor = dict(answer.cursor)
        return
    resumed = sensor.resume_cursor(answer)
    ctx.cursor = dict(resumed) if resumed is not None else None
