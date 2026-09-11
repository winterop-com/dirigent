"""Pipelines: what a listing shows, what an apply sends, and what an apply reports back."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from dirigent_client.enums import DocumentKind, LogLevel, ProvenanceSource, RunPriority, RunStatus
from dirigent_client.schemas.common import WireModel
from dirigent_common import EntityName, JsonMap


class Requirements(WireModel):
    """What a shared document needs from the instance before it can be applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    blocks: list[str] = Field(default_factory=list[str])
    connections: list[EntityName] = Field(default_factory=list[str])
    pipelines: list[EntityName] = Field(default_factory=list[str])
    """Pipelines this one starts with ``pipeline.run``, and therefore cannot run without."""

    storage: list[str] = Field(default_factory=list[str])
    """Storage this document writes through, named by scheme, such as ``s3``; some backend
    on the instance must claim each one."""

    schemas: list[EntityName] = Field(default_factory=list[str])
    """Named JSON Schemas this document references, by code; the instance must hold each one."""

    workers: list[EntityName] = Field(default_factory=list[str])
    """Capability tags a worker must carry to claim this pipeline's work, such as ``docker``.
    A run pins the list at creation, and only a worker carrying every tag claims it."""

    @property
    def empty(self) -> bool:
        """Report whether this document requires nothing in particular."""
        return not (self.blocks or self.connections or self.pipelines or self.storage or self.schemas or self.workers)


class LastRun(WireModel):
    """The most recent run of a pipeline, as a listing shows it."""

    id: UUID
    status: RunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failed_step: str | None = None
    """The step whose first failed attempt this run holds, when it did not end well."""


class PipelineOut(WireModel):
    """A pipeline as a listing shows it."""

    id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    """What the current document says this pipeline is for."""

    active: bool
    current_version: int | None = None
    active_runs: int = 0
    schedules: int = 0
    """How many clocks fire this pipeline."""

    webhooks: int = 0
    """How many inbound endpoints fire this pipeline."""

    last_run: LastRun | None = None
    """How the newest run of this pipeline went, or nothing when it has never run."""

    created_at: datetime
    updated_at: datetime


class PipelineVersionOut(WireModel):
    """One immutable version, its digest, and where it came from."""

    id: UUID
    version: int
    digest: str
    provenance_source: ProvenanceSource
    provenance_ref: str | None = None
    applied_by: str | None = None
    created_at: datetime


class PipelineDetail(PipelineOut):
    """A pipeline plus the document its current version holds."""

    document: JsonMap | None = None


class ApplyRequest(BaseModel):
    """A whole ``dirigent/v1`` document, optionally registered under a different code."""

    document: JsonMap
    code: str | None = Field(default=None, description="Register under this code instead of the document's own.")
    source: ProvenanceSource = ProvenanceSource.API
    source_ref: str | None = Field(default=None, description="The file path or URL the document came from.")
    pause_schedules: bool = Field(
        default=False,
        description="Create the schedules this apply brings into being already paused.",
    )


class PruneRequest(BaseModel):
    """The codes a reconcile keeps: everything else it once applied is deactivated."""

    keep: list[str]
    """Every code the reconciled directory holds. A directory-provenance pipeline absent
    from this list is deactivated; a pipeline applied any other way is never touched."""


class PruneResult(BaseModel):
    """What a prune deactivated and deleted, or would have."""

    pruned: list[str]
    trigger_documents_removed: list[str] = Field(default_factory=list[str])
    """The triggers documents a directory no longer holds, deleted with the rows they owned."""

    dry_run: bool = False


class RunRequest(BaseModel):
    """Ad hoc run parameters, validated against the pipeline's own schema."""

    params: JsonMap = Field(default_factory=dict)
    priority: RunPriority | None = Field(
        default=None,
        description=(
            "How far ahead of other runs this run's attempts are claimed. Omitted takes the pipeline's own priority."
        ),
    )
    window_start: datetime | None = Field(
        default=None,
        description="Start of the logical data interval this run covers, inclusive.",
    )
    window_end: datetime | None = Field(
        default=None,
        description="End of that interval, exclusive. Both are given or neither is.",
    )
    log_levels: dict[str, LogLevel] | None = Field(
        default=None,
        description=(
            "Which log levels this run keeps, as a map of block-id pattern to level; the most "
            "specific pattern wins. Omitted keeps info and up."
        ),
    )

    @field_validator("log_levels")
    @classmethod
    def _a_pattern_names_something(cls, value: dict[str, LogLevel] | None) -> dict[str, LogLevel] | None:
        """Refuse an empty pattern, which would match nothing and say nothing."""
        if value is not None and any(not pattern for pattern in value):
            raise ValueError("log_levels: a pattern may not be empty")
        return value

    @model_validator(mode="after")
    def _a_window_has_two_ends(self) -> "RunRequest":
        """Refuse a half-declared window, which no step could read as an interval."""
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("a window has two ends: give both window_start and window_end, or neither")
        if self.window_start is not None and self.window_end is not None and self.window_start >= self.window_end:
            raise ValueError(
                f"a window runs forwards and covers something: {self.window_start.isoformat()} "
                f"is not before {self.window_end.isoformat()}"
            )
        return self


class RunAccepted(WireModel):
    """What starting a run returns: the run id, or why nothing started."""

    run_id: UUID | None = None
    status: str
    detail: str | None = None


