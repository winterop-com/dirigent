"""The closed vocabularies the engine's state machines are built from."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Where a run is."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    """The step-attempt state machine."""

    PENDING = "pending"
    """Waiting on its depends_on edges; not yet claimable."""

    QUEUED = "queued"
    """Claimable once available_at has passed."""

    RUNNING = "running"
    """Claimed by a worker, holding a lease."""

    WAITING = "waiting"
    """Not on a worker: parked with a remote handle or a pending poke, re-examined when
    next_poll_at is due."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AttemptKind(StrEnum):
    """Whether the engine created an attempt or an operator asked for it."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class RunItemStatus(StrEnum):
    """Per-item status of a fan-out step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunPriority(StrEnum):
    """How far ahead of the other runs a run's attempts are claimed."""

    LOW = "low"
    """Claimed after everything else, which is where a bulk job belongs."""

    NORMAL = "normal"

    HIGH = "high"
    """Claimed before any other run's attempts, the moment a slot frees."""


#: What each priority is worth to the claim's sort, highest first.
PRIORITY_RANK: dict[RunPriority, int] = {RunPriority.LOW: 0, RunPriority.NORMAL: 1, RunPriority.HIGH: 2}


class TriggerKind(StrEnum):
    """What started a run."""

    ADHOC = "adhoc"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    API_TOKEN = "api_token"
    USER = "user"
    PIPELINE = "pipeline"
    """A step of another run started this one, and ``triggered_by_id`` names that run."""

    BACKFILL = "backfill"
    """A backfill over past windows created this one, and ``triggered_by_id`` names the schedule."""


class ScheduleKind(StrEnum):
    """How a schedule computes its next firing."""

    CRON = "cron"
    INTERVAL = "interval"
    ONE_TIME = "one_time"


class AlertEvent(StrEnum):
    """The run-level events an alert rule may bind to."""

    RUN_FAILED = "run_failed"
    RUN_COMPLETED_WITH_ERRORS = "run_completed_with_errors"
    RUN_SUCCEEDED = "run_succeeded"
    RUN_STUCK = "run_stuck"


class AlertScope(StrEnum):
    """Whether an alert rule watches everything or one pipeline."""

    GLOBAL = "global"
    PIPELINE = "pipeline"


class NotificationStatus(StrEnum):
    """Where one queued alert delivery is."""

    PENDING = "pending"
    """Queued and claimable once available_at has passed."""

    SENDING = "sending"
    """Claimed by a worker, holding a lease."""

    SENT = "sent"
    """The notifier accepted it."""

    FAILED = "failed"
    """Terminally undeliverable: the retry budget is gone, and the error is on the row."""


class FiringOutcome(StrEnum):
    """What one scheduler tick decided about one due schedule."""

    FIRED = "fired"
    """A run was created and is executing."""

    QUEUED = "queued"
    """A run was created but is held behind the one already in flight."""

    REPLACED = "replaced"
    """The run in flight was cancelled and a new one took its place."""

    SKIPPED = "skipped"
    """The concurrency policy dropped this firing; the run in flight is enough."""

    FAILED = "failed"
    """The run could not be created at all, and the reason is on the row."""


class WebhookOutcome(StrEnum):
    """What the intake endpoint did with one delivery."""

    ACCEPTED = "accepted"
    """The payload mapped, validated, and started a run."""

    SKIPPED = "skipped"
    """The payload was good, but the pipeline's concurrency policy dropped the run."""

    REJECTED = "rejected"
    """The delivery was refused, and the reason is on the row."""


class LogLevel(StrEnum):
    """Severity of a product log entry, which is separate from process logging."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DocumentKind(StrEnum):
    """Which kind of ``dirigent/v1`` document an apply carried."""

    PIPELINE = "pipeline"
    TRIGGERS = "triggers"
    """Clocks and webhooks for a pipeline defined somewhere else."""


class ProvenanceSource(StrEnum):
    """Where a pipeline version came from, recorded when it is applied."""

    UI = "ui"
    FILE = "file"
    URL = "url"
    API = "api"
    DIRECTORY = "directory"


class UserRole(StrEnum):
    """What an account may do."""

    ADMIN = "admin"
    """Full access: definitions, connections, runs, users, and tokens."""

    OPERATOR = "operator"
    """Define, apply, run, cancel and schedule, but not manage accounts, tokens or connections."""

    VIEWER = "viewer"
    """Read-only: every listing, run, log and report, and nothing that writes."""


class TokenKind(StrEnum):
    """Whether a stored credential is an automation token or a browser session."""

    API = "api"
    """A bearer token an operator created for a script or a CI job."""

    SESSION = "session"
    """A cookie-borne session minted by a login, expiring on its own."""


class WorkerStatus(StrEnum):
    """What the worker registry last heard from a node."""

    STARTING = "starting"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPED = "stopped"
