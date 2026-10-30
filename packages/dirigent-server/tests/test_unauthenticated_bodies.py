"""What the versioned API reads from a caller before it knows who the caller is."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from dirigent_core.config import Settings
from dirigent_server import bodies, create_app
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


class Stalled:
    """One request that sends a head and a byte of body, then nothing."""

    def __init__(self) -> None:
        """Start with nothing sent and nothing answered."""
        self.answered: list[Message] = []
        self._started = False

    async def receive(self) -> Message:
        """Hand over the first byte, then wait until cancelled."""
        if not self._started:
            self._started = True
            return {"type": "http.request", "body": b"{", "more_body": True}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(self, message: Message) -> None:
        """Keep what the application answered."""
        self.answered.append(message)

    @property
    def status(self) -> int:
        """The status the application answered with."""
        return int(self.answered[0]["status"])

    @property
    def headers(self) -> dict[bytes, bytes]:
        """The headers the application answered with."""
        return dict(self.answered[0]["headers"])


def _scope(path: str, *extra: tuple[bytes, bytes]) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"), *extra],
        "client": ("203.0.113.9", 4000),
        "server": ("testserver", 80),
    }


@pytest.fixture
async def app(settings: Settings, admin_token: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    monkeypatch.setattr(bodies, "BODY_DEADLINE", timedelta(milliseconds=100))
    built = create_app(settings, scheduler=False)
    async with built.router.lifespan_context(built):
        yield built


@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/login", "/api/v1/pipelines/$apply", "/api/v1/playground/request"],
)
async def test_a_stranger_whose_body_stops_arriving_is_answered_408_and_closed(app: FastAPI, path: str) -> None:
    call = Stalled()
    await asyncio.wait_for(app(_scope(path), call.receive, call.send), timeout=60)
    assert call.status == 408
    assert call.headers[b"connection"] == b"close"
    assert call.headers[b"x-frame-options"] == b"DENY"


async def test_a_forged_credential_gets_no_longer_than_none(app: FastAPI) -> None:
    call = Stalled()
    forged = (b"authorization", b"Bearer not-a-token")
    await asyncio.wait_for(app(_scope("/api/v1/pipelines/$apply", forged), call.receive, call.send), timeout=60)
    assert call.status == 408


async def test_an_authenticated_caller_keeps_sending_past_the_deadline(app: FastAPI, admin_token: str) -> None:
    arrived = asyncio.Event()
    finish = asyncio.Event()
    chunks = [b'{"code": ', b'"demo"}']

    async def receive() -> Message:
        if len(chunks) == 2:
            return {"type": "http.request", "body": chunks.pop(0), "more_body": True}
        arrived.set()
        await finish.wait()
        return {"type": "http.request", "body": chunks.pop(0), "more_body": False}

    answered: list[Message] = []

    async def send(message: Message) -> None:
        answered.append(message)

    credential = (b"authorization", f"Bearer {admin_token}".encode())
    running = asyncio.create_task(app(_scope("/api/v1/connections", credential), receive, send))
    await asyncio.wait_for(arrived.wait(), timeout=60)
    await asyncio.sleep(bodies.BODY_DEADLINE.total_seconds() * 3)
    assert answered == [], "the caller is still sending, and has not been answered"
    finish.set()
    await asyncio.wait_for(running, timeout=60)
    assert int(answered[0]["status"]) == 422
    assert b"kind" in b"".join(message.get("body", b"") for message in answered), "the route read the whole body"


async def test_a_playground_read_has_its_own_deadline_for_an_authenticated_caller(
    app: FastAPI, admin_token: str
) -> None:
    call = Stalled()
    credential = (b"authorization", f"Bearer {admin_token}".encode())
    await asyncio.wait_for(app(_scope("/api/v1/playground/request", credential), call.receive, call.send), timeout=60)
    assert call.status == 408
    assert call.headers[b"connection"] == b"close"
