"""The account guard's and the alert outcome's concurrency lane: what only a real PostgreSQL can prove."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import AlertEvent, NotificationEvent, RunStatus, UserRole
from dirigent_core.alerting import AlertRuleRequest, create_rule, raise_for_status
from dirigent_core.auth import LastAdmin, count_active_admins, create_user, deactivate_user, find_user, set_role
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Base, Run
from dirigent_core.plugins import PluginHost
from engineblocks import EngineTestPlugin

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


@pytest.fixture
def pg_services(pg_settings: Settings) -> EngineServices:
    """The engine's services against the container, with the test blocks installed."""
    return EngineServices.build(pg_settings, PluginHost({"engine-tests": EngineTestPlugin().contribute()}))


async def a_run(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> Run:
    """Create one more run of the same pipeline."""
    definition = PipelineDefinition(code="watched", steps={"only": StepDefinition(block="test.echo")})
    async with session_scope(sessions) as session:
        created = await create_run(session, services, await save_pipeline(session, definition))
    assert created is not None
    return created


async def settle(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, run: Run, status: RunStatus
) -> list[NotificationEvent]:
    """Settle a run in its own transaction, as the worker that finished it would, and name what it raised."""
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        stored.status = status
        return [notification.event for notification in await raise_for_status(session, services, stored, status)]


async def test_two_runs_recovering_at_once_raise_one_recovery(
    pg_sessions: async_sessionmaker[AsyncSession], pg_services: EngineServices
) -> None:
    """The second to settle reads the first's success, not the failure both of them followed."""
    async with session_scope(pg_sessions) as session:
        await create_rule(session, pg_services, AlertRuleRequest(code="all-clear", event=AlertEvent.RUN_RECOVERED))
    for _ in range(5):
        await settle(pg_sessions, pg_services, await a_run(pg_sessions, pg_services), RunStatus.FAILED)
        one, two = await a_run(pg_sessions, pg_services), await a_run(pg_sessions, pg_services)
        raised = await asyncio.gather(
            settle(pg_sessions, pg_services, one, RunStatus.SUCCEEDED),
            settle(pg_sessions, pg_services, two, RunStatus.SUCCEEDED),
        )
        assert sorted(raised) == [[], [NotificationEvent.RUN_RECOVERED]]
