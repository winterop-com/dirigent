"""The MCP server's tools against the real application, in this process."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cryptography.fernet import Fernet
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr

from dirigent_client import Dirigent
from dirigent_client.enums import UserRole
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_mcp import server as mcp_server
from dirigent_server import create_app

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: mcp-demo
steps:
  greet:
    block: value.const
    config:
      value: hello from an agent
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance pointed at a throwaway database, artifact root, and secret key."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )


@pytest.fixture
def token(settings: Settings) -> str:
    """Create the schema and one operator account, and return a bearer token for it."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with session_scope(create_session_factory(engine)) as session:
                user = await create_user(session, "agent", "an agent password", role=UserRole.OPERATOR)
                issued = await issue_token(session, user, name="mcp-tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
async def server(settings: Settings, token: str) -> AsyncIterator[MCPServer]:
    """The MCP server, its client reaching the real application without a socket in between."""
    app = create_app(settings, scheduler=False)
    async with (
        httpx2.ASGITransport(app) as transport,
        app.router.lifespan_context(app),
        Dirigent(url="http://testserver", token=token, http_transport=transport) as client,
    ):
        yield mcp_server.build(lambda: client)


async def call(server: MCPServer, tool: str, **arguments: Any) -> Any:
    """Call a tool and read back the JSON it answered with."""
    result = await server.call_tool(tool, arguments)
    assert isinstance(result, CallToolResult), "no tool here asks the agent for more input"
    assert not result.is_error, result.content
    [text] = [block.text for block in result.content if isinstance(block, TextContent)]
    return json.loads(text)


async def test_every_tool_says_whether_it_writes(server: MCPServer) -> None:
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert {"plan_document", "apply_document", "run_pipeline", "get_run", "run_logs", "get_block"} <= set(tools)
    assert not {name for name in tools if name.startswith("delete")}, "nothing an agent calls deletes"
    reads = {name for name, tool in tools.items() if tool.annotations and tool.annotations.read_only_hint}
    assert {"list_pipelines", "get_run", "plan_document", "get_block"} <= reads
    assert not {"apply_document", "run_pipeline", "cancel_run"} & reads


async def test_a_document_is_planned_applied_and_run(server: MCPServer) -> None:
    planned = await call(server, "plan_document", document=DOCUMENT)
    assert (planned["plan"]["action"], planned["dry_run"]) == ("create", True)
    assert (await call(server, "list_pipelines"))["items"] == []

    applied = await call(server, "apply_document", document=DOCUMENT)
    assert applied["plan"]["action"] == "create"
    [listed] = (await call(server, "list_pipelines"))["items"]
    assert listed["code"] == "mcp-demo"
    assert (await call(server, "validate_pipeline", code="mcp-demo")) == {"issues": []}

    accepted = await call(server, "run_pipeline", code="mcp-demo")
    run = await call(server, "get_run", run_id=accepted["run_id"])
    assert run["run"]["id"] == accepted["run_id"]
    assert [row["id"] for row in (await call(server, "list_runs", pipeline="mcp-demo"))["items"]] == [
        accepted["run_id"]
    ]


async def test_a_refusal_reaches_the_agent_as_a_tool_error(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="nobody"):
        await server.call_tool("get_pipeline", {"code": "nobody"})


async def test_the_catalog_is_listed_short_and_read_whole(server: MCPServer) -> None:
    listed = (await call(server, "list_blocks"))["blocks"]
    const = next(entry for entry in listed if entry["id"] == "value.const")
    assert set(const) == {"id", "kind", "group", "summary"}
    block = await call(server, "get_block", block_id="value.const")
    assert "properties" in block["config_schema"]


def test_the_server_refuses_to_start_without_an_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(mcp_server.URL_ENV, raising=False)
    with pytest.raises(SystemExit) as stopped:
        mcp_server.main()
    assert stopped.value.code == 2
