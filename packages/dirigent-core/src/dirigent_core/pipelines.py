"""Applying, exporting, and retiring pipelines: the definition lifecycle in one place.

A document is matched to a pipeline by code, and an unchanged one reports ``unchanged`` and
writes no new version.
"""

from collections.abc import Sequence
from typing import Final, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_client.schemas import (
    ApplyResult,
    DiffSummary,
    LastRun,
    Materialized,
    PipelinePlan,
    PlanAction,
    ValidationIssue,
)
from dirigent_core.documents import (
    digest_of,
    to_yaml,
    validate_against_catalog,
    worker_routing_issues,
)
from dirigent_core.engine.definition import Document, PipelineDefinition, TriggersDefinition, load_definition
from dirigent_core.engine.runs import Provenance, save_pipeline
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.logging import get_logger
from dirigent_core.models import (
    ArtifactRef,
    Connection,
    LogEntry,
    Notification,
    Pipeline,
    PipelineVersion,
    Run,
    RunItem,
    Schedule,
    StepAttempt,
    WebhookTrigger,
)
from dirigent_core.registry import live_worker_tags
from dirigent_core.schemas import schema_codes
from dirigent_core.triggers.materialize import materialize_triggers, owner_issues

_logger = get_logger("pipelines")


class PipelineError(Exception):
    """A pipeline could not be found, applied, or retired."""


class UnknownPipeline(PipelineError):
    """No live pipeline holds the given code."""

    def __init__(self, code: str) -> None:
        """Name what was asked for."""
        super().__init__(f"no pipeline coded {code!r}")
        self.code = code


class PipelineInUse(PipelineError):
    """A pipeline was asked to be deleted while runs of it are still in flight."""

    def __init__(self, code: str, runs: int) -> None:
        """Say how much work is still in flight, and what to do about it."""
        super().__init__(
            f"pipeline {code!r} has {runs} run(s) still in flight and cannot be deleted; finish or cancel them first"
        )
        self.code = code
        self.runs = runs


async def connection_codes(session: AsyncSession) -> list[str]:
    """List the connections this instance holds."""
    rows = await session.execute(sa.select(Connection.code).order_by(Connection.code))
    return list(rows.scalars())


async def pipeline_codes(session: AsyncSession) -> list[str]:
    """List the pipelines this instance holds."""
    rows = await session.execute(sa.select(Pipeline.code).order_by(Pipeline.code))
    return list(rows.scalars())


async def find_pipeline(session: AsyncSession, code: str) -> Pipeline | None:
    """Find the pipeline holding a code."""
    found = await session.execute(sa.select(Pipeline).where(Pipeline.code == code))
    return found.scalar_one_or_none()


async def require_pipeline(session: AsyncSession, code: str) -> Pipeline:
    """Find a pipeline by code, or raise :class:`UnknownPipeline`."""
    pipeline = await find_pipeline(session, code)
    if pipeline is None:
        raise UnknownPipeline(code)
    return pipeline


async def list_pipelines(
    session: AsyncSession,
    *,
    after: str | None = None,
    limit: int | None = None,
    tags: Sequence[str] = (),
) -> list[Pipeline]:
    """List pipelines in code order, narrowed to the ones wearing every named tag."""
    statement = sa.select(Pipeline).order_by(Pipeline.code)
    if after is not None:
        statement = statement.where(Pipeline.code > after)
    for tag in tags:
        statement = statement.where(carries_tag(session, tag))
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


def carries_tag(session: AsyncSession, tag: str) -> sa.ColumnElement[bool]:
    """Say "this pipeline wears that tag" in the spelling the session's dialect can answer.

    The fork is here because SQLite's json1 has no containment operator: PostgreSQL asks the
    JSONB itself with ``@>``, and SQLite has to walk the array with ``json_each`` and ask
    whether any element is the tag. Repeating the predicate is what makes two tags an AND.
    """
    if session.get_bind().dialect.name == "postgresql":
        return sa.type_coerce(Pipeline.tags, postgresql.JSONB).contains([tag])
    element = sa.func.json_each(Pipeline.tags).table_valued("value")
    return sa.select(1).select_from(element).where(element.c.value == tag).exists()


