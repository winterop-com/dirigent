"""What every other wire model is built out of: the base itself, one refusal, and one page."""

from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    """A frozen shape that crosses the wire."""

    model_config = ConfigDict(frozen=True)


class Problem(WireModel):
    """One refusal, in the one shape every error response takes."""

    status: int
    """The HTTP status, repeated in the body so a logged payload is self-contained."""

    title: str
    """The short, stable name of the condition: the status phrase."""

    detail: str
    """One sentence a person can act on."""

    problems: list[str] = Field(default_factory=list[str])
    """The individual failures, when the refusal is a list of them rather than one."""

    instance: str | None = None
    """The path that was asked for, redacted of any credential it carried."""


class Page[T](WireModel):
    """One page of a listing, and the cursor that continues it."""

    items: list[T]
    """The rows of this page, in the listing's own order."""

    next: str | None = None
    """The opaque cursor a caller passes as ``after`` to continue, or nothing at the end."""
