"""The source contract: where an input enters a pipeline, and how a kind turns it into one.

A source is a pipeline's first node. Each input it takes becomes one run, in which the node is
already settled and its output is the input. A kind is hosted one of three ways: the server
receives it, a worker polls it, or a worker holds it open.
"""

import re
from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar, Final, Literal, Protocol

from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field

from dirigent_common import Issue, JsonMap, Message
from dirigent_plugin.blocks import ConnectionRef, ErrorClass, Logger, Storage, classify_default
from dirigent_plugin.messages import (
    ROUTE_BAD_PARAMETER,
    ROUTE_BAD_SEGMENT,
    ROUTE_NOT_ROOTED,
    ROUTE_REPEATED_PARAMETER,
    ROUTE_TAIL_NOT_LAST,
)

#: What a document writes as ``source.kind``: a bare word, or a pack's dotted one.
SOURCE_KIND_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"

#: The methods a received source may declare.
ROUTE_METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE")

#: One template parameter: ``{name}`` matches a segment, ``{name:path}`` the rest of the path.
_PARAMETER: Final = re.compile(r"^\{([a-z_][a-z0-9_]*)(:path)?\}$")

#: What a literal segment may hold: anything a path segment carries but a brace or a query.
_LITERAL: Final = re.compile(r"^[^{}?#/]+$")


class SourceHosting(StrEnum):
    """Where a kind's inputs come from, which decides what runs it."""

    RECEIVED = "received"
    """The server takes a request and turns it into an input."""

    POLLED = "polled"
    """A worker asks on a cadence, from the source's row."""

    HELD = "held"
    """A worker holds a listener open under a lease."""


class SourceSpec(BaseModel):
    """The catalog entry for a source kind."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(pattern=SOURCE_KIND_PATTERN)
    summary: str = Field(min_length=1)
    group: str | None = None
    hosting: SourceHosting
    replies: bool = False
    """Whether a reply node may answer an input of this kind."""

    default_poll: timedelta | None = None


class SourceAuth(BaseModel):
    """How a received source authenticates its callers."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    kind: Literal["token", "hmac", "public"] = "token"
    """``token`` takes ``Authorization: Bearer`` with the token the instance minted; ``hmac`` takes a
    signature of the body, made with the source's signing secret; ``public`` admits anyone."""

    header: str = Field(default="X-Dirigent-Signature", min_length=1)
    """For ``hmac``, the header the signature arrives in: the hex HMAC-SHA256 of the raw body,
    with or without a leading ``sha256=``."""


class SourceRate(BaseModel):
    """How fast one received source takes calls: a bucket refilled at ``per_minute``, holding ``burst``."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    per_minute: int = Field(default=600, ge=1)
    burst: int | None = Field(default=None, ge=1)
    """How many calls the bucket holds when it is full; ``per_minute`` when unset."""


class Route(BaseModel):
    """The methods and the path template a received source answers.

    A template is rooted, and each segment is a literal, ``{name}``, or a closing
    ``{name:path}`` that takes the rest of the path.
    """

    model_config = ConfigDict(frozen=True)

    methods: tuple[str, ...]
    template: str

    @property
    def normalised(self) -> str:
        """Spell the template without its parameter names, which is what two routes collide on."""
        return "/".join(_blank(segment) for segment in self.template.split("/"))

    @property
    def literal_segments(self) -> int:
        """Count the literal segments, which is how specific a match on this template is."""
        return sum(1 for segment in _segments(self.template) if _PARAMETER.match(segment) is None)

    def match(self, path: str) -> dict[str, str] | None:
        """Read the path parameters this template takes from a concrete path, or None when it does not match."""
        written = _segments(self.template)
        given = _segments(path)
        taken: dict[str, str] = {}
        for index, segment in enumerate(written):
            parameter = _PARAMETER.match(segment)
            if parameter is not None and parameter.group(2):
                rest = given[index:]
                if not rest:
                    return None
                taken[parameter.group(1)] = "/".join(rest)
                return taken
            if index >= len(given):
                return None
            if parameter is not None:
                taken[parameter.group(1)] = given[index]
            elif segment != given[index]:
                return None
        return taken if len(given) == len(written) else None

    def fill(self, path_params: dict[str, str]) -> str:
        """Write the concrete path this template takes for a set of parameters, leaving a missing one as written."""
        filled: list[str] = []
        for segment in self.template.split("/"):
            parameter = _PARAMETER.match(segment)
            filled.append(path_params.get(parameter.group(1), segment) if parameter is not None else segment)
        return "/".join(filled)


def _segments(path: str) -> list[str]:
    """Split a path into its segments, ignoring the leading slash and a trailing one."""
    return [segment for segment in path.strip("/").split("/") if segment != ""] if path.strip("/") else []


def _blank(segment: str) -> str:
    """Replace a parameter's name with nothing, keeping whether it takes a tail."""
    parameter = _PARAMETER.match(segment)
    if parameter is None:
        return segment
    return "{:path}" if parameter.group(2) else "{}"


