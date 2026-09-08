"""Tests for the generic HTTP blocks, against httpx2's own mock transport."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks.connections import HttpConnectionConfig, HttpConnectionKind, build_client
from dirigent_blocks.http import (
    HttpReadyConfig,
    HttpReadyOutput,
    HttpReadySensor,
    HttpRequestConfig,
    HttpRequestOperator,
    HttpRequestOutput,
    status_class,
)
from dirigent_plugin import BlockFailure, ErrorClass, NotYet, StatResult
from dirigent_testing import FakeContext, FakeStorage


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


def json_response(status: int, payload: Any) -> httpx2.Response:
    """Build a JSON response the block will parse."""
    return httpx2.Response(status, json=payload)


# -- http.request ----------------------------------------------------------------


async def test_a_successful_call_reports_what_the_service_said(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(json_response(200, {"id": "abc"}))
    config = HttpRequestConfig(connection="api", method="POST", path="/v1/ingest", body={"day": "2026-08-28"})
    output = await HttpRequestOperator().execute(config, ctx.as_context())
    assert isinstance(output, HttpRequestOutput)
    assert output.status == 200
    assert output.json_body == {"id": "abc"}
    assert output.text is None
    assert output.duration_ms >= 0
    assert "http call" in ctx.log.messages()

    request = handler.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://service.test/v1/ingest"


async def test_a_text_body_is_sent_verbatim_as_plain_text(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(json_response(200, {"elements": []}))
    query = "[out:json];node[amenity=hospital](59.9,10.7,60.0,10.8);out;"
    config = HttpRequestConfig(connection="api", method="POST", path="/interpreter", text=query)
    output = await HttpRequestOperator().execute(config, ctx.as_context())
    assert isinstance(output, HttpRequestOutput)

    request = handler.requests[0]
    assert request.content == query.encode("utf-8")
    assert request.headers["content-type"] == "text/plain; charset=utf-8"


async def test_a_named_content_type_wins_over_the_text_default(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(
        connection="api",
        method="POST",
        path="/graphql",
        text="{ me { id } }",
        headers={"Content-Type": "application/graphql"},
    )
    await HttpRequestOperator().execute(config, ctx.as_context())
    assert handler.requests[0].headers["content-type"] == "application/graphql"


async def test_a_form_body_is_url_encoded(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(
        connection="api", method="POST", path="/token", form={"grant_type": "client_credentials"}
    )
    await HttpRequestOperator().execute(config, ctx.as_context())

    request = handler.requests[0]
    assert request.content == b"grant_type=client_credentials"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"


def test_a_request_carrying_two_bodies_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        HttpRequestConfig(connection="api", method="POST", body={"a": 1}, text="a=1")
    assert "one body" in str(raised.value)


def test_a_stored_body_beside_an_inline_one_is_refused() -> None:
    """body_from is a body like the other three, so the same rule counts it."""
    with pytest.raises(ValidationError) as raised:
        HttpRequestConfig(connection="api", method="POST", text="a=1", body_from="file://payload.bin")
    assert "one body" in str(raised.value)
    assert "body_from" in str(raised.value)


async def test_a_redirect_is_the_answer_unless_the_step_asked_to_follow_it(ctx: FakeContext) -> None:
    """A 3xx is a status like any other: it fails the success rule rather than being chased."""
    ctx.handler = Responder(httpx2.Response(302, headers={"location": "http://service.test/moved"}))
    config = HttpRequestConfig(connection="api", path="/start")
    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(config, ctx.as_context())
    assert "302" in str(raised.value)


async def test_following_a_redirect_lands_on_what_it_pointed_at(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(
        httpx2.Response(302, headers={"location": "http://service.test/moved"}),
        json_response(200, {"id": "abc"}),
    )
    config = HttpRequestConfig(connection="api", path="/start", follow_redirects=True)
    output = await HttpRequestOperator().execute(config, ctx.as_context())
    assert isinstance(output, HttpRequestOutput)
    assert output.status == 200
    assert [str(request.url) for request in handler.requests] == [
        "http://service.test/start",
        "http://service.test/moved",
    ]


async def test_a_redirect_to_another_host_does_not_carry_the_credentials(ctx: FakeContext) -> None:
    """Following one is not a way to hand a service's password to a different service."""
    ctx.handler = handler = Responder(
        httpx2.Response(302, headers={"location": "http://elsewhere.test/moved"}),
        json_response(200, {"id": "abc"}),
    )
    config = HttpRequestConfig(
        connection="api", path="/start", follow_redirects=True, headers={"Authorization": "Basic c2VjcmV0"}
    )
    await HttpRequestOperator().execute(config, ctx.as_context())
    first, second = handler.requests
    assert first.headers["authorization"] == "Basic c2VjcmV0"
    assert "authorization" not in second.headers, "the credential stayed with the host it was for"
    assert str(second.url) == "http://elsewhere.test/moved"


