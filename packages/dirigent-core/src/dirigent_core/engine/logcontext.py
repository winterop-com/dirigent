"""The fields every engine log line about a run or an attempt carries.

A line about an attempt names its run, its pipeline's code, its step and, for a fan-out
element, the item's key, so a reader goes from the line to the run without a query.
"""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_core.models import Pipeline, Run, RunItem, StepAttempt

type LogFields = dict[str, str]


def fields_of(
    *,
    run_id: UUID,
    pipeline: str | None,
    step: str | None = None,
    attempt_id: UUID | None = None,
    item: str | None = None,
) -> LogFields:
    """Name a run or an attempt the way every engine line does, leaving out what is unknown."""
    fields: LogFields = {"run_id": str(run_id)}
    if pipeline is not None:
        fields["pipeline"] = pipeline
    if step is not None:
        fields["step"] = step
    if attempt_id is not None:
        fields["attempt_id"] = str(attempt_id)
    if item is not None:
        fields["item"] = item
    return fields


async def run_fields(session: AsyncSession, run_id: UUID) -> LogFields:
    """Name a run and its pipeline, in one read."""
    found = await session.execute(
        sa.select(Pipeline.code).join(Run, Run.pipeline_id == Pipeline.id).where(Run.id == run_id)
    )
    return fields_of(run_id=run_id, pipeline=found.scalar_one_or_none())


async def attempt_fields(session: AsyncSession, attempt: StepAttempt) -> LogFields:
    """Name an attempt with its run, its pipeline, its step and its item, in one read."""
    found = await session.execute(
        sa.select(Pipeline.code, RunItem.item_key)
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .outerjoin(RunItem, RunItem.id == attempt.run_item_id)
        .where(Run.id == attempt.run_id)
    )
    row = found.one_or_none()
    return fields_of(
        run_id=attempt.run_id,
        pipeline=row[0] if row else None,
        step=attempt.step_name,
        attempt_id=attempt.id,
        item=row[1] if row and attempt.run_item_id is not None else None,
    )
