"""The baseline schema: immutable definitions, triggers, and mutable execution state."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from dirigent_client.enums import (
    AlertEvent,
    AlertScope,
    AttemptKind,
    AttemptStatus,
    FiringOutcome,
    LogLevel,
    NotificationStatus,
    ProvenanceSource,
    RunItemStatus,
    RunPriority,
    RunStatus,
    ScheduleKind,
    TokenKind,
    TriggerKind,
    UserRole,
    WebhookOutcome,
    WorkerStatus,
)
from dirigent_common import JsonList, JsonMap
from dirigent_core.ids import uuid7
from dirigent_core.types import BigId, JsonDocument, Timestamp, string_enum

#: Predictable constraint and index names, so migrations can always address them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Return the current instant as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base carrying the shared metadata and naming convention."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class Entity(Base):
    """A row with its own identity: a time-ordered id, and the two stamps every entity carries."""

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid7, sort_order=-100)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, default=utcnow, server_default=sa.func.now(), sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, default=utcnow, onupdate=utcnow, server_default=sa.func.now(), sort_order=100
    )


class Journal(Base):
    """A row that is written once and never updated, keyed by the integer that also orders it."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True, sort_order=-100)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, default=utcnow, server_default=sa.func.now(), sort_order=100
    )


class Pipeline(Entity):
    """A coded definition with immutable versions; the code is the only portable identity.

    Deleting the row takes its versions, schedules, webhooks and alert rules with it, and
    the code becomes free again.
    """

    __tablename__ = "pipelines"

    code: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    tags: Mapped[JsonList] = mapped_column(JsonDocument, nullable=False, default=list)
    """What the current document says this pipeline is for; an apply replaces the whole list."""

    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    current_version: Mapped[int | None] = mapped_column(sa.Integer)


class PipelineVersion(Entity):
    """One immutable definition document, its digest, and where it came from."""

    __tablename__ = "pipeline_versions"
    __table_args__ = (sa.UniqueConstraint("pipeline_id", "version"),)

    pipeline_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    document: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False)
    step_order: Mapped[list[str]] = mapped_column(JsonDocument, nullable=False, default=list[str])
    """The step names in the order their author wrote them.

    The stored document is canonical, and PostgreSQL normalises jsonb key order besides, so
    the order a person reads their pipeline in survives nowhere else."""

    digest: Mapped[str] = mapped_column(sa.String(71), nullable=False, index=True)
    provenance_source: Mapped[ProvenanceSource] = mapped_column(
        string_enum(ProvenanceSource, "provenance_source"), nullable=False, default=ProvenanceSource.API
    )
    provenance_ref: Mapped[str | None] = mapped_column(sa.Text)
    applied_by: Mapped[str | None] = mapped_column(sa.String(200))

    @property
    def ordered_document(self) -> JsonMap:
        """The stored document with its steps back in the order their author wrote them."""
        document = dict(self.document)
        steps = document.get("steps")
        if not isinstance(steps, dict) or not self.step_order:
            return document
        held = cast("JsonMap", steps)
        ordered = {name: held[name] for name in self.step_order if name in held}
        ordered.update({name: body for name, body in held.items() if name not in ordered})
        document["steps"] = ordered
        return document


class Connection(Entity):
    """A coded credential record of some plugin-provided kind, with secrets encrypted at rest."""

    __tablename__ = "connections"

    code: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    kind: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(sa.Text)
    config: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    secret_envelope: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    secret_key_id: Mapped[str | None] = mapped_column(sa.String(100))
    last_check_at: Mapped[datetime | None] = mapped_column(Timestamp)
    last_check_healthy: Mapped[bool | None] = mapped_column(sa.Boolean)
    last_check_detail: Mapped[str | None] = mapped_column(sa.Text)


class Schema(Entity):
    """A named JSON Schema an instance holds, addressable by code and referenced by name.

    The body is a JSON Schema in its own right, and its identity is read from the schema's
    own keywords when it is stored: ``$id`` is the code, ``title`` the name, ``description``
    the description. So what is stored is a portable schema, not a wrapper around one.
    """

    __tablename__ = "schemas"

    code: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    body: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)


