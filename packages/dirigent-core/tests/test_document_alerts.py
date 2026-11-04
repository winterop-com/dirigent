"""A pipeline document's ``alerts:``: planned, reconciled on apply, and owned by the document."""

from typing import ClassVar

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AlertEvent, AlertScope, Importance
from dirigent_client.schemas import PlanAction
from dirigent_core.alerting import (
    AlertRuleRequest,
    DeclaredRule,
    create_rule,
    delete_rule,
    find_rule,
    set_paused,
    update_rule,
)
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.documents import DocumentError, load_pipeline_text, to_yaml
from dirigent_core.engine import EngineServices
from dirigent_core.models import AlertRule, Connection
from dirigent_core.pipelines import apply_document, delete_pipeline, export_pipeline, plan_apply, set_active
from dirigent_core.plugins import PluginHost
from dirigent_plugin import AlertMessage, Contribution, Notifier
from engineblocks import EngineTestPlugin

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: nightly
steps:
  only:
    block: test.echo
    config: { value: one }
alerts:
  nightly-failed:
    name: Nightly failed
    event: run_failed
    connection: desk
    template: "{{ run.pipeline }} failed"
    throttle: 15m
  nightly-logged:
    event: run_completed_with_errors
"""


class DeskConfig(BaseModel):
    """What the desk channel is told."""


class DeskNotifier(Notifier):
    """A channel that delivers nowhere, so a connection of its kind is one alerts can name."""

    id: ClassVar[str] = "desk"
    config_model: ClassVar[type[BaseModel]] = DeskConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Deliver nothing."""


@pytest.fixture
def host() -> PluginHost:
    """The engine test blocks, and a notifier the desk connection's kind names."""
    return PluginHost(
        {
            "engine-tests": EngineTestPlugin().contribute(),
            "desk": Contribution(notifiers=[DeskNotifier()]),
        }
    )


@pytest.fixture
def services(settings: Settings, host: PluginHost) -> EngineServices:
    """The services every path shares, over the host with the desk notifier."""
    return EngineServices.build(settings, host)


