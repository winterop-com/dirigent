"""The one request choke point: authentication, retries, and what each refusal becomes."""

import httpx2
import pytest

from clientsupport import BASE_URL, Recorder, client_of, ok, refusal
from dirigent_client import (
    API_PREFIX,
    Conflict,
    Dirigent,
    DirigentError,
    Forbidden,
    NotDirigent,
    NotFound,
    RateLimited,
    ServerError,
    TransportError,
    Unauthorized,
    ValidationFailed,
)
from dirigent_client.transport import BACKOFF_MAX_SECONDS, backoff_for


async def test_every_call_carries_the_bearer_token_and_the_api_prefix() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return ok({"items": [], "next": None})

    async with client_of(Recorder(handler)) as dg:
        await dg.pipelines.list()
    assert seen[0].headers["authorization"] == "Bearer a-token"
    assert seen[0].url.path == f"{API_PREFIX}/pipelines"


async def test_a_call_may_name_its_own_timeout() -> None:
    recorder = Recorder([ok({"items": [], "next": None})])
    async with client_of(recorder, timeout=1.0) as dg:
        await dg.transport.request("GET", "/pipelines", timeout=90.0)
    assert recorder.paths == [f"{API_PREFIX}/pipelines"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, DirigentError),
        (401, Unauthorized),
        (403, Forbidden),
        (404, NotFound),
        (409, Conflict),
        (422, ValidationFailed),
        (429, RateLimited),
        (500, ServerError),
        (503, ServerError),
    ],
)
async def test_each_status_becomes_the_exception_a_caller_branches_on(
    status: int, expected: type[DirigentError], no_sleep: list[float]
) -> None:
    async with client_of(Recorder([refusal(status, "no")])) as dg:
        with pytest.raises(expected) as raised:
            await dg.pipelines.get("nothing")
    assert raised.value.status == status
    assert raised.value.url.endswith("/pipelines/nothing")
    assert raised.value.problem is not None


async def test_a_validation_failure_carries_the_field_list_it_named() -> None:
    problems = ["params.day: Input should be a valid string"]
    async with client_of(Recorder([refusal(422, "; ".join(problems), problems=problems)])) as dg:
        with pytest.raises(ValidationFailed) as raised:
            await dg.pipelines.run("demo", params={"day": 3})
    assert raised.value.problems == problems


async def test_a_rate_limit_carries_how_long_the_server_asked_for() -> None:
    async with client_of(Recorder([refusal(429, "slow down", headers={"retry-after": "5"})])) as dg:
        with pytest.raises(RateLimited) as raised:
            await dg.pipelines.list()
    assert raised.value.retry_after == 5.0


async def test_a_retry_after_that_is_a_date_is_ignored_rather_than_guessed() -> None:
    header = {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}
    async with client_of(Recorder([refusal(429, "slow down", headers=header)])) as dg:
        with pytest.raises(RateLimited) as raised:
            await dg.pipelines.list()
    assert raised.value.retry_after is None


async def test_a_refusal_with_no_version_header_is_not_a_dirigent_instance() -> None:
    answer = httpx2.Response(404, text="<html>not found</html>", headers={"content-type": "text/html"})
    async with client_of(Recorder([answer])) as dg:
        with pytest.raises(NotDirigent) as raised:
            await dg.pipelines.list()
    assert "does not look like a dirigent instance" in raised.value.message
    assert "text/html" in raised.value.message
    assert raised.value.base_url == BASE_URL


async def test_a_reply_with_no_content_type_at_all_is_still_named() -> None:
    async with client_of(Recorder([httpx2.Response(404)])) as dg:
        with pytest.raises(NotDirigent) as raised:
            await dg.pipelines.list()
    assert "no content type" in raised.value.message


async def test_a_refusal_whose_body_is_not_json_still_says_the_status() -> None:
    answer = httpx2.Response(404, text="nope", headers={"X-Dirigent-Version": "0.1.0"})
    async with client_of(Recorder([answer])) as dg:
        with pytest.raises(NotFound) as raised:
            await dg.pipelines.list()
    assert raised.value.message == "HTTP 404"
    assert raised.value.problem is None


