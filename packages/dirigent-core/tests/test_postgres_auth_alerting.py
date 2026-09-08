"""The account guard's concurrency lane: what only a real PostgreSQL can prove."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import UserRole
from dirigent_core.auth import LastAdmin, count_active_admins, create_user, deactivate_user, find_user, set_role
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base

pytestmark = pytest.mark.postgres

PASSWORD = "correct horse battery"


@pytest.fixture
def pg_settings(postgres_url: str, tmp_path: Any) -> Settings:
    """Settings pointed at the container."""
    return Settings(database_url=postgres_url, artifact_root=f"file://{tmp_path / 'artifacts'}")


@pytest.fixture
async def pg_engine(pg_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A clean schema per test, so contention tests cannot see each other's rows."""
    engine = create_engine(pg_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def pg_sessions(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory every caller in a test shares."""
    return create_session_factory(pg_engine)


async def two_admins(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Leave the instance with exactly the two accounts that keep each other's change legal."""
    async with session_scope(sessions) as session:
        await create_user(session, "ada", PASSWORD, role=UserRole.ADMIN)
        await create_user(session, "grace", PASSWORD, role=UserRole.ADMIN)


async def demote(sessions: async_sessionmaker[AsyncSession], username: str) -> bool:
    """Demote one account in its own transaction, reporting whether the guard allowed it."""
    try:
        async with session_scope(sessions) as session:
            user = await find_user(session, username)
            assert user is not None
            await set_role(session, user, UserRole.VIEWER)
    except LastAdmin:
        return False
    return True


async def deactivate(sessions: async_sessionmaker[AsyncSession], username: str) -> bool:
    """Deactivate one account in its own transaction, reporting whether the guard allowed it."""
    try:
        async with session_scope(sessions) as session:
            user = await find_user(session, username)
            assert user is not None
            await deactivate_user(session, user)
    except LastAdmin:
        return False
    return True


async def active_admins(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Count what is left able to manage the instance."""
    async with sessions() as session:
        return await count_active_admins(session)


async def test_two_admins_demoting_each_other_at_once_leave_one_behind(
    pg_sessions: async_sessionmaker[AsyncSession],
) -> None:
    await two_admins(pg_sessions)
    allowed = await asyncio.gather(demote(pg_sessions, "grace"), demote(pg_sessions, "ada"))
    assert sorted(allowed) == [False, True]
    assert await active_admins(pg_sessions) == 1


async def test_two_admins_deactivating_each_other_at_once_leave_one_behind(
    pg_sessions: async_sessionmaker[AsyncSession],
) -> None:
    await two_admins(pg_sessions)
    allowed = await asyncio.gather(deactivate(pg_sessions, "grace"), deactivate(pg_sessions, "ada"))
    assert sorted(allowed) == [False, True]
    assert await active_admins(pg_sessions) == 1
