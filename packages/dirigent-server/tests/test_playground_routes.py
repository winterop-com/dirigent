"""The playground's routes: the envelope, the knobs, the credential, and the setting."""

import asyncio
import json
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.types import Message, Scope

from dirigent_core.config import Settings
from dirigent_server import create_app
from dirigent_server.routes import playground as routes

PREFIX = "/api/v1/playground"


@pytest.fixture
def playground(anonymous: TestClient) -> TestClient:
    """A client carrying no credential at all, which is how the playground is meant to be called."""
    return anonymous


def test_a_reflection_needs_no_credential(playground: TestClient) -> None:
    """The whole point: a step calling its own instance must not need a token."""
    body = playground.get(f"{PREFIX}/request").json()
    assert body["kind"] == "request"
    assert body["request"]["method"] == "GET"
    assert body["status"] == 200


def test_the_reflection_carries_the_query_verbatim(playground: TestClient) -> None:
    body = playground.get(f"{PREFIX}/request", params={"station": "bergen", "reading": "12.4"}).json()
    assert body["request"]["args"] == {"station": "bergen", "reading": "12.4"}
    assert body["request"]["url"].endswith("station=bergen&reading=12.4")
    assert body["request"]["path"] == f"{PREFIX}/request"


def test_a_repeated_argument_arrives_as_a_list(playground: TestClient) -> None:
    body = playground.get(f"{PREFIX}/request?tag=a&tag=b").json()
    assert body["request"]["args"]["tag"] == ["a", "b"]


def test_a_json_body_appears_once_as_json(playground: TestClient) -> None:
    """A body is decoded once and reported once, never under two names."""
    body = playground.post(f"{PREFIX}/request", json={"a": 1, "b": [2, 3]}).json()
    assert body["request"]["body"] == {"a": 1, "b": [2, 3]}
    assert body["request"]["body_kind"] == "json"
    assert body["request"]["body_bytes"] > 0
    assert body["request"]["content_type"].startswith("application/json")


def test_a_form_body_appears_once_as_form(playground: TestClient) -> None:
    body = playground.post(f"{PREFIX}/request", data={"a": "b", "c": "d"}).json()
    assert body["request"]["body"] == {"a": "b", "c": "d"}
    assert body["request"]["body_kind"] == "form"


def test_a_body_that_is_neither_is_text(playground: TestClient) -> None:
    body = playground.put(f"{PREFIX}/request", content=b"plain words", headers={"content-type": "text/plain"}).json()
    assert body["request"]["body"] == "plain words"
    assert body["request"]["body_kind"] == "text"


def test_no_body_says_so(playground: TestClient) -> None:
    body = playground.delete(f"{PREFIX}/request").json()
    assert body["request"]["body"] is None
    assert body["request"]["body_kind"] == "none"
    assert body["request"]["body_bytes"] == 0


def test_a_credential_is_reflected_as_present_and_never_as_its_value(playground: TestClient) -> None:
    """An origin that reflected a session cookie would hand it to any script on that origin."""
    response = playground.get(f"{PREFIX}/request", headers={"Authorization": "Bearer a-real-secret"})
    headers = response.json()["request"]["headers"]
    assert headers["authorization"] == "<redacted>"
    assert "a-real-secret" not in response.text


