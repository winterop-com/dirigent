"""Tests for alerting: rules, matching, the throttle, the deduplication, and the delivery queue."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import BaseModel, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from dirigent_client.enums import AlertEvent, AlertScope, LogLevel, NotificationStatus, RunStatus, TriggerKind
from dirigent_common import JsonMap
from dirigent_core.alerting import (
    DEFAULT_TEMPLATE,
    EVENT_FOR_STATUS,
    AlertError,
    AlertRuleRequest,
    NotificationDispatcher,
    build_context,
    claim_notification,
    create_rule,
    delete_rule,
    find_rule,
    list_notifications,
    list_rules,
    matching_rules,
    notifier_config,
    queue_test_message,
    raise_for_run,
    raise_for_status,
    raise_for_stuck,
    recover_notifications,
    render_template,
    renew_lease,
    retry_notification,
    send_notification,
    set_paused,
    throttled_until,
)
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import AlertRule, Connection, LogEntry, Notification, Pipeline, Run
from dirigent_core.plugins import PluginHost
from dirigent_plugin import AlertMessage, Contribution, Notifier
from engineblocks import EngineTestPlugin

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

LEASE = 60

OWNER = "worker-under-test"

BRIEF_LEASE = 5


# -- the fake channels -----------------------------------------------------------


class RecordingConfig(BaseModel):
    """What the recording notifier is told, including one field that has to be sealed."""

    label: str = "default"
    token: SecretStr | None = None


class RecordingNotifier(Notifier):
    """A notifier that accepts everything and remembers what it was handed."""

    id = "recording"
    config_model = RecordingConfig
    sent: ClassVar[list[tuple[AlertMessage, BaseModel]]] = []

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Accept the message, keeping it and the config it was delivered with."""
        RecordingNotifier.sent.append((message, config))


class ExplodingNotifier(Notifier):
    """A notifier that refuses everything, which is what the retry budget is for."""

    id = "exploding"
    config_model = RecordingConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Refuse the delivery the way a flaky channel does."""
        raise RuntimeError("the channel is on fire")


class Interference(BaseModel):
    """What the interfering notifier does mid-delivery, set by the test that needs it."""

    during: Callable[[], Awaitable[None]] | None = None
    refuses: bool = False


interference = Interference()


class InterferingNotifier(Notifier):
    """A notifier that runs the test's own callback in the middle of a delivery."""

    id = "interfering"
    config_model = RecordingConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Let the test act while this delivery is in flight, then deliver or refuse."""
        if interference.during is not None:
            await interference.during()
        if interference.refuses:
            raise RuntimeError("the channel is on fire")


@pytest.fixture(autouse=True)
def _forget_deliveries() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Leave the fake channels with no memory of the previous test."""
    RecordingNotifier.sent.clear()
    interference.during = None
    interference.refuses = False
    yield
    RecordingNotifier.sent.clear()
    interference.during = None
    interference.refuses = False


@pytest.fixture
def host() -> PluginHost:  # pyright: ignore[reportUnusedFunction]
    """A plugin host carrying the engine's test blocks and both fake channels."""
    return PluginHost(
        {
            "engine-tests": EngineTestPlugin().contribute(),
            "alert-tests": Contribution(notifiers=[RecordingNotifier(), ExplodingNotifier(), InterferingNotifier()]),
        }
    )


@pytest.fixture
def bare_services(settings: Settings) -> EngineServices:
    """Services for an instance with no notifier installed at all."""
    return EngineServices.build(settings, PluginHost({}))


@pytest.fixture
def brief_services(settings: Settings, host: PluginHost) -> EngineServices:
    """Services whose notification lease is short enough for a renewal to be observed."""
    brief = settings.model_copy(update={"notification_lease": timedelta(seconds=BRIEF_LEASE)})
    return EngineServices.build(brief, host)


@pytest.fixture
def linked_services(settings: Settings, host: PluginHost) -> EngineServices:
    """Services for an instance that knows its own address, so alerts can link back."""
    return EngineServices.build(settings.model_copy(update={"alert_base_url": "https://dirigent.test/"}), host)


# -- helpers ---------------------------------------------------------------------


def a_pipeline(code: str = "nightly") -> Pipeline:
    """Build an unattached pipeline row, which is all the context builder reads."""
    return Pipeline(id=uuid4(), code=code)


def a_run(
    *,
    status: RunStatus = RunStatus.FAILED,
    params: JsonMap | None = None,
    started_at: datetime | None = NOW,
    finished_at: datetime | None = NOW + timedelta(seconds=90, milliseconds=250),
) -> Run:
    """Build an unattached run row carrying exactly the facts a template may read."""
    return Run(
        id=uuid4(),
        pipeline_id=uuid4(),
        pipeline_version_id=uuid4(),
        status=status,
        params=params or {},
        triggered_by_kind=TriggerKind.ADHOC,
        triggered_by_label="morten",
        error="the loader gave up",
        started_at=started_at,
        finished_at=finished_at,
    )


def run_facts(context: JsonMap) -> JsonMap:
    """Read the one namespace an alert context has."""
    return cast("JsonMap", context["run"])


