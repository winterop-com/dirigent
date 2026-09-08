"""The transform verb frames: one contract per verb, one engine per kind.

A transform block's id is ``<verb>.<kind>``. The verb names the contract and the semantic
promise the frame enforces; the kind names the engine that keeps it. Four verbs live here:
``transform``, an arbitrary whole-value reshape driven by a program; ``convert``, a
content-preserving re-encoding from one format to another; ``map``, whose output has the
same length as its input; and ``filter``, whose output is a subset of its input with the
elements unmodified.

The frame owns everything an engine would otherwise repeat: where the input comes from and
how much of it may be read, where the result goes, the catalog entry, and the apply-time
check that refuses a bad program or an unsupported format pair before a document is stored.
An engine supplies only the part that is specific to it.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Final, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from dirigent_common import BlockModel, Size, StorageUri
from dirigent_plugin.blocks import (
    BlockFailure,
    ErrorClass,
    Operator,
    OperatorSpec,
    RemoteHandle,
    StepContext,
)

#: The same bound ``http.request`` puts on a body it holds in memory.
MAX_INPUT_DEFAULT: Final = 32 * 1024 * 1024

#: How much is handed to a storage sink at a time.
CHUNK_BYTES: Final = 64 * 1024

#: What the ``map`` frame says it does, in the refusal of an input that is not a list.
MAP_PROMISE: Final = "replaces every element of a list"

#: What the ``filter`` frame says it does, in the same refusal.
FILTER_PROMISE: Final = "keeps some of the elements of a list"


class TransformError(Exception):
    """An engine refused what it was given: a program it cannot compile, or a value it cannot reshape.

    Raised by an engine and turned into a rejected block failure by the frame, so an engine
    never classifies a failure or constructs one itself.
    """


class TransformConfig(BlockModel):
    """The half of a transform's config the frame owns, whatever the verb or the engine."""

    model_config = ConfigDict(
        use_attribute_docstrings=True,
        # The published schema carries the exactly-one rule, so a document that breaks it is
        # refused where every other config mistake is, rather than on the first run.
        json_schema_extra={"oneOf": [{"required": ["input"]}, {"required": ["input_uri"]}]},
    )

    input: JsonValue | None = None
    """The value to work on, written inline in the document.

    A ``null`` written here is read as no input at all, which is the one value that cannot
    be passed inline."""

    input_uri: StorageUri | None = None
    """A storage URI to read the input from instead of writing it inline."""

    save_to: StorageUri | None = None
    """A storage URI to stream the result to, instead of carrying it inline.

    The step's output then carries ``output_uri`` and ``output_bytes``: a result worth
    saving is one the next step reads from storage."""

    max_input: Size = MAX_INPUT_DEFAULT
    """How much of ``input_uri`` is read into memory.

    A value has to be whole to be reshaped, so one too large to hold is refused rather than
    truncated: half a document is not a smaller input, it is a wrong one."""

    @model_validator(mode="after")
    def _require_one_input(self) -> "TransformConfig":
        """Reject a config that gives both an inline value and a URI, or neither."""
        if (self.input is None) == (self.input_uri is None):
            raise ValueError("a transform reads either input or input_uri, and needs exactly one of the two")
        return self


class ProgramConfig(TransformConfig):
    """What a program-shaped engine is told: the shared fields, plus the program itself."""

    program: str = Field(min_length=1)
    """The engine's program, in whatever language the engine's kind names."""


class TransformOutput(BlockModel):
    """What one reshape produced: the value itself, or where it was written."""

    value: JsonValue | None = None
    """The reshaped value, when it was not streamed to storage."""

    output_uri: str | None = None
    """Where the result was written, when ``save_to`` asked for it."""

    output_bytes: int | None = None
    """How many bytes were written there."""


class ConvertConfig(TransformConfig):
    """What one re-encoding is told: where the bytes come from, and the pair of formats."""

    input: str | None = None  # pyright: ignore[reportIncompatibleVariableOverride] - a codec reads text, not JSON
    """The text to re-encode, written inline in the document."""

    from_format: str = Field(alias="from", min_length=1)
    """The format the input is in, named as the engine names it."""

    to_format: str = Field(alias="to", min_length=1)
    """The format to produce."""