async def test_query_and_headers_reach_the_service(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(httpx2.Response(200, text="ok"))
    config = HttpRequestConfig(connection="api", path="/search", query={"q": "x", "n": 2}, headers={"X-Trace": "t"})
    await HttpRequestOperator().execute(config, ctx.as_context())
    request = handler.requests[0]
    assert request.url.params["q"] == "x"
    assert request.url.params["n"] == "2"
    assert request.headers["x-trace"] == "t"


async def test_a_non_json_body_is_reported_as_text(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(200, text="plain words"))
    output = await HttpRequestOperator().execute(HttpRequestConfig(connection="api"), ctx.as_context())
    assert isinstance(output, HttpRequestOutput)
    assert output.text == "plain words"
    assert output.json_body is None


async def test_a_malformed_json_body_falls_back_to_text(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(200, content=b"{not json", headers={"content-type": "application/json"}))
    output = await HttpRequestOperator().execute(HttpRequestConfig(connection="api"), ctx.as_context())
    assert isinstance(output, HttpRequestOutput)
    assert output.text == "{not json"


async def test_a_server_error_is_transient(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(503, text="down"))
    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(HttpRequestConfig(connection="api"), ctx.as_context())
    assert raised.value.error_class is ErrorClass.TRANSIENT
    assert "503" in str(raised.value)


async def test_a_client_error_is_rejected(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(422, text="no"))
    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(HttpRequestConfig(connection="api"), ctx.as_context())
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_declared_success_set_overrides_the_2xx_default(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(409, text="already there"))
    config = HttpRequestConfig(connection="api", success_status=[200, 409])
    output = await HttpRequestOperator().execute(config, ctx.as_context())
    assert isinstance(output, HttpRequestOutput)
    assert output.status == 409

    strict = HttpRequestConfig(connection="api", success_status=[200])
    with pytest.raises(BlockFailure):
        await HttpRequestOperator().execute(strict, ctx.as_context())


async def test_a_transport_failure_classifies_as_transient(ctx: FakeContext) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    ctx.handler = fail
    operator = HttpRequestOperator()
    with pytest.raises(httpx2.ConnectError) as raised:
        await operator.execute(HttpRequestConfig(connection="api"), ctx.as_context())
    assert operator.classify_error(raised.value) is ErrorClass.TRANSIENT


def test_a_config_naming_neither_a_connection_nor_a_url_is_refused() -> None:
    with pytest.raises(ValidationError, match="either a connection or an absolute url"):
        HttpRequestConfig()


async def test_a_call_without_an_override_inherits_the_connections_timeout(ctx: FakeContext) -> None:
    """An unset override must not become "no timeout": an unanswered call would hold a worker."""
    ctx.handler = handler = Responder(json_response(200, {}))
    await HttpRequestOperator().execute(HttpRequestConfig(connection="api", path="/x"), ctx.as_context())
    assert handler.requests[0].extensions["timeout"] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}


