"""The playground: a request-and-response service the instance serves itself.

Unauthenticated, because a pipeline step calling its own instance's playground must not need
a token, and because there is nothing here to protect: no database session is opened, no
instance data is read, and nothing is remembered between requests.

Every route answers the same envelope. ``kind`` names the answer, ``request`` holds what
arrived verbatim, and every other key is what the route decided -- the knobs resolved, after
defaults and after a seed was drawn. So ``request.args.rows`` is the string that was sent
and ``rows`` is the number that was used.

``/playground/stream`` is the one route that cannot repeat the envelope, because a stream has
one set of headers and many bodies. It sends the envelope as its first line instead, and the
lines after it carry only what changes.

Nothing here generates records. A field map is Faker, Faker lives in the block family that
contributes ``playground.generate``, and the server does not depend on a block package: blocks
are contributed through pluginkit and run on workers, and a server-only install in a split
deployment must not have to carry the built-in block set to serve an API. So the division is
along what each surface is for -- the routes hand a consumer bytes arriving over time, and the
blocks put generated data into a pipeline, which is where the field map belongs.
"""

import asyncio
import base64
import binascii
import json
import secrets
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final
from urllib.parse import unquote_plus, urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, JsonValue

from dirigent_common import Duration, Size, filler
from dirigent_server.errors import Refusal
from dirigent_server.messages import (
    PLAYGROUND_BAD_KNOB,
    PLAYGROUND_HEADER_REFUSED,
    PLAYGROUND_OFF_INSTANCE,
    PLAYGROUND_UNAUTHENTICATED,
)

router = APIRouter(tags=["playground"])

PREFIX: Final = "/playground"

#: Reflected as this rather than repeated, so a page on this origin cannot read a session
#: cookie back out of the playground that ``httponly`` exists to keep from it.
REDACTED: Final = "<redacted>"

#: Request headers whose value is never reflected, only their presence.
SECRET_HEADERS: Final = frozenset({"authorization", "cookie", "proxy-authorization"})

#: Statuses that carry no body, so the reflection has nowhere to go.
BODYLESS: Final = frozenset({204, 304})

#: The redirect statuses the playground will issue. A 304 is not a redirect and carries no
#: body, and no other 3xx is one a client follows.
REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})

#: The longest redirect chain one call may ask for.
MAX_HOPS: Final = 10

#: The longest a call may be asked to take before answering. The same ceiling the
#: ``playground.generate`` node puts on its own ``delay``.
MAX_DELAY: Final = timedelta(seconds=30)

#: Response headers the playground will not set on itself, because each one would make this
#: origin do something for a caller that is not teaching anything: plant a cookie, open the
#: origin to another site, or weaken what a browser enforces here.
FORBIDDEN_HEADERS: Final = frozenset(
    {
        "connection",
        "content-length",
        "content-security-policy",
        "set-cookie",
        "set-cookie2",
        "strict-transport-security",
        "transfer-encoding",
        "upgrade",
        "x-frame-options",
    }
)

#: Query names the routes read as knobs, so ``response-headers`` never sets one as a header.
RESERVED_ARGS: Final = frozenset({"delay", "status"})

#: The most messages one stream may be asked for.
MAX_STREAM_MESSAGES: Final = 100

#: The longest gap one stream may be asked to leave between messages.
MAX_GAP: Final = timedelta(seconds=10)

#: The longest a whole stream may take. The gap and the message count multiply, so each one
#: being inside its own bound is not enough to keep an unauthenticated connection short.
MAX_SPAN: Final = timedelta(seconds=60)

#: The largest filler one stream message may carry. The same ceiling the ``playground.generate``
#: node puts on its own ``payload``, which is the same filler at the same size.
MAX_PAYLOAD: Final = 1024 * 1024

#: What a stream is served as: one JSON record per line, which is the shape every record this
#: project emits already has, and what ``jq`` reads a line at a time.
NDJSON: Final = "application/x-ndjson"

#: The credential ``/playground/auth`` accepts. Public constants, documented as such: they
#: protect nothing and unlock nothing but this one route's 200.
BASIC_USERNAME: Final = "playground"
BASIC_PASSWORD: Final = "playground"
BEARER_TOKEN: Final = "playground-token"


