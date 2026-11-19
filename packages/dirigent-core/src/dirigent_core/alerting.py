"""Alerting rules and channels as data, with delivery queued and retried like any other work.

A rule says one thing about one run once: the unique constraint on
``(alert_rule_id, run_id, event)`` is the deduplication, and the throttle window is a second,
coarser guard against a flapping pipeline.
"""

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator, Collection, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, NamedTuple, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import (
    IMPORTANCE_RANK,
    SETTLED_ALERT_EVENTS,
    AlertEvent,
    AlertScope,
    AttemptStatus,
    AuditAction,
    AuditSubject,
    Importance,
    LogLevel,
    NotificationEvent,
    NotificationStatus,
    RunItemStatus,
    RunStatus,
    TriggerKind,
    WorkerStatus,
)
from dirigent_client.schemas import ValidationIssue
from dirigent_client.schemas.alerts import LOG_NOTIFIER, TEST_BODY, TEST_SUBJECT
from dirigent_common import (
    EntityName,
    JsonMap,
    RenderTooLarge,
    TemplateError,
    as_text,
    compile_template,
    format_duration,
    render_off_loop,
    scrub,
    secrets_of,
)
from dirigent_common.depth import shown
from dirigent_core import audit
from dirigent_core.database import insert_unless_taken, is_deadlock, session_scope
from dirigent_core.engine.definition import PipelineDefinition, load_definition
from dirigent_core.engine.services import EngineServices
from dirigent_core.errors import DomainError
from dirigent_core.ids import uuid7
from dirigent_core.logging import get_logger
from dirigent_core.messages import (
    ALERT_DECLARED,
    ALERT_OWNED_ELSEWHERE,
    ALERT_TEMPLATE_NAME_UNKNOWN,
    ALERT_UNKNOWN_CONNECTION,
    ALERT_UNKNOWN_PIPELINE,
    ALERT_VERSION_GONE,
    BAD_ALERT_TEMPLATE,
    BLOCK_RAISED,
    DUPLICATE_RULE,
    NOTIFICATION_IN_FLIGHT,
    NOTIFIER_NOT_ON_WORKER,
    NOTIFIER_TIMED_OUT,
    ON_CHANGE_UNSETTLED,
    SCOPE_NEEDS_PIPELINE,
    TARGET_HAS_NO_NOTIFIER,
)
from dirigent_core.models import (
    AlertRule,
    Connection,
    LogEntry,
    Notification,
    Pipeline,
    PipelineOutcome,
    PipelineVersion,
    Run,
    RunItem,
    StepAttempt,
    Worker,
    utcnow,
)
from dirigent_core.reportchecks import REPORT_CONTEXT, unknown_names
from dirigent_core.secrets import ConnectionAwaitingSecrets, unset_secrets
from dirigent_plugin import AlertMessage, Notifier

if TYPE_CHECKING:
    from dirigent_core.reporting import RunFacts

EVENT_FOR_STATUS: dict[RunStatus, AlertEvent] = {
    RunStatus.FAILED: AlertEvent.RUN_FAILED,
    RunStatus.COMPLETED_WITH_ERRORS: AlertEvent.RUN_COMPLETED_WITH_ERRORS,
    RunStatus.SUCCEEDED: AlertEvent.RUN_SUCCEEDED,
}

#: The events a run's settling raises, which are the ones its report document is handed to.
SETTLED_EVENTS: Final = tuple(NotificationEvent(event.value) for event in EVENT_FOR_STATUS.values())

#: The characters a subject is cut to, which is what a subject line is.
SUBJECT_CAP: Final = 200

#: What a subject may render before it is refused: room to be cut rather than lost.
SUBJECT_RENDER_CAP: Final = 8 * SUBJECT_CAP

#: The characters an alert's error is cut to: one line, read beside the run's other facts.
ERROR_CAP: Final = 300

#: The run statuses an alert names a failing step and an error for.
FAILING: Final = frozenset({RunStatus.FAILED, RunStatus.COMPLETED_WITH_ERRORS})

#: How the default body opens for each status, before the failing step and its error.
OPENING: Final = {
    RunStatus.FAILED.value: "Failed",
    RunStatus.COMPLETED_WITH_ERRORS.value: "Completed with errors",
    RunStatus.SUCCEEDED.value: "Succeeded",
    RunStatus.RUNNING.value: "Still running, with no progress",
}

#: How the default body of a recovery opens, before what the previous run ended as.
RECOVERED_OPENING: Final = "Recovered"

CLAIM_LIMIT = 1

#: How many times a lease is renewed over its own length while a delivery is in flight.
RENEWALS_PER_LEASE = 3

_logger = get_logger("alerting")


class AlertError(DomainError):
    """An alert rule could not be declared, found, or delivered."""


class NotificationInFlight(AlertError):
    """A notification a worker is delivering was asked to go back on the queue."""

    status = 409
    message = NOTIFICATION_IN_FLIGHT


class DeclaredRule(AlertError):
    """A rule a pipeline's document declares was asked to change or go through the API."""

    status = 409
    message = ALERT_DECLARED


class AlertRuleRequest(BaseModel):
    """What it takes to declare an alert rule, from the API or the CLI."""

    model_config = ConfigDict(frozen=True)

    code: EntityName
    name: str | None = None
    description: str | None = None
    event: AlertEvent
    scope: AlertScope = AlertScope.GLOBAL
    pipeline: str | None = None
    importance: Importance | None = None
    connection: str | None = None
    """The connection this rule delivers through, whose kind names the sender; none is the log."""
    template: str | None = None
    body: str | None = None
    throttle: timedelta = timedelta(0)
    on_change: bool = False
    """Raise only for a run whose outcome differs from the pipeline's previous settled run's."""


class Outcome(NamedTuple):
    """How one settled run ended: its status, and which steps and fan-out elements failed."""

    status: RunStatus
    failures: str
    """The digest of the failed steps and elements, which is all a comparison needs."""

    run_id: UUID | None


class Change(NamedTuple):
    """A settled run's outcome beside the pipeline's previous one, which a rule on change is asked about."""

    previous: Outcome | None
    current: Outcome

    @property
    def changed(self) -> bool:
        """Report whether this outcome differs from the previous one; a pipeline's first is a change."""
        if self.previous is None:
            return True
        return (self.previous.status, self.previous.failures) != (self.current.status, self.current.failures)

    @property
    def recovered(self) -> bool:
        """Report whether this run succeeded where the previous settled run did not."""
        return (
            self.current.status is RunStatus.SUCCEEDED
            and self.previous is not None
            and self.previous.status is not RunStatus.SUCCEEDED
        )


