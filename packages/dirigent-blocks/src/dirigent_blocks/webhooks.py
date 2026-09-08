"""``webhook.post``: an outbound, optionally HMAC-signed JSON POST.

The ``X-Dirigent-Signature`` it presents is computed the same way dirigent's own inbound
``/hooks/{token}`` verifies one, so the two must stay in step.

The block serialises the body itself, and the signature covers the bytes that go on the
wire: letting the HTTP client re-encode the body after signing would produce a signature
that verifies nowhere.
"""

import hashlib
import hmac
import json
import time
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from dirigent_blocks.connections import HttpConnectionConfig
from dirigent_blocks.http import (
    HttpTarget,
    client_for,
    decode,
    is_success,
    read_bounded,
    request_url,
    status_class,
)
from dirigent_common import BlockModel, Size
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, Operator, OperatorSpec, RemoteHandle, StepContext

SIGNATURE_HEADER: Final = "X-Dirigent-Signature"

JSON_CONTENT_TYPE: Final = "application/json"

JSON_SEPARATORS: Final = (",", ":")


class WebhookPostConfig(HttpTarget):
    """What to POST, where, and what to sign it with."""

    model_config = ConfigDict(populate_by_name=True)

    body: JsonValue = Field(default_factory=dict[str, JsonValue])
    """The JSON payload, usually built from upstream outputs with ``${steps...}`` references."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    """Extra headers the receiver wants, such as a routing key."""

    max_response: Size = 1024 * 1024
    """How much of the receiver's answer is read, before the step is failed instead.

    An acknowledgement is small: what a receiver says back is that it took the delivery, not
    the data itself. A megabyte is generous for that, and a receiver answering with more than
    a step said it would hold is a receiver to find out about rather than to read.
    """

    sign_with: ConnectionRef | None = None
    """The connection whose ``hmac_secret`` signs the body; unset means the POST is unsigned.

    Named separately from ``connection`` so a POST to an absolute URL can still be signed
    with a secret this instance holds, and so signing is something a document says out loud
    rather than something that happens because a connection had a field set."""

    success_status: list[int] = Field(default_factory=list[int])
    """Status codes that count as delivered; empty means any 2xx."""


class WebhookPostOutput(BlockModel):
    """What the receiver said, which downstream steps reference by field."""

    status: int
    signed: bool
    duration_ms: int
    json_body: JsonValue | None = None
    text: str | None = None


class WebhookPostOperator(Operator[WebhookPostConfig, WebhookPostOutput]):
    """POSTs a JSON body to a connection or a URL, optionally signed the way dirigent signs."""

    spec = OperatorSpec(id="webhook.post", summary="POST a JSON body, optionally HMAC-signed.", idempotent=False)
    config_model: ClassVar[type[BaseModel]] = WebhookPostConfig
    output_model: ClassVar[type[BaseModel]] = WebhookPostOutput

    async def execute(self, config: WebhookPostConfig, ctx: StepContext) -> WebhookPostOutput | RemoteHandle:
        """Render the body once, sign those bytes, send them, and read the answer."""
        payload = render(config.body)
        headers = {**config.headers, "Content-Type": JSON_CONTENT_TYPE}
        secret = _secret(config, ctx)
        if secret is not None:
            headers[SIGNATURE_HEADER] = sign(secret, payload)
        started = time.monotonic()
        async with client_for(config, ctx) as client:
            request = client.build_request(
                "POST",
                request_url(config),
                content=payload,
                headers=headers,
                timeout=config.timeout.total_seconds() if config.timeout is not None else None,
            )
            response = await client.send(request, stream=True, follow_redirects=config.follow_redirects)
            try:
                answered = await read_bounded(response, config.max_response)
            finally:
                await response.aclose()
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "webhook delivered",
            status=response.status_code,
            bytes_sent=len(payload),
            signed=secret is not None,
            duration_ms=duration,
        )
        if not is_success(response.status_code, config.success_status):
            raise BlockFailure(
                f"the receiver at {request_url(config)} answered {response.status_code}",
                error_class=status_class(response.status_code),
            )
        parsed, text = decode(response, answered)
        return WebhookPostOutput(
            status=response.status_code,
            signed=secret is not None,
            duration_ms=duration,
            json_body=parsed,
            text=text,
        )


def render(body: JsonValue) -> bytes:
    """Serialise the body once, into the exact bytes that are both signed and sent."""
    return json.dumps(body, separators=JSON_SEPARATORS, ensure_ascii=False).encode()


def sign(secret: bytes, payload: bytes) -> str:
    """Compute the signature over the raw body, the way dirigent's own intake verifies one."""
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _secret(config: WebhookPostConfig, ctx: StepContext) -> bytes | None:
    """Read the signing secret off the named connection, refusing one that has none."""
    if config.sign_with is None:
        return None
    connection = ctx.connection(config.sign_with, HttpConnectionConfig)
    if connection.hmac_secret is None:
        raise BlockFailure(
            f"connection {config.sign_with!r} has no hmac_secret, so this POST cannot be signed",
            error_class=ErrorClass.REJECTED,
        )
    return connection.hmac_secret.get_secret_value().encode()