class RequestFacts(BaseModel):
    """What arrived, verbatim: the same shape on every playground answer."""

    method: str
    """The HTTP method the call was made with."""

    url: str
    """The whole URL as this instance saw it, query string included."""

    path: str
    """The path alone, without the query."""

    args: dict[str, JsonValue]
    """The query arguments as strings, with a repeated name arriving as a list."""

    headers: dict[str, str]
    """The request headers, lowercased. A credential's presence is shown, never its value."""

    body: JsonValue = None
    """The body, decoded the way ``body_kind`` says. Null when there was none."""

    body_kind: str = "none"
    """How the body was read: ``none``, ``json``, ``form`` or ``text``. A body appears once."""

    body_bytes: int = 0
    """How large the body was, in bytes."""

    content_type: str | None = None
    """The content type the body arrived under, as the header spelled it."""


class Answer(BaseModel):
    """The envelope every playground route answers with."""

    kind: str
    """What this answer is, which is what a reader dispatches on."""

    request: RequestFacts
    """What the call arrived as."""


class Reflection(Answer):
    """A call reflected back, with nothing added."""

    status: int
    """The status this answer was given."""


class Redirect(Answer):
    """One hop of a redirect chain."""

    status: int
    """The redirect status this hop answered with."""

    location: str
    """Where this hop points, which is the next hop or the destination."""

    hops: int
    """How many hops remain after this one."""


class Unreliable(Answer):
    """A call that fails while the attempt it names is inside the failing window."""

    status: int
    """The status this answer was given."""

    attempt: int
    """Which attempt the caller said this is."""

    fail_until: int
    """How many attempts fail before one succeeds."""

    outcome: str
    """``failed`` while the window lasts, then ``succeeded``."""


class SetHeaders(Answer):
    """The headers the playground set on the way back."""

    status: int
    """The status this answer was given."""

    headers: dict[str, str]
    """Every header this answer set, exactly as it was asked to."""


class StreamOpened(Answer):
    """A stream's first line: the request facts, and every knob the lines after it run under.

    A stream has one set of headers and many bodies, so the envelope cannot ride on each
    message the way it rides on every other playground answer. It is sent once, here.
    """

    messages: int
    """How many messages follow this line."""

    gap_ms: int
    """How long the stream waits before each message, in milliseconds."""

    payload_bytes: int | None = None
    """How large the filler on each message is, when a payload size was asked for."""


class StreamMessage(BaseModel):
    """One message of a stream, carrying only what the first line could not say in advance."""

    kind: str = "stream.message"
    """What this line is, which is what a reader dispatches on."""

    offset: int
    """Its place in the stream, counting from zero."""

    sent_at: datetime
    """When this message left the instance."""

    elapsed_ms: int
    """How long after the first line this message left, so a cadence can be measured."""

    payload: str | None = None
    """The filler that was asked for, when a payload size was set."""


class StreamClosed(BaseModel):
    """A stream's last line, which is how a reader tells an ending from a cut connection."""

    kind: str = "stream.closed"
    """What this line is, which is what a reader dispatches on."""

    messages: int
    """How many messages the stream sent."""

    duration_ms: int
    """How long the whole stream took, from its first line to this one."""


class Credential(Answer):
    """A call that presented a credential the playground accepts."""

    status: int
    """The status this answer was given."""

    authenticated: bool
    """Always true: a call that was not authenticated is refused rather than answered."""

    scheme: str
    """Which HTTP authentication scheme the accepted credential used."""


def _args(request: Request) -> dict[str, JsonValue]:
    """The query string as the playground reports it: one value a string, a repeated one a list."""
    gathered: dict[str, list[str]] = {}
    for name, value in request.query_params.multi_items():
        gathered.setdefault(name, []).append(value)
    return {name: values[0] if len(values) == 1 else list(values) for name, values in gathered.items()}


def _headers(request: Request) -> dict[str, str]:
    """The request headers, lowercased, with every credential's value replaced."""
    return {
        name.lower(): REDACTED if name.lower() in SECRET_HEADERS else value for name, value in request.headers.items()
    }