class Run(Entity):
    """One execution of a pinned pipeline version with resolved parameters and an attributed trigger."""

    __tablename__ = "runs"
    __table_args__ = (
        sa.Index("ix_runs_pipeline_id_status_created_at", "pipeline_id", "status", "created_at"),
        sa.Index("ix_runs_finished_at", "finished_at"),
    )

    pipeline_id: Mapped[UUID] = mapped_column(sa.ForeignKey("pipelines.id", ondelete="RESTRICT"), nullable=False)
    pipeline_version_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("pipeline_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        string_enum(RunStatus, "run_status"), nullable=False, default=RunStatus.QUEUED, index=True
    )
    priority: Mapped[RunPriority] = mapped_column(
        string_enum(RunPriority, "run_priority"),
        nullable=False,
        default=RunPriority.NORMAL,
        server_default=RunPriority.NORMAL.value,
    )
    """How far ahead of other runs the claim takes this one's attempts.

    Resolved and pinned at creation, so editing the document does not reorder a run in
    flight."""

    params: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    triggered_by_kind: Mapped[TriggerKind] = mapped_column(
        string_enum(TriggerKind, "trigger_kind"), nullable=False, default=TriggerKind.ADHOC
    )
    triggered_by_id: Mapped[UUID | None] = mapped_column(sa.Uuid)
    triggered_by_label: Mapped[str | None] = mapped_column(sa.String(200))
    traceparent: Mapped[str | None] = mapped_column(sa.String(64))
    """The trace context the run was created in, which every attempt of it opens under."""
    error: Mapped[str | None] = mapped_column(sa.Text)
    started_at: Mapped[datetime | None] = mapped_column(Timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)

    window_start: Mapped[datetime | None] = mapped_column(Timestamp)
    """The logical data interval this run covers, half-open: ``[window_start, window_end)``.

    Both columns are set or neither is. A schedule-fired run derives them from the cadence, a
    backfill from the window it is filling, and an ad hoc run only if it was asked for."""

    window_end: Mapped[datetime | None] = mapped_column(Timestamp)

    log_levels: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    """Which log levels this run keeps, as a map of block-id pattern to level.

    None keeps the default: info and up. The most specific pattern wins, so
    ``{"*": "info", "acme.*": "debug"}`` is one loud family in a quiet run."""

    worker_tags: Mapped[JsonList] = mapped_column(JsonDocument, nullable=False, default=list)
    """The tags a worker must carry to claim this run, pinned from ``requires.workers``.

    Pinned at creation, so a later version of the document does not re-route a run in
    flight. An empty list is claimable by any worker."""


class RunItem(Entity):
    """One element of a fan-out step's mapped input, with its own status and retry."""

    __tablename__ = "run_items"
    __table_args__ = (sa.UniqueConstraint("run_id", "step_name", "item_index"),)

    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    item_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    item_key: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    item_value: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    status: Mapped[RunItemStatus] = mapped_column(
        string_enum(RunItemStatus, "run_item_status"), nullable=False, default=RunItemStatus.PENDING, index=True
    )
    failing_step: Mapped[str | None] = mapped_column(sa.String(200))
    error: Mapped[str | None] = mapped_column(sa.Text)
    started_at: Mapped[datetime | None] = mapped_column(Timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)


