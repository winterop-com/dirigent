"""An endpoint reads a body with no database connection held, and gives up on one that stops arriving."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Final

import httpx2
import pytest
from fastapi import FastAPI
from starlette.types import Message, Scope

from dirigent_core.config import Settings
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
