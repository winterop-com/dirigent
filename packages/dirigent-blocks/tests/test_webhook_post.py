"""Tests for ``webhook.post``: the bytes it sends, the signature over them, and the answer."""

import hashlib
import hmac
import json
from collections.abc import AsyncGenerator

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks.connections import HttpConnectionConfig
from dirigent_blocks.webhooks import (
    JSON_CONTENT_TYPE,
    SIGNATURE_HEADER,
    WebhookPostConfig,
    WebhookPostOperator,
    WebhookPostOutput,
    render,
    sign,
)
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext

SECRET = "a shared secret"


class Responder:
    """Answers each request with the next scripted response, and remembers what it was sent."""

    def __init__(self, *responses: httpx2.Response) -> None:
        """Script the responses, the last of which repeats forever."""
        self.responses = responses
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Answer one request."""
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


def wired(ctx: FakeContext, *responses: httpx2.Response) -> Responder:
    """Point the context's client at a scripted receiver and hand the script back."""
    responder = Responder(*responses or (httpx2.Response(204),))
    ctx.handler = responder
    return responder


def with_secret(ctx: FakeContext, name: str = "peer", secret: str | None = SECRET) -> None:
    """Install a connection carrying (or deliberately lacking) a signing secret."""
    ctx.connections[name] = HttpConnectionConfig(
        base_url="http://service.test",
        hmac_secret=SecretStr(secret) if secret is not None else None,
    )


# -- the config ------------------------------------------------------------------


def test_a_post_needs_a_connection_or_an_absolute_url() -> None:
    with pytest.raises(ValidationError, match="either a connection or an absolute url"):
        WebhookPostConfig()
    assert WebhookPostConfig(url="https://example.test/hook").sign_with is None
    assert WebhookPostConfig(connection="peer").body == {}


# -- the bytes on the wire -------------------------------------------------------


def test_the_body_is_rendered_once_and_compactly() -> None:
    assert render({"a": 1, "b": [1, 2]}) == b'{"a":1,"b":[1,2]}'
    assert json.loads(render({"note": "å"})) == {"note": "å"}


async def test_the_body_sent_is_the_body_declared(ctx: FakeContext) -> None:
    responder = wired(ctx)
    config = WebhookPostConfig(connection="peer", path="/hooks/abc", body={"day": "2026-01-01"})

    await WebhookPostOperator().execute(config, ctx.as_context())

    request = responder.requests[0]
    assert request.method == "POST"
    assert request.content == b'{"day":"2026-01-01"}'
    assert request.headers["content-type"] == JSON_CONTENT_TYPE
    assert SIGNATURE_HEADER.lower() not in request.headers


async def test_declared_headers_travel_with_the_post(ctx: FakeContext) -> None:
    responder = wired(ctx)
    config = WebhookPostConfig(connection="peer", headers={"X-Route": "climate"})
    await WebhookPostOperator().execute(config, ctx.as_context())
    assert responder.requests[0].headers["x-route"] == "climate"


# -- signing ---------------------------------------------------------------------


async def test_a_signed_post_carries_an_hmac_over_the_bytes_it_sent(ctx: FakeContext) -> None:
    with_secret(ctx)
    responder = wired(ctx)
    config = WebhookPostConfig(connection="peer", sign_with="peer", body={"day": "2026-01-01"})

    output = await WebhookPostOperator().execute(config, ctx.as_context())

    assert isinstance(output, WebhookPostOutput)
    assert output.signed
    request = responder.requests[0]
    expected = hmac.new(SECRET.encode(), request.content, hashlib.sha256).hexdigest()
    assert request.headers[SIGNATURE_HEADER] == expected


async def test_the_signature_covers_the_bytes_sent_and_not_a_reserialisation(ctx: FakeContext) -> None:
    """A receiver hashing the bytes that arrived must get the same digest."""
    with_secret(ctx)
    responder = wired(ctx)
    config = WebhookPostConfig(connection="peer", sign_with="peer", body={"b": 2, "a": 1})

    await WebhookPostOperator().execute(config, ctx.as_context())

    request = responder.requests[0]
    presented = request.headers[SIGNATURE_HEADER]
    assert hmac.compare_digest(sign(SECRET.encode(), request.content), presented)
    reserialised = json.dumps(json.loads(request.content)).encode()
    assert reserialised != request.content, "the naive re-encoding differs, which is why it is not signed"


