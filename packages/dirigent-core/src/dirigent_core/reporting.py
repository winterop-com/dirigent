"""A run's facts, assembled once for the report, the templates and the CLI."""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, LogLevel, RunItemStatus
from dirigent_common import JsonMap, render
from dirigent_core import alerting, telemetry
from dirigent_core.artifacts import MARKDOWN_CONTENT_TYPE, canonical_json, persist_document
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import build_step_states, in_execution_order
from dirigent_core.logging import get_logger
from dirigent_core.models import ArtifactRef, LogEntry, Pipeline, PipelineVersion, Run, RunItem, StepAttempt

#: The document a run renders when it declares ``report:`` without a template of its own.
DEFAULT_TEMPLATE: Final = """\
# {{ pipeline.name or pipeline.code }} run {{ run.status }}

- run: {{ run.id }}
- pipeline: {{ pipeline.code }} (version {{ pipeline.version }})
- trigger: {{ run.trigger }}
- started: {{ run.started_at | iso }}
- finished: {{ run.finished_at | iso }}
- duration: {{ run.duration_ms | duration }}
- rendered: {{ rendered_at | iso }}
{% if run.window_start or run.window_end %}
- window: {{ run.window_start | iso }} to {{ run.window_end | iso }}
{% endif %}

| step | outcome | attempts | took | output | warnings |
| --- | --- | --- | --- | --- | --- |
{% for name, one in step.items() %}
| {{ name }} | {{ one.outcome }} | {{ one.attempts }} | {{ one.duration_ms | duration }} | \
{{ one.output_bytes | bytes }} | {{ one.warnings }} |
{% endfor %}
{% if items_failed > 0 %}

## Failed items

{% for item in items if item.status == 'failed' %}
- {{ item.index }} `{{ item.key }}` failed at {{ item.failing_step }}: {{ item.error }}
{% endfor %}
{% endif %}
{% if run.error %}

## Error

```
{{ run.error }}
```
{% endif %}
"""

#: What the document is stored as when it is too large to inline.
REPORT_NAME: Final = "report.md"

_logger = get_logger("reporting")


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
    output_bytes: int | None = None


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
    step: dict[str, StepFacts] = Field(default_factory=dict[str, StepFacts])
    """The same steps by name, so a template reads one step without filtering the list."""

    items: list[ItemFacts] = Field(default_factory=list[ItemFacts])
    items_total: int = 0
    items_failed: int = 0
    url: str | None = None
    rendered_at: datetime


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


async def _output_rows(session: AsyncSession, run_id: UUID) -> dict[UUID, tuple[str | None, int | None]]:
    """Map each attempt that stored an output to the URI it went as and how large it was.

    The URI is null for an attempt whose output inlined: its own row carries the value.
    """
    rows = await session.execute(
        sa.select(ArtifactRef.step_attempt_id, ArtifactRef.uri, ArtifactRef.size_bytes).where(
            ArtifactRef.run_id == run_id, ArtifactRef.step_attempt_id.is_not(None)
        )
    )
    return {found: (uri, size) for found, uri, size in rows.all() if found is not None}


async def run_facts(
    session: AsyncSession,
    run: Run,
    pipeline: Pipeline,
    version: PipelineVersion,
    definition: PipelineDefinition,
    *,
    base_url: str | None,
    rendered_at: datetime,
) -> RunFacts:
    """Assemble everything there is to say about one run, in one pass of queries."""
    attempts = await attempts_in_order(session, run.id, version.step_order)
    items = await items_in_order(session, run.id)
    warned = await warning_counts(session, run.id)
    stored = await _output_rows(session, run.id)
    states = build_step_states(definition, attempts)
    steps: list[StepFacts] = []
    for name in human_order(definition, [attempt.step_name for attempt in attempts]):
        of_step = [attempt for attempt in attempts if attempt.step_name == name]
        last = of_step[-1] if of_step else None
        output = dict(last.output) if last is not None and last.output is not None else None
        uri, size = stored.get(last.id, (None, None)) if last is not None else (None, None)
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
                output=output,
                output_uri=uri,
                output_bytes=size if size is not None else _json_bytes(output),
            )
        )
    return RunFacts(
        run=_run_namespace(run, pipeline, base_url=base_url),
        pipeline=PipelineFacts(code=pipeline.code, name=pipeline.name, version=version.version),
        steps=steps,
        step={step.step: step for step in steps},
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
        rendered_at=rendered_at,
    )