class ConvertOutput(BlockModel):
    """What one re-encoding produced: the text itself, or where it was written."""

    text: str | None = None
    """The re-encoded text, when it was not streamed to storage."""

    output_uri: str | None = None
    """Where the result was written, when ``save_to`` asked for it."""

    output_bytes: int | None = None
    """How many bytes were written there."""


class Transformer(Operator[ProgramConfig, TransformOutput], ABC):
    """The ``transform`` verb: reshape one whole value into another by running a program.

    An engine names its kind, summarises itself in one line, and supplies the two halves of
    running a program: compiling it, which is also what the apply-time check runs, and
    applying it to a value. The frame derives the catalog entry, resolves the input, and
    disposes of the result.

    An engine touches no HTTP, no file outside storage, and nothing in the environment. It
    is handed a value and returns a value; everything that reaches the world is the frame's.
    """

    kind: ClassVar[str]
    """The engine's name, which is the second half of the block id."""

    summary: ClassVar[str]
    """The one line the catalog shows for this engine."""

    local_execution: ClassVar[bool] = False
    """Whether this engine executes code on the worker, which puts it behind the allowlist."""

    config_model: ClassVar[type[BaseModel]] = ProgramConfig
    output_model: ClassVar[type[BaseModel]] = TransformOutput

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Derive the catalog entry: the id is ``transform.<kind>`` and the group ``transform``."""
        super().__init_subclass__(**kwargs)
        kind = cls.__dict__.get("kind")
        if kind is not None:
            cls.spec = OperatorSpec(
                id=f"transform.{kind}",
                group="transform",
                summary=cls.summary,
                idempotent=True,
                local_execution=cls.local_execution,
            )

    @abstractmethod
    def compile(self, program: str) -> object:
        """Turn a program into whatever this engine applies, raising TransformError on a bad one."""
        ...

    @abstractmethod
    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run a compiled program over one whole value."""
        ...

    async def execute(self, config: ProgramConfig, ctx: StepContext) -> TransformOutput | RemoteHandle:
        """Resolve the input, run the program over it, and inline or store the result."""
        value = await _read_value(config, ctx)
        try:
            result = self.apply(self.compile(config.program), value)
        except TransformError as error:
            raise BlockFailure(str(error), error_class=ErrorClass.REJECTED) from error
        if config.save_to is None:
            return TransformOutput(value=result)
        written = await _write(ctx, config.save_to, json.dumps(result, separators=(",", ":")).encode())
        return TransformOutput(output_uri=config.save_to, output_bytes=written)

    def check_config(self, config: BaseModel) -> list[str]:
        """Compile the program at apply, so a bad one is refused before the document is stored."""
        if not isinstance(config, ProgramConfig):
            return []
        try:
            self.compile(config.program)
        except TransformError as error:
            return [str(error)]
        return []


