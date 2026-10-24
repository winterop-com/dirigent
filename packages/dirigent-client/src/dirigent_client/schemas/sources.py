"""Sources: what an input arrives as, the source rows that take inputs, and their journal."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from dirigent_client.enums import BodyKind


class RequestFacts(BaseModel):
    """What an HTTP request arrived as, read once: the shape the playground and an endpoint share."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    method: str
    """The HTTP method the call was made with."""

    path: str
    """The concrete path, without the query."""

    query: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    """The query arguments as strings, with a repeated name arriving as a list."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    """The request headers, lowercased."""

    content_type: str | None = None
    """The content type the body arrived under, as the header spelled it."""

    body_kind: BodyKind = BodyKind.NONE
    """How the body was read. A body appears once, in ``body``."""

    body: JsonValue = None
    """The body, decoded the way ``body_kind`` says. Null when there was none."""

    body_bytes: int = 0
    """How large the body was, in bytes."""


class EndpointInput(RequestFacts):
    """The output of an endpoint source, which is the input its pipeline's next steps read.

    ``headers`` never carries the credential the caller presented: ``authorization``, the
    cookie and the signature header are removed before the input is written.
    """

    route: str
    """The template the source declares, which the concrete path matched."""

    path_params: dict[str, str] = Field(default_factory=dict[str, str])
    """What each ``{name}`` in the template matched, as a string."""

    received_at: datetime
    """When the input arrived, or when a hand run supplied it."""