async def failures_of(session: AsyncSession, run: Run) -> str:
    """Digest which steps of a settled run failed, and which elements of its fan-outs, in a stable order.

    A step is read by its newest attempt, so a retry that succeeded is not a failure.
    """
    failed: set[str] = set()
    items = await session.execute(
        sa.select(RunItem.step_name, RunItem.item_key).where(
            RunItem.run_id == run.id, RunItem.status == RunItemStatus.FAILED
        )
    )
    failed.update(json.dumps([step, key]) for step, key in items.all())
    newest: dict[str, tuple[int, AttemptStatus]] = {}
    attempts = await session.execute(
        sa.select(StepAttempt.step_name, StepAttempt.attempt, StepAttempt.status).where(
            StepAttempt.run_id == run.id, StepAttempt.run_item_id.is_(None)
        )
    )
    for step, number, status in attempts.all():
        if step not in newest or number > newest[step][0]:
            newest[step] = (number, status)
    failed.update(json.dumps([step, None]) for step, (_, status) in newest.items() if status is AttemptStatus.FAILED)
    return "sha256:" + hashlib.sha256(json.dumps(sorted(failed)).encode()).hexdigest()


#: The class of the advisory locks :func:`_lock_outcome` takes, one per pipeline inside it.
OUTCOME_LOCK_CLASS: Final = 0x64_6F_75_74


async def _lock_outcome(session: AsyncSession, pipeline_id: UUID) -> None:
    """Serialise the outcome reads and writes of one pipeline until this transaction ends.

    A lock on the outcome alone, never the pipeline's row: a settling transaction already holds
    its run's lock, and nothing that holds this one waits on a run lock or on the pipeline row.
    PostgreSQL only: SQLite's ``BEGIN IMMEDIATE`` already serialises the transactions.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(
        sa.select(sa.func.pg_advisory_xact_lock(OUTCOME_LOCK_CLASS, sa.func.hashtext(str(pipeline_id))))
    )


async def record_outcome(session: AsyncSession, run: Run, status: RunStatus, *, now: datetime | None = None) -> Change:
    """Write a settled run's outcome as its pipeline's latest, and say what it replaced.

    The previous outcome is the one the last settlement of this pipeline to commit wrote, read
    under the pipeline's outcome lock, so two runs settling at once are ordered by their commits
    rather than by their clocks: the second reads the first. A run settling again after a retry
    is compared with its own earlier outcome.
    """
    await _lock_outcome(session, run.pipeline_id)
    current = Outcome(status=status, failures=await failures_of(session, run), run_id=run.id)
    row = await session.get(PipelineOutcome, run.pipeline_id, populate_existing=True)
    if row is None:
        session.add(
            PipelineOutcome(
                pipeline_id=run.pipeline_id,
                run_id=run.id,
                status=status,
                failures=current.failures,
                settled_at=now or utcnow(),
            )
        )
        await session.flush()
        return Change(previous=None, current=current)
    previous = Outcome(status=row.status, failures=row.failures, run_id=row.run_id)
    row.run_id, row.status, row.failures, row.settled_at = run.id, status, current.failures, now or utcnow()
    await session.flush()
    return Change(previous=previous, current=current)


def build_context(
    run: Run, pipeline: Pipeline, *, base_url: str | None = None, report_url: str | None = None
) -> JsonMap:
    """Gather the facts a template may read, under the one namespace it has.

    A flat snapshot rather than a live handle: the notification is delivered later, and must
    describe the run as it was when the alert fired.
    """
    duration = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else None
    return {
        "params": shown(dict(run.params)),
        "run": {
            "id": str(run.id),
            "status": run.status.value,
            "pipeline": pipeline.code,
            "error": run.error,
            "error_code": run.error_code,
            "error_params": dict(run.error_params or {}),
            "failed_step": None,
            "params": shown(dict(run.params)),
            "trigger": run.triggered_by_label or run.triggered_by_kind.value,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "duration_ms": round(duration * 1000) if duration is not None else None,
            "url": f"{base_url.rstrip('/')}/runs/{run.id}" if base_url else None,
            "report_url": report_url,
        },
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
    """Declare an alert rule, refusing a target or a scope this instance cannot honour."""
    if await find_rule(session, request.code) is not None:
        raise AlertError(DUPLICATE_RULE, code=repr(request.code))
    check_templates(template=request.template, body=request.body)
    check_on_change(request.event, on_change=request.on_change)
    pipeline_id = await _scope_pipeline(session, request)
    notifier, connection_id = await _target(session, services, request.connection)
    rule = AlertRule(
        code=request.code,
        name=request.name,
        description=request.description,
        event=request.event,
        scope=request.scope,
        pipeline_id=pipeline_id,
        importance=request.importance,
        notifier=notifier,
        connection_id=connection_id,
        template=request.template,
        body=request.body,
        throttle_seconds=int(request.throttle.total_seconds()),
        on_change=request.on_change,
    )

    async def taken() -> bool:
        return await find_rule(session, request.code) is not None

    if not await insert_unless_taken(session, rule, taken):
        raise AlertError(DUPLICATE_RULE, code=repr(request.code))
    await audit.record(session, AuditAction.CREATED, AuditSubject.ALERT_RULE, code=rule.code, subject_id=rule.id)
    return rule


def check_templates(*, template: str | None = None, body: str | None = None) -> None:
    """Refuse a subject or a body that does not compile, naming the field and the line."""
    for field, source in (("template", template), ("body", body)):
        if source is None:
            continue
        try:
            compile_template(source)
        except TemplateError as error:
            raise AlertError(BAD_ALERT_TEMPLATE, field=field, detail=str(error)) from error


def check_on_change(event: AlertEvent, *, on_change: bool) -> None:
    """Refuse to compare outcomes for an event a run raises before it has settled."""
    if on_change and event not in SETTLED_ALERT_EVENTS:
        raise AlertError(ON_CHANGE_UNSETTLED, event=event.value)


#: Every name an alert's subject and body are given: a run's report facts, where it went wrong, and its report.
ALERT_CONTEXT: Final[Mapping[str, frozenset[str] | None]] = {
    **REPORT_CONTEXT,
    "failing_step": None,
    "failing_item": None,
    "error": None,
    "error_code": None,
    "report": None,
    "event": None,
    "previous_status": None,
}


def template_warnings(*, template: str | None = None, body: str | None = None, at: str = "") -> list[ValidationIssue]:
    """Warn on each name a subject or a body reads that an alert is never given, which renders empty.

    ``at`` is what each warning's location is prefixed with, before ``template`` or ``body``.
    """
    return [
        issue
        for field, source in (("template", template), ("body", body))
        if source is not None
        for issue in unknown_names(source, f"{at}{field}", ALERT_CONTEXT, ALERT_TEMPLATE_NAME_UNKNOWN)
    ]


async def _scope_pipeline(session: AsyncSession, request: AlertRuleRequest) -> UUID | None:
    """Resolve the pipeline a rule is scoped to, refusing a scope that names nothing."""
    if request.scope is AlertScope.GLOBAL:
        return None
    if not request.pipeline:
        raise AlertError(SCOPE_NEEDS_PIPELINE)
    found = await session.execute(sa.select(Pipeline).where(Pipeline.code == request.pipeline))
    pipeline = found.scalar_one_or_none()
    if pipeline is None:
        raise AlertError(ALERT_UNKNOWN_PIPELINE, code=repr(request.pipeline))
    return pipeline.id


async def _connection(session: AsyncSession, code: str) -> Connection:
    """Read one connection by code, refusing a code this instance does not hold."""
    found = await session.execute(sa.select(Connection).where(Connection.code == code))
    connection = found.scalar_one_or_none()
    if connection is None:
        raise AlertError(ALERT_UNKNOWN_CONNECTION, code=repr(code))
    return connection


async def _target(session: AsyncSession, services: EngineServices, code: str | None) -> tuple[str, UUID | None]:
    """Resolve the one target named into the sender that delivers it and what it opens.

    A target is a connection, and the notifier is that connection's kind; naming nothing is
    the process log. A kind no installed notifier answers to is refused here rather than
    stored, because the row would otherwise hold a sender no worker can dispatch on.
    """
    if code is None:
        return LOG_NOTIFIER, None
    connection = await _connection(session, code)
    if connection.kind not in services.host.notifiers:
        installed = ", ".join(sorted(services.host.notifiers)) or "none are installed"
        raise AlertError(
            TARGET_HAS_NO_NOTIFIER, code=repr(connection.code), kind=repr(connection.kind), installed=installed
        )
    return connection.kind, connection.id


async def refuse_declared(session: AsyncSession, rule: AlertRule) -> None:
    """Refuse to rewrite or remove by hand a rule its pipeline's document declares."""
    if not rule.declared:
        return
    pipeline = await session.get(Pipeline, rule.pipeline_id) if rule.pipeline_id else None
    raise DeclaredRule(code=repr(rule.code), pipeline=repr(pipeline.code if pipeline else "?"))


