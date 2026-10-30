"""The default security headers, on every layer that can answer a request."""

from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from dirigent_core import __version__
from dirigent_core.config import Settings
from dirigent_server import create_app
from dirigent_server.errors import VERSION_HEADER
from dirigent_server.messages import INTERNAL
from dirigent_server.security import DOCS_POLICY, UI_POLICY


@pytest.mark.parametrize(
    "path",
    ["/health", "/api/v1/auth/me", "/api/v1/no-such-route", "/config.json", "/assets/missing.js", "/openapi.json"],
)
def test_every_layer_sends_the_defaults(anonymous: TestClient, path: str) -> None:
    headers = anonymous.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "same-origin"
    assert headers["content-security-policy"] == UI_POLICY


def test_a_refused_write_sends_the_defaults(anonymous: TestClient) -> None:
    response = anonymous.post("/api/v1/auth/login", json={})
    assert response.status_code == 422
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    ("path", "policy"),
    [("/boom", UI_POLICY), ("/api/v1/boom", UI_POLICY), ("/docs/boom", DOCS_POLICY)],
)
def test_an_unhandled_exception_sends_the_defaults(
    settings: Settings, admin_token: str, path: str, policy: str
) -> None:
    async def boom() -> None:
        raise RuntimeError("something nobody expected")

    app = create_app(settings)
    app.router.routes.insert(0, APIRoute(path, boom))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(path)
    assert response.status_code == 500
    assert response.json()["code"] == INTERNAL.code
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["content-security-policy"] == policy
    assert response.headers[VERSION_HEADER] == __version__


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_the_api_viewers_have_their_own_policy(anonymous: TestClient, path: str) -> None:
    response = anonymous.get(path)
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == DOCS_POLICY
    assert response.headers["x-frame-options"] == "DENY"


def test_no_policy_allows_framing_or_a_script_from_elsewhere() -> None:
    for policy in (UI_POLICY, DOCS_POLICY):
        assert "frame-ancestors 'none'" in policy
    assert "script-src 'self';" in UI_POLICY
    assert "unsafe-eval" not in UI_POLICY + DOCS_POLICY


def test_the_shell_loads_no_inline_script_the_policy_would_block() -> None:
    index = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
    html = index.read_text()
    assert '<script src="/palette.js"></script>' in html
    assert "<script>" not in html
