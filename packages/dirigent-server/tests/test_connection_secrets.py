"""A connection named by a step or a source of another kind is refused, and no failure carries its secret."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx2
import pytest
from fastapi import FastAPI

from dirigent_core.config import Settings
from dirigent_core.engine.executor import Engine
from dirigent_core.sources import polling
from dirigent_core.sources.holding import Holder
from dirigent_server import create_app

PREFIX: Final = "/api/v1"

BEARER: Final = "DUMMY-bearer-canary-0001"
PASSWORD: Final = "DUMMY-sql-canary-0002"


def _carries_a_secret(text: str) -> bool:
    return BEARER in text or PASSWORD in text


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
        for code, kind, config in (
            ("web", "http", {"base_url": "https://svc.invalid", "bearer_token": BEARER}),
            ("db", "sql", {"url": "postgresql+asyncpg://u@db.invalid/d", "password": PASSWORD}),
        ):
            created = await client.post(f"{PREFIX}/connections", json={"code": code, "kind": kind, "config": config})
            assert created.status_code == 201, created.text
        yield client


async def _run_one_step(app: FastAPI, client: httpx2.AsyncClient, code: str, step: dict[str, Any]) -> dict[str, Any]:
    """Run one document of a single step on the engine, and return its attempt."""
    document = {"format": "dirigent/v1", "code": code, "steps": {"only": step}}
    applied = await client.post(f"{PREFIX}/pipelines/$apply", json={"document": document, "paused": False})
    assert applied.status_code == 200, applied.text
    run_id = (await client.post(f"{PREFIX}/pipelines/{code}/$run", json={"params": {}})).json()["run_id"]
    engine = Engine(app.state.session_factory, app.state.services, owner="worker")
    while unit := await engine.claim():
        await engine.run_unit(unit)
    attempts = await client.get(f"{PREFIX}/runs/{run_id}/attempts")
    logs = await client.get(f"{PREFIX}/runs/{run_id}/$logs")
    assert not _carries_a_secret(attempts.text)
    assert not _carries_a_secret(logs.text)
    attempt: dict[str, Any] = attempts.json()["items"][0]
    return attempt


async def test_a_step_naming_another_kind_is_refused_without_its_secret(
    app: FastAPI, admin: httpx2.AsyncClient
) -> None:
    attempt = await _run_one_step(
        app, admin, "wrong-sql", {"block": "sql.query", "config": {"connection": "web", "sql": "select 1"}}
    )
    assert attempt["status"] == "failed"
    assert attempt["error_code"] == "run.connection_wrong_kind"
    assert attempt["error_params"] == {"ref": "'web'", "kind": "'http'", "wanted": "'sql'"}


async def test_signing_with_another_kind_is_refused_without_its_secret(app: FastAPI, admin: httpx2.AsyncClient) -> None:
    attempt = await _run_one_step(
        app,
        admin,
        "wrong-sign",
        {"block": "webhook.post", "config": {"url": "http://127.0.0.1:9/x", "body": {}, "sign_with": "db"}},
    )
    assert attempt["error_code"] == "run.connection_wrong_kind"
    assert attempt["error_params"] == {"ref": "'db'", "kind": "'sql'", "wanted": "'http'"}


def _sourced(code: str, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "dirigent/v1",
        "code": code,
        "steps": {
            "tail": {"source": source},
            "after": {"block": "log.write", "depends_on": ["tail"], "config": {"message": "x"}},
        },
    }


async def _apply(client: httpx2.AsyncClient, document: dict[str, Any]) -> None:
    applied = await client.post(f"{PREFIX}/pipelines/$apply", json={"document": document, "paused": False})
    assert applied.status_code == 200, applied.text


async def _last_error(client: httpx2.AsyncClient, code: str) -> str:
    source = await client.get(f"{PREFIX}/pipelines/{code}/sources/tail")
    last_error: str = source.json()["last_error"]
    return last_error


async def test_a_polled_source_naming_another_kind_keeps_the_secret_out_of_its_error_and_the_log(
    app: FastAPI, admin: httpx2.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    await _apply(
        admin,
        _sourced(
            "polled",
            {
                "kind": "sensor",
                "block": "kafka.consume",
                "poll": "1h",
                "config": {"connection": "web", "topic": "t", "group_id": "g"},
            },
        ),
    )

    await polling.tick(app.state.session_factory, app.state.services, owner="worker")

    last_error = await _last_error(admin, "polled")
    assert "connection 'web' has kind 'http'" in last_error
    assert not _carries_a_secret(last_error)
    assert not _carries_a_secret("".join(capfd.readouterr()))


async def test_a_held_source_naming_another_kind_keeps_the_secret_out_of_its_error_and_the_log(
    app: FastAPI, admin: httpx2.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    await _apply(admin, _sourced("held", {"kind": "kafka", "connection": "web", "topic": "t", "group_id": "g"}))

    holder = Holder(app.state.session_factory, app.state.services, owner="worker")
    await holder.tick()
    await asyncio.sleep(0.3)
    await holder.stop()

    last_error = await _last_error(admin, "held")
    assert "connection 'web' has kind 'http'" in last_error
    assert not _carries_a_secret(last_error)
    assert not _carries_a_secret("".join(capfd.readouterr()))