async def delete_rule(session: AsyncSession, rule: AlertRule) -> None:
    """Remove an alert rule; the notifications it already raised are kept."""
    await refuse_declared(session, rule)
    code, rule_id = rule.code, rule.id
    await session.delete(rule)
    await session.flush()
    await audit.record(session, AuditAction.DELETED, AuditSubject.ALERT_RULE, code=code, subject_id=rule_id)


async def declared_rule_issues(
    session: AsyncSession, services: EngineServices, pipeline: Pipeline | None, definition: PipelineDefinition
) -> list[ValidationIssue]:
    """Refuse the ``alerts:`` a document declares that this instance could not hold for it.

    A code another owner already holds is refused, naming the owner, since a rule code is unique
    across the instance; so is a connection the instance does not hold, or one of a kind no
    installed notifier delivers through.
    """
    if not definition.alerts:
        return []
    held = {
        row.code: row
        for row in (
            await session.execute(sa.select(AlertRule).where(AlertRule.code.in_(sorted(definition.alerts))))
        ).scalars()
    }
    named = sorted({spec.connection for spec in definition.alerts.values() if spec.connection is not None})
    kinds = {
        code: kind
        for code, kind in await session.execute(
            sa.select(Connection.code, Connection.kind).where(Connection.code.in_(named))
        )
    }
    issues: list[ValidationIssue] = []
    for code, spec in definition.alerts.items():
        row = held.get(code)
        if row is not None and not (pipeline is not None and row.declared and row.pipeline_id == pipeline.id):
            issues.append(
                ValidationIssue.of(
                    ALERT_OWNED_ELSEWHERE,
                    location=f"alerts.{code}",
                    code=repr(code),
                    owner=await _owner_of(session, row),
                )
            )
        if spec.connection is None:
            continue
        kind = kinds.get(spec.connection)
        if kind is None:
            issues.append(
                ValidationIssue.of(
                    ALERT_UNKNOWN_CONNECTION, location=f"alerts.{code}.connection", code=repr(spec.connection)
                )
            )
        elif kind not in services.host.notifiers:
            installed = ", ".join(sorted(services.host.notifiers)) or "none are installed"
            issues.append(
                ValidationIssue.of(
                    TARGET_HAS_NO_NOTIFIER,
                    location=f"alerts.{code}.connection",
                    code=repr(spec.connection),
                    kind=repr(kind),
                    installed=installed,
                )
            )
    return issues


