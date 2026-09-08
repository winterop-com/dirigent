"""Readiness, trigger rules, and the run status that derives from the leaves.

The DAG walk is the last statement of every outcome transaction: the same commit that settles
an attempt readies its dependents and derives the run's status.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import NamedTuple
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, RunItemStatus, RunStatus
from dirigent_client.schemas import AttemptOut
from dirigent_core.engine.definition import ItemPolicy, PipelineDefinition, StepDefinition, TriggerRule
from dirigent_core.models import Pipeline, Run, RunItem, StepAttempt, utcnow


class StepOutcome(StrEnum):
    """What a step as a whole amounts to, once its attempts and items are folded together."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        """Report whether this outcome can still change."""
        return self in TERMINAL_OUTCOMES


TERMINAL_OUTCOMES = frozenset({StepOutcome.SUCCEEDED, StepOutcome.FAILED, StepOutcome.SKIPPED, StepOutcome.CANCELLED})

ATTEMPT_OUTCOME: dict[AttemptStatus, StepOutcome] = {
    AttemptStatus.PENDING: StepOutcome.PENDING,
    AttemptStatus.QUEUED: StepOutcome.RUNNING,
    AttemptStatus.RUNNING: StepOutcome.RUNNING,
    AttemptStatus.WAITING: StepOutcome.RUNNING,
    AttemptStatus.SUCCEEDED: StepOutcome.SUCCEEDED,
    AttemptStatus.FAILED: StepOutcome.FAILED,
    AttemptStatus.SKIPPED: StepOutcome.SKIPPED,
    AttemptStatus.CANCELLED: StepOutcome.CANCELLED,
}

ITEM_STATUS: dict[StepOutcome, RunItemStatus] = {
    StepOutcome.PENDING: RunItemStatus.PENDING,
    StepOutcome.RUNNING: RunItemStatus.RUNNING,
    StepOutcome.SUCCEEDED: RunItemStatus.SUCCEEDED,
    StepOutcome.FAILED: RunItemStatus.FAILED,
    StepOutcome.SKIPPED: RunItemStatus.SKIPPED,
    StepOutcome.CANCELLED: RunItemStatus.SKIPPED,
}


class Readiness(StrEnum):
    """What a trigger rule says about a step whose prerequisites are in a given state."""

    WAIT = "wait"
    READY = "ready"

    NEVER = "never"
    """The rule can no longer be satisfied; the step is skipped, and that propagates."""


def evaluate_rule(rule: TriggerRule, outcomes: Sequence[StepOutcome]) -> Readiness:
    """Apply a trigger rule to the outcomes of a step's prerequisites."""
    if not outcomes:
        return Readiness.READY
    settled = all(outcome.terminal for outcome in outcomes)
    match rule:
        case TriggerRule.ALL_SUCCESS:
            if any(outcome.terminal and outcome is not StepOutcome.SUCCEEDED for outcome in outcomes):
                return Readiness.NEVER
            return Readiness.READY if settled else Readiness.WAIT
        case TriggerRule.ALL_DONE | TriggerRule.ALWAYS:
            return Readiness.READY if settled else Readiness.WAIT
        case TriggerRule.ONE_FAILED:
            if any(outcome is StepOutcome.FAILED for outcome in outcomes):
                return Readiness.READY
            return Readiness.NEVER if settled else Readiness.WAIT


def aggregate_items(outcomes: Sequence[StepOutcome], policy: ItemPolicy) -> StepOutcome:
    """Fold a fan-out step's per-item outcomes into one step outcome."""
    if not outcomes:
        return StepOutcome.SKIPPED
    if any(not outcome.terminal for outcome in outcomes):
        return StepOutcome.RUNNING
    if any(outcome is StepOutcome.CANCELLED for outcome in outcomes):
        return StepOutcome.CANCELLED
    failed = [outcome for outcome in outcomes if outcome is StepOutcome.FAILED]
    succeeded = [outcome for outcome in outcomes if outcome is StepOutcome.SUCCEEDED]
    if policy is ItemPolicy.FAIL_FAST:
        return StepOutcome.FAILED if failed else (StepOutcome.SUCCEEDED if succeeded else StepOutcome.SKIPPED)
    if succeeded:
        return StepOutcome.SUCCEEDED
    return StepOutcome.FAILED if failed else StepOutcome.SKIPPED


