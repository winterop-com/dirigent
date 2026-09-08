"""``POST /hooks/{token}``: the one unauthenticated write surface, and what it refuses.

Every delivery goes in through the ``anonymous`` client: the token in the path is the whole
credential, and a test that also carried a bearer token would prove nothing about the
surface a sender reaches.
"""

import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dirigent_core import telemetry
from dirigent_core.triggers.webhooks import SIGNATURE_HEADER, sign
from dirigent_server.routes.hooks import BUCKETS, INTAKE_BUCKETS, UNKNOWN_TOKEN
from tests_support import DOCUMENT, apply_document

PREFIX = "/api/v1"
WEBHOOKS = f"{PREFIX}/pipelines/api-demo/triggers/webhooks"

MAPPING = {"greeting": "$.message.text"}
PAYLOAD: dict[str, Any] = {"message": {"text": "hello from a sender"}}
SECRET = "a shared secret"


@pytest.fixture(autouse=True)
def _empty_buckets() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Empty the process-wide rate limiters around every test in this module.

    The buckets are module-level state that outlives a request and so outlives a test: a
    re-minted token can reuse a hash, and a leftover bucket would then refuse a delivery
    the test never made.
    """
    BUCKETS.buckets.clear()
    INTAKE_BUCKETS.buckets.clear()
    yield
    BUCKETS.buckets.clear()
    INTAKE_BUCKETS.buckets.clear()


def mint(client: TestClient, code: str = "from-github", **payload: Any) -> dict[str, Any]:
    """Declare a pipeline and one webhook on it, and return the token minted for it."""
    apply_document(client, DOCUMENT)
    body: dict[str, Any] = {"code": code, "params_from_payload": MAPPING, **payload}
    response = client.post(WEBHOOKS, json=body)
    assert response.status_code == 201, response.text
    minted: dict[str, Any] = response.json()
    return minted


def deliveries(client: TestClient, code: str = "from-github") -> list[dict[str, Any]]:
    """Read a webhook's delivery history."""
    response = client.get(f"{WEBHOOKS}/{code}/deliveries")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["items"]
    return rows


def test_a_minted_token_starts_a_run_attributed_to_the_webhook(client: TestClient, anonymous: TestClient) -> None:
    minted = mint(client)
    delivered = anonymous.post(minted["url_path"], json=PAYLOAD)
    assert delivered.status_code == 201, delivered.text
    assert delivered.json()["outcome"] == "accepted"
    run_id = delivered.json()["run_id"]
    assert run_id

    run = client.get(f"{PREFIX}/runs/{run_id}").json()["run"]
    assert run["pipeline"] == "api-demo"
    assert run["triggered_by_kind"] == "webhook"
    assert run["triggered_by_label"] == "webhook from-github"
    assert run["params"] == {"greeting": "hello from a sender"}


def test_the_intake_endpoint_takes_no_credential_while_the_versioned_api_still_does(
    client: TestClient, anonymous: TestClient
) -> None:
    minted = mint(client)
    assert anonymous.post(minted["url_path"], json=PAYLOAD).status_code == 201, (
        "a webhook sender authenticates as the trigger, with the token in the path"
    )
    for method, path in [("get", WEBHOOKS), ("get", f"{PREFIX}/runs"), ("get", f"{PREFIX}/pipelines")]:
        refused = anonymous.request(method, path)
        assert refused.status_code == 401, f"{method} {path} let an anonymous request through"
        assert "authentication required" in refused.json()["detail"]


def test_an_unknown_token_says_only_that_no_webhook_accepts_it(client: TestClient, anonymous: TestClient) -> None:
    mint(client)
    response = anonymous.post("/hooks/there-is-no-such-token", json=PAYLOAD)
    assert response.status_code == 404
    assert response.json() == {"run_id": None, "outcome": "rejected", "detail": UNKNOWN_TOKEN}
    assert "from-github" not in response.text, "the refusal names no webhook, so it cannot be probed for one"
    assert deliveries(client) == [], "a token that resolves to nothing has no history to write to"


