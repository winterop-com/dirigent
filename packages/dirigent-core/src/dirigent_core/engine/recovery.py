"""Crash recovery: expired leases, the submit window, runs that stopped moving, and dead workers.

Where a reclaimed attempt lands depends on whether its work went out. A handle committed on
the attempt's own row means it returns to ``waiting`` and keeps probing; no handle means it
re-queues.
"""

from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.engine.state import lock_run
from dirigent_core.logging import get_logger
from dirigent_core.models import Run, StepAttempt, utcnow
from dirigent_core.models import Worker as WorkerRow

_logger = get_logger("engine")


async def sweep_leases(session: AsyncSession, *, now: datetime | None = None) -> list[UUID]:
    """Reclaim every attempt whose worker stopped heartbeating, and say which ones moved."""
    moment = now or utcnow()
    rows = await session.execute(
        sa.select(StepAttempt)
        .where(
            StepAttempt.status == AttemptStatus.RUNNING,
            StepAttempt.lease_expires_at.is_not(None),
            StepAttempt.lease_expires_at < moment,
        )
        # Ordered by run so that two sweepers take the same run locks in the same order and
        # queue behind each other instead of deadlocking.
        .order_by(StepAttempt.run_id, StepAttempt.id)
    )
    recovered: list[UUID] = []
    for attempt in rows.scalars():
        # Recovery competes with the worker that still thinks it owns this attempt. Taking
        # the run lock orders the two: either the worker's outcome transaction lands first
        # and this attempt is no longer running, or this one lands first and the worker's
        # lease check refuses. Re-read the row under the lock, because the select above ran
        # without one.
        await lock_run(session, attempt.run_id)
        await session.refresh(attempt)
        if attempt.status is not AttemptStatus.RUNNING or attempt.lease_expires_at is None:
            continue
        if attempt.lease_expires_at >= moment:
            continue
        if attempt.remote_handle is not None:
            attempt.status = AttemptStatus.WAITING
            attempt.next_poll_at = moment
            landing = "waiting"
        else:
            attempt.status = AttemptStatus.QUEUED
            attempt.available_at = moment
            landing = "queued"
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        recovered.append(attempt.id)
        _logger.warning(
            "lease expired, attempt recovered",
            attempt_id=str(attempt.id),
            step=attempt.step_name,
            landing=landing,
        )
    return recovered


async def detect_stuck_runs(
    session: AsyncSession,
    *,
    after: timedelta,
    now: datetime | None = None,
) -> list[UUID]:
    """Flag running runs that have not moved for too long."""
    moment = now or utcnow()
    threshold = moment - after
    latest_change = (
        sa.select(StepAttempt.run_id, sa.func.max(StepAttempt.updated_at).label("last_change"))
        .group_by(StepAttempt.run_id)
        .subquery()
    )
    rows = await session.execute(
        sa.select(Run.id)
        .join(latest_change, latest_change.c.run_id == Run.id)
        .where(Run.status == RunStatus.RUNNING, latest_change.c.last_change < threshold)
    )
    stuck = list(rows.scalars())
    for run_id in stuck:
        _logger.warning("run has not progressed", run_id=str(run_id), stalled_for=str(after))
    return stuck


async def overdue_deadlines(session: AsyncSession, *, now: datetime | None = None) -> list[StepAttempt]:
    """Attempts whose deadline passed while nothing was working on them.

    A running attempt is already bounded: the executor holds it under the step's timeout. These
    are the ones parked between pokes, where the next poke is what would notice the deadline
    and may be an hour away.
    """
    moment = now or utcnow()
    rows = await session.execute(
        sa.select(StepAttempt).where(
            StepAttempt.deadline_at.is_not(None),
            StepAttempt.deadline_at <= moment,
            StepAttempt.status.in_((AttemptStatus.PENDING, AttemptStatus.QUEUED, AttemptStatus.WAITING)),
        )
    )
    return list(rows.scalars())


async def reap_workers(
    session: AsyncSession,
    *,
    older_than: timedelta,
    now: datetime | None = None,
) -> list[str]:
    """Delete registry rows for workers that stopped heartbeating, and say which ones went.

    Only the registry row goes; leases are reclaimed by :func:`sweep_leases` on a much
    shorter clock.
    """
    moment = now or utcnow()
    threshold = moment - older_than
    rows = await session.execute(sa.select(WorkerRow).where(WorkerRow.last_seen_at < threshold))
    reaped: list[str] = []
    for worker in rows.scalars():
        _logger.info(
            "worker registry row reaped",
            worker=worker.name,
            status=worker.status.value,
            last_seen_at=worker.last_seen_at.isoformat(),
        )
        reaped.append(worker.name)
        await session.delete(worker)
    return reaped
