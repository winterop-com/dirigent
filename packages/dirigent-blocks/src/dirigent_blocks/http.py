"""The generic HTTP blocks: one operator that calls a service, one sensor that waits for one."""

import json
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import timedelta
from typing import ClassVar, Literal

import httpx2
from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_blocks.connections import HttpConnectionConfig
from dirigent_common import BlockModel, Duration, Size, StorageUri
from dirigent_plugin import (
    BlockFailure,
    ErrorClass,
    NotYet,
    Operator,
    OperatorSpec,
    RemoteHandle,
    Sensor,
    SensorSpec,
    StepContext,
)

type HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

MAX_TEXT_BYTES = 64 * 1024

DEFAULT_TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"


class HttpTarget(BlockModel):
    """The half of an HTTP block's config that says which service to talk to."""

    connection: str | None = None
    """The code of the connection whose base URL, auth, TLS, and timeout apply."""

    url: str | None = None
    """An absolute URL, for the case where no connection is configured."""

    path: str = "/"
    """The path resolved against the connection's base URL."""

    timeout: Duration | None = Field(default=None, gt=timedelta(0))
    """Overrides the connection's timeout for this call alone."""

    follow_redirects: bool = False
    """Whether a 3xx is followed rather than returned as the answer.

    A redirect to another host arrives without the connection's credentials: the client drops
    the ``Authorization`` header when the origin changes, so a service that redirects before
    authenticating must be configured with the URL it redirects to.
    """

    @model_validator(mode="after")
    def _require_a_target(self) -> "HttpTarget":
        """Reject a config that names neither a connection nor an absolute URL."""
        if not self.connection and not self.url:
            raise ValueError("an HTTP block needs either a connection or an absolute url")
        return self


def client_for(target: HttpTarget, ctx: StepContext) -> httpx2.AsyncClient:
    """Build the client one call uses: the connection's, or a bare one for an absolute URL."""
    if target.connection:
        return ctx.http(target.connection)
    fallback: timedelta = HttpConnectionConfig.model_fields["timeout"].default
    return httpx2.AsyncClient(timeout=(target.timeout or fallback).total_seconds())


def request_timeout(target: HttpTarget, client: httpx2.AsyncClient) -> httpx2.Timeout:
    """The timeout one request carries: the step's override, or the client's own.

    ``build_request`` reads an explicit ``timeout=None`` as "no timeout on any phase" rather
    than as "whatever the client is configured with", so a step that configures no override
    is given the client's own timeout rather than the unset field.
    """
    if target.timeout is None:
        return client.timeout
    return httpx2.Timeout(target.timeout.total_seconds())


def request_url(target: HttpTarget) -> str:
    """Resolve what one call requests: the absolute URL, or the path on the connection."""
    return target.url or target.path


def decode(response: httpx2.Response, payload: bytes) -> tuple[JsonValue | None, str | None]:
    """Split a body into its parsed JSON and its text, whichever it turned out to be."""
    if "json" in response.headers.get("content-type", ""):
        try:
            parsed: JsonValue = json.loads(payload)
        except ValueError:
            return None, _as_text(payload)
        return parsed, None
    return None, _as_text(payload)


def _as_text(payload: bytes) -> str:
    """Render a body as the text an output carries, cut to what may be inlined."""
    return payload[:MAX_TEXT_BYTES].decode("utf-8", errors="replace")


