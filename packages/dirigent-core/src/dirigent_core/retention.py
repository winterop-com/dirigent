"""What is deleted once it is old enough, and how much of it goes at a time.

Every table here grows with use and nothing else bounds it. A run's own age governs the
run and everything the database cascades from it -- its items, attempts, artifact refs and
notifications -- so pruning a run is one delete. Log entries carry their own age because
they are the bulk of it and are worth losing first.

A sweep deletes in batches and commits each one, so a prune that is interrupted has still
made progress and a prune of a year's backlog never holds one long transaction open.
"""

import shutil
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_core.engine.claim import is_postgres
from dirigent_core.logging import get_logger
from dirigent_core.models import LogEntry, Notification, Run, ScheduleFiring, WebhookDelivery
from dirigent_core.storage import Storage

if TYPE_CHECKING:
    from dirigent_core.config import Settings

_logger: Final = get_logger("dirigent.retention")

#: How many rows one statement deletes. A batch commits on its own, so a large backlog is
#: many short transactions rather than one that holds locks for minutes.
BATCH: Final = 500

#: Each family a sweep prunes on its own age: the policy field, the table, and what else
#: disqualifies a row from going. Runs are not here -- they are pruned on when they settled
#: rather than on when they were created, and their artifacts go before their rows.
FAMILIES: Final[tuple[tuple[str, type[Any], tuple[sa.ColumnElement[bool], ...]], ...]] = (
    ("logs", LogEntry, ()),
    ("deliveries", WebhookDelivery, ()),
    ("firings", ScheduleFiring, ()),
    # An alert that has not been sent is still owed to somebody.
    ("notifications", Notification, (Notification.sent_at.is_not(None),)),
)

#: A run is only ever pruned once it has settled: an unfinished run is either still running
#: or is the evidence of something that went wrong.
SETTLED: Final = Run.finished_at.is_not(None)


class Policy(BaseModel):
    """How long each family of rows is kept. A family with no age is never pruned."""

    model_config = ConfigDict(frozen=True)

    runs: timedelta | None = None
    """Runs, and by cascade their items, attempts, artifact refs and notifications."""

    logs: timedelta | None = None
    """Log entries of runs too young to prune, which is what makes a shorter age useful."""

    deliveries: timedelta | None = None
    """What arrived at a webhook."""

    firings: timedelta | None = None
    """When a schedule fired."""

    notifications: timedelta | None = None
    """Alerts already sent, whose run is too young to prune."""

    scratch: bool = True
    """Whether a pruned run's artifacts are deleted from storage along with its rows."""


class Swept(BaseModel):
    """What one sweep deleted, by family, and what it could not."""

    counts: dict[str, int] = Field(default_factory=dict[str, int])
    """How many rows went, keyed by family. A family that pruned nothing is absent."""

    scratch_deleted: int = 0
    """How many artifacts were deleted from storage."""

    scratch_failed: int = 0
    """How many prefixes storage refused, which leaves the rows for the next sweep."""

    @property
    def total(self) -> int:
        """How many rows went in all."""
        return sum(self.counts.values())

    def record(self, family: str, deleted: int) -> None:
        """Note that a family deleted this many rows, where it deleted any."""
        if deleted:
            self.counts[family] = self.counts.get(family, 0) + deleted


def policy_from(settings: "Settings") -> Policy:
    """Read the configured ages as a policy. Nothing configured prunes nothing."""
    return Policy(
        runs=settings.retention_runs,
        logs=settings.retention_logs,
        deliveries=settings.retention_deliveries,
        firings=settings.retention_firings,
        notifications=settings.retention_notifications,
        scratch=settings.retention_scratch,
    )


def configured(policy: Policy) -> bool:
    """Report whether any family has an age, which is whether a sweep would do anything."""
    return any(
        age is not None for age in (policy.runs, policy.logs, policy.deliveries, policy.firings, policy.notifications)
    )


async def sweep(
    session: AsyncSession,
    policy: Policy,
    *,
    storage: Storage | None = None,
    now: datetime | None = None,
    limit: int = BATCH,
) -> Swept:
    """Delete one batch of everything the policy has outlived, and say what went.

    Runs go last, so a log entry pruned on its own age is not counted twice when the run it
    belongs to goes in the same sweep.
    """
    moment = now or datetime.now(UTC)
    swept = Swept()
    for family, model, extra in FAMILIES:
        age = getattr(policy, family)
        if age is not None:
            swept.record(family, await _prune(session, model, moment - age, limit, *extra))
    if policy.runs is not None:
        swept.record("runs", await _prune_runs(session, moment - policy.runs, limit, policy, storage, swept))
    return swept


async def counted(session: AsyncSession, policy: Policy, *, now: datetime | None = None) -> dict[str, int]:
    """Count what a sweep would delete, without deleting any of it.

    The counts are of what is old enough now. A run pruned here would take its own log
    entries with it, so the two families overlap and the total is an upper bound.
    """
    moment = now or datetime.now(UTC)
    counts: dict[str, int] = {}
    for family, model, extra in FAMILIES:
        age = getattr(policy, family)
        if age is not None:
            counts[family] = await _count(session, model, moment - age, *extra)
    if policy.runs is not None:
        counts["runs"] = await _count(session, Run, moment - policy.runs, SETTLED, column=Run.finished_at)
    return {family: count for family, count in counts.items() if count}


