"""A run's facts, assembled once for the report, the templates and the CLI."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, LogLevel, RunItemStatus
from dirigent_common import JsonMap, RenderTooLarge, render_off_loop
from dirigent_common.depth import shown
from dirigent_core import alerting, telemetry
from dirigent_core.artifacts import MARKDOWN_CONTENT_TYPE, canonical_json, persist_document
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import PipelineDefinition, load_definition
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import build_step_states, in_execution_order
from dirigent_core.logging import get_logger
from dirigent_core.messages import REPORT_STEP_LEFT_NO_TEXT
from dirigent_core.models import ArtifactRef, LogEntry, Pipeline, PipelineVersion, Run, RunItem, StepAttempt, utcnow

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

#: How long past its render budget a worker holds a run's report before another may take it over.
REPORT_HOLD_MARGIN: Final = timedelta(seconds=30)

#: The most owed reports one pass writes.
REPORT_BATCH: Final = 10

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
    error_code: str | None = None
    error_params: JsonMap | None = None
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
    error_code: str | None = None
    error_params: JsonMap | None = None


class RunFacts(BaseModel):
    """Everything a report, an alert or a template may read about one settled or running run."""

    model_config = ConfigDict(frozen=True)

    run: JsonMap
    pipeline: PipelineFacts
    params: JsonMap = Field(default_factory=dict)
    """The parameters the run resolved to, the same as ``run.params``."""

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
        sa.select(StepAttempt, sa.Nullable(RunItem.item_index))
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
        # The refusal the step ended on, taken whole: its sentence, its code and its params
        # come off one attempt, so a reader re-rendering it is not mixing two failures.
        failed = next((one for one in of_step if one.status is AttemptStatus.FAILED and one.error), None)
        output = shown(dict(last.output)) if last is not None and last.output is not None else None
        uri, size = stored.get(last.id, (None, None)) if last is not None else (None, None)
        steps.append(
            StepFacts(
                step=name,
                block=definition.steps[name].block_id,
                outcome=states[name].outcome.value,
                attempts=len(of_step),
                depends_on=list(definition.steps[name].depends_on),
                warnings=warned.get(name, 0),
                duration_ms=duration_ms(
                    min((one.started_at for one in of_step if one.started_at), default=None),
                    max((one.finished_at for one in of_step if one.finished_at), default=None),
                ),
                error=failed.error if failed else None,
                error_code=failed.error_code if failed else None,
                error_params=failed.error_params if failed else None,
                output=output,
                output_uri=uri,
                output_bytes=size if size is not None else _json_bytes(output),
            )
        )
    facts = RunFacts(
        run=_run_namespace(run, pipeline, base_url=base_url),
        pipeline=PipelineFacts(code=pipeline.code, name=pipeline.name, version=version.version),
        params=shown(dict(run.params)),
        steps=steps,
        step={step.step: step for step in steps},
        items=[
            ItemFacts(
                index=item.item_index,
                key=item.item_key,
                status=item.status,
                failing_step=item.failing_step,
                error=item.error,
                error_code=item.error_code,
                error_params=item.error_params,
            )
            for item in items
        ],
        items_total=len(items),
        items_failed=sum(1 for item in items if item.status is RunItemStatus.FAILED),
        url=f"{base_url.rstrip('/')}/runs/{run.id}" if base_url else None,
        rendered_at=rendered_at,
    )
    return _with_failure(run, facts)


def _with_failure(run: Run, facts: RunFacts) -> RunFacts:
    """Write where a failing run went wrong onto its ``run`` namespace, as the top-level names say it."""
    found = alerting.failure_reason(run, facts)
    if found is None:
        return facts
    namespace: JsonMap = {
        **facts.run,
        "error": found.error,
        "error_code": found.code,
        "error_params": dict(found.params or {}),
        "failed_step": found.step,
    }
    return facts.model_copy(update={"run": namespace})


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


def owe_report(run: Run, definition: PipelineDefinition, now: datetime) -> None:
    """Write down, in the transaction that settles the run, that it owes the document its ``report:`` declares.

    The document is rendered and stored once that transaction has committed, by
    ``write_owed_report`` or a worker's pass over every run owing one, so no template runs
    while the run's lock is held. A document that declares no ``report:`` owes nothing.
    """
    if definition.report is not None:
        run.report_due_at = now


async def write_owed_report(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, run_id: UUID, *, now: datetime
) -> bool:
    """Write the report one run owes, if it owes one, and say whether this call wrote it."""
    async with sessions() as session:
        seen = (await session.execute(sa.select(Run.report_due_at).where(Run.id == run_id))).scalar_one_or_none()
    if seen is None:
        return False
    return await _write_report(sessions, services, run_id, seen, now=now)


async def write_due_reports(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, *, now: datetime | None = None
) -> int:
    """Write the reports owed by runs whose turn has come, and say how many this pass wrote.

    A run is due from the moment it settles, and again once a worker that took it has held
    it past its render budget, which is how a document outlives a worker dying mid-render.
    """
    moment = now or utcnow()
    async with sessions() as session:
        found = await session.execute(
            sa.select(Run.id, Run.report_due_at)
            .where(Run.report_due_at.is_not(None), Run.report_due_at <= moment)
            .order_by(Run.report_due_at, Run.id)
            .limit(REPORT_BATCH)
        )
        due = [(run_id, seen) for run_id, seen in found.all() if seen is not None]
    written = 0
    for run_id, seen in due:
        written += await _write_report(sessions, services, run_id, seen, now=moment)
    return written


async def _write_report(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    run_id: UUID,
    seen: datetime,
    *,
    now: datetime,
) -> bool:
    """Take one owed report, render it with no transaction open, and store it with the alerts it releases.

    The take is a conditional write of the due time, so of two workers reaching one run only
    one renders it, and the store is fenced on the time this take wrote: a run that settled
    again, or a take that outlived its hold, leaves the document to the later one.
    """
    held = now + services.settings.report_render_timeout + REPORT_HOLD_MARGIN
    async with session_scope(sessions) as session:
        taken = await session.execute(
            sa.update(Run)
            .where(Run.id == run_id, Run.report_due_at == seen)
            .values(report_due_at=held)
            .returning(Run.id)
            .execution_options(synchronize_session=False)
        )
        if taken.scalar_one_or_none() is None:
            return False
    async with sessions() as session:
        run = await session.get(Run, run_id)
        version = await session.get(PipelineVersion, run.pipeline_version_id) if run is not None else None
        if run is None or version is None:  # pragma: no cover - the foreign keys make this unreachable
            return False
        definition = load_definition(version.document)
        facts = await facts_of_run(session, run, definition, base_url=services.settings.alert_base_url, rendered_at=now)
    markdown, failure = await _render(services, definition, facts)
    async with session_scope(sessions) as session:
        released = await session.execute(
            sa.update(Run)
            .where(Run.id == run_id, Run.report_due_at == held)
            .values(report_due_at=None)
            .returning(Run.id)
            .execution_options(synchronize_session=False)
        )
        if released.scalar_one_or_none() is None:
            return False
        reference: ArtifactRef | None = None
        if markdown is not None:
            try:
                async with session.begin_nested():
                    existing = await _report_row(session, run_id)
                    storage = await services.bound_storage(session)
                    reference = await persist_document(
                        session,
                        storage,
                        run_id,
                        name=REPORT_NAME,
                        text=markdown,
                        content_type=MARKDOWN_CONTENT_TYPE,
                        inline_max_bytes=int(services.settings.inline_artifact_max),
                        existing=existing,
                    )
            except Exception as error:  # noqa: BLE001 - a report is never worth the run it describes
                failure = str(error)
        if failure is not None:
            session.add(
                LogEntry(
                    run_id=run_id,
                    level=LogLevel.WARNING,
                    message="the run's report was not rendered",
                    fields={"reason": failure},
                    created_at=now,
                )
            )
            _logger.warning("the run's report was not rendered", run_id=str(run_id), error=failure)
        stored = reference is not None
        await alerting.attach_report(
            session,
            services,
            run_id,
            report=markdown if stored else None,
            artifact_id=reference.id if reference is not None else None,
        )
    return True


async def _render(
    services: EngineServices, definition: PipelineDefinition, facts: RunFacts
) -> tuple[str | None, str | None]:
    """Render a run's document off the loop, as the markdown or the reason there is none."""
    if definition.report is None:
        return None, None
    max_bytes = int(services.settings.report_max_size)
    try:
        if definition.report.step is not None:
            return step_text(facts, definition.report.step, max_bytes=max_bytes), None
        template = definition.report.template or DEFAULT_TEMPLATE
        within = services.settings.report_render_timeout
        return await render_off_loop(template, as_context(facts), max_bytes=max_bytes, within=within), None
    except Exception as error:  # noqa: BLE001 - a report is never worth the run it describes
        return None, str(error)


def step_text(facts: RunFacts, step: str, *, max_bytes: int) -> str:
    """The ``text`` a step handed on, which ``report: {from: <step>}`` makes the run's report."""
    found = facts.step.get(step)
    text = found.output.get("text") if found is not None and found.output is not None else None
    if not isinstance(text, str):
        raise ValueError(REPORT_STEP_LEFT_NO_TEXT.render(step=repr(step)))
    if len(text.encode()) > max_bytes:
        raise RenderTooLarge(max_bytes)
    return text


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
