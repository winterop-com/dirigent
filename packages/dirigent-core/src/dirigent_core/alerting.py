"""Alerting rules and channels as data, with delivery queued and retried like any other work.

A rule says one thing about one run once: the unique constraint on
``(alert_rule_id, run_id, event)`` is the deduplication, and the throttle window is a second,
coarser guard against a flapping pipeline.
"""

import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AlertEvent, AlertScope, LogLevel, NotificationStatus, RunStatus
from dirigent_common import (
    EntityName,
    JsonMap,
    RenderTooLarge,
    TemplateError,
    compile_template,
    format_duration,
    render,
)
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import load_definition
from dirigent_core.engine.services import EngineServices
from dirigent_core.logging import get_logger
from dirigent_core.models import (
    AlertRule,
    Connection,
    LogEntry,
    Notification,
    Pipeline,
    PipelineVersion,
    Run,
    utcnow,
)
from dirigent_plugin import AlertMessage, Notifier

if TYPE_CHECKING:
    from dirigent_core.reporting import RunFacts

EVENT_FOR_STATUS: dict[RunStatus, AlertEvent] = {
    RunStatus.FAILED: AlertEvent.RUN_FAILED,
    RunStatus.COMPLETED_WITH_ERRORS: AlertEvent.RUN_COMPLETED_WITH_ERRORS,
    RunStatus.SUCCEEDED: AlertEvent.RUN_SUCCEEDED,
}

DEFAULT_TEMPLATE = "{{ run.pipeline }} run {{ run.status }}"

#: The characters a subject is cut to, which is what a subject line is.
SUBJECT_CAP: Final = 200

#: What a subject may render before it is refused: room to be cut rather than lost.
SUBJECT_RENDER_CAP: Final = 8 * SUBJECT_CAP

CLAIM_LIMIT = 1

#: How many times a lease is renewed over its own length while a delivery is in flight.
RENEWALS_PER_LEASE = 3

_logger = get_logger("alerting")


class AlertError(Exception):
    """An alert rule could not be declared, found, or delivered."""


class AlertRuleRequest(BaseModel):
    """What it takes to declare an alert rule, from the API or the CLI."""

    model_config = ConfigDict(frozen=True)

    code: EntityName
    name: str | None = None
    description: str | None = None
    event: AlertEvent
    notifier: str
    scope: AlertScope = AlertScope.GLOBAL
    pipeline: str | None = None
    connection: str | None = None
    template: str | None = None
    body: str | None = None
    throttle: timedelta = timedelta(0)


