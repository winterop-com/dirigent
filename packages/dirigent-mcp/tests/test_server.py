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


async def test_only_applying_and_stopping_are_marked_destructive(server: MCPServer) -> None:
    tools = {tool.name: tool for tool in await server.list_tools()}
    destructive = {name for name, tool in tools.items() if tool.annotations and tool.annotations.destructive_hint}
    assert "apply_document" in destructive
    assert "run_pipeline" not in destructive
    assert "plan_document" not in destructive


WITH_A_SOURCE = """
format: dirigent/v1
kind: pipeline
code: mcp-sourced
steps:
  ask:
    source:
      kind: endpoint
      path: /mcp-sourced
  greet:
    block: value.const
    depends_on: [ask]
    config:
      value: hello
"""

WITH_A_SCHEDULE = """
format: dirigent/v1
kind: pipeline
code: mcp-clocked
triggers:
  schedules:
    - code: nightly
      cron: "0 5 * * *"
steps:
  greet:
    block: value.const
    config:
      value: hello
"""

BARE = """
format: dirigent/v1
kind: pipeline
code: {code}
steps:
  greet:
    block: value.const
    config:
      value: hello
"""


async def test_a_plan_names_the_source_applying_would_retire_and_retires_nothing(server: MCPServer) -> None:
    await call(server, "apply_document", document=WITH_A_SOURCE)
    bare = BARE.format(code="mcp-sourced")

    planned = await call(server, "plan_document", document=bare)
    assert (planned["dry_run"], planned["sources"]["removed"]) == (True, ["ask"])
    assert (await call(server, "plan_document", document=WITH_A_SOURCE))["sources"]["removed"] == [], (
        "it is still there"
    )

    assert (await call(server, "apply_document", document=bare))["sources"]["removed"] == ["ask"]


async def test_a_plan_names_the_schedule_applying_would_retire_and_retires_nothing(server: MCPServer) -> None:
    await call(server, "apply_document", document=WITH_A_SCHEDULE)
    bare = BARE.format(code="mcp-clocked")

    planned = await call(server, "plan_document", document=bare)
    assert (planned["dry_run"], planned["triggers"]["schedules_removed"]) == (True, ["nightly"])
    unchanged = await call(server, "plan_document", document=WITH_A_SCHEDULE)
    assert unchanged["triggers"]["schedules_removed"] == [], "it is still there"

    assert (await call(server, "apply_document", document=bare))["triggers"]["schedules_removed"] == ["nightly"]


async def test_a_read_only_server_offers_only_the_tools_that_read(server: MCPServer) -> None:
    every = {tool.name: tool for tool in await server.list_tools()}
    reading = mcp_server.build(lambda: pytest.fail("listing tools opens no client"), read_only=True)
    offered = {tool.name for tool in await reading.list_tools()}
    assert offered == {name for name, tool in every.items() if tool.annotations and tool.annotations.read_only_hint}
    assert {"apply_document", "run_pipeline", "cancel_run", "pause_source"}.isdisjoint(offered)


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


@pytest.mark.parametrize("code", ["mcp-demo/$deactivate#", "x/../mcp-demo/$deactivate#"])
async def test_a_reading_tool_cannot_be_steered_to_another_route_by_its_argument(server: MCPServer, code: str) -> None:
    await call(server, "apply_document", document=DOCUMENT)

    with pytest.raises(ToolError, match="not an identifier"):
        await server.call_tool("validate_pipeline", {"code": code})

    assert (await call(server, "get_pipeline", code="mcp-demo"))["active"] is True


@pytest.mark.parametrize("tool", ["plan_document", "apply_document"])
@pytest.mark.parametrize("contents", ["[default]\nkey = DUMMYKEY\n", '{"format": "dirigent/v1", "DUMMYKEY": 1}'])
async def test_a_document_argument_naming_a_local_file_is_text_and_the_file_is_never_read(
    server: MCPServer, tmp_path: Path, tool: str, contents: str
) -> None:
    path = tmp_path / "secret.conf"
    path.write_text(contents)

    with pytest.raises(ToolError, match="a document is a mapping, not str") as raised:
        await server.call_tool(tool, {"document": str(path)})

    assert "DUMMYKEY" not in str(raised.value)
    assert (await call(server, "list_pipelines"))["items"] == []


async def test_a_settled_run_is_rerun_and_one_in_flight_is_refused(server: MCPServer) -> None:
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["rerun_run"].annotations is not None and not tools["rerun_run"].annotations.read_only_hint

    await call(server, "apply_document", document=DOCUMENT)
    original = (await call(server, "run_pipeline", code="mcp-demo"))["run_id"]
    with pytest.raises(ToolError, match="only a settled run can be rerun"):
        await server.call_tool("rerun_run", {"run_id": original})

    await call(server, "cancel_run", run_id=original)
    accepted = await call(server, "rerun_run", run_id=original, current=True)
    again = (await call(server, "get_run", run_id=accepted["run_id"]))["run"]
    assert (again["triggered_by_kind"], again["triggered_by_id"]) == ("rerun", original)


async def test_run_stats_are_read_only_and_answer_the_window(server: MCPServer) -> None:
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["run_stats"].annotations is not None and tools["run_stats"].annotations.read_only_hint

    stats = await call(server, "run_stats", since="24h", pipeline="mcp-demo")
    assert set(stats) >= {"window", "trend"}
    assert sum(day["total"] for day in stats["trend"]) == 0, "nothing has settled yet"
    assert len(stats["trend"]) == 2, "a day back from now touches two UTC days"
    with pytest.raises(ToolError, match="at most"):
        await server.call_tool("run_stats", {"since": "400d"})


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
