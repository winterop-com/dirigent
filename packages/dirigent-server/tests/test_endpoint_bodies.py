"""An endpoint reads a body with no database connection held, and gives up on one that stops arriving."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2
import pytest
from fastapi import FastAPI
from starlette.types import Message, Scope

from dirigent_core.config import Settings
from dirigent_core.sources import intake
from dirigent_plugin.sources import sign_body
from dirigent_server import create_app

PREFIX: Final = "/api/v1"


def _document(auth: str) -> dict[str, Any]:
    return {
        "format": "dirigent/v1",
        "code": "stalled",
        "steps": {
            "ask": {"source": {"kind": "endpoint", "path": "/stalled", "auth": {"kind": auth}}},
            "shape": {
                "block": "transform.jq",
                "depends_on": ["ask"],
                "config": {"input": "${steps.ask.output.body}", "program": "."},
            },
        },
    }


class Unfinished:
    """One request that sends a head and a byte of body, then nothing until it is told to finish."""

    def __init__(self) -> None:
        """Start with nothing sent and nothing answered."""
        self.answered: list[Message] = []
        self.stalled = asyncio.Event()
        self.finish = asyncio.Event()
        self._started = False

    async def receive(self) -> Message:
        """Hand over the first byte, then stall until the test finishes the body."""
        if not self._started:
            self._started = True
            return {"type": "http.request", "body": b"{", "more_body": True}
        self.stalled.set()
        await self.finish.wait()
        return {"type": "http.request", "body": b"}", "more_body": False}

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


def _scope(path: str) -> Scope:
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
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"), (b"content-length", b"1000")],
        "client": ("203.0.113.9", 4000),
        "server": ("testserver", 80),
    }


@pytest.fixture
async def app(settings: Settings, admin_token: str) -> AsyncIterator[FastAPI]:
    built = create_app(settings, scheduler=False)
    async with built.router.lifespan_context(built):
        yield built


@pytest.fixture
async def admin(app: FastAPI, admin_token: str) -> AsyncIterator[httpx2.AsyncClient]:
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://testserver", headers=headers
    ) as client:
        yield client


async def _apply(client: httpx2.AsyncClient, auth: str) -> None:
    applied = await client.post(f"{PREFIX}/pipelines/$apply", json={"document": _document(auth), "paused": False})
    assert applied.status_code == 200, applied.text


async def _stall(app: FastAPI) -> tuple[Unfinished, asyncio.Task[None]]:
    """Start one call whose body stops arriving, and return once the route is waiting on it."""
    call = Unfinished()
    task = asyncio.create_task(app(_scope("/endpoints/stalled"), call.receive, call.send))
    await asyncio.wait_for(call.stalled.wait(), timeout=60)
    return call, task


@pytest.mark.parametrize("auth", ["hmac", "public"])
async def test_an_unfinished_body_holds_no_database_connection(
    app: FastAPI, admin: httpx2.AsyncClient, auth: str
) -> None:
    await _apply(admin, auth)
    call, task = await _stall(app)
    try:
        assert app.state.engine.pool.checkedout() == 0
        answered = await admin.get(f"{PREFIX}/pipelines")
        assert answered.status_code == 200, answered.text
    finally:
        call.finish.set()
        await task


async def test_a_call_finishing_its_body_reads_what_changed_while_it_arrived(
    app: FastAPI, admin: httpx2.AsyncClient
) -> None:
    await _apply(admin, "public")
    call, task = await _stall(app)
    try:
        paused = await admin.post(f"{PREFIX}/pipelines/stalled/sources/ask/$pause")
        assert paused.status_code == 200, paused.text
    finally:
        call.finish.set()
        await task
    assert call.status == 503


async def test_a_call_finishing_its_body_is_taken(app: FastAPI, admin: httpx2.AsyncClient) -> None:
    await _apply(admin, "public")
    call, task = await _stall(app)
    call.finish.set()
    await task
    assert call.status == 202


@pytest.mark.parametrize(("auth", "journaled"), [("hmac", 0), ("public", 1)])
async def test_a_body_that_stops_arriving_is_answered_408_and_closes_the_connection(
    settings: Settings, admin_token: str, auth: str, journaled: int
) -> None:
    built = create_app(
        settings.model_copy(update={"source_body_timeout": timedelta(milliseconds=100)}), scheduler=False
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with (
        built.router.lifespan_context(built),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(built), base_url="http://testserver", headers=headers
        ) as client,
    ):
        await _apply(client, auth)
        call = Unfinished()
        await asyncio.wait_for(built(_scope("/endpoints/stalled"), call.receive, call.send), timeout=60)
        assert call.status == 408
        assert call.headers[b"connection"] == b"close"
        inputs = (await client.get(f"{PREFIX}/pipelines/stalled/sources/ask/inputs")).json()["items"]
        assert [row["status"] for row in inputs] == [408] * journaled


#: Far enough from the wall clock that no test here reads it by accident.
SIGNED_AT: Final = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

SECRET: Final = "DUMMY-signing-secret"

#: The whole body an ``Unfinished`` call sends: its first byte, then the rest.
BODY: Final = b"{}"


class HeldClock:
    """A clock a test moves by hand, in place of the one the intake reads."""

    def __init__(self, at: datetime) -> None:
        """Start at a fixed moment."""
        self.at = at

    def __call__(self) -> datetime:
        """Say what time the test has set."""
        return self.at


def _signed_head(at: datetime, body: bytes) -> list[tuple[bytes, bytes]]:
    """Write the headers of one signed call at a moment, over a body."""
    stamp = str(int(at.timestamp()))
    return [
        (b"host", b"testserver"),
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"x-dirigent-timestamp", stamp.encode()),
        (b"x-dirigent-signature", sign_body(SECRET.encode(), stamp, body).encode()),
    ]


async def _signed_call(app: FastAPI, at: datetime, body: bytes) -> int:
    """Send one whole signed call and say how it was answered."""
    answered: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        answered.append(message)

    scope = {**_scope("/endpoints/stalled"), "headers": _signed_head(at, body)}
    await app(scope, receive, send)
    return int(answered[0]["status"])


async def test_a_spent_signature_held_across_the_end_of_its_window_is_refused(
    app: FastAPI, admin: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _apply(admin, "hmac")
    secret = await admin.post(f"{PREFIX}/pipelines/stalled/sources/ask/$set-secret", json={"secret": SECRET})
    assert secret.status_code == 200, secret.text
    clock = HeldClock(SIGNED_AT)
    monkeypatch.setattr(intake, "utcnow", clock)
    window = app.state.services.settings.source_signature_window

    assert await _signed_call(app, SIGNED_AT, BODY) == 202
    assert await _signed_call(app, SIGNED_AT, BODY) == 401

    held = Unfinished()
    scope = {**_scope("/endpoints/stalled"), "headers": _signed_head(SIGNED_AT, BODY)}
    task = asyncio.create_task(app(scope, held.receive, held.send))
    await asyncio.wait_for(held.stalled.wait(), timeout=60)

    clock.at = SIGNED_AT + window + timedelta(hours=1)
    assert await _signed_call(app, clock.at, b'{"another": "call"}') == 202, "this call purges old signatures"

    held.finish.set()
    await task

    assert held.status == 401, "the record of what it copies may be gone, and the clock says it is stale"
    inputs = (await admin.get(f"{PREFIX}/pipelines/stalled/sources/ask/inputs")).json()["items"]
    assert [row["status"] for row in inputs if row["status"] == 202] == [202, 202]


async def test_a_spent_signature_keeps_its_record_past_the_window_for_a_call_that_read_the_clock_inside_it(
    app: FastAPI, admin: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _apply(admin, "hmac")
    secret = await admin.post(f"{PREFIX}/pipelines/stalled/sources/ask/$set-secret", json={"secret": SECRET})
    assert secret.status_code == 200, secret.text
    clock = HeldClock(SIGNED_AT)
    monkeypatch.setattr(intake, "utcnow", clock)
    window = app.state.services.settings.source_signature_window
    assert await _signed_call(app, SIGNED_AT, BODY) == 202

    clock.at = SIGNED_AT + window + timedelta(seconds=1)
    assert await _signed_call(app, clock.at, b'{"another": "call"}') == 202

    clock.at = SIGNED_AT + window
    assert await _signed_call(app, SIGNED_AT, BODY) == 401
