"""What a run writes to storage, counted as it is written and held to the quota its chain shares.

A run's own count is on its row, and its chain's count is on the row of the run that began the
chain, so a run that a step of another run started spends from that run's quota. Every change
to a count is one statement in a transaction of its own, never inside another: it locks one row
and waits holding nothing, so it cannot close a cycle with the transactions that lock runs.

Checking and adding are one conditional UPDATE. SQLite runs every transaction behind
``BEGIN IMMEDIATE``, one at a time; PostgreSQL holds a second writer of the row until the first
commits, then tests the condition against the row that commit left. Either way two writers
cannot both pass a quota only one of them fits under.
"""

import asyncio
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from dirigent_client.enums import TriggerKind
from dirigent_common import format_size
from dirigent_core.database import session_scope
from dirigent_core.engine.failure import Failure
from dirigent_core.engine.runs import MAX_CHAIN_WALK
from dirigent_core.logging import get_logger
from dirigent_core.messages import STORAGE_QUOTA
from dirigent_core.models import Run
from dirigent_plugin import BlockFailure, ErrorClass

#: How much a meter counts at a time, so a stream of small writes is not a transaction each.
GRANT: Final = 1024 * 1024

_logger = get_logger("quota")


async def chain_root(session: AsyncSession, run_id: UUID) -> UUID:
    """Find the run that began a run's chain, following the runs whose steps started each one.

    A run whose starter is no longer held begins what is left of its chain.
    """
    starter = aliased(Run)
    root = run_id
    for _ in range(MAX_CHAIN_WALK):
        found = await session.execute(
            sa.select(starter.id)
            .join(Run, Run.triggered_by_id == starter.id)
            .where(Run.id == root, Run.triggered_by_kind == TriggerKind.PIPELINE)
        )
        parent = found.scalar_one_or_none()
        if parent is None:
            return root
        root = parent
    return root


class StorageMeter:
    """Counts one attempt's writes against its run's quota, reserving a grant at a time.

    What is reserved and not yet written is held as credit and handed back by :meth:`settle`.
    The first write it refuses is kept in :attr:`refusal`, and every write after it is refused
    too, since the step it belongs to has failed.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession], run_id: UUID, quota: int) -> None:
        """Bind the meter to the run it counts for and the quota that run's chain is held to."""
        self._sessions = sessions
        self.run_id = run_id
        self.quota = quota
        self._root: UUID | None = None
        self._credit = 0
        self._lock = asyncio.Lock()
        self.refusal: Failure | None = None

    async def take(self, size: int) -> None:
        """Count ``size`` more bytes as written, or raise the quota's refusal without counting them."""
        if size <= 0:
            return
        async with self._lock:
            if self.refusal is not None:
                raise _raised(self.refusal)
            if size <= self._credit:
                self._credit -= size
                return
            needed = size - self._credit
            granted = await self._reserve(max(needed, GRANT))
            if not granted and needed < GRANT:
                granted = await self._reserve(needed)
            if not granted:
                self.refusal = await self._refused(size)
                raise _raised(self.refusal)
            self._credit += granted - size

    async def settle(self) -> None:
        """Hand back what was reserved and not written, so the counts say what was stored."""
        async with self._lock:
            unused, self._credit = self._credit, 0
        if unused:
            try:
                await self._change(-unused, root=await self._root_id())
            except Exception as error:
                _logger.warning(
                    "unwritten storage credit was not handed back", run_id=str(self.run_id), error=str(error)
                )

    async def _root_id(self) -> UUID:
        """The run whose row counts this run's chain, read once."""
        if self._root is None:
            async with session_scope(self._sessions) as session:
                self._root = await chain_root(session, self.run_id)
        return self._root

    async def _reserve(self, amount: int) -> int:
        """Add to the chain's count if it stays within the quota, and say how much was added."""
        while True:
            root = await self._root_id()
            async with session_scope(self._sessions) as session:
                counted = await session.execute(
                    sa.update(Run)
                    .where(Run.id == root, Run.chain_stored_bytes + amount <= self.quota)
                    .values(_added(amount, own=root == self.run_id))
                    .execution_options(synchronize_session=False)
                )
                added = _rowcount(counted) == 1
                gone = not added and root != self.run_id and await session.get(Run, root) is None
            if added:
                break
            if not gone:
                return 0
            # The run that began the chain was pruned while this one ran; what is left of the chain counts.
            self._root = None
        if root != self.run_id:
            await self._change(amount, root=None)
        return amount

    async def _change(self, amount: int, *, root: UUID | None) -> None:
        """Move the counts by ``amount`` with no condition: the chain's, when given a root, then the run's own."""
        if root is not None:
            async with session_scope(self._sessions) as session:
                await session.execute(
                    sa.update(Run)
                    .where(Run.id == root)
                    .values(_added(amount, own=root == self.run_id))
                    .execution_options(synchronize_session=False)
                )
            if root == self.run_id:
                return
        async with session_scope(self._sessions) as session:
            await session.execute(
                sa.update(Run)
                .where(Run.id == self.run_id)
                .values({Run.stored_bytes: Run.stored_bytes + amount})
                .execution_options(synchronize_session=False)
            )

    async def _refused(self, size: int) -> Failure:
        """The refusal for a write of ``size`` bytes, naming what the chain holds already."""
        root = await self._root_id()
        async with session_scope(self._sessions) as session:
            held = await session.execute(sa.select(Run.chain_stored_bytes).where(Run.id == root))
        return Failure.rejected(
            STORAGE_QUOTA,
            run=str(root),
            stored_bytes=held.scalar_one_or_none() or 0,
            size_bytes=size,
            quota=format_size(self.quota),
        )


def _added(amount: int, *, own: bool) -> dict[Any, Any]:
    """The SET of a change to the chain's count, and to the run's own when the run began the chain."""
    values: dict[Any, Any] = {Run.chain_stored_bytes: Run.chain_stored_bytes + amount}
    if own:
        values[Run.stored_bytes] = Run.stored_bytes + amount
    return values


def _rowcount(result: object) -> int:
    """How many rows an UPDATE matched."""
    return int(getattr(result, "rowcount", 0))


def _raised(refusal: Failure) -> BlockFailure:
    """The refusal as a block sees it, raised out of the write that crossed the quota."""
    return BlockFailure(STORAGE_QUOTA, error_class=ErrorClass.REJECTED, **refusal.params)