class StepAttempt(Entity):
    """One try of one step: the unit workers claim, lease, park, and probe."""

    __tablename__ = "step_attempts"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "step_name", "run_item_id", "attempt"),
        sa.UniqueConstraint("run_id", "idempotency_key"),
        sa.Index("ix_step_attempts_status_available_at", "status", "available_at"),
        sa.Index("ix_step_attempts_status_next_poll_at", "status", "next_poll_at"),
        sa.Index("ix_step_attempts_lease_expires_at", "lease_expires_at"),
    )

    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_item_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("run_items.id", ondelete="CASCADE"), index=True)
    step_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    block_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    kind: Mapped[AttemptKind] = mapped_column(
        string_enum(AttemptKind, "attempt_kind"), nullable=False, default=AttemptKind.AUTOMATIC
    )
    status: Mapped[AttemptStatus] = mapped_column(
        string_enum(AttemptStatus, "attempt_status"), nullable=False, default=AttemptStatus.PENDING
    )

    available_at: Mapped[datetime | None] = mapped_column(Timestamp)
    next_poll_at: Mapped[datetime | None] = mapped_column(Timestamp)
    deadline_at: Mapped[datetime | None] = mapped_column(Timestamp)

    lease_owner: Mapped[str | None] = mapped_column(sa.String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(Timestamp)
    heartbeat_at: Mapped[datetime | None] = mapped_column(Timestamp)

    remote_handle: Mapped[JsonMap | None] = mapped_column(JsonDocument)

    poke_cursor: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    """How far a sensor's poke has read, handed to the next poke as ``ctx.cursor``."""

    gone_probes: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default=sa.text("0"))
    poke_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default=sa.text("0"))

    waiting_message: Mapped[str | None] = mapped_column(sa.String(500))
    """What the last probe or poke said it was seeing, while the attempt waits."""

    waiting_progress: Mapped[float | None] = mapped_column(sa.Float)

    idempotency_key: Mapped[str | None] = mapped_column(sa.String(400))
    """What a manual retry was keyed on, scoped to the step and item it retried.

    The stored value is the scoped key rendered by ``idempotency_scope``, and the unique
    constraint on it is what makes "this retry happens once" hold across processes."""

    input: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    output: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    output_artifact_id: Mapped[UUID | None] = mapped_column(sa.Uuid)
    error: Mapped[str | None] = mapped_column(sa.Text)
    error_class: Mapped[str | None] = mapped_column(sa.String(32))

    started_at: Mapped[datetime | None] = mapped_column(Timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)


class TriggerDocument(Entity):
    """A ``kind: triggers`` document: clocks and webhooks for a pipeline defined elsewhere.

    It has no versions. The digest is what makes an unchanged re-apply cheap, and the rows it
    owns name it, so a reconcile of one owner never reaches another's. Deleting it, or the
    pipeline it names, takes those rows with it.
    """

    __tablename__ = "trigger_documents"

    code: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    pipeline_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(71), nullable=False, index=True)
    provenance_source: Mapped[ProvenanceSource] = mapped_column(
        string_enum(ProvenanceSource, "provenance_source"), nullable=False, default=ProvenanceSource.API
    )
    provenance_ref: Mapped[str | None] = mapped_column(sa.Text)
    applied_by: Mapped[str | None] = mapped_column(sa.String(200))


class Schedule(Entity):
    """A pipeline's clock: cron, interval, or one-time, in its own timezone."""

    __tablename__ = "schedules"
    __table_args__ = (
        sa.UniqueConstraint("pipeline_id", "code"),
        sa.Index("ix_schedules_paused_next_fire_at", "paused", "next_fire_at"),
    )

    pipeline_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    kind: Mapped[ScheduleKind] = mapped_column(string_enum(ScheduleKind, "schedule_kind"), nullable=False)
    cron: Mapped[str | None] = mapped_column(sa.String(200))
    interval_seconds: Mapped[int | None] = mapped_column(sa.Integer)
    run_at: Mapped[datetime | None] = mapped_column(Timestamp)
    timezone: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="UTC", server_default="UTC")
    params: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    connection_pins: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    log_levels: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    """The log-level map copied onto every run this schedule fires."""
    priority: Mapped[RunPriority | None] = mapped_column(string_enum(RunPriority, "run_priority"))
    """The priority every fired run carries, or null to take the pipeline's own."""
    managed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    """Whether a document's ``triggers:`` section owns this row, and may therefore remove it."""

    trigger_document_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("trigger_documents.id", ondelete="CASCADE"), index=True
    )
    """Which triggers document owns this row, or null when the pipeline's own document does."""

    paused: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    next_fire_at: Mapped[datetime | None] = mapped_column(Timestamp)
    last_fired_at: Mapped[datetime | None] = mapped_column(Timestamp)