async def list_versions(
    session: AsyncSession,
    pipeline_id: UUID,
    *,
    after: int | None = None,
    limit: int | None = None,
) -> list[PipelineVersion]:
    """List a pipeline's versions, newest first."""
    statement = (
        sa.select(PipelineVersion)
        .where(PipelineVersion.pipeline_id == pipeline_id)
        .order_by(PipelineVersion.version.desc())
    )
    if after is not None:
        statement = statement.where(PipelineVersion.version < after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def get_version(session: AsyncSession, pipeline: Pipeline, version: int | None = None) -> PipelineVersion:
    """Read one version of a pipeline, defaulting to the current one."""
    wanted = version if version is not None else pipeline.current_version
    if wanted is None:
        raise PipelineError(f"pipeline {pipeline.code!r} has no versions yet")
    found = await session.execute(
        sa.select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == wanted)
    )
    row = found.scalar_one_or_none()
    if row is None:
        raise PipelineError(f"pipeline {pipeline.code!r} has no version {wanted}")
    return row


def diff_definitions(current: PipelineDefinition, incoming: PipelineDefinition) -> DiffSummary:
    """Summarise what changed between two definitions, at the granularity a plan shows."""
    before, after = set(current.steps), set(incoming.steps)
    return DiffSummary(
        steps_added=sorted(after - before),
        steps_removed=sorted(before - after),
        steps_changed=sorted(name for name in before & after if current.steps[name] != incoming.steps[name]),
        params_changed=current.params != incoming.params,
        triggers_changed=current.triggers != incoming.triggers,
        settings_changed=(
            current.name != incoming.name
            or current.description != incoming.description
            or current.tags != incoming.tags
            or current.concurrency != incoming.concurrency
        ),
    )


async def plan_apply(
    session: AsyncSession,
    services: EngineServices,
    definition: PipelineDefinition,
) -> PipelinePlan:
    """Work out what applying a document would do, without writing anything."""
    digest = digest_of(definition)
    issues = validate_against_catalog(
        definition,
        services.host.catalog(),
        connections=await connection_codes(session),
        pipelines=await pipeline_codes(session),
        unsafe_allowed=services.settings.enabled_unsafe_blocks,
        storage_schemes=services.storage.schemes,
        schemas=await schema_codes(session),
        blocks=services.host.blocks,
        format_checker=services.format_checker,
    )
    pipeline = await find_pipeline(session, definition.code)
    if not issues and pipeline is not None:
        issues = await owner_issues(session, pipeline, definition.triggers, owner=None)
    if issues:
        return PipelinePlan(
            code=definition.code,
            action=PlanAction.INVALID,
            digest=digest,
            current_version=pipeline.current_version if pipeline else None,
            issues=issues,
        )
    warnings = worker_routing_issues(definition, await live_worker_tags(session))
    if pipeline is None or pipeline.current_version is None:
        return PipelinePlan(
            code=definition.code, action=PlanAction.CREATE, digest=digest, next_version=1, warnings=warnings
        )
    current = await get_version(session, pipeline)
    if current.digest == digest:
        return PipelinePlan(
            code=definition.code,
            action=PlanAction.UNCHANGED,
            digest=digest,
            current_version=current.version,
            next_version=current.version,
            diff=DiffSummary(),
            warnings=warnings,
        )
    return PipelinePlan(
        code=definition.code,
        action=PlanAction.UPDATE,
        digest=digest,
        current_version=current.version,
        next_version=current.version + 1,
        diff=diff_definitions(load_definition(current.document), definition),
        warnings=warnings,
    )


