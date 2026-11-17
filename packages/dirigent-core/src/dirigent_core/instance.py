"""This instance's own identity: the one id it marks what it leaves outside its database with.

A container or a compose stack a step creates lives on a Docker daemon other instances may
share. The id written onto it is what lets this instance's reaper tell its own leftovers from
another instance's live work.
"""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_core.database import session_scope
from dirigent_core.models import Instance

__all__ = ["instance_id", "known_instance_id"]


async def known_instance_id(session: AsyncSession) -> UUID | None:
    """The instance's id, or None where none has been made yet."""
    return await session.scalar(sa.select(Instance.id))


async def instance_id(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    """The instance's id, made on first use; two processes making it at once agree on one."""
    async with session_scope(sessions) as session:
        found = await known_instance_id(session)
    if found is not None:
        return found
    try:
        async with session_scope(sessions) as session:
            made = Instance()
            session.add(made)
            await session.flush()
            return made.id
    except IntegrityError:
        async with session_scope(sessions) as session:
            found = await known_instance_id(session)
        assert found is not None
        return found