class StepState(BaseModel):
    """One step folded down to what the rest of the engine needs to know about it."""

    model_config = ConfigDict(frozen=True)

    name: str
    outcome: StepOutcome
    item_failures: int = 0
    tolerated: bool = False

    @property
    def rule_outcome(self) -> StepOutcome:
        """The outcome dependents see: a tolerated failure does not block the branch."""
        if self.outcome is StepOutcome.FAILED and self.tolerated:
            return StepOutcome.SUCCEEDED
        return self.outcome

    @property
    def has_errors(self) -> bool:
        """Report whether this step contributes to a completed-with-errors run."""
        return self.item_failures > 0 or (self.outcome is StepOutcome.FAILED and self.tolerated)


#: Stands in for the start of a step that never started, so it sorts after every one that did.
NEVER = datetime.max.replace(tzinfo=UTC)


#: What ordering a run's attempts can be asked to order: the stored row, or its wire shape.
type Attempted = StepAttempt | AttemptOut


def in_execution_order[T: Attempted](
    attempts: Iterable[T],
    item_index: Mapping[UUID, int] | None = None,
    step_order: Sequence[str] = (),
) -> list[T]:
    """Order a run's attempts the way a person watched them happen.

    A step sorts on when it first started, which puts it after everything it waited for
    without any edge being consulted: it could not have started before they finished. Steps
    that have not started have no execution order to be in, so they keep the order their
    author wrote them in, which is also the tiebreak between two that started together --
    alphabetical order is nobody's intent. Inside one step the sequence that carries meaning
    is the fan-out item's index rather than which item was claimed first, and a retry follows
    the attempt it retries.
    """
    rows = list(attempts)
    indexes = item_index or {}
    written = {name: index for index, name in enumerate(step_order)}
    started: dict[str, datetime] = {}
    finished: dict[str, datetime] = {}
    for row in rows:
        if row.started_at is not None:
            started[row.step_name] = min(started.get(row.step_name, row.started_at), row.started_at)
        if row.finished_at is not None:
            finished[row.step_name] = min(finished.get(row.step_name, row.finished_at), row.finished_at)

    def sequence(row: T) -> tuple[datetime, datetime, int, str, int, int, UUID]:
        return (
            started.get(row.step_name, NEVER),
            finished.get(row.step_name, NEVER),
            written.get(row.step_name, len(written)),
            row.step_name,
            indexes.get(row.id, -1),
            row.attempt,
            row.id,
        )

    return sorted(rows, key=sequence)


def latest_attempts(attempts: Iterable[StepAttempt]) -> dict[tuple[str, UUID | None], StepAttempt]:
    """Keep only the newest attempt of each step, or of each item of a fan-out step."""
    newest: dict[tuple[str, UUID | None], StepAttempt] = {}
    for attempt in attempts:
        key = (attempt.step_name, attempt.run_item_id)
        current = newest.get(key)
        if current is None or attempt.attempt > current.attempt:
            newest[key] = attempt
    return newest


def latest_outcomes(attempts: Iterable[StepAttempt]) -> dict[str, list[StepOutcome]]:
    """Read what the newest try of each step, and of each item of a fan-out step, amounts to."""
    by_step: dict[str, list[StepOutcome]] = {}
    for (step_name, _), attempt in latest_attempts(attempts).items():
        by_step.setdefault(step_name, []).append(ATTEMPT_OUTCOME[attempt.status])
    return by_step


def step_states(definition: PipelineDefinition, outcomes: Mapping[str, Sequence[StepOutcome]]) -> dict[str, StepState]:
    """Fold each step's newest attempt outcomes into one state per step.

    A step is its attempts folded down, and folding reads only what each newest try amounts
    to, so a caller holding counts can answer this without holding the rows they came from.
    """
    states: dict[str, StepState] = {}
    for name, step in definition.steps.items():
        found = list(outcomes.get(name, ()))
        if step.is_fan_out:
            outcome = aggregate_items(found, step.items)
            failures = sum(1 for item in found if item is StepOutcome.FAILED)
        elif found:
            outcome = found[0]
            failures = 0
        else:
            outcome = StepOutcome.PENDING
            failures = 0
        states[name] = StepState(
            name=name,
            outcome=outcome,
            item_failures=failures,
            tolerated=step.continue_on_failure or _tolerated_fan_out(step, outcome),
        )
    return states


