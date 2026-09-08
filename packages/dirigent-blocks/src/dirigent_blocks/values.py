"""``value.const``: a fixed value, into the run, with nothing granted."""

from typing import ClassVar

from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_plugin import Operator, OperatorSpec, StepContext


class ValueConstConfig(BlockModel):
    """The one thing a constant step declares."""

    value: JsonValue
    """The value this step emits, exactly as written. An explicit null is a value; leaving
    the field out is a step that declares nothing, and is refused."""


class ValueConstOutput(BlockModel):
    """What the step emitted, for downstream references to read."""

    value: JsonValue = None
    """The declared value, unchanged."""


class ValueConstOperator(Operator[ValueConstConfig, ValueConstOutput]):
    """Emits its configured value, giving a pipeline a place to park a literal.

    The step exists for what downstream steps can do with it: a payload several steps
    read, a parameter defaulted in one place, the smallest possible pipeline. It runs on
    any worker with nothing on the allowlist, because it touches nothing.
    """

    spec = OperatorSpec(id="value.const", summary="Emit a fixed value.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = ValueConstConfig
    output_model: ClassVar[type[BaseModel]] = ValueConstOutput

    async def execute(self, config: ValueConstConfig, ctx: StepContext) -> ValueConstOutput:
        """Hand the declared value on."""
        return ValueConstOutput(value=config.value)
