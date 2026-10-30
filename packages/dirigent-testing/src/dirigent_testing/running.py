"""Making one block call from a test, through the validation the engine puts in front of it."""

from collections.abc import Mapping
from typing import Any

from jsonschema import FormatChecker
from pydantic import BaseModel

from dirigent_common.formats import base_format_checker
from dirigent_plugin import AnyOperator, AnySensor, Logger, NotYet, Operator, StepContext
from dirigent_plugin.sources import Ignore, InboundRequest, ReceivedSource, Refusal
from dirigent_testing.doubles import FakeContext, RecordingLogger


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
    none leaves it. A success hands on what :meth:`Sensor.resume_cursor` says, as a
    ``sensor`` source hands it to the poke that starts its next wait.
    """
    if isinstance(answer, NotYet):
        if answer.cursor is not None:
            ctx.cursor = dict(answer.cursor)
        return
    resumed = sensor.resume_cursor(answer)
    ctx.cursor = dict(resumed) if resumed is not None else None


class FakeReceiveContext:
    """What a received kind may reach while it turns a request into an input, with its log kept."""

    def __init__(self, format_checker: FormatChecker | None = None) -> None:
        """Start with an empty log and the base format checker unless one is given."""
        self.logger = RecordingLogger()
        self._format_checker = format_checker or base_format_checker()

    @property
    def log(self) -> Logger:
        """Where the kind says what it did with the request."""
        return self.logger

    @property
    def format_checker(self) -> FormatChecker:
        """The checker the kind's input is held to."""
        return self._format_checker


async def receive_request(
    source: ReceivedSource[Any, Any],
    config: Mapping[str, Any],
    request: InboundRequest,
    ctx: FakeReceiveContext | None = None,
) -> BaseModel | Ignore | Refusal:
    """Validate the config, then take a request the way the intake does: its head, then its body.

    A refusal on the head alone is answered before the body is read, as the server answers it.
    """
    validated = source.config_model.model_validate(config)
    refused = source.admit(validated, request)
    if refused is not None:
        return refused
    return await source.receive(validated, request, ctx or FakeReceiveContext())
