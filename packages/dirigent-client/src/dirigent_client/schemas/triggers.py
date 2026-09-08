"""A pipeline's persisted triggers: its schedules and its inbound webhooks."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator

from dirigent_client.enums import (
    FiringOutcome,
    LogLevel,
    ProvenanceSource,
    RunPriority,
    ScheduleKind,
    WebhookOutcome,
)
from dirigent_client.schemas.common import WireModel
from dirigent_common import EntityName, JsonMap
from dirigent_common.durations import Duration


class ScheduleIn(BaseModel):
    """A schedule as a caller declares it: exactly one clock, in its own timezone."""

    code: EntityName
    name: str | None = None
    description: str | None = None
    cron: str | None = None
    interval: Duration | None = None
    at: datetime | None = None
    timezone: str = "UTC"
    params: JsonMap = Field(default_factory=dict)
    connection_pins: JsonMap = Field(default_factory=dict)
    log_levels: dict[str, LogLevel] | None = Field(
        default=None,
        description=(
            "The log-level map every fired run carries, as block-id patterns; the most "
            "specific pattern wins. Omitted keeps info and up."
        ),
    )
    priority: RunPriority | None = Field(
        default=None,
        description="The priority every fired run carries. Omitted takes the pipeline's own.",
    )

    @field_validator("log_levels")
    @classmethod
    def _a_pattern_names_something(cls, value: dict[str, LogLevel] | None) -> dict[str, LogLevel] | None:
        """Refuse an empty pattern, which would match nothing and say nothing."""
        if value is not None and any(not pattern for pattern in value):
            raise ValueError("log_levels: a pattern may not be empty")
        return value


class SchedulePreviewRequest(BaseModel):
    """A clock as it is being written, for reading back what it would fire.

    The three expressions are text rather than parsed values: a clock is previewed while it is
    being typed, so a half-written interval is an answer saying what is wrong with it rather
    than a request the server refuses to read.
    """

    cron: str | None = None
    interval: str | None = None
    at: str | None = None
    timezone: str = "UTC"


class SchedulePreview(WireModel):
    """The next firings of a clock nothing has declared yet, oldest first."""

    firings: list[datetime]


class ScheduleOut(WireModel):
    """A schedule as a listing shows it."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    kind: ScheduleKind
    cron: str | None = None
    interval: str | None = None
    at: datetime | None = None
    timezone: str
    params: JsonMap = Field(default_factory=dict)
    log_levels: dict[str, LogLevel] | None = None
    priority: RunPriority | None = None
    """The priority every fired run carries, or null when it takes the pipeline's own."""
    paused: bool
    managed: bool
    trigger_document: str | None = None
    """The triggers document that declares this row, or null when the pipeline's own does."""

    next_fire_at: datetime | None = None
    last_fired_at: datetime | None = None
    created_at: datetime


class FiringOut(WireModel):
    """One recorded firing: what it was due for, and what came of it."""

    id: int
    scheduled_for: datetime
    created_at: datetime
    outcome: FiringOutcome
    misfired: bool
    run_id: UUID | None = None
    detail: str | None = None


class WebhookIn(BaseModel):
    """A webhook as a caller declares it; the token is never supplied, only minted."""

    code: EntityName
    name: str | None = None
    description: str | None = None
    params_from_payload: dict[str, str] = Field(default_factory=dict[str, str])
    hmac_secret: SecretStr | None = Field(default=None, min_length=1)
    """The signing secret, or null for an unsigned webhook; an empty string is neither."""

    rate_limit_per_minute: int = Field(default=60, ge=1)
    priority: RunPriority | None = Field(
        default=None,
        description="The priority every accepted delivery's run carries. Omitted takes the pipeline's own.",
    )


class WebhookOut(WireModel):
    """A webhook as a listing shows it: everything about it except the token."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    token_prefix: str
    params_from_payload: dict[str, str] = Field(default_factory=dict[str, str])
    signed: bool
    """Whether this webhook requires an HMAC signature; the secret itself never leaves."""

    active: bool
    managed: bool
    trigger_document: str | None = None
    """The triggers document that declares this row, or null when the pipeline's own does."""

    rate_limit_per_minute: int
    priority: RunPriority | None = None
    """The priority every accepted delivery's run carries, or null when it takes the pipeline's own."""

    last_delivery_at: datetime | None = None
    created_at: datetime


class TriggerDocumentOut(WireModel):
    """A ``kind: triggers`` document as a listing shows it."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    pipeline: str
    """The code of the pipeline these triggers fire."""

    digest: str
    provenance_source: ProvenanceSource
    provenance_ref: str | None = None
    applied_by: str | None = None
    created_at: datetime
    updated_at: datetime


class TriggerDocumentDetail(TriggerDocumentOut):
    """The document itself, and the rows it owns on the pipeline it names."""

    document: JsonMap
    schedules: list[str] = Field(default_factory=list[str])
    webhooks: list[str] = Field(default_factory=list[str])


class WebhookTokenOut(WireModel):
    """A freshly minted webhook token, returned once and never readable again."""

    webhook_id: UUID
    code: str
    token: str
    prefix: str
    url_path: str
    """Where to POST, so a caller can be configured without assembling the path by hand."""


class HookAccepted(WireModel):
    """What an accepted delivery answers with: the run it started, or why it started none."""

    run_id: UUID | None = None
    outcome: WebhookOutcome
    detail: str | None = None


class DeliveryOut(WireModel):
    """One inbound delivery, and what came of it."""

    id: int
    created_at: datetime
    outcome: WebhookOutcome
    run_id: UUID | None = None
    reason: str | None = None
    mapped_params: JsonMap | None = None
    source: str | None = None