def _as_text(value: JsonValue) -> str:
    """Render a resolved value the way a message wants to read it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def build_context(
    run: Run, pipeline: Pipeline, *, base_url: str | None = None, report_url: str | None = None
) -> JsonMap:
    """Gather the facts a template may read, under the one namespace it has.

    A flat snapshot rather than a live handle: the notification is delivered later, and must
    describe the run as it was when the alert fired.
    """
    duration = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else None
    return {
        "run": {
            "id": str(run.id),
            "status": run.status.value,
            "pipeline": pipeline.code,
            "error": run.error,
            "params": dict(run.params),
            "trigger": run.triggered_by_label or run.triggered_by_kind.value,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "duration_ms": round(duration * 1000) if duration is not None else None,
            "url": f"{base_url.rstrip('/')}/runs/{run.id}" if base_url else None,
            "report_url": report_url,
        }
    }


def report_url_for(base_url: str | None, artifact_id: UUID | None) -> str | None:
    """Name where a rendered report document is read, when there is one and somewhere to read it."""
    if base_url is None or artifact_id is None:
        return None
    return f"{base_url.rstrip('/')}/api/v1/artifacts/{artifact_id}"


async def find_rule(session: AsyncSession, code: str) -> AlertRule | None:
    """Find one alert rule by code."""
    found = await session.execute(sa.select(AlertRule).where(AlertRule.code == code))
    return found.scalar_one_or_none()


async def list_rules(
    session: AsyncSession,
    *,
    after: UUID | None = None,
    limit: int | None = None,
) -> list[AlertRule]:
    """List every alert rule in id order, which is the order they were declared in."""
    statement = sa.select(AlertRule).order_by(AlertRule.id)
    if after is not None:
        statement = statement.where(AlertRule.id > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def create_rule(session: AsyncSession, services: EngineServices, request: AlertRuleRequest) -> AlertRule:
    """Declare an alert rule, refusing a notifier or a scope this instance cannot honour."""
    if request.notifier not in services.host.notifiers:
        installed = ", ".join(sorted(services.host.notifiers)) or "none are installed"
        raise AlertError(f"no notifier {request.notifier!r} is installed ({installed})")
    if await find_rule(session, request.code) is not None:
        raise AlertError(f"an alert rule coded {request.code!r} already exists")
    check_templates(template=request.template, body=request.body)
    pipeline_id = await _scope_pipeline(session, request)
    connection_id = await _connection_id(session, request.connection) if request.connection else None
    rule = AlertRule(
        code=request.code,
        name=request.name,
        description=request.description,
        event=request.event,
        scope=request.scope,
        pipeline_id=pipeline_id,
        notifier=request.notifier,
        connection_id=connection_id,
        template=request.template,
        body=request.body,
        throttle_seconds=int(request.throttle.total_seconds()),
    )
    session.add(rule)
    await session.flush()
    _logger.info("alert rule created", rule=rule.code, alert_event=rule.event.value, notifier=rule.notifier)
    return rule


def check_templates(*, template: str | None = None, body: str | None = None) -> None:
    """Refuse a subject or a body that does not compile, naming the field and the line."""
    for field, source in (("template", template), ("body", body)):
        if source is None:
            continue
        try:
            compile_template(source)
        except TemplateError as error:
            raise AlertError(f"{field} is not a Jinja template: {error}") from error


async def _scope_pipeline(session: AsyncSession, request: AlertRuleRequest) -> UUID | None:
    """Resolve the pipeline a rule is scoped to, refusing a scope that names nothing."""
    if request.scope is AlertScope.GLOBAL:
        return None
    if not request.pipeline:
        raise AlertError("a pipeline-scoped rule has to name the pipeline it watches")
    found = await session.execute(sa.select(Pipeline).where(Pipeline.code == request.pipeline))
    pipeline = found.scalar_one_or_none()
    if pipeline is None:
        raise AlertError(f"no pipeline coded {request.pipeline!r}")
    return pipeline.id


async def _connection_id(session: AsyncSession, code: str) -> UUID:
    """Resolve the connection a notifier delivers through, refusing an unknown code."""
    found = await session.execute(sa.select(Connection).where(Connection.code == code))
    connection = found.scalar_one_or_none()
    if connection is None:
        raise AlertError(f"no connection coded {code!r}")
    return connection.id


async def delete_rule(session: AsyncSession, rule: AlertRule) -> None:
    """Remove an alert rule; the notifications it already raised are kept."""
    code = rule.code
    await session.delete(rule)
    await session.flush()
    _logger.info("alert rule deleted", rule=code)


async def matching_rules(session: AsyncSession, event: AlertEvent, pipeline_id: UUID) -> list[AlertRule]:
    """Find the live rules that want to hear about one event, throttled or not.

    A paused rule matches nothing. Pausing is instance state an operator sets on the row, so
    it is read here rather than folded into ``active``, which is what the rule itself declares.
    """
    rows = await session.execute(
        sa.select(AlertRule).where(
            AlertRule.event == event,
            AlertRule.active.is_(True),
            AlertRule.paused.is_(False),
            sa.or_(AlertRule.scope == AlertScope.GLOBAL, AlertRule.pipeline_id == pipeline_id),
        )
    )
    return list(rows.scalars())


async def set_paused(session: AsyncSession, rule: AlertRule, *, paused: bool) -> AlertRule:
    """Hold a rule's deliveries, or let them resume; the rule itself is left as declared."""
    rule.paused = paused
    await session.flush()
    _logger.info("alert rule paused" if paused else "alert rule resumed", rule=rule.code)
    return rule


