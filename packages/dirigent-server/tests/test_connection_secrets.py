"""A connection named by a step or a source of another kind is refused, and no failure carries its secret."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx2
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from dirigent_core.alerting import NotificationDispatcher
from dirigent_core.config import Settings
from dirigent_core.engine.executor import Engine
from dirigent_core.models import Connection
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


#: A dummy token, and what a paste or a file read makes of it.
MALFORMED: Final = {
    "trailing-blank": "DUMMY-header-canary-0003 ",
    "trailing-newline": "DUMMY-header-canary-0003\n",
    "trailing-crlf": "DUMMY-header-canary-0003\r\n",
    "embedded-newline": "DUMMY-header\n-canary-0003",
}

#: Long enough that a detail cut before scrubbing would still hold most of it.
LONG: Final = "DUMMY-header-canary-0003" * 200 + " "


def _holds(text: str, token: str) -> bool:
    """Say whether any spelling of a token, or a good stretch of it, is in a text."""
    trimmed = token.strip()
    escaped = repr(trimmed)[1:-1]
    return any(part in text for part in (trimmed, escaped, trimmed[:24], trimmed[-24:]))


@pytest.fixture
async def listener() -> AsyncIterator[str]:
    """A server that accepts a connection and closes it, since a header is refused after connecting."""

    async def close(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    server = await asyncio.start_server(close, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()


async def _already_stored(app: FastAPI, code: str, token: str) -> None:
    """Put a token straight on the row, the way one sealed before the refusal stayed there."""
    services = app.state.services
    async with app.state.session_factory() as session:
        await session.execute(
            sa.update(Connection)
            .where(Connection.code == code)
            .values(
                secret_envelope=services.secrets.seal({"bearer_token": token}), secret_key_id=services.secrets.key_id
            )
        )
        await session.commit()


@pytest.mark.parametrize("token", MALFORMED.values(), ids=MALFORMED.keys())
@pytest.mark.parametrize(
    ("kind", "config"),
    [("http", {"base_url": "https://svc.invalid"}), ("webhook", {"url": "https://svc.invalid/hook"})],
    ids=["http", "webhook"],
)
async def test_a_token_no_header_can_carry_is_refused_when_it_is_stored(
    admin: httpx2.AsyncClient, kind: str, config: dict[str, Any], token: str
) -> None:
    created = await admin.post(
        f"{PREFIX}/connections", json={"code": "bad", "kind": kind, "config": {**config, "bearer_token": token}}
    )
    assert created.status_code == 422, created.text
    assert created.json()["code"] == "secret.not_sendable"
    assert not _holds(created.text, token)

    assert (
        await admin.post(
            f"{PREFIX}/connections", json={"code": "bad", "kind": kind, "config": {**config, "bearer_token": "clean"}}
        )
    ).status_code == 201
    patched = await admin.patch(f"{PREFIX}/connections/bad", json={"config": {**config, "bearer_token": token}})
    assert patched.status_code == 422, patched.text
    assert patched.json()["code"] == "secret.not_sendable"


@pytest.mark.parametrize("token", [" DUMMY-leading-blank-is-a-paste", "DUMMY\x7fcontrol"], ids=["leading", "delete"])
async def test_the_refusal_holds_for_a_blank_in_front_and_any_control_character(
    admin: httpx2.AsyncClient, token: str
) -> None:
    created = await admin.post(
        f"{PREFIX}/connections",
        json={"code": "bad", "kind": "http", "config": {"base_url": "https://svc.invalid", "bearer_token": token}},
    )
    assert created.status_code == 422, created.text


@pytest.mark.parametrize("token", [*MALFORMED.values(), LONG], ids=[*MALFORMED.keys(), "long"])
async def test_a_stored_token_no_header_can_carry_reaches_no_check_detail(
    app: FastAPI, admin: httpx2.AsyncClient, listener: str, token: str
) -> None:
    created = await admin.post(
        f"{PREFIX}/connections",
        json={"code": "stored", "kind": "http", "config": {"base_url": listener, "bearer_token": "clean"}},
    )
    assert created.status_code == 201, created.text
    await _already_stored(app, "stored", token)
    report = await admin.post(f"{PREFIX}/connections/stored/$check")
    assert report.status_code == 200, report.text
    assert report.json()["healthy"] is False
    assert not _holds(report.text, token)
    assert not _holds((await admin.get(f"{PREFIX}/connections/stored")).text, token)
    assert not _holds((await admin.get(f"{PREFIX}/system/info")).text, token)


@pytest.mark.parametrize("token", [*MALFORMED.values(), LONG], ids=[*MALFORMED.keys(), "long"])
async def test_a_stored_token_no_header_can_carry_reaches_no_delivery_error(
    app: FastAPI, admin: httpx2.AsyncClient, listener: str, token: str
) -> None:
    created = await admin.post(
        f"{PREFIX}/connections",
        json={"code": "hook", "kind": "webhook", "config": {"url": f"{listener}/h", "bearer_token": "clean"}},
    )
    assert created.status_code == 201, created.text
    await _already_stored(app, "hook", token)
    tested = await admin.post(f"{PREFIX}/alert-rules/$test", json={"connection": "hook", "subject": "s", "body": "b"})
    assert tested.status_code == 202, tested.text
    dispatcher = NotificationDispatcher(sessions=app.state.session_factory, services=app.state.services, owner="w")
    await dispatcher.drain()
    notifications = await admin.get(f"{PREFIX}/notifications")
    assert notifications.json()["items"][0]["error"], notifications.text
    assert "***" in notifications.json()["items"][0]["error"]
    assert not _holds(notifications.text, token)


@pytest.mark.parametrize("token", [*MALFORMED.values(), LONG], ids=[*MALFORMED.keys(), "long"])
async def test_a_stored_token_no_header_can_carry_reaches_no_failure_log_or_report(
    app: FastAPI, admin: httpx2.AsyncClient, listener: str, token: str
) -> None:
    created = await admin.post(
        f"{PREFIX}/connections",
        json={"code": "svc", "kind": "http", "config": {"base_url": listener, "bearer_token": "clean"}},
    )
    assert created.status_code == 201, created.text
    await _already_stored(app, "svc", token)
    document = {
        "format": "dirigent/v1",
        "code": "calling",
        "steps": {"call": {"block": "http.request", "config": {"connection": "svc", "path": "/"}}},
    }
    await _apply(admin, document)
    run_id = (await admin.post(f"{PREFIX}/pipelines/calling/$run", json={"params": {}})).json()["run_id"]
    engine = Engine(app.state.session_factory, app.state.services, owner="worker")
    while unit := await engine.claim():
        await engine.run_unit(unit)
    attempts = await admin.get(f"{PREFIX}/runs/{run_id}/attempts")
    assert attempts.json()["items"][0]["status"] == "failed", attempts.text
    assert "***" in attempts.text
    assert not _holds(attempts.text, token)
    assert not _holds((await admin.get(f"{PREFIX}/runs/{run_id}/$logs")).text, token)
    assert not _holds((await admin.get(f"{PREFIX}/runs/{run_id}/$report")).text, token)
