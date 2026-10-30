"""The default security headers, on every layer that can answer a request."""

import base64
import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dirigent_core.config import Settings
from dirigent_server import create_app
from dirigent_server.security import DOCS_POLICY, UI_POLICY
from dirigent_server.viewers import (
    REDOC_JS,
    REDOC_JS_INTEGRITY,
    SWAGGER_BOOTSTRAP,
    SWAGGER_CSS,
    SWAGGER_CSS_INTEGRITY,
    SWAGGER_JS,
    SWAGGER_JS_INTEGRITY,
)


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


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_the_api_viewers_have_their_own_policy(anonymous: TestClient, path: str) -> None:
    response = anonymous.get(path)
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == DOCS_POLICY
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    ("path", "tags"),
    [
        (
            "/docs",
            [
                f'<script src="{SWAGGER_JS}" integrity="{SWAGGER_JS_INTEGRITY}" crossorigin="anonymous">',
                f'<link rel="stylesheet" href="{SWAGGER_CSS}" integrity="{SWAGGER_CSS_INTEGRITY}" '
                'crossorigin="anonymous">',
            ],
        ),
        ("/redoc", [f'<script src="{REDOC_JS}" integrity="{REDOC_JS_INTEGRITY}" crossorigin="anonymous">']),
    ],
)
def test_a_viewer_loads_only_pinned_bytes(anonymous: TestClient, path: str, tags: list[str]) -> None:
    page = anonymous.get(path).text
    for tag in tags:
        assert tag in page
    loaded = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
    assert len(loaded) == len(tags), "every external load is one of the tags above"
    for url in loaded:
        assert re.search(r"@\d+\.\d+\.\d+/", url), f"{url} names no exact version"
    unpinned = [tag for tag in re.findall(r"<script[^>]*>", page) if "integrity=" not in tag]
    assert unpinned == (["<script>"] if path == "/docs" else []), "only the bootstrap, allowed by its hash"


def test_the_viewers_policy_names_their_bundles_and_not_their_host() -> None:
    sources = dict(directive.split(" ", 1) for directive in DOCS_POLICY.split("; "))
    digest = base64.b64encode(hashlib.sha256(SWAGGER_BOOTSTRAP.encode()).digest()).decode()
    assert sources["script-src"].split() == [SWAGGER_JS, REDOC_JS, f"'sha256-{digest}'"]
    assert sources["style-src"].split() == [SWAGGER_CSS, "'unsafe-inline'"]
    assert "https://cdn.jsdelivr.net " not in DOCS_POLICY
    assert "fonts.g" not in DOCS_POLICY


def test_a_viewer_page_holds_the_bootstrap_its_hash_was_taken_of(anonymous: TestClient) -> None:
    assert f"<script>{SWAGGER_BOOTSTRAP}</script>" in anonymous.get("/docs").text


def test_a_viewer_escapes_the_address_it_is_served_under(settings: Settings, admin_token: str) -> None:
    with TestClient(create_app(settings), root_path='/a"><script>') as client:
        page = client.get("/docs").text
    assert "<script>/openapi" not in page
    assert "&quot;&gt;&lt;script&gt;" in page


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