async def stored_run(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    *,
    pipeline: str = "nightly",
    status: RunStatus = RunStatus.FAILED,
) -> Run:
    """Save a pipeline, create a run of it, and settle it, as a worker's outcome would."""
    definition = PipelineDefinition(code=pipeline, steps={"only": StepDefinition(block="test.echo")})
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        created = await create_run(session, services, version)
    assert created is not None
    async with session_scope(sessions) as session:
        run = await session.get(Run, created.id)
        assert run is not None
        run.status = status
        run.started_at = NOW
        run.finished_at = NOW + timedelta(minutes=2)
        run.error = "the loader gave up" if status is RunStatus.FAILED else None
        return run


async def declare(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    request: AlertRuleRequest,
) -> AlertRule:
    """Declare one alert rule in its own transaction, the way the API does."""
    async with session_scope(sessions) as session:
        return await create_rule(session, services, request)


async def a_connection(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    *,
    name: str = "desk",
) -> Connection:
    """Store one connection whose secret half is sealed with the instance key."""
    public, envelope, key_id = services.secrets.encrypt_config(
        RecordingConfig, RecordingConfig(label="ops", token=SecretStr("s3cret"))
    )
    async with session_scope(sessions) as session:
        connection = Connection(
            code=name, kind="recording", config=public, secret_envelope=envelope, secret_key_id=key_id
        )
        session.add(connection)
        await session.flush()
        return connection


async def enqueue(sessions: async_sessionmaker[AsyncSession], **fields: Any) -> Notification:
    """Put one notification row straight on the queue, bypassing the rules that raise them."""
    async with session_scope(sessions) as session:
        notification = Notification(**fields)
        session.add(notification)
        await session.flush()
        return notification


async def queued_message(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    *,
    notifier: str = "recording",
    subject: str = "dirigent test alert",
    connection: str | None = None,
) -> Notification:
    """Queue one test message and pin it to the fixed clock the delivery tests claim against."""
    async with session_scope(sessions) as session:
        notification = await queue_test_message(
            session, services, notifier=notifier, connection=connection, subject=subject
        )
        notification.available_at = NOW
        return notification


async def reload_notification(sessions: async_sessionmaker[AsyncSession], notification_id: UUID) -> Notification:
    """Read one notification back from the database."""
    async with sessions() as session:
        row = await session.get(Notification, notification_id)
        assert row is not None
        return row


async def reclaim(sessions: async_sessionmaker[AsyncSession], notification_id: UUID, *, owner: str) -> None:
    """Hand a sending notification to another worker, as recovery and a fresh claim would."""
    async with session_scope(sessions) as session:
        row = await session.get(Notification, notification_id)
        assert row is not None
        row.status = NotificationStatus.SENDING
        row.lease_owner = owner
        row.lease_expires_at = NOW + timedelta(seconds=LEASE)


async def notifications_of(sessions: async_sessionmaker[AsyncSession]) -> list[Notification]:
    """Read every queued notification, oldest first."""
    async with sessions() as session:
        rows = await session.execute(sa.select(Notification).order_by(Notification.id))
        return list(rows.scalars())


async def entries_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[LogEntry]:
    """Read one run's timeline, oldest first."""
    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == run_id).order_by(LogEntry.id))
        return list(rows.scalars())


# -- render_template -------------------------------------------------------------


def test_a_template_resolves_the_run_facts_it_names() -> None:
    context = build_context(a_run(), a_pipeline())
    assert render_template("${run.pipeline} run ${run.status}", context) == "nightly run failed"


def test_a_template_resolves_a_nested_path() -> None:
    context = build_context(a_run(params={"day": "2026-08-28"}), a_pipeline())
    assert render_template("loading ${run.params.day}", context) == "loading 2026-08-28"


def test_an_unresolvable_reference_is_left_verbatim_rather_than_blanked() -> None:
    context = build_context(a_run(), a_pipeline())
    assert render_template("${run.typo} and ${nothing.at.all}", context) == "${run.typo} and ${nothing.at.all}"
    assert render_template("${run.status.deeper}", context) == "${run.status.deeper}"


def test_a_template_with_no_references_is_its_own_rendering() -> None:
    assert render_template("the nightly load needs looking at", {}) == "the nightly load needs looking at"


def test_a_boolean_renders_as_a_word_and_a_null_renders_as_nothing() -> None:
    context: JsonMap = {"flag": True, "off": False, "nothing": None}
    assert render_template("${flag} ${off}", context) == "true false"
    # A null is a resolved value, not a missing one, so it renders as empty rather than as
    # the reference printed back.
    assert render_template("${nothing}", context) == ""


def test_an_empty_reference_names_nothing_and_is_left_alone() -> None:
    # Rendering it would splice a Python dict repr into the alert, so it is left visible.
    assert render_template("${ }", {"run": {"pipeline": "nightly"}}) == "${ }"
    assert render_template("${}", {"run": {"pipeline": "nightly"}}) == "${}"


# -- build_context ---------------------------------------------------------------


def test_the_context_gathers_the_run_facts_under_one_namespace() -> None:
    run = a_run(params={"day": "2026-08-28"})
    facts = run_facts(build_context(run, a_pipeline()))
    assert facts["id"] == str(run.id)
    assert facts["status"] == "failed"
    assert facts["pipeline"] == "nightly"
    assert facts["error"] == "the loader gave up"
    assert facts["params"] == {"day": "2026-08-28"}
    assert facts["trigger"] == "morten"
    assert facts["started_at"] == NOW.isoformat()