def declared_rule_warnings(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Warn on each name a declared rule's subject or body reads that an alert is never given."""
    return [
        issue
        for code, spec in definition.alerts.items()
        for issue in template_warnings(template=spec.template, body=spec.body, at=f"alerts.{code}.")
    ]


async def _owner_of(session: AsyncSession, rule: AlertRule) -> str:
    """Name whoever declared a rule, in the words a refusal is read in."""
    if not rule.declared:
        return "hand, through the API"
    pipeline = await session.get(Pipeline, rule.pipeline_id) if rule.pipeline_id else None
    return f"the document of pipeline {pipeline.code if pipeline else '?'!r}"


async def reconcile_declared_rules(
    session: AsyncSession, services: EngineServices, pipeline: Pipeline, definition: PipelineDefinition
) -> None:
    """Make the rules this pipeline's document owns exactly the ones its ``alerts:`` declares.

    A declared rule is created, rewritten where it differs, and removed when the document no
    longer declares it. Whether a rule is paused is instance state and is left as it is. A rule
    created through the API is never reached, even one scoped to this pipeline.
    """
    rows = await session.execute(
        sa.select(AlertRule).where(AlertRule.pipeline_id == pipeline.id, AlertRule.declared.is_(True))
    )
    existing = {row.code: row for row in rows.scalars()}
    for code, spec in definition.alerts.items():
        notifier, connection_id = await _target(session, services, spec.connection)
        wanted: dict[str, object] = {
            "name": spec.name,
            "description": spec.description,
            "event": spec.event,
            "scope": AlertScope.PIPELINE,
            "pipeline_id": pipeline.id,
            "importance": spec.importance,
            "notifier": notifier,
            "connection_id": connection_id,
            "template": spec.template,
            "body": spec.body,
            "throttle_seconds": int(spec.throttle.total_seconds()),
            "on_change": spec.on_change,
            "active": spec.active,
        }
        row = existing.get(code)
        if row is None:
            rule = AlertRule(code=code, declared=True, **wanted)
            session.add(rule)
            await session.flush()
            await audit.record(session, AuditAction.CREATED, AuditSubject.ALERT_RULE, code=code, subject_id=rule.id)
            continue
        fields = [field for field, value in wanted.items() if getattr(row, field) != value]
        if not fields:
            continue
        for field in fields:
            setattr(row, field, wanted[field])
        await session.flush()
        await audit.record(
            session, AuditAction.UPDATED, AuditSubject.ALERT_RULE, code=code, subject_id=row.id, fields=fields
        )
    for code, row in existing.items():
        if code in definition.alerts:
            continue
        rule_id = row.id
        await session.delete(row)
        await session.flush()
        await audit.record(session, AuditAction.DELETED, AuditSubject.ALERT_RULE, code=code, subject_id=rule_id)


def _satisfied_levels(importance: Importance) -> list[Importance]:
    """The floors a pipeline of this importance clears: its own and every lesser one."""
    reached = IMPORTANCE_RANK[importance]
    return [level for level, rank in IMPORTANCE_RANK.items() if rank <= reached]


async def matching_rules(
    session: AsyncSession, event: AlertEvent, pipeline_id: UUID, importance: Importance
) -> list[AlertRule]:
    """Find the live rules that want to hear about one event, throttled or not.

    A paused rule matches nothing. Pausing is instance state an operator sets on the row, so
    it is read here rather than folded into ``active``, which is what the rule itself declares.

    A rule that names an importance wants only the pipelines that carry at least that much;
    one that names none wants every pipeline, so a rule that pages the critical failures and
    a rule that logs everything both raise on the same run.
    """
    rows = await session.execute(
        sa.select(AlertRule).where(
            AlertRule.event == event,
            AlertRule.active.is_(True),
            AlertRule.paused.is_(False),
            sa.or_(AlertRule.scope == AlertScope.GLOBAL, AlertRule.pipeline_id == pipeline_id),
            sa.or_(AlertRule.importance.is_(None), AlertRule.importance.in_(_satisfied_levels(importance))),
        )
    )
    return list(rows.scalars())


async def set_paused(session: AsyncSession, rule: AlertRule, *, paused: bool) -> AlertRule:
    """Pause a rule, so it ignores every event until resumed, or resume it; the rule itself is left as declared.

    Nothing is queued for a paused rule: an event it would have matched is not raised later.
    """
    if rule.paused is paused:
        return rule
    rule.paused = paused
    await session.flush()
    action = AuditAction.PAUSED if paused else AuditAction.RESUMED
    await audit.record(session, action, AuditSubject.ALERT_RULE, code=rule.code, subject_id=rule.id)
    return rule


#: What a PATCH may write on a rule, and nothing else on the row.
UPDATABLE: Final = ("paused", "template", "body", "importance", "connection")


async def update_rule(
    session: AsyncSession, services: EngineServices, rule: AlertRule, changes: Mapping[str, object]
) -> AlertRule:
    """Write the fields a PATCH named on a rule, leaving every field it did not name.

    A subject or a body is compiled here as it is at creation, and a target is resolved here as
    it is at creation, so a rule on the row always holds a template that renders and a sender a
    worker can dispatch on.
    """
    named = {name: value for name, value in changes.items() if name in UPDATABLE}
    if set(named) - {"paused"}:
        await refuse_declared(session, rule)
    before = {
        "template": rule.template,
        "body": rule.body,
        "importance": rule.importance,
        "connection": rule.connection_id,
    }
    if "template" in named or "body" in named:
        check_templates(
            template=cast("str | None", named.get("template", rule.template)),
            body=cast("str | None", named.get("body", rule.body)),
        )
        rule.template = cast("str | None", named.get("template", rule.template))
        rule.body = cast("str | None", named.get("body", rule.body))
        await session.flush()
    if "importance" in named:
        floor = cast("Importance | None", named["importance"])
        rule.importance = floor
        await session.flush()
    if "connection" in named:
        code = cast("str | None", named["connection"])
        rule.notifier, rule.connection_id = await _target(session, services, code)
        await session.flush()
    after = {
        "template": rule.template,
        "body": rule.body,
        "importance": rule.importance,
        "connection": rule.connection_id,
    }
    fields = audit.changed(before, after)
    if fields:
        await audit.record(
            session, AuditAction.UPDATED, AuditSubject.ALERT_RULE, code=rule.code, subject_id=rule.id, fields=fields
        )
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


#: The class of the advisory locks :func:`_lock_throttles` takes, one per pipeline inside it.
THROTTLE_LOCK_CLASS: Final = 0x64_61_6C_74


async def _lock_throttles(session: AsyncSession, pipeline_id: UUID) -> None:
    """Serialise the throttle decisions for one pipeline until this transaction ends.

    Two runs of a pipeline settling at once each hold only their own run's lock, so neither
    sees the other's uncommitted alert. This lock is on the pipeline's throttles alone: only
    raising an alert takes it, and never while holding the pipeline's row.
    PostgreSQL only: SQLite's ``BEGIN IMMEDIATE`` already serialises the transactions.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(
        sa.select(sa.func.pg_advisory_xact_lock(THROTTLE_LOCK_CLASS, sa.func.hashtext(str(pipeline_id))))
    )


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
    change: Change | None = None,
) -> list[Notification]:
    """Queue whatever this run's settling owes, in the caller's outcome transaction.

    Called from the same commit that settles the run, so a run cannot reach a terminal state
    without its alerts having been queued. The run's facts are read only once a rule is due to
    raise, so a run nothing watches, or whose rules already spoke or are throttled, pays for
    none. A run that owes its report document holds its alerts until the document is stored,
    which hands them the link and the text.

    A savepoint, and everything that fails inside it is logged rather than raised: the caller
    has already written the outcome this reports on, and an alert nobody can queue must not
    cost the work a second execution. A deadlock is the one failure passed on, because the
    caller answers that by running its whole transaction again.
    """
    try:
        async with session.begin_nested():
            return await _queue_for_run(
                session,
                services,
                run,
                event,
                now=now,
                change=change,
            )
    except Exception as error:
        if is_deadlock(error):
            raise
        _logger.error("alerts not raised", run_id=str(run.id), alert_event=event.value, error=str(error))
        return []


async def _queue_for_run(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    event: AlertEvent,
    *,
    now: datetime | None = None,
    change: Change | None = None,
) -> list[Notification]:
    """Write down the notifications and the timeline entries one raised event owes.

    ``change`` is the run's outcome beside the previous one; without it nothing was compared,
    and a rule on change raises as though the outcome had changed.
    """
    moment = now or utcnow()
    pipeline = await session.get(Pipeline, run.pipeline_id)
    if pipeline is None:  # pragma: no cover - the foreign key makes this unreachable
        return []
    rules = await matching_rules(session, event, run.pipeline_id, pipeline.importance)
    if any(rule.throttle_seconds for rule in rules):
        await _lock_throttles(session, run.pipeline_id)
    due: list[AlertRule] = []
    for rule in rules:
        if await _already_raised(session, rule.id, run.id, event):
            continue
        if rule.on_change and run.triggered_by_kind is TriggerKind.BACKFILL:
            session.add(_history_entry(run, rule, event, moment))
            continue
        if rule.on_change and change is not None and not change.changed:
            session.add(_unchanged_entry(run, rule, event, change, moment))
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
        due.append(rule)
    if not due:
        return []
    facts = await _facts_of(session, run, base_url=services.settings.alert_base_url, rendered_at=moment)
    context = _context_for(run, facts, output_cap=int(services.settings.inline_artifact_max))
    context |= _change_facts(event, change)
    queued: list[Notification] = []
    for rule in due:
        # The rule's templates render at delivery, outside this transaction and off the loop;
        # until then the row carries the defaults.
        notification = Notification(
            alert_rule_id=rule.id,
            rule_code=rule.code,
            run_id=run.id,
            event=NotificationEvent(event.value),
            notifier=rule.notifier,
            connection_id=rule.connection_id,
            subject=_default_subject(context),
            body=_body(context),
            subject_template=rule.template,
            body_template=rule.body,
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


def _change_facts(event: AlertEvent, change: Change | None) -> JsonMap:
    """Name the event an alert was raised for and how the pipeline's previous settled run ended."""
    previous = change.previous if change is not None else None
    return {"event": event.value, "previous_status": previous.status.value if previous is not None else None}


def _history_entry(run: Run, rule: AlertRule, event: AlertEvent, moment: datetime) -> LogEntry:
    """Say on a backfill run's timeline that a rule on change stayed quiet, since history is not compared."""
    return LogEntry(
        run_id=run.id,
        level=LogLevel.INFO,
        message=f"alert {rule.code!r} not raised: a backfill run is history, and is not compared with the present",
        fields={"event": event.value},
        created_at=moment,
    )


def _unchanged_entry(run: Run, rule: AlertRule, event: AlertEvent, change: Change, moment: datetime) -> LogEntry:
    """Say on the run's timeline that a rule on change stayed quiet, and which run it matched."""
    previous = change.previous.run_id if change.previous is not None else None
    return LogEntry(
        run_id=run.id,
        level=LogLevel.INFO,
        message=f"alert {rule.code!r} not raised: the outcome is the same as the previous settled run's",
        fields={"event": event.value, "previous_run_id": str(previous) if previous is not None else None},
        created_at=moment,
    )


def _context_for(run: Run, facts: "RunFacts", *, output_cap: int) -> JsonMap:
    """The frozen context a notification carries: the run's facts, where it went wrong, and bounded outputs.

    A step output larger than ``output_cap`` bytes is the one the engine stored as an object
    rather than inline, and the context names it by its ``output_uri`` and ``output_bytes``
    with a null ``output``, in ``steps`` and in ``step`` alike.
    """
    # Imported here rather than at module scope: reporting imports this module back.
    from dirigent_core.reporting import as_context

    context = as_context(facts)
    steps = [_bounded(cast("JsonMap", one), output_cap) for one in cast("list[JsonValue]", context["steps"])]
    context["steps"] = cast("list[JsonValue]", steps)
    context["step"] = {cast("str", one["step"]): one for one in steps}
    return {**context, **failure_of(run, facts)}


def _bounded(step: JsonMap, cap: int) -> JsonMap:
    """A step's facts with its output left out when it is larger than ``cap`` bytes."""
    size = step.get("output_bytes")
    if isinstance(size, int) and size > cap:
        return {**step, "output": None}
    return step


def failure_of(run: Run, facts: "RunFacts") -> JsonMap:
    """Name where a failing run went wrong: the failing step, the fan-out element, and what was said.

    The first failed element's own refusal comes first, then the first failed step's, then the
    run's own error, which is what a run that failed outside every step carries. A run that did
    not fail names nothing.
    """
    found = failure_reason(run, facts)
    if found is None:
        return {"failing_step": None, "failing_item": None, "error": None, "error_code": None}
    return {
        "failing_step": found.step,
        "failing_item": found.item,
        "error": found.error,
        "error_code": found.code,
    }


class FailureReason(NamedTuple):
    """Where a failing run went wrong and what was said there, cut to the line an alert carries."""

    step: str | None
    item: str | None
    error: str | None
    code: str | None
    params: JsonMap | None


def failure_reason(run: Run, facts: "RunFacts") -> FailureReason | None:
    """Find what ``failure_of`` names, with the params of the refusal; nothing for a run that did not fail."""
    if run.status not in FAILING:
        return None
    step = next((one for one in facts.steps if one.outcome == "failed"), None)
    item = next(
        (
            one
            for one in facts.items
            if one.status is RunItemStatus.FAILED and (step is None or one.failing_step in (None, step.step))
        ),
        None,
    )
    error: str | None
    code: str | None
    params: Mapping[str, JsonValue] | None
    if item is not None and item.error:
        error, code, params = item.error, item.error_code, item.error_params
    elif step is not None and step.error:
        error, code, params = step.error, step.error_code, step.error_params
    else:
        error, code, params = run.error, run.error_code, run.error_params
    failing_step = step.step if step is not None else (item.failing_step if item is not None else None)
    return FailureReason(
        step=failing_step,
        item=item.key if item is not None else None,
        error=_said(error, code, params),
        code=code if error else None,
        params=dict(params) if error and params else None,
    )


def _said(error: str | None, code: str | None, params: Mapping[str, JsonValue] | None) -> str | None:
    """Cut a refusal to the one line an alert carries.

    A block that raised something it did not explain is named by a sentence that says only
    that, so what it raised is the line instead. Both were scrubbed of the step's secrets
    when the attempt was written, and nothing here reads anything else.
    """
    if not error:
        return None
    detail = (params or {}).get("raised_detail") if code == BLOCK_RAISED.code else None
    if isinstance(detail, str) and detail:
        kind = (params or {}).get("raised_kind")
        error = f"{kind}: {detail}" if isinstance(kind, str) and kind else detail
    return " ".join(error.split())[:ERROR_CAP]


async def _facts_of(session: AsyncSession, run: Run, *, base_url: str | None, rendered_at: datetime) -> "RunFacts":
    """Read a run's whole facts, for a rule that matched when the caller assembled none."""
    # Imported here rather than at module scope: reporting imports this module back.
    from dirigent_core.reporting import facts_of_run

    version = await session.get(PipelineVersion, run.pipeline_version_id)
    if version is None:  # pragma: no cover - a run always pins a version that exists
        raise AlertError(ALERT_VERSION_GONE, run=run.id)
    definition = load_definition(version.document)
    return await facts_of_run(session, run, definition, base_url=base_url, rendered_at=rendered_at)


def _default_subject(context: JsonMap) -> str:
    """Write the subject a rule with no subject template sends: the pipeline and how its run ended."""
    run = cast("JsonMap", context.get("run", {}))
    said = "recovered" if context.get("event") == AlertEvent.RUN_RECOVERED.value else as_text(run.get("status"))
    return _one_line(f"{as_text(run.get('pipeline'))} run {said}")


class Rendered(NamedTuple):
    """What a notification's templates rendered to, and why any of them fell back."""

    subject: str
    body: str
    fallbacks: list[tuple[str, str]]
    """Each template that did not render, as its field and the reason."""


async def _rendered(services: EngineServices, notification: Notification) -> Rendered:
    """Render a notification's subject and body templates on a worker thread, under the render budget.

    A rule's template that fails or passes its budget leaves the default the row already
    carries; a test message's leaves the text it was typed as, since it may never have been
    meant as a template.
    """
    context: JsonMap = {**(notification.context or {}), "report": notification.report}
    within = services.settings.report_render_timeout
    subject, body = notification.subject, notification.body
    fallbacks: list[tuple[str, str]] = []
    for field, source, cap in (
        ("subject", notification.subject_template, SUBJECT_RENDER_CAP),
        ("body", notification.body_template, int(services.settings.report_max_size)),
    ):
        if source is None:
            continue
        try:
            text = await render_off_loop(source, context, max_bytes=cap, within=within)
        except (TemplateError, RenderTooLarge) as error:
            if notification.event is not NotificationEvent.TEST:
                fallbacks.append((field, str(error)))
                continue
            text = source
        if field == "subject":
            subject = _one_line(text)
        else:
            body = text
    return Rendered(subject=subject, body=body, fallbacks=fallbacks)


def _keep_rendered(session: AsyncSession, notification: Notification, rendered: Rendered, moment: datetime) -> None:
    """Write what the templates rendered onto the row, and say in the run's timeline which fell back.

    A retry then sends the same text without rendering again.
    """
    notification.subject = rendered.subject
    notification.body = rendered.body
    notification.subject_template = None
    notification.body_template = None
    notification.report = None
    for field, reason in rendered.fallbacks:
        _logger.warning("alert template not rendered", rule=notification.rule_code, field=field, error=reason)
        if notification.run_id is None:
            continue
        session.add(
            LogEntry(
                run_id=notification.run_id,
                level=LogLevel.WARNING,
                message=f"the {field} of alert {notification.rule_code!r} was not rendered, so the default was sent",
                fields={"reason": reason, "notifier": notification.notifier},
                created_at=moment,
            )
        )


def _one_line(text: str) -> str:
    """Collapse a rendering to the single line a subject is, no longer than the cap."""
    return " ".join(text.split())[:SUBJECT_CAP]


def _body(context: JsonMap) -> str:
    """Render the default body: how the run ended and where, who started it, then the links.

    Short lines a person reads in a mail or a chat message, with the parameters as JSON.
    """
    run = cast("JsonMap", context.get("run", {}))
    status = as_text(run.get("status"))
    where = ", ".join(
        part
        for part in (
            f"at step {as_text(context.get('failing_step'))}" if context.get("failing_step") else "",
            f"item {as_text(context.get('failing_item'))}" if context.get("failing_item") else "",
        )
        if part
    )
    opening = " ".join(part for part in (OPENING.get(status, status.replace("_", " ").capitalize()), where) if part)
    if context.get("event") == AlertEvent.RUN_RECOVERED.value:
        previous = as_text(context.get("previous_status")).replace("_", " ")
        opening = f"{RECOVERED_OPENING}: the previous run {previous}"
    error = context.get("error")
    lines = [f"{opening}: {as_text(error)}" if error else f"{opening}."]
    started = f"Triggered by {as_text(run.get('trigger'))}" if run.get("trigger") else "Started"
    duration = run.get("duration_ms")
    if isinstance(duration, int) and duration > 0:
        started += f", ran for {format_duration(timedelta(milliseconds=duration))}"
    lines.append(f"{started}.")
    params = run.get("params")
    if params:
        lines.append(f"Params: {json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)}")
    if run.get("window_start") or run.get("window_end"):
        lines.append(f"Window: {as_text(run.get('window_start'))} to {as_text(run.get('window_end'))}.")
    if run.get("started_at"):
        moments = f"Started {as_text(run.get('started_at'))}"
        if run.get("finished_at"):
            moments += f", finished {as_text(run.get('finished_at'))}"
        lines.append(f"{moments}.")
    lines.append(f"Run: {as_text(run.get('url') or run.get('id'))}")
    if run.get("report_url"):
        lines.append(f"Report: {as_text(run.get('report_url'))}")
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
) -> list[Notification]:
    """Queue the alerts a terminal run status owes, if that status raises an event at all.

    The run's outcome is recorded as its pipeline's latest first, whether or not any rule
    watches it, so a rule declared later compares with the run before it. A run that succeeded
    where the previous settled run did not raises ``run_recovered`` as well. A backfill run is
    history rather than the present: it neither reads nor moves the outcome, and raises no
    recovery.
    """
    event = EVENT_FOR_STATUS.get(status)
    if event is None:
        return []
    history = run.triggered_by_kind is TriggerKind.BACKFILL
    change = None if history else await _recorded(session, run, status, now=now)
    raised: list[Notification] = []
    for each in (event, AlertEvent.RUN_RECOVERED) if change is not None and change.recovered else (event,):
        raised += await raise_for_run(session, services, run, each, now=now, change=change)
    return raised