#: What a PATCH may write on a rule, and nothing else on the row.
UPDATABLE: Final = ("paused", "template", "body")


async def update_rule(session: AsyncSession, rule: AlertRule, changes: Mapping[str, object]) -> AlertRule:
    """Write the fields a PATCH named on a rule, leaving every field it did not name.

    A subject or a body is compiled here as it is at creation, so a rule on the row always
    holds a template that renders.
    """
    named = {name: value for name, value in changes.items() if name in UPDATABLE}
    if "template" in named or "body" in named:
        check_templates(
            template=cast("str | None", named.get("template", rule.template)),
            body=cast("str | None", named.get("body", rule.body)),
        )
        rule.template = cast("str | None", named.get("template", rule.template))
        rule.body = cast("str | None", named.get("body", rule.body))
        await session.flush()
        _logger.info("alert rule retemplated", rule=rule.code)
    if "paused" in named:
        await set_paused(session, rule, paused=bool(named["paused"]))
    return rule


async def raised_at(session: AsyncSession, rule: AlertRule, pipeline_id: UUID) -> datetime | None:
    """When this rule last raised anything **for this pipeline**.

    A global rule watches every pipeline, and a window measured across all of them lets one
    noisy pipeline silence the rest. The window is per pipeline, which is what an operator
    means by "not more than one of these an hour".

    Read from ``created_at``, which nothing moves: ``available_at`` is rewritten by every
    delivery retry and by every recovery, so a channel that is down would widen the window
    it was raised in.
    """
    return (
        await session.execute(
            sa.select(sa.func.max(Notification.created_at))
            .join(Run, Run.id == Notification.run_id)
            .where(Notification.alert_rule_id == rule.id, Run.pipeline_id == pipeline_id)
        )
    ).scalar()


async def throttled_until(session: AsyncSession, rule: AlertRule, pipeline_id: UUID, now: datetime) -> datetime | None:
    """Say when this rule may next raise for this pipeline, or ``None`` if it may now.

    Measured from when a message was raised, not from when it was delivered or retried, so
    neither a slow notifier nor a failing one moves the window.
    """
    if not rule.throttle_seconds:
        return None
    last = await raised_at(session, rule, pipeline_id)
    if last is None:
        return None
    opens = last + timedelta(seconds=rule.throttle_seconds)
    return opens if opens > now else None


async def raise_for_run(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    event: AlertEvent,
    *,
    now: datetime | None = None,
    facts: "RunFacts | None" = None,
    report: str | None = None,
    report_artifact_id: UUID | None = None,
) -> list[Notification]:
    """Queue whatever this run's settling owes, in the caller's outcome transaction.

    Called from the same commit that settles the run, so a run cannot reach a terminal state
    without its alerts having been queued. ``facts`` is the run's full facts when the caller
    has already assembled them, and they are read here when a rule matched and the caller had
    none, so a run nothing watches pays for no facts at all. The rendered document is what the
    templates read as ``report``; it is not stored on the notification.
    """
    moment = now or utcnow()
    pipeline = await session.get(Pipeline, run.pipeline_id)
    if pipeline is None:  # pragma: no cover - the foreign key makes this unreachable
        return []
    rules = await matching_rules(session, event, run.pipeline_id)
    if not rules:
        return []
    report_url = report_url_for(services.settings.alert_base_url, report_artifact_id)
    if facts is None:
        facts = await _facts_of(session, run, base_url=services.settings.alert_base_url, rendered_at=moment)
    context = _context_for(run, pipeline, facts, base_url=services.settings.alert_base_url, report_url=report_url)
    rendering = {**context, "report": report}
    queued: list[Notification] = []
    for rule in rules:
        if await _already_raised(session, rule.id, run.id, event):
            continue
        opens = await throttled_until(session, rule, run.pipeline_id, moment)
        if opens is not None:
            # A suppressed alert that leaves nothing behind is indistinguishable from a rule
            # that never matched, which is the hard way to learn a throttle is too wide.
            session.add(
                LogEntry(
                    run_id=run.id,
                    level=LogLevel.INFO,
                    message=f"alert {rule.code!r} suppressed by its throttle window",
                    fields={
                        "event": event.value,
                        "notifier": rule.notifier,
                        "throttle": format_duration(timedelta(seconds=rule.throttle_seconds)),
                        "opens_at": opens.isoformat(),
                    },
                    created_at=moment,
                )
            )
            continue
        subject = _subject_of(session, rule, rendering, run_id=run.id, moment=moment)
        body = _body_of(session, services, rule, rendering, run_id=run.id, moment=moment)
        notification = Notification(
            alert_rule_id=rule.id,
            run_id=run.id,
            event=event,
            notifier=rule.notifier,
            connection_id=rule.connection_id,
            subject=subject,
            body=body,
            context=context,
            status=NotificationStatus.PENDING,
            available_at=moment,
            created_at=moment,
        )
        # A savepoint, because two processes can reach this between the check above and the
        # insert, and an IntegrityError raised here would otherwise abort the caller's whole
        # transaction rather than just this insert.
        try:
            async with session.begin_nested():
                session.add(notification)
                session.add(
                    LogEntry(
                        run_id=run.id,
                        level=LogLevel.INFO,
                        message=f"alert {rule.code!r} queued for delivery through {rule.notifier!r}",
                        fields={"event": event.value, "notifier": rule.notifier},
                        created_at=moment,
                    )
                )
        except IntegrityError:
            continue
        rule.last_sent_at = moment
        queued.append(notification)
    await session.flush()
    if queued:
        _logger.info("alerts raised", run_id=str(run.id), alert_event=event.value, rules=len(queued))
    return queued


