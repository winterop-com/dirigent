"""The tools and resources for connections, schemas, alert rules and sources, and a source's token."""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, ClassVar

import httpx2
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, SecretStr, model_validator

from dirigent_client import AlertEvent, AttemptStatus, Dirigent, DirigentError
from dirigent_client.enums import UserRole
from dirigent_common import BlockModel, HealthReport, JsonMap
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base, StepAttempt
from dirigent_core.plugins import load_plugin_host
from dirigent_mcp import server as mcp_server
from dirigent_mcp.answers import MAX_ANSWER_BYTES, PREVIEW_CHARS
from dirigent_plugin import ConnectionKind, Contribution, extension
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


class VaultConfig(BlockModel):
    """A kind the model refuses without a credential, as a DHIS2 connection is."""

    endpoint: str
    api_token: SecretStr | None = None

    @model_validator(mode="after")
    def _a_credential(self) -> "VaultConfig":
        if self.api_token is None:
            raise ValueError("a vault connection needs an api_token")
        return self


class VaultKind(ConnectionKind):
    id: ClassVar[str] = "vault"
    config_model: ClassVar[type[BaseModel]] = VaultConfig

    async def check(self, config: BaseModel) -> HealthReport:
        return HealthReport(healthy=True)


class VaultPlugin:
    @extension
    def contribute(self) -> Contribution:
        return Contribution(connection_kinds=[VaultKind()])


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
    host = load_plugin_host(extra={"vault": VaultPlugin()})
    app = create_app(settings.model_copy(update={"mcp_enabled": False}), scheduler=False, host=host)
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


async def test_a_connection_is_created_awaiting_the_secrets_a_person_supplies(admin: MCPServer) -> None:
    created = await call(
        admin, "create_connection", kind="vault", code="vault", settings={"endpoint": "https://vault.invalid"}
    )

    assert created["connection"]["awaiting_secrets"] is True
    assert created["secrets_to_supply"] == ["api_token"]
    assert created["supply_with"] == {
        "by": "an admin of this instance",
        "command": "dg --url http://testserver connection set-secret vault",
        "screen": "http://testserver/connections/vault",
    }
    assert (await call(admin, "get_connection", code="vault"))["awaiting_secrets"] is True
    with pytest.raises(ToolError, match="awaits its secrets"):
        await admin.call_tool("check_connection", {"code": "vault"})


async def test_a_connection_whose_credential_is_optional_is_usable_and_says_what_it_could_be_given(
    operator: MCPServer,
) -> None:
    created = await call(
        operator,
        "create_connection",
        kind="http",
        code="api",
        name="The API",
        settings={"base_url": "https://x.invalid"},
    )

    assert (created["connection"]["name"], created["connection"]["awaiting_secrets"]) == ("The API", False)
    assert created["secrets_to_supply"] == []
    assert {"bearer_token", "basic_password"} <= set(created["optional_secrets"])
    assert created["supply_with"]["command"].endswith("connection set-secret api")


async def test_a_kind_requiring_a_credential_awaits_it(operator: MCPServer) -> None:
    created = await call(operator, "create_connection", kind="slack", code="ops-slack", settings={"channel": "#ops"})

    assert created["connection"]["awaiting_secrets"] is True
    assert {"webhook_url", "bot_token"} <= set(created["secrets_to_supply"])


async def test_a_secret_handed_to_create_connection_is_refused_by_name_and_never_repeated(
    admin: MCPServer,
) -> None:
    with pytest.raises(ToolError) as refused:
        await admin.call_tool(
            "create_connection",
            {"kind": "http", "code": "api", "settings": {"base_url": "https://x.invalid", "bearer_token": SECRET}},
        )

    assert "bearer_token" in str(refused.value)
    assert SECRET not in str(refused.value)
    assert (await call(admin, "list_connections"))["items"] == []