def _json_bytes(output: JsonMap | None) -> int | None:
    """Measure an output the way the engine stores it, for a step whose artifact row is gone."""
    return None if output is None else len(canonical_json(output))


def _run_namespace(run: Run, pipeline: Pipeline, *, base_url: str | None) -> JsonMap:
    """The ``run`` namespace an alert template already reads, plus the window and the trace."""
    context = alerting.build_context(run, pipeline, base_url=base_url)
    namespace: JsonMap = dict(context["run"])
    namespace["window_start"] = run.window_start.isoformat() if run.window_start else None
    namespace["window_end"] = run.window_end.isoformat() if run.window_end else None
    namespace["trace_id"] = telemetry.trace_id_of(run.traceparent)
    return namespace


async def facts_of_run(
    session: AsyncSession,
    run: Run,
    definition: PipelineDefinition,
    *,
    base_url: str | None,
    rendered_at: datetime,
) -> RunFacts:
    """Assemble one run's facts from the run alone, reading the pipeline and version it pins."""
    pipeline = await session.get(Pipeline, run.pipeline_id)
    version = await session.get(PipelineVersion, run.pipeline_version_id)
    if pipeline is None or version is None:  # pragma: no cover - the foreign keys make this unreachable
        raise RuntimeError(f"run {run.id} names a pipeline or a version that is gone")
    return await run_facts(session, run, pipeline, version, definition, base_url=base_url, rendered_at=rendered_at)


def as_context(facts: RunFacts) -> JsonMap:
    """Render the facts as the plain JSON a template and a stored notification read."""
    return facts.model_dump(mode="json")


class RenderedReport(BaseModel):
    """What a settling run's report amounted to: its facts, and the document when there is one.

    ``facts`` is null for a run whose document declared no ``report:`` section: nothing has
    asked for them yet, and an alert rule that wants them builds them itself.
    """

    model_config = ConfigDict(frozen=True)

    facts: RunFacts | None = None
    markdown: str | None = None
    artifact_id: UUID | None = None


async def render_run_report(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    *,
    now: datetime,
) -> RenderedReport:
    """Render and store the document a settling run owes, and never fail the run doing it.

    Called from the transaction that settles the run, so the facts are the ones the alerts it
    owes are raised over. A run whose document declares no ``report:`` section costs nothing
    here: the facts are a pass of queries, and nothing has asked for them. A template that
    loops, overflows or names nothing leaves a warning in the run's timeline and no document.
    """
    if definition.report is None:
        return RenderedReport()
    facts = await facts_of_run(session, run, definition, base_url=services.settings.alert_base_url, rendered_at=now)
    template = definition.report.template or DEFAULT_TEMPLATE
    try:
        markdown = await asyncio.wait_for(
            asyncio.to_thread(render, template, as_context(facts), max_bytes=int(services.settings.report_max_size)),
            timeout=services.settings.report_render_timeout.total_seconds(),
        )
        existing = await _report_row(session, run.id)
        async with session.begin_nested():
            reference = await persist_document(
                session,
                services.storage,
                run.id,
                name=REPORT_NAME,
                text=markdown,
                content_type=MARKDOWN_CONTENT_TYPE,
                inline_max_bytes=int(services.settings.inline_artifact_max),
                existing=existing,
            )
    except Exception as error:  # noqa: BLE001 - a report is never worth the run it describes
        session.add(
            LogEntry(
                run_id=run.id,
                level=LogLevel.WARNING,
                message="the run's report was not rendered",
                fields={"reason": str(error)},
                created_at=now,
            )
        )
        _logger.warning("the run's report was not rendered", run_id=str(run.id), error=str(error))
        return RenderedReport(facts=facts)
    return RenderedReport(facts=facts, markdown=markdown, artifact_id=reference.id)


async def _report_row(session: AsyncSession, run_id: UUID) -> ArtifactRef | None:
    """Find the one run-level document row a run has, which a resettlement writes over."""
    found = await session.execute(
        sa.select(ArtifactRef).where(
            ArtifactRef.run_id == run_id,
            ArtifactRef.step_attempt_id.is_(None),
            ArtifactRef.content_type == MARKDOWN_CONTENT_TYPE,
        )
    )
    return found.scalars().first()