async def read_bounded(response: httpx2.Response, limit: int) -> bytes:
    """Read a whole body, refusing one larger than the step said it would hold.

    Counted as it arrives rather than trusted from a header, because content-length is the
    service's claim and this is the worker's memory.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            raise BlockFailure(
                f"the response is larger than max_response ({limit} bytes) and is not being saved; "
                f"raise max_response, or give save_to a URI to stream it to",
                error_class=ErrorClass.REJECTED,
            )
        chunks.append(chunk)
    return b"".join(chunks)


class HttpRequestConfig(HttpTarget):
    """What one HTTP call sends, and which responses count as success."""

    method: HttpMethod = "GET"
    query: dict[str, str | int | float | bool] = Field(default_factory=dict[str, str | int | float | bool])
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    body: JsonValue | None = None
    """A value sent as a JSON document, for an endpoint that takes JSON.

    Serialised and sent as ``application/json``. Mutually exclusive with the other body forms.
    """

    text: str | None = None
    """A string sent as the request body verbatim, for an endpoint that takes a raw document.

    Sent byte for byte, with the content type the ``headers`` name or
    ``text/plain; charset=utf-8`` when they name none. This is what a query language, an XML
    document, or a CSV upload goes in. Mutually exclusive with the other body forms.
    """

    form: dict[str, str] | None = None
    """Fields sent as an HTML form, for an endpoint that takes one.

    Encoded and sent as ``application/x-www-form-urlencoded``. Mutually exclusive with the
    other body forms.
    """

    body_from: StorageUri | None = None
    """A storage URI whose object is sent as the request body, streamed rather than held.

    The bytes go from storage onto the wire a chunk at a time and are never held whole, so a
    file larger than the worker's memory is a POST rather than a dead worker. ``Content-Length``
    is the size storage reports for the object, and a URI naming nothing is refused before the
    call is made. The output then carries ``sent_bytes``. Mutually exclusive with the other
    body forms.
    """

    content_type: str | None = None
    """The content type sent with ``body_from``, for a backend that stores none.

    Storage may already know what the object is -- an S3 object carries its content type,
    a file on disk does not -- and what it reports is used when this is unset. A step whose
    backend reports none and which names none here is refused, because an endpoint reading
    a body it was not told the type of is guessing.
    """

    success_status: list[int] = Field(default_factory=list[int])
    """Status codes that count as success; empty means any 2xx."""

    max_response: Size = 32 * 1024 * 1024
    """How much of a response is read into memory when it is not streamed to storage.

    A body has to be whole to be parsed, so one too large to hold is refused rather than
    truncated: half a JSON document is not a smaller answer, it is a wrong one, and a step
    that acted on it would be acting on something the service never said. ``save_to`` streams
    instead, and is bounded by the storage rather than by this.
    """

    save_to: StorageUri | None = None
    """A storage URI to stream the response body to, instead of carrying it inline.

    The body goes to storage a chunk at a time and is never held whole, so a response larger
    than the worker's memory is a file rather than a dead worker. The step's output then
    carries ``body_uri`` and ``body_bytes`` rather than ``json_body`` or ``text``: a body
    worth saving is one the next step reads from storage.
    """

    @model_validator(mode="after")
    def _one_payload_at_most(self) -> "HttpRequestConfig":
        """Reject a config that names more than one way to fill the request body."""
        named = [name for name in ("body", "text", "form", "body_from") if getattr(self, name) is not None]
        if len(named) > 1:
            raise ValueError(f"an HTTP request carries one body: {', '.join(named)} were all configured")
        return self

    def request_body(self) -> tuple[dict[str, str], bytes | None, dict[str, str] | None, JsonValue | None]:
        """The headers and the three httpx2 body arguments one request is built with."""
        headers = dict(self.headers)
        if self.text is not None:
            if not any(name.lower() == "content-type" for name in headers):
                headers["content-type"] = DEFAULT_TEXT_CONTENT_TYPE
            return headers, self.text.encode("utf-8"), None, None
        return headers, None, self.form, self.body


class HttpRequestOutput(BlockModel):
    """What one HTTP call observed, which downstream steps reference by field."""

    status: int
    headers: dict[str, str]
    json_body: JsonValue | None = None
    text: str | None = None
    duration_ms: int
    body_uri: str | None = None
    """Where the body was written, when ``save_to`` asked for it."""

    body_bytes: int | None = None
    """How many bytes were written there."""

    sent_bytes: int | None = None
    """How many bytes of request body were streamed out of ``body_from``."""


class StoredBody:
    """A request body streamed out of storage, counting the bytes it hands the client."""

    def __init__(self, size: int, content_type: str, stream: AsyncGenerator[bytes]) -> None:
        """Hold one opened storage stream, and what stat said about the object behind it."""
        self.size = size
        self.content_type = content_type
        self.sent = 0
        self._stream = stream

    def headers_on(self, headers: dict[str, str]) -> dict[str, str]:
        """Add the content headers this body carries, leaving a named content type alone."""
        named = {name.lower() for name in headers}
        if "content-type" not in named:
            headers["content-type"] = self.content_type
        headers["content-length"] = str(self.size)
        return headers

    async def __aiter__(self) -> AsyncGenerator[bytes]:
        """Hand the client one chunk at a time, the size storage yields them in."""
        async for chunk in self._stream:
            self.sent += len(chunk)
            yield chunk

    async def aclose(self) -> None:
        """Release the storage stream, whether the request drained it or stopped part way."""
        await self._stream.aclose()


async def open_stored_body(config: HttpRequestConfig, ctx: StepContext) -> StoredBody | None:
    """Open the object ``body_from`` names, refusing a URI that holds nothing.

    A step whose file is not there is wrong rather than early: the run that was supposed to
    produce it did not, and retrying the call cannot make it appear.
    """
    if not config.body_from:
        return None
    found = await ctx.storage.stat(config.body_from)
    if found is None:
        raise BlockFailure(
            f"there is nothing at {config.body_from} to send as the request body",
            error_class=ErrorClass.REJECTED,
        )
    content_type = config.content_type or found.content_type
    if not content_type:
        raise BlockFailure(
            f"storage reports no content type for {config.body_from}, so this request needs content_type",
            error_class=ErrorClass.REJECTED,
        )
    return StoredBody(found.size, content_type, _read(ctx, config.body_from))


async def _read(ctx: StepContext, uri: str) -> AsyncGenerator[bytes]:
    """Yield the object's bytes, closing the storage stream when the reader stops."""
    async with aclosing(ctx.storage.open_read(uri)) as stream:
        async for chunk in stream:
            yield chunk