async def apply_document(
    session: AsyncSession,
    services: EngineServices,
    definition: Document,
    *,
    provenance: Provenance | None = None,
    dry_run: bool = False,
    pause_schedules: bool = False,
) -> ApplyResult:
    """Validate, plan, and -- unless this is a dry run -- commit what a document declares.

    A pipeline document commits a new version; a triggers document writes itself and its rows.
    ``pause_schedules`` governs the schedules this apply creates, and only those: a schedule
    the instance already holds keeps whatever paused state an operator gave it, because that
    is state about this instance rather than something the document declares.
    """
    if isinstance(definition, TriggersDefinition):
        # Imported here because applying a triggers document reads the pipeline this module
        # owns, and importing it at module scope would close the loop.
        from dirigent_core.trigger_documents import apply_triggers_document

        return await apply_triggers_document(
            session,
            services,
            definition,
            provenance=provenance,
            dry_run=dry_run,
            pause_schedules=pause_schedules,
        )
    pipeline = await find_pipeline(session, definition.code)
    if pipeline is not None:
        # The plan reads the current version and everything after it writes against that
        # read, so the two are one decision: without the lock an apply that commits a new
        # version in between has its triggers reconciled away by a plan made before it. A
        # pipeline that does not exist yet has no row to lock, and the unique code refuses
        # the second of two creations.
        await lock_pipeline(session, pipeline.id)
    plan = await plan_apply(session, services, definition)
    if dry_run or plan.action in (PlanAction.INVALID, PlanAction.UNCHANGED):
        # An unchanged document still reconciles its triggers: the digest covers the
        # definition, not the instance, so a schedule deleted by hand is restored.
        triggers = Materialized()
        if pipeline is not None and plan.action is PlanAction.UNCHANGED and not dry_run:
            triggers = await materialize_triggers(session, pipeline, definition, pause_created=pause_schedules)
        return ApplyResult(
            plan=plan,
            pipeline_id=pipeline.id if pipeline else None,
            version=plan.current_version if plan.action is PlanAction.UNCHANGED else None,
            dry_run=dry_run,
            triggers=triggers,
        )
    version = await save_pipeline(session, definition, provenance=provenance)
    pipeline = await require_pipeline(session, definition.code)
    triggers = await materialize_triggers(session, pipeline, definition, pause_created=pause_schedules)
    _logger.info(
        "pipeline applied",
        pipeline=definition.code,
        version=version.version,
        action=plan.action.value,
        digest=plan.digest,
    )
    return ApplyResult(plan=plan, pipeline_id=version.pipeline_id, version=version.version, triggers=triggers)


async def export_pipeline(session: AsyncSession, code: str, *, version: int | None = None) -> str:
    """Render a stored pipeline as the canonical YAML a git repository holds."""
    pipeline = await require_pipeline(session, code)
    stored = await get_version(session, pipeline, version)
    return to_yaml(load_definition(stored.document))


async def revalidate(
    session: AsyncSession,
    services: EngineServices,
    code: str,
    *,
    version: int | None = None,
) -> list[ValidationIssue]:
    """Check a stored version against what the instance has **now**.

    An instance drifts: a plugin package is uninstalled, a connection deleted, the allowlist
    tightened. A pipeline that applied cleanly then fails when it next runs, which is the
    worst moment to find out. This is the same check apply makes, run against a version the
    instance already holds.
    """
    pipeline = await require_pipeline(session, code)
    stored = await get_version(session, pipeline, version)
    return validate_against_catalog(
        load_definition(stored.document),
        services.host.catalog(),
        connections=await connection_codes(session),
        pipelines=await pipeline_codes(session),
        unsafe_allowed=services.settings.enabled_unsafe_blocks,
        storage_schemes=services.storage.schemes,
        schemas=await schema_codes(session),
        blocks=services.host.blocks,
        format_checker=services.format_checker,
    )


async def set_active(session: AsyncSession, code: str, *, active: bool) -> Pipeline:
    """Activate or deactivate a pipeline, keeping its code and its history."""
    pipeline = await require_pipeline(session, code)
    pipeline.active = active
    await session.flush()
    _logger.info("pipeline activation changed", pipeline=code, active=active)
    return pipeline


async def count_runs(session: AsyncSession, pipeline_id: UUID, *narrow: sa.ColumnElement[bool]) -> int:
    """Count a pipeline's runs, or the ones a narrowing matches."""
    found = await session.execute(
        sa.select(sa.func.count()).select_from(Run).where(Run.pipeline_id == pipeline_id, *narrow)
    )
    return int(found.scalar_one())


#: The run statuses that mean work is still in flight for a pipeline.
IN_FLIGHT = (RunStatus.QUEUED, RunStatus.RUNNING)

#: The tables a run's history lives in, deepest first: the order a delete has to walk them in.
RUN_FAMILY: Final[tuple[type[ArtifactRef | LogEntry | Notification | RunItem | StepAttempt], ...]] = (
    LogEntry,
    ArtifactRef,
    Notification,
    StepAttempt,
    RunItem,
)