def template_issues(template: str) -> list[Issue]:
    """Say what is wrong with a path template, or nothing when it is one."""
    if not template.startswith("/"):
        return [Issue.of(ROUTE_NOT_ROOTED, template=repr(template))]
    segments = _segments(template)
    issues: list[Issue] = []
    seen: set[str] = set()
    for index, segment in enumerate(segments):
        parameter = _PARAMETER.match(segment)
        if parameter is None:
            if "{" in segment or "}" in segment:
                issues.append(Issue.of(ROUTE_BAD_PARAMETER, template=repr(template), segment=repr(segment)))
            elif _LITERAL.match(segment) is None:
                issues.append(Issue.of(ROUTE_BAD_SEGMENT, template=repr(template), segment=repr(segment)))
            continue
        name = parameter.group(1)
        if name in seen:
            issues.append(Issue.of(ROUTE_REPEATED_PARAMETER, template=repr(template), name=repr(name)))
        seen.add(name)
        if parameter.group(2) and index != len(segments) - 1:
            issues.append(Issue.of(ROUTE_TAIL_NOT_LAST, template=repr(template), segment=repr(segment)))
    return issues


class InboundRequest(BaseModel):
    """One request as a received kind is handed it: the head, and the body once it is read.

    ``headers`` holds every header lowercased, credentials included, because a kind that
    verifies a signature needs the one it was sent; what a kind writes into its output is its
    own business.
    """

    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    route: str
    """The template the path matched."""

    path_params: dict[str, str] = Field(default_factory=dict[str, str])
    query: list[tuple[str, str]] = Field(default_factory=list[tuple[str, str]])
    """The query string's pairs in the order they were written, a repeated name repeated."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    body: bytes = b""
    received_at: datetime

    @property
    def content_type(self) -> str | None:
        """The content type the body arrived under, as the header spelled it."""
        return self.headers.get("content-type")


class Ignore(BaseModel):
    """An input that is a sign of life and creates no run, such as a handshake or a heartbeat."""

    model_config = ConfigDict(frozen=True)

    reason: str | None = None


class Refusal(BaseModel):
    """An input a kind refuses before any run exists, and the status its caller is answered with."""

    model_config = ConfigDict(frozen=True)

    status: int
    code: str
    message: str
    params: JsonMap = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict[str, str])

    @classmethod
    def of(cls, message: Message, /, *, status: int, headers: dict[str, str] | None = None, **params: Any) -> "Refusal":
        """Build a refusal by rendering a catalogued message with its params."""
        return cls(
            status=status,
            code=message.code,
            message=message.render(**params),
            params=params,
            headers=dict(headers or {}),
        )


class ReceiveContext(Protocol):
    """What a received kind may reach while it turns a request into an input: no connection, no secret."""

    @property
    def log(self) -> Logger:
        """Where the kind says what it did with the request."""
        ...

    @property
    def format_checker(self) -> FormatChecker:
        """The instance's assembled format checker."""
        ...


class PollContext(Protocol):
    """What a polled kind may reach while it asks for new inputs: storage bound as the instance configures it."""

    @property
    def log(self) -> Logger:
        """Where the kind says what it found."""
        ...

    @property
    def storage(self) -> Storage:
        """Storage, every scheme configured from the connection the instance names for it."""
        ...


class HoldContext(Protocol):
    """What a held kind may reach while it listens: storage, and the connections the instance holds."""

    @property
    def log(self) -> Logger:
        """Where the kind says what it is doing."""
        ...

    @property
    def storage(self) -> Storage:
        """Storage, every scheme configured from the connection the instance names for it."""
        ...

    def connection[C: BaseModel](self, ref: ConnectionRef, model: type[C]) -> C:
        """Resolve a connection by code, opened and validated against the kind's own model."""
        ...


class Listener[OutputT: BaseModel](Protocol):
    """One open consumer a held kind answers ``listen`` with."""

    async def receive(self, limit: int, wait: timedelta) -> list[OutputT]:
        """Take at most ``limit`` inputs, waiting no longer than ``wait`` for the first."""
        ...

    async def ack(self) -> None:
        """Acknowledge every input received so far, once each has become a run."""
        ...


class Polled[OutputT: BaseModel](BaseModel):
    """What one poll found: the inputs, oldest first, and where the next poll carries on from."""

    model_config = ConfigDict(frozen=True)

    inputs: list[OutputT] = Field(default_factory=list[OutputT])
    cursor: JsonMap | None = None
    """Stored once every input became a run, and handed to the next poll."""