async def _recorded(session: AsyncSession, run: Run, status: RunStatus, *, now: datetime | None) -> Change | None:
    """Record a settled run's outcome, or log why it could not be and compare nothing.

    A savepoint, logged rather than raised for the reason :func:`raise_for_run` gives.
    """
    try:
        async with session.begin_nested():
            return await record_outcome(session, run, status, now=now)
    except Exception as error:
        if is_deadlock(error):
            raise
        _logger.error("outcome not recorded", run_id=str(run.id), error=str(error))
        return None


async def attach_report(
    session: AsyncSession,
    services: EngineServices,
    run_id: UUID,
    *,
    report: str | None,
    artifact_id: UUID | None,
) -> int:
    """Hand a run's stored report to the alerts its settling raised, which nothing has claimed yet.

    Each gets ``run.report_url`` and a default body that links it, and a rule with a template
    gets the document its template reads as ``report``. A report that did not render hands on
    nothing, and the alerts go out without one. Say how many were handed it.
    """
    report_url = report_url_for(services.settings.alert_base_url, artifact_id)
    found = await session.execute(
        sa.select(Notification).where(
            Notification.run_id == run_id,
            Notification.status == NotificationStatus.PENDING,
            Notification.attempt == 0,
            Notification.event.in_(SETTLED_EVENTS),
        )
    )
    held = list(found.scalars())
    for notification in held:
        context = dict(notification.context or {})
        context["run"] = {**cast("JsonMap", context.get("run") or {}), "report_url": report_url}
        notification.context = context
        notification.body = _body(context)
        if notification.subject_template is not None or notification.body_template is not None:
            notification.report = report
    return len(held)


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
    connection: str | None = None,
    subject: str = TEST_SUBJECT,
    body: str = TEST_BODY,
) -> Notification:
    """Queue one unattached message, which is what ``dg alerts test`` sends.

    The message names one target the way a rule does, and the sender follows from that
    connection's kind. The subject and the body are rendered at delivery as a rule's are, over a
    stand-in context, so a template can be tried out before it is written onto a rule.
    """
    notifier, connection_id = await _target(session, services, connection)
    context: JsonMap = {"run": {"pipeline": "(test)", "status": "succeeded"}, "report": None}
    notification = Notification(
        alert_rule_id=None,
        run_id=None,
        event=NotificationEvent.TEST,
        notifier=notifier,
        connection_id=connection_id,
        subject=_one_line(subject),
        body=body,
        subject_template=subject,
        body_template=body,
        context=context,
        status=NotificationStatus.PENDING,
        available_at=utcnow(),
    )
    session.add(notification)
    await session.flush()
    return notification