async def test_an_operator_creates_a_connection_an_admin_completes(
    operator: MCPServer, clients: dict[UserRole, Dirigent]
) -> None:
    created = await call(
        operator, "create_connection", kind="vault", code="vault", settings={"endpoint": "https://vault.invalid"}
    )
    assert (created["secrets_to_supply"], created["supply_with"]["by"]) == (["api_token"], "an admin of this instance")

    with pytest.raises(DirigentError, match="not permitted for your role"):
        await clients[UserRole.OPERATOR].connections.update(
            "vault", config={"endpoint": "https://vault.invalid", "api_token": SECRET}
        )
    completed = await clients[UserRole.ADMIN].connections.update(
        "vault", config={"endpoint": "https://vault.invalid", "api_token": SECRET}
    )
    assert completed.awaiting_secrets is False


async def test_an_operator_handing_create_connection_a_secret_is_refused_by_name(operator: MCPServer) -> None:
    with pytest.raises(ToolError) as refused:
        await operator.call_tool(
            "create_connection", {"kind": "vault", "code": "vault", "settings": {"endpoint": "x", "api_token": SECRET}}
        )
    assert "api_token" in str(refused.value)
    assert SECRET not in str(refused.value)


async def test_the_audit_trail_is_read_by_an_admin_and_names_the_agents_token(
    admin: MCPServer, clients: dict[UserRole, Dirigent]
) -> None:
    await clients[UserRole.ADMIN].connections.create(
        "warehouse", kind="http", config={"base_url": "http://x.invalid", "bearer_token": SECRET}
    )
    trail = await call(admin, "list_audit", subject_kind="connection")
    [entry] = trail["items"]
    assert (entry["action"], entry["subject_code"]) == ("created", "warehouse")
    assert entry["actor_label"] == "admin (token admin-mcp)"
    assert SECRET not in json.dumps(trail)


async def test_the_audit_trail_is_not_offered_below_admin(clients: dict[UserRole, Dirigent]) -> None:
    offered = mcp_server.build(
        mcp_server.shared(lambda: clients[UserRole.OPERATOR]), offers=mcp_server.Offers.OPERATING
    )
    assert "list_audit" not in {tool.name for tool in await offered.list_tools()}
    with pytest.raises(ToolError, match="not permitted for your role"):
        await mcp_server.build(mcp_server.shared(lambda: clients[UserRole.OPERATOR])).call_tool("list_audit", {})


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


async def test_an_attempt_is_read_by_its_id_alone(operator: MCPServer) -> None:
    document = "format: dirigent/v1\nkind: pipeline\ncode: plain\nsteps:\n  one:\n    block: value.const\n"
    await call(operator, "apply_document", document=document + "    config:\n      value: 1\n")
    accepted = await call(operator, "run_pipeline", code="plain")
    attempts = await call(operator, "run_attempts", run_id=accepted["run_id"])
    attempt_id = attempts["items"][0]["id"]
    found = await call(operator, "get_attempt", attempt_id=attempt_id)
    assert (found["id"], found["run_id"], found["pipeline"], found["step_name"]) == (
        attempt_id,
        accepted["run_id"],
        "plain",
        "one",
    )
    assert found.get("item") is None, "not a fan-out element"


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
    assert {"list_alert_rules", "get_alert_rule", "get_run", "get_attempt", "whoami", "list_audit"} <= reads
    assert all(hints[name][2] for name in reads), "reading twice is reading once"
    assert hints["rotate_source_token"][:3] == (False, True, False)
    assert hints["apply_document"][:3] == (False, True, True)
    assert hints["cancel_run"][:3] == (False, True, False)
    assert hints["check_connection"] == (False, False, True, True)
    assert hints["create_connection"] == (False, False, False, False), "an operator is offered it"
    assert hints["run_pipeline"] == (False, False, False, True)
    assert hints["pause_source"][:3] == (False, False, True)
    assert hints["delete_alert_rule"][:3] == (False, True, False)
    assert hints["edit_pipeline"][:3] == (False, True, True)
    assert hints["create_alert_rule"][:3] == (False, False, False)


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


WRITING_TOOLS = {
    "edit_pipeline",
    "create_alert_rule",
    "update_alert_rule",
    "pause_alert_rule",
    "resume_alert_rule",
    "delete_alert_rule",
    "create_schema",
    "update_schema",
    "delete_schema",
}

