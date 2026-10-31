"""The endpoint kind: a request made to this instance, at a route its source declares, becomes the input.

It takes JSON (``application/json`` and any ``+json``), a urlencoded form, and text. Anything
else is refused before its body is read, and a file is posted as a URI in a JSON body.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Final, Literal, cast
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from dirigent_client.enums import BodyKind
from dirigent_client.schemas import EndpointInput
from dirigent_common import Issue, JsonMap, Size
from dirigent_common.requests import form_values, gather_values, media_type
from dirigent_core.messages import (
    BODY_WITHOUT_TYPE,
    ENDPOINT_ACCEPTS_REFUSED,
    ENDPOINT_BODY_NOT_JSON,
    ENDPOINT_BODY_NOT_TEXT,
    ENDPOINT_BODY_TOO_DEEP,
    ENDPOINT_CHARSET_REFUSED,
    ENDPOINT_METHOD_NOT_DECLARED,
    ENDPOINT_PATH_PARAMS_MISSING,
    UNSUPPORTED_MEDIA,
)
from dirigent_plugin.sources import (
    Ignore,
    InboundRequest,
    ReceiveContext,
    ReceivedSource,
    Refusal,
    Route,
    SourceAuth,
    SourceHosting,
    SourceRate,
    SourceSpec,
    template_issues,
)

#: What an endpoint takes when its source names nothing: every body family it can read.
DEFAULT_ACCEPTS: Final = ("application/json", "application/*+json", "application/x-www-form-urlencoded", "text/*")

FORM: Final = "application/x-www-form-urlencoded"

#: Headers an input never carries, because each one is a credential the caller presented.
CREDENTIAL_HEADERS: Final = frozenset({"authorization", "cookie", "proxy-authorization", "x-dirigent-signature"})


def _credentials(config: "EndpointConfig") -> frozenset[str]:
    """Name every header a caller of this source presents a credential in, its own signature header included."""
    if config.auth.kind == "hmac":
        return CREDENTIAL_HEADERS | {config.auth.header.lower()}
    return CREDENTIAL_HEADERS


#: The most levels of lists and objects a JSON body may nest, well inside what pydantic walks
#: once a body sits in an input, a step's output and a resolved config.
MAX_BODY_DEPTH: Final = 128

#: What a text body is decoded with when its content type names no charset.
DEFAULT_CHARSET: Final = "utf-8"

#: Every charset a text body may name, lowercased, and the codec that reads it. A caller's name
#: is never handed to Python's codec lookup, which also finds codecs whose cost grows faster than
#: their input.
CHARSETS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "utf-8": "utf-8",
        "utf8": "utf-8",
        "utf-16": "utf-16",
        "utf-16le": "utf-16-le",
        "utf-16be": "utf-16-be",
        "us-ascii": "ascii",
        "ascii": "ascii",
        "iso-8859-1": "latin-1",
        "latin-1": "latin-1",
        "latin1": "latin-1",
        "windows-1252": "cp1252",
    }
)

type Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class EndpointConfig(BaseModel):
    """An endpoint source: a route on this instance, the bodies it takes, and the limits it holds."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    path: str
    """The path template under the instance's endpoint prefix: ``/customers/{id}``, or ``{rest:path}`` for a tail."""

    methods: list[Method] = Field(default_factory=lambda: cast("list[Method]", ["POST"]), min_length=1)
    """The methods answered at the path; another method at it is answered 405."""

    accepts: list[str] | None = None
    """The content types a body may arrive as; unset takes JSON, forms and text."""

    max_body: Size | None = None
    """The largest body read, below the instance's own cap; one byte past it is refused 413."""

    auth: SourceAuth = SourceAuth()
    """How a caller authenticates: a token by default, or ``{kind: public}`` when written out."""

    rate: SourceRate = SourceRate()
    """How fast calls are taken; one past it is answered 429 before its body is read."""

    max_in_flight: int | None = Field(default=None, ge=1)
    """How many unsettled runs from this source may exist before a new input is refused 503."""


def body_family(media: str | None) -> BodyKind | None:
    """Say how a body of this media type is read, or None when an endpoint cannot read it."""
    if media is None:
        return None
    if media == "application/json" or (media.startswith("application/") and media.endswith("+json")):
        return BodyKind.JSON
    if media == FORM:
        return BodyKind.FORM
    if media.startswith("text/"):
        return BodyKind.TEXT
    return None