def test_a_chosen_status_is_answered_and_reflected(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/request", params={"status": 503})
    assert response.status_code == 503
    assert response.json()["status"] == 503
    assert response.json()["request"]["args"]["status"] == "503"


def test_a_status_that_carries_no_body_carries_none(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/request", params={"status": 204})
    assert response.status_code == 204
    assert response.content == b""


def test_a_delay_is_taken_before_the_answer(playground: TestClient) -> None:
    """Short enough that the test does not sleep, long enough that the knob is exercised."""
    response = playground.get(f"{PREFIX}/request", params={"delay": "50ms"})
    assert response.status_code == 200


def test_a_delay_longer_than_the_playground_allows_is_refused(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/request", params={"delay": "10m"})
    assert response.status_code == 422


def test_a_redirect_points_at_the_reflection_route(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == f"{PREFIX}/request"
    assert response.json()["kind"] == "redirect"
    assert response.json()["hops"] == 0


def test_a_redirect_chain_walks_itself_down(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", params={"hops": 3}, follow_redirects=False)
    assert response.json()["hops"] == 2
    assert "hops=2" in response.headers["location"]
    landed = playground.get(f"{PREFIX}/redirect", params={"hops": 3})
    assert landed.json()["kind"] == "request"


def test_a_redirect_chooses_its_status(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", params={"status": 308}, follow_redirects=False)
    assert response.status_code == 308


def test_a_status_that_is_not_a_redirect_is_refused(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/redirect", params={"status": 200}).status_code == 422


def test_the_playground_will_not_redirect_off_this_instance(playground: TestClient) -> None:
    """An open redirect is a phishing tool wearing the instance's own domain."""
    for target in ("https://example.com", "//example.com"):
        response = playground.get(f"{PREFIX}/redirect", params={"to": target}, follow_redirects=False)
        assert response.status_code == 422, target


@pytest.mark.parametrize(
    "target",
    [
        "/\\example.com",
        "\\\\example.com",
        "\\/example.com",
        "///example.com",
        "/\t/example.com",
        "/\n/example.com",
        " //example.com",
        "http:example.com",
        "https:/example.com",
        "javascript:alert(1)",
        "http://[bad",
        "path-without-a-slash",
    ],
)
def test_a_redirect_target_a_browser_reads_as_another_origin_is_refused(playground: TestClient, target: str) -> None:
    response = playground.get(f"{PREFIX}/redirect", params={"to": target}, follow_redirects=False)
    assert response.status_code == 422
    assert "location" not in response.headers


def test_a_redirect_target_is_sent_as_it_was_judged(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", params={"to": "/api\\v1?x=1"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/api/v1?x=1"


def test_an_unreliable_call_fails_until_the_attempt_it_names(playground: TestClient) -> None:
    failing = playground.get(f"{PREFIX}/unreliable", params={"attempt": 1, "fail_until": 2})
    assert failing.status_code == 503
    assert failing.json()["outcome"] == "failed"
    succeeding = playground.get(f"{PREFIX}/unreliable", params={"attempt": 3, "fail_until": 2})
    assert succeeding.status_code == 200
    assert succeeding.json()["outcome"] == "succeeded"
    assert succeeding.json()["attempt"] == 3


def test_an_unreliable_call_chooses_the_status_it_fails_with(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/unreliable", params={"attempt": 1, "fail_until": 1, "status": 429})
    assert response.status_code == 429


def test_response_headers_are_set_from_the_query(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/response-headers", params={"X-Station": "bergen", "X-Run": "7"})
    assert response.headers["x-station"] == "bergen"
    assert response.json()["headers"] == {"X-Station": "bergen", "X-Run": "7"}


def test_a_header_this_origin_will_not_set_is_refused(playground: TestClient) -> None:
    """Planting a cookie on this origin from a query string is not a thing to teach."""
    response = playground.get(f"{PREFIX}/response-headers", params={"Set-Cookie": "a=b"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "header",
    [
        "WWW-Authenticate",
        "Refresh",
        "Clear-Site-Data",
        "Content-Disposition",
        "Link",
        "X-Content-Type-Options",
        "Access-Control-Allow-Origin",
        "Cross-Origin-Resource-Policy",
        "X-Accel-Redirect",
        "bad name",
    ],
)
def test_a_header_that_makes_this_origin_act_is_refused(playground: TestClient, header: str) -> None:
    response = playground.get(f"{PREFIX}/response-headers", params={header: "x"})
    assert response.status_code == 422
    assert response.headers.get(header.lower()) != "x"


def test_a_header_value_cannot_start_another_header(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/response-headers", params={"X-Station": "a\r\nSet-Cookie: b=c"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "content_type",
    ["text/html", "TEXT/HTML; charset=utf-8", "image/svg+xml", "application/xhtml+xml", "text/plain, text/html"],
)
def test_a_content_type_a_browser_runs_is_refused(playground: TestClient, content_type: str) -> None:
    """The envelope reflects the query, so an HTML answer would run what a link put in it."""
    response = playground.get(f"{PREFIX}/response-headers", params={"content-type": content_type})
    assert response.status_code == 422
    assert "<script>" not in response.text


@pytest.mark.parametrize("content_type", ["text/csv", "application/json", "text/plain; charset=utf-8"])
def test_an_inert_content_type_is_set_as_asked(playground: TestClient, content_type: str) -> None:
    response = playground.get(f"{PREFIX}/response-headers", params={"content-type": content_type})
    assert response.status_code == 200
    assert response.headers["content-type"] == content_type


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com/",
        "//example.com",
        "/\\example.com",
        "http://testserver@example.com/",
        "http://testserver:81/",
    ],
)
def test_a_location_on_another_origin_is_refused(playground: TestClient, location: str) -> None:
    response = playground.get(
        f"{PREFIX}/response-headers", params={"location": location, "status": 302}, follow_redirects=False
    )
    assert response.status_code == 422
    assert "location" not in response.headers


@pytest.mark.parametrize("location", ["/api/v1/playground/request", "http://testserver/api", "http://testserver:80/x"])
def test_a_location_on_this_origin_is_set(playground: TestClient, location: str) -> None:
    response = playground.get(
        f"{PREFIX}/response-headers", params={"location": location, "status": 302}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == location


@pytest.mark.parametrize(
    ("route", "params"),
    [
        ("/request", {}),
        ("/request", {"status": 204}),
        ("/redirect", {}),
        ("/unreliable", {"fail_until": 0}),
        ("/response-headers", {"X-Station": "bergen"}),
        ("/stream", {"messages": 1, "every": "0ms"}),
    ],
)
def test_every_answer_is_contained(playground: TestClient, route: str, params: dict[str, Any]) -> None:
    response = playground.get(f"{PREFIX}{route}", params=params, follow_redirects=False)
    assert response.status_code < 400
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("sandbox;")


def test_a_body_past_the_cap_is_refused_before_the_route_without_a_credential(playground: TestClient) -> None:
    response = playground.post(f"{PREFIX}/request", content=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["code"] == "server.unauthenticated_body_too_large"


def test_a_body_past_the_cap_is_refused_by_the_route_with_a_credential(client: TestClient) -> None:
    response = client.post(f"{PREFIX}/request", content=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["code"] == "server.playground_body_too_large"


def test_a_body_at_the_cap_is_reflected(playground: TestClient) -> None:
    response = playground.post(f"{PREFIX}/request", content=b"x" * (1024 * 1024))
    assert response.status_code == 200
    assert response.json()["request"]["body_bytes"] == 1024 * 1024


def test_auth_refuses_a_call_with_no_credential(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/auth")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="playground"'


def test_auth_accepts_the_documented_basic_pair(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/auth", auth=("playground", "playground"))
    assert response.status_code == 200
    assert response.json()["scheme"] == "basic"
    assert response.json()["authenticated"] is True


def test_auth_accepts_the_documented_bearer_token(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/auth", headers={"Authorization": "Bearer playground-token"})
    assert response.json()["scheme"] == "bearer"


def test_auth_refuses_a_credential_that_is_not_the_documented_one(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/auth", auth=("playground", "wrong")).status_code == 401
    assert playground.get(f"{PREFIX}/auth", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_every_route_answers_the_same_envelope(playground: TestClient) -> None:
    """One shape to learn: a kind, what arrived, and the route's own answer beside it."""
    for path, params in [
        ("/request", {}),
        ("/unreliable", {"attempt": 9, "fail_until": 0}),
        ("/response-headers", {}),
    ]:
        body = playground.get(f"{PREFIX}{path}", params=params).json()
        assert body["kind"], path
        assert body["request"]["method"] == "GET", path
        assert body["request"]["path"] == f"{PREFIX}{path}", path


def test_the_openapi_document_names_the_playground(client: TestClient) -> None:
    """Honest in the document rather than hidden, so a reader finds it where everything else is."""
    document = client.get("/openapi.json").json()
    paths = [path for path in document["paths"] if path.startswith(PREFIX)]
    assert f"{PREFIX}/request" in paths
    assert f"{PREFIX}/redirect" in paths
    operations = [
        operation
        for path, methods in document["paths"].items()
        if path.startswith(PREFIX)
        for operation in methods.values()
    ]
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids)), "an operation id is used twice"
    assert all(operation.get("summary") for operation in operations)


def test_the_setting_unmounts_the_playground() -> None:
    """Off means the routes are not there, not that they are there and refuse."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        playground_enabled=False,
    )
    with TestClient(create_app(settings, scheduler=False)) as client:
        assert client.get(f"{PREFIX}/request").status_code == 404
        assert f"{PREFIX}/request" not in client.get("/openapi.json").json()["paths"]


def lines(playground: TestClient, **params: str | int) -> list[dict[str, Any]]:
    """Read a stream to its end, as a consumer that parses one JSON record per line does."""
    with playground.stream("GET", f"{PREFIX}/stream", params=params) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in response.iter_lines() if line]


def test_a_stream_opens_with_the_envelope_and_closes_with_an_end(playground: TestClient) -> None:
    """A stream has one set of headers, so the request facts go out once, on the first line."""
    read = lines(playground, messages=3, every="0s")
    assert [record["kind"] for record in read] == [
        "stream",
        "stream.message",
        "stream.message",
        "stream.message",
        "stream.closed",
    ]
    assert read[0]["request"]["path"] == f"{PREFIX}/stream"
    assert read[0]["request"]["args"] == {"messages": "3", "every": "0s"}
    assert read[0]["messages"] == 3


def test_only_the_first_line_carries_the_request(playground: TestClient) -> None:
    read = lines(playground, messages=2, every="0s")
    assert all("request" not in record for record in read[1:])


def test_the_messages_are_offset_in_order_and_the_end_counts_them(playground: TestClient) -> None:
    read = lines(playground, messages=4, every="0s")
    assert [record["offset"] for record in read[1:-1]] == [0, 1, 2, 3]
    assert read[-1]["messages"] == 4
    assert read[-1]["duration_ms"] >= 0


def test_a_gap_puts_the_messages_apart_in_time(playground: TestClient) -> None:
    read = lines(playground, messages=2, every="60ms")
    elapsed = [record["elapsed_ms"] for record in read[1:-1]]
    assert elapsed[0] >= 55
    assert elapsed[1] >= elapsed[0] + 55
    assert read[-1]["duration_ms"] >= elapsed[-1]


def test_a_payload_rides_on_every_message_at_the_size_it_was_asked_for(playground: TestClient) -> None:
    read = lines(playground, messages=2, every="0s", payload="2kb")
    assert read[0]["payload_bytes"] == 2048
    assert all(len(record["payload"]) == 2048 for record in read[1:-1])


def test_no_payload_means_no_filler(playground: TestClient) -> None:
    read = lines(playground, messages=1, every="0s")
    assert read[0]["payload_bytes"] is None
    assert read[1]["payload"] is None


def test_the_default_stream_needs_no_knobs_at_all(playground: TestClient) -> None:
    with playground.stream("GET", f"{PREFIX}/stream", params={"every": "0s"}) as response:
        read = [json.loads(line) for line in response.iter_lines() if line]
    assert read[0]["messages"] == 5
    assert len([record for record in read if record["kind"] == "stream.message"]) == 5


def test_a_stream_that_would_hold_the_connection_too_long_is_refused(playground: TestClient) -> None:
    """The gap and the count multiply, so each being inside its own bound is not enough."""
    response = playground.get(f"{PREFIX}/stream", params={"messages": 100, "every": "10s"})
    assert response.status_code == 422
    assert "60s" in response.json()["detail"]


def test_a_gap_longer_than_the_playground_allows_is_refused(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/stream", params={"messages": 1, "every": "30s"}).status_code == 422


def test_more_messages_than_the_playground_sends_are_refused(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/stream", params={"messages": 5000, "every": "0s"}).status_code == 422


def test_a_payload_larger_than_the_playground_fills_is_refused(playground: TestClient) -> None:
    assert (
        playground.get(f"{PREFIX}/stream", params={"messages": 1, "every": "0s", "payload": "8mb"}).status_code == 422
    )


def _stream_scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"{PREFIX}/stream",
        "raw_path": f"{PREFIX}/stream".encode(),
        "root_path": "",
        "query_string": b"messages=100&every=0s&payload=1mb",
        "headers": [(b"host", b"testserver")],
        "client": ("203.0.113.9", 4000),
        "server": ("testserver", 80),
    }


class _NotReading:
    """A client that takes the response head and one write, and then never reads again."""

    def __init__(self) -> None:
        """Start having read nothing."""
        self.statuses: list[int] = []
        self.written: list[int] = []
        self.blocked = asyncio.Event()

    async def receive(self) -> Message:
        """Send an empty body, then stay connected."""
        if not self.blocked.is_set():
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        """Take the head and one write, and block on anything after them."""
        if message["type"] == "http.response.start":
            self.statuses.append(int(message["status"]))
            return
        self.written.append(len(message.get("body", b"")))
        self.blocked.set()
        await asyncio.Event().wait()


async def test_a_stream_a_client_stopped_reading_ends_at_its_deadline(
    settings: Settings, admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "STREAM_DEADLINE", timedelta(milliseconds=200), raising=False)
    client = _NotReading()
    await asyncio.wait_for(create_app(settings)(_stream_scope(), client.receive, client.send), timeout=5)
    assert client.statuses == [200]
    assert client.written, "the stream got as far as a write it could not finish"


async def test_a_stream_hands_the_server_no_write_past_the_bound(playground_stream_lines: list[int]) -> None:
    assert max(playground_stream_lines) <= 64 * 1024, "a client that stops reading holds at most this much of a write"


@pytest.fixture
async def playground_stream_lines(settings: Settings, admin_token: str) -> list[int]:
    written: list[int] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            written.append(len(message.get("body", b"")))

    scope = {**_stream_scope(), "query_string": b"messages=2&every=0s&payload=1mb"}
    await asyncio.wait_for(create_app(settings)(scope, receive, send), timeout=30)
    assert sum(written) > 2 * 1024 * 1024
    return written


async def test_one_process_holds_only_so_many_streams_and_frees_a_seat_at_the_deadline(
    settings: Settings, admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_STREAMS", 1, raising=False)
    monkeypatch.setattr(routes, "STREAM_DEADLINE", timedelta(milliseconds=300), raising=False)
    app = create_app(settings)
    first = _NotReading()
    held = asyncio.create_task(app(_stream_scope(), first.receive, first.send))
    await asyncio.wait_for(first.blocked.wait(), timeout=5)

    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url="http://testserver") as client:
        refused = await client.get(f"{PREFIX}/stream", params={"messages": 1, "every": "0s"})
        assert refused.status_code == 503, refused.text
        assert refused.json()["code"] == "server.playground_streams_full"
        assert refused.headers["retry-after"] == "10"
        await asyncio.wait_for(held, timeout=5)
        answered = await client.get(f"{PREFIX}/stream", params={"messages": 1, "every": "0s"})
        assert answered.status_code == 200, answered.text


def test_a_stream_needs_no_credential_either(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/stream", params={"messages": 1, "every": "0s"}).status_code == 200


def test_the_stream_is_in_the_openapi_document_as_ndjson(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][f"{PREFIX}/stream"]["get"]
    assert "application/x-ndjson" in operation["responses"]["200"]["content"]