SCHEMA_WRITES = {"create_schema", "update_schema", "delete_schema"}

READING_TOOLS = {
    "get_run_report",
    "get_run_profile",
    "get_attempt_output",
    "list_schedule_firings",
    "list_alert_deliveries",
}


async def offered(offers: mcp_server.Offers) -> set[str]:
    """The tools a server offering what one role may do lists."""
    server = mcp_server.build(mcp_server.shared(lambda: pytest.fail("listing tools opens no client")), offers=offers)
    return {tool.name for tool in await server.list_tools()}


async def test_each_role_is_offered_the_tools_the_api_allows_it() -> None:
    reading = await offered(mcp_server.Offers.READING)
    operating = await offered(mcp_server.Offers.OPERATING)
    administering = await offered(mcp_server.Offers.ADMINISTERING)

    assert reading >= READING_TOOLS
    assert not WRITING_TOOLS & reading, "a viewer is offered nothing that writes"
    assert operating >= WRITING_TOOLS - SCHEMA_WRITES
    assert not SCHEMA_WRITES & operating, "a schema is an admin's to write"
    assert administering >= WRITING_TOOLS | READING_TOOLS


async def test_only_a_rule_and_a_schema_are_deleted_and_every_rewrite_says_it_destroys(admin: MCPServer) -> None:
    tools = {tool.name: tool.annotations for tool in await admin.list_tools()}
    assert {name for name in tools if name.startswith("delete")} == {"delete_alert_rule", "delete_schema"}
    for name in ("delete_alert_rule", "delete_schema", "update_schema", "update_alert_rule", "edit_pipeline"):
        hints = tools[name]
        assert hints is not None and hints.destructive_hint and not hints.read_only_hint, name


async def test_an_alert_rule_is_created_changed_paused_resumed_and_deleted(operator: MCPServer) -> None:
    created = await call(operator, "create_alert_rule", code="on-failure", event="run_failed", throttle="15m")
    assert (created["code"], created["throttle"], created["paused"]) == ("on-failure", "15m", False)

    changed = await call(operator, "update_alert_rule", code="on-failure", template="{{ run.pipeline }} failed")
    assert changed["template"] == "{{ run.pipeline }} failed"
    assert (await call(operator, "pause_alert_rule", code="on-failure"))["paused"] is True
    assert (await call(operator, "resume_alert_rule", code="on-failure"))["paused"] is False

    assert await call(operator, "delete_alert_rule", code="on-failure") == {"deleted": "on-failure"}
    assert (await call(operator, "list_alert_rules"))["items"] == []
    with pytest.raises(ToolError, match="no alert rule coded"):
        await operator.call_tool("delete_alert_rule", {"code": "on-failure"})


async def test_the_delivery_queue_is_read_and_narrowed_by_state(
    operator: MCPServer, clients: dict[UserRole, Dirigent]
) -> None:
    queued = await clients[UserRole.OPERATOR].alerts.test()

    [delivery] = (await call(operator, "list_alert_deliveries"))["items"]
    assert delivery["id"] == str(queued.notification_id)
    assert (await call(operator, "list_alert_deliveries", status="pending"))["items"] == [delivery]
    assert (await call(operator, "list_alert_deliveries", status="sent"))["items"] == []


async def test_a_schema_is_created_updated_and_deleted_by_an_admin(admin: MCPServer) -> None:
    body = {"type": "object", "properties": {"station": {"type": "string"}}}
    created = await call(admin, "create_schema", body=body, code="reading", name="A reading")
    assert (created["code"], created["name"]) == ("reading", "A reading")

    updated = await call(admin, "update_schema", code="reading", body={**body, "required": ["station"]})
    assert (updated["body"]["required"], updated["name"]) == (["station"], "A reading")

    assert await call(admin, "delete_schema", code="reading") == {"deleted": "reading"}
    assert (await call(admin, "list_schemas"))["items"] == []