def _context_for(
    run: Run,
    pipeline: Pipeline,
    facts: "RunFacts | None",
    *,
    base_url: str | None,
    report_url: str | None,
) -> JsonMap:
    """The frozen context a notification carries: the run's whole facts when the caller has them.

    The ``run`` namespace is the same either way, so a template written against it reads the
    same whether the facts came with the call or were built here.
    """
    if facts is None:
        return build_context(run, pipeline, base_url=base_url, report_url=report_url)
    # Imported here rather than at module scope: reporting imports this module back.
    from dirigent_core.reporting import as_context

    context = as_context(facts)
    cast("JsonMap", context["run"])["report_url"] = report_url
    return context


async def _facts_of(session: AsyncSession, run: Run, *, base_url: str | None, rendered_at: datetime) -> "RunFacts":
    """Read a run's whole facts, for a rule that matched when the caller assembled none."""
    # Imported here rather than at module scope: reporting imports this module back.
    from dirigent_core.reporting import facts_of_run

    version = await session.get(PipelineVersion, run.pipeline_version_id)
    if version is None:  # pragma: no cover - a run always pins a version that exists
        raise AlertError(f"run {run.id} pins a pipeline version that is gone")
    definition = load_definition(version.document)
    return await facts_of_run(session, run, definition, base_url=base_url, rendered_at=rendered_at)


def _subject_of(
    session: AsyncSession, rule: AlertRule, context: JsonMap, *, run_id: UUID | None, moment: datetime
) -> str:
    """Render a rule's subject: one line, whitespace collapsed, cut at the cap."""
    try:
        return _one_line(render(rule.template or DEFAULT_TEMPLATE, context, max_bytes=SUBJECT_RENDER_CAP))
    except (TemplateError, RenderTooLarge) as error:
        _render_failed(session, rule, "subject", error, run_id=run_id, moment=moment)
        return _one_line(render(DEFAULT_TEMPLATE, context, max_bytes=SUBJECT_RENDER_CAP))


def _body_of(
    session: AsyncSession,
    services: EngineServices,
    rule: AlertRule,
    context: JsonMap,
    *,
    run_id: UUID | None,
    moment: datetime,
) -> str:
    """Render a rule's body, or write the run's own facts when it declares no template."""
    if rule.body is None:
        return _body(context)
    try:
        return render(rule.body, context, max_bytes=int(services.settings.report_max_size))
    except (TemplateError, RenderTooLarge) as error:
        _render_failed(session, rule, "body", error, run_id=run_id, moment=moment)
        return _body(context)


