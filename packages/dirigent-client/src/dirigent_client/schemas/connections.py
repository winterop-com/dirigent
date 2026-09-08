"""Connections: coded credential records of a contributed kind, redacted in every response."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from dirigent_client.schemas.common import WireModel
from dirigent_common import EntityName, JsonMap


class ConnectionIn(BaseModel):
    """What creating or replacing a connection sends; secret fields are write-only."""

    code: EntityName
    name: str | None = None
    kind: str = Field(min_length=1, max_length=100)
    description: str | None = None
    config: JsonMap = Field(default_factory=dict)
    """The kind's own config, validated against its published model before anything is stored."""


class ConnectionUpdate(BaseModel):
    """What editing a connection may change; the kind and code are fixed once minted.

    A field left out is left alone, and a field sent as null is cleared. Those are different
    requests, so they are told apart by what the body contained rather than by the value
    landing as ``None`` either way.
    """

    name: str | None = None
    description: str | None = None
    config: JsonMap | None = None

    def changing(self, field: str) -> bool:
        """Report whether the request said anything about this field at all."""
        return field in self.model_fields_set


class ConnectionOut(WireModel):
    """A connection as every response shows it: settings visible, secrets redacted."""

    id: UUID
    code: str
    name: str | None = None
    kind: str
    description: str | None = None
    config: JsonMap
    secret_fields: list[str] = Field(default_factory=list[str])
    """Which fields the kind declares secret, so a form knows what to render as a password."""

    last_check_at: datetime | None = None
    last_check_healthy: bool | None = None
    last_check_detail: str | None = None
    created_at: datetime
    updated_at: datetime
