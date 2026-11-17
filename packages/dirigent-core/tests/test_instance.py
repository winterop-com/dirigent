"""Tests for the instance's own identity."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory
from dirigent_core.instance import instance_id, known_instance_id
from dirigent_core.models import Base, Instance


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on a fresh file-backed SQLite database."""
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


async def test_the_instance_id_is_made_once_and_then_always_the_same(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        assert await known_instance_id(session) is None

    first = await instance_id(sessions)
    assert await instance_id(sessions) == first

    async with sessions() as session:
        assert await known_instance_id(session) == first
        assert await session.scalar(sa.select(sa.func.count()).select_from(Instance)) == 1


async def test_two_callers_making_it_at_once_agree_on_one(sessions: async_sessionmaker[AsyncSession]) -> None:
    made = await asyncio.gather(*(instance_id(sessions) for _ in range(5)))

    assert len(set(made)) == 1
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(Instance)) == 1
