"""A connection whose base URL redirects: where the base lands, and what reaches it."""

import base64
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dirigent_common import CredentialOnOrigin, HttpConnectionConfig, build_client, raised_detail, secrets_of
from dirigent_common.clients import resolve_base

ALIAS = "https://play.dhis2.org/2.43"
TARGET = "https://play.im.dhis2.org/stable-2-43-2"

#: A version alias on one host redirecting to a demo on another, which sends an anonymous
#: caller to its sign-in page over plain HTTP before TLS takes it back.
REDIRECTS = {
    f"{ALIAS}/": f"{TARGET}/",
    f"{TARGET}/": "http://play.im.dhis2.org/stable-2-43-2/login/",
    "http://play.im.dhis2.org/stable-2-43-2/login/": f"{TARGET}/login/",
}


def _serve(monkeypatch: pytest.MonkeyPatch, seen: list[httpx2.Request]) -> None:
    """Answer every client from the redirects above, and an echo of the credential elsewhere."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        location = REDIRECTS.get(str(request.url))
        if location is not None:
            return httpx2.Response(302, headers={"location": location})
        return httpx2.Response(200, json={"authorization": request.headers.get("authorization")})

    real = httpx2.AsyncClient

    def build(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs["transport"] = httpx2.MockTransport(handle)
        return real(**kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", build)


async def test_a_base_lands_where_its_redirects_take_it_and_not_on_the_sign_in_page_inside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, [])
    assert await resolve_base(ALIAS, verify=True) == TARGET


async def test_a_base_redirecting_only_inside_itself_stays_put(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, [])
    assert await resolve_base(TARGET, verify=True) == TARGET


async def test_a_connection_following_redirects_sends_the_credential_and_the_method_to_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx2.Request] = []
    _serve(monkeypatch, seen)
    config = HttpConnectionConfig(
        base_url=ALIAS, basic_username="admin", basic_password=SecretStr("district"), follow_redirects_with_auth=True
    )
    async with build_client(config) as client:
        response = await client.post("/api/dataValueSets", json={})
    assert response.status_code == 200
    expected = "Basic " + base64.b64encode(b"admin:district").decode()
    assert response.json() == {"authorization": expected}
    sent = seen[-1]
    assert (sent.method, str(sent.url), sent.headers["host"]) == (
        "POST",
        f"{TARGET}/api/dataValueSets",
        "play.im.dhis2.org",
    )
    assert all(request.headers.get("authorization") is None for request in seen[:-1])


async def test_a_connection_without_the_setting_answers_with_the_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, [])
    config = HttpConnectionConfig(base_url=ALIAS, basic_username="admin", basic_password=SecretStr("district"))
    async with build_client(config) as client:
        response = await client.get("/")
    assert response.status_code == 302


@pytest.mark.parametrize(
    ("settings", "header", "sent"),
    [
        ({}, "authorization", "dummy"),
        ({"credential_scheme": "Token"}, "authorization", "Token dummy"),
        ({"credential_header": "X-Api-Key"}, "x-api-key", "dummy"),
    ],
    ids=["alone", "under-a-scheme", "in-a-header-of-its-own"],
)
def test_a_credential_is_sent_in_its_header(settings: dict[str, str], header: str, sent: str) -> None:
    config = HttpConnectionConfig.model_validate({"base_url": "http://x", "credential": "dummy", **settings})
    assert build_client(config).headers[header] == sent


def test_a_credential_is_sealed_and_named_among_the_secrets() -> None:
    config = HttpConnectionConfig(base_url="http://x", credential=SecretStr("dummy"))
    assert "dummy" not in repr(config)
    assert secrets_of(config) == {"dummy"}


def test_an_empty_credential_is_unset() -> None:
    config = HttpConnectionConfig.model_validate({"base_url": "http://x", "credential": ""})
    assert config.credential is None
    assert "authorization" not in build_client(config).headers


@pytest.mark.parametrize("value", ["DUMMY\n", "Bearer DUMMY", " DUMMY", "DUMMYé"])
def test_a_credential_that_cannot_be_sent_is_refused_without_repeating_it(value: str) -> None:
    with pytest.raises(ValidationError, match="a credential must be visible ASCII") as refused:
        HttpConnectionConfig.model_validate({"base_url": "http://x", "credential": value})
    assert "DUMMY" not in str(refused.value)


@pytest.mark.parametrize("field", ["credential_header", "credential_scheme"])
def test_a_credential_word_with_a_space_in_it_is_refused(field: str) -> None:
    with pytest.raises(ValidationError, match="must each be one HTTP token"):
        HttpConnectionConfig.model_validate({"base_url": "http://x", field: "two words"})


async def test_a_credential_in_a_header_of_its_own_stays_on_the_origin() -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.host == "service.test":
            return httpx2.Response(302, headers={"location": "http://elsewhere.test/moved"})
        return httpx2.Response(200)

    async with httpx2.AsyncClient(
        base_url="http://service.test",
        headers={"X-Api-Key": "dummy"},
        event_hooks={"request": [CredentialOnOrigin("http://service.test", "X-Api-Key")]},
        transport=httpx2.MockTransport(handle),
        follow_redirects=True,
    ) as client:
        await client.get("/start")
    assert [request.headers.get("x-api-key") for request in seen] == ["dummy", None]


def test_the_client_carries_the_hook_only_with_a_credential() -> None:
    bare = build_client(HttpConnectionConfig(base_url="http://x"))
    held = build_client(HttpConnectionConfig(base_url="http://x", credential=SecretStr("dummy")))
    assert bare.event_hooks["request"] == []
    assert [type(hook) for hook in held.event_hooks["request"]] == [CredentialOnOrigin]


def _as_a_query_parameter(handle: Any) -> httpx2.AsyncClient:
    built = build_client(
        HttpConnectionConfig(
            base_url="http://service.test/api", credential=SecretStr("a+b"), credential_query="api_key"
        )
    )
    return httpx2.AsyncClient(
        base_url=built.base_url,
        event_hooks=built.event_hooks,
        transport=httpx2.MockTransport(handle),
        follow_redirects=True,
    )


async def test_a_credential_sent_as_a_query_parameter_stays_on_the_origin() -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/api/start":
            return httpx2.Response(302, headers={"location": "/api/moved"})
        if request.url.path == "/api/moved":
            return httpx2.Response(302, headers={"location": "http://elsewhere.test/x?api_key=a%2Bb&keep=1"})
        return httpx2.Response(200)

    async with _as_a_query_parameter(handle) as client:
        await client.get("/start", params={"page": 2})
    first, same_origin, other = seen
    assert first.url.params["api_key"] == "a+b" and first.url.params["page"] == "2"
    assert same_origin.url.params["api_key"] == "a+b"
    assert "api_key" not in other.url.params and other.url.params["keep"] == "1"
    assert "authorization" not in first.headers


def test_a_credential_cannot_go_in_a_query_parameter_and_a_header() -> None:
    for beside in ({"credential_header": "X-Api-Key"}, {"credential_scheme": "Token"}):
        with pytest.raises(ValidationError, match="credential goes in one place"):
            HttpConnectionConfig.model_validate(
                {"base_url": "http://x", "credential": "dummy", "credential_query": "api_key", **beside}
            )


def test_a_connection_read_back_through_its_dump_still_validates() -> None:
    config = HttpConnectionConfig(base_url="http://x", credential=SecretStr("dummy"), credential_query="api_key")
    assert HttpConnectionConfig.model_validate(config.model_dump()).credential_query == "api_key"


def test_the_query_parameter_is_scrubbed_from_a_url_a_failure_echoes() -> None:
    config = HttpConnectionConfig(base_url="http://x", credential=SecretStr("a+b/c"), credential_query="api_key")
    url = str(httpx2.URL("http://x/y").copy_set_param("api_key", "a+b/c"))
    assert "a+b" not in raised_detail(RuntimeError(f"could not reach {url}"), redact=secrets_of(config)).replace(
        "api_key=***", ""
    )
    assert "api_key=***" in raised_detail(RuntimeError(f"could not reach {url}"), redact=secrets_of(config))


@pytest.mark.parametrize(
    ("base_url", "said"),
    [
        ("https://user:DUMMY@service.test", "cannot carry a user or a password"),
        ("https://service.test?api_key=DUMMY", "the api_key query parameter"),
    ],
)
def test_a_base_url_refuses_a_credential_without_repeating_it(base_url: str, said: str) -> None:
    with pytest.raises(ValidationError) as refused:
        HttpConnectionConfig(base_url=base_url)
    assert said in str(refused.value)
    assert "DUMMY" not in str(refused.value)