def _render_failed(
    session: AsyncSession,
    rule: AlertRule,
    field: str,
    error: Exception,
    *,
    run_id: UUID | None,
    moment: datetime,
) -> None:
    """Say in the run's own timeline that a rule's template did not render, and what replaced it."""
    _logger.warning("alert template not rendered", rule=rule.code, field=field, error=str(error))
    if run_id is None:
        return
    session.add(
        LogEntry(
            run_id=run_id,
            level=LogLevel.WARNING,
            message=f"the {field} of alert {rule.code!r} was not rendered, so the default was sent",
            fields={"reason": str(error), "notifier": rule.notifier},
            created_at=moment,
        )
    )


def _or_literal(source: str, context: JsonMap, *, max_bytes: int) -> str:
    """Render text that a person typed, keeping it verbatim when it is not a template at all."""
    try:
        return render(source, context, max_bytes=max_bytes)
    except (TemplateError, RenderTooLarge):
        return source


def _one_line(text: str) -> str:
    """Collapse a rendering to the single line a subject is, no longer than the cap."""
    return " ".join(text.split())[:SUBJECT_CAP]


def _body(context: JsonMap) -> str:
    """Render the default body: the run's own facts, one per line, in a stable order."""
    run = cast("JsonMap", context.get("run", {}))
    lines = [f"{name}: {_as_text(value)}" for name, value in run.items() if value not in (None, "", {}, [])]
    return "\n".join(lines)


async def _already_raised(session: AsyncSession, rule_id: UUID, run_id: UUID, event: AlertEvent) -> bool:
    """Report whether this rule has already said this about this run."""
    found = await session.execute(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(
            Notification.alert_rule_id == rule_id,
            Notification.run_id == run_id,
            Notification.event == event,
        )
    )
    return int(found.scalar_one()) > 0


async def raise_for_status(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    status: RunStatus,
    *,
    now: datetime | None = None,
    facts: "RunFacts | None" = None,
    report: str | None = None,
    report_artifact_id: UUID | None = None,
) -> list[Notification]:
    """Queue the alerts a terminal run status owes, if that status raises an event at all."""
    event = EVENT_FOR_STATUS.get(status)
    if event is None:
        return []
    return await raise_for_run(
        session,
        services,
        run,
        event,
        now=now,
        facts=facts,
        report=report,
        report_artifact_id=report_artifact_id,
    )


async def raise_for_stuck(
    session: AsyncSession,
    services: EngineServices,
    run_ids: Sequence[UUID],
    *,
    now: datetime | None = None,
) -> int:
    """Queue ``run_stuck`` alerts for the runs the sweeper found standing still.

    The sweeper re-detects the same run every sweep; the once-per-rule-per-run constraint is
    what keeps that to one message.
    """
    moment = now or utcnow()
    queued = 0
    for run_id in run_ids:
        run = await session.get(Run, run_id)
        if run is None:  # pragma: no cover - the sweeper just read these ids
            continue
        queued += len(await raise_for_run(session, services, run, AlertEvent.RUN_STUCK, now=moment))
    return queued


async def queue_test_message(
    session: AsyncSession,
    services: EngineServices,
    *,
    notifier: str,
    connection: str | None = None,
    subject: str = "dirigent test alert",
    body: str = "This is a test message sent through the notifier surface.",
) -> Notification:
    """Queue one unattached message, which is what ``dg alerts test`` sends.

    The subject and the body are rendered as a rule's are, over a stand-in context, so a
    template can be tried out before it is written onto a rule.
    """
    if notifier not in services.host.notifiers:
        installed = ", ".join(sorted(services.host.notifiers)) or "none are installed"
        raise AlertError(f"no notifier {notifier!r} is installed ({installed})")
    context: JsonMap = {"run": {"pipeline": "(test)", "status": "succeeded"}, "report": None}
    notification = Notification(
        alert_rule_id=None,
        run_id=None,
        event=AlertEvent.RUN_SUCCEEDED,
        notifier=notifier,
        connection_id=await _connection_id(session, connection) if connection else None,
        subject=_one_line(_or_literal(subject, context, max_bytes=SUBJECT_RENDER_CAP)),
        body=_or_literal(body, context, max_bytes=int(services.settings.report_max_size)),
        context=context,
        status=NotificationStatus.PENDING,
        available_at=utcnow(),
    )
    session.add(notification)
    await session.flush()
    return notification


