"""What the versioned API reads from a caller before it knows who the caller is."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dirigent_server.bodies import LOGIN_MAX_BODY, UNAUTHENTICATED_MAX_BODY
from dirigent_server.routes.auth import LOGIN_BUCKETS

PREFIX = "/api/v1"
PAST_THE_CAP = b"x" * (UNAUTHENTICATED_MAX_BODY + 1)
APPLY = f"{PREFIX}/pipelines/$apply"
TOO_LARGE = "server.unauthenticated_body_too_large"


@pytest.fixture(autouse=True)
def fresh_login_buckets() -> Iterator[None]:
    LOGIN_BUCKETS.buckets.clear()
    yield
    LOGIN_BUCKETS.buckets.clear()


def in_pieces(body: bytes) -> Iterator[bytes]:
    """Send a body with no content length, so only counting what arrives can bound it."""
    yield body[:1024]
    yield body[1024:]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Cookie": "dirigent_session=not-a-session"}],
    ids=["none", "bad-bearer", "bad-cookie"],
)
def test_a_body_past_the_cap_is_refused_without_a_working_credential(
    anonymous: TestClient, headers: dict[str, str]
) -> None:
    response = anonymous.post(APPLY, content=PAST_THE_CAP, headers=headers)
    assert response.status_code == 413
    assert response.json()["code"] == TOO_LARGE
    assert "x-dirigent-version" in response.headers


def test_a_body_with_no_declared_length_is_counted(anonymous: TestClient) -> None:
    response = anonymous.post(APPLY, content=in_pieces(PAST_THE_CAP))
    assert response.status_code == 413
    assert response.json()["code"] == TOO_LARGE


def test_a_body_under_the_cap_reaches_authentication(anonymous: TestClient) -> None:
    response = anonymous.post(APPLY, content=b"x" * 64)
    assert response.status_code == 401


@pytest.mark.parametrize("pieces", [False, True], ids=["declared", "counted"])
def test_an_authenticated_caller_is_not_held_to_the_cap(client: TestClient, pieces: bool) -> None:
    """Refused as a body that is not a document, which it can only be once it has been read."""
    response = client.post(APPLY, content=in_pieces(PAST_THE_CAP) if pieces else PAST_THE_CAP)
    assert response.status_code == 422


def test_a_login_past_its_cap_is_refused_whatever_it_presents(client: TestClient) -> None:
    username = "x" * LOGIN_MAX_BODY
    response = client.post(f"{PREFIX}/auth/login", json={"username": username, "password": "y"})
    assert response.status_code == 413
    assert response.json()["code"] == TOO_LARGE
    assert not LOGIN_BUCKETS.buckets, "nothing was keyed off a body that was refused"


def test_a_long_username_inside_the_cap_is_held_as_a_short_key(anonymous: TestClient) -> None:
    response = anonymous.post(f"{PREFIX}/auth/login", json={"username": "x" * 8192, "password": "y"})
    assert response.status_code == 401
    assert max(len(key) for key in LOGIN_BUCKETS.buckets) < 128


def test_an_ordinary_login_still_works(anonymous: TestClient) -> None:
    response = anonymous.post(f"{PREFIX}/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["code"] == "server.bad_credentials"