WITH_A_CLOCK = """
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


async def test_a_schedule_that_has_not_fired_lists_no_firings(operator: MCPServer) -> None:
    await call(operator, "apply_document", document=WITH_A_CLOCK)
    assert (await call(operator, "list_schedule_firings", pipeline="mcp-clocked", code="nightly"))["items"] == []
    with pytest.raises(ToolError):
        await operator.call_tool("list_schedule_firings", {"pipeline": "mcp-clocked", "code": "nobody"})


REPORTED = """
format: dirigent/v1
kind: pipeline
code: {code}
{report}
steps:
  greet:
    block: value.const
    config:
      value: hello
"""


async def test_a_run_report_document_is_read_and_its_absence_said(operator: MCPServer) -> None:
    await call(operator, "apply_document", document=REPORTED.format(code="reported", report="report: {}"))
    await call(operator, "apply_document", document=REPORTED.format(code="silent", report=""))
    reported = (await call(operator, "run_pipeline", code="reported"))["run_id"]
    silent = (await call(operator, "run_pipeline", code="silent"))["run_id"]
    await call(operator, "cancel_run", run_id=reported)
    await call(operator, "cancel_run", run_id=silent)

    document = await call(operator, "get_run_report", run_id=reported)
    assert document["exists"] is True
    assert "reported" in document["text"]
    assert document["total_chars"] == len(document["text"])
    assert "next_offset" not in document
    assert await call(operator, "get_run_report", run_id=silent) == {"run_id": silent, "exists": False}


async def test_a_run_profile_names_its_critical_path_and_where_its_time_went(operator: MCPServer) -> None:
    await call(operator, "apply_document", document=REPORTED.format(code="profiled", report=""))
    run_id = (await call(operator, "run_pipeline", code="profiled"))["run_id"]
    await call(operator, "cancel_run", run_id=run_id)

    measured = await call(operator, "get_run_profile", run_id=run_id)
    assert (measured["run_id"], measured["pipeline"], measured["status"]) == (run_id, "profiled", "cancelled")
    assert {"critical_path", "queued_ms", "running_ms", "waiting_ms", "steps", "warnings"} <= set(measured)


def wide(code: str, steps: int) -> str:
    """A pipeline of this many independent steps, so one run holds as many attempts at once."""
    lines = ["format: dirigent/v1", "kind: pipeline", f"code: {code}", "steps:"]
    for index in range(steps):
        lines += [f"  s{index:02d}:", "    block: value.const", "    config:", "      value: 1"]
    return "\n".join(lines) + "\n"


#: An output far larger than one answer may carry.
LARGE_OUTPUT = {"rows": [{"index": index, "text": "x" * 400} for index in range(200)]}


async def settle_every_attempt(settings: Settings, run_id: str, output: JsonMap) -> None:
    """Write an output on every attempt of a run, as if each step had produced it."""
    engine = create_engine(settings)
    try:
        async with session_scope(create_session_factory(engine)) as session:
            await session.execute(
                sa.update(StepAttempt)
                .where(StepAttempt.run_id == uuid.UUID(run_id))
                .values(output=output, status=AttemptStatus.SUCCEEDED)
            )
    finally:
        await engine.dispose()


def answered_bytes(result: object) -> int:
    """How many bytes of text a tool answered with."""
    assert isinstance(result, CallToolResult) and not result.is_error, result
    return sum(len(block.text.encode()) for block in result.content if isinstance(block, TextContent))


async def test_attempts_are_listed_without_their_outputs_and_every_answer_stays_bounded(
    operator: MCPServer, settings: Settings
) -> None:
    await call(operator, "apply_document", document=wide("wide", 25))
    run_id = (await call(operator, "run_pipeline", code="wide"))["run_id"]
    await settle_every_attempt(settings, run_id, LARGE_OUTPUT)

    assert answered_bytes(await operator.call_tool("run_attempts", {"run_id": run_id})) <= MAX_ANSWER_BYTES
    page = await call(operator, "run_attempts", run_id=run_id)
    assert len(page["items"]) == mcp_server.DEFAULT_LIMIT
    first = page["items"][0]
    assert "output" not in first
    assert first["output_bytes"] > MAX_ANSWER_BYTES
    assert first["output_preview"].startswith('{"rows"')
    assert len(first["output_preview"]) <= PREVIEW_CHARS

    every = {"run_id": run_id, "include_output": True, "limit": 25}
    assert answered_bytes(await operator.call_tool("run_attempts", every)) <= MAX_ANSWER_BYTES
    whole = await call(operator, "run_attempts", **every)
    assert "`limit`" in whole["truncated"] and "next" not in whole

    one = {"run_id": run_id, "attempt_id": first["id"]}
    assert answered_bytes(await operator.call_tool("get_attempt_output", one)) <= MAX_ANSWER_BYTES
    assert "`path`" in (await call(operator, "get_attempt_output", **one))["truncated"]
    part = await call(operator, "get_attempt_output", **one, path="/rows/3/index")
    assert (part["output"], part["step"]) == (3, first["step_name"])
    with pytest.raises(ToolError, match="reaches nothing"):
        await operator.call_tool("get_attempt_output", {**one, "path": "/nope"})
    with pytest.raises(ToolError, match="has no attempt"):
        await operator.call_tool("get_attempt_output", {"run_id": run_id, "attempt_id": str(uuid.uuid4())})


async def test_the_examples_are_listed_short_by_default_and_read_one_at_a_time(operator: MCPServer) -> None:
    assert answered_bytes(await operator.call_tool("list_examples", {})) <= MAX_ANSWER_BYTES
    listed = await call(operator, "list_examples")
    assert 0 < len(listed["items"]) <= mcp_server.DEFAULT_LIMIT
    assert all(set(row) <= {"code", "name", "shelf", "tags", "blocks"} for row in listed["items"])

    everything = {"summary": False, "limit": 500}
    assert answered_bytes(await operator.call_tool("list_examples", everything)) <= MAX_ANSWER_BYTES

    example = await call(operator, "get_example", code=listed["items"][0]["code"])
    assert "format: dirigent/v1" in example["source"]
    assert example["total_chars"] >= len(example["source"])


EDITABLE = """
format: dirigent/v1
kind: pipeline
code: mcp-edited
steps:
  greet:
    block: value.const
    config:
      value: hello
  part:
    block: value.const
    config:
      value: hello