async def claim_notification(
    session: AsyncSession,
    *,
    owner: str,
    now: datetime,
    lease_seconds: int,
) -> Notification | None:
    """Claim the next due notification, the same way a worker claims an attempt."""
    statement = (
        sa.select(Notification)
        .where(Notification.status == NotificationStatus.PENDING, Notification.available_at <= now)
        .order_by(Notification.available_at, Notification.id)
        .limit(CLAIM_LIMIT)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True, of=Notification)
    found = await session.execute(statement)
    notification = found.scalars().first()
    if notification is None:
        return None
    notification.status = NotificationStatus.SENDING
    notification.lease_owner = owner
    notification.lease_expires_at = now + timedelta(seconds=lease_seconds)
    notification.attempt += 1
    await session.flush()
    return notification


def notifier_config(services: EngineServices, notifier: Notifier, connection: Connection | None) -> BaseModel:
    """Open the connection a notifier delivers through, validated against its own model."""
    if connection is None:
        return notifier.config_model()
    return services.secrets.decrypt_config(
        notifier.config_model, connection.config, connection.secret_envelope, key_id=connection.secret_key_id
    )


async def send_notification(
    session: AsyncSession,
    services: EngineServices,
    notification: Notification,
    *,
    owner: str,
    now: datetime | None = None,
) -> bool:
    """Deliver one claimed notification, returning whether it was delivered.

    The outcome is written only while this worker still holds the lease, so a delivery that
    outlasted its lease cannot overwrite the outcome of the worker the row was handed to.

    THE SESSION IS COMMITTED BEFORE THE SEND, so no transaction is open while an outbound
    call is in flight: on SQLite that transaction holds the one write lock, and everything
    else on the instance -- the sweeper reclaiming this very row, the API, a worker settling
    an attempt -- would queue behind a notifier that is slow to answer. Nothing read above
    has to be held anyway, because the fence below re-reads the row it writes.
    """
    moment = now or utcnow()
    try:
        notifier = services.host.notifiers.get(notification.notifier)
        if notifier is None:
            raise AlertError(f"notifier {notification.notifier!r} is not installed on this worker")
        connection = await session.get(Connection, notification.connection_id) if notification.connection_id else None
        config = notifier_config(services, notifier, connection)
        await session.commit()
        await notifier.send(_message(notification), config)
    except Exception as error:
        if not await _holds_lease(session, notification, owner):
            return False
        return await _record_failure(session, services, notification, error, moment)
    if not await _holds_lease(session, notification, owner):
        return False
    notification.status = NotificationStatus.SENT
    notification.sent_at = moment
    notification.error = None
    notification.lease_owner = None
    notification.lease_expires_at = None
    _timeline(session, notification, LogLevel.INFO, f"alert delivered through {notification.notifier!r}", moment)
    _logger.info("notification delivered", notification_id=str(notification.id), notifier=notification.notifier)
    return True


async def _holds_lease(session: AsyncSession, notification: Notification, owner: str) -> bool:
    """Re-read the row and report whether this worker may still write this outcome.

    The lease is a fence, not a hint: a row the sweeper returned to the queue belongs to
    whoever claimed it next, and writing into it would replace a live delivery's outcome
    with the outcome of an abandoned one.
    """
    found = await session.execute(
        sa.select(Notification.status, Notification.lease_owner).where(Notification.id == notification.id)
    )
    row = found.one_or_none()
    if row is not None and row.status is NotificationStatus.SENDING and row.lease_owner == owner:
        return True
    _logger.warning(
        "lease lost, notification outcome discarded",
        notification_id=str(notification.id),
        notifier=notification.notifier,
        holder=None if row is None else row.lease_owner,
        notification_status=None if row is None else row.status.value,
    )
    return False


