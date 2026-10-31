"""An open log tail or event stream answers to the credential it was opened with, on every poll."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI
from starlette.types import Message

from dirigent_core.config import Settings
from dirigent_core.models import LogEntry
from dirigent_server import create_app

PREFIX: Final = "/api/v1"

#: The account the viewer_token fixture creates.
VIEWER: Final = "a-viewer"

#: Long past the slowest a quiet stream polls, for a stream that never ends to fail rather than hang.
STREAM_PATIENCE_SECONDS: Final = 60.0

DOCUMENT: Final = {
    "format": "dirigent/v1",
    "code": "watched",
    "steps": {"only": {"block": "log.write", "config": {"message": "never runs: no worker is started"}}},
}


class OpenStream:
    """One streaming request held open, and everything it has sent so far."""

    def __init__(self, app: FastAPI, path: str, query: bytes, token: str) -> None:
        """Send the request straight into the application, which answers until the stream ends."""
        self.frames: asyncio.Queue[Message] = asyncio.Queue()
        self.seen = ""
        self.ended = False
        self.asked = False
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": query,
            "headers": [(b"host", b"testserver"), (b"authorization", f"Bearer {token}".encode())],
            "client": ("203.0.113.9", 4000),
            "server": ("testserver", 80),
        }
        self.task = asyncio.create_task(app(scope, self._receive, self.frames.put))

    async def _receive(self) -> Message:
        """Hand over the empty body once: a client watching a stream sends nothing more until it leaves."""
        if not self.asked:
            self.asked = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def read_until(self, text: str) -> str:
        """Read frames until one holds a text or the stream ends, and hand back what was seen."""
        async with asyncio.timeout(STREAM_PATIENCE_SECONDS):
            while text not in self.seen and not self.ended:
                frame = await self.frames.get()
                if frame["type"] == "http.response.start":
                    assert frame["status"] == 200, frame
                    continue
                self.seen += frame.get("body", b"").decode()
                self.ended = not frame.get("more_body", False)
        return self.seen

    async def close(self) -> None:
        """Stop the request, wherever it has got to."""
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


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


async def _run_with_no_worker(admin: httpx2.AsyncClient) -> str:
    applied = await admin.post(f"{PREFIX}/pipelines/$apply", json={"document": DOCUMENT, "paused": False})
    assert applied.status_code == 200, applied.text
    started = await admin.post(f"{PREFIX}/pipelines/watched/$run", json={"params": {}})
    assert started.status_code == 202, started.text
    return str(started.json()["run_id"])


async def _write_line(app: FastAPI, run_id: str, message: str) -> None:
    async with app.state.session_factory() as session:
        session.add(LogEntry(run_id=UUID(run_id), message=message))
        await session.commit()


async def _revoke(admin: httpx2.AsyncClient, viewer_token: str) -> None:
    tokens = await admin.get(f"{PREFIX}/users/{VIEWER}/tokens")
    assert tokens.status_code == 200, tokens.text
    revoked = await admin.delete(f"{PREFIX}/tokens/{tokens.json()['items'][0]['id']}")
    assert revoked.status_code == 204, revoked.text
    stale = await admin.get(f"{PREFIX}/auth/me", headers={"Authorization": f"Bearer {viewer_token}"})
    assert stale.status_code == 401, stale.text


async def _deactivate(admin: httpx2.AsyncClient, viewer_token: str) -> None:
    deactivated = await admin.post(f"{PREFIX}/users/{VIEWER}/$deactivate")
    assert deactivated.status_code == 200, deactivated.text


@pytest.mark.parametrize("end_it", [_revoke, _deactivate], ids=["token-revoked", "account-deactivated"])
@pytest.mark.parametrize(
    ("route", "query"), [("$logs", b"follow=sse"), ("$events", b"")], ids=["log-tail", "event-stream"]
)
async def test_a_stream_ends_at_its_credential_and_delivers_nothing_written_after(
    app: FastAPI, admin: httpx2.AsyncClient, viewer_token: str, end_it: Any, route: str, query: bytes
) -> None:
    run_id = await _run_with_no_worker(admin)
    stream = OpenStream(app, f"{PREFIX}/runs/{run_id}/{route}", query, viewer_token)
    try:
        await _write_line(app, run_id, "written-while-allowed")
        assert "written-while-allowed" in await stream.read_until("written-while-allowed")

        await end_it(admin, viewer_token)
        await _write_line(app, run_id, "written-after-the-end")

        seen = await stream.read_until("written-after-the-end")
        assert "written-after-the-end" not in seen
        assert stream.ended
        assert "event: expired" in seen
    finally:
        await stream.close()


async def test_a_stream_whose_credential_stands_keeps_going(
    app: FastAPI, admin: httpx2.AsyncClient, viewer_token: str
) -> None:
    run_id = await _run_with_no_worker(admin)
    stream = OpenStream(app, f"{PREFIX}/runs/{run_id}/$logs", b"follow=sse", viewer_token)
    try:
        await _write_line(app, run_id, "first")
        assert "first" in await stream.read_until("first")
        await _write_line(app, run_id, "second")
        assert "second" in await stream.read_until("second")
        assert not stream.ended
    finally:
        await stream.close()
