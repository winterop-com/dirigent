"""The generic storage blocks: bytes in, bytes out, bytes between URIs, and a wait.

``storage.read`` is the only way a value comes in from storage and ``storage.write`` the only
way one goes out, so a step that has a value hands it to a write and a step that needs one
takes it from a read. ``storage.copy`` is neither: it moves bytes nobody has to look at.
"""

import json
import mimetypes
from contextlib import aclosing
from datetime import datetime
from typing import ClassVar, cast

from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_common import BlockModel, Size, StorageUri
from dirigent_plugin import (
    BlockFailure,
    ErrorClass,
    NotYet,
    Operator,
    OperatorSpec,
    RemoteHandle,
    Sensor,
    SensorSpec,
    StatResult,
    StepContext,
)

GLOB_CHARACTERS = ("*", "?", "[")

#: What a text value is written as when the step names no content type.
TEXT_CONTENT_TYPE = "text/plain"

#: What a JSON value is written as when the step names no content type.
JSON_CONTENT_TYPE = "application/json"

#: What an object is read as when nothing -- the step, the backend, the extension -- says.
OCTET_STREAM = "application/octet-stream"

#: Content types outside the JSON family whose objects are text a step can hold.
TEXT_TYPES = ("application/x-ndjson", "application/yaml", "application/xml")


class StorageCopyConfig(BlockModel):
    """Which object to move, and where to put it."""

    source: StorageUri = Field(min_length=1)
    target: StorageUri = Field(min_length=1)


class StorageCopyOutput(BlockModel):
    """What the copy moved, so a downstream step can address the result."""

    source: str
    target: str
    bytes_copied: int