class Mapper(Operator[ProgramConfig, TransformOutput], ABC):
    """The ``map`` verb: replace every element of a list with what a program makes of it.

    An engine names its kind, summarises itself in one line, and supplies compiling a
    program and applying it -- to one element at a time, not to the whole list. The frame
    derives the catalog entry, resolves the input, refuses an input that is not an array,
    runs the loop, and disposes of the result.

    The promise is length: the output has one element for every element of the input, in
    input order. The frame builds it one element at a time, so the promise holds by
    construction, and asserts it afterwards so an engine that reached past the loop fails
    itself rather than quietly returning a shorter list.

    An engine touches no HTTP, no file outside storage, and nothing in the environment. It
    is handed an element and returns an element; everything that reaches the world is the
    frame's.
    """

    kind: ClassVar[str]
    """The engine's name, which is the second half of the block id."""

    summary: ClassVar[str]
    """The one line the catalog shows for this engine."""

    local_execution: ClassVar[bool] = False
    """Whether this engine executes code on the worker, which puts it behind the allowlist."""

    config_model: ClassVar[type[BaseModel]] = ProgramConfig
    output_model: ClassVar[type[BaseModel]] = TransformOutput

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Derive the catalog entry: the id is ``map.<kind>`` and the group ``transform``."""
        super().__init_subclass__(**kwargs)
        kind = cls.__dict__.get("kind")
        if kind is not None:
            cls.spec = OperatorSpec(
                id=f"map.{kind}",
                group="transform",
                summary=cls.summary,
                idempotent=True,
                local_execution=cls.local_execution,
            )

    @abstractmethod
    def compile(self, program: str) -> object:
        """Turn a program into whatever this engine applies, raising TransformError on a bad one."""
        ...

    @abstractmethod
    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run a compiled program over one element and return the element that replaces it."""
        ...

    async def execute(self, config: ProgramConfig, ctx: StepContext) -> TransformOutput | RemoteHandle:
        """Resolve the input, replace every element, and inline or store the list."""
        elements = _elements(await _read_value(config, ctx), self.spec.id, MAP_PROMISE)
        try:
            compiled = self.compile(config.program)
        except TransformError as error:
            raise BlockFailure(str(error), error_class=ErrorClass.REJECTED) from error
        mapped = self._map_each(compiled, elements)
        assert len(mapped) == len(elements), (
            f"{self.spec.id} produced {len(mapped)} elements from {len(elements)}, breaking the map promise"
        )
        if config.save_to is None:
            return TransformOutput(value=mapped)
        written = await _write(ctx, config.save_to, json.dumps(mapped, separators=(",", ":")).encode())
        return TransformOutput(output_uri=config.save_to, output_bytes=written)

    def _map_each(self, compiled: object, elements: list[JsonValue]) -> list[JsonValue]:
        """Apply the engine once per element, in order, naming the element it refused."""
        mapped: list[JsonValue] = []
        for index, element in enumerate(elements):
            try:
                mapped.append(self.apply(compiled, element))
            except TransformError as error:
                raise BlockFailure(f"element {index}: {error}", error_class=ErrorClass.REJECTED) from error
        return mapped

    def check_config(self, config: BaseModel) -> list[str]:
        """Compile the program at apply, so a bad one is refused before the document is stored."""
        if not isinstance(config, ProgramConfig):
            return []
        try:
            self.compile(config.program)
        except TransformError as error:
            return [str(error)]
        return []