def accepts_media(pattern: str, media: str) -> bool:
    """Match one media type against one ``accepts`` entry, which may be ``text/*`` or ``application/*+json``."""
    written = pattern.strip().lower()
    if written == media:
        return True
    kind, _, subtype = written.partition("/")
    given_kind, _, given_subtype = media.partition("/")
    if kind != given_kind:
        return False
    if subtype == "*":
        return True
    return subtype.startswith("*+") and given_subtype.endswith(subtype[1:])


class EndpointSource(ReceivedSource[EndpointConfig, EndpointInput]):
    """A route on this instance: its requests are the inputs, and a reply node may answer them."""

    spec = SourceSpec(
        kind="endpoint",
        summary="A request made to this instance at a route the source declares",
        hosting=SourceHosting.RECEIVED,
        replies=True,
    )
    config_model = EndpointConfig
    output_model = EndpointInput

    def route(self, config: EndpointConfig) -> Route:
        """Answer the declared methods at the declared template."""
        return Route(methods=tuple(config.methods), template=config.path)

    def max_body(self, config: EndpointConfig) -> int | None:
        """Read at most what the source declares."""
        return config.max_body

    def auth(self, config: EndpointConfig) -> SourceAuth:
        """Take the token the instance minted, unless the source writes out public."""
        return config.auth

    def rate(self, config: EndpointConfig) -> SourceRate:
        """Take calls as fast as the source declares."""
        return config.rate

    def max_in_flight(self, config: EndpointConfig) -> int | None:
        """Bound the unsettled runs the way the source declares."""
        return config.max_in_flight

    def check_config(self, config: EndpointConfig) -> list[Issue]:
        """Refuse a template that is not one, and a content type an endpoint cannot read."""
        issues = [issue.model_copy(update={"location": "path"}) for issue in template_issues(config.path)]
        for index, pattern in enumerate(config.accepts or ()):
            if not _readable_pattern(pattern):
                issues.append(Issue.of(ENDPOINT_ACCEPTS_REFUSED, location=f"accepts.{index}", accepts=repr(pattern)))
        return issues

    def summary_of(self, config: EndpointConfig) -> str | None:
        """Name the bodies the endpoint takes."""
        return ", ".join(config.accepts or DEFAULT_ACCEPTS)

    def admit(self, config: EndpointConfig, head: InboundRequest) -> Refusal | None:
        """Refuse a content type the endpoint does not take, and a body that names none, before reading it."""
        accepted = list(config.accepts or DEFAULT_ACCEPTS)
        media, _ = media_type(head.content_type)
        if media is None:
            if _declares_a_body(head.headers):
                return Refusal.of(BODY_WITHOUT_TYPE, status=415, accepted=", ".join(accepted))
            return None
        if body_family(media) is None or not any(accepts_media(pattern, media) for pattern in accepted):
            return Refusal.of(UNSUPPORTED_MEDIA, status=415, accepted=", ".join(accepted), content_type=media)
        return None

    async def receive(
        self, config: EndpointConfig, request: InboundRequest, ctx: ReceiveContext
    ) -> EndpointInput | Ignore | Refusal:
        """Read the body the way its content type says, and write the request down as the input."""
        media, params = media_type(request.content_type)
        body: JsonValue = None
        kind = BodyKind.NONE
        if request.body:
            family = body_family(media)
            if family is None:
                accepted = ", ".join(config.accepts or DEFAULT_ACCEPTS)
                return Refusal.of(BODY_WITHOUT_TYPE, status=415, accepted=accepted)
            read = _read_body(request.body, family, params.get("charset") or DEFAULT_CHARSET)
            if isinstance(read, Refusal):
                return read
            body, kind = read, family
        return EndpointInput(
            method=request.method,
            path=request.path,
            route=request.route,
            path_params=dict(request.path_params),
            query=gather_values(request.query),
            headers={name: value for name, value in request.headers.items() if name not in _credentials(config)},
            content_type=request.content_type,
            body_kind=kind,
            body=body,
            body_bytes=len(request.body),
            received_at=request.received_at,
        )

    def complete(self, config: EndpointConfig, given: JsonMap, *, received_at: datetime) -> EndpointInput:
        """Make a partial input whole: the first declared method, the template filled, the body sized."""
        route = self.route(config)
        method = str(given.get("method") or route.methods[0]).upper()
        if method not in route.methods:
            raise ValueError(ENDPOINT_METHOD_NOT_DECLARED.render(method=method, methods=", ".join(route.methods)))
        raw_params = given.get("path_params")
        written = cast("JsonMap", raw_params) if isinstance(raw_params, dict) else {}
        path_params = {str(name): str(value) for name, value in written.items()}
        missing = [name for name in _template_parameters(config.path) if name not in path_params]
        if missing and "path" not in given:
            raise ValueError(ENDPOINT_PATH_PARAMS_MISSING.render(names=", ".join(missing)))
        body = given.get("body")
        content_type = given.get("content_type")
        if content_type is None and body is not None:
            content_type = "text/plain" if isinstance(body, str) else "application/json"
        media, _ = media_type(cast("str | None", content_type))
        kind = given.get("body_kind") or (body_family(media) if body is not None else BodyKind.NONE)
        filled: JsonMap = {
            "method": method,
            "path": given.get("path") or route.fill(path_params),
            "route": config.path,
            "path_params": path_params,
            "query": given.get("query") or {},
            "headers": given.get("headers") or {},
            "content_type": content_type,
            "body_kind": kind or BodyKind.TEXT,
            "body": body,
            "body_bytes": given.get("body_bytes", _size_of(body, kind)),
            "received_at": given.get("received_at") or received_at.isoformat(),
        }
        return EndpointInput.model_validate(filled)