async def test_a_configured_timeout_overrides_the_connections(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(connection="api", path="/x", timeout=timedelta(seconds=2.5))
    await HttpRequestOperator().execute(config, ctx.as_context())
    assert handler.requests[0].extensions["timeout"] == {"connect": 2.5, "read": 2.5, "write": 2.5, "pool": 2.5}


@pytest.mark.parametrize(
    ("status", "expected"),
    [(500, ErrorClass.TRANSIENT), (502, ErrorClass.TRANSIENT), (400, ErrorClass.REJECTED), (301, ErrorClass.UNKNOWN)],
)
def test_status_classification(status: int, expected: ErrorClass) -> None:
    assert status_class(status) is expected


# -- http.ready ------------------------------------------------------------------


async def test_the_sensor_observes_a_ready_service(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(200, text="ready"))
    observed = await HttpReadySensor().poke(HttpReadyConfig(connection="api", path="/health"), ctx.as_context())
    assert isinstance(observed, HttpReadyOutput)
    assert observed.status == 200
    assert observed.matched is False


async def test_a_poke_without_an_override_inherits_the_connections_timeout(ctx: FakeContext) -> None:
    ctx.handler = handler = Responder(httpx2.Response(200, text="ready"))
    await HttpReadySensor().poke(HttpReadyConfig(connection="api", path="/health"), ctx.as_context())
    assert handler.requests[0].extensions["timeout"] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}

    ctx.handler = handler = Responder(httpx2.Response(200, text="ready"))
    await HttpReadySensor().poke(
        HttpReadyConfig(connection="api", path="/health", timeout=timedelta(seconds=1.5)), ctx.as_context()
    )
    assert handler.requests[0].extensions["timeout"] == {"connect": 1.5, "read": 1.5, "write": 1.5, "pool": 1.5}


async def test_the_sensor_reports_not_yet_while_the_service_is_unhealthy(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(503, text="starting"))
    assert isinstance(await HttpReadySensor().poke(HttpReadyConfig(connection="api"), ctx.as_context()), NotYet)


async def test_the_sensor_treats_an_unreachable_service_as_the_condition_not_an_error(
    ctx: FakeContext,
) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("nothing listening yet")

    ctx.handler = refuse
    observed = await HttpReadySensor().poke(HttpReadyConfig(connection="api"), ctx.as_context())
    assert isinstance(observed, NotYet)
    assert "not reachable yet" in " ".join(ctx.log.messages())


async def test_the_sensor_can_require_a_body_matcher(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(200, text="status: starting"))
    config = HttpReadyConfig(connection="api", contains="status: ready")
    assert isinstance(await HttpReadySensor().poke(config, ctx.as_context()), NotYet)

    ctx.handler = Responder(httpx2.Response(200, text="status: ready"))
    observed = await HttpReadySensor().poke(config, ctx.as_context())
    assert isinstance(observed, HttpReadyOutput)
    assert observed.matched is True


async def test_the_sensor_can_require_specific_statuses(ctx: FakeContext) -> None:
    ctx.handler = Responder(httpx2.Response(204))
    strict = HttpReadyConfig(connection="api", expect_status=[200])
    assert isinstance(await HttpReadySensor().poke(strict, ctx.as_context()), NotYet)
    lenient = HttpReadyConfig(connection="api", expect_status=[204])
    assert isinstance(await HttpReadySensor().poke(lenient, ctx.as_context()), HttpReadyOutput)


# -- the connection kind ---------------------------------------------------------


def test_the_connection_marks_its_secret_fields() -> None:
    fields = HttpConnectionConfig.model_fields
    assert fields["bearer_token"].annotation is not str
    config = HttpConnectionConfig(base_url="http://x", bearer_token=SecretStr("t0ken"))
    assert "t0ken" not in repr(config)


def test_a_connection_field_that_does_not_exist_is_refused_not_ignored() -> None:
    """A stored connection config is a map, so a misspelled field has to be caught reading it."""
    with pytest.raises(ValidationError) as raised:
        HttpConnectionConfig.model_validate({"base_url": "http://x", "verify_ssl": False})
    assert [(error["loc"], error["type"]) for error in raised.value.errors()] == [(("verify_ssl",), "extra_forbidden")]


def test_a_bearer_connection_builds_an_authorized_client() -> None:
    config = HttpConnectionConfig(base_url="http://x", bearer_token=SecretStr("t0ken"))
    client = build_client(config)
    assert client.headers["authorization"] == "Bearer t0ken"
    assert str(client.base_url) == "http://x"


def test_a_basic_auth_connection_builds_an_authenticated_client() -> None:
    config = HttpConnectionConfig(base_url="http://x", basic_username="u", basic_password=SecretStr("p"))
    assert build_client(config).auth is not None


