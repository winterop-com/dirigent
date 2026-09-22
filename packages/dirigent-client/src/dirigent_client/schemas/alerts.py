"""Alert rules, and the notification queue they deliver through."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field

from dirigent_client.enums import AlertEvent, AlertScope, Importance, NotificationStatus
from dirigent_client.schemas.common import WireModel
from dirigent_common import EntityName
from dirigent_common.durations import Duration

#: The notifier a rule that names no connection delivers through.
LOG_NOTIFIER = "log"

SUBJECT_HELP = "Subject, a Jinja template over the run's facts."

BODY_HELP = "Body, a Jinja template over the run's facts; `report` is the run's report document when it has one."

IMPORTANCE_HELP = "The least importance a pipeline must carry before this rule fires; absent fires for every one."

CONNECTION_HELP = (
    "The connection this rule delivers through, whose kind names the sender; absent delivers to the process log."
)


class AlertRuleIn(BaseModel):
    """An alert rule as a caller declares it."""

    code: EntityName
    name: str | None = None
    description: str | None = None
    event: AlertEvent
    scope: AlertScope = AlertScope.GLOBAL
    pipeline: str | None = None
    importance: Importance | None = Field(default=None, description=IMPORTANCE_HELP)
    connection: str | None = Field(default=None, description=CONNECTION_HELP)
    template: str | None = Field(default=None, description=SUBJECT_HELP)
    body: str | None = Field(default=None, description=BODY_HELP)
    throttle: Duration = timedelta(0)


class AlertRuleOut(WireModel):
    """An alert rule as a listing shows it."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    event: AlertEvent
    scope: AlertScope
    pipeline: str | None = None
    importance: Importance | None = None
    """The least importance a pipeline must carry before this rule fires."""

    notifier: str
    """The sender this rule's target resolved to, which is its connection's kind or the log."""

    connection: str | None = None
    template: str | None = None
    body: str | None = None
    throttle: str
    active: bool
    paused: bool = False
    last_sent_at: datetime | None = None
    created_at: datetime


class AlertRuleUpdate(BaseModel):
    """What a PATCH may change about an alert rule: whether it is held, and what it says.

    Every field is optional, and a field a caller leaves out is left as it was.
    """

    paused: bool | None = None
    template: str | None = Field(default=None, description=SUBJECT_HELP)
    body: str | None = Field(default=None, description=BODY_HELP)
    importance: Importance | None = Field(default=None, description=IMPORTANCE_HELP)
    connection: str | None = Field(default=None, description=CONNECTION_HELP)


class NotificationOut(WireModel):
    """One queued or delivered alert."""

    id: UUID
    event: AlertEvent
    rule: str | None = Field(default=None, description="The rule that raised it; null for a test.")
    notifier: str
    connection: str | None = None
    subject: str
    status: NotificationStatus
    attempt: int
    max_attempts: int
    run_id: UUID | None = None
    run_pipeline: str | None = None
    run_started_at: datetime | None = None
    available_at: datetime
    sent_at: datetime | None = None
    error: str | None = None
    created_at: datetime


class TestRequest(BaseModel):
    """Which channel to send a test message through, and what to say."""

    notifier: str
    connection: str | None = None
    subject: str = "dirigent test alert"
    body: str = "This is a test message sent through the notifier surface."


class TestQueued(WireModel):
    """What a test message queued."""

    notification_id: UUID
    notifier: str
    detail: str = "queued; a worker delivers it on its next pass"
