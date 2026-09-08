"""The generic storage blocks: copy bytes between URIs, and wait for an object to appear."""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

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