async def renew_lease(
    session: AsyncSession,
    notification_id: UUID,
    *,
    owner: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Push a notification's lease out, reporting whether this worker still held it."""
    moment = now or utcnow()
    renewed = await session.execute(
        sa.update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.status == NotificationStatus.SENDING,
            Notification.lease_owner == owner,
        )
        .values(lease_expires_at=moment + timedelta(seconds=lease_seconds))
        .returning(Notification.id)
        .execution_options(synchronize_session=False)
    )
    return renewed.scalar_one_or_none() is not None


def _message(notification: Notification) -> AlertMessage:
    """Render a stored notification as the message the notifier surface takes."""
    context = notification.context or {}
    run = cast("JsonMap", context.get("run", {}))
    return AlertMessage(
        event=notification.event.value,
        subject=notification.subject,
        body=notification.body,
        run_id=notification.run_id,
        pipeline=cast("str | None", run.get("pipeline")),
        url=cast("str | None", run.get("url")),
        context=cast("dict[str, JsonValue]", context),
    )


async def _record_failure(
    session: AsyncSession,
    services: EngineServices,
    notification: Notification,
    error: Exception,
    moment: datetime,
) -> bool:
    """Schedule another delivery, or record that this one is never going to arrive."""
    message = f"{type(error).__name__}: {error}"
    notification.error = message
    notification.lease_owner = None
    notification.lease_expires_at = None
    budget = services.settings.notification_max_attempts
    if notification.attempt >= budget:
        notification.status = NotificationStatus.FAILED
        _timeline(
            session,
            notification,
            LogLevel.ERROR,
            f"alert could not be delivered through {notification.notifier!r} after {budget} attempts: {message}",
            moment,
        )
        _logger.error(
            "notification failed terminally",
            notification_id=str(notification.id),
            notifier=notification.notifier,
            attempts=notification.attempt,
            error=message,
        )
        return False
    delay = services.settings.notification_backoff.total_seconds() * (2 ** (notification.attempt - 1))
    notification.status = NotificationStatus.PENDING
    notification.available_at = moment + timedelta(seconds=delay)
    _logger.warning(
        "notification delivery failed, will retry",
        notification_id=str(notification.id),
        attempt=notification.attempt,
        delay_seconds=round(delay, 1),
        error=message,
    )
    return False


def _timeline(
    session: AsyncSession,
    notification: Notification,
    level: LogLevel,
    message: str,
    moment: datetime,
) -> None:
    """Put a delivery outcome into the run's timeline."""
    if notification.run_id is None:
        return
    session.add(
        LogEntry(
            run_id=notification.run_id,
            level=level,
            message=message,
            fields={"notifier": notification.notifier, "event": notification.event.value},
            created_at=moment,
        )
    )


