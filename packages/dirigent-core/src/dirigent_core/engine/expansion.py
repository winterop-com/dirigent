"""Writing a fan-out's items: when the run is created, or when a late grid's step becomes ready.

A grid is late when its ``for_each`` reads a step's output, or when it adopts a late grid.
Until its step is ready such a step holds one pending attempt with no item, its gate, which
keeps the step pending rather than folding it to skipped. When the walk finds the gate ready it
resolves the list against the outputs the run already holds, writes the items and their queued
attempts, and deletes the gate, all in the transaction that readied it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptKind, AttemptStatus, LogLevel, RunItemStatus
from dirigent_common import JsonMap
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.failure import Failure
from dirigent_core.engine.references import ReferenceScope, UnknownReference, resolve
from dirigent_core.engine.services import EngineServices
from dirigent_core.ids import uuid7
from dirigent_core.messages import FAN_OUT_EMPTY, FAN_OUT_NOT_A_LIST, FAN_OUT_TOO_WIDE
from dirigent_core.models import LogEntry, Run, RunItem, StepAttempt
from dirigent_core.storage import scratch_prefix
from dirigent_plugin import ErrorClass


def new_attempt(
    run: Run,
    name: str,
    step: StepDefinition,
    moment: datetime,
    *,
    held: bool,
    ready: bool = False,
    run_item_id: UUID | None = None,
    cursor: JsonMap | None = None,
) -> StepAttempt:
    """Build one attempt row: root steps queued, everything else pending on its edges.

    ``ready`` queues the attempt whatever its edges say, which is what an expanded gate's items
    are: the gate was ready, so every one of them is.
    """
    queued = ready or (not step.depends_on and not held)
    return StepAttempt(
        poke_cursor=dict(cursor) if cursor is not None else None,
        run_id=run.id,
        run_item_id=run_item_id,
        step_name=name,
        block_id=step.block,
        attempt=1,
        kind=AttemptKind.AUTOMATIC,
        status=AttemptStatus.QUEUED if queued else AttemptStatus.PENDING,
        available_at=moment if queued else None,
    )


async def write_items(
    session: AsyncSession,
    run: Run,
    name: str,
    step: StepDefinition,
    elements: Sequence[JsonValue],
    moment: datetime,
    *,
    held: bool = False,
    ready: bool = False,
) -> list[StepAttempt]:
    """Write one run item per element, in list order, and the first attempt of each."""
    items = [
        RunItem(
            id=uuid7(),
            run_id=run.id,
            step_name=name,
            item_index=index,
            item_key=str(element)[:500],
            item_value={"value": element},
            status=RunItemStatus.PENDING,
        )
        for index, element in enumerate(elements)
    ]
    session.add_all(items)
    await session.flush()
    attempts = [new_attempt(run, name, step, moment, held=held, ready=ready, run_item_id=item.id) for item in items]
    session.add_all(attempts)
    return attempts


def is_gate(definition: PipelineDefinition, attempt: StepAttempt) -> bool:
    """Report whether an attempt stands in for a fan-out step's items that do not exist yet."""
    step = definition.steps.get(attempt.step_name)
    return step is not None and step.is_fan_out and attempt.run_item_id is None


def item_value_of(item: RunItem | None) -> tuple[JsonValue, bool]:
    """Unwrap the element a run item maps, and say whether there is one at all."""
    if item is None or item.item_value is None:
        return None, False
    return item.item_value.get("value"), True


async def collect_outputs(session: AsyncSession, run_id: UUID, definition: PipelineDefinition) -> dict[str, JsonValue]:
    """Gather the stored outputs a step's references may read.

    A fan-out step's output is the list of its items' outputs in item order.
    """
    rows = await session.execute(
        sa.select(StepAttempt, RunItem.item_index)
        .join(RunItem, RunItem.id == StepAttempt.run_item_id, isouter=True)
        .where(StepAttempt.run_id == run_id, StepAttempt.status == AttemptStatus.SUCCEEDED)
        .order_by(StepAttempt.step_name, RunItem.item_index, StepAttempt.attempt)
    )
    collected: dict[str, JsonValue] = {}
    fanned: dict[str, list[JsonValue]] = {}
    for attempt, _index in rows:
        step = definition.steps.get(attempt.step_name)
        if step is not None and step.is_fan_out:
            fanned.setdefault(attempt.step_name, []).append(attempt.output)
        else:
            collected[attempt.step_name] = attempt.output
    collected.update(fanned)
    return collected


