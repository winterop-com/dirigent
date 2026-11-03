"""MCP over Streamable HTTP at ``/mcp``, through the SDK's own client against a server on a socket."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent, Tool

from dirigent_client import UserRole
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_server import create_app
from tests_support import PASSWORD, USERNAME

#: The operator account the conftest makes.
OPERATOR = "an-operator"

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: over-http
steps:
  greet:
    block: value.const
    config:
      value: hello over http
"""

#: An MCP initialize request, as a client opens a session with.
INITIALIZE: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "tests", "version": "0"},
    },
}

#: What a Streamable HTTP client says it accepts.
ACCEPT = {"Accept": "application/json, text/event-stream"}


@asynccontextmanager
async def serving(settings: Settings) -> AsyncGenerator[str]:
    """Serve the application on a loopback port of its own, and answer its base URL."""
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings, scheduler=False), host="127.0.0.1", port=0, log_level="warning")
    )
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
async def base(settings: Settings, admin_token: str) -> AsyncGenerator[str]:
    """The base URL of a running instance."""
    async with serving(settings) as url:
        yield url


@pytest.fixture
def second_operator_token(settings: Settings, operator_token: str) -> str:
    """Another operator's bearer token, whose sessions the same server holds."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with session_scope(create_session_factory(engine)) as session:
                user = await create_user(session, "a-second-operator", PASSWORD, role=UserRole.OPERATOR)
                return (await issue_token(session, user, name="second")).secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


async def opened(http: httpx2.AsyncClient, base: str, token: str) -> httpx2.Response:
    """Ask for a new session with one bearer token."""
    return await http.post(f"{base}/mcp", json=INITIALIZE, headers={**ACCEPT, "Authorization": f"Bearer {token}"})


async def test_one_token_cannot_hold_every_session_its_server_has_room_for(
    settings: Settings, operator_token: str, second_operator_token: str
) -> None:
    capped = settings.model_copy(update={"mcp_max_sessions": 4, "mcp_max_sessions_per_token": 2})
    async with serving(capped) as url, httpx2.AsyncClient(timeout=30) as http:
        kept = [await opened(http, url, operator_token) for _ in range(2)]
        assert [answer.status_code for answer in kept] == [200, 200]
        assert (await opened(http, url, operator_token)).status_code == 503
        assert (await opened(http, url, second_operator_token)).status_code == 200, "another token still gets one"

        ended = await http.delete(
            f"{url}/mcp",
            headers={
                **ACCEPT,
                "Authorization": f"Bearer {operator_token}",
                "Mcp-Session-Id": kept[0].headers["mcp-session-id"],
                "Mcp-Protocol-Version": "2025-06-18",
            },
        )
        assert ended.status_code == 200, ended.text
        assert (await opened(http, url, operator_token)).status_code == 200, "ending a session frees its place"


async def test_an_open_stream_does_not_keep_a_session_past_its_idle_time(settings: Settings, admin_token: str) -> None:
    quick = settings.model_copy(update={"mcp_session_idle": timedelta(milliseconds=300)})
    async with serving(quick) as url, httpx2.AsyncClient(timeout=30) as http:
        session = (await opened(http, url, admin_token)).headers["mcp-session-id"]
        headers = {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {admin_token}",
            "Mcp-Session-Id": session,
            "Mcp-Protocol-Version": "2025-06-18",
        }
        async with http.stream("GET", f"{url}/mcp", headers=headers) as stream:
            assert stream.status_code == 200
            async with asyncio.timeout(10):
                async for _ in stream.aiter_raw():
                    pass

        async def gone() -> bool:
            asked = await http.post(
                f"{url}/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers={**ACCEPT, **headers}
            )
            return asked.status_code == 404

        async with asyncio.timeout(10):
            await asyncio.sleep(0.6)
            while not await gone():
                await asyncio.sleep(0.6)


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


async def test_a_session_initialises_lists_its_tools_and_calls_one(base: str, operator_token: str) -> None:
    async with connected(base, operator_token) as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        assert {"apply_document", "run_pipeline", "list_pipelines", "whoami"} <= tools

        applied = await called(session, "apply_document", document=DOCUMENT)
        assert applied["plan"]["action"] == "create"
        [listed] = (await called(session, "list_pipelines"))["items"]
        assert listed["code"] == "over-http"
        accepted = await called(session, "run_pipeline", code="over-http")
        run = (await called(session, "get_run", run_id=accepted["run_id"]))["run"]
        assert run["triggered_by_label"] == f"{OPERATOR} (token operator-tests)"


async def test_a_viewer_is_offered_only_the_reading_tools(base: str, viewer_token: str, operator_token: str) -> None:
    async with connected(base, operator_token) as session:
        every = {tool.name: tool for tool in (await session.list_tools()).tools}
    async with connected(base, viewer_token) as session:
        offered = {tool.name for tool in (await session.list_tools()).tools}
        reads = {name for name, tool in every.items() if tool.annotations and tool.annotations.read_only_hint}
        assert offered == reads - {"plan_document"}
        assert {"apply_document", "run_pipeline", "cancel_run"}.isdisjoint(offered)
        assert (await called(session, "whoami"))["role"] == "viewer"
        refused = await session.call_tool("apply_document", {"document": DOCUMENT})
        assert refused.is_error


def _filled(tool: Tool) -> dict[str, Any]:
    """The arguments a tool requires, filled with a document or a name no row holds."""
    schema = tool.input_schema
    return {name: DOCUMENT if name == "document" else "absent" for name in schema.get("required", [])}


async def test_no_tool_a_role_is_offered_is_one_the_api_refuses_it(
    base: str, viewer_token: str, operator_token: str, admin_token: str
) -> None:
    for token in (viewer_token, operator_token, admin_token):
        async with connected(base, token) as session:
            for tool in (await session.list_tools()).tools:
                answered = await session.call_tool(tool.name, _filled(tool))
                said = " ".join(block.text for block in answered.content if isinstance(block, TextContent))
                assert "not permitted for your role" not in said, tool.name


async def test_each_role_is_offered_the_tools_of_its_own_reach(
    base: str, viewer_token: str, operator_token: str, admin_token: str
) -> None:
    offered: dict[str, set[str]] = {}
    for role, token in (("viewer", viewer_token), ("operator", operator_token), ("admin", admin_token)):
        async with connected(base, token) as session:
            offered[role] = {tool.name for tool in (await session.list_tools()).tools}
    assert offered["viewer"] < offered["operator"] < offered["admin"]
    assert "plan_document" not in offered["viewer"]
    assert "plan_document" in offered["operator"]
    assert "check_connection" not in offered["operator"]
    assert "create_connection" not in offered["viewer"]
    assert {"create_connection"} <= offered["operator"]
    assert {"check_connection", "create_connection"} <= offered["admin"]


async def test_two_sessions_act_as_their_own_callers(base: str, admin_token: str, operator_token: str) -> None:
    async with connected(base, admin_token) as admin, connected(base, operator_token) as operator:
        assert (await called(admin, "whoami"))["username"] == USERNAME
        assert (await called(operator, "whoami"))["username"] == OPERATOR
        assert (await called(admin, "whoami"))["role"] == "admin"
        assert (await called(operator, "whoami"))["role"] == "operator"


@pytest.mark.parametrize("authorization", [None, "Bearer not-a-token", "Basic YWRtaW46YWRtaW4="])
async def test_a_request_without_a_token_that_resolves_is_answered_401(base: str, authorization: str | None) -> None:
    headers = {**ACCEPT, **({"Authorization": authorization} if authorization else {})}
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{base}/mcp", json=INITIALIZE, headers=headers)
    assert answered.status_code == 401
    assert answered.headers["www-authenticate"] == "Bearer"
    assert answered.json()["code"] == "server.unauthenticated"


async def test_a_session_cookie_does_not_authenticate_mcp(settings: Settings, admin_token: str) -> None:
    with TestClient(create_app(settings, scheduler=False)) as client:
        logged_in = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        assert logged_in.status_code == 200, logged_in.text
        answered = client.post("/mcp", json=INITIALIZE, headers=ACCEPT)
    assert answered.status_code == 401


async def test_a_session_answers_only_the_token_that_opened_it(
    base: str, admin_token: str, operator_token: str
) -> None:
    async with httpx2.AsyncClient() as http:
        opened = await http.post(
            f"{base}/mcp", json=INITIALIZE, headers={**ACCEPT, "Authorization": f"Bearer {admin_token}"}
        )
        assert opened.status_code == 200, opened.text
        session = opened.headers["mcp-session-id"]
        borrowed = await http.post(
            f"{base}/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={**ACCEPT, "Authorization": f"Bearer {operator_token}", "Mcp-Session-Id": session},
        )
    assert borrowed.status_code == 404


@pytest.mark.parametrize(
    "browser",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "http://127.0.0.1:1"},
        {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
async def test_a_request_another_origin_caused_is_refused_403(
    base: str, admin_token: str, browser: dict[str, str]
) -> None:
    headers = {**ACCEPT, **browser, "Authorization": f"Bearer {admin_token}"}
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{base}/mcp", json=INITIALIZE, headers=headers)
    assert answered.status_code == 403
    assert answered.json()["code"] == "server.mcp_cross_origin"


async def test_a_request_from_the_instances_own_origin_is_served(base: str, admin_token: str) -> None:
    headers = {**ACCEPT, "Origin": base, "Authorization": f"Bearer {admin_token}"}
    async with httpx2.AsyncClient() as http:
        answered = await http.post(f"{base}/mcp", json=INITIALIZE, headers=headers)
    assert answered.status_code == 200, answered.text


async def test_an_mcp_message_past_the_cap_is_answered_413(settings: Settings, admin_token: str) -> None:
    capped = settings.model_copy(update={"mcp_max_body": 1024})
    async with serving(capped) as url, httpx2.AsyncClient() as http:
        padded: dict[str, Any] = {**INITIALIZE, "params": {**INITIALIZE["params"], "padding": "x" * 2048}}
        answered = await http.post(
            f"{url}/mcp", json=padded, headers={**ACCEPT, "Authorization": f"Bearer {admin_token}"}
        )
    assert answered.status_code == 413


async def test_a_token_past_its_rate_is_answered_429_and_another_token_is_not(
    settings: Settings, operator_token: str, second_operator_token: str
) -> None:
    limited = settings.model_copy(update={"mcp_rate_per_minute": 2})
    async with serving(limited) as url, httpx2.AsyncClient(timeout=30) as http:
        kept = [await opened(http, url, operator_token) for _ in range(2)]
        assert [answer.status_code for answer in kept] == [200, 200]
        refused = await opened(http, url, operator_token)
        assert refused.status_code == 429
        assert refused.headers["retry-after"] == "30"
        assert refused.json()["code"] == "server.mcp_rate"
        assert refused.json()["params"] == {"per_minute": 2}
        assert (await opened(http, url, second_operator_token)).status_code == 200, "another token has its own count"


def test_an_instance_that_turns_mcp_off_does_not_mount_it(settings: Settings, admin_token: str) -> None:
    off = settings.model_copy(update={"mcp_enabled": False})
    with TestClient(create_app(off, scheduler=False), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        answered = client.post("/mcp", json=INITIALIZE, headers=ACCEPT)
        navigated = client.get("/mcp", headers={"Accept": "text/html"})
    assert answered.status_code in {404, 405}
    assert navigated.status_code == 404


def test_every_mcp_answer_carries_the_security_headers(settings: Settings, admin_token: str) -> None:
    with TestClient(create_app(settings, scheduler=False)) as client:
        answered = client.post("/mcp", json=INITIALIZE, headers=ACCEPT)
    assert answered.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in answered.headers["content-security-policy"]