def test_a_disabled_webhook_refuses_and_records_the_refusal(client: TestClient, anonymous: TestClient) -> None:
    minted = mint(client)
    assert client.post(f"{WEBHOOKS}/from-github/$disable").json()["active"] is False

    refused = anonymous.post(minted["url_path"], json=PAYLOAD)
    assert refused.json()["outcome"] == "rejected"
    assert refused.json()["run_id"] is None
    assert [row["reason"] for row in deliveries(client)] == ["this webhook is disabled"]

    # The caller is told exactly what a caller with an unknown token is told: otherwise the
    # holder of a revoked token learns that it once addressed a real webhook.
    unknown = anonymous.post("/hooks/there-is-no-such-token", json=PAYLOAD)
    assert (refused.status_code, refused.json()["detail"]) == (unknown.status_code, unknown.json()["detail"])
    assert refused.status_code == 404

    assert client.post(f"{WEBHOOKS}/from-github/$enable").json()["active"] is True
    assert anonymous.post(minted["url_path"], json=PAYLOAD).status_code == 201


def test_a_signed_webhook_accepts_a_signature_over_the_raw_body(client: TestClient, anonymous: TestClient) -> None:
    minted = mint(client, hmac_secret=SECRET)
    body = json.dumps(PAYLOAD).encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(SECRET.encode(), body)}
    delivered = anonymous.post(minted["url_path"], content=body, headers=headers)
    assert delivered.status_code == 201, delivered.text
    assert delivered.json()["run_id"]


def test_a_signed_webhook_accepts_the_prefixed_form_several_senders_write(
    client: TestClient, anonymous: TestClient
) -> None:
    minted = mint(client, hmac_secret=SECRET)
    body = json.dumps(PAYLOAD).encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: f"sha256={sign(SECRET.encode(), body)}"}
    assert anonymous.post(minted["url_path"], content=body, headers=headers).status_code == 201


def test_a_wrong_or_missing_signature_is_refused_and_recorded(client: TestClient, anonymous: TestClient) -> None:
    minted = mint(client, hmac_secret=SECRET)
    body = json.dumps(PAYLOAD).encode()

    missing = anonymous.post(minted["url_path"], content=body, headers={"Content-Type": "application/json"})
    assert missing.status_code == 401
    assert SIGNATURE_HEADER in missing.json()["detail"]

    wrong_secret = sign(b"not the shared secret", body)
    wrong = anonymous.post(
        minted["url_path"],
        content=body,
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: wrong_secret},
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "the signature does not match the body"

    other_body = anonymous.post(
        minted["url_path"],
        content=json.dumps({"message": {"text": "a different body"}}).encode(),
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: sign(SECRET.encode(), body)},
    )
    assert other_body.status_code == 401, "the signature covers the bytes that arrived, not the ones that were signed"

    assert [row["outcome"] for row in deliveries(client)] == ["rejected", "rejected", "rejected"]
    assert client.get(WEBHOOKS).json()["items"][0]["signed"] is True
    assert SECRET not in client.get(WEBHOOKS).text


def test_an_empty_hmac_secret_is_refused_at_declaration_rather_than_stored(client: TestClient) -> None:
    """An empty secret would seal into an envelope that reads as signed and verifies nothing."""
    apply_document(client, DOCUMENT)
    refused = client.post(WEBHOOKS, json={"code": "from-github", "params_from_payload": MAPPING, "hmac_secret": ""})

    assert refused.status_code == 422, refused.text
    assert client.get(WEBHOOKS).json()["items"] == [], "nothing was stored"


