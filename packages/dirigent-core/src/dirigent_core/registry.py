"""The worker registry read as routing data: who is alive, and what they carry."""

from collections.abc import Iterable
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import WorkerStatus
from dirigent_core.models import Worker, utcnow

STALE_AFTER = timedelta(minutes=2)
"""How long a registry row stands without a heartbeat before the worker is presumed gone."""


async def live_worker_tags(session: AsyncSession) -> set[str]:
    """Collect every tag carried by a worker that is still heartbeating."""
    rows = await session.execute(
        sa.select(Worker.tags).where(
            Worker.last_seen_at >= utcnow() - STALE_AFTER, Worker.status != WorkerStatus.STOPPED
        )
    )
    return {str(tag) for row in rows.scalars() for tag in row}


async def unmet_worker_tags(session: AsyncSession, tags: Iterable[str]) -> list[str]:
    """Report which of ``tags`` no live worker carries, in the order they were declared."""
    wanted = list(dict.fromkeys(tags))
    if not wanted:
        return []
    carried = await live_worker_tags(session)
    return [tag for tag in wanted if tag not in carried]