class StorageCopyOperator(Operator[StorageCopyConfig, StorageCopyOutput]):
    """Streams one object onto another, across backends, without buffering it whole."""

    spec = OperatorSpec(id="storage.copy", summary="Copy an object from one URI to another.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = StorageCopyConfig
    output_model: ClassVar[type[BaseModel]] = StorageCopyOutput

    async def execute(self, config: StorageCopyConfig, ctx: StepContext) -> StorageCopyOutput | RemoteHandle:
        """Copy source to target through the storage facade, refusing a missing source."""
        if await ctx.storage.stat(config.source) is None:
            raise BlockFailure(f"there is nothing at {config.source}", error_class=ErrorClass.REJECTED)
        copied = 0
        async with ctx.storage.open_write(config.target) as sink:
            async for chunk in ctx.storage.open_read(config.source):
                copied += await sink.write(chunk)
        ctx.log.info("copied", source=config.source, target=config.target, bytes_copied=copied)
        return StorageCopyOutput(source=config.source, target=config.target, bytes_copied=copied)


class StorageWriteConfig(BlockModel):
    """What to write, and where to put it."""

    target: StorageUri = Field(min_length=1)
    """The URI the object is written to, replacing whatever is there."""

    text: str | None = None
    """A string written as UTF-8, for a report, a csv, or any document that is already text."""

    value: JsonValue | None = None
    """A value written as canonical JSON, for what an earlier step produced as structure."""

    content_type: str | None = None
    """What the object is, recorded where the backend can record it.

    Unset, it is ``text/plain`` for ``text`` and ``application/json`` for ``value``; an
    explicit one wins, which is how a markdown page or a csv says what it is."""

    @model_validator(mode="after")
    def _one_payload(self) -> "StorageWriteConfig":
        """Reject a config that names neither a text nor a value, or both."""
        named = [name for name in ("text", "value") if getattr(self, name) is not None]
        if len(named) != 1:
            raise ValueError(
                "a write needs either text or value"
                f"{', and this step names both' if named else ', and this step names neither'}"
            )
        return self

    def payload(self) -> bytes:
        """The bytes this step writes, in the encoding its content type promises."""
        if self.text is not None:
            return self.text.encode()
        # The engine's canonical JSON: sorted keys and no spaces, written as UTF-8.
        return json.dumps(self.value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def declared_content_type(self) -> str:
        """What the object is: the step's own answer, or the default for what it carries."""
        if self.content_type is not None:
            return self.content_type
        return TEXT_CONTENT_TYPE if self.text is not None else JSON_CONTENT_TYPE


class StorageWriteOutput(BlockModel):
    """Where the object landed, so a downstream step can address it."""

    uri: str
    bytes_written: int
    content_type: str


class StorageWriteOperator(Operator[StorageWriteConfig, StorageWriteOutput]):
    """Writes one value or one string to a URI, which is the only way a value leaves a run."""

    spec = OperatorSpec(id="storage.write", summary="Write a value or text to a storage URI.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = StorageWriteConfig
    output_model: ClassVar[type[BaseModel]] = StorageWriteOutput

    async def execute(self, config: StorageWriteConfig, ctx: StepContext) -> StorageWriteOutput | RemoteHandle:
        """Encode what the step carries and stream it to the target."""
        payload = config.payload()
        content_type = config.declared_content_type()
        written = 0
        async with ctx.storage.open_write(config.target) as sink:
            written += await sink.write(payload)
        ctx.log.info("wrote", uri=config.target, bytes_written=written, content_type=content_type)
        return StorageWriteOutput(uri=config.target, bytes_written=written, content_type=content_type)


class StorageReadConfig(BlockModel):
    """Which object to read, and what to read it as."""

    source: StorageUri = Field(min_length=1)
    """The URI the object is read from."""

    content_type: str | None = None
    """What to read the object as, overriding what the backend and the extension say.

    A backend that records no content type and a file named without an extension leave the
    object as bytes nobody can decode, and this is where a step says what it actually is."""

    max_size: Size = 1 * 1024 * 1024
    """How much of an object this step will hold, such as ``8mb``.

    The value is carried in the step's output, so an object too large to hold is refused
    rather than truncated: half a document is not a smaller one, it is a wrong one. Bytes
    nobody reads move with ``storage.copy``, which is bounded by the storage rather than
    by this."""


class StorageReadOutput(BlockModel):
    """What the object turned out to be, in the one field its content type decides."""

    content_type: str
    text: str | None = None
    value: JsonValue | None = None
    bytes_read: int


class StorageReadOperator(Operator[StorageReadConfig, StorageReadOutput]):
    """Reads one object into the run as a value, which is the only way a value comes in."""

    spec = OperatorSpec(id="storage.read", summary="Read an object from a storage URI as a value.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = StorageReadConfig
    output_model: ClassVar[type[BaseModel]] = StorageReadOutput

    async def execute(self, config: StorageReadConfig, ctx: StepContext) -> StorageReadOutput | RemoteHandle:
        """Resolve what the object is, read it bounded, and decode it accordingly."""
        found = await ctx.storage.stat(config.source)
        if found is None:
            raise BlockFailure(f"there is nothing at {config.source}", error_class=ErrorClass.REJECTED)
        if found.size > config.max_size:
            raise _too_large(config)
        content_type = _content_type(config, found)
        payload = await _read_bounded(config, ctx)
        ctx.log.info("read", uri=config.source, bytes_read=len(payload), content_type=content_type)
        return StorageReadOutput(
            content_type=content_type,
            text=None if _is_json(content_type) else _as_text(config, payload),
            value=_as_value(config, payload) if _is_json(content_type) else None,
            bytes_read=len(payload),
        )


def _content_type(config: StorageReadConfig, found: StatResult) -> str:
    """What the object is: the step's override, the backend's answer, the extension, or bytes."""
    guessed = mimetypes.guess_type(config.source)[0]
    resolved = config.content_type or found.content_type or guessed or OCTET_STREAM
    if _is_json(resolved) or resolved.startswith("text/") or resolved in TEXT_TYPES:
        return resolved
    raise BlockFailure(
        f"{config.source} is {resolved}, which this step has no way to read as a value; "
        f"set content_type to say what it really is, or move the bytes with storage.copy",
        error_class=ErrorClass.REJECTED,
    )


def _is_json(content_type: str) -> bool:
    """Say whether a content type is the JSON family, which is parsed rather than decoded."""
    bare = content_type.split(";")[0].strip()
    return bare == "application/json" or bare.endswith("+json")


async def _read_bounded(config: StorageReadConfig, ctx: StepContext) -> bytes:
    """Read the object a chunk at a time, stopping the moment it passes the cap.

    Counted as it arrives rather than trusted from ``stat``, because the size a backend
    reports is the backend's claim and this is the worker's memory.
    """
    chunks: list[bytes] = []
    total = 0
    async with aclosing(ctx.storage.open_read(config.source)) as stream:
        async for chunk in stream:
            total += len(chunk)
            if total > config.max_size:
                raise _too_large(config)
            chunks.append(chunk)
    return b"".join(chunks)


def _too_large(config: StorageReadConfig) -> BlockFailure:
    """The refusal of an object bigger than the step said it would hold."""
    return BlockFailure(
        f"{config.source} is larger than max_size ({config.max_size} bytes); raise max_size, "
        f"or move the bytes with storage.copy instead of carrying them",
        error_class=ErrorClass.REJECTED,
    )


def _as_text(config: StorageReadConfig, payload: bytes) -> str:
    """Decode an object its content type says is text."""
    try:
        return payload.decode()
    except UnicodeDecodeError as error:
        raise BlockFailure(
            f"{config.source} is not the utf-8 its content type promises: {error}",
            error_class=ErrorClass.REJECTED,
        ) from error


def _as_value(config: StorageReadConfig, payload: bytes) -> JsonValue:
    """Parse an object its content type says is JSON."""
    try:
        return cast("JsonValue", json.loads(payload))
    except ValueError as error:
        raise BlockFailure(
            f"{config.source} is not the json its content type promises: {error}",
            error_class=ErrorClass.REJECTED,
        ) from error


class StorageExistsConfig(BlockModel):
    """Which object, or which pattern of objects, to wait for."""

    uri: str = Field(min_length=1)
    """A URI, which may contain a glob pattern in its final segments."""

    min_size: Size = Field(default=0, ge=0)
    """Ignore an object until it is at least this large, such as ``1mb``."""


class StorageExistsOutput(BlockModel):
    """The observation that an object arrived, passed downstream like any output."""

    uri: str
    size: int
    modified_at: datetime


class StorageExistsSensor(Sensor[StorageExistsConfig, StorageExistsOutput]):
    """Waits for an object to appear at a URI; each poke is one stat or one listing."""

    spec = SensorSpec(id="storage.exists", summary="Wait for an object to appear at a URI.")
    config_model: ClassVar[type[BaseModel]] = StorageExistsConfig
    output_model: ClassVar[type[BaseModel]] = StorageExistsOutput

    async def poke(self, config: StorageExistsConfig, ctx: StepContext) -> StorageExistsOutput | NotYet:
        """Observe once, read-only: stat a plain URI, list a pattern, take the first match."""
        found = await _first_match(config, ctx)
        if found is None:
            ctx.log.debug("nothing at the uri yet", uri=config.uri, min_size=config.min_size)
            return NotYet()
        ctx.log.info("object found", uri=found.uri, bytes=found.size)
        return StorageExistsOutput(uri=found.uri, size=found.size, modified_at=found.modified_at)


async def _first_match(config: StorageExistsConfig, ctx: StepContext) -> StatResult | None:
    """Find the first object satisfying the config, whether it names one or a pattern."""
    if any(character in config.uri for character in GLOB_CHARACTERS):
        async for result in ctx.storage.list(config.uri):
            if result.size >= config.min_size:
                return result
        return None
    found = await ctx.storage.stat(config.uri)
    if found is None or found.size < config.min_size:
        return None
    return found
