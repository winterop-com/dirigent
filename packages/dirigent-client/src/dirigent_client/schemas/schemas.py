"""Schemas: named JSON Schemas an instance holds, addressable by code and referenced by name."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from dirigent_client.schemas.common import WireModel
from dirigent_common import EntityName, JsonMap


class SchemaIn(BaseModel):
    """What storing a schema sends: the JSON Schema itself, and an identity it need not repeat.

    The body is a JSON Schema in its own right. Its identity is read from the schema's own
    keywords when the caller leaves it out -- ``$id`` for the code, ``title`` for the name,
    ``description`` for the description -- so a portable schema file stores as one without a
    dirigent wrapper. A code given here wins over ``$id``; a code given neither way, with no
    ``$id`` and no filename to fall back on, is refused.
    """

    code: EntityName | None = None
    name: str | None = None
    description: str | None = None
    body: JsonMap = Field(default_factory=dict)
    """The JSON Schema, checked to be a valid schema before anything is stored."""


class SchemaUpdate(BaseModel):
    """What editing a schema may change; the code is fixed once minted.

    A field left out is left alone, and a field sent as null is cleared. The body, when
    sent, replaces the stored schema and is checked the same way a create's is.
    """

    name: str | None = None
    description: str | None = None
    body: JsonMap | None = None

    def changing(self, field: str) -> bool:
        """Report whether the request said anything about this field at all."""
        return field in self.model_fields_set


class SchemaOut(WireModel):
    """A schema as every response shows it: the identity quartet and the schema body."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    body: JsonMap
    created_at: datetime
    updated_at: datetime