def _body(raw: bytes, content_type: str | None) -> tuple[JsonValue, str]:
    """Decode a body once, and say how it was decoded."""
    if not raw:
        return None, "none"
    media = (content_type or "").split(";")[0].strip().lower()
    text = raw.decode("utf-8", errors="replace")
    if media == "application/json":
        try:
            return json.loads(text), "json"
        except json.JSONDecodeError:
            return text, "text"
    if media == "application/x-www-form-urlencoded":
        gathered: dict[str, JsonValue] = {}
        for pair in text.split("&"):
            if not pair:
                continue
            name, _, value = pair.partition("=")
            gathered[unquote_plus(name)] = unquote_plus(value)
        return gathered, "form"
    return text, "text"


async def _facts(request: Request) -> RequestFacts:
    """Gather what arrived, for the envelope every route shares."""
    raw = await request.body()
    content_type = request.headers.get("content-type")
    body, body_kind = _body(raw, content_type)
    return RequestFacts(
        method=request.method,
        url=str(request.url),
        path=request.url.path,
        args=_args(request),
        headers=_headers(request),
        body=body,
        body_kind=body_kind,
        body_bytes=len(raw),
        content_type=content_type,
    )


def _answer(model: BaseModel, code: int, headers: dict[str, str] | None = None) -> Response:
    """Send one answer, leaving out the body where the status cannot carry one."""
    if code in BODYLESS or code < 200:
        return Response(status_code=code, headers=headers)
    return JSONResponse(model.model_dump(mode="json"), status_code=code, headers=headers)