def test_a_webhook_reads_as_signed_only_when_a_secret_that_verifies_is_stored(
    client: TestClient, anonymous: TestClient
) -> None:
    mint(client, "unsigned")
    signed = mint(client, "signed", hmac_secret=SECRET)
    rows = {row["code"]: row["signed"] for row in client.get(WEBHOOKS).json()["items"]}

    assert rows == {"signed": True, "unsigned": False}

    body = json.dumps(PAYLOAD).encode()
    unsigned = anonymous.post(signed["url_path"], content=body, headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 401, "what reads as signed refuses an unsigned delivery"


def test_a_payload_missing_a_mapped_path_is_refused_and_the_evidence_commits(
    client: TestClient, anonymous: TestClient
) -> None:
    """The refusal is a returned value, not a raised exception, so the history row commits."""
    minted = mint(client)
    refused = anonymous.post(minted["url_path"], json={"message": {"body": "wrong key"}})
    assert 400 <= refused.status_code < 500
    assert refused.json()["run_id"] is None
    assert refused.json()["outcome"] == "rejected"
    assert "$.message.text" in refused.json()["detail"]

    history = deliveries(client)
    assert [row["outcome"] for row in history] == ["rejected"]
    assert "$.message.text" in history[0]["reason"]
    assert history[0]["run_id"] is None
    assert client.get(f"{PREFIX}/runs").json()["items"] == [], "a refused delivery starts nothing"


def test_a_mapped_payload_that_violates_the_parameter_schema_is_refused_and_recorded(
    client: TestClient, anonymous: TestClient
) -> None:
    minted = mint(client, params_from_payload={"greeting": "$.count"})
    refused = anonymous.post(minted["url_path"], json={"count": 7})
    assert refused.status_code == 422
    assert "does not satisfy the pipeline's parameters" in refused.json()["detail"]
    assert [row["outcome"] for row in deliveries(client)] == ["rejected"]
    assert deliveries(client)[0]["mapped_params"] is None


def test_a_body_that_is_not_a_json_object_is_refused(client: TestClient, anonymous: TestClient) -> None:
    minted = mint(client)
    not_json = anonymous.post(
        minted["url_path"], content=b"this is not json", headers={"Content-Type": "application/json"}
    )
    assert not_json.status_code == 400
    assert "the body is not JSON" in not_json.json()["detail"]

    an_array = anonymous.post(minted["url_path"], content=b"[1, 2, 3]", headers={"Content-Type": "application/json"})
    assert an_array.status_code == 400
    assert an_array.json()["detail"] == "a webhook payload is a JSON object, not list"

    history = deliveries(client)
    assert [row["outcome"] for row in history] == ["rejected", "rejected"]
    assert history[0]["reason"] == "a webhook payload is a JSON object, not list"
    assert history[1]["reason"].startswith("the body is not JSON:")


def test_a_token_delivering_faster_than_its_limit_is_told_to_come_back(
    client: TestClient, anonymous: TestClient
) -> None:
    minted = mint(client, rate_limit_per_minute=1)
    assert anonymous.post(minted["url_path"], json=PAYLOAD).status_code == 201

    limited = anonymous.post(minted["url_path"], json=PAYLOAD)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json()["outcome"] == "rejected"
    assert "1 deliveries a minute" in limited.json()["detail"]
    assert [row["outcome"] for row in deliveries(client)] == ["accepted"], (
        "the limit is applied before the body is read, so a hammered token costs no database write"
    )


def test_the_history_shows_what_arrived_and_what_it_mapped_to(client: TestClient, anonymous: TestClient) -> None:
    minted = mint(client)
    assert anonymous.post(minted["url_path"], json=PAYLOAD).status_code == 201
    assert anonymous.post(minted["url_path"], json={"message": {}}).status_code == 400

    history = deliveries(client)
    assert [row["outcome"] for row in history] == ["rejected", "accepted"], "newest first"
    assert history[0]["mapped_params"] is None
    assert history[0]["reason"]
    assert history[1]["mapped_params"] == {"greeting": "hello from a sender"}
    assert history[1]["run_id"]
    assert history[1]["reason"] is None
    assert client.get(WEBHOOKS).json()["items"][0]["last_delivery_at"] is not None
    assert len(client.get(f"{WEBHOOKS}/from-github/deliveries", params={"limit": 1}).json()["items"]) == 1


def test_what_webhook_post_signs_is_what_the_intake_verifies(client: TestClient, anonymous: TestClient) -> None:
    """``webhook.post``'s rendering and signature must verify at the intake endpoint."""
    from dirigent_blocks.webhooks import SIGNATURE_HEADER as OUTBOUND_HEADER
    from dirigent_blocks.webhooks import render
    from dirigent_blocks.webhooks import sign as sign_outbound

    minted = mint(client, hmac_secret=SECRET)
    payload = render(PAYLOAD)
    headers = {"Content-Type": "application/json", OUTBOUND_HEADER: sign_outbound(SECRET.encode(), payload)}

    delivered = anonymous.post(minted["url_path"], content=payload, headers=headers)

    assert OUTBOUND_HEADER == SIGNATURE_HEADER, "both ends name the same header"
    assert delivered.status_code == 201, delivered.text
    assert delivered.json()["run_id"]


class _RecordingSpan:
    """A span that records its name and attributes."""

    def __init__(self, name: str, attributes: dict[str, Any]) -> None:
        self.name = name
        self.attributes = dict(attributes)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def update_name(self, name: str) -> None:
        self.name = name

    def record_exception(self, *_: Any, **__: Any) -> None: ...

    def set_status(self, *_: Any, **__: Any) -> None: ...


class _RecordingTracer:
    """A tracer that keeps the spans it was asked to start."""

    def __init__(self) -> None:
        self.spans: list[_RecordingSpan] = []

    @contextmanager
    def start_as_current_span(
        self, name: str, *, kind: Any = None, attributes: dict[str, Any] | None = None
    ) -> Generator[_RecordingSpan]:
        span = _RecordingSpan(name, attributes or {})
        self.spans.append(span)
        yield span


def test_a_delivery_never_puts_its_token_in_a_span(
    client: TestClient, anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token is the whole credential, and a span name travels to every trace viewer."""
    tracer = _RecordingTracer()
    monkeypatch.setattr(telemetry, "_tracer", tracer)
    minted = mint(client)
    token = minted["url_path"].rsplit("/", 1)[-1]

    delivered = anonymous.post(minted["url_path"], json=PAYLOAD)

    assert delivered.status_code == 201, delivered.text
    assert tracer.spans, "the middleware recorded no span at all"
    recorded = json.dumps([{"name": span.name, "attributes": span.attributes} for span in tracer.spans])
    assert token not in recorded
    assert "POST /hooks/{token}" in [span.name for span in tracer.spans]


def test_an_unknown_token_is_rate_limited_the_same_way_a_disabled_one_is(
    client: TestClient, anonymous: TestClient
) -> None:
    """The 429 threshold must not tell a token holder that the token addresses a real webhook."""
    minted = mint(client)
    assert client.post(f"{WEBHOOKS}/{minted['code']}/$disable").status_code == 200
    unknown = "/hooks/" + "z" * 40

    disabled_codes = [anonymous.post(minted["url_path"], json=PAYLOAD).status_code for _ in range(4)]
    unknown_codes = [anonymous.post(unknown, json=PAYLOAD).status_code for _ in range(4)]

    assert disabled_codes == unknown_codes
    assert set(disabled_codes) == {404}


def test_a_token_nobody_minted_is_throttled_before_anything_is_looked_up(anonymous: TestClient) -> None:
    """The intake bucket is what makes an invalid-token spray cheap for the instance."""
    unknown = "/hooks/" + "q" * 40
    codes = {anonymous.post(unknown, json=PAYLOAD).status_code for _ in range(200)}
    assert 429 in codes


def test_a_body_larger_than_the_limit_is_refused_without_being_buffered(
    client: TestClient, anonymous: TestClient
) -> None:
    """An unauthenticated caller must not be able to make the process allocate what it sends."""
    minted = mint(client)
    oversized = json.dumps({"message": {"text": "x" * 2_000_000}}).encode()

    refused = anonymous.post(minted["url_path"], content=oversized, headers={"Content-Type": "application/json"})

    assert refused.status_code == 413
    assert "reads at most" in refused.json()["detail"]
    assert [row["outcome"] for row in deliveries(client)] == ["rejected"], (
        "an oversized delivery is still evidence, so the row is written"
    )