class ClaimedNotification(BaseModel):
    """A notification one claim holds, and the generation that claim took."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    notification: Notification
    lease_token: UUID
    """The generation this claim took, which every later write of the row is fenced against."""


async def claim_notification(
    session: AsyncSession,
    *,
    owner: str,
    now: datetime,
    lease_seconds: int,
    notifiers: Collection[str] | None = None,
) -> ClaimedNotification | None:
    """Claim the next due notification, the same way a worker claims an attempt.

    ``notifiers`` narrows the claim to the notifiers this worker can send through; None claims any.
    An alert of a run still owing its report document waits for the document, which it links.
    """
    owing = sa.exists().where(Run.id == Notification.run_id, Run.report_due_at.is_not(None))
    statement = (
        sa.select(Notification)
        .where(Notification.status == NotificationStatus.PENDING, Notification.available_at <= now, ~owing)
        .order_by(Notification.available_at, Notification.id)
        .limit(CLAIM_LIMIT)
    )
    if notifiers is not None:
        statement = statement.where(Notification.notifier.in_(list(notifiers)))
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True, of=Notification)
    found = await session.execute(statement)
    notification = found.scalars().first()
    if notification is None:
        return None
    token = uuid7()
    notification.status = NotificationStatus.SENDING
    notification.lease_owner = owner
    notification.lease_token = token
    notification.lease_expires_at = now + timedelta(seconds=lease_seconds)
    notification.attempt += 1
    await session.flush()
    return ClaimedNotification(notification=notification, lease_token=token)


def notifier_config(services: EngineServices, notifier: Notifier, connection: Connection | None) -> BaseModel:
    """Open the connection a notifier delivers through, validated against its own model."""
    if connection is None:
        return notifier.config_model()
    if connection.awaiting_secrets:
        raise ConnectionAwaitingSecrets(
            connection.code,
            unset_secrets(
                notifier.config_model, dict(connection.config), sealed=connection.secret_envelope is not None
            ),
        )
    return services.secrets.decrypt_config(
        notifier.config_model, connection.config, connection.secret_envelope, key_id=connection.secret_key_id
    )


async def send_notification(
    session: AsyncSession,
    services: EngineServices,
    notification: Notification,
    *,
    owner: str,
    lease_token: UUID,
    now: datetime | None = None,
) -> bool:
    """Deliver one claimed notification, returning whether it was delivered.

    The outcome is written only while this claim still holds the lease, so a delivery that
    outlasted its lease cannot overwrite the outcome of the claim the row was handed to.

    THE SESSION IS COMMITTED BEFORE THE SEND, so no transaction is open while an outbound
    call is in flight: on SQLite that transaction holds the one write lock, and everything
    else on the instance -- the sweeper reclaiming this very row, the API, a worker settling
    an attempt -- would queue behind a notifier that is slow to answer. Nothing read above
    has to be held anyway, because the fence below re-reads the row it writes.
    """
    moment = now or utcnow()
    secrets: set[str] = set()
    rendered: Rendered | None = None
    try:
        notifier = services.host.notifiers.get(notification.notifier)
        if notifier is None:
            raise AlertError(NOTIFIER_NOT_ON_WORKER, notifier=repr(notification.notifier))
        connection = await session.get(Connection, notification.connection_id) if notification.connection_id else None
        config = notifier_config(services, notifier, connection)
        secrets = secrets_of(config)
        await session.commit()
        rendered = await _rendered(services, notification)
        await _sent(services, notifier, _message(notification, rendered.subject, rendered.body), config)
    except Exception as error:
        if not await _holds_lease(session, notification, owner, lease_token):
            return False
        if rendered is not None:
            _keep_rendered(session, notification, rendered, moment)
        return await _record_failure(session, services, notification, error, moment, secrets)
    if not await _holds_lease(session, notification, owner, lease_token):
        return False
    _keep_rendered(session, notification, rendered, moment)
    notification.status = NotificationStatus.SENT
    notification.sent_at = moment
    notification.error = None
    notification.lease_owner = None
    notification.lease_token = None
    notification.lease_expires_at = None
    _timeline(session, notification, LogLevel.INFO, f"alert delivered through {notification.notifier!r}", moment)
    _logger.info("notification delivered", notification_id=str(notification.id), notifier=notification.notifier)
    return True


async def _sent(services: EngineServices, notifier: Notifier, message: AlertMessage, config: BaseModel) -> None:
    """Send one message, failing it once it has taken longer than ``notification_timeout``."""
    within = services.settings.notification_timeout
    deadline = asyncio.timeout(within.total_seconds())
    try:
        async with deadline:
            await notifier.send(message, config)
    except TimeoutError as error:
        if not deadline.expired():
            raise
        raise AlertError(NOTIFIER_TIMED_OUT, notifier=repr(notifier.id), timeout=format_duration(within)) from error


async def _holds_lease(session: AsyncSession, notification: Notification, owner: str, lease_token: UUID) -> bool:
    """Re-read the row and report whether this claim may still write this outcome.

    The lease is a fence, not a hint: a row the sweeper returned to the queue belongs to
    whoever claimed it next, and writing into it would replace a live delivery's outcome
    with the outcome of an abandoned one. The token is what makes that hold when the
    somebody else is this worker again: a name matches its own next claim, a token never does.
    """
    found = await session.execute(
        sa.select(Notification.status, Notification.lease_owner, Notification.lease_token).where(
            Notification.id == notification.id
        )
    )
    row = found.one_or_none()
    if (
        row is not None
        and row.status is NotificationStatus.SENDING
        and row.lease_owner == owner
        and row.lease_token == lease_token
    ):
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
    lease_token: UUID,
    lease_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Push a notification's lease out, reporting whether this claim still held it.

    A renewal names the claim's generation as well as its row, so one that outlived its lease
    extends nothing: the row it names is either unclaimed or held by a later claim, this
    worker's own next one included.
    """
    moment = now or utcnow()
    renewed = await session.execute(
        sa.update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.status == NotificationStatus.SENDING,
            Notification.lease_owner == owner,
            Notification.lease_token == lease_token,
        )
        .values(lease_expires_at=moment + timedelta(seconds=lease_seconds))
        .returning(Notification.id)
        .execution_options(synchronize_session=False)
    )
    return renewed.scalar_one_or_none() is not None