def _readable_pattern(pattern: str) -> bool:
    """Say whether an ``accepts`` entry names only bodies an endpoint can read."""
    media, _ = media_type(pattern)
    if media is None:
        return False
    return (
        media in ("application/json", FORM)
        or media.startswith("text/")
        or (media.startswith("application/") and media.endswith("+json"))
    )


def _declares_a_body(headers: dict[str, str]) -> bool:
    """Say whether a request's head promises a body."""
    length = headers.get("content-length", "").strip()
    return (length.isdigit() and int(length) > 0) or "transfer-encoding" in headers


def _read_body(raw: bytes, family: BodyKind, charset: str) -> JsonValue | Refusal:
    """Decode one body of a family the endpoint takes, or refuse it 400."""
    if family is BodyKind.JSON:
        try:
            value = cast("JsonValue", json.loads(raw))
        except ValueError as error:
            return Refusal.of(ENDPOINT_BODY_NOT_JSON, status=400, detail=str(error))
        except RecursionError:
            return Refusal.of(ENDPOINT_BODY_TOO_DEEP, status=400, limit=MAX_BODY_DEPTH)
        if _nests_past(value, MAX_BODY_DEPTH):
            return Refusal.of(ENDPOINT_BODY_TOO_DEEP, status=400, limit=MAX_BODY_DEPTH)
        return value
    codec = CHARSETS.get(charset.strip().lower()) if family is BodyKind.TEXT else "ascii"
    if codec is None:
        return Refusal.of(ENDPOINT_CHARSET_REFUSED, status=415, charset=repr(charset), accepted=", ".join(CHARSETS))
    try:
        text = raw.decode(codec)
    except UnicodeError as error:
        return Refusal.of(ENDPOINT_BODY_NOT_TEXT, status=400, charset=charset, detail=str(error))
    return form_values(text) if family is BodyKind.FORM else text


def _nests_past(value: JsonValue, limit: int) -> bool:
    """Say whether a parsed body holds a list or object more than ``limit`` levels down."""
    level = [value]
    for _ in range(limit):
        level = [
            child
            for held in level
            if isinstance(held, dict | list)
            for child in (held.values() if isinstance(held, dict) else held)
        ]
        if not level:
            return False
    return any(isinstance(held, dict | list) for held in level)


def _template_parameters(template: str) -> list[str]:
    """Name the parameters a template takes, in the order it writes them."""
    names: list[str] = []
    for segment in template.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            names.append(segment[1:-1].split(":", 1)[0])
    return names


def _size_of(body: JsonValue, kind: object) -> int:
    """Measure what a body would have been on the wire, for an input written by hand."""
    if body is None:
        return 0
    if isinstance(body, str):
        return len(body.encode())
    if kind == BodyKind.FORM and isinstance(body, dict):
        return len(urlencode(cast("dict[str, object]", body), doseq=True).encode())
    return len(json.dumps(body, separators=(",", ":")).encode())


__all__ = ["DEFAULT_ACCEPTS", "EndpointConfig", "EndpointSource"]