class HttpRequestOperator(Operator[HttpRequestConfig, HttpRequestOutput]):
    """Calls an HTTP service once and reports what it said."""

    spec = OperatorSpec(id="http.request", summary="Call an HTTP endpoint.", idempotent=False)
    config_model: ClassVar[type[BaseModel]] = HttpRequestConfig
    output_model: ClassVar[type[BaseModel]] = HttpRequestOutput

    async def execute(self, config: HttpRequestConfig, ctx: StepContext) -> HttpRequestOutput | RemoteHandle:
        """Send the request, and turn an unsuccessful status into a classified failure."""
        started = time.monotonic()
        sending = await open_stored_body(config, ctx)
        try:
            async with client_for(config, ctx) as client:
                headers, content, form, body = config.request_body()
                request = client.build_request(
                    config.method,
                    request_url(config),
                    params=dict(config.query) or None,
                    headers=sending.headers_on(headers) if sending is not None else (headers or None),
                    content=sending if sending is not None else content,
                    data=form,
                    json=body,
                    timeout=request_timeout(config, client),
                )
                response = await client.send(request, stream=True, follow_redirects=config.follow_redirects)
                try:
                    # An unsuccessful answer is never saved: writing it would replace whatever
                    # ``save_to`` already holds with an error body, and the step then fails.
                    succeeded = is_success(response.status_code, config.success_status)
                    written = await _save_body(config, response, ctx) if succeeded else None
                    payload = b"" if written is not None else await read_bounded(response, config.max_response)
                finally:
                    await response.aclose()
        finally:
            if sending is not None:
                await sending.aclose()
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "http call",
            method=config.method,
            url=request_url(config),
            status=response.status_code,
            bytes=written if written is not None else len(payload),
            sent_bytes=sending.sent if sending is not None else None,
            duration_ms=duration,
        )
        if not succeeded:
            raise BlockFailure(
                f"{config.method} {request_url(config)} answered {response.status_code}",
                error_class=status_class(response.status_code),
            )
        parsed, text = (None, None) if written is not None else decode(response, payload)
        return HttpRequestOutput(
            status=response.status_code,
            headers={name.lower(): value for name, value in response.headers.items()},
            json_body=parsed,
            text=text,
            duration_ms=duration,
            body_uri=config.save_to if written is not None else None,
            body_bytes=written,
            sent_bytes=sending.sent if sending is not None else None,
        )


