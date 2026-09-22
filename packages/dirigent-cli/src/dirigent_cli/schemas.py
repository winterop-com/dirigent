"""What the rows inside a record carry: a run's steps, a backfill's windows, a document's shape.

Records are written through :mod:`dirigent_core.protocol`; these are the shapes of the
collections one carries beneath its line. They are the contract a script filters on, and they
are also what the table under that line is rendered from, so a field the rendering needs
belongs here rather than in a second query.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dirigent_common import Duration, JsonMap


class StepSummary(BaseModel):
    """What one settled attempt amounted to, as the closing event carries it."""

    model_config = ConfigDict(frozen=True)

    step: str
    item: str | None = None
    block: str
    status: str
    depends_on: list[str] = Field(default_factory=list[str])
    """The steps this one waited for, which is why it ran when it did."""

    warnings: int = 0
    """How many warnings or errors this attempt logged, whatever it settled as."""

    attempts: int = 1
    """How many attempts this step took to settle."""

    duration_ms: int | None = None
    output: JsonMap | None = None
    error: str | None = None
    artifact_uri: str | None = None
    artifact_bytes: int | None = None


class FailureSummary(BaseModel):
    """One failed attempt, with the diagnosis a deleted local database cannot be asked for."""

    model_config = ConfigDict(frozen=True)

    step: str
    block: str
    attempt: int
    error_class: str | None = None
    error: str | None = None
    logs: list[str] = Field(default_factory=list[str])
    input: JsonMap | None = None
    """What the attempt was given, which is half of why it failed."""


class StepShape(BaseModel):
    """What one step of a checked document will become, before anything has run."""

    model_config = ConfigDict(frozen=True)

    name: str
    """The step's own map key, which is what every reference to it is written with."""

    block: str
    depends_on: list[str] = Field(default_factory=list[str])

    cardinality: int | str = 1
    """How many run items this step becomes: a count, ``adopts <step>``, or ``unknown``."""

    elements: int | None = 1
    """The count behind the cardinality, which an adoption takes from the grid it adopts."""

    reference: str | None = None
    """The ``for_each`` this step maps over, where it names one rather than listing it."""

    items: str = "fail_fast"
    max_attempts: int = 1

    retry_wait: Duration | None = None
    """The longest this step may spend in backoff, which is every delay its policy allows."""

    timeout: Duration | None = None
    poll: Duration | None = None
    deadline: Duration | None = None
    on_timeout: str = "fail"

    from_block: list[str] = Field(default_factory=list[str])
    """Which of this row's waits the block's own defaults filled, the document declaring none."""


class ShapeWarning(BaseModel):
    """One thing about a document's shape worth knowing before the run, said as a sentence."""

    model_config = ConfigDict(frozen=True)

    step: str
    cause: str
    message: str


class BackfillWindow(BaseModel):
    """One window a backfill enumerated, as the closing backfill record carries it."""

    model_config = ConfigDict(frozen=True)

    window_start: str
    window_end: str
    run_id: str | None = None
    detail: str | None = None


class RunFinished(BaseModel):
    """The run reached a terminal status; the last line of a run's stream."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID | None = None
    pipeline: str
    pipeline_version: int | None = None
    status: str
    triggered_by: str | None = None
    duration_ms: int | None = None
    items_total: int = 0
    items_failed: int = 0
    error: str | None = None
    exit_code: int = 0
    steps: list[StepSummary] = Field(default_factory=list[StepSummary])
    failures: list[FailureSummary] = Field(default_factory=list[FailureSummary])
    kept_at: str | None = None
    """Where a ``--keep`` local run left its throwaway instance."""