class ScheduleFiring(Journal):
    """One tick's decision about one due schedule: what it was due for, and what happened.

    A firing is recorded whatever the outcome, including the ones that create no run.
    """

    __tablename__ = "schedule_firings"
    __table_args__ = (
        sa.Index("ix_schedule_firings_schedule_id_id", "schedule_id", "id"),
        sa.Index("ix_schedule_firings_created_at", "created_at"),
    )

    schedule_id: Mapped[UUID] = mapped_column(sa.ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("runs.id", ondelete="SET NULL"))
    scheduled_for: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    """The ``next_fire_at`` the schedule was claimed at, which is the clock time it owes."""

    outcome: Mapped[FiringOutcome] = mapped_column(string_enum(FiringOutcome, "firing_outcome"), nullable=False)
    misfired: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    """Whether this firing was late past the misfire grace, and therefore fired once and advanced."""

    detail: Mapped[str | None] = mapped_column(sa.Text)


class WebhookTrigger(Entity):
    """An inbound endpoint: a hashed token, an optional HMAC secret, and a strict payload mapping."""

    __tablename__ = "webhook_triggers"
    __table_args__ = (sa.UniqueConstraint("pipeline_id", "code"),)

    pipeline_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    token_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="", server_default="")
    """The leading characters of the token, shown in listings."""

    hmac_secret: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    """The signing secret, sealed by the instance key exactly as a connection's secrets are.

    What is stored is the ciphertext of ``{"hmac_secret": "..."}``, and the key that sealed it
    is named in :attr:`hmac_secret_key_id`."""

    hmac_secret_key_id: Mapped[str | None] = mapped_column(sa.String(100))
    """Which key sealed :attr:`hmac_secret`, mirroring ``connections.secret_key_id``."""

    params_from_payload: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    priority: Mapped[RunPriority | None] = mapped_column(string_enum(RunPriority, "run_priority"))
    """The priority every accepted delivery's run carries, or null to take the pipeline's own."""
    managed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    """Whether a document's ``triggers:`` section owns this row, and may therefore remove it."""

    trigger_document_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("trigger_documents.id", ondelete="CASCADE"), index=True
    )
    """Which triggers document owns this row, or null when the pipeline's own document does."""

    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    rate_limit_per_minute: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=60, server_default=sa.text("60")
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(Timestamp)


class WebhookDelivery(Journal):
    """One inbound call: what arrived, what it mapped to, and the run or the refusal it produced."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        sa.Index("ix_webhook_deliveries_webhook_id_id", "webhook_id", "id"),
        sa.Index("ix_webhook_deliveries_created_at", "created_at"),
    )

    webhook_id: Mapped[UUID] = mapped_column(sa.ForeignKey("webhook_triggers.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("runs.id", ondelete="SET NULL"))
    outcome: Mapped[WebhookOutcome] = mapped_column(string_enum(WebhookOutcome, "webhook_outcome"), nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    payload: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    """What arrived, truncated to a readable size."""

    mapped_params: Mapped[JsonMap | None] = mapped_column(JsonDocument)
    source: Mapped[str | None] = mapped_column(sa.String(64))


class AlertRule(Entity):
    """An event-to-channel binding, declared as data rather than code."""

    __tablename__ = "alert_rules"

    code: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    event: Mapped[AlertEvent] = mapped_column(string_enum(AlertEvent, "alert_event"), nullable=False, index=True)
    scope: Mapped[AlertScope] = mapped_column(
        string_enum(AlertScope, "alert_scope"), nullable=False, default=AlertScope.GLOBAL
    )
    pipeline_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("pipelines.id", ondelete="CASCADE"), index=True)
    notifier: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    connection_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("connections.id", ondelete="RESTRICT"))
    template: Mapped[str | None] = mapped_column(sa.Text)
    """The subject, a Jinja template over the run's facts; the module's default when null."""

    body: Mapped[str | None] = mapped_column(sa.Text)
    """The body, a Jinja template over the same facts; the run's facts one per line when null."""

    throttle_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default=sa.text("0"))
    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    paused: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    """Instance state rather than document state: an apply rewrites the rule and leaves this."""

    last_sent_at: Mapped[datetime | None] = mapped_column(Timestamp)


