"""What every other wire model is built out of: the bases themselves, one refusal, and one page."""

from typing import Annotated, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, JsonValue, field_validator

from dirigent_common import Issue, JsonMap
from dirigent_common.depth import shown
from dirigent_common.storable import refuse_unstorable


class WireModel(BaseModel):
    """A frozen shape that crosses the wire."""

    model_config = ConfigDict(frozen=True)


def _shown(value: JsonValue) -> JsonValue:
    """A stored value cut where it nests deeper than a run stores, before pydantic walks it."""
    return shown(value)


#: A stored JSON value a read answers with, which a row from before the bound can nest past it.
StoredJson = Annotated[JsonMap | None, BeforeValidator(_shown)]


class RequestModel(BaseModel):
    """A body a caller writes, whose text is refused when no database stores it as written."""

    @field_validator("*")
    @classmethod
    def _storable(cls, value: object) -> object:
        """Refuse a NUL or half a surrogate pair in any text field, or list of text."""
        for element in cast("list[object]", value) if isinstance(value, list) else [value]:
            refuse_unstorable(element)
        return value


class Problem(WireModel):
    """One refusal, in the one shape every error response takes."""

    status: int
    """The HTTP status, repeated in the body so a logged payload is self-contained."""

    title: str
    """The short, stable name of the condition: the status phrase."""

    detail: str
    """One sentence a person can act on."""

    code: str
    """The dotted code of the message the detail was rendered from."""

    params: JsonMap = Field(default_factory=dict)
    """The specifics the detail rendered, for a re-render in another language."""

    problems: list[Issue] = Field(default_factory=list[Issue])
    """The individual failures, when the refusal is a list of them rather than one."""

    instance: str | None = None
    """The path that was asked for, redacted of any credential it carried."""


class Page[T](WireModel):
    """One page of a listing, and the cursor that continues it."""

    items: list[T]
    """The rows of this page, in the listing's own order."""

    next: str | None = None
    """The opaque cursor a caller passes as ``after`` to continue, or nothing at the end."""