async def _count(
    session: AsyncSession,
    model: type[Any],
    threshold: datetime,
    *conditions: sa.ColumnElement[bool],
    column: Any = None,
) -> int:
    """Count the rows of one family that are old enough to go."""
    age = model.created_at if column is None else column
    counting = sa.select(sa.func.count()).select_from(model).where(age < threshold, *conditions)
    return int((await session.execute(counting)).scalar_one())


async def _prune(
    session: AsyncSession,
    model: type[Any],
    threshold: datetime,
    limit: int,
    *conditions: sa.ColumnElement[bool],
) -> int:
    """Delete up to ``limit`` rows older than the threshold, and say how many went.

    Every table says how old a row is the same way, so the only thing that varies between
    families is which table and what else disqualifies a row from going.

    The rows are selected by primary key first and deleted by that key, because ``DELETE ..
    LIMIT`` is not portable and a bare ``DELETE .. WHERE age`` has no bound at all.
    """
    doomed = sa.select(model.id).where(model.created_at < threshold, *conditions).order_by(model.id).limit(limit)
    keys = list((await session.execute(doomed)).scalars())
    if not keys:
        return 0
    await session.execute(sa.delete(model).where(model.id.in_(keys)))
    return len(keys)


async def _prune_runs(
    session: AsyncSession,
    threshold: datetime,
    limit: int,
    policy: Policy,
    storage: Storage | None,
    swept: Swept,
) -> int:
    """Delete settled runs older than the threshold, with their artifacts before their rows.

    Storage goes first: a row deleted before its artifacts are gone is a scratch prefix
    nothing points at any more, and nothing would find it again.
    """
    doomed = sa.select(Run.id).where(Run.finished_at < threshold, SETTLED).order_by(Run.id).limit(limit)
    if is_postgres(session):
        # A manual retry holds the run's row while it reopens it. Skipping a locked row leaves
        # that run to the next sweep rather than clearing artifacts a live run is about to read.
        doomed = doomed.with_for_update(skip_locked=True)
    keys = list((await session.execute(doomed)).scalars())
    if not keys:
        return 0
    cleared = False
    if policy.scratch and storage is not None:
        cleared = True
        keys = await _clear_scratch(storage, keys, swept)
        if not keys:
            return 0
    # Storage is cleared outside the transaction, and a retry can reopen a run in that window.
    # The delete says again what made the run prunable, so a reopened run keeps its rows.
    await session.execute(sa.delete(Run).where(Run.id.in_(keys), SETTLED, Run.finished_at < threshold))
    survived = list((await session.execute(sa.select(Run.id).where(Run.id.in_(keys)))).scalars())
    if cleared:
        for run_id in survived:
            _logger.warning("a run reopened mid-sweep kept its rows without its artifacts", run_id=str(run_id))
    return len(keys) - len(survived)


async def sweep_work(session: AsyncSession, work_root: str, policy: Policy, *, now: datetime | None = None) -> int:
    """Remove this worker's work directory for every run the policy has outlived.

    The database sweep runs on the scheduler alone, and a work directory is on the filesystem
    of the worker that wrote it, so this is the worker's own half of the same policy: each
    worker sweeps its own, and a run's directories go from every worker that held one.

    A directory whose run has no row left is swept too, because the row went in a sweep that
    could not reach here.
    """
    if policy.runs is None or not policy.scratch:
        return 0
    directory = Path(work_root).expanduser() / "runs"
    if not directory.is_dir():
        return 0
    held = {run.name: run for run in directory.iterdir() if run.is_dir() and _is_uuid(run.name)}
    if not held:
        return 0
    threshold = (now or datetime.now(UTC)) - policy.runs
    keeping = await session.execute(
        sa.select(Run.id).where(
            Run.id.in_([UUID(name) for name in held]), sa.or_(~SETTLED, Run.finished_at >= threshold)
        )
    )
    swept = 0
    for name in held.keys() - {str(run_id) for run_id in keeping.scalars()}:
        try:
            shutil.rmtree(held[name])
        except OSError as error:
            _logger.warning("a run's work directory was not deleted", run_id=name, error=str(error))
            continue
        swept += 1
    return swept


def _is_uuid(name: str) -> bool:
    """Whether a directory under the work root is one a run made, rather than somebody else's."""
    try:
        UUID(name)
    except ValueError:
        return False
    return True


async def _clear_scratch(storage: Storage, keys: Sequence[UUID], swept: Swept) -> list[UUID]:
    """Delete each run's artifacts, and report the runs whose rows may now go.

    A run whose storage refused is left whole -- rows and all -- for the next sweep, rather
    than having its rows deleted and its bytes orphaned.
    """
    cleared: list[UUID] = []
    for run_id in keys:
        prefix = storage.scratch_for(run_id)
        try:
            swept.scratch_deleted += await storage.delete_prefix(prefix)
        except OSError as error:
            swept.scratch_failed += 1
            _logger.warning("run scratch was not deleted", run_id=str(run_id), uri=prefix, error=str(error))
            continue
        cleared.append(run_id)
    return cleared
