"""The storage kind: each object that appears under a prefix, or matching a glob, becomes one input.

A worker lists the location on the source's cadence and hands over what is newer than its
cursor, oldest first. The cursor is the last object handed over, by its modification time and
then its URI, so an object written later with an earlier timestamp than one already handed
over is not seen.
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
        """List the location, and hand over what is newer than the cursor, oldest first."""
        listed = [found async for found in ctx.storage.list(config.uri)]
        mark = _mark_of(cursor)
        newer = sorted((one for one in listed if mark is None or _key(one) > mark), key=_key)[:limit]
        if not newer:
            return Polled(inputs=[], cursor=cursor)
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
        last = newer[-1]
        ctx.log.info("objects found", location=config.uri, found=len(inputs))
        return Polled(inputs=inputs, cursor={"modified_at": last.modified_at.isoformat(), "uri": last.uri})


def _key(found: StatResult) -> tuple[datetime, str]:
    """Order objects by when they were modified, then by URI."""
    return (found.modified_at, found.uri)


def _mark_of(cursor: JsonMap | None) -> tuple[datetime, str] | None:
    """Read the last object a cursor handed over, or None for a source that has handed over nothing."""
    if cursor is None:
        return None
    modified, uri = cursor.get("modified_at"), cursor.get("uri")
    if not isinstance(modified, str) or not isinstance(uri, str):
        return None
    try:
        return (datetime.fromisoformat(modified), uri)
    except ValueError:
        return None