async def delete_pipeline(session: AsyncSession, code: str) -> None:
    """Delete a pipeline and every run ever attributed to it, in one transaction.

    Refuses while runs are in flight, because deleting those would strand work a worker still
    holds a lease on: finish or cancel them first. Settled history goes with the pipeline --
    its runs, their items, attempts, logs and artifact references -- and the row itself takes
    its versions, schedules, webhooks and alert rules through their cascades.
    """
    pipeline = await require_pipeline(session, code)
    # Run creation takes the same lock, so a run that commits between the count and the
    # delete is either seen here or created against a pipeline this delete already removed.
    await lock_pipeline(session, pipeline.id)
    live = await count_runs(session, pipeline.id, Run.status.in_(IN_FLIGHT))
    if live:
        raise PipelineInUse(code, live)
    history = await count_runs(session, pipeline.id)
    runs = sa.select(Run.id).where(Run.pipeline_id == pipeline.id).scalar_subquery()
    for table in RUN_FAMILY:
        await session.execute(sa.delete(table).where(table.run_id.in_(runs)))
    await session.execute(sa.delete(Run).where(Run.pipeline_id == pipeline.id))
    await session.delete(pipeline)
    await session.flush()
    _logger.info("pipeline deleted", pipeline=code, runs=history)


#: The run statuses a step failure is worth naming under.
UNWELL = (RunStatus.FAILED, RunStatus.COMPLETED_WITH_ERRORS)


class PipelineCounts(NamedTuple):
    """What a pipeline row is worth counting: its runs in flight, and what fires it."""

    active_runs: int = 0
    schedules: int = 0
    webhooks: int = 0


NO_COUNTS = PipelineCounts()


async def listing_counts(session: AsyncSession, pipeline_ids: Sequence[UUID]) -> dict[UUID, PipelineCounts]:
    """Count the runs in flight, the schedules and the webhooks of a page of pipelines.

    One statement for the whole page: three correlated counts per row, each of them a lookup
    on the ``pipeline_id`` index the table already carries.
    """
    if not pipeline_ids:
        return {}
    counted = sa.select(
        Pipeline.id,
        _count_of(Run, Run.pipeline_id, Run.status.in_(IN_FLIGHT)).label("active_runs"),
        _count_of(Schedule, Schedule.pipeline_id).label("schedules"),
        _count_of(WebhookTrigger, WebhookTrigger.pipeline_id).label("webhooks"),
    ).where(Pipeline.id.in_(pipeline_ids))
    rows = await session.execute(counted)
    return {row.id: PipelineCounts(row.active_runs, row.schedules, row.webhooks) for row in rows.all()}


def _count_of(
    entity: type[Run | Schedule | WebhookTrigger],
    owner: InstrumentedAttribute[UUID],
    *narrow: sa.ColumnElement[bool],
) -> sa.ScalarSelect[int]:
    """Count one pipeline's rows in another table, as a subquery correlated to the row being read."""
    return sa.select(sa.func.count()).select_from(entity).where(owner == Pipeline.id, *narrow).scalar_subquery()


async def last_runs(session: AsyncSession, pipeline_ids: Sequence[UUID]) -> dict[UUID, LastRun]:
    """Read the newest run of each of a page of pipelines, and the step a bad one ended on.

    A run id is a uuid7, so the greatest id a pipeline holds is its newest run -- the same
    order the runs listing itself walks in.
    """
    if not pipeline_ids:
        return {}
    ranked = (
        sa.select(
            Run.pipeline_id,
            Run.id,
            Run.status,
            Run.started_at,
            Run.finished_at,
            sa.func.row_number().over(partition_by=Run.pipeline_id, order_by=Run.id.desc()).label("rank"),
        )
        .where(Run.pipeline_id.in_(pipeline_ids))
        .subquery()
    )
    rows = (await session.execute(sa.select(ranked).where(ranked.c.rank == 1))).all()
    failing = await failing_steps(session, [row.id for row in rows if row.status in UNWELL])
    return {
        row.pipeline_id: LastRun(
            id=row.id,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            failed_step=failing.get(row.id),
        )
        for row in rows
    }


async def failing_steps(session: AsyncSession, run_ids: Sequence[UUID]) -> dict[UUID, str]:
    """Name the step each run's first failed attempt was of."""
    if not run_ids:
        return {}
    ranked = (
        sa.select(
            StepAttempt.run_id,
            StepAttempt.step_name,
            sa.func.row_number().over(partition_by=StepAttempt.run_id, order_by=StepAttempt.id).label("rank"),
        )
        .where(StepAttempt.run_id.in_(run_ids), StepAttempt.status == AttemptStatus.FAILED)
        .subquery()
    )
    rows = await session.execute(sa.select(ranked.c.run_id, ranked.c.step_name).where(ranked.c.rank == 1))
    return {run_id: step for run_id, step in rows.all()}
