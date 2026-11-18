"""Crash recovery: expired leases, the submit window, runs that stopped moving, and dead workers.

Where a reclaimed attempt lands depends on whether its work went out. A handle committed on
the attempt's own row means it returns to ``waiting`` and keeps probing; no handle means it
re-queues.
"""

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.engine.logcontext import attempt_fields, run_fields
from dirigent_core.engine.state import lock_run
from dirigent_core.logging import get_logger
from dirigent_core.models import Run, StepAttempt, utcnow
from dirigent_core.models import Worker as WorkerRow

_logger = get_logger("engine")

#: How far a worker's clock may stand from the database's before it says so: every lease and
#: due time is written by one host's clock and compared by another's.
CLOCK_SKEW_TOLERANCE: Final = timedelta(seconds=5)


async def warn_on_clock_skew(session: AsyncSession, *, worker: str) -> timedelta | None:
    """Say at WARNING when this host's clock stands off the database's, and answer by how much.

    Answers None on SQLite, whose one file is never shared between hosts.
    """
    if session.get_bind().dialect.name != "postgresql":
        return None
    database = (await session.execute(sa.select(sa.func.clock_timestamp()))).scalar_one()
    skew: timedelta = utcnow() - database
    if abs(skew) > CLOCK_SKEW_TOLERANCE:
        _logger.warning(
            "this host's clock is off the database's, so leases and due times are misjudged",
            worker=worker,
            skew_ms=round(skew.total_seconds() * 1000),
            tolerance_ms=round(CLOCK_SKEW_TOLERANCE.total_seconds() * 1000),
        )
    return skew


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
        attempt.lease_recoveries += 1
        attempt.lease_owner = None
        attempt.lease_token = None
        attempt.lease_expires_at = None
        recovered.append(attempt.id)
        _logger.warning(
            "lease expired, attempt recovered",
            **await attempt_fields(session, attempt),
            landing=landing,
        )
    return recovered


async def detect_stuck_runs(
    session: AsyncSession,
    *,
    after: timedelta,
    now: datetime | None = None,
) -> list[UUID]:
    """Flag running runs that have not moved for too long.

    A run moves when an attempt row changes, and an attempt parked on a poll or a retry backoff
    is owed its next look at ``next_poll_at`` or ``available_at``: a run is stuck only when both
    its last change and the latest look it is owed lie further back than ``after``.
    """
    moment = now or utcnow()
    threshold = moment - after
    owed = sa.case(
        (StepAttempt.status == AttemptStatus.WAITING, StepAttempt.next_poll_at),
        (StepAttempt.status == AttemptStatus.QUEUED, StepAttempt.available_at),
    )
    latest = (
        sa.select(
            StepAttempt.run_id,
            sa.func.max(StepAttempt.updated_at).label("last_change"),
            sa.func.max(owed).label("owed_at"),
        )
        .where(StepAttempt.run_id.in_(sa.select(Run.id).where(Run.status == RunStatus.RUNNING)))
        .group_by(StepAttempt.run_id)
        .subquery()
    )
    rows = await session.execute(
        sa.select(latest.c.run_id).where(
            latest.c.last_change < threshold,
            sa.or_(latest.c.owed_at.is_(None), latest.c.owed_at < threshold),
        )
    )
    stuck = list(rows.scalars())
    for run_id in stuck:
        _logger.warning("run has not progressed", **await run_fields(session, run_id), stalled_for=str(after))
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
