"""A run's facts, assembled once for the report, the templates and the CLI."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, LogLevel, RunItemStatus
from dirigent_common import JsonMap
from dirigent_core import alerting, telemetry
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.state import build_step_states, in_execution_order
from dirigent_core.models import ArtifactRef, LogEntry, Pipeline, PipelineVersion, Run, RunItem, StepAttempt


class PipelineFacts(BaseModel):
    """The pipeline a run was of, as a reader names it."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str | None = None
    version: int


class StepFacts(BaseModel):
    """What one step amounted to."""

    model_config = ConfigDict(frozen=True)

    step: str
    block: str
    outcome: str
    attempts: int
    depends_on: list[str] = Field(default_factory=list[str])
    warnings: int = 0
    duration_ms: int | None = None
    error: str | None = None
    output: JsonMap | None = None
    output_uri: str | None = None


class ItemFacts(BaseModel):
    """One element of a fan-out step's mapped input."""

    model_config = ConfigDict(frozen=True)

    index: int
    key: str
    status: RunItemStatus
    failing_step: str | None = None
    error: str | None = None


class RunFacts(BaseModel):
    """Everything a report, an alert or a template may read about one settled or running run."""

    model_config = ConfigDict(frozen=True)

    run: JsonMap
    pipeline: PipelineFacts
    steps: list[StepFacts] = Field(default_factory=list[StepFacts])
    items: list[ItemFacts] = Field(default_factory=list[ItemFacts])
    items_total: int = 0
    items_failed: int = 0
    url: str | None = None


async def attempts_in_order(session: AsyncSession, run_id: UUID, step_order: Sequence[str] = ()) -> list[StepAttempt]:
    """Read every attempt of a run, in the order they ran."""
    rows = await session.execute(
        sa.select(StepAttempt, RunItem.item_index)
        .outerjoin(RunItem, RunItem.id == StepAttempt.run_item_id)
        .where(StepAttempt.run_id == run_id)
    )
    found = rows.all()
    indexes = {attempt.id: index for attempt, index in found if index is not None}
    return in_execution_order([attempt for attempt, _ in found], indexes, step_order)


async def items_in_order(session: AsyncSession, run_id: UUID) -> list[RunItem]:
    """Read a run's fan-out items, in grid order."""
    rows = await session.execute(
        sa.select(RunItem).where(RunItem.run_id == run_id).order_by(RunItem.step_name, RunItem.item_index)
    )
    return list(rows.scalars())


async def warning_counts(session: AsyncSession, run_id: UUID) -> dict[str, int]:
    """Count the warnings and errors each step logged, which a succeeded step can still have."""
    rows = await session.execute(
        sa.select(LogEntry.step_name, sa.func.count())
        .where(LogEntry.run_id == run_id, LogEntry.level.in_((LogLevel.WARNING, LogLevel.ERROR)))
        .group_by(LogEntry.step_name)
    )
    return {name: count for name, count in rows.all() if name is not None}


def human_order(definition: PipelineDefinition, ran: Sequence[str]) -> list[str]:
    """Name a run's steps the way a person watched them: as they ran, then as they were written.

    The steps that ran arrive in execution order, which already carries the written order for
    the steps that have not, so following them says both things at once.
    """
    seen = list(dict.fromkeys(ran))
    return [name for name in seen if name in definition.steps] + [name for name in definition.steps if name not in seen]


def duration_ms(started: datetime | None, finished: datetime | None) -> int | None:
    """Report how long something took, or nothing when it has not finished."""
    if started is None or finished is None:
        return None
    return round((finished - started).total_seconds() * 1000)


async def _output_uris(session: AsyncSession, run_id: UUID) -> dict[UUID, str]:
    """Map each attempt whose output went to storage to the URI it went as.

    An attempt whose output inlined is not in here: its own row carries the value.
    """
    rows = await session.execute(
        sa.select(ArtifactRef.step_attempt_id, ArtifactRef.uri).where(
            ArtifactRef.run_id == run_id, ArtifactRef.uri.is_not(None)
        )
    )
    return {found: uri for found, uri in rows.all() if found is not None and uri is not None}


async def run_facts(
    session: AsyncSession,
    run: Run,
    pipeline: Pipeline,
    version: PipelineVersion,
    definition: PipelineDefinition,
    *,
    base_url: str | None,
) -> RunFacts:
    """Assemble everything there is to say about one run, in one pass of queries."""
    attempts = await attempts_in_order(session, run.id, version.step_order)
    items = await items_in_order(session, run.id)
    warned = await warning_counts(session, run.id)
    uris = await _output_uris(session, run.id)
    states = build_step_states(definition, attempts)
    steps: list[StepFacts] = []
    for name in human_order(definition, [attempt.step_name for attempt in attempts]):
        of_step = [attempt for attempt in attempts if attempt.step_name == name]
        last = of_step[-1] if of_step else None
        steps.append(
            StepFacts(
                step=name,
                block=definition.steps[name].block,
                outcome=states[name].outcome.value,
                attempts=len(of_step),
                depends_on=list(definition.steps[name].depends_on),
                warnings=warned.get(name, 0),
                duration_ms=duration_ms(
                    min((one.started_at for one in of_step if one.started_at), default=None),
                    max((one.finished_at for one in of_step if one.finished_at), default=None),
                ),
                error=next(
                    (one.error for one in of_step if one.status is AttemptStatus.FAILED and one.error),
                    None,
                ),
                output=dict(last.output) if last is not None and last.output is not None else None,
                output_uri=uris.get(last.id) if last is not None else None,
            )
        )
    return RunFacts(
        run=_run_namespace(run, pipeline, base_url=base_url),
        pipeline=PipelineFacts(code=pipeline.code, name=pipeline.name, version=version.version),
        steps=steps,
        items=[
            ItemFacts(
                index=item.item_index,
                key=item.item_key,
                status=item.status,
                failing_step=item.failing_step,
                error=item.error,
            )
            for item in items
        ],
        items_total=len(items),
        items_failed=sum(1 for item in items if item.status is RunItemStatus.FAILED),
        url=f"{base_url.rstrip('/')}/runs/{run.id}" if base_url else None,
    )


def _run_namespace(run: Run, pipeline: Pipeline, *, base_url: str | None) -> JsonMap:
    """The ``run`` namespace an alert template already reads, plus the window and the trace."""
    context = alerting.build_context(run, pipeline, base_url=base_url)
    namespace: JsonMap = dict(context["run"])
    namespace["window_start"] = run.window_start.isoformat() if run.window_start else None
    namespace["window_end"] = run.window_end.isoformat() if run.window_end else None
    namespace["trace_id"] = telemetry.trace_id_of(run.traceparent)
    return namespace


def as_context(facts: RunFacts) -> JsonMap:
    """Render the facts as the plain JSON a template and a stored notification read."""
    return facts.model_dump(mode="json")
