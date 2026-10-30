"""Runs: the listing row, the detail with its DAG view model, log pages, the report, and the stats."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dirigent_client.enums import (
    AttemptKind,
    AttemptStatus,
    LogLevel,
    RunItemStatus,
    RunPriority,
    RunStatus,
    StepKind,
    TriggerKind,
)
from dirigent_client.schemas.common import WireModel
from dirigent_common import JsonMap

TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.COMPLETED_WITH_ERRORS,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class RunOut(WireModel):
    """A run as a listing shows it."""

    id: UUID
    pipeline: str
    pipeline_version: int
    status: RunStatus
    priority: RunPriority = RunPriority.NORMAL
    """The priority the claim takes this run's attempts at, pinned when it was created."""
    params: JsonMap = Field(default_factory=dict)
    log_levels: dict[str, LogLevel] | None = None
    """Which log levels this run keeps, by block-id pattern; None keeps info and up."""
    triggered_by_kind: TriggerKind
    parent_run_id: UUID | None = None
    """The run whose step started this one, when a step of another run did."""
    triggered_by_id: UUID | None = None
    """What started the run: the source, schedule, token or user, as its id."""

    triggered_by_label: str | None = None
    source: str | None = None
    """The source node a run of a pipeline with sources entered at, by its step code."""

    trace_id: str | None = None
    error: str | None = None
    """What went wrong: the reason a cancel gave, else what the first failed attempt said."""
    error_code: str | None = None
    """The dotted code of the refusal the error was rendered from."""
    error_params: JsonMap | None = None
    """The specifics the refusal rendered, for a re-render in another language."""
    failed_step: str | None = None
    """The step whose first failed attempt this run holds, when it did not end well."""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    window_start: datetime | None = None
    """The start of the logical data interval this run covers, when it carries one."""

    window_end: datetime | None = None
    """The end of that interval, exclusive. Both are set or neither is."""

    created_at: datetime

    @property
    def terminal(self) -> bool:
        """Report whether this run has reached a status nothing will move it out of."""
        return self.status in TERMINAL_RUN_STATUSES


class AttemptOut(WireModel):
    """One try of one step, which is the unit a retry addresses."""

    id: UUID
    step_name: str
    block_id: str
    attempt: int
    kind: AttemptKind
    status: AttemptStatus
    run_item_id: UUID | None = None
    error: str | None = None
    error_code: str | None = None
    """The dotted code of the refusal this attempt failed with."""
    error_params: JsonMap | None = None
    """The specifics the refusal rendered, for a re-render in another language."""
    error_class: str | None = None
    output: JsonMap | None = None
    output_uri: str | None = None
    """Where the output was written, when it was too large to inline on the artifact."""

    output_bytes: int | None = None
    waiting_message: str | None = None
    waiting_progress: float | None = None
    poke_count: int = 0
    """How many times a probe answered that the work was not done yet."""

    next_poll_at: datetime | None = None
    available_at: datetime | None = None
    """When this attempt became claimable, which a retry's backoff pushes into the future."""

    deadline_at: datetime | None = None
    """When the engine gives up on this attempt, which is the budget its waiting is spent against."""

    heartbeat_at: datetime | None = None
    """When a worker last took this attempt up, which on a parked attempt is its last probe."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    """When the attempt was written down, which is where its queued time is measured from."""


class AttemptEvent(AttemptOut):
    """One attempt state on the run's event stream, with the label a person knows the item by."""

    item: str | None = None
    item_index: int | None = None
    """Where the element sits in the fan-out, which is the order a reader lists the elements in."""


class ItemOut(WireModel):
    """One element of a fan-out step."""

    id: UUID
    step_name: str
    item_index: int
    item_key: str
    status: RunItemStatus
    failing_step: str | None = None
    error: str | None = None
    error_code: str | None = None
    """The dotted code of the refusal the error was rendered from."""
    error_params: JsonMap | None = None
    """The specifics the refusal rendered, for a re-render in another language."""


class ArtifactOut(WireModel):
    """One artifact a run left behind: a step's output, or the run's own report document."""

    id: UUID
    step_name: str | None = None
    """The step whose output this is, or nothing when the artifact belongs to the run itself."""

    content_type: str | None = None
    size_bytes: int | None = None
    uri: str | None = None
    """Where the content was written, when it was too large to inline on the row."""

    created_at: datetime