class Filterer(Operator[ProgramConfig, TransformOutput], ABC):
    """The ``filter`` verb: keep the elements of a list a program answers true for.

    An engine names its kind, summarises itself in one line, supplies compiling a program,
    and answers one question about one element: keep it, or not. The frame derives the
    catalog entry, resolves the input, refuses an input that is not an array, runs the loop,
    and disposes of the result.

    The promise is a subset with the elements unmodified. The frame keeps the element it was
    given rather than anything the engine produced, so an engine has no way to change an
    element it was only asked about, and an answer that is not a boolean is a refusal rather
    than a truthiness question the frame would have to decide.

    An engine touches no HTTP, no file outside storage, and nothing in the environment. It
    is handed an element and returns a verdict; everything that reaches the world is the
    frame's.
    """

    kind: ClassVar[str]
    """The engine's name, which is the second half of the block id."""

    summary: ClassVar[str]
    """The one line the catalog shows for this engine."""

    local_execution: ClassVar[bool] = False
    """Whether this engine executes code on the worker, which puts it behind the allowlist."""

    config_model: ClassVar[type[BaseModel]] = ProgramConfig
    output_model: ClassVar[type[BaseModel]] = TransformOutput

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Derive the catalog entry: the id is ``filter.<kind>`` and the group ``transform``."""
        super().__init_subclass__(**kwargs)
        kind = cls.__dict__.get("kind")
        if kind is not None:
            cls.spec = OperatorSpec(
                id=f"filter.{kind}",
                group="transform",
                summary=cls.summary,
                idempotent=True,
                local_execution=cls.local_execution,
            )

    @abstractmethod
    def compile(self, program: str) -> object:
        """Turn a program into whatever this engine applies, raising TransformError on a bad one."""
        ...

    @abstractmethod
    def keep(self, compiled: object, value: JsonValue) -> bool:
        """Answer whether one element is kept."""
        ...

    async def execute(self, config: ProgramConfig, ctx: StepContext) -> TransformOutput | RemoteHandle:
        """Resolve the input, keep the elements the engine answers true for, and inline or store them."""
        elements = _elements(await _read_value(config, ctx), self.spec.id, FILTER_PROMISE)
        try:
            compiled = self.compile(config.program)
        except TransformError as error:
            raise BlockFailure(str(error), error_class=ErrorClass.REJECTED) from error
        # The element the frame was given, never anything the engine returned: what a filter
        # keeps is what arrived.
        kept = [element for index, element in enumerate(elements) if self._verdict(compiled, element, index)]
        if config.save_to is None:
            return TransformOutput(value=kept)
        written = await _write(ctx, config.save_to, json.dumps(kept, separators=(",", ":")).encode())
        return TransformOutput(output_uri=config.save_to, output_bytes=written)

    def _verdict(self, compiled: object, element: JsonValue, index: int) -> bool:
        """Ask the engine about one element, refusing an answer that is not a boolean."""
        try:
            # Read as object rather than bool: the signature says bool, and this is where an
            # engine is held to it.
            answer = cast("object", self.keep(compiled, element))
        except TransformError as error:
            raise BlockFailure(f"element {index}: {error}", error_class=ErrorClass.REJECTED) from error
        if not isinstance(answer, bool):
            raise BlockFailure(
                f"{self.spec.id} answered {answer!r} for element {index}, and a filter's answer is true or false",
                error_class=ErrorClass.REJECTED,
            )
        return answer

    def check_config(self, config: BaseModel) -> list[str]:
        """Compile the program at apply, so a bad one is refused before the document is stored."""
        if not isinstance(config, ProgramConfig):
            return []
        try:
            self.compile(config.program)
        except TransformError as error:
            return [str(error)]
        return []


class Converter(Operator[ConvertConfig, ConvertOutput], ABC):
    """The ``convert`` verb: re-encode bytes from one format into another, content preserved.

    A converter is a codec, not a language: there is no program. An engine names its kind,
    declares the ``(from, to)`` format pairs it supports, and re-encodes bytes. The frame
    derives the catalog entry, resolves the input, refuses an unsupported pair at apply, and
    disposes of the result.

    An engine touches no HTTP, no file outside storage, and nothing in the environment. It
    is handed bytes and returns bytes; everything that reaches the world is the frame's.
    """

    kind: ClassVar[str]
    """The engine's name, which is the second half of the block id."""

    summary: ClassVar[str]
    """The one line the catalog shows for this engine."""

    pairs: ClassVar[frozenset[tuple[str, str]]]
    """Every ``(from, to)`` format pair this engine re-encodes between."""

    local_execution: ClassVar[bool] = False
    """Whether this engine executes code on the worker, which puts it behind the allowlist."""

    config_model: ClassVar[type[BaseModel]] = ConvertConfig
    output_model: ClassVar[type[BaseModel]] = ConvertOutput

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Derive the catalog entry: the id is ``convert.<kind>`` and the group ``transform``."""
        super().__init_subclass__(**kwargs)
        kind = cls.__dict__.get("kind")
        if kind is not None:
            cls.spec = OperatorSpec(
                id=f"convert.{kind}",
                group="transform",
                summary=cls.summary,
                idempotent=True,
                local_execution=cls.local_execution,
            )

    @abstractmethod
    def convert(self, source: bytes, *, source_format: str, target_format: str) -> bytes:
        """Re-encode one whole payload from one format into another."""
        ...

    async def execute(self, config: ConvertConfig, ctx: StepContext) -> ConvertOutput | RemoteHandle:
        """Refuse an unsupported pair, then re-encode the input and inline or store the result."""
        unsupported = self._pair_refusal(config.from_format, config.to_format)
        if unsupported is not None:
            raise BlockFailure(unsupported, error_class=ErrorClass.REJECTED)
        source = await _read_bytes(config, ctx)
        try:
            produced = self.convert(source, source_format=config.from_format, target_format=config.to_format)
        except TransformError as error:
            raise BlockFailure(str(error), error_class=ErrorClass.REJECTED) from error
        if config.save_to is None:
            return ConvertOutput(text=produced.decode("utf-8", errors="replace"))
        written = await _write(ctx, config.save_to, produced)
        return ConvertOutput(output_uri=config.save_to, output_bytes=written)

    def check_config(self, config: BaseModel) -> list[str]:
        """Refuse a format pair this engine has no codec for, at apply."""
        if not isinstance(config, ConvertConfig):
            return []
        unsupported = self._pair_refusal(config.from_format, config.to_format)
        return [] if unsupported is None else [unsupported]

    def _pair_refusal(self, source_format: str, target_format: str) -> str | None:
        """Word the refusal of a pair this engine does not support, naming the ones it does."""
        if (source_format, target_format) in self.pairs:
            return None
        listed = ", ".join(f"{one} to {other}" for one, other in sorted(self.pairs))
        supported = listed or "this engine converts nothing"
        return f"{self.spec.id} does not convert {source_format} to {target_format} ({supported})"


def _elements(value: JsonValue, spec_id: str, promise: str) -> list[JsonValue]:
    """Read a verb's input as a JSON array, refusing anything else with the promise it broke."""
    if isinstance(value, list):
        return value
    raise BlockFailure(
        f"{spec_id} {promise}, so its input has to be a JSON array, and this one is {_named(value)}",
        error_class=ErrorClass.REJECTED,
    )