async def expand_gate(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    gate: StepAttempt,
    moment: datetime,
) -> list[StepAttempt] | None:
    """Replace a ready gate with its grid's items and their queued attempts.

    Returns the attempts written, and None when the gate stays: a list that cannot be read, or
    one wider than ``fan_out_max_items``, fails it as ``rejected``, and an empty one skips it.
    """
    name = gate.step_name
    step = definition.steps[name]
    source = definition.grid_source(name) or name
    try:
        elements = await _late_elements(session, services, run, definition, step)
    except UnknownReference as error:
        _fail(
            gate,
            Failure(code=error.code, message=str(error), params=error.params, error_class=ErrorClass.REJECTED),
            moment,
        )
        return None
    expression = repr(step.for_each)
    if not isinstance(elements, list):
        _fail(
            gate,
            Failure.rejected(FAN_OUT_NOT_A_LIST, step=repr(name), expression=expression, kind=type(elements).__name__),
            moment,
        )
        return None
    listed: list[JsonValue] = elements
    maximum = services.settings.fan_out_max_items
    if len(listed) > maximum:
        _fail(gate, Failure.rejected(FAN_OUT_TOO_WIDE, step=repr(name), count=len(listed), maximum=maximum), moment)
        return None
    if not listed:
        _skip_empty(gate, name, expression, source, moment)
        return None
    written = await write_items(session, run, name, step, listed, moment, ready=True)
    await session.delete(gate)
    session.add(
        LogEntry(
            run_id=run.id,
            step_name=name,
            level=LogLevel.INFO,
            message=f"expanded into {len(written)} items from {source}",
            fields={"items": len(written), "source": source},
        )
    )
    return written


async def _late_elements(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    step: StepDefinition,
) -> JsonValue:
    """Read the list a late grid expands into: an adopted grid's items, or what ``for_each`` resolves to."""
    adopted = step.adopted_grid
    if adopted is not None and step.output_source is None:
        rows = await session.execute(
            sa.select(RunItem)
            .where(RunItem.run_id == run.id, RunItem.step_name == adopted)
            .order_by(RunItem.item_index)
        )
        return [item_value_of(item)[0] for item in rows.scalars()]
    scope = ReferenceScope(
        params=dict(run.params),
        outputs=await collect_outputs(session, run.id, definition),
        scratch=scratch_prefix(services.settings.artifact_root, run.id),
        artifacts=services.storage.artifact_root,
        run_id=run.id,
        window_start=run.window_start,
        window_end=run.window_end,
    )
    return resolve(cast("JsonValue", step.for_each), scope)


def _fail(gate: StepAttempt, failure: Failure, moment: datetime) -> None:
    """Settle a gate whose grid cannot be expanded as a failure no retry can fix."""
    gate.status = AttemptStatus.FAILED
    gate.finished_at = moment
    gate.error = failure.message
    gate.error_code = failure.code
    gate.error_params = failure.params or None
    gate.error_class = failure.error_class.value


def _skip_empty(gate: StepAttempt, name: str, expression: str, source: str, moment: datetime) -> None:
    """Settle a gate whose list was empty as skipped, which folds the step to skipped.

    It is given a start, which is what keeps a retry elsewhere in the run from reopening it as
    a skip that only propagated.
    """
    gate.status = AttemptStatus.SKIPPED
    gate.started_at = moment
    gate.finished_at = moment
    gate.error = FAN_OUT_EMPTY.render(step=repr(name), expression=expression, source=source)
    gate.error_code = FAN_OUT_EMPTY.code
    gate.error_params = {"step": repr(name), "expression": expression, "source": source}
