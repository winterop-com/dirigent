"""What a server bound to loopback answers to, which is how DNS rebinding is refused."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dirigent_core.config import Settings
from dirigent_server import create_app
from dirigent_server.messages import HOST_NOT_LOOPBACK


@pytest.fixture
def guarded(settings: Settings, admin_token: str) -> Iterator[TestClient]:
    with TestClient(create_app(settings, scheduler=False, loopback_only=True)) as client:
        yield client


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.1:3333", "127.0.0.2:3333", "localhost", "localhost:3333", "LOCALHOST:3333", "[::1]:3333"],
)
def test_a_loopback_name_is_served(guarded: TestClient, host: str) -> None:
    assert guarded.get("/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:3333",
        "127.0.0.1.evil.example",
        "localhost.evil.example:3333",
        "evil.localhost",
        "localhost.",
        "0.0.0.0:3333",
        "192.168.1.10:3333",
        "[2001:db8::1]:3333",
        "[::1].evil.example",
        "127.0.0.1:evil.example",
        "localhost@evil.example",
        "127.0.0.1, evil.example",
        "",
    ],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/health"), ("GET", "/"), ("GET", "/api/v1/auth/me"), ("POST", "/api/v1/auth/login")],
)
def test_any_other_host_is_refused_on_every_layer(guarded: TestClient, host: str, method: str, path: str) -> None:
    response = guarded.request(method, path, headers={"host": host})
    assert response.status_code == 421
    assert response.json()["code"] == HOST_NOT_LOOPBACK.code
    assert response.headers["x-frame-options"] == "DENY"


def test_a_rebound_page_cannot_sign_in(guarded: TestClient) -> None:
    response = guarded.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
        headers={"host": "evil.example:3333", "origin": "http://evil.example:3333", "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 421
    assert "set-cookie" not in response.headers


def test_two_host_headers_are_judged_together(guarded: TestClient) -> None:
    response = guarded.get("/health", headers=[("host", "127.0.0.1"), ("host", "evil.example")])
    assert response.status_code == 421


def test_a_server_not_asked_to_is_served_under_any_name(settings: Settings, admin_token: str) -> None:
    with TestClient(create_app(settings, scheduler=False)) as client:
        assert client.get("/health", headers={"host": "dirigent.example.org"}).status_code == 200
