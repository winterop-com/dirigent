"""The generic HTTP blocks: one operator that calls a service, one sensor that waits for one."""

import json
import time
from datetime import timedelta
from typing import ClassVar, Literal

import httpx2
from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_blocks.connections import HttpConnectionConfig
from dirigent_common import BlockModel, Duration, Size
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

DEFAULT_TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"

JSON_CONTENT_TYPE = "application/json"


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


def body_of(response: httpx2.Response, payload: bytes) -> JsonValue:
    """The one value an output carries: the parsed JSON when the answer is JSON, else the text."""
    parsed, text = decode(response, payload)
    return text if parsed is None else parsed


def _as_text(payload: bytes) -> str:
    """Render a body as the text an output carries."""
    return payload.decode("utf-8", errors="replace")


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
                f"the response is larger than max_response ({limit} bytes) and is not being read; "
                f"raise max_response, or ask the endpoint for less",
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
    """What the request sends, usually a reference to what an earlier step produced.

    A string is sent as it stands, which is what a query language, an XML document or a csv
    upload goes in; any other value is serialised and sent as JSON. A document held in
    storage is read by ``storage.read`` first and referenced here.
    """

    content_type: str | None = None
    """The content type the body is sent with, overriding the default for what it carries.

    A string defaults to ``text/plain; charset=utf-8`` and any other value to
    ``application/json``, so this is where an endpoint that wants ``text/csv`` or
    ``application/xml`` is told.
    """

    success_status: list[int] = Field(default_factory=list[int])
    """Status codes that count as success; empty means any 2xx."""

    max_response: Size = 32 * 1024 * 1024
    """How much of a response is read into memory.

    A body has to be whole to be parsed, so one too large to hold is refused rather than
    truncated: half a JSON document is not a smaller answer, it is a wrong one, and a step
    that acted on it would be acting on something the service never said.
    """

    def request_body(self) -> tuple[dict[str, str], bytes | None]:
        """The headers and the bytes one request is built with, the body serialised here.

        Serialised by the block rather than by the client, so the content type and the bytes
        are decided in one place.
        """
        if self.body is None:
            return dict(self.headers), None
        if isinstance(self.body, str):
            content, declared = self.body.encode(), DEFAULT_TEXT_CONTENT_TYPE
        else:
            content = json.dumps(self.body, separators=(",", ":"), ensure_ascii=False).encode()
            declared = JSON_CONTENT_TYPE
        # Rebuilt without the header so one spelling of it reaches the client, whichever
        # case the document wrote.
        headers = {name: value for name, value in self.headers.items() if name.lower() != "content-type"}
        named = next((value for name, value in self.headers.items() if name.lower() == "content-type"), None)
        headers["content-type"] = self.content_type or named or declared
        return headers, content


class HttpRequestOutput(BlockModel):
    """What one HTTP call observed, which downstream steps reference by field."""

    status: int
    headers: dict[str, str]
    body: JsonValue = None
    """What the service answered: the parsed document when it is JSON, else the text."""

    body_bytes: int
    """How many bytes the answer was."""

    duration_ms: int


class HttpRequestOperator(Operator[HttpRequestConfig, HttpRequestOutput]):
    """Calls an HTTP service once and reports what it said."""

    spec = OperatorSpec(id="http.request", summary="Call an HTTP endpoint.", idempotent=False)
    config_model: ClassVar[type[BaseModel]] = HttpRequestConfig
    output_model: ClassVar[type[BaseModel]] = HttpRequestOutput

    async def execute(self, config: HttpRequestConfig, ctx: StepContext) -> HttpRequestOutput | RemoteHandle:
        """Send the request, and turn an unsuccessful status into a classified failure."""
        started = time.monotonic()
        async with client_for(config, ctx) as client:
            headers, content = config.request_body()
            request = client.build_request(
                config.method,
                request_url(config),
                params=dict(config.query) or None,
                headers=headers or None,
                content=content,
                timeout=request_timeout(config, client),
            )
            response = await client.send(request, stream=True, follow_redirects=config.follow_redirects)
            try:
                payload = await read_bounded(response, config.max_response)
            finally:
                await response.aclose()
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "http call",
            method=config.method,
            url=request_url(config),
            status=response.status_code,
            bytes=len(payload),
            duration_ms=duration,
        )
        if not is_success(response.status_code, config.success_status):
            raise BlockFailure(
                f"{config.method} {request_url(config)} answered {response.status_code}",
                error_class=status_class(response.status_code),
            )
        return HttpRequestOutput(
            status=response.status_code,
            headers={name.lower(): value for name, value in response.headers.items()},
            body=body_of(response, payload),
            body_bytes=len(payload),
            duration_ms=duration,
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