def test_the_trigger_falls_back_to_the_kind_when_nothing_is_labelled() -> None:
    run = a_run()
    run.triggered_by_label = None
    assert run_facts(build_context(run, a_pipeline()))["trigger"] == "adhoc"


def test_the_duration_is_computed_when_both_timestamps_exist() -> None:
    assert run_facts(build_context(a_run(), a_pipeline()))["duration_ms"] == 90250


@pytest.mark.parametrize(
    ("started_at", "finished_at"),
    [(None, NOW), (NOW, None), (None, None)],
)
def test_the_duration_is_none_when_a_timestamp_is_missing(
    started_at: datetime | None, finished_at: datetime | None
) -> None:
    facts = run_facts(build_context(a_run(started_at=started_at, finished_at=finished_at), a_pipeline()))
    assert facts["duration_ms"] is None


def test_the_url_is_built_only_when_the_instance_knows_its_own_address() -> None:
    run = a_run()
    assert run_facts(build_context(run, a_pipeline()))["url"] is None
    linked = build_context(run, a_pipeline(), base_url="https://dirigent.test/")
    assert run_facts(linked)["url"] == f"https://dirigent.test/runs/{run.id}"


# -- create_rule, and the rest of the rule surface --------------------------------


async def test_a_rule_naming_an_uninstalled_notifier_is_refused_with_what_is_installed(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    request = AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="carrier-pigeon")
    with pytest.raises(AlertError) as raised:
        await declare(sessions, services, request)
    assert "carrier-pigeon" in str(raised.value)
    assert "exploding, interfering, recording" in str(raised.value)


async def test_an_instance_with_no_channel_says_so(
    sessions: async_sessionmaker[AsyncSession], bare_services: EngineServices
) -> None:
    request = AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    with pytest.raises(AlertError, match="none are installed"):
        await declare(sessions, bare_services, request)


async def test_a_duplicate_rule_name_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    request = AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    await declare(sessions, services, request)
    with pytest.raises(AlertError, match="already exists"):
        await declare(sessions, services, request)


async def test_a_pipeline_scoped_rule_naming_no_pipeline_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    request = AlertRuleRequest(
        code="watch", event=AlertEvent.RUN_FAILED, notifier="recording", scope=AlertScope.PIPELINE
    )
    with pytest.raises(AlertError, match="has to name the pipeline"):
        await declare(sessions, services, request)


async def test_a_pipeline_scoped_rule_naming_an_unknown_pipeline_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    request = AlertRuleRequest(
        code="watch",
        event=AlertEvent.RUN_FAILED,
        notifier="recording",
        scope=AlertScope.PIPELINE,
        pipeline="no-such-thing",
    )
    with pytest.raises(AlertError, match="no pipeline coded 'no-such-thing'"):
        await declare(sessions, services, request)


async def test_a_rule_naming_an_unknown_connection_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    request = AlertRuleRequest(
        code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording", connection="no-such-desk"
    )
    with pytest.raises(AlertError, match="no connection coded 'no-such-desk'"):
        await declare(sessions, services, request)