def _message(notification: Notification, subject: str, body: str) -> AlertMessage:
    """Render a stored notification as the message the notifier surface takes."""
    context = notification.context or {}
    run = cast("JsonMap", context.get("run", {}))
    return AlertMessage(
        event=notification.event.value,
        subject=subject,
        body=body,
        run_id=notification.run_id,
        pipeline=cast("str | None", run.get("pipeline")),
        url=cast("str | None", run.get("url")),
        error_code=cast("str | None", run.get("error_code")),
        error_params=cast("dict[str, JsonValue]", run.get("error_params") or {}),
        context=cast("dict[str, JsonValue]", context),
    )


async def _record_failure(
    session: AsyncSession,
    services: EngineServices,
    notification: Notification,
    error: Exception,
    moment: datetime,
    secrets: set[str],
) -> bool:
    """Schedule another delivery, or record that this one is never going to arrive."""
    message = scrub(f"{type(error).__name__}: {error}", secrets)
    notification.error = message
    notification.lease_owner = None
    notification.lease_token = None
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
        raise NotificationInFlight
    notification.status = NotificationStatus.PENDING
    notification.available_at = now or utcnow()
    notification.attempt = 0
    notification.error = None
    notification.sent_at = None
    notification.lease_owner = None
    notification.lease_token = None
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
            lease_token=None,
            lease_expires_at=None,
        )
        .returning(Notification.id)
        .execution_options(synchronize_session=False)
    )
    return len(recovered.scalars().all())


