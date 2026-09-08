"""The ``jq`` engines: a jq program as the transform, map, and filter verbs' program."""

import json
from typing import Annotated, Any, ClassVar, cast

import jq
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import JQ_MEDIA_TYPE
from dirigent_plugin import Filterer, Mapper, ProgramConfig, Transformer, TransformError

#: What a program producing nothing is told to write instead.
NO_OUTPUT = (
    "the program produced no output, and a transform step has to produce one; "
    "a program that means 'possibly nothing' emits [] or null explicitly"
)

#: Wraps the author's program so jq's ``env`` and ``$ENV`` read an empty object instead of
#: the worker's environment, which is where dirigent's own secrets live. The program keeps
#: its own line numbers because the message a bad one is refused with comes from compiling
#: the author's text, unwrapped.
SANDBOX = "{} as $ENV | def env: {}; (\n"

#: Typed ``Any`` because the jq binding is a C extension that ships no type information.
libjq: Any = jq


def _compile(program: str) -> object:
    """Compile a jq program with env and $ENV shadowed, refusing a bad one with jq's own message."""
    try:
        # The author's text is compiled first, so a refusal carries jq's message about their
        # program and not about the wrapper.
        libjq.compile(program)
        return libjq.compile(f"{SANDBOX}{program}\n)")
    except ValueError as error:
        raise TransformError(str(error).strip()) from error


def _outputs(compiled: object, value: JsonValue) -> list[JsonValue]:
    """Run a compiled program over one value and read its whole stream of outputs."""
    try:
        return cast("list[JsonValue]", cast("Any", compiled).input_value(value).all())
    except ValueError as error:
        raise TransformError(str(error).strip()) from error


class JqProgramConfig(ProgramConfig):
    """The program-shaped config of a jq engine, whichever verb is running it.

    All three verbs take the same program in the same language, so all three publish the
    same config: the frame's fields, with ``program`` narrowed to jq source.
    """

    program: Annotated[str, Field(min_length=1, json_schema_extra={"contentMediaType": JQ_MEDIA_TYPE})]
    """The jq program this step runs."""


class JqTransformer(Transformer):
    """Reshapes one whole value by running a jq program over it.

    jq opens no file, no socket, and starts no process: a program is handed a value and
    returns values, which is why this engine executes no code on the worker and needs no
    allowlist entry. Its two ways of reading the worker's environment, ``env`` and ``$ENV``,
    are shadowed, so a program sees an empty object rather than the process it runs in.

    A jq program is a stream: it can emit zero, one, or many outputs. One output is the
    step's value, many outputs are that list of values, and none is a refusal, because a
    step that produced nothing has no output for the next step to read.
    """

    kind = "jq"
    summary = "Reshape a value with a jq program."
    config_model: ClassVar[type[BaseModel]] = JqProgramConfig

    def compile(self, program: str) -> object:
        """Compile a jq program, refusing a bad one with jq's own message about it."""
        return _compile(program)

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run the program over one value, and read its stream of outputs as one result."""
        produced = _outputs(compiled, value)
        if not produced:
            raise TransformError(NO_OUTPUT)
        return produced[0] if len(produced) == 1 else produced


class JqMapper(Mapper):
    """Replaces every element of a list with what a jq program makes of that element.

    The program is run once per element, with the element as its input, and is sandboxed
    exactly as ``transform.jq`` is: ``env`` and ``$ENV`` read an empty object.

    A map replaces each element with one thing, so the stream a program emits for an element
    has to be exactly one output. Zero of them and several of them are both refusals rather
    than a shorter or longer list, because dropping elements is what ``filter.jq`` is for and
    changing their number is what ``transform.jq`` is for.
    """

    kind = "jq"
    summary = "Replace every element of a list with what a jq program makes of it."
    config_model: ClassVar[type[BaseModel]] = JqProgramConfig

    def compile(self, program: str) -> object:
        """Compile a jq program, refusing a bad one with jq's own message about it."""
        return _compile(program)

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run the program over one element, and take its single output as the replacement."""
        produced = _outputs(compiled, value)
        if len(produced) != 1:
            raise TransformError(
                f"the program produced {len(produced)} outputs, and a map replaces an element with "
                f"exactly one; a program that drops elements is a filter.jq step, and one that "
                f"changes how many there are is a transform.jq step"
            )
        return produced[0]


class JqFilterer(Filterer):
    """Keeps the elements of a list a jq program answers true for.

    The program is run once per element, with the element as its input, and is sandboxed
    exactly as ``transform.jq`` is: ``env`` and ``$ENV`` read an empty object.

    The answer has to be exactly one output, and that output has to be ``true`` or ``false``.
    jq's own truthiness is not applied: a program emitting ``0`` or ``""`` is a mistake
    surfaced rather than an element quietly dropped, and an author who means "has readings"
    writes ``.count > 0``.
    """

    kind = "jq"
    summary = "Keep the elements of a list a jq program answers true for."
    config_model: ClassVar[type[BaseModel]] = JqProgramConfig

    def compile(self, program: str) -> object:
        """Compile a jq program, refusing a bad one with jq's own message about it."""
        return _compile(program)

    def keep(self, compiled: object, value: JsonValue) -> bool:
        """Run the program over one element, and read its single boolean output as the verdict."""
        produced = _outputs(compiled, value)
        if len(produced) != 1:
            raise TransformError(
                f"the program produced {len(produced)} outputs, and a filter answers one true or false "
                f"per element; a program that reshapes an element is a map.jq or transform.jq step"
            )
        answer = produced[0]
        if not isinstance(answer, bool):
            raise TransformError(
                f"the program answered {json.dumps(answer)}, and a filter answers true or false; jq's "
                f"truthiness is not applied, so a program meaning 'has readings' writes '.count > 0'"
            )
        return answer