async def test_a_rule_records_its_scope_its_channel_and_its_throttle(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await stored_run(sessions, services, pipeline="nightly")
    connection = await a_connection(sessions, services)
    rule = await declare(
        sessions,
        services,
        AlertRuleRequest(
            code="page-ops",
            event=AlertEvent.RUN_FAILED,
            notifier="recording",
            scope=AlertScope.PIPELINE,
            pipeline="nightly",
            connection="desk",
            template="${run.pipeline} is unhappy",
            throttle=timedelta(minutes=15),
        ),
    )
    assert rule.pipeline_id is not None
    assert rule.connection_id == connection.id
    assert rule.throttle_seconds == 900
    assert rule.active is True
    assert rule.last_sent_at is None


async def test_the_rules_can_be_listed_found_and_deleted(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await declare(sessions, services, AlertRuleRequest(code="zulu", event=AlertEvent.RUN_FAILED, notifier="recording"))
    await declare(sessions, services, AlertRuleRequest(code="alpha", event=AlertEvent.RUN_STUCK, notifier="recording"))
    async with sessions() as session:
        assert [rule.code for rule in await list_rules(session)] == ["zulu", "alpha"], "declared order"
        assert await find_rule(session, "nothing-like-it") is None
    async with session_scope(sessions) as session:
        found = await find_rule(session, "zulu")
        assert found is not None
        await delete_rule(session, found)
    async with sessions() as session:
        assert [rule.code for rule in await list_rules(session)] == ["alpha"]


# -- matching_rules and the throttle ---------------------------------------------


async def test_a_global_rule_matches_any_pipeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with sessions() as session:
        matched = await matching_rules(session, AlertEvent.RUN_FAILED, uuid4())
    assert [rule.code for rule in matched] == ["page-ops"]


async def test_a_pipeline_scoped_rule_matches_only_its_own_pipeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services, pipeline="nightly")
    await declare(
        sessions,
        services,
        AlertRuleRequest(
            code="watch-nightly",
            event=AlertEvent.RUN_FAILED,
            notifier="recording",
            scope=AlertScope.PIPELINE,
            pipeline="nightly",
        ),
    )
    async with sessions() as session:
        assert len(await matching_rules(session, AlertEvent.RUN_FAILED, run.pipeline_id)) == 1
        assert await matching_rules(session, AlertEvent.RUN_FAILED, uuid4()) == []


async def test_an_inactive_rule_never_matches(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    rule = await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(AlertRule, rule.id)
        assert stored is not None
        stored.active = False
    async with sessions() as session:
        assert await matching_rules(session, AlertEvent.RUN_FAILED, uuid4()) == []


async def test_a_paused_rule_never_matches(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    rule = await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(AlertRule, rule.id)
        assert stored is not None
        await set_paused(session, stored, paused=True)
    async with sessions() as session:
        assert await matching_rules(session, AlertEvent.RUN_FAILED, uuid4()) == []


async def test_a_resumed_rule_matches_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    rule = await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(AlertRule, rule.id)
        assert stored is not None
        await set_paused(session, stored, paused=True)
        await set_paused(session, stored, paused=False)
    async with sessions() as session:
        assert len(await matching_rules(session, AlertEvent.RUN_FAILED, uuid4())) == 1


async def test_a_rule_is_declared_unpaused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    rule = await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    assert rule.paused is False


async def test_a_rule_for_another_event_never_matches(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await declare(
        sessions, services, AlertRuleRequest(code="cheer", event=AlertEvent.RUN_SUCCEEDED, notifier="recording")
    )
    async with sessions() as session:
        assert await matching_rules(session, AlertEvent.RUN_FAILED, uuid4()) == []
        assert len(await matching_rules(session, AlertEvent.RUN_SUCCEEDED, uuid4())) == 1


@pytest.mark.parametrize(
    ("elapsed", "throttled"),
    [(timedelta(minutes=5), True), (timedelta(minutes=14, seconds=59), True), (timedelta(minutes=15), False)],
)
async def test_a_throttled_rule_raises_again_only_once_its_window_has_passed(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    elapsed: timedelta,
    throttled: bool,
) -> None:
    run = await stored_run(sessions, services, pipeline="nightly")
    rule = await declare(
        sessions,
        services,
        AlertRuleRequest(
            code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording", throttle=timedelta(minutes=15)
        ),
    )
    async with session_scope(sessions) as session:
        settled = await session.get(Run, run.id)
        assert settled is not None
        await raise_for_run(session, services, settled, AlertEvent.RUN_FAILED, now=NOW)

    async with sessions() as session:
        stored = await session.get(AlertRule, rule.id)
        assert stored is not None
        opens = await throttled_until(session, stored, run.pipeline_id, NOW + elapsed)
    assert (opens is not None) is throttled


async def test_a_rule_with_no_throttle_always_matches(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    rule = await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with sessions() as session:
        stored = await session.get(AlertRule, rule.id)
        assert stored is not None
        assert await throttled_until(session, stored, uuid4(), NOW) is None


async def test_a_suppressed_alert_says_so_on_the_run_it_was_suppressed_for(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A throttle that leaves nothing behind reads exactly like a rule that never matched."""
    await declare(
        sessions,
        services,
        AlertRuleRequest(
            code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording", throttle=timedelta(minutes=15)
        ),
    )
    first = await stored_run(sessions, services, pipeline="nightly")
    async with session_scope(sessions) as session:
        settled = await session.get(Run, first.id)
        assert settled is not None
        assert await raise_for_run(session, services, settled, AlertEvent.RUN_FAILED, now=NOW)

    second = await stored_run(sessions, services, pipeline="nightly")
    async with session_scope(sessions) as session:
        settled = await session.get(Run, second.id)
        assert settled is not None
        queued = await raise_for_run(session, services, settled, AlertEvent.RUN_FAILED, now=NOW + timedelta(minutes=1))
    assert queued == [], "the window has not passed"

    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == second.id))
        entries = list(rows.scalars())
    assert len(entries) == 1, "the suppression is on the run it was suppressed for"
    assert "suppressed by its throttle window" in entries[0].message
    assert entries[0].fields is not None
    assert entries[0].fields["throttle"] == "15m"
    assert entries[0].fields["opens_at"] == (NOW + timedelta(minutes=15)).isoformat()


async def test_a_global_rule_throttles_each_pipeline_on_its_own(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """One noisy pipeline must not silence every other pipeline the rule watches."""
    await declare(
        sessions,
        services,
        AlertRuleRequest(
            code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording", throttle=timedelta(minutes=15)
        ),
    )
    noisy = await stored_run(sessions, services, pipeline="nightly")
    async with session_scope(sessions) as session:
        settled = await session.get(Run, noisy.id)
        assert settled is not None
        assert await raise_for_run(session, services, settled, AlertEvent.RUN_FAILED, now=NOW)

    quiet = await stored_run(sessions, services, pipeline="hourly")
    async with session_scope(sessions) as session:
        settled = await session.get(Run, quiet.id)
        assert settled is not None
        queued = await raise_for_run(session, services, settled, AlertEvent.RUN_FAILED, now=NOW + timedelta(minutes=1))
    assert [message.notifier for message in queued] == ["recording"], "another pipeline is not silenced"


async def test_a_delivery_retry_does_not_widen_the_throttle_window(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The window is measured from when the message was raised, not from its next retry."""
    run = await stored_run(sessions, services, pipeline="nightly")
    rule = await declare(
        sessions,
        services,
        AlertRuleRequest(
            code="page-ops", event=AlertEvent.RUN_FAILED, notifier="exploding", throttle=timedelta(seconds=10)
        ),
    )
    async with session_scope(sessions) as session:
        settled = await session.get(Run, run.id)
        assert settled is not None
        await raise_for_run(session, services, settled, AlertEvent.RUN_FAILED, now=NOW)
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is False
        assert claimed.available_at > NOW + timedelta(seconds=10)

    async with sessions() as session:
        stored = await session.get(AlertRule, rule.id)
        assert stored is not None
        assert await throttled_until(session, stored, run.pipeline_id, NOW + timedelta(seconds=11)) is None


# -- raising -----------------------------------------------------------------------


async def test_raising_queues_one_message_per_matching_rule_and_stamps_the_rules(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    await declare(
        sessions,
        services,
        AlertRuleRequest(code="tell-slack", event=AlertEvent.RUN_FAILED, notifier="recording", template="down again"),
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        queued = await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW)
    assert len(queued) == 2
    assert {notification.subject for notification in queued} == {"nightly run failed", "down again"}
    assert all(notification.status is NotificationStatus.PENDING for notification in queued)
    assert all(notification.available_at == NOW for notification in queued)

    async with sessions() as session:
        rules = await list_rules(session)
    assert [rule.last_sent_at for rule in rules] == [NOW, NOW]


async def test_the_default_subject_is_the_one_the_module_declares(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        queued = await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW)
    assert queued[0].subject == render_template(DEFAULT_TEMPLATE, queued[0].context)


async def test_raising_writes_the_alert_into_the_runs_own_timeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW)
    entries = await entries_of(sessions, run.id)
    assert len(entries) == 1
    assert entries[0].level is LogLevel.INFO
    assert "'page-ops' queued for delivery through 'recording'" in entries[0].message
    assert entries[0].fields == {"event": "run_failed", "notifier": "recording"}


async def test_a_queued_message_carries_the_link_back_when_the_instance_has_one(
    sessions: async_sessionmaker[AsyncSession], linked_services: EngineServices
) -> None:
    run = await stored_run(sessions, linked_services)
    await declare(
        sessions, linked_services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        queued = await raise_for_run(session, linked_services, stored, AlertEvent.RUN_FAILED, now=NOW)
    assert run_facts(queued[0].context)["url"] == f"https://dirigent.test/runs/{run.id}"
    assert f"url: https://dirigent.test/runs/{run.id}" in queued[0].body
    assert "duration_ms: 120000" in queued[0].body


async def test_a_run_no_rule_cares_about_queues_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW) == []
    assert await notifications_of(sessions) == []
    assert await entries_of(sessions, run.id) == []


@pytest.mark.parametrize(("status", "event"), sorted(EVENT_FOR_STATUS.items()))
async def test_a_terminal_status_raises_the_event_it_maps_to(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    status: RunStatus,
    event: AlertEvent,
) -> None:
    run = await stored_run(sessions, services, status=status)
    await declare(sessions, services, AlertRuleRequest(code="watch", event=event, notifier="recording"))
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        queued = await raise_for_status(session, services, stored, status, now=NOW)
    assert [notification.event for notification in queued] == [event]


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.QUEUED, RunStatus.RUNNING])
async def test_a_status_that_maps_to_no_event_raises_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, status: RunStatus
) -> None:
    run = await stored_run(sessions, services, status=status)
    for event in AlertEvent:
        await declare(
            sessions,
            services,
            AlertRuleRequest(code=f"watch-{event.value.replace('_', '-')}", event=event, notifier="recording"),
        )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert await raise_for_status(session, services, stored, status, now=NOW) == []
    assert await notifications_of(sessions) == []


# -- the deduplication -------------------------------------------------------------


async def test_a_rule_says_one_thing_about_one_run_once(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    for moment in (NOW, NOW + timedelta(minutes=1)):
        async with session_scope(sessions) as session:
            stored = await session.get(Run, run.id)
            assert stored is not None
            await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=moment)
    assert len(await notifications_of(sessions)) == 1
    assert len(await entries_of(sessions, run.id)) == 1


async def test_the_same_rule_still_speaks_for_a_different_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    first = await stored_run(sessions, services, pipeline="nightly")
    second = await stored_run(sessions, services, pipeline="hourly")
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    for run in (first, second):
        async with session_scope(sessions) as session:
            stored = await session.get(Run, run.id)
            assert stored is not None
            await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW)
    assert {notification.run_id for notification in await notifications_of(sessions)} == {first.id, second.id}


async def test_a_sweeper_redetecting_a_stuck_run_pages_once(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services, status=RunStatus.RUNNING)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_STUCK, notifier="recording")
    )
    queued: list[int] = []
    for sweep in range(4):
        async with session_scope(sessions) as session:
            queued.append(await raise_for_stuck(session, services, [run.id], now=NOW + timedelta(seconds=30 * sweep)))
    assert queued == [1, 0, 0, 0]
    assert len(await notifications_of(sessions)) == 1