def _named(value: JsonValue) -> str:
    """Say what a JSON value is, so a refusal names what arrived; only ever called with a non-array."""
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, str):
        return "a string"
    # Before the number check, because a bool is an int in Python and is not one in JSON.
    if isinstance(value, bool):
        return "a boolean"
    if value is None:
        return "null"
    return "a number"


async def _read_value(config: ProgramConfig, ctx: StepContext) -> JsonValue:
    """Resolve a program engine's input: the inline value, or the JSON stored at a URI."""
    if config.input_uri is None:
        return config.input
    payload = await _read_bounded(ctx, config.input_uri, config.max_input)
    try:
        parsed: JsonValue = json.loads(payload)
    except ValueError as error:
        raise BlockFailure(
            f"{config.input_uri} does not hold JSON: {error}", error_class=ErrorClass.REJECTED
        ) from error
    return parsed


async def _read_bytes(config: ConvertConfig, ctx: StepContext) -> bytes:
    """Resolve a codec engine's input: the inline text, or the bytes stored at a URI."""
    if config.input_uri is None:
        return (config.input or "").encode()
    return await _read_bounded(ctx, config.input_uri, config.max_input)


async def _read_bounded(ctx: StepContext, uri: str, limit: int) -> bytes:
    """Read a stored object whole, refusing one larger than the step said it would hold.

    Counted as it arrives rather than trusted from a stat, because a recorded size is the
    backend's claim and this is the worker's memory.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in ctx.storage.open_read(uri):
        total += len(chunk)
        if total > limit:
            raise BlockFailure(
                f"{uri} is larger than max_input ({limit} bytes) and is not being read; "
                f"raise max_input, or transform it in pieces",
                error_class=ErrorClass.REJECTED,
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _write(ctx: StepContext, uri: str, payload: bytes) -> int:
    """Stream a result to storage a chunk at a time, and say how much reached it."""
    written = 0
    async with ctx.storage.open_write(uri) as sink:
        for start in range(0, len(payload), CHUNK_BYTES):
            written += await sink.write(payload[start : start + CHUNK_BYTES])
    ctx.log.info("transform result saved", uri=uri, bytes=written)
    return written