class BackfillRequest(BaseModel):
    """One backfill: whose cadence defines the windows, what interval to fill, and with what.

    ``from_`` and ``to`` bound the firings enumerated, half-open, and each enumerated firing
    becomes one run carrying the window that firing would have covered.
    """

    schedule: str = Field(description="The schedule on this pipeline whose cadence defines the windows.")
    #: ``from`` is a Python keyword, so the field is ``from_`` here and ``from`` on the wire.
    from_: datetime = Field(
        serialization_alias="from",
        validation_alias=AliasChoices("from", "from_"),
        description="First instant of the interval to enumerate, inclusive.",
    )
    to: datetime = Field(description="Last instant of the interval to enumerate, exclusive.")
    params: JsonMap | None = Field(
        default=None,
        description="Parameters every run created here is given; the schedule's own pins when omitted.",
    )
    dry_run: bool = Field(default=False, description="Answer with the plan and create nothing.")

    @model_validator(mode="after")
    def _runs_forwards(self) -> "BackfillRequest":
        """Refuse an empty or backwards interval, which encloses no firing at all."""
        if self.from_ >= self.to:
            raise ValueError(
                f"a backfill runs forwards and covers something: {self.from_.isoformat()} "
                f"is not before {self.to.isoformat()}"
            )
        return self


class BackfilledRun(WireModel):
    """One window a backfill enumerated, and the run it created for it."""

    window_start: datetime
    window_end: datetime
    run_id: UUID | None = None
    """The run created for this window, or None on a dry run and where the policy refused one."""

    detail: str | None = None
    """Why no run was created, when none was."""


class BackfillAccepted(WireModel):
    """What a backfill amounted to: the windows it enumerated, in chronological order."""

    pipeline: str
    schedule: str
    dry_run: bool = False
    windows: list[BackfilledRun] = Field(default_factory=list[BackfilledRun])

    @property
    def created(self) -> int:
        """How many runs this backfill actually created."""
        return sum(1 for window in self.windows if window.run_id is not None)


class ValidationIssue(WireModel):
    """One problem with a document, addressed at the place in it that is wrong."""

    location: str
    """Where the problem is, as a dotted document path such as ``steps.push.config.method``."""

    message: str
    """What is wrong, in the terms the person editing the document is thinking in."""

    def __str__(self) -> str:
        """Render the issue as one line."""
        return f"{self.location}: {self.message}"


class PlanAction(StrEnum):
    """What applying a document would do to the instance."""

    CREATE = "create"
    """No pipeline holds this code; applying mints one with version 1."""

    UPDATE = "update"
    """The code exists and the document differs; applying writes the next version."""

    UNCHANGED = "unchanged"
    """The digest matches the current version; applying writes nothing."""

    INVALID = "invalid"
    """The document did not validate against this instance; applying is refused."""


class DiffSummary(WireModel):
    """What changed between the current version and the document being applied."""

    steps_added: list[str] = Field(default_factory=list[str])
    steps_removed: list[str] = Field(default_factory=list[str])
    steps_changed: list[str] = Field(default_factory=list[str])
    params_changed: bool = False
    triggers_changed: bool = False
    settings_changed: bool = False
    """Name, description, or concurrency policy differs."""

    @property
    def empty(self) -> bool:
        """Report whether the two definitions are the same in every respect summarised here."""
        return not (
            self.steps_added
            or self.steps_removed
            or self.steps_changed
            or self.params_changed
            or self.triggers_changed
            or self.settings_changed
        )


class Materialized(WireModel):
    """What applying a document did to its triggers."""

    schedules_created: list[str] = Field(default_factory=list[str])
    schedules_updated: list[str] = Field(default_factory=list[str])
    schedules_removed: list[str] = Field(default_factory=list[str])
    webhooks_created: list[str] = Field(default_factory=list[str])
    webhooks_updated: list[str] = Field(default_factory=list[str])
    webhooks_removed: list[str] = Field(default_factory=list[str])

    @property
    def empty(self) -> bool:
        """Report whether the apply left every trigger exactly as it was."""
        return not (
            self.schedules_created
            or self.schedules_updated
            or self.schedules_removed
            or self.webhooks_created
            or self.webhooks_updated
            or self.webhooks_removed
        )


class PipelinePlan(WireModel):
    """What applying a document would do, before anything is written."""

    code: str
    action: PlanAction
    digest: str
    pipeline: str | None = None
    """The pipeline a triggers document declares clocks for; a pipeline document names none."""

    current_version: int | None = None
    next_version: int | None = None
    issues: list[ValidationIssue] = Field(default_factory=list[ValidationIssue])
    warnings: list[ValidationIssue] = Field(default_factory=list[ValidationIssue])
    """What is worth saying but does not refuse the apply, such as a worker tag nobody carries."""

    diff: DiffSummary | None = None

    @property
    def ok(self) -> bool:
        """Report whether this document could be applied as it stands."""
        return self.action is not PlanAction.INVALID


class ApplyResult(WireModel):
    """The outcome of an apply."""

    kind: DocumentKind = DocumentKind.PIPELINE
    """Which kind of document was applied; a triggers document writes no version."""

    plan: PipelinePlan
    pipeline_id: UUID | None = None
    """The pipeline this apply wrote, or the one a triggers document declares clocks for."""

    version: int | None = None
    dry_run: bool = False
    triggers: Materialized = Field(default_factory=Materialized)
    """Which schedules and webhooks the document's ``triggers:`` section created, changed, or retired."""