#: The registry states of a worker that claims notifications, or is about to.
SENDING_WORKERS: Final = (WorkerStatus.STARTING, WorkerStatus.RUNNING)


async def fail_unsendable_notifications(
    session: AsyncSession, *, waited: timedelta, now: datetime | None = None
) -> int:
    """Fail every pending notification due for longer than ``waited`` whose notifier no live worker has.

    A worker claims only what it can send, so such a notification would otherwise wait forever.
    """
    moment = now or utcnow()
    found = await session.execute(sa.select(Worker.notifiers).where(Worker.status.in_(SENDING_WORKERS)))
    installed = {str(name) for names in found.scalars() for name in names}
    statement = sa.select(Notification).where(
        Notification.status == NotificationStatus.PENDING, Notification.available_at < moment - waited
    )
    if installed:
        statement = statement.where(Notification.notifier.not_in(sorted(installed)))
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    failed = list((await session.execute(statement)).scalars())
    for notification in failed:
        message = NOTIFIER_NOT_ON_WORKER.render(notifier=repr(notification.notifier))
        notification.status = NotificationStatus.FAILED
        notification.error = f"AlertError: {message}"
        _timeline(
            session,
            notification,
            LogLevel.ERROR,
            f"alert could not be delivered through {notification.notifier!r}: {message}",
            moment,
        )
        _logger.error(
            "notification failed terminally",
            notification_id=str(notification.id),
            notifier=notification.notifier,
            error=message,
        )
    return len(failed)


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
                claim = await claim_notification(
                    session,
                    owner=self.owner,
                    now=moment,
                    lease_seconds=int(self.services.settings.notification_lease.total_seconds()),
                    notifiers=self.services.host.notifiers.keys(),
                )
                if claim is None:
                    return sent
                notification_id, lease_token = claim.notification.id, claim.lease_token
            async with session_scope(self.sessions) as session:
                claimed = await session.get(Notification, notification_id)
                if claimed is None:  # pragma: no cover - it was just claimed
                    continue
                async with self._renewing(notification_id, lease_token):
                    delivered = await send_notification(
                        session, self.services, claimed, owner=self.owner, lease_token=lease_token, now=now
                    )
                if delivered:
                    sent += 1
        return sent

    @asynccontextmanager
    async def _renewing(self, notification_id: UUID, lease_token: UUID) -> AsyncGenerator[None]:
        """Hold a notification's lease open for as long as its delivery is in flight."""
        halting = asyncio.Event()
        renewing = asyncio.create_task(self._renew_until_halted(notification_id, lease_token, halting))
        try:
            yield
        finally:
            halting.set()
            await renewing

    async def _renew_until_halted(self, notification_id: UUID, lease_token: UUID, halting: asyncio.Event) -> None:
        """Extend the lease on a cadence until halted, or until the row is no longer this claim's.

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
                    renewed = await renew_lease(
                        session,
                        notification_id,
                        owner=self.owner,
                        lease_token=lease_token,
                        lease_seconds=lease_seconds,
                    )
                    if not renewed:
                        return
            except Exception as error:  # the delivery runs on; the sweeper reclaims if it outlasts the lease
                _logger.warning(
                    "notification lease renewal failed", notification_id=str(notification_id), error=str(error)
                )
                return
