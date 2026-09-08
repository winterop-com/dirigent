"""What this instance is, whether it is well, and which nodes are picking work up."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dirigent_client.enums import WorkerStatus
from dirigent_client.schemas.common import WireModel
from dirigent_common import JsonMap


class ConnectionHealth(WireModel):
    """What one connection reported when it was asked."""

    code: str
    name: str | None = None
    kind: str
    connected: bool
    detail: str | None = None
    version: str | None = None


class SystemInfo(WireModel):
    """What this instance is, and whether it is well."""

    name: str = "dirigent"
    version: str
    environment: str
    database: str
    checked_at: datetime
    plugins: list[str] = Field(default_factory=list[str])
    blocks: int = 0
    storage_schemes: list[str] = Field(default_factory=list[str])
    """Every scheme a URI in a document may address, including the one core ships."""

    notifiers: list[str] = Field(default_factory=list[str])
    connection_kinds: list[str] = Field(default_factory=list[str])
    workers_live: int = 0
    unsafe_blocks_enabled: list[str] = Field(default_factory=list[str])
    secrets_configured: bool = False
    connections: list[ConnectionHealth] = Field(default_factory=list[ConnectionHealth])


class WorkerOut(WireModel):
    """One worker as the registry knows it."""

    id: UUID
    name: str
    hostname: str
    version: str
    status: WorkerStatus
    concurrency: int
    tags: list[str] = Field(default_factory=list[str])
    plugins: JsonMap = Field(default_factory=dict)
    catalog_digest: str | None = None
    code_matches_server: bool = True
    """Whether this worker's catalog is the same code the server is running."""

    stale: bool = False
    """Whether its heartbeat is old enough that it is presumed gone."""

    created_at: datetime
    last_seen_at: datetime


class CheckStatus(StrEnum):
    """How one dependency is doing; the worst status across checks becomes the answer."""

    HEALTHY = "healthy"
    """Reachable and behaving."""

    DEGRADED = "degraded"
    """Usable, but not as it should be; readiness still succeeds."""

    UNHEALTHY = "unhealthy"
    """Unusable; readiness fails and the process should not receive traffic."""


class CheckResult(BaseModel):
    """What one health check reports."""

    status: CheckStatus
    detail: str | None = None


class Health(BaseModel):
    """The liveness answer: the process is running and can serve requests."""

    status: Literal["ok"] = "ok"
    version: str


class Readiness(BaseModel):
    """The readiness answer: the worst status across the checks, and each check's own."""

    status: CheckStatus
    checks: dict[str, CheckResult]
