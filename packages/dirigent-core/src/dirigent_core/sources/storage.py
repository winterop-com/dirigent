"""The storage kind: each object that appears under a prefix, or matching a glob, becomes one input.

A worker lists the location on the source's cadence and hands over every object it has not
handed over before, oldest first. The cursor maps each object handed over that is still listed
to its modification time, so an object is new whatever its timestamp, an object rewritten in
place is handed over again, and the cursor holds as many entries as the location holds objects.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from dirigent_common import Duration, JsonMap
from dirigent_plugin.blocks import StatResult
from dirigent_plugin.sources import PollContext, Polled, PolledSource, SourceHosting, SourceSpec


class StorageConfig(BaseModel):
    """A storage source: where to look, and how often."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    uri: str = Field(min_length=1)
    """A prefix such as ``s3://landing/incoming/``, or a glob such as ``file:///data/in/*.csv``."""

    poll: Duration = timedelta(minutes=1)
    """How long a worker waits between two looks."""

    max_in_flight: int | None = Field(default=None, ge=1)
    """How many unsettled runs from this source may exist before the next look waits for one to settle."""


class StorageInput(BaseModel):
    """One object that appeared."""

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)

    uri: str
    """Where the object is, which a step reads it from."""

    size_bytes: int = 0
    modified_at: datetime
    content_type: str | None = None
    received_at: datetime
    """When the worker found it, or when a hand run supplied it."""


class StorageSource(PolledSource[StorageConfig, StorageInput]):
    """Objects appearing under a storage location."""

    spec = SourceSpec(
        kind="storage",
        summary="An object that appears under a storage prefix, or matching a glob",
        hosting=SourceHosting.POLLED,
        default_poll=timedelta(minutes=1),
    )
    config_model = StorageConfig
    output_model = StorageInput

    def poll_every(self, config: StorageConfig) -> timedelta:
        """Look as often as the source declares."""
        return config.poll

    def max_in_flight(self, config: StorageConfig) -> int | None:
        """Bound the unsettled runs the way the source declares."""
        return config.max_in_flight

    def cursor_key(self, config: StorageConfig) -> JsonMap | None:
        """Keep the cursor for as long as the source looks in the same place."""
        return {"uri": config.uri}

    def summary_of(self, config: StorageConfig) -> str | None:
        """Name the location the source looks in."""
        return config.uri

    def label_of(self, output: StorageInput) -> str | None:
        """Name an input by the object it found."""
        return output.uri

    def complete(self, config: StorageConfig, given: JsonMap, *, received_at: datetime) -> StorageInput:
        """Make a hand run's input whole: an object it names, dated now unless it says otherwise."""
        return StorageInput.model_validate(
            {"modified_at": received_at, **given, "received_at": given.get("received_at", received_at)}
        )

    async def poll(
        self, config: StorageConfig, cursor: JsonMap | None, ctx: PollContext, limit: int
    ) -> Polled[StorageInput]:
        """List the location, and hand over what the cursor has not seen, oldest first."""
        listed = [found async for found in ctx.storage.list(config.uri)]
        seen = _seen_of(cursor)
        unseen = sorted((one for one in listed if seen.get(one.uri) != _stamp(one)), key=_key)
        newer = unseen[:limit]
        kept = {one.uri: _stamp(one) for one in listed if seen.get(one.uri) == _stamp(one)}
        if not newer:
            return Polled(inputs=[], cursor={"seen": kept} if kept else None)
        now = datetime.now(UTC)
        inputs = [
            StorageInput(
                uri=one.uri,
                size_bytes=one.size,
                modified_at=one.modified_at,
                content_type=one.content_type,
                received_at=now,
            )
            for one in newer
        ]
        ctx.log.info("objects found", location=config.uri, found=len(inputs))
        return Polled(inputs=inputs, cursor={"seen": kept | {one.uri: _stamp(one) for one in newer}})


def _key(found: StatResult) -> tuple[datetime, str]:
    """Order objects by when they were modified, then by URI."""
    return (found.modified_at, found.uri)


def _stamp(found: StatResult) -> str:
    """Write an object's modification time the way the cursor keeps it."""
    return found.modified_at.isoformat()


def _seen_of(cursor: JsonMap | None) -> dict[str, str]:
    """Read the objects a cursor has handed over, by URI, or none for a source that has handed over nothing."""
    seen = cursor.get("seen") if cursor is not None else None
    if not isinstance(seen, dict):
        return {}
    return {uri: stamp for uri, stamp in seen.items() if isinstance(uri, str) and isinstance(stamp, str)}