@pytest.fixture
async def desk(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Hold a desk connection, and an http one no notifier delivers through."""
    async with session_scope(sessions) as session:
        session.add(Connection(code="desk", kind="desk", config={}))
        session.add(Connection(code="api", kind="http", config={}))


async def apply(sessions: async_sessionmaker[AsyncSession], services: EngineServices, text: str) -> object:
    async with session_scope(sessions) as session:
        return await apply_document(session, services, load_pipeline_text(text))


async def rules(sessions: async_sessionmaker[AsyncSession]) -> dict[str, AlertRule]:
    async with sessions() as session:
        return {row.code: row for row in (await session.execute(sa.select(AlertRule))).scalars()}


@pytest.mark.usefixtures("desk")
async def test_an_apply_creates_the_rules_a_document_declares_scoped_to_its_pipeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, DOCUMENT)
    held = await rules(sessions)
    assert sorted(held) == ["nightly-failed", "nightly-logged"]
    failed = held["nightly-failed"]
    assert (failed.declared, failed.scope, failed.notifier, failed.throttle_seconds) == (
        True,
        AlertScope.PIPELINE,
        "desk",
        900,
    )
    assert held["nightly-logged"].notifier == "log"


@pytest.mark.usefixtures("desk")
async def test_a_reapply_rewrites_a_changed_rule_removes_a_dropped_one_and_keeps_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, DOCUMENT)
    async with session_scope(sessions) as session:
        rule = await find_rule(session, "nightly-failed")
        assert rule is not None
        await set_paused(session, rule, paused=True)
    changed = DOCUMENT.replace("throttle: 15m", "throttle: 1h\n    importance: critical").replace(
        "  nightly-logged:\n    event: run_completed_with_errors\n", "  nightly-ok:\n    event: run_succeeded\n"
    )
    async with session_scope(sessions) as session:
        plan = await plan_apply(session, services, load_pipeline_text(changed))
    assert plan.diff is not None
    assert (plan.diff.alerts_added, plan.diff.alerts_removed, plan.diff.alerts_changed) == (
        ["nightly-ok"],
        ["nightly-logged"],
        ["nightly-failed"],
    )
    await apply(sessions, services, changed)
    held = await rules(sessions)
    assert sorted(held) == ["nightly-failed", "nightly-ok"]
    failed = held["nightly-failed"]
    assert (failed.throttle_seconds, failed.importance, failed.paused) == (3600, Importance.CRITICAL, True)


@pytest.mark.usefixtures("desk")
async def test_an_apply_never_touches_a_rule_created_through_the_api(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, DOCUMENT)
    async with session_scope(sessions) as session:
        await create_rule(
            session,
            services,
            AlertRuleRequest(
                code="by-hand", event=AlertEvent.RUN_FAILED, scope=AlertScope.PIPELINE, pipeline="nightly"
            ),
        )
    await apply(sessions, services, DOCUMENT.split("alerts:")[0])
    held = await rules(sessions)
    assert sorted(held) == ["by-hand"]
    assert not held["by-hand"].declared


@pytest.mark.usefixtures("desk")
async def test_plan_refuses_a_code_held_by_hand_and_a_connection_that_cannot_deliver(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await create_rule(session, services, AlertRuleRequest(code="nightly-logged", event=AlertEvent.RUN_FAILED))
    refused = DOCUMENT.replace("connection: desk", "connection: api")
    async with session_scope(sessions) as session:
        plan = await plan_apply(session, services, load_pipeline_text(refused))
    assert plan.action is PlanAction.INVALID
    assert sorted((issue.location, issue.code) for issue in plan.issues) == [
        ("alerts.nightly-failed.connection", "alert.target_has_no_notifier"),
        ("alerts.nightly-logged", "alert.owned_elsewhere"),
    ]


@pytest.mark.usefixtures("desk")
async def test_plan_refuses_a_code_another_pipelines_document_declares(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, DOCUMENT)
    async with session_scope(sessions) as session:
        plan = await plan_apply(session, services, load_pipeline_text(DOCUMENT.replace("code: nightly", "code: other")))
    assert {issue.code for issue in plan.issues} == {"alert.owned_elsewhere"}
    assert plan.issues[0].params["owner"] == "the document of pipeline 'nightly'"


async def test_plan_refuses_a_connection_the_instance_does_not_hold(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        plan = await plan_apply(session, services, load_pipeline_text(DOCUMENT))
    assert [(issue.location, issue.code) for issue in plan.issues] == [
        ("alerts.nightly-failed.connection", "alert.unknown_connection")
    ]


@pytest.mark.usefixtures("desk")
async def test_plan_warns_on_a_name_a_declared_rule_reads_that_an_alert_is_never_given(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    misspelt = DOCUMENT.replace('"{{ run.pipeline }} failed"', '"{{ run.pipelin }} failed"').replace(
        "  nightly-logged:\n", '  nightly-logged:\n    body: "{{ nonsense }}"\n'
    )
    async with session_scope(sessions) as session:
        plan = await plan_apply(session, services, load_pipeline_text(misspelt))
    assert plan.action is PlanAction.CREATE
    assert [(issue.location, issue.code, issue.params["name"]) for issue in plan.warnings] == [
        ("alerts.nightly-failed.template", "alert.template_name_unknown", "run.pipelin"),
        ("alerts.nightly-logged.body", "alert.template_name_unknown", "nonsense"),
    ]


def test_a_template_that_does_not_compile_is_refused_by_the_document() -> None:
    with pytest.raises(DocumentError, match=r"alerts\.nightly-failed\.template"):
        load_pipeline_text(DOCUMENT.replace('"{{ run.pipeline }} failed"', '"{{ run.pipeline "'))


@pytest.mark.usefixtures("desk")
async def test_a_declared_rule_refuses_an_update_and_a_delete_but_pauses(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, DOCUMENT)
    async with session_scope(sessions) as session:
        rule = await find_rule(session, "nightly-failed")
        assert rule is not None
        with pytest.raises(DeclaredRule) as refused:
            await update_rule(session, services, rule, {"template": "changed"})
        assert refused.value.params == {"code": "'nightly-failed'", "pipeline": "'nightly'"}
        with pytest.raises(DeclaredRule):
            await delete_rule(session, rule)
        await update_rule(session, services, rule, {"paused": True})
        assert rule.paused


@pytest.mark.usefixtures("desk")
async def test_the_export_round_trips_the_alerts_in_code_order(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    reordered = DOCUMENT.replace("  nightly-failed:", "  zz-placeholder:")
    definition = load_pipeline_text(reordered)
    assert list(load_pipeline_text(to_yaml(definition)).alerts) == ["nightly-logged", "zz-placeholder"]
    await apply(sessions, services, DOCUMENT)
    async with sessions() as session:
        exported = await export_pipeline(session, "nightly")
    assert load_pipeline_text(exported) == load_pipeline_text(DOCUMENT)
    assert "throttle: 15m" in exported


@pytest.mark.usefixtures("desk")
async def test_deactivating_keeps_the_rules_and_deleting_the_pipeline_takes_them(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, DOCUMENT)
    async with session_scope(sessions) as session:
        await set_active(session, "nightly", active=False)
    assert sorted(await rules(sessions)) == ["nightly-failed", "nightly-logged"]
    async with session_scope(sessions) as session:
        await delete_pipeline(session, "nightly")
    assert await rules(sessions) == {}
