"""Sources: what an input arrives as, the source rows that take inputs, and their journal."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from dirigent_client.enums import BodyKind, InputOutcome, SourceState
from dirigent_client.schemas.common import WireModel
from dirigent_common import JsonMap


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


class SourceOut(WireModel):
    """A source as a listing shows it: what it listens to, its state, and what it has taken, never its token."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: UUID
    pipeline: str
    """The code of the pipeline the source belongs to."""

    code: str
    """The source's step key."""

    name: str | None = None
    description: str | None = None
    kind: str
    state: SourceState
    methods: list[str] = Field(default_factory=list[str])
    """The methods a received source answers; empty for a kind the server does not receive."""

    route: str | None = None
    """The template a received source answers, under the instance's endpoint prefix."""

    url_path: str | None = None
    """Where a received source is called: the endpoint prefix and the template."""

    auth: str | None = None
    """How a caller of a received source authenticates: ``token`` or ``public``."""

    token_prefix: str | None = None
    """The leading characters of a bearer token, so a caller's copy can be told apart."""

    secret_fingerprint: str | None = None
    """For an ``hmac`` source, 12 hex characters of a hash of its signing secret, keyed by the instance."""

    signature_header: str | None = None
    """For an ``hmac`` source, the header a caller's signature of the body arrives in."""

    in_flight: int = 0
    """How many runs it started are unsettled."""

    max_in_flight: int | None = None
    """How many unsettled runs it allows before refusing an input, or null for no bound."""

    accepted: int = 0
    """How many inputs became runs."""

    refused: int = 0
    """How many inputs were refused once their caller was let in."""

    last_input_at: datetime | None = None
    summary: str | None = None
    """What the source listens to, in one line its kind writes, such as the prefix it polls."""

    polled_at: datetime | None = None
    """When a poll of a polled source last succeeded."""

    next_poll_at: datetime | None = None
    failures: int = 0
    """How many polls in a row have failed."""

    last_error: str | None = None
    created_at: datetime


class SourceTokenOut(WireModel):
    """A credential freshly minted for a source, returned once and never readable again."""

    source_id: UUID
    pipeline: str
    code: str
    auth: str = "token"
    """``token`` for a bearer token a caller presents, ``hmac`` for a secret a caller signs the body with."""

    header: str | None = None
    """For ``hmac``, the header the signature arrives in."""

    token: str
    """The token, or the signing secret."""

    prefix: str | None = None
    """The leading characters of a bearer token."""

    fingerprint: str | None = None
    """For ``hmac``, 12 hex characters of a hash of the signing secret, keyed by the instance."""

    url_path: str
    """Where the source is called, so a caller can be configured without assembling the path by hand."""


class SetSecretRequest(WireModel):
    """The signing secret a sender issued, to replace the one the instance minted."""

    secret: SecretStr


class SourceChanges(WireModel):
    """What applying a document did to the source rows its pipeline holds."""

    created: list[str] = Field(default_factory=list[str])
    updated: list[str] = Field(default_factory=list[str])
    removed: list[str] = Field(default_factory=list[str])
    tokens: list[SourceTokenOut] = Field(default_factory=list[SourceTokenOut])
    """The tokens minted for the sources this apply created, each shown here and nowhere else again."""

    @property
    def empty(self) -> bool:
        """Report whether the apply left every source row exactly as it was."""
        return not (self.created or self.updated or self.removed)


class SourceInputOut(WireModel):
    """One input that reached a source, and the run or the refusal it became."""

    id: int
    created_at: datetime
    outcome: InputOutcome
    status: int | None = None
    """The HTTP status the caller was answered with, or null for an input a worker polled."""

    run_id: UUID | None = None
    code: str | None = None
    """The refusal's message code, or null for an accepted input."""

    reason: str | None = None
    params: JsonMap | None = None
    method: str | None = None
    path: str | None = None
    label: str | None = None
    """What a polled kind names the input, such as the object it found."""

    body_bytes: int = 0
    duration_ms: int = 0
    caller: str | None = None


class InputAccepted(WireModel):
    """What a caller of a source is answered with when its input became a run."""

    run_id: UUID
    status: str
    """The status the run was created in."""

    run_url: str
    """Where the run is read, under the versioned API."""
