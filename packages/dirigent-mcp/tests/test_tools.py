"""The tools and resources that read connections, schemas, alert rules and sources, and rotate a source's token."""

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cryptography.fernet import Fernet
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr

from dirigent_client import AlertEvent, Dirigent
from dirigent_client.enums import UserRole
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_mcp import server as mcp_server
from dirigent_server import create_app

#: A secret no answer may carry.
SECRET = "a-bearer-token-nobody-may-read"

WITH_AN_ENDPOINT = """
format: dirigent/v1
kind: pipeline
code: mcp-endpoint
steps:
  ask:
    source:
      kind: endpoint
      path: /mcp-endpoint
  greet:
    block: value.const
    depends_on: [ask]
    config:
      value: hello
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
                    minted = await issue_token(session, user, name=f"{role.value}-mcp")
                    issued[role] = minted.secret.get_secret_value()
            return issued
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
async def clients(settings: Settings, tokens: dict[UserRole, str]) -> AsyncGenerator[dict[UserRole, Dirigent]]:
    """A client per role, each reaching the real application without a socket in between."""
    app = create_app(settings.model_copy(update={"mcp_enabled": False}), scheduler=False)
    async with httpx2.ASGITransport(app) as transport, app.router.lifespan_context(app):
        opened = {
            role: Dirigent(url="http://testserver", token=token, http_transport=transport)
            for role, token in tokens.items()
        }
        try:
            yield opened
        finally:
            for client in opened.values():
                await client.aclose()


@pytest.fixture
def admin(clients: dict[UserRole, Dirigent]) -> MCPServer:
    """The MCP server acting as an admin."""
    return mcp_server.build(mcp_server.shared(lambda: clients[UserRole.ADMIN]))


@pytest.fixture
def operator(clients: dict[UserRole, Dirigent]) -> MCPServer:
    """The MCP server acting as an operator."""
    return mcp_server.build(mcp_server.shared(lambda: clients[UserRole.OPERATOR]))


async def call(server: MCPServer, tool: str, **arguments: Any) -> Any:
    """Call a tool and read back the JSON it answered with."""
    result = await server.call_tool(tool, arguments)
    assert isinstance(result, CallToolResult)
    assert not result.is_error, result.content
    [text] = [block.text for block in result.content if isinstance(block, TextContent)]
    return json.loads(text)


async def read(server: MCPServer, uri: str) -> Any:
    """Read a resource and parse the JSON it serves."""
    contents = await server.read_resource(uri)
    assert not isinstance(contents, dict) and isinstance(contents, list)
    [content] = contents
    assert isinstance(content.content, str)
    return json.loads(content.content)


async def test_a_connection_is_listed_read_and_checked_and_its_secret_never_shown(
    admin: MCPServer, clients: dict[UserRole, Dirigent]
) -> None:
    await clients[UserRole.ADMIN].connections.create(
        "warehouse", kind="http", config={"base_url": "http://127.0.0.1:1", "bearer_token": SECRET}
    )

    [listed] = (await call(admin, "list_connections"))["items"]
    read_one = await call(admin, "get_connection", code="warehouse")
    checked = await call(admin, "check_connection", code="warehouse")

    assert (listed["code"], read_one["kind"]) == ("warehouse", "http")
    assert checked["healthy"] is False, "nothing answers on port 1"
    assert SECRET not in json.dumps([listed, read_one, checked])
    assert (await call(admin, "get_connection", code="warehouse"))["last_check_healthy"] is False


async def test_checking_a_connection_is_the_apis_to_refuse_to_an_operator(
    operator: MCPServer, clients: dict[UserRole, Dirigent]
) -> None:
    await clients[UserRole.ADMIN].connections.create("warehouse", kind="http", config={"base_url": "http://x.invalid"})
    with pytest.raises(ToolError, match="not permitted for your role"):
        await operator.call_tool("check_connection", {"code": "warehouse"})
    assert (await call(operator, "get_connection", code="warehouse"))["code"] == "warehouse"


async def test_a_schema_is_listed_and_read(operator: MCPServer, clients: dict[UserRole, Dirigent]) -> None:
    body = {"type": "object", "properties": {"station": {"type": "string"}}}
    await clients[UserRole.ADMIN].schemas.create(body, code="reading")

    assert [row["code"] for row in (await call(operator, "list_schemas"))["items"]] == ["reading"]
    assert (await call(operator, "get_schema", code="reading"))["body"]["properties"] == body["properties"]


async def test_an_alert_rule_is_listed_and_read(operator: MCPServer, clients: dict[UserRole, Dirigent]) -> None:
    await clients[UserRole.ADMIN].alerts.create_rule("on-failure", event=AlertEvent.RUN_FAILED, throttle="15m")

    assert [row["code"] for row in (await call(operator, "list_alert_rules"))["items"]] == ["on-failure"]
    rule = await call(operator, "get_alert_rule", code="on-failure")
    assert (rule["event"], rule["throttle"]) == ("run_failed", "15m")
    with pytest.raises(ToolError, match="no alert rule coded"):
        await operator.call_tool("get_alert_rule", {"code": "nobody"})


async def test_an_endpoint_says_where_and_how_it_is_called_and_its_token_rotates(operator: MCPServer) -> None:
    applied = await call(operator, "apply_document", document=WITH_AN_ENDPOINT)
    [minted] = applied["sources"]["tokens"]

    source = await call(operator, "get_source", pipeline="mcp-endpoint", code="ask")
    calling = source["calling"]
    assert calling["url"] == "http://testserver/endpoints/mcp-endpoint"
    assert (calling["auth"], calling["token_prefix"]) == ("token", minted["prefix"])
    assert "POST" in calling["methods"]
    assert minted["token"] not in json.dumps(source)

    rotated = await call(operator, "rotate_source_token", pipeline="mcp-endpoint", code="ask")
    assert rotated["token"] != minted["token"]
    after = await call(operator, "get_source", pipeline="mcp-endpoint", code="ask")
    assert after["calling"]["token_prefix"] == rotated["prefix"]


async def test_a_run_says_how_its_input_arrived_and_what_it_stored(operator: MCPServer) -> None:
    await call(operator, "apply_document", document=WITH_AN_ENDPOINT)
    accepted = await call(operator, "run_pipeline", code="mcp-endpoint", source="ask", input={"q": 1})
    entered = await call(operator, "get_run", run_id=accepted["run_id"])
    assert (entered["via"], entered["stored_bytes"]) == ("hand", 0)


async def test_a_run_with_no_source_says_so(operator: MCPServer) -> None:
    document = "format: dirigent/v1\nkind: pipeline\ncode: plain\nsteps:\n  one:\n    block: value.const\n"
    await call(operator, "apply_document", document=document + "    config:\n      value: 1\n")
    accepted = await call(operator, "run_pipeline", code="plain")
    answered = await call(operator, "get_run", run_id=accepted["run_id"])
    assert answered["via"] is None
    assert answered["stored_bytes"] == 0


async def test_every_tool_says_whether_it_writes_destroys_or_repeats(operator: MCPServer) -> None:
    tools = {tool.name: tool.annotations for tool in await operator.list_tools()}
    assert all(annotations is not None for annotations in tools.values())
    hints = {
        name: (a.read_only_hint, a.destructive_hint, a.idempotent_hint, a.open_world_hint)
        for name, a in tools.items()
        if a is not None
    }
    reads = {name for name, (read_only, *_) in hints.items() if read_only}
    assert {"list_connections", "get_connection", "list_schemas", "get_schema", "get_source"} <= reads
    assert {"list_alert_rules", "get_alert_rule", "get_run", "whoami"} <= reads
    assert all(hints[name][2] for name in reads), "reading twice is reading once"
    assert hints["rotate_source_token"][:3] == (False, True, False)
    assert hints["apply_document"][:3] == (False, True, True)
    assert hints["cancel_run"][:3] == (False, True, False)
    assert hints["check_connection"] == (False, False, True, True)
    assert hints["run_pipeline"] == (False, False, False, True)
    assert hints["pause_source"][:3] == (False, False, True)
    assert not {name for name in tools if name.startswith("delete")}


async def test_the_document_format_and_the_block_catalogue_are_resources(operator: MCPServer) -> None:
    listed = {str(resource.uri) for resource in await operator.list_resources()}
    assert {"dirigent://schema/document", "dirigent://blocks"} <= listed
    templates = {template.uri_template for template in await operator.list_resource_templates()}
    assert "dirigent://blocks/{block_id}" in templates

    schema = await read(operator, "dirigent://schema/document")
    assert schema["$schema"].startswith("https://json-schema.org/")
    catalogue = (await read(operator, "dirigent://blocks"))["blocks"]
    assert any(entry["id"] == "value.const" for entry in catalogue)
    block = await read(operator, "dirigent://blocks/value.const")
    assert "properties" in block["config_schema"]