def build_step_states(definition: PipelineDefinition, attempts: Iterable[StepAttempt]) -> dict[str, StepState]:
    """Fold every attempt of a run into one state per step."""
    return step_states(definition, latest_outcomes(attempts))


def _tolerated_fan_out(step: StepDefinition, outcome: StepOutcome) -> bool:
    """Report whether ``items: continue`` should absorb this fan-out step's outcome.

    ``continue`` means "carry on past the items that failed", not "this step cannot fail": a
    fan-out where every item failed must stay failed, or dependents run on nothing.
    """
    if not (step.is_fan_out and step.items is ItemPolicy.CONTINUE):
        return False
    return outcome is not StepOutcome.FAILED


def readiness_of(definition: PipelineDefinition, name: str, states: dict[str, StepState]) -> Readiness:
    """Evaluate one step's trigger rule against the current state of its prerequisites."""
    step = definition.steps[name]
    outcomes = [states[dependency].rule_outcome for dependency in step.depends_on]
    return evaluate_rule(step.rule, outcomes)


def derive_run_status(states: dict[str, StepState], *, cancelled: bool = False) -> RunStatus | None:
    """Derive the run's status from its leaves, or None while anything is still in flight."""
    if cancelled:
        return RunStatus.CANCELLED
    if any(not state.outcome.terminal for state in states.values()):
        return None
    if any(state.outcome is StepOutcome.CANCELLED for state in states.values()):
        return RunStatus.CANCELLED
    hard = [state for state in states.values() if state.outcome is StepOutcome.FAILED and not state.tolerated]
    if hard:
        return RunStatus.FAILED
    if any(state.has_errors for state in states.values()):
        return RunStatus.COMPLETED_WITH_ERRORS
    return RunStatus.SUCCEEDED


async def lock_run(session: AsyncSession, run_id: UUID) -> None:
    """Serialise the outcome transactions of one run, so its status is derived once.

    Without this, two workers settling the run's last two attempts each read the other as
    still in flight and neither concludes the run finished. PostgreSQL only.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(sa.select(Run.id).where(Run.id == run_id).with_for_update())


async def lock_pipeline(session: AsyncSession, pipeline_id: UUID) -> None:
    """Serialise the run-creation decisions of one pipeline, so its concurrency policy holds.

    ``skip`` and ``queue`` are read-then-decide-then-write across processes. PostgreSQL only,
    as :func:`lock_run` is.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(sa.select(Pipeline.id).where(Pipeline.id == pipeline_id).with_for_update())


async def load_attempts(session: AsyncSession, run_id: UUID) -> list[StepAttempt]:
    """Read every attempt of a run."""
    rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run_id))
    return list(rows.scalars())


async def advance(
    session: AsyncSession, run: Run, definition: PipelineDefinition, *, now: datetime | None = None
) -> RunStatus:
    """Walk the DAG once: ready what is unblocked, skip what can never run, settle the run.

    This is the last statement of an outcome transaction, so it must reach a fixpoint in one
    pass: skipping a step can unblock or doom its own dependents.
    """
    moment = now or utcnow()
    await session.flush()
    await lock_run(session, run.id)
    attempts = await load_attempts(session, run.id)
    pending = [attempt for attempt in attempts if attempt.status is AttemptStatus.PENDING]

    changed = True
    while changed:
        changed = False
        states = build_step_states(definition, attempts)
        for attempt in pending:
            if attempt.status is not AttemptStatus.PENDING:
                continue
            match readiness_of(definition, attempt.step_name, states):
                case Readiness.READY:
                    attempt.status = AttemptStatus.QUEUED
                    attempt.available_at = moment
                    changed = True
                case Readiness.NEVER:
                    attempt.status = AttemptStatus.SKIPPED
                    attempt.finished_at = moment
                    changed = True
                case Readiness.WAIT:
                    pass

    await _settle_items(session, run, attempts, moment)
    states = build_step_states(definition, attempts)
    derived = derive_run_status(states, cancelled=run.status is RunStatus.CANCELLED)
    if derived is None:
        if run.status is RunStatus.QUEUED and any(attempt.started_at is not None for attempt in attempts):
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or moment
        await session.flush()
        return run.status
    run.status = derived
    run.finished_at = run.finished_at or moment
    await session.flush()
    return derived