"""


async def test_a_pipeline_is_edited_in_place_from_its_exported_text(operator: MCPServer) -> None:
    await call(operator, "apply_document", document=EDITABLE)
    assert "greet:" in (await call(operator, "export_pipeline", code="mcp-edited"))["text"]
    renamed = [{"old": "greet:", "new": "welcome:"}]

    planned = await call(operator, "edit_pipeline", code="mcp-edited", edits=renamed, plan_only=True)
    assert (planned["dry_run"], planned["plan"]["action"]) == (True, "update")
    assert (await call(operator, "get_pipeline", code="mcp-edited"))["current_version"] == 1

    applied = await call(operator, "edit_pipeline", code="mcp-edited", edits=renamed)
    assert (applied["version"], applied["plan"]["diff"]["steps_added"]) == (2, ["welcome"])
    assert "welcome:" in (await call(operator, "export_pipeline", code="mcp-edited"))["text"]


@pytest.mark.parametrize(
    ("edits", "refusal"),
    [
        ([{"old": "part:", "new": "piece:"}, {"old": "nowhere", "new": "x"}], "edit 1: its `old` text does not occur"),
        ([{"old": "value: hello", "new": "value: bye"}], "occurs 2 times"),
        ([{"old": "", "new": "x"}], "edit 0: its `old` text is empty"),
    ],
)
async def test_an_edit_that_misses_refuses_every_edit_and_stores_nothing(
    operator: MCPServer, edits: list[dict[str, str]], refusal: str
) -> None:
    await call(operator, "apply_document", document=EDITABLE)
    before = (await call(operator, "export_pipeline", code="mcp-edited"))["text"]

    with pytest.raises(ToolError, match=refusal) as refused:
        await operator.call_tool("edit_pipeline", {"code": "mcp-edited", "edits": edits})

    assert "nothing was planned or applied" in str(refused.value)
    assert (await call(operator, "export_pipeline", code="mcp-edited"))["text"] == before
    assert (await call(operator, "get_pipeline", code="mcp-edited"))["current_version"] == 1