def _bad_knob(detail: str) -> Refusal:
    """Refuse a knob the playground could not honour, naming what was wrong with it."""
    return Refusal(PLAYGROUND_BAD_KNOB, status=http_status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


async def _delayed(delay: timedelta) -> None:
    """Take as long as the delay asks for, refusing one longer than the playground allows."""
    if delay < timedelta(0) or delay > MAX_DELAY:
        raise _bad_knob(f"a delay is between 0 and {int(MAX_DELAY.total_seconds())}s")
    if delay > timedelta(0):
        await asyncio.sleep(delay.total_seconds())


StatusArg = Annotated[int, Query(ge=100, le=599, description="The status to answer with.")]
DelayArg = Annotated[Duration, Query(description="How long to take before answering, as `250ms` or `2s`.")]


@router.api_route(
    f"{PREFIX}/request",
    methods=["GET"],
    operation_id="playgroundRequestGet",
    summary="Reflect a GET back",
    response_model=Reflection,
)
@router.api_route(
    f"{PREFIX}/request",
    methods=["POST"],
    operation_id="playgroundRequestPost",
    summary="Reflect a POST and its body back",
    response_model=Reflection,
)
@router.api_route(
    f"{PREFIX}/request",
    methods=["PUT"],
    operation_id="playgroundRequestPut",
    summary="Reflect a PUT and its body back",
    response_model=Reflection,
)
@router.api_route(
    f"{PREFIX}/request",
    methods=["PATCH"],
    operation_id="playgroundRequestPatch",
    summary="Reflect a PATCH and its body back",
    response_model=Reflection,
)
@router.api_route(
    f"{PREFIX}/request",
    methods=["DELETE"],
    operation_id="playgroundRequestDelete",
    summary="Reflect a DELETE back",
    response_model=Reflection,
)
async def reflect(request: Request, status: StatusArg = 200, delay: DelayArg = timedelta(0)) -> Response:
    """Answer with what arrived, under the status that was asked for.

    The degenerate route: every other one reflects too, and adds an answer of its own.
    """
    await _delayed(delay)
    return _answer(Reflection(kind="request", request=await _facts(request), status=status), status)


@router.get(
    f"{PREFIX}/redirect",
    operation_id="playgroundRedirect",
    summary="Issue a redirect, or a chain of them",
    response_model=Redirect,
    status_code=http_status.HTTP_302_FOUND,
    responses={422: {"description": "A status that is not a redirect, or a destination off this instance."}},
)
async def redirect(
    request: Request,
    hops: Annotated[int, Query(ge=1, le=MAX_HOPS, description="How many redirects to issue before arriving.")] = 1,
    to: Annotated[
        str | None,
        Query(description="Where the last hop points, as a path on this instance. Defaults to the reflection route."),
    ] = None,
    status: Annotated[int, Query(description="The redirect status each hop answers with.")] = 302,
    delay: DelayArg = timedelta(0),
) -> Response:
    """Point at the next hop, or at the destination when this is the last one.

    The destination is a path on this instance and never an absolute URL: an open redirect
    is a phishing tool wearing the instance's own domain, and there is nothing to teach
    that needs one.
    """
    if status not in REDIRECTS:
        raise _bad_knob(f"{status} is not a redirect status; use one of {sorted(REDIRECTS)}")
    destination = _destination(request, to)
    await _delayed(delay)
    location = destination if hops <= 1 else _next_hop(request, hops - 1, to, status)
    answer = Redirect(
        kind="redirect",
        request=await _facts(request),
        status=status,
        location=location,
        hops=hops - 1,
    )
    return _answer(answer, status, headers={"location": location})


def _destination(request: Request, to: str | None) -> str:
    """Where the chain ends: a path on this instance, defaulting to the reflection route."""
    if to is None:
        return f"{request.url.path.removesuffix('/redirect')}/request"
    if not to.startswith("/") or to.startswith("//"):
        raise Refusal(
            PLAYGROUND_OFF_INSTANCE,
            status=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            to=to,
        )
    return to


def _next_hop(request: Request, hops: int, to: str | None, status: int) -> str:
    """The same route again with one fewer hop, so a chain walks itself down to the destination."""
    query = {"hops": str(hops), "status": str(status)}
    if to is not None:
        query["to"] = to
    return f"{request.url.path}?{urlencode(query)}"


@router.get(
    f"{PREFIX}/unreliable",
    operation_id="playgroundUnreliable",
    summary="Fail until a given attempt, then succeed",
    response_model=Unreliable,
)
async def unreliable(
    request: Request,
    attempt: Annotated[int, Query(ge=1, description="Which attempt the caller says this is.")] = 1,
    fail_until: Annotated[int, Query(ge=0, description="How many attempts fail before one succeeds.")] = 1,
    status: Annotated[int, Query(ge=100, le=599, description="The status answered while failing.")] = 503,
    delay: DelayArg = timedelta(0),
) -> Response:
    """Answer the failing status while the attempt is inside the window, and 200 after it.

    The window is driven by the attempt the caller names, because the playground remembers
    nothing between requests and an answer that depended on what it remembered could not be
    reproduced.
    """
    await _delayed(delay)
    failing = attempt <= fail_until
    code = status if failing else http_status.HTTP_200_OK
    answer = Unreliable(
        kind="unreliable",
        request=await _facts(request),
        status=code,
        attempt=attempt,
        fail_until=fail_until,
        outcome="failed" if failing else "succeeded",
    )
    return _answer(answer, code)


@router.get(
    f"{PREFIX}/stream",
    operation_id="playgroundStream",
    summary="Send a stream of messages instead of one body",
    response_model=None,
    responses={
        200: {"content": {NDJSON: {}}, "description": "One JSON record per line: an envelope, messages, an end."},
        422: {"description": "A stream that would run longer than the playground holds a connection open."},
    },
)
async def stream(
    request: Request,
    messages: Annotated[
        int,
        Query(ge=1, le=MAX_STREAM_MESSAGES, description="How many messages to send after the envelope."),
    ] = 5,
    every: Annotated[Duration, Query(description="How long to wait before each message, as `250ms` or `2s`.")] = (
        timedelta(seconds=1)
    ),
    payload: Annotated[
        Size | None,
        Query(description="Filler of this size on every message, as `16kb`, to make each one large."),
    ] = None,
    delay: DelayArg = timedelta(0),
) -> Response:
    """Send an envelope, then a message every ``every``, then a line saying the stream ended.

    The one route whose answer arrives in pieces, for a consumer that has to be tested against
    bytes that turn up over time rather than a body that is already whole. It generates
    nothing: a message carries its offset, when it was sent, how long after the envelope that
    was, and the filler a ``payload`` asked for.
    """
    if every < timedelta(0) or every > MAX_GAP:
        raise _bad_knob(f"a gap is between 0 and {int(MAX_GAP.total_seconds())}s")
    if payload is not None and payload > MAX_PAYLOAD:
        raise _bad_knob(f"a payload is at most {MAX_PAYLOAD} bytes")
    if messages * every > MAX_SPAN:
        raise _bad_knob(
            f"{messages} messages {int(every.total_seconds() * 1000)}ms apart would hold the "
            f"connection open longer than {int(MAX_SPAN.total_seconds())}s"
        )
    await _delayed(delay)
    opened = StreamOpened(
        kind="stream",
        request=await _facts(request),
        messages=messages,
        gap_ms=round(every.total_seconds() * 1000),
        payload_bytes=payload,
    )
    return StreamingResponse(
        _lines(opened, every, None if payload is None else filler(payload)),
        media_type=NDJSON,
        # A stream a proxy holds until it is whole is not a stream, and the point of the route
        # is that its pieces arrive apart.
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


async def _lines(opened: StreamOpened, every: timedelta, padding: str | None) -> AsyncIterator[str]:
    """The lines one stream sends: the envelope, a message per gap, and the end."""
    started = time.monotonic()
    yield opened.model_dump_json() + "\n"
    for offset in range(opened.messages):
        if every > timedelta(0):
            await asyncio.sleep(every.total_seconds())
        message = StreamMessage(
            offset=offset,
            sent_at=datetime.now(UTC),
            elapsed_ms=round((time.monotonic() - started) * 1000),
            payload=padding,
        )
        yield message.model_dump_json() + "\n"
    closed = StreamClosed(messages=opened.messages, duration_ms=round((time.monotonic() - started) * 1000))
    yield closed.model_dump_json() + "\n"


@router.get(
    f"{PREFIX}/response-headers",
    operation_id="playgroundResponseHeaders",
    summary="Set the query's pairs as response headers",
    response_model=SetHeaders,
    responses={422: {"description": "A header this origin will not set on itself."}},
)
async def response_headers(request: Request, status: StatusArg = 200, delay: DelayArg = timedelta(0)) -> Response:
    """Set each query argument as a response header, so a client's header handling has something to read."""
    await _delayed(delay)
    chosen: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name in RESERVED_ARGS:
            continue
        if name.lower() in FORBIDDEN_HEADERS:
            raise Refusal(
                PLAYGROUND_HEADER_REFUSED,
                status=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                header=name,
            )
        chosen[name] = value
    answer = SetHeaders(kind="headers", request=await _facts(request), status=status, headers=chosen)
    return _answer(answer, status, headers=chosen)


@router.get(
    f"{PREFIX}/auth",
    operation_id="playgroundAuth",
    summary="Require a credential the playground documents",
    response_model=Credential,
    responses={401: {"description": "No credential, or one the playground does not accept."}},
)
async def auth(request: Request, status: StatusArg = 200, delay: DelayArg = timedelta(0)) -> Response:
    """Accept the documented basic pair or the documented bearer token, and refuse anything else.

    The credential is a public constant. It guards nothing: it exists so a document can be
    seen presenting one, and so the reflection can be seen redacting it.
    """
    await _delayed(delay)
    scheme = _scheme(request.headers.get("authorization"))
    if scheme is None:
        raise Refusal(
            PLAYGROUND_UNAUTHENTICATED,
            status=http_status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="playground"'},
            username=BASIC_USERNAME,
        )
    answer = Credential(
        kind="auth",
        request=await _facts(request),
        status=status,
        authenticated=True,
        scheme=scheme,
    )
    return _answer(answer, status)


def _scheme(header: str | None) -> str | None:
    """Which scheme an acceptable credential used, or None when there was not one."""
    if not header:
        return None
    kind, _, presented = header.partition(" ")
    lowered = kind.lower()
    if lowered == "bearer" and secrets.compare_digest(presented.strip(), BEARER_TOKEN):
        return "bearer"
    if lowered == "basic" and _basic(presented.strip()):
        return "basic"
    return None


def _basic(presented: str) -> bool:
    """Whether a base64 basic credential is the documented pair."""
    try:
        decoded = base64.b64decode(presented, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    return secrets.compare_digest(decoded, f"{BASIC_USERNAME}:{BASIC_PASSWORD}")


__all__ = ["PREFIX", "router"]