class Notification(Entity):
    """One queued alert delivery: engine work, claimed and retried exactly like an attempt.

    The unique constraint is the deduplication: one rule says one thing about one run once.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        sa.UniqueConstraint("alert_rule_id", "run_id", "event"),
        sa.Index("ix_notifications_status_available_at", "status", "available_at"),
        sa.Index("ix_notifications_created_at", "created_at"),
    )

    alert_rule_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True)
    """The rule that raised this, or null for a test message sent through ``dg alerts test``."""

    run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    event: Mapped[AlertEvent] = mapped_column(string_enum(AlertEvent, "alert_event"), nullable=False)
    notifier: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    connection_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("connections.id", ondelete="RESTRICT"))
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False, default="", server_default="")
    context: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    status: Mapped[NotificationStatus] = mapped_column(
        string_enum(NotificationStatus, "notification_status"), nullable=False, default=NotificationStatus.PENDING
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default=sa.text("0"))
    available_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False, default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(sa.String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(Timestamp)
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp)
    error: Mapped[str | None] = mapped_column(sa.Text)


class LogEntry(Journal):
    """Append-only product telemetry, scoped to run, item, and attempt, written in batches."""

    __tablename__ = "log_entries"
    __table_args__ = (
        sa.Index("ix_log_entries_run_id_id", "run_id", "id"),
        sa.Index("ix_log_entries_created_at", "created_at"),
    )

    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run_item_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("run_items.id", ondelete="CASCADE"))
    step_attempt_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("step_attempts.id", ondelete="CASCADE"))
    step_name: Mapped[str | None] = mapped_column(sa.String(200))
    level: Mapped[LogLevel] = mapped_column(string_enum(LogLevel, "log_level"), nullable=False, default=LogLevel.INFO)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    fields: Mapped[JsonMap | None] = mapped_column(JsonDocument)


class Worker(Entity):
    """The worker registry: who is alive, on what version, with which plugins and tags."""

    __tablename__ = "workers"

    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    hostname: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    plugins: Mapped[JsonMap] = mapped_column(JsonDocument, nullable=False, default=dict)
    tags: Mapped[JsonList] = mapped_column(JsonDocument, nullable=False, default=list)
    concurrency: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1, server_default=sa.text("1"))
    status: Mapped[WorkerStatus] = mapped_column(
        string_enum(WorkerStatus, "worker_status"), nullable=False, default=WorkerStatus.STARTING
    )
    catalog_digest: Mapped[str | None] = mapped_column(sa.String(71))
    last_seen_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, default=utcnow, server_default=sa.func.now(), index=True, sort_order=101
    )


class ArtifactRef(Entity):
    """A step output passed by URI through pluggable storage; small values may inline."""

    __tablename__ = "artifact_refs"

    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_attempt_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("step_attempts.id", ondelete="CASCADE"))
    step_name: Mapped[str | None] = mapped_column(sa.String(200))
    uri: Mapped[str | None] = mapped_column(sa.Text)
    scheme: Mapped[str | None] = mapped_column(sa.String(32))
    content_type: Mapped[str | None] = mapped_column(sa.String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigId)
    digest: Mapped[str | None] = mapped_column(sa.String(71))
    inline_value: Mapped[JsonMap | None] = mapped_column(JsonDocument)


class User(Entity):
    """A local account, with its password stored only as an Argon2id hash."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(sa.String(200))
    email: Mapped[str | None] = mapped_column(sa.String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(string_enum(UserRole, "user_role"), nullable=False)
    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    last_login_at: Mapped[datetime | None] = mapped_column(Timestamp)


class ApiToken(Entity):
    """A bearer credential for automation, or a browser session; only its hash is stored."""

    __tablename__ = "api_tokens"
    __table_args__ = (sa.Index("ix_api_tokens_user_id_kind", "user_id", "kind"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    kind: Mapped[TokenKind] = mapped_column(string_enum(TokenKind, "token_kind"), nullable=False, default=TokenKind.API)
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    """The leading characters of the token, shown in listings."""

    expires_at: Mapped[datetime | None] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    last_used_at: Mapped[datetime | None] = mapped_column(Timestamp)


#: Every table in the schema, in dependency order.
ALL_TABLES = (
    Pipeline,
    PipelineVersion,
    Connection,
    Schema,
    Run,
    RunItem,
    StepAttempt,
    TriggerDocument,
    Schedule,
    ScheduleFiring,
    WebhookTrigger,
    WebhookDelivery,
    AlertRule,
    Notification,
    LogEntry,
    Worker,
    ArtifactRef,
    User,
    ApiToken,
)