async def _settle_items(
    session: AsyncSession,
    run: Run,
    attempts: Sequence[StepAttempt],
    moment: datetime,
) -> None:
    """Mirror each fan-out attempt's state onto its run item."""
    item_ids = {attempt.run_item_id for attempt in attempts if attempt.run_item_id is not None}
    if not item_ids:
        return
    rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id))
    items = {item.id: item for item in rows.scalars()}
    for (step_name, run_item_id), attempt in latest_attempts(attempts).items():
        item = items.get(run_item_id) if run_item_id is not None else None
        if item is None:
            continue
        outcome = ATTEMPT_OUTCOME[attempt.status]
        item.status = ITEM_STATUS[outcome]
        item.started_at = item.started_at or attempt.started_at
        if outcome.terminal:
            item.finished_at = attempt.finished_at or moment
            item.error = attempt.error
            item.failing_step = step_name if outcome is StepOutcome.FAILED else None


class StepCounts(NamedTuple):
    """One step's attempts read as counts: how many there were, and what the newest amount to."""

    total: int
    latest: tuple[StepOutcome, ...]
    started_at: datetime | None
    finished_at: datetime | None


def _earliest(one: datetime | None, other: datetime | None) -> datetime | None:
    """Take the earlier of two instants, either of which may be missing."""
    if one is None or other is None:
        return one or other
    return min(one, other)


async def attempt_counts(session: AsyncSession, run_id: UUID) -> dict[str, StepCounts]:
    """Count a run's attempts per step and status, and say when each step first moved.

    A step's outcome is folded from the newest try of it, or of each of its fan-out items,
    which the rank picks out; the rest of a step's attempts are only ever counted.
    """
    ranked = (
        sa.select(
            StepAttempt.step_name,
            StepAttempt.status,
            StepAttempt.started_at,
            StepAttempt.finished_at,
            sa.func.row_number()
            .over(
                partition_by=(StepAttempt.step_name, StepAttempt.run_item_id),
                order_by=StepAttempt.attempt.desc(),
            )
            .label("rank"),
        )
        .where(StepAttempt.run_id == run_id)
        .subquery()
    )
    rows = await session.execute(
        sa.select(
            ranked.c.step_name,
            ranked.c.status,
            sa.func.count(),
            sa.func.sum(sa.case((ranked.c.rank == 1, 1), else_=0)),
            sa.func.min(ranked.c.started_at),
            sa.func.min(ranked.c.finished_at),
        ).group_by(ranked.c.step_name, ranked.c.status)
    )
    counts: dict[str, StepCounts] = {}
    for name, attempt_status, total, newest, started, finished in rows.all():
        held = counts.get(name, StepCounts(0, (), None, None))
        counts[name] = StepCounts(
            total=held.total + total,
            latest=held.latest + (ATTEMPT_OUTCOME[attempt_status],) * newest,
            started_at=_earliest(held.started_at, started),
            finished_at=_earliest(held.finished_at, finished),
        )
    return counts


async def item_counts(session: AsyncSession, run_id: UUID) -> dict[str, dict[RunItemStatus, int]]:
    """Count a run's fan-out items per step and status."""
    rows = await session.execute(
        sa.select(RunItem.step_name, RunItem.status, sa.func.count())
        .where(RunItem.run_id == run_id)
        .group_by(RunItem.step_name, RunItem.status)
    )
    counts: dict[str, dict[RunItemStatus, int]] = {}
    for name, item_status, total in rows.all():
        counts.setdefault(name, {})[item_status] = total
    return counts