async def test_a_bare_detail_body_is_read_even_without_the_whole_envelope() -> None:
    answer = httpx2.Response(404, json={"detail": "no pipeline coded 'x'"}, headers={"X-Dirigent-Version": "0.1.0"})
    async with client_of(Recorder([answer])) as dg:
        with pytest.raises(NotFound) as raised:
            await dg.pipelines.list()
    assert raised.value.message == "no pipeline coded 'x'"


async def test_a_detail_that_is_a_field_list_is_rendered_into_problems() -> None:
    body = {"detail": [{"loc": ["body", "name"], "msg": "field required"}]}
    answer = httpx2.Response(422, json=body, headers={"X-Dirigent-Version": "0.1.0"})
    async with client_of(Recorder([answer])) as dg:
        with pytest.raises(ValidationFailed) as raised:
            await dg.pipelines.list()
    assert raised.value.problems == ["body.name: field required"]


async def test_an_unreachable_server_names_the_url_it_could_not_reach(no_sleep: list[float]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    async with client_of(Recorder(handler)) as dg:
        with pytest.raises(TransportError) as raised:
            await dg.pipelines.list()
    assert BASE_URL in raised.value.message
    assert isinstance(raised.value.cause, httpx2.ConnectError)


async def test_an_idempotent_call_is_retried_through_a_transport_failure(no_sleep: list[float]) -> None:
    attempts: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx2.ReadError("dropped", request=request)
        return ok({"items": [], "next": None})

    async with client_of(Recorder(handler)) as dg:
        assert (await dg.pipelines.list()).items == []
    assert len(attempts) == 3
    assert no_sleep == [backoff_for(0), backoff_for(1)]


async def test_an_idempotent_call_is_retried_through_a_server_error(no_sleep: list[float]) -> None:
    recorder = Recorder([refusal(503, "restarting"), ok({"items": [], "next": None})])
    async with client_of(recorder) as dg:
        assert (await dg.pipelines.list()).items == []
    assert len(recorder.calls) == 2


async def test_a_post_is_never_repeated_because_it_may_already_have_taken_effect(no_sleep: list[float]) -> None:
    recorder = Recorder([refusal(503, "restarting")])
    async with client_of(recorder) as dg:
        with pytest.raises(ServerError):
            await dg.pipelines.run("demo")
    assert len(recorder.calls) == 1


async def test_retries_can_be_turned_off(no_sleep: list[float]) -> None:
    recorder = Recorder([refusal(500, "boom")])
    async with client_of(recorder, retries=0) as dg:
        with pytest.raises(ServerError):
            await dg.pipelines.list()
    assert len(recorder.calls) == 1


def test_backoff_doubles_and_then_stops_growing() -> None:
    assert backoff_for(0) < backoff_for(1) < backoff_for(2)
    assert backoff_for(20) == BACKOFF_MAX_SECONDS


async def test_the_client_can_be_closed_without_a_context_manager() -> None:
    dg = client_of(Recorder([ok({"items": [], "next": None})]))
    assert dg.url == BASE_URL
    await dg.aclose()


async def test_a_trailing_slash_on_the_url_does_not_become_a_double_slash() -> None:
    recorder = Recorder([ok({"items": [], "next": None})])
    async with Dirigent(url=f"{BASE_URL}/", http_transport=httpx2.MockTransport(recorder)) as dg:
        await dg.pipelines.list()
    assert recorder.paths == [f"{API_PREFIX}/pipelines"]


async def test_a_client_with_no_token_sends_no_authorization_header() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return ok({"status": "ok", "version": "0.1.0"})

    async with Dirigent(url=BASE_URL, http_transport=httpx2.MockTransport(handler)) as dg:
        await dg.system.health()
    assert "authorization" not in seen[0].headers
