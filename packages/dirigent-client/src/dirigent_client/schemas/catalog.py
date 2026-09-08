"""The block catalog: what an instance can run, and the schemas a form is built from."""

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, Field

from dirigent_common import API_VERSION, JsonMap


class BlockKind(StrEnum):
    """Which block surface a catalog entry describes."""

    OPERATOR = "operator"
    """Does work; may finish synchronously or return a remote handle."""

    SENSOR = "sensor"
    """Waits for the world through durable, scheduled pokes."""


class BlockEntry(BaseModel):
    """One block in the catalog, with the schemas a form is built from."""

    id: str
    kind: BlockKind
    summary: str
    group: str
    plugin: str
    idempotent: bool = False
    local_execution: bool = False
    default_poll_seconds: float | None = None
    default_deadline_seconds: float | None = None
    config_schema: JsonMap = Field(default_factory=dict)
    output_schema: JsonMap = Field(default_factory=dict)


class SurfaceEntry(BaseModel):
    """One catalog entry for a non-block surface: a scheme, a notifier, a connection kind."""

    id: str
    plugin: str
    config_schema: JsonMap = Field(default_factory=dict)
    secret_fields: list[str] = Field(default_factory=list[str])
    """Which config fields this surface declares secret, so a form draws them write-only."""


class Catalog(BaseModel):
    """The host's merged view of every contribution."""

    api_version: int = API_VERSION
    plugins: list[str] = Field(default_factory=list[str])
    blocks: list[BlockEntry] = Field(default_factory=list[BlockEntry])
    storage_schemes: list[SurfaceEntry] = Field(default_factory=list[SurfaceEntry])
    notifiers: list[SurfaceEntry] = Field(default_factory=list[SurfaceEntry])
    connection_kinds: list[SurfaceEntry] = Field(default_factory=list[SurfaceEntry])

    def block(self, block_id: str) -> BlockEntry | None:
        """Find one catalog entry by block id."""
        return next((entry for entry in self.blocks if entry.id == block_id), None)

    @property
    def digest(self) -> str:
        """Hash the catalog, so a worker registry row can prove code parity across nodes."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"