async def test_a_sweep_with_nothing_stuck_queues_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_STUCK, notifier="recording")
    )
    async with session_scope(sessions) as session:
        assert await raise_for_stuck(session, services, [], now=NOW) == 0


# -- claiming ----------------------------------------------------------------------


async def test_claiming_leases_the_next_due_message_and_counts_the_attempt(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await queued_message(sessions, services)
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        assert claimed.status is NotificationStatus.SENDING
        assert claimed.lease_owner == OWNER
        assert claimed.lease_expires_at == NOW + timedelta(seconds=LEASE)
        assert claimed.attempt == 1


async def test_claiming_an_empty_queue_returns_nothing(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        assert await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE) is None


async def test_a_message_whose_backoff_has_not_elapsed_is_not_claimable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await enqueue(
        sessions,
        event=AlertEvent.RUN_FAILED,
        notifier="recording",
        subject="later",
        available_at=NOW + timedelta(minutes=1),
    )
    async with session_scope(sessions) as session:
        assert await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE) is None
        claimed = await claim_notification(session, owner=OWNER, now=NOW + timedelta(minutes=1), lease_seconds=LEASE)
        assert claimed is not None


# -- sending -----------------------------------------------------------------------


async def test_a_delivered_alert_is_marked_sent_released_and_written_into_the_timeline(
    sessions: async_sessionmaker[AsyncSession], linked_services: EngineServices
) -> None:
    run = await stored_run(sessions, linked_services)
    await declare(
        sessions, linked_services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await raise_for_run(session, linked_services, stored, AlertEvent.RUN_FAILED, now=NOW)
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        assert await send_notification(session, linked_services, claimed, owner=OWNER, now=NOW) is True
        assert claimed.status is NotificationStatus.SENT
        assert claimed.sent_at == NOW
        assert claimed.error is None
        assert claimed.lease_owner is None
        assert claimed.lease_expires_at is None

    message, config = RecordingNotifier.sent[0]
    assert message.event == "run_failed"
    assert message.subject == "nightly run failed"
    assert message.pipeline == "nightly"
    assert message.run_id == run.id
    assert message.url == f"https://dirigent.test/runs/{run.id}"
    assert isinstance(config, RecordingConfig)

    entries = await entries_of(sessions, run.id)
    assert [entry.level for entry in entries] == [LogLevel.INFO, LogLevel.INFO]
    assert "alert delivered through 'recording'" in entries[1].message


async def test_a_refused_delivery_goes_back_on_the_queue_with_a_doubling_backoff(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await queued_message(sessions, services, notifier="exploding")
    backoff = services.settings.notification_backoff.total_seconds()
    delays: list[float] = []
    moment = NOW
    for attempt in (1, 2, 3):
        async with session_scope(sessions) as session:
            claimed = await claim_notification(session, owner=OWNER, now=moment, lease_seconds=LEASE)
            assert claimed is not None
            assert claimed.attempt == attempt
            assert await send_notification(session, services, claimed, owner=OWNER, now=moment) is False
            assert claimed.status is NotificationStatus.PENDING
            assert claimed.lease_owner is None
            assert claimed.lease_expires_at is None
            assert claimed.error == "RuntimeError: the channel is on fire"
            delays.append((claimed.available_at - moment).total_seconds())
            moment = claimed.available_at
    assert delays == [backoff, backoff * 2, backoff * 4]


async def test_a_delivery_that_runs_out_of_budget_fails_terminally_in_the_runs_timeline(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="exploding")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW)
    budget = services.settings.notification_max_attempts
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        claimed.attempt = budget
        assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is False
        assert claimed.status is NotificationStatus.FAILED
        assert claimed.error == "RuntimeError: the channel is on fire"
        assert claimed.lease_expires_at is None

    entries = await entries_of(sessions, run.id)
    assert entries[-1].level is LogLevel.ERROR
    assert f"after {budget} attempts" in entries[-1].message
    assert "the channel is on fire" in entries[-1].message


async def test_a_notifier_missing_from_this_worker_fails_the_delivery_rather_than_the_worker(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await enqueue(
        sessions, event=AlertEvent.RUN_FAILED, notifier="carrier-pigeon", subject="unreachable", available_at=NOW
    )
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is False
        assert claimed.status is NotificationStatus.PENDING
        assert "is not installed on this worker" in (claimed.error or "")


async def test_a_message_with_no_run_and_no_context_still_delivers(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await enqueue(
        sessions, event=AlertEvent.RUN_SUCCEEDED, notifier="recording", subject="bare", context={}, available_at=NOW
    )
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is True
    message, _ = RecordingNotifier.sent[0]
    assert message.pipeline is None
    assert message.url is None
    assert message.context == {}


async def test_a_delivery_whose_lease_was_reclaimed_leaves_the_new_owners_row_alone(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A send that outlasts its lease must not overwrite the outcome of whoever has the row."""
    notification = await enqueue(
        sessions, event=AlertEvent.RUN_SUCCEEDED, notifier="interfering", subject="slow", available_at=NOW
    )
    interference.during = lambda: reclaim(sessions, notification.id, owner="other-worker")
    async with session_scope(sessions) as session:
        assert await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE) is not None
    with capture_logs() as logged:
        async with session_scope(sessions) as session:
            claimed = await session.get(Notification, notification.id)
            assert claimed is not None
            assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is False

    stored = await reload_notification(sessions, notification.id)
    assert stored.status is NotificationStatus.SENDING
    assert stored.lease_owner == "other-worker"
    assert stored.sent_at is None
    assert stored.error is None
    assert [entry["event"] for entry in logged] == ["lease lost, notification outcome discarded"]
    assert logged[0]["holder"] == "other-worker"


async def test_a_refused_delivery_whose_lease_was_reclaimed_does_not_reschedule_the_new_owners_row(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    notification = await enqueue(
        sessions, event=AlertEvent.RUN_SUCCEEDED, notifier="interfering", subject="slow", available_at=NOW
    )
    interference.during = lambda: reclaim(sessions, notification.id, owner="other-worker")
    interference.refuses = True
    async with session_scope(sessions) as session:
        assert await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE) is not None
    async with session_scope(sessions) as session:
        claimed = await session.get(Notification, notification.id)
        assert claimed is not None
        assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is False

    stored = await reload_notification(sessions, notification.id)
    assert stored.status is NotificationStatus.SENDING
    assert stored.lease_owner == "other-worker"
    assert stored.error is None
    assert stored.available_at == NOW


# -- notifier_config ---------------------------------------------------------------


def test_a_channel_with_no_connection_gets_its_models_defaults(services: EngineServices) -> None:
    config = notifier_config(services, services.host.notifiers["recording"], None)
    assert isinstance(config, RecordingConfig)
    assert config.label == "default"
    assert config.token is None


async def test_a_channel_with_a_connection_gets_the_decrypted_config(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    connection = await a_connection(sessions, services)
    async with sessions() as session:
        stored = await session.get(Connection, connection.id)
        assert stored is not None
        config = notifier_config(services, services.host.notifiers["recording"], stored)
    assert isinstance(config, RecordingConfig)
    assert config.label == "ops"
    assert config.token is not None
    assert config.token.get_secret_value() == "s3cret"


async def test_a_delivery_through_a_connection_opens_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await a_connection(sessions, services)
    await queued_message(sessions, services, connection="desk")
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner=OWNER, now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        assert await send_notification(session, services, claimed, owner=OWNER, now=NOW) is True
    _, config = RecordingNotifier.sent[0]
    assert isinstance(config, RecordingConfig)
    assert config.label == "ops"


# -- queue_test_message ------------------------------------------------------------


async def test_a_test_message_is_queued_attached_to_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        queued = await queue_test_message(session, services, notifier="recording")
    assert queued.alert_rule_id is None
    assert queued.run_id is None
    assert queued.subject == "dirigent test alert"
    assert queued.status is NotificationStatus.PENDING
    assert run_facts(queued.context)["pipeline"] == "(test)"


async def test_a_test_message_through_an_uninstalled_channel_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        with pytest.raises(AlertError, match="no notifier 'carrier-pigeon' is installed"):
            await queue_test_message(session, services, notifier="carrier-pigeon")


# -- listing and recovery ----------------------------------------------------------


async def test_notifications_list_newest_first_and_can_be_scoped_to_one_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await stored_run(sessions, services)
    await declare(
        sessions, services, AlertRuleRequest(code="page-ops", event=AlertEvent.RUN_FAILED, notifier="recording")
    )
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await raise_for_run(session, services, stored, AlertEvent.RUN_FAILED, now=NOW)
        await queue_test_message(session, services, notifier="recording")
    async with sessions() as session:
        assert len(await list_notifications(session)) == 2
        scoped = await list_notifications(session, run_id=run.id)
    assert [notification.run_id for notification in scoped] == [run.id]


async def test_a_lease_that_outlived_its_worker_goes_back_on_the_queue(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await queued_message(sessions, services)
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner="dead-worker", now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        claimed_id = claimed.id
    async with session_scope(sessions) as session:
        assert await recover_notifications(session, now=NOW + timedelta(seconds=LEASE + 1)) == 1
    recovered = await reload_notification(sessions, claimed_id)
    assert recovered.status is NotificationStatus.PENDING
    assert recovered.lease_owner is None
    assert recovered.lease_expires_at is None
    assert recovered.available_at == NOW + timedelta(seconds=LEASE + 1)


async def test_a_lease_that_is_still_valid_is_left_alone(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await queued_message(sessions, services)
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner="busy-worker", now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        claimed_id = claimed.id
    async with session_scope(sessions) as session:
        assert await recover_notifications(session, now=NOW + timedelta(seconds=LEASE - 1)) == 0
    held = await reload_notification(sessions, claimed_id)
    assert held.status is NotificationStatus.SENDING
    assert held.lease_owner == "busy-worker"


async def test_a_lease_renewed_while_the_sweep_runs_is_not_taken_from_its_holder(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Recovery is one conditional statement, so a renewal decides the row rather than losing to it."""
    await queued_message(sessions, services, subject="renewed")
    await queued_message(sessions, services, subject="abandoned")
    async with session_scope(sessions) as session:
        renewed = await claim_notification(session, owner="live-worker", now=NOW, lease_seconds=LEASE)
        abandoned = await claim_notification(session, owner="dead-worker", now=NOW, lease_seconds=LEASE)
        assert renewed is not None
        assert abandoned is not None
        renewed_id, abandoned_id = renewed.id, abandoned.id
    async with session_scope(sessions) as session:
        assert await renew_lease(
            session, renewed_id, owner="live-worker", lease_seconds=LEASE, now=NOW + timedelta(seconds=LEASE)
        )

    async with session_scope(sessions) as session:
        assert await recover_notifications(session, now=NOW + timedelta(seconds=LEASE + 1)) == 1

    held = await reload_notification(sessions, renewed_id)
    assert held.status is NotificationStatus.SENDING
    assert held.lease_owner == "live-worker"
    assert held.lease_expires_at == NOW + timedelta(seconds=LEASE * 2)
    requeued = await reload_notification(sessions, abandoned_id)
    assert requeued.status is NotificationStatus.PENDING
    assert requeued.lease_owner is None


async def test_a_notification_already_delivered_is_not_put_back_on_the_queue(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A delivery that landed on an expired lease stays sent: recovery only moves sending rows."""
    await queued_message(sessions, services)
    async with session_scope(sessions) as session:
        claimed = await claim_notification(session, owner="slow-worker", now=NOW, lease_seconds=LEASE)
        assert claimed is not None
        claimed_id = claimed.id
    async with session_scope(sessions) as session:
        # The lease fields are left where they were, which is what makes this row look
        # recoverable to everything but the status the delivery wrote.
        await session.execute(
            sa.update(Notification).where(Notification.id == claimed_id).values(status=NotificationStatus.SENT)
        )

    async with session_scope(sessions) as session:
        assert await recover_notifications(session, now=NOW + timedelta(seconds=LEASE + 1)) == 0

    delivered = await reload_notification(sessions, claimed_id)
    assert delivered.status is NotificationStatus.SENT
    assert delivered.lease_owner == "slow-worker"


# -- the dispatcher ----------------------------------------------------------------


async def test_the_dispatcher_delivers_everything_due_and_reports_the_count(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    for index in range(3):
        await queued_message(sessions, services, subject=f"message {index}")
    dispatcher = NotificationDispatcher(sessions=sessions, services=services, owner=OWNER)
    assert await dispatcher.drain(now=NOW) == 3
    assert [message.subject for message, _ in RecordingNotifier.sent] == ["message 0", "message 1", "message 2"]
    assert all(row.status is NotificationStatus.SENT for row in await notifications_of(sessions))
    assert await dispatcher.drain(now=NOW) == 0


async def test_one_undeliverable_message_never_rolls_back_the_ones_beside_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await queued_message(sessions, services, notifier="exploding", subject="bad")
    await queued_message(sessions, services, subject="good")
    dispatcher = NotificationDispatcher(sessions=sessions, services=services, owner=OWNER)
    assert await dispatcher.drain(now=NOW) == 1
    by_subject = {row.subject: row for row in await notifications_of(sessions)}
    assert by_subject["good"].status is NotificationStatus.SENT
    assert by_subject["bad"].status is NotificationStatus.PENDING
    assert by_subject["bad"].error == "RuntimeError: the channel is on fire"
    assert by_subject["bad"].available_at > NOW


async def test_the_dispatcher_stops_at_its_own_ceiling(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    for index in range(3):
        await queued_message(sessions, services, subject=f"message {index}")
    dispatcher = NotificationDispatcher(sessions=sessions, services=services, owner=OWNER, max_per_pass=2)
    assert await dispatcher.drain(now=NOW) == 2
    assert len(RecordingNotifier.sent) == 2


async def test_a_slow_delivery_keeps_its_lease_refreshed_past_its_original_expiry(
    sessions: async_sessionmaker[AsyncSession], brief_services: EngineServices
) -> None:
    notification = await enqueue(
        sessions, event=AlertEvent.RUN_SUCCEEDED, notifier="interfering", subject="slow", available_at=NOW
    )
    seen: list[datetime] = []

    async def wait_for_a_renewal() -> None:
        """Block the delivery until the heartbeat has pushed the lease out, or give up."""
        original = (await reload_notification(sessions, notification.id)).lease_expires_at
        assert original is not None
        for _ in range(200):
            current = (await reload_notification(sessions, notification.id)).lease_expires_at
            if current is not None and current > original:
                seen.append(current)
                return
            await asyncio.sleep(0.05)

    interference.during = wait_for_a_renewal
    dispatcher = NotificationDispatcher(sessions=sessions, services=brief_services, owner=OWNER)
    assert await dispatcher.drain() == 1
    assert seen, "the lease was never renewed while the delivery was in flight"
    assert (await reload_notification(sessions, notification.id)).status is NotificationStatus.SENT


# -- putting one back on the queue -------------------------------------------------


async def test_a_retry_makes_a_failed_notification_due_now_with_its_budget_back(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued = await queued_message(sessions, services)
    async with session_scope(sessions) as session:
        row = await session.get(Notification, queued.id)
        assert row is not None
        row.status = NotificationStatus.FAILED
        row.attempt = 5
        row.error = "the endpoint answered HTTP 500"
        row.available_at = NOW + timedelta(hours=1)
    async with session_scope(sessions) as session:
        row = await session.get(Notification, queued.id)
        assert row is not None
        await retry_notification(session, row, now=NOW)
    again = await reload_notification(sessions, queued.id)
    assert again.status is NotificationStatus.PENDING
    assert again.available_at == NOW
    assert again.attempt == 0
    assert again.error is None


async def test_a_notification_a_worker_is_holding_is_not_handed_to_a_second_one(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued = await queued_message(sessions, services)
    async with session_scope(sessions) as session:
        row = await session.get(Notification, queued.id)
        assert row is not None
        row.status = NotificationStatus.SENDING
        row.lease_owner = "worker-1"
    async with session_scope(sessions) as session:
        row = await session.get(Notification, queued.id)
        assert row is not None
        with pytest.raises(AlertError, match="wait for it"):
            await retry_notification(session, row, now=NOW)