async def list_notifications(
    session: AsyncSession,
    *,
    run_id: UUID | None = None,
    notification_status: NotificationStatus | None = None,
    notifier: str | None = None,
    after: UUID | None = None,
    limit: int | None = None,
) -> list[Notification]:
    """List notifications newest first, for one run or across the instance.

    The filters are the server's own, so a row they leave out is one the caller never reads
    and a cursor walk does not have to be told which pages to skip.
    """
    statement = sa.select(Notification).order_by(Notification.id.desc())
    if run_id is not None:
        statement = statement.where(Notification.run_id == run_id)
    if notification_status is not None:
        statement = statement.where(Notification.status == notification_status)
    if notifier is not None:
        statement = statement.where(Notification.notifier == notifier)
    if after is not None:
        statement = statement.where(Notification.id < after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def find_notification(session: AsyncSession, notification_id: UUID) -> Notification | None:
    """Find one notification by id."""
    return await session.get(Notification, notification_id)


async def retry_notification(
    session: AsyncSession,
    notification: Notification,
    *,
    now: datetime | None = None,
) -> Notification:
    """Put one notification back on the queue, due now.

    An explicit retry starts the delivery over rather than adding one try to a budget that is
    already spent: a row that failed terminally has no attempts left, and a retry that left the
    counter where it was would fail again without calling the notifier at all. So the backoff,
    the counter and the last refusal all go, and a worker claims the row on its next pass.

    A row a worker is holding is left alone: its lease is live, and returning it to the queue
    would hand the same message to a second worker.
    """
    if notification.status is NotificationStatus.SENDING:
        raise AlertError("a worker is delivering this one; wait for it to finish or fail")
    notification.status = NotificationStatus.PENDING
    notification.available_at = now or utcnow()
    notification.attempt = 0
    notification.error = None
    notification.sent_at = None
    notification.lease_owner = None
    notification.lease_expires_at = None
    await session.flush()
    _logger.info("notification queued again", notification_id=str(notification.id), notifier=notification.notifier)
    return notification


async def recover_notifications(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Return notifications whose worker died back to the queue, like the lease sweeper does.

    One conditional statement rather than a select and a write: a renewal or a delivery that
    commits between the two would otherwise be overwritten, requeueing a notification another
    worker is still sending or has already sent.
    """
    moment = now or utcnow()
    recovered = await session.execute(
        sa.update(Notification)
        .where(
            Notification.status == NotificationStatus.SENDING,
            Notification.lease_expires_at.is_not(None),
            Notification.lease_expires_at < moment,
        )
        .values(
            status=NotificationStatus.PENDING,
            available_at=moment,
            lease_owner=None,
            lease_expires_at=None,
        )
        .returning(Notification.id)
        .execution_options(synchronize_session=False)
    )
    return len(recovered.scalars().all())


class NotificationDispatcher(BaseModel):
    """The worker's alert-delivery loop: claim one, send it, repeat until the queue is empty."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    sessions: async_sessionmaker[AsyncSession]
    services: EngineServices
    owner: str
    max_per_pass: int = Field(default=25, ge=1)

    async def drain(self, *, now: datetime | None = None) -> int:
        """Deliver every notification that is due, and report how many were sent.

        Each delivery is its own transaction, so one undeliverable message never rolls back
        the ones that went out beside it.
        """
        sent = 0
        for _ in range(self.max_per_pass):
            async with session_scope(self.sessions) as session:
                moment = now or utcnow()
                notification = await claim_notification(
                    session,
                    owner=self.owner,
                    now=moment,
                    lease_seconds=int(self.services.settings.notification_lease.total_seconds()),
                )
                if notification is None:
                    return sent
            async with session_scope(self.sessions) as session:
                claimed = await session.get(Notification, notification.id)
                if claimed is None:  # pragma: no cover - it was just claimed
                    continue
                async with self._renewing(claimed.id):
                    delivered = await send_notification(session, self.services, claimed, owner=self.owner, now=now)
                if delivered:
                    sent += 1
        return sent

    @asynccontextmanager
    async def _renewing(self, notification_id: UUID) -> AsyncGenerator[None]:
        """Hold a notification's lease open for as long as its delivery is in flight."""
        halting = asyncio.Event()
        renewing = asyncio.create_task(self._renew_until_halted(notification_id, halting))
        try:
            yield
        finally:
            halting.set()
            await renewing

    async def _renew_until_halted(self, notification_id: UUID, halting: asyncio.Event) -> None:
        """Extend the lease on a cadence until halted, or until the row is no longer this worker's.

        The halt is a flag rather than a cancel: a renewal already inside its transaction runs
        to its own end, where a cancel landing in a database await strands the session's
        connection, checked out of the pool and never closed.
        """
        lease_seconds = int(self.services.settings.notification_lease.total_seconds())
        while not halting.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(halting.wait(), timeout=lease_seconds / RENEWALS_PER_LEASE)
            if halting.is_set():
                return
            try:
                async with session_scope(self.sessions) as session:
                    if not await renew_lease(session, notification_id, owner=self.owner, lease_seconds=lease_seconds):
                        return
            except Exception as error:  # the delivery runs on; the sweeper reclaims if it outlasts the lease
                _logger.warning(
                    "notification lease renewal failed", notification_id=str(notification_id), error=str(error)
                )
                return
