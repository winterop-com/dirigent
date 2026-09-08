"""``validate.schema``: a gate that fails at the boundary, not three steps later."""

from typing import Any, ClassVar

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_plugin import BlockFailure, ErrorClass, Operator, OperatorSpec, StepContext


class ValidateSchemaConfig(BlockModel):
    """What one gate checks, and against what."""

    input: JsonValue = None
    """The value to check, normally a ``${steps....}`` reference to what an upstream step
    produced. An explicit null is a value like any other and is checked as one."""

    json_schema: str = Field(alias="schema")
    """The code of the schema the value must satisfy: one the instance holds, or one the
    document carries in its top-level ``schemas`` section. The named schema was validated when
    it was stored or applied, so nothing rechecks it here; a code no instance holds fails the
    run at the gate. The Python attribute is renamed only to dodge a pydantic clash; a
    document writes ``schema``."""


class ValidateSchemaOutput(BlockModel):
    """What the gate passed through, so a downstream step reads a value it knows fits."""

    value: JsonValue = None
    """The validated input, unchanged. The gate is also a waypoint: reference
    ``${steps.<gate>.output.value}`` and every step past it provably received the shape."""


class ValidateSchemaOperator(Operator[ValidateSchemaConfig, ValidateSchemaOutput]):
    """Checks a value against a JSON Schema, and passes it through when it fits.

    A pipeline that reads from a service it does not control is one schema change away from
    a step deep in the graph choking on a field that moved. This gate states the expected
    shape where the value enters, so a drift fails here -- with the path into the payload
    that is wrong -- rather than surfacing later as a confusing error somewhere downstream.

    A value that fails is rejected rather than retried: the same value against the same
    schema fails the same way, so trying again cannot help.
    """

    spec = OperatorSpec(id="validate.schema", summary="Validate a value against a JSON Schema.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = ValidateSchemaConfig
    output_model: ClassVar[type[BaseModel]] = ValidateSchemaOutput

    async def execute(self, config: ValidateSchemaConfig, ctx: StepContext) -> ValidateSchemaOutput:
        """Validate, then hand the value on; refuse it naming the place it is wrong.

        The schema is the body of the named one -- a code no instance holds fails the run at
        the gate rather than passing the value on.
        """
        schema = ctx.schema(config.json_schema)
        validator = Draft202012Validator(schema, format_checker=ctx.format_checker())
        errors: Any = validator.iter_errors(config.input)  # pyright: ignore[reportUnknownMemberType]
        first = next(iter(sorted(errors, key=_where)), None)
        if first is not None:
            raise BlockFailure(f"at {first.json_path}: {first.message}", error_class=ErrorClass.REJECTED)
        return ValidateSchemaOutput(value=config.input)

    def check_config(self, config: BaseModel) -> list[str]:
        """Nothing to check at apply: the named schema was validated when it was stored or applied.

        A carried schema is checked at apply by the document format; an instance schema was
        checked when it was stored. The ``requires.schemas`` preflight catches a code no
        instance holds, and a carried code satisfies its own reference.
        """
        return []


def _where(error: SchemaValidationError) -> str:
    """The path a failure is reported at, so the first error named is the earliest one."""
    return error.json_path
