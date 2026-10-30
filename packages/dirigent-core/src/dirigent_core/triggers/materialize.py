"""Turning a document's ``triggers:`` section into rows, on every apply.

A declaration travels; operational state -- paused, last fired -- stays on the instance and is
never touched by an apply. Only a row marked
``managed`` may be created, redeclared, or removed here; a hand-created one is left alone.

A reconcile reaches only the rows of its own owner: ``trigger_document_id`` is null for the
rows a pipeline's own document declares, and the document's id for the rows a ``kind:
triggers`` document declares.
"""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import Materialized, ValidationIssue
from dirigent_core.engine.definition import Document, TriggerSpecs
from dirigent_core.logging import get_logger
from dirigent_core.messages import TRIGGER_OWNED_ELSEWHERE
from dirigent_core.models import Pipeline, Schedule, TriggerDocument
from dirigent_core.triggers.schedules import (
    ScheduleRequest,
    create_schedule,
    update_schedule,
)

_logger = get_logger("triggers")


async def materialize_triggers(
    session: AsyncSession,
    pipeline: Pipeline,
    definition: Document,
    *,
    now: datetime | None = None,
    pause_created: bool = False,
    owner: UUID | None = None,
) -> Materialized:
    """Reconcile the triggers one owner declares with what the instance holds for it.

    ``pause_created`` governs only the schedules this reconciliation creates. One
    the instance already holds keeps whatever it is: paused is operational state, so a
    redeclared trigger is neither re-paused nor resumed here. ``owner`` is the triggers
    document whose rows these are, or None for the ones the pipeline's own document declares.
    """
    specs = definition.triggers
    schedules = await _reconcile_schedules(session, pipeline, specs, now=now, pause_created=pause_created, owner=owner)
    result = Materialized(**schedules)
    if not result.empty:
        _logger.info(
            "triggers materialized",
            pipeline=pipeline.code,
            document=definition.code,
            schedules=len(specs.schedules),
        )
    return result


async def _reconcile_schedules(
    session: AsyncSession,
    pipeline: Pipeline,
    specs: TriggerSpecs,
    *,
    now: datetime | None,
    pause_created: bool,
    owner: UUID | None,
) -> dict[str, list[str]]:
    """Create, redeclare, and retire the schedules one owner declares, matching by code."""
    rows = await session.execute(sa.select(Schedule).where(Schedule.pipeline_id == pipeline.id))
    existing = {row.code: row for row in rows.scalars() if row.trigger_document_id == owner}
    declared = {spec.code: spec for spec in specs.schedules}
    created: list[str] = []
    updated: list[str] = []

    for code, spec in declared.items():
        request = ScheduleRequest.from_spec(spec)
        current = existing.get(code)
        if current is None:
            schedule = await create_schedule(session, pipeline, request, now=now, paused=pause_created)
            schedule.managed = True
            schedule.trigger_document_id = owner
            created.append(code)
            continue
        current.managed = True
        if _schedule_differs(current, request):
            await update_schedule(session, current, request, now=now)
            updated.append(code)

    removed = [code for code, row in existing.items() if row.managed and code not in declared]
    for code in removed:
        await session.delete(existing[code])
    await session.flush()
    return {"schedules_created": created, "schedules_updated": updated, "schedules_removed": sorted(removed)}


def _schedule_differs(schedule: Schedule, request: ScheduleRequest) -> bool:
    """Report whether a declaration says anything different from the row that holds it.

    Compared field by field rather than rewritten unconditionally, so re-applying an unchanged
    document does not reset ``next_fire_at``.
    """
    interval = int(request.interval.total_seconds()) if request.interval else None
    return (
        schedule.name != request.name
        or schedule.description != request.description
        or schedule.kind is not request.kind()
        or schedule.cron != request.cron
        or schedule.interval_seconds != interval
        or schedule.run_at != request.at
        or schedule.timezone != request.timezone
        or schedule.params != dict(request.params)
        or schedule.priority != request.priority
    )


async def owner_issues(
    session: AsyncSession,
    pipeline: Pipeline,
    specs: TriggerSpecs,
    *,
    owner: UUID | None,
) -> list[ValidationIssue]:
    """Refuse a declared code the pipeline already holds under a different owner, naming it.

    The unique constraint on ``(pipeline_id, code)`` would refuse it anyway, as an integrity
    error nobody can read; this says whose row it is instead.
    """
    documents = {row.id: row.code for row in (await session.execute(sa.select(TriggerDocument))).scalars()}
    schedules = await session.execute(sa.select(Schedule).where(Schedule.pipeline_id == pipeline.id))
    held = {row.code: row for row in schedules.scalars()}
    issues: list[ValidationIssue] = []
    for index, spec in enumerate(specs.schedules):
        row = held.get(spec.code)
        if row is None or row.trigger_document_id == owner:
            continue
        issues.append(
            ValidationIssue.of(
                TRIGGER_OWNED_ELSEWHERE,
                location=f"triggers.schedules[{index}].code",
                label="schedule",
                code=repr(spec.code),
                pipeline=repr(pipeline.code),
                owner=_owner_of(row, documents),
            )
        )
    return issues


def _owner_of(row: Schedule, documents: dict[UUID, str]) -> str:
    """Name whoever declared a row, in the words the refusal is read in."""
    if row.trigger_document_id is not None:
        return f"the triggers document {documents.get(row.trigger_document_id, '?')!r}"
    return "the pipeline's own document" if row.managed else "hand, through the API"
