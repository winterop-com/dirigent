"""A connection whose base URL redirects: where the base lands, and what reaches it."""

import base64
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from dirigent_common import HttpConnectionConfig, build_client
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