class Source[ConfigT: BaseModel, OutputT: BaseModel](ABC):
    """One source kind: its config, its output, and what it refuses at apply."""

    spec: ClassVar[SourceSpec]
    config_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    mark: ClassVar[str | None] = None
    """The ``d`` of one SVG path on a 24-unit grid the kind is drawn by, or None to be drawn by its hosting."""

    def check_config(self, config: ConfigT) -> list[Issue]:
        """List the refusals this kind makes at apply beyond its config schema, located under ``source``."""
        return []

    def max_in_flight(self, config: ConfigT) -> int | None:
        """Say how many unsettled runs from this source may exist before an input is refused, or None for no bound."""
        return None

    def cursor_key(self, config: ConfigT) -> JsonMap | None:
        """Name the config that a stored cursor belongs to; a change of it resets the cursor."""
        return None

    def classify_error(self, error: Exception) -> ErrorClass:
        """Classify a failure the kind raised."""
        return classify_default(error)

    @abstractmethod
    def complete(self, config: ConfigT, given: JsonMap, *, received_at: datetime) -> OutputT:
        """Build a whole input from a partial one, filling what it omits from the config.

        A hand run and a sample are written as much of an input as matters, and this is what
        makes them one the next step can read. It raises ``ValueError`` for one it cannot make
        whole.
        """
        ...

    def summary_of(self, config: ConfigT) -> str | None:
        """Say in one line what this source listens to, for a listing."""
        return None


class ReceivedSource[ConfigT: BaseModel, OutputT: BaseModel](Source[ConfigT, OutputT]):
    """A kind the server receives: a route, a check on the head, then the body read into an input."""

    @abstractmethod
    def route(self, config: ConfigT) -> Route:
        """Name the methods and the template this source answers."""
        ...

    def max_body(self, config: ConfigT) -> int | None:
        """Say how many bytes of body this source reads at most, or None for the instance's cap."""
        return None

    def auth(self, config: ConfigT) -> SourceAuth:
        """Say how a caller authenticates: a token the instance mints, unless the config writes out public."""
        return SourceAuth()

    def rate(self, config: ConfigT) -> SourceRate | None:
        """Say how fast this source takes calls, or None for the instance's intake bucket alone."""
        return None

    def admit(self, config: ConfigT, head: InboundRequest) -> Refusal | None:
        """Refuse a request on its head alone, before a byte of its body is read."""
        return None

    @abstractmethod
    async def receive(
        self, config: ConfigT, request: InboundRequest, ctx: ReceiveContext
    ) -> OutputT | Ignore | Refusal:
        """Turn one request into an input, an ignored sign of life, or a refusal.

        It runs in the server process: it does no I/O beyond the request it was handed.
        """
        ...


class PolledSource[ConfigT: BaseModel, OutputT: BaseModel](Source[ConfigT, OutputT]):
    """A kind a worker asks on a cadence, carrying a cursor from one poll to the next."""

    def poll_every(self, config: ConfigT) -> timedelta:
        """Say how long a worker waits between two polls of this source."""
        return self.spec.default_poll or DEFAULT_POLL

    def label_of(self, output: OutputT) -> str | None:
        """Name one input in a line of the source's journal, such as the object it found."""
        return None

    @abstractmethod
    async def poll(self, config: ConfigT, cursor: JsonMap | None, ctx: PollContext, limit: int) -> Polled[OutputT]:
        """Find what is new since the cursor, at most ``limit`` inputs, oldest first.

        A failure it raises is the source's: it is recorded on the row and the next poll backs
        off, from the same cursor.
        """
        ...


class HeldSource[ConfigT: BaseModel, OutputT: BaseModel](Source[ConfigT, OutputT]):
    """A kind a worker holds open under a lease: a consumer whose messages are the inputs.

    The worker makes a run of each input it receives, commits them, and only then acknowledges
    them, so an input is never lost and may, after a crash between the two, arrive twice.
    """

    def label_of(self, output: OutputT) -> str | None:
        """Name one input in a line of the source's journal, such as where it was read from."""
        return None

    @abstractmethod
    def listen(self, config: ConfigT, ctx: HoldContext) -> AbstractAsyncContextManager[Listener[OutputT]]:
        """Open a consumer for as long as the worker holds the source; leaving it closes the consumer.

        A failure it raises, opening or receiving, is the source's: it is recorded on the row,
        the lease is let go, and the source is taken up again after a backoff.
        """
        ...


#: How long a worker waits between two polls of a kind whose spec names no cadence.
DEFAULT_POLL: Final = timedelta(minutes=1)

type AnySource = Source[Any, Any]
