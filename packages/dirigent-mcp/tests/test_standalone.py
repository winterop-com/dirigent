"""The standalone HTTP server in front of a real instance, both on loopback sockets, through the SDK's client."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
import uvicorn
from cryptography.fernet import Fernet
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dirigent_client.enums import UserRole
from dirigent_common.hosts import is_loopback_host
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_mcp import server as mcp_server
from dirigent_mcp.standalone import LoopbackHostsOnly, _host_name, standalone_app  # pyright: ignore[reportPrivateUsage]
from dirigent_server import create_app

INITIALIZE: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "tests", "version": "0"}},
}

ACCEPT = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance pointed at a throwaway database, artifact root, and secret key."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )


@pytest.fixture
def tokens(settings: Settings) -> dict[UserRole, str]:
    """Create the schema and one account of each role, and return a bearer token for each."""

    async def prepare() -> dict[UserRole, str]:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            issued: dict[UserRole, str] = {}
            async with session_scope(create_session_factory(engine)) as session:
                for role in UserRole:
                    user = await create_user(session, role.value, "an agent password", role=role)
                    issued[role] = (
                        await issue_token(session, user, name=f"{role.value}-mcp")
                    ).secret.get_secret_value()
            return issued
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@asynccontextmanager
async def serving(app: ASGIApp) -> AsyncGenerator[str]:
    """Serve an application on a loopback port of its own, and answer its base URL."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def instance(settings: Settings, tokens: dict[UserRole, str]) -> AsyncGenerator[str]:
    """The base URL of a running instance."""
    async with serving(create_app(settings, scheduler=False)) as url:
        yield url


@pytest.fixture
async def standalone(instance: str) -> AsyncGenerator[str]:
    """The base URL of the standalone MCP server in front of that instance."""
    async with serving(standalone_app(instance, loopback=True)) as url:
        yield url


@asynccontextmanager
async def connected(base: str, token: str) -> AsyncGenerator[ClientSession]:
    """An initialised MCP session at ``/mcp``, presenting one bearer token."""
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as http,
        streamable_http_client(f"{base}/mcp", http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def called(session: ClientSession, tool: str, **arguments: Any) -> Any:
    """Call a tool and read back the JSON it answered with."""
    result = await session.call_tool(tool, arguments)
    assert isinstance(result, CallToolResult)
    assert not result.is_error, result.content
    [text] = [block.text for block in result.content if isinstance(block, TextContent)]
    return json.loads(text)


async def test_each_caller_acts_as_its_own_token(standalone: str, tokens: dict[UserRole, str]) -> None:
    async with (
        connected(standalone, tokens[UserRole.OPERATOR]) as operator,
        connected(standalone, tokens[UserRole.VIEWER]) as viewer,
    ):
        assert (await called(operator, "whoami"))["role"] == "operator"
        assert (await called(viewer, "whoami"))["role"] == "viewer"
        operating = {tool.name for tool in (await operator.list_tools()).tools}
        reading = {tool.name for tool in (await viewer.list_tools()).tools}
        assert {"apply_document", "run_pipeline"} <= operating
        assert reading < operating
        assert {"apply_document", "run_pipeline"}.isdisjoint(reading)


async def test_the_environments_token_is_never_used_for_an_http_caller(
    standalone: str, tokens: dict[UserRole, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(mcp_server.TOKEN_ENV, tokens[UserRole.ADMIN])
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{standalone}/mcp", json=INITIALIZE, headers=ACCEPT)
    assert answered.status_code == 401
    assert answered.json()["code"] == "mcp.unauthenticated"


@pytest.mark.parametrize("authorization", [None, "Bearer not-a-token"])
async def test_a_token_the_instance_refuses_is_answered_401(standalone: str, authorization: str | None) -> None:
    headers = {**ACCEPT, **({"Authorization": authorization} if authorization else {})}
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{standalone}/mcp", json=INITIALIZE, headers=headers)
    assert answered.status_code == 401
    assert answered.headers["www-authenticate"] == "Bearer"


async def test_a_request_another_origin_caused_is_refused_403(standalone: str, tokens: dict[UserRole, str]) -> None:
    headers = {**ACCEPT, "Origin": "https://evil.example", "Authorization": f"Bearer {tokens[UserRole.ADMIN]}"}
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{standalone}/mcp", json=INITIALIZE, headers=headers)
    assert answered.status_code == 403
    assert answered.json()["code"] == "mcp.cross_origin"


@pytest.mark.parametrize(
    "answer",
    [
        PlainTextResponse("no", status_code=500),
        PlainTextResponse("no", status_code=503),
        PlainTextResponse("not a dirigent", status_code=200),
        RedirectResponse("http://elsewhere.example/", status_code=302),
    ],
    ids=["500", "503", "not-dirigent", "redirect"],
)
async def test_an_instance_that_cannot_say_whose_a_token_is_is_answered_502(answer: Response) -> None:
    async def me(_: Request) -> Response:
        return answer

    failing = Starlette(routes=[Route("/api/v1/auth/me", me)])
    async with (
        serving(failing) as url,
        serving(standalone_app(url, loopback=True)) as base,
        httpx2.AsyncClient(timeout=60) as http,
    ):
        answered = await http.post(
            f"{base}/mcp", json=INITIALIZE, headers={**ACCEPT, "Authorization": "Bearer a-token"}
        )
    assert answered.status_code == 502, answered.text
    assert answered.json()["code"] == "mcp.instance_unavailable"


async def test_an_instance_that_is_not_there_is_answered_502() -> None:
    async with (
        serving(standalone_app("http://127.0.0.1:1", loopback=True)) as base,
        httpx2.AsyncClient(timeout=60) as http,
    ):
        answered = await http.post(
            f"{base}/mcp", json=INITIALIZE, headers={**ACCEPT, "Authorization": "Bearer a-token"}
        )
    assert answered.status_code == 502, answered.text


@pytest.mark.parametrize("host", ["localhost", "localhost:3334", "127.0.0.1:1", "[::1]", "[::1]:3334", "LOCALHOST:1"])
def test_a_loopback_authority_reads_as_loopback(host: str) -> None:
    assert is_loopback_host(_host_name(host.lower()))


async def test_a_request_with_no_host_is_refused() -> None:
    answers: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("a request naming no host never reaches the server")

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        answers.append(message)

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    await LoopbackHostsOnly(app)(scope, receive, send)
    assert answers[0]["status"] == 421


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:3334",
        "10.0.0.1",
        "localhost:evil",
        "localhost:3334:1",
        "[::1]evil.example",
        "[::1]:evil",
        "[::1",
    ],
)
async def test_a_loopback_bind_answers_only_a_loopback_host(
    standalone: str, tokens: dict[UserRole, str], host: str
) -> None:
    headers = {**ACCEPT, "Host": host, "Authorization": f"Bearer {tokens[UserRole.ADMIN]}"}
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{standalone}/mcp", json=INITIALIZE, headers=headers)
    assert answered.status_code == 421
    assert answered.json()["code"] == "mcp.host_not_loopback"


def test_http_refuses_an_address_other_machines_reach_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mcp_server.URL_ENV, "http://127.0.0.1:1")
    with pytest.raises(SystemExit) as stopped:
        mcp_server.main(["--transport", "http", "--host", "0.0.0.0"])  # noqa: S104 - refused before any bind
    assert stopped.value.code == 2


def test_http_refuses_to_start_without_an_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(mcp_server.URL_ENV, raising=False)
    with pytest.raises(SystemExit) as stopped:
        mcp_server.main(["--transport", "http"])
    assert stopped.value.code == 2
