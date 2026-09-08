"""The claim query: one statement that pulls the next due unit of work.

On PostgreSQL the claim takes ``FOR UPDATE SKIP LOCKED``, so concurrent workers step over
each other's rows. SQLite has no such clause, and the process-wide lock that stands in for it
is only correct when exactly one process exists -- the guarantee the standalone mode makes.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import PRIORITY_RANK, AttemptStatus, RunPriority, RunStatus
from dirigent_common import JsonMap
from dirigent_core.engine.context import ConnectionRecord
from dirigent_core.engine.definition import StepDefinition
from dirigent_core.models import Run, StepAttempt
from dirigent_plugin import RemoteHandle

MAX_SETTLED_PER_CLAIM = 50

CLAIMABLE_RUN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


class ClaimedUnit(BaseModel):
    """Everything one block call needs, snapshotted by the transaction that claimed it."""

    model_config = ConfigDict(frozen=True)

    attempt_id: UUID
    run_id: UUID
    run_item_id: UUID | None
    step_name: str
    block_id: str
    attempt_number: int
    started_at: datetime
    """When this attempt first started, which a wait measures itself from."""

    previous_status: AttemptStatus
    step: StepDefinition
    config: JsonMap
    params: JsonMap
    log_levels: JsonMap | None = None
    """The run's kept-level map, resolved against the block id when the buffer is built."""
    scratch: str
    item: JsonValue
    has_item: bool
    connections: dict[str, ConnectionRecord]
    schemas: dict[str, JsonMap] = Field(default_factory=dict)
    traceparent: str | None = None
    """The run's trace context, so an attempt's span joins the trace the run started in."""

    remote_handle: RemoteHandle | None = None
    poke_cursor: JsonMap | None = None
    """The cursor the last committed poke returned, handed to the next one."""

    deadline_at: datetime | None = None
    gone_probes: int = 0

    @property
    def is_probe(self) -> bool:
        """Report whether this claim continues a wait rather than starting the work."""
        return self.previous_status is AttemptStatus.WAITING


def is_postgres(session: AsyncSession) -> bool:
    """Report whether this session speaks PostgreSQL."""
    return session.get_bind().dialect.name == "postgresql"


def routable(tags: Sequence[str], *, postgres: bool) -> sa.ColumnElement[bool]:
    """Build the test that a run's pinned tags are all carried by a worker holding ``tags``.

    A run pinning no tags is claimable by anyone. On PostgreSQL the column is ``jsonb`` and
    the test is containment, which a GIN index answers; on SQLite it is a correlated
    ``json_each`` walk looking for one pinned tag the worker does not carry.
    """
    carried = sorted(set(tags))
    if postgres:
        contained = sa.type_coerce(Run.worker_tags, JSONB).contained_by(
            sa.cast(sa.literal(json.dumps(carried), sa.Text), JSONB)
        )
        return cast("sa.ColumnElement[bool]", contained)
    element = sa.func.json_each(Run.worker_tags).table_valued("value", joins_implicitly=True)
    missing = sa.select(1).select_from(element).where(element.c.value.notin_(carried))
    return ~sa.exists(missing)


def priority_rank() -> sa.Case[int]:
    """Score a run's priority so the claim can sort on it, highest first."""
    return sa.case(
        {priority.value: rank for priority, rank in PRIORITY_RANK.items()},
        value=Run.priority,
        else_=PRIORITY_RANK[RunPriority.NORMAL],
    )


def due_attempt_statement(
    now: datetime, tags: Sequence[str] = (), *, postgres: bool = False
) -> sa.Select[tuple[StepAttempt]]:
    """Build the select that finds the next due unit of work this worker may run.

    The order is priority first, then fairness, then due time. Fairness is round-robin
    between runs: every attempt of a run still in flight is numbered within that run, and the
    claim takes the lowest number among the due ones. The number counts the attempts already
    taken, so a run that has been served falls behind one that has not, and a
    four-hundred-item fan-out interleaves one attempt at a time with a two-step run rather
    than holding every slot until it drains. Numbering only the due rows would not do it:
    claiming one removes it, and the rest would renumber from one after every claim.

    The subquery computes the ranking and nothing else. Every predicate that decides whether
    an attempt may be claimed is repeated on the locked ``step_attempts`` relation in the
    outer select, because ``SKIP LOCKED`` re-checks a row that changed under it against the
    outer query's own predicates only: a status test living solely in the subquery would not
    be re-evaluated, and two workers would take the same attempt.
    """
    due_at = sa.func.coalesce(StepAttempt.available_at, StepAttempt.next_poll_at)
    ranked = (
        sa.select(
            StepAttempt.id.label("attempt_id"),
            priority_rank().label("priority_rank"),
            sa.func.row_number().over(partition_by=StepAttempt.run_id, order_by=(due_at, StepAttempt.id)).label("turn"),
            due_at.label("due_at"),
        )
        .join(Run, Run.id == StepAttempt.run_id)
        .where(Run.status.in_(CLAIMABLE_RUN_STATUSES), routable(tags, postgres=postgres))
        .subquery()
    )
    due = sa.or_(
        sa.and_(StepAttempt.status == AttemptStatus.QUEUED, StepAttempt.available_at <= now),
        sa.and_(StepAttempt.status == AttemptStatus.WAITING, StepAttempt.next_poll_at <= now),
    )
    return (
        sa.select(StepAttempt)
        .join(Run, Run.id == StepAttempt.run_id)
        .join(ranked, ranked.c.attempt_id == StepAttempt.id)
        .where(due, Run.status.in_(CLAIMABLE_RUN_STATUSES), routable(tags, postgres=postgres))
        .order_by(ranked.c.priority_rank.desc(), ranked.c.turn, ranked.c.due_at, ranked.c.attempt_id)
        .limit(1)
    )


async def select_due(session: AsyncSession, now: datetime, tags: Sequence[str] = ()) -> StepAttempt | None:
    """Run the claim select, locking the row on the dialect that can."""
    postgres = is_postgres(session)
    statement = due_attempt_statement(now, tags, postgres=postgres)
    if postgres:
        statement = statement.with_for_update(skip_locked=True, of=StepAttempt)
    result = await session.execute(statement)
    return result.scalars().first()