class HttpReadyConfig(HttpTarget):
    """What readiness means for one service."""

    expect_status: list[int] = Field(default_factory=list[int])
    """Status codes that mean ready; empty means any 2xx."""

    contains: str | None = None
    """Optional body matcher; readiness also requires the response to contain this text."""

    max_response: Size = 1024 * 1024
    """How much of the answer is read while looking for ``contains``.

    A probe asks whether a service is up. An endpoint answering a readiness check with more
    than this is not answering the question, so the poke reads that much and stops rather
    than holding whatever arrives on a worker that pokes it every few seconds.
    """


class HttpReadyOutput(BlockModel):
    """The observation that a service is up, passed downstream like any output."""

    status: int
    duration_ms: int
    matched: bool


class HttpReadySensor(Sensor[HttpReadyConfig, HttpReadyOutput]):
    """Waits for an endpoint to answer successfully; each poke is one short, read-only GET."""

    spec = SensorSpec(id="http.ready", summary="Wait for an HTTP endpoint to report ready.")
    config_model: ClassVar[type[BaseModel]] = HttpReadyConfig
    output_model: ClassVar[type[BaseModel]] = HttpReadyOutput

    async def poke(self, config: HttpReadyConfig, ctx: StepContext) -> HttpReadyOutput | NotYet:
        """Observe once. A service that is not up yet is the condition, not an error."""
        started = time.monotonic()
        try:
            async with client_for(config, ctx) as client:
                request = client.build_request("GET", request_url(config), timeout=request_timeout(config, client))
                response = await client.send(request, stream=True, follow_redirects=config.follow_redirects)
                try:
                    answered = await read_bounded(response, config.max_response)
                finally:
                    await response.aclose()
        except httpx2.TransportError as error:
            ctx.log.debug("endpoint is not reachable yet", error=str(error))
            return NotYet()
        duration = round((time.monotonic() - started) * 1000)
        if not is_success(response.status_code, config.expect_status):
            ctx.log.debug("endpoint is not ready yet", status=response.status_code)
            return NotYet()
        if config.contains is not None and config.contains not in _as_text(answered):
            ctx.log.debug("endpoint answered but the body does not match yet")
            return NotYet()
        return HttpReadyOutput(status=response.status_code, duration_ms=duration, matched=config.contains is not None)


async def _save_body(config: HttpRequestConfig, response: httpx2.Response, ctx: StepContext) -> int | None:
    """Stream the response body to storage when the step asked for it, and say how much.

    Chunk by chunk, so a response larger than the worker's memory is a file rather than a
    dead worker. Nothing of it is kept: a body worth saving is one to read from storage, and
    holding it as well would be the thing this exists to avoid.
    """
    if not config.save_to:
        return None
    written = 0
    async with ctx.storage.open_write(config.save_to) as sink:
        async for chunk in response.aiter_bytes():
            written += await sink.write(chunk)
    ctx.log.info("response body saved", uri=config.save_to, bytes=written)
    return written


def status_class(status: int) -> ErrorClass:
    """Classify an HTTP status the way retry policy needs it classified."""
    if status >= 500:
        return ErrorClass.TRANSIENT
    if 400 <= status < 500:
        return ErrorClass.REJECTED
    return ErrorClass.UNKNOWN


def is_success(status: int, expected: list[int]) -> bool:
    """Decide whether a status counts as success: the declared set, or any 2xx."""
    return status in expected if expected else 200 <= status < 300
