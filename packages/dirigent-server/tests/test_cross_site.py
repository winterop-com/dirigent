"""The cross-site guard: a session cookie may not be spent on a write another site caused.

The session cookie is ambient, so a browser attaches it to a request an attacker's page
made. A bearer token is not, so a request carrying one is exempt whatever it says about its
origin.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dirigent_core.config import Settings
from dirigent_server import create_app
from dirigent_server.routes.auth import LOGIN_BUCKETS
from dirigent_server.security import SESSION_COOKIE
from tests_support import PASSWORD, USERNAME

PREFIX = "/api/v1"
LOGIN = f"{PREFIX}/auth/login"
TOKENS = f"{PREFIX}/tokens"
ELSEWHERE = "https://an-attacker.example"


@pytest.fixture(autouse=True)
def _empty_buckets() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Empty the process-wide login limiter, which outlives a request and so a test."""
    LOGIN_BUCKETS.buckets.clear()
    yield
    LOGIN_BUCKETS.buckets.clear()


@pytest.fixture
def browser(anonymous: TestClient) -> TestClient:
    """A client holding a session cookie, as a logged-in browser does."""
    assert anonymous.post(LOGIN, json={"username": USERNAME, "password": PASSWORD}).status_code == 200
    assert SESSION_COOKIE in anonymous.cookies
    return anonymous


def test_a_cross_site_write_spending_the_cookie_is_refused(browser: TestClient) -> None:
    response = browser.post(TOKENS, json={"name": "stolen"}, headers={"Origin": ELSEWHERE})
    assert response.status_code == 403
    assert "another site" in response.json()["detail"]


def test_fetch_metadata_alone_is_enough_to_refuse(browser: TestClient) -> None:
    response = browser.post(TOKENS, json={"name": "stolen"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert response.json()["status"] == 403


def test_a_same_origin_write_spending_the_cookie_passes(browser: TestClient) -> None:
    response = browser.post(TOKENS, json={"name": "from-the-ui"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 201


def test_a_write_declaring_no_origin_passes(browser: TestClient) -> None:
    assert browser.post(TOKENS, json={"name": "from-curl"}).status_code == 201


def test_a_navigation_write_passes(browser: TestClient) -> None:
    response = browser.post(TOKENS, json={"name": "from-a-form"}, headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 201


def test_a_bearer_token_is_exempt_because_no_browser_attaches_it(client: TestClient) -> None:
    response = client.post(TOKENS, json={"name": "automation"}, headers={"Origin": ELSEWHERE})
    assert response.status_code == 201


def test_a_bearer_token_wins_over_a_cookie_the_same_request_carries(browser: TestClient, admin_token: str) -> None:
    headers = {"Origin": ELSEWHERE, "Authorization": f"Bearer {admin_token}"}
    assert browser.post(TOKENS, json={"name": "automation"}, headers=headers).status_code == 201


def test_a_cross_site_login_is_refused_before_a_session_exists(anonymous: TestClient) -> None:
    response = anonymous.post(LOGIN, json={"username": USERNAME, "password": PASSWORD}, headers={"Origin": ELSEWHERE})
    assert response.status_code == 403
    assert SESSION_COOKIE not in anonymous.cookies


def test_a_same_origin_login_passes(anonymous: TestClient) -> None:
    response = anonymous.post(
        LOGIN, json={"username": USERNAME, "password": PASSWORD}, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 200


def test_a_cross_site_read_is_not_a_write(browser: TestClient) -> None:
    assert browser.get(f"{PREFIX}/pipelines", headers={"Origin": ELSEWHERE}).status_code == 200


def test_webhook_intake_is_not_guarded_by_the_cookie(anonymous: TestClient) -> None:
    response = anonymous.post("/hooks/not-a-token", json={}, headers={"Origin": ELSEWHERE})
    assert response.status_code == 404


def test_the_guard_follows_the_configured_api_prefix(settings: Settings, admin_token: str) -> None:
    moved = settings.model_copy(update={"api_prefix": "/api/v2"})
    with TestClient(create_app(moved)) as client:
        login = client.post("/api/v2/auth/login", json={"username": USERNAME, "password": PASSWORD})
        refused = client.post("/api/v2/tokens", json={"name": "stolen"}, headers={"Origin": ELSEWHERE})
    assert login.status_code == 200
    assert refused.status_code == 403
