"""A lone surrogate an outside service answers with is stored as text, and the run stays readable."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx2
import pytest
from fastapi import FastAPI

from dirigent_core.config import Settings
from dirigent_core.engine.executor import Engine
from dirigent_server import create_app

PREFIX: Final = "/api/v1"

#: JSON a parser takes and no database driver can encode, beside a pair that is one real character.
LONE_AND_PAIRED: Final = b'{"lone": "before \\udc80 after", "pair": "\\ud83d\\ude00"}'


def _document(url: str) -> dict[str, Any]:
    return {
        "format": "dirigent/v1",
        "code": "fetching",
        "steps": {
            "fetch": {"block": "http.request", "config": {"url": url}},
            "shape": {
                "block": "transform.jq",
                "depends_on": ["fetch"],
                "config": {"input": "${steps.fetch.output.body}", "program": ".lone"},
            },
        },
    }


async def _serve(body: bytes) -> asyncio.Server:
    """Answer every connection with one JSON response holding exactly these bytes."""

    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        head = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        writer.write(head.encode() + b"Connection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    return await asyncio.start_server(answer, "127.0.0.1", 0)


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


async def _run_to_its_end(app: FastAPI, admin: httpx2.AsyncClient, body: bytes) -> str:
    server = await _serve(body)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/answer"
    try:
        applied = await admin.post(f"{PREFIX}/pipelines/$apply", json={"document": _document(url), "paused": False})
        assert applied.status_code == 200, applied.text
        started = await admin.post(f"{PREFIX}/pipelines/fetching/$run", json={"params": {}})
        assert started.status_code == 202, started.text
        engine = Engine(app.state.session_factory, app.state.services, owner="worker")
        while unit := await engine.claim():
            await engine.run_unit(unit)
    finally:
        server.close()
    return str(started.json()["run_id"])


async def test_a_run_holding_a_lone_surrogate_from_a_service_stays_readable(
    app: FastAPI, admin: httpx2.AsyncClient
) -> None:
    run_id = await _run_to_its_end(app, admin, LONE_AND_PAIRED)

    attempts = await admin.get(f"{PREFIX}/runs/{run_id}/attempts")
    assert attempts.status_code == 200, attempts.text
    rows = {row["step_name"]: row for row in attempts.json()["items"]}
    assert rows["fetch"]["status"] == "succeeded"
    assert rows["fetch"]["attempt"] == 1
    assert rows["fetch"]["output"]["body"]["lone"] == "before \\udc80 after"
    assert rows["fetch"]["output"]["body"]["pair"] == "\U0001f600"
    assert rows["shape"]["status"] == "succeeded"
    assert rows["shape"]["output"]["value"] == "before \\udc80 after"

    for path in (f"{PREFIX}/runs/{run_id}", f"{PREFIX}/runs/{run_id}/$report", f"{PREFIX}/runs/{run_id}/$logs"):
        answered = await admin.get(path)
        assert answered.status_code == 200, f"{path}: {answered.text}"


async def test_an_output_too_large_to_keep_inline_with_a_lone_surrogate_stays_readable(
    app: FastAPI, admin: httpx2.AsyncClient, settings: Settings
) -> None:
    filler = "x" * (int(settings.inline_artifact_max) + 1)
    body = b'{"lone": "before \\udc80 after", "filler": "' + filler.encode() + b'"}'
    run_id = await _run_to_its_end(app, admin, body)

    attempts = await admin.get(f"{PREFIX}/runs/{run_id}/attempts")
    assert attempts.status_code == 200, attempts.text
    rows = {row["step_name"]: row for row in attempts.json()["items"]}
    assert rows["fetch"]["status"] == "succeeded"
    assert rows["shape"]["output"]["value"] == "before \\udc80 after"