class DagNode(WireModel):
    """One node of the run's graph."""

    code: str
    """The step's key in the document, which is what every edge and every attempt references."""

    name: str | None = None
    """The step's human title, when the document gave it one."""

    kind: StepKind = StepKind.BLOCK
    """Which form the step takes: a block, a source an input enters at, or a reply."""

    block: str
    """The block a block step runs, the kind of a source, or ``reply``."""

    outcome: str
    depends_on: list[str] = Field(default_factory=list[str])
    rule: str
    fan_out: bool = False
    grid_source: str | None = None
    """The step a late grid waits for before it expands, or null for a grid fixed at creation."""

    item_wise_parent: str | None = None
    """The fan-out whose matching item each of this step's items waits for, one by one, or null
    when the step waits for its prerequisites whole."""

    items_total: int = 0
    items_failed: int = 0
    attempts: int = 0


class DagView(WireModel):
    """The run's graph: its nodes and the edges between them."""

    nodes: list[DagNode] = Field(default_factory=list[DagNode])
    edges: list[tuple[str, str]] = Field(default_factory=list[tuple[str, str]])


class RunDetail(WireModel):
    """A run, the DAG view model, and how big the grids its sub-resources page are."""

    run: RunOut
    dag: DagView
    items_total: int = 0
    attempts_total: int = 0
    waiting_for_workers: list[str] | None = None
    """The tags this queued run needs that no live worker carries; null when nothing blocks it."""


class LogEntryOut(WireModel):
    """One product-telemetry entry."""

    id: int
    run_id: UUID
    step_name: str | None = None
    step_attempt_id: UUID | None = None
    level: LogLevel
    message: str
    fields: JsonMap | None = None
    error_code: str | None = None
    """The dotted code of the refusal this line reports, when it reports one.

    A log line is an event and carries no code of its own; a line the engine writes about a
    refusal repeats that refusal's code, so a reader can render the line rather than print it."""
    error_params: JsonMap | None = None
    """The specifics that refusal rendered, for a re-render in another language."""
    created_at: datetime


class StepReport(WireModel):
    """What one step amounted to, for the run report."""

    step: str
    block: str
    outcome: str
    attempts: int
    depends_on: list[str] = Field(default_factory=list[str])
    """The steps this one waited for, which is why it ran when it did."""

    warnings: int = 0
    """How many warnings or errors this step logged, whatever it settled as."""

    duration_ms: int | None = None
    error: str | None = None
    error_code: str | None = None
    """The dotted code of the refusal this step failed with."""
    error_params: JsonMap | None = None
    """The specifics that refusal rendered, for a re-render in another language."""


class RunReport(WireModel):
    """A plain summary of one run."""

    run_id: UUID
    pipeline: str
    pipeline_version: int
    status: RunStatus
    triggered_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    steps: list[StepReport] = Field(default_factory=list[StepReport])
    items_total: int = 0
    items_failed: int = 0
    error: str | None = None
    error_code: str | None = None
    """The dotted code of the refusal this run ended with."""
    error_params: JsonMap | None = None
    """The specifics that refusal rendered, for a re-render in another language."""


class RerunRequest(BaseModel):
    """How a settled run is run again: on the version it pinned, or on its pipeline's current one."""

    version: Literal["pinned", "current"] = Field(
        default="pinned",
        description=(
            "pinned runs the version the original ran; current runs the pipeline's current "
            "version, with the same parameters and input."
        ),
    )


class StatsWindow(WireModel):
    """The interval a stats read covers, half-open: the runs that settled in ``[start, end)``."""

    start: datetime
    end: datetime


class DayCounts(WireModel):
    """How many runs settled on one UTC day, by the status they settled in."""

    day: date
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    completed_with_errors: int = 0
    cancelled: int = 0


class PipelineDurations(WireModel):
    """How long one pipeline's settled runs took, from start to finish."""

    pipeline: str
    runs: int
    """How many runs the percentiles are measured over."""

    p50_ms: int
    p95_ms: int
    max_ms: int


class ErrorCount(WireModel):
    """One error the window's failed attempts said, and how often they said it."""

    code: str | None = None
    """The dotted code the attempts failed with; null when they carried none and the message groups them."""

    message: str | None = None
    """What one of those attempts said."""

    count: int
    last_at: datetime | None = None
    pipeline: str | None = None
    """The pipeline every one of those attempts was of; null when they span several."""


class StepFailures(WireModel):
    """One step whose attempts failed in the window, and how often."""

    pipeline: str
    step: str
    failures: int
    last_at: datetime | None = None


class RunStats(WireModel):
    """How the runs that settled in a window went: per day, per pipeline, and where they failed."""

    window: StatsWindow
    trend: list[DayCounts] = Field(default_factory=list[DayCounts])
    """One row per UTC day of the window, oldest first, a day with no runs included."""

    durations: list[PipelineDurations] = Field(default_factory=list[PipelineDurations])
    top_errors: list[ErrorCount] = Field(default_factory=list[ErrorCount])
    failing_steps: list[StepFailures] = Field(default_factory=list[StepFailures])
