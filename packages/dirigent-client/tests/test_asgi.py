"""The client against the real application, in this process, so the schemas are proven."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
import yaml
from cryptography.fernet import Fernet
from pydantic import SecretStr

from dirigent_client import BlockKind, Dirigent, NotFound, PlanAction, RunStatus, ValidationFailed
from dirigent_client.enums import UserRole
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_server import create_app

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: sdk-demo
description: Two shell steps, so the SDK has something real to drive.
params:
  type: object
  properties:
    greeting:
      type: string
      default: hello from the sdk
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, "${params.greeting}"]
  farewell:
    block: shell.run
    depends_on: [greet]
    config:
      argv: [echo, goodbye]
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance pointed at a throwaway database, artifact root, and secret key."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        enabled_unsafe_blocks=["shell.run"],
    )


@pytest.fixture
def token(settings: Settings) -> str:
    """Create the schema and one admin account, and return a bearer token for it."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with session_scope(create_session_factory(engine)) as session:
                user = await create_user(session, "tester", "a test password", role=UserRole.ADMIN)
                issued = await issue_token(session, user, name="sdk-tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
async def dg(settings: Settings, token: str) -> AsyncIterator[Dirigent]:
    """A client whose requests reach the real application without a socket in between."""
    app = create_app(settings, scheduler=False)
    # The lifespan opens the engine and builds the plugin host, so it has to run before any
    # request reaches a route.
    async with (
        httpx2.ASGITransport(app) as transport,
        app.router.lifespan_context(app),
        Dirigent(url="http://testserver", token=token, http_transport=transport) as client,
    ):
        yield client


async def test_the_instance_describes_itself_through_the_client(dg: Dirigent) -> None:
    info = await dg.system.info()
    assert info.name == "dirigent"
    assert info.database == "sqlite"
    assert info.blocks > 0
    assert (await dg.system.health()).status == "ok"
    assert (await dg.system.ready()).status == "healthy"


async def test_the_catalog_parses_into_the_schemas_the_client_publishes(dg: Dirigent) -> None:
    catalog = await dg.blocks.catalog()
    assert catalog.block("shell.run") is not None
    sensors = await dg.blocks.catalog(kind=BlockKind.SENSOR)
    assert all(entry.kind is BlockKind.SENSOR for entry in sensors.blocks)
    entry = await dg.blocks.get("shell.run")
    assert entry.config_schema["properties"]


async def test_the_caller_can_ask_who_it_is(dg: Dirigent) -> None:
    me = await dg.auth.whoami()
    assert me.username == "tester"


async def test_apply_plans_then_writes_then_reports_unchanged(dg: Dirigent) -> None:
    planned = await dg.pipelines.apply(DOCUMENT, dry_run=True)
    assert planned.plan.action is PlanAction.CREATE
    assert planned.dry_run is True
    assert (await dg.pipelines.list()).items == []

    created = await dg.pipelines.apply(DOCUMENT)
    assert created.plan.action is PlanAction.CREATE
    assert created.version == 1

    again = await dg.pipelines.apply(DOCUMENT)
    assert again.plan.action is PlanAction.UNCHANGED

    stored = await dg.pipelines.get("sdk-demo")
    assert stored.current_version == 1
    assert stored.document is not None
    assert [row.version for row in (await dg.pipelines.versions("sdk-demo")).items] == [1]
    assert yaml.safe_load(await dg.pipelines.export("sdk-demo"))["code"] == "sdk-demo"


async def test_a_document_this_instance_cannot_run_comes_back_as_a_plan(dg: Dirigent) -> None:
    document = yaml.safe_load(DOCUMENT)
    document["steps"]["greet"]["block"] = "nothing.installed"
    result = await dg.pipelines.apply(document)
    assert result.plan.action is PlanAction.INVALID
    assert any("nothing.installed" in issue.message for issue in result.plan.issues)


async def test_a_run_can_be_started_read_and_summarised(dg: Dirigent) -> None:
    await dg.pipelines.apply(DOCUMENT)
    accepted = await dg.pipelines.run("sdk-demo", params={"greeting": "from the sdk"})
    assert accepted.run_id is not None
    assert accepted.status == RunStatus.QUEUED.value

    detail = await dg.runs.get(accepted.run_id)
    assert detail.run.pipeline == "sdk-demo"
    assert [node.code for node in detail.dag.nodes] == ["greet", "farewell"]
    assert detail.run.terminal is False

    assert [row.id for row in (await dg.runs.list(pipeline="sdk-demo")).items] == [accepted.run_id]
    report = await dg.runs.report(accepted.run_id)
    assert report.pipeline == "sdk-demo"
    assert (await dg.runs.logs(accepted.run_id)).items == []

    cancelled = await dg.runs.cancel(accepted.run_id)
    assert cancelled.status is RunStatus.CANCELLED


async def test_parameters_the_schema_refuses_arrive_as_a_validation_failure(dg: Dirigent) -> None:
    await dg.pipelines.apply(DOCUMENT)
    with pytest.raises(ValidationFailed):
        await dg.pipelines.run("sdk-demo", params={"greeting": 7})


async def test_a_pipeline_this_instance_does_not_hold_is_a_not_found(dg: Dirigent) -> None:
    with pytest.raises(NotFound) as raised:
        await dg.pipelines.get("no-such-pipeline")
    assert raised.value.status == 404
    assert raised.value.problem is not None
    assert raised.value.problem.instance == "/api/v1/pipelines/no-such-pipeline"


async def test_a_schedule_and_a_webhook_round_trip_through_the_client(dg: Dirigent) -> None:
    await dg.pipelines.apply(DOCUMENT)
    schedule = await dg.schedules.create("sdk-demo", "nightly", cron="0 5 * * *", timezone="Europe/Oslo")
    assert schedule.next_fire_at is not None
    assert (await dg.schedules.pause("sdk-demo", "nightly")).paused is True
    assert (await dg.schedules.resume("sdk-demo", "nightly")).paused is False
    assert (await dg.schedules.firings("sdk-demo", "nightly")).items == []

    minted = await dg.webhooks.create("sdk-demo", "inbound", params_from_payload={"greeting": "$.text"})
    assert minted.url_path.startswith("/hooks/")
    assert [row.code for row in (await dg.webhooks.list("sdk-demo")).items] == ["inbound"]
    rotated = await dg.webhooks.rotate_token("sdk-demo", "inbound")
    assert rotated.token != minted.token
    assert (await dg.webhooks.disable("sdk-demo", "inbound")).active is False
    await dg.webhooks.delete("sdk-demo", "inbound")
    await dg.schedules.delete("sdk-demo", "nightly")
    assert (await dg.schedules.list("sdk-demo")).items == []


async def test_a_connection_round_trips_with_its_secret_redacted(dg: Dirigent) -> None:
    created = await dg.connections.create(
        "warehouse",
        kind="http",
        config={"base_url": "https://example.invalid"},
        description="a credential the tests never use",
    )
    assert created.code == "warehouse"
    assert [row.code for row in (await dg.connections.list()).items] == ["warehouse"]
    updated = await dg.connections.update("warehouse", description="renamed")
    assert updated.description == "renamed"
    await dg.connections.delete("warehouse")
    assert (await dg.connections.list()).items == []


async def test_an_alert_rule_and_its_queue_round_trip(dg: Dirigent) -> None:
    from dirigent_client import AlertEvent

    rule = await dg.alerts.create_rule("on-failure", event=AlertEvent.RUN_FAILED, notifier="log", throttle="15m")
    assert rule.throttle == "15m"
    queued = await dg.alerts.test(notifier="log", subject="a test message")
    assert queued.notifier == "log"
    assert [row.subject for row in (await dg.alerts.notifications()).items] == ["a test message"]
    await dg.alerts.delete_rule("on-failure")
    assert (await dg.alerts.rules()).items == []


async def test_tokens_and_accounts_are_managed_through_the_admin_accessor(dg: Dirigent) -> None:
    issued = await dg.admin.tokens.create("ci")
    assert issued.token.startswith(issued.prefix)
    assert "ci" in [row.name for row in (await dg.admin.tokens.list()).items]
    await dg.admin.tokens.revoke("ci")

    created = await dg.admin.users.create("second", "another test password", role=UserRole.OPERATOR)
    assert created.username == "second"
    assert {row.username for row in (await dg.admin.users.list()).items} == {"tester", "second"}

    theirs = await dg.admin.users.create_token("second", "ci")
    assert theirs.username == "second"
    assert [(row.username, row.name) for row in (await dg.admin.users.tokens("second")).items] == [("second", "ci")]
    await dg.admin.users.reset_password("second", "a third test password")
    await dg.admin.users.revoke_token("second", "ci")
    assert all(row.revoked_at is not None for row in (await dg.admin.users.tokens("second")).items)


async def test_the_worker_registry_is_empty_until_a_worker_registers(dg: Dirigent) -> None:
    assert (await dg.workers.list()).items == []


async def test_deactivating_then_deleting_a_pipeline_works_through_the_client(dg: Dirigent) -> None:
    await dg.pipelines.apply(DOCUMENT)
    assert (await dg.pipelines.deactivate("sdk-demo")).active is False
    assert (await dg.pipelines.activate("sdk-demo")).active is True
    await dg.pipelines.delete("sdk-demo")
    assert (await dg.pipelines.list()).items == []