async def test_signing_may_name_a_connection_other_than_the_target(ctx: FakeContext) -> None:
    with_secret(ctx, "secrets")
    with_secret(ctx, "peer", secret=None)
    responder = wired(ctx)
    config = WebhookPostConfig(connection="peer", path="/hooks/abc", sign_with="secrets", body={"x": 1})

    await WebhookPostOperator().execute(config, ctx.as_context())

    request = responder.requests[0]
    assert request.headers[SIGNATURE_HEADER] == sign(SECRET.encode(), request.content)


async def test_a_connection_with_no_secret_is_refused_rather_than_sent_unsigned(ctx: FakeContext) -> None:
    with_secret(ctx, secret=None)
    responder = wired(ctx)

    with pytest.raises(BlockFailure) as failure:
        await WebhookPostOperator().execute(WebhookPostConfig(connection="peer", sign_with="peer"), ctx.as_context())

    assert failure.value.error_class is ErrorClass.REJECTED
    assert responder.requests == [], "nothing is sent when the signature cannot be computed"


# -- what the answer means -------------------------------------------------------


async def test_a_receiver_that_accepts_the_delivery_produces_its_answer(ctx: FakeContext) -> None:
    wired(ctx, httpx2.Response(201, json={"run_id": "01a0"}))

    output = await WebhookPostOperator().execute(WebhookPostConfig(connection="peer"), ctx.as_context())

    assert isinstance(output, WebhookPostOutput)
    assert output.status == 201
    assert output.json_body == {"run_id": "01a0"}
    assert output.text is None
    assert not output.signed
    assert output.duration_ms >= 0
    assert "webhook delivered" in ctx.log.messages()


async def test_a_non_json_answer_is_carried_as_text(ctx: FakeContext) -> None:
    wired(ctx, httpx2.Response(200, text="accepted"))
    output = await WebhookPostOperator().execute(WebhookPostConfig(connection="peer"), ctx.as_context())
    assert isinstance(output, WebhookPostOutput)
    assert output.text == "accepted"
    assert output.json_body is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [(500, ErrorClass.TRANSIENT), (401, ErrorClass.REJECTED), (422, ErrorClass.REJECTED)],
)
async def test_a_refused_delivery_fails_with_the_class_its_status_earns(
    ctx: FakeContext, status: int, expected: ErrorClass
) -> None:
    wired(ctx, httpx2.Response(status, json={"detail": "no"}))

    with pytest.raises(BlockFailure) as failure:
        await WebhookPostOperator().execute(WebhookPostConfig(connection="peer"), ctx.as_context())

    assert failure.value.error_class is expected
    assert str(failure.value).endswith(f"answered {status}")


async def test_a_receiver_with_an_unusual_success_code_is_declared_rather_than_guessed(ctx: FakeContext) -> None:
    wired(ctx, httpx2.Response(302))
    config = WebhookPostConfig(connection="peer", success_status=[302])
    output = await WebhookPostOperator().execute(config, ctx.as_context())
    assert isinstance(output, WebhookPostOutput)
    assert output.status == 302


def test_the_block_is_not_idempotent_and_runs_nothing_on_the_worker() -> None:
    spec = WebhookPostOperator().spec
    assert spec.id == "webhook.post"
    assert not spec.idempotent, "a delivery is a side effect, and re-sending one is a decision"
    assert not spec.local_execution


async def test_a_receiver_that_answers_with_more_than_an_acknowledgement_is_refused(ctx: FakeContext) -> None:
    """What a receiver says back is that it took the delivery, not the data itself."""
    chunks = [b"w" * 1024 for _ in range(4)]

    async def arriving() -> AsyncGenerator[bytes]:
        for chunk in chunks:
            yield chunk

    ctx.handler = Responder(httpx2.Response(200, content=arriving()))
    config = WebhookPostConfig(connection="api", path="/hook", body={"a": 1}, max_response=1024)

    with pytest.raises(BlockFailure) as raised:
        await WebhookPostOperator().execute(config, ctx.as_context())

    assert "max_response" in str(raised.value)


async def test_an_acknowledgement_inside_the_bound_is_still_read(ctx: FakeContext) -> None:
    """The delivery is what matters, and what the receiver said about it still comes back."""
    ctx.handler = Responder(httpx2.Response(200, json={"queued": True}))

    output = await WebhookPostOperator().execute(
        WebhookPostConfig(connection="api", path="/hook", body={"a": 1}), ctx.as_context()
    )

    assert isinstance(output, WebhookPostOutput)
    assert output.json_body == {"queued": True}