async def test_the_connection_check_reports_health(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = Responder(httpx2.Response(200, headers={"server": "nginx"}))

    def fake_client(config: HttpConnectionConfig) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url=config.base_url, transport=httpx2.MockTransport(handler))

    monkeypatch.setattr("dirigent_blocks.connections.build_client", fake_client)
    report = await HttpConnectionKind().check(HttpConnectionConfig(base_url="http://x"))
    assert report.healthy is True
    assert report.version == "nginx"


async def test_the_connection_check_reports_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    def fake_client(config: HttpConnectionConfig) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url=config.base_url, transport=httpx2.MockTransport(refuse))

    monkeypatch.setattr("dirigent_blocks.connections.build_client", fake_client)
    report = await HttpConnectionKind().check(HttpConnectionConfig(base_url="http://x"))
    assert report.healthy is False
    assert "ConnectError" in (report.detail or "")


async def test_a_saved_body_is_streamed_rather_than_held_whole(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """save_to exists so a response of any size need not fit in the worker's memory.

    A body that arrives in many chunks has to reach storage in many writes. One write is the
    proof that the whole thing was materialised first.
    """
    writes: list[int] = []

    class Recording:
        """A sink that remembers how many times it was written to."""

        async def write(self, data: bytes) -> int:
            writes.append(len(data))
            return len(data)

    @asynccontextmanager
    async def recording_write(uri: str) -> AsyncGenerator[Any]:
        yield Recording()

    chunks = [b"x" * 1024 for _ in range(8)]

    async def arriving() -> AsyncGenerator[bytes]:
        """A body that arrives over the wire in pieces, as a large one does."""
        for chunk in chunks:
            yield chunk

    ctx.handler = Responder(
        httpx2.Response(200, content=arriving(), headers={"content-type": "application/octet-stream"})
    )
    monkeypatch.setattr(ctx.storage, "open_write", recording_write)
    body = b"".join(chunks)

    config = HttpRequestConfig(connection="api", path="/big", save_to="file://out.bin")
    output = await HttpRequestOperator().execute(config, ctx.as_context())

    assert isinstance(output, HttpRequestOutput)
    assert output.body_bytes == len(body)
    assert sum(writes) == len(body), "the whole body reached storage"
    assert len(writes) > 1, "the body was buffered whole before being written"


async def test_a_response_too_large_to_hold_is_refused_rather_than_truncated(ctx: FakeContext) -> None:
    """Half a JSON document is not a smaller answer, so a step is told rather than handed one."""
    chunks = [b"x" * 1024 for _ in range(8)]

    async def arriving() -> AsyncGenerator[bytes]:
        for chunk in chunks:
            yield chunk

    ctx.handler = Responder(httpx2.Response(200, content=arriving()))
    config = HttpRequestConfig(connection="api", path="/big", max_response=4096)

    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(config, ctx.as_context())

    assert raised.value.error_class is ErrorClass.REJECTED, "reading it again would read the same size"
    assert "max_response" in str(raised.value)
    assert "save_to" in str(raised.value), "and says what to do instead"


async def test_a_response_inside_the_bound_is_read_whole(ctx: FakeContext) -> None:
    """The bound is a limit, not a budget: a body under it arrives entire and parses."""
    ctx.handler = Responder(json_response(200, {"rows": list(range(50))}))
    config = HttpRequestConfig(connection="api", path="/fits", max_response=64 * 1024)

    output = await HttpRequestOperator().execute(config, ctx.as_context())

    assert isinstance(output, HttpRequestOutput)
    assert output.json_body == {"rows": list(range(50))}


async def test_a_saved_body_is_not_bounded_by_max_response(ctx: FakeContext) -> None:
    """save_to streams, so what bounds it is the storage rather than the worker's memory."""
    chunks = [b"y" * 1024 for _ in range(8)]

    async def arriving() -> AsyncGenerator[bytes]:
        for chunk in chunks:
            yield chunk

    ctx.handler = Responder(httpx2.Response(200, content=arriving()))
    config = HttpRequestConfig(connection="api", path="/big", save_to="file://out.bin", max_response=1024)

    output = await HttpRequestOperator().execute(config, ctx.as_context())

    assert isinstance(output, HttpRequestOutput)
    assert output.body_bytes == 8 * 1024


async def test_a_probe_stops_reading_an_endpoint_that_will_not_stop_answering(ctx: FakeContext) -> None:
    """A poke asks whether a service is up, and repeats every few seconds.

    An endpoint answering a readiness check with more than the step said it would hold is not
    answering the question, and holding it would put a worker at the mercy of what it pokes.
    """
    chunks = [b"z" * 1024 for _ in range(8)]

    async def arriving() -> AsyncGenerator[bytes]:
        for chunk in chunks:
            yield chunk

    ctx.handler = Responder(httpx2.Response(200, content=arriving()))
    config = HttpReadyConfig(connection="api", path="/health", contains="ready", max_response=2048)

    with pytest.raises(BlockFailure) as raised:
        await HttpReadySensor().poke(config, ctx.as_context())

    assert "max_response" in str(raised.value)


async def test_a_probe_inside_the_bound_still_matches_its_body(ctx: FakeContext) -> None:
    """The bound must not change what readiness means for an endpoint that answers normally."""
    ctx.handler = Responder(httpx2.Response(200, text="everything is ready here"))

    observed = await HttpReadySensor().poke(
        HttpReadyConfig(connection="api", path="/health", contains="ready"), ctx.as_context()
    )

    assert isinstance(observed, HttpReadyOutput)
    assert observed.matched is True


async def test_a_failed_answer_never_replaces_what_save_to_already_holds(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    """A 500 is not a body worth keeping: saving it would destroy the last good one."""
    target = storage.path_for("file://saved/report.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"the good answer")

    ctx.handler = Responder(httpx2.Response(500, text="upstream exploded"))
    config = HttpRequestConfig(connection="api", path="/report", save_to="file://saved/report.json")

    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(config, ctx.as_context())

    assert raised.value.error_class is ErrorClass.TRANSIENT
    assert "500" in str(raised.value)
    assert target.read_bytes() == b"the good answer"


async def test_a_failed_answer_writes_no_object_where_there_was_none(ctx: FakeContext, storage: FakeStorage) -> None:
    ctx.handler = Responder(httpx2.Response(401, text="who are you"))
    config = HttpRequestConfig(connection="api", path="/report", save_to="file://unwritten/report.json")

    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(config, ctx.as_context())

    assert raised.value.error_class is ErrorClass.REJECTED
    assert not storage.path_for("file://unwritten/report.json").exists()


async def test_a_body_streamed_from_storage_reaches_the_service_intact(ctx: FakeContext, storage: FakeStorage) -> None:
    """body_from is the sending half of save_to: the bytes go from storage onto the wire."""
    payload = bytes(range(256)) * 64
    storage.path_for("file://upload.bin").write_bytes(payload)
    ctx.handler = handler = Responder(json_response(200, {"ok": True}))
    config = HttpRequestConfig(
        connection="api",
        method="POST",
        path="/v1/files",
        body_from="file://upload.bin",
        content_type="application/octet-stream",
    )

    output = await HttpRequestOperator().execute(config, ctx.as_context())

    assert isinstance(output, HttpRequestOutput)
    assert output.sent_bytes == len(payload)
    request = handler.requests[0]
    assert request.content == payload, "every byte arrived, and in order"
    assert request.headers["content-type"] == "application/octet-stream"


async def test_a_sized_object_is_sent_with_a_content_length_rather_than_chunked(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    """Storage knows how big the object is, so the receiver is told rather than left counting."""
    storage.path_for("file://upload.json").write_bytes(b'{"rows": 3}')
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(
        connection="api",
        method="PUT",
        path="/v1/files",
        body_from="file://upload.json",
        content_type="application/json",
    )

    await HttpRequestOperator().execute(config, ctx.as_context())

    request = handler.requests[0]
    assert request.headers["content-length"] == "11"
    assert "transfer-encoding" not in request.headers


async def test_the_content_type_storage_reports_is_the_one_sent(
    ctx: FakeContext, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backend that stores the content type answers the question, so the step need not."""
    storage.path_for("file://upload.parquet").write_bytes(b"PAR1")

    async def described(uri: str) -> StatResult:
        return StatResult(uri=uri, size=4, modified_at=datetime.now(tz=UTC), content_type="application/parquet")

    monkeypatch.setattr(ctx.storage, "stat", described)
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(connection="api", method="POST", path="/v1/files", body_from="file://upload.parquet")

    await HttpRequestOperator().execute(config, ctx.as_context())

    assert handler.requests[0].headers["content-type"] == "application/parquet"


async def test_a_named_content_type_wins_over_the_one_storage_reports(ctx: FakeContext, storage: FakeStorage) -> None:
    """A header names the content type for a stored body the same way it does for text."""
    storage.path_for("file://upload.bin").write_bytes(b"rows")
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(
        connection="api",
        method="POST",
        path="/v1/files",
        body_from="file://upload.bin",
        content_type="application/octet-stream",
        headers={"Content-Type": "application/vnd.acme+binary"},
    )

    await HttpRequestOperator().execute(config, ctx.as_context())

    assert handler.requests[0].headers["content-type"] == "application/vnd.acme+binary"


async def test_a_stored_body_nobody_can_name_a_type_for_is_refused(ctx: FakeContext, storage: FakeStorage) -> None:
    """A file on disk carries no content type, so the document has to say what it is."""
    storage.path_for("file://upload.bin").write_bytes(b"rows")
    config = HttpRequestConfig(connection="api", method="POST", path="/v1/files", body_from="file://upload.bin")

    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(config, ctx.as_context())

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "content_type" in str(raised.value)


async def test_a_missing_object_is_rejected_before_the_call_is_made(ctx: FakeContext) -> None:
    """The file the upstream step was supposed to write is not there, and a retry cannot help."""
    ctx.handler = handler = Responder(json_response(200, {}))
    config = HttpRequestConfig(
        connection="api",
        method="POST",
        path="/v1/files",
        body_from="file://never-written.bin",
        content_type="application/octet-stream",
    )

    with pytest.raises(BlockFailure) as raised:
        await HttpRequestOperator().execute(config, ctx.as_context())

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "file://never-written.bin" in str(raised.value)
    assert handler.requests == [], "nothing was sent"


async def test_a_call_abandoned_mid_body_releases_the_storage_stream(
    ctx: FakeContext, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled upload must not leave the file handle open until the worker is collected."""
    storage.path_for("file://upload.bin").write_bytes(b"x" * 16)
    released = False

    async def reading(uri: str) -> AsyncGenerator[bytes]:
        nonlocal released
        try:
            yield b"x" * 8
            yield b"x" * 8
        finally:
            released = True

    class Abandoning(httpx2.AsyncBaseTransport):
        """A transport that takes one chunk of the request body and then gives up on the call."""

        def __init__(self) -> None:
            self.taken: list[bytes] = []

        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            stream = request.stream
            assert isinstance(stream, httpx2.AsyncByteStream)
            async for chunk in stream:
                self.taken.append(chunk)
                raise asyncio.CancelledError
            raise AssertionError("the request carried no body")

    transport = Abandoning()

    def client(ref: str) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://service.test", transport=transport)

    monkeypatch.setattr(ctx.storage, "open_read", reading)
    monkeypatch.setattr(ctx, "http", client)
    config = HttpRequestConfig(
        connection="api",
        method="POST",
        path="/v1/files",
        body_from="file://upload.bin",
        content_type="application/octet-stream",
    )

    with pytest.raises(asyncio.CancelledError):
        await HttpRequestOperator().execute(config, ctx.as_context())

    assert transport.taken == [b"x" * 8], "the send stopped part way through the object"
    assert released, "the storage stream was closed rather than left to the collector"


async def test_a_successful_answer_is_still_saved(ctx: FakeContext, storage: FakeStorage) -> None:
    ctx.handler = Responder(httpx2.Response(200, text="the good answer"))
    config = HttpRequestConfig(connection="api", path="/report", save_to="file://saved/fresh.json")

    output = await HttpRequestOperator().execute(config, ctx.as_context())

    assert isinstance(output, HttpRequestOutput)
    assert output.body_uri == "file://saved/fresh.json"
    assert output.body_bytes == len(b"the good answer")
    assert storage.path_for("file://saved/fresh.json").read_bytes() == b"the good answer"
