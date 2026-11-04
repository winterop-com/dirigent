"""Schemas: named JSON Schemas an instance holds, addressable by code and referenced by name."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, JsonValue

from dirigent_client.schemas.common import RequestModel, WireModel
from dirigent_common import EntityName, JsonMap


class SchemaIn(RequestModel):
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


class SchemaUpdate(RequestModel):
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
    """A schema as every response shows it: the identity quartet, the body, and what names it."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    body: JsonMap
    created_at: datetime
    updated_at: datetime
    used_by: list[str] = Field(default_factory=list[str])
    """The codes of the stored pipelines whose current version names this schema, in code order.

    A reader deciding whether to change a shape is deciding for these pipelines, so every
    response carries them rather than leaving a surface to ask a second time. Empty means
    nothing stored names it, and editing or removing it is nobody else's business."""


class CheckSchemaRequest(RequestModel):
    """A value, and the schema to check it against: a stored one by its code, or a body not yet stored.

    Exactly one of ``code`` and ``body`` is given. A body is what an editor holds before it is
    saved, and is checked to be a valid JSON Schema before the value is checked against it.
    """

    value: JsonValue
    """The value to check. An explicit null is a value like any other and is checked as one."""

    code: str | None = None
    body: JsonMap | None = None


class SchemaViolation(WireModel):
    """One way a value fails a schema: where in the value, which keyword refused it, and why."""

    at: str
    """A JSON Pointer into the value, empty for the value itself."""

    keyword: str
    """The keyword that refused it, such as ``required`` or ``minimum``."""

    schema_at: str
    """The way through the schema to the keyword that refused it, as a JSON Pointer. A ``$ref``
    is walked through in place, so past one the pointer names the path the check took rather
    than where the keyword is written."""

    message: str


class SchemaCheck(WireModel):
    """What checking a value against a schema found, with the validator a ``validate.schema`` step uses."""

    valid: bool
    errors: list[SchemaViolation] = Field(default_factory=list[SchemaViolation])
    """Every way the value fails, earliest place in the value first, a hundred at most."""

    omitted: int = 0
    """How many more failures there were past the ones listed."""
