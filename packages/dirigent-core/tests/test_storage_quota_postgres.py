"""The run-wide storage quota on a real PostgreSQL, where workers really do write at once."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.quota import StorageMeter
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Base, Run, StepAttempt
from dirigent_core.plugins import PluginHost
from dirigent_plugin import BlockFailure
from engineblocks import EngineTestPlugin

pytestmark = pytest.mark.postgres

QUOTA = 10 * 1024

CAPTURE = 1024

#: The code a step the quota refused fails with.
REFUSED = "run.storage_quota"


@pytest.fixture
def quota_settings(postgres_url: str, tmp_path: Path) -> Settings:
    """Settings pointed at the container, with a quota a test can fill."""
    return Settings(
        database_url=postgres_url,
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        run_storage_quota=QUOTA,
        inline_artifact_max=CAPTURE,
    )


@pytest.fixture
def quota_services(quota_settings: Settings) -> EngineServices:
    """Engine services carrying the test blocks."""
    return EngineServices.build(quota_settings, PluginHost({"engine-tests": EngineTestPlugin().contribute()}))


@pytest.fixture
async def quota_engine(quota_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A clean schema per test."""
    engine = create_engine(quota_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def quota_sessions(quota_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory every worker in a test shares."""
    return create_session_factory(quota_engine)


async def start(sessions: async_sessionmaker[AsyncSession], services: EngineServices, step: StepDefinition) -> Run:
    """Save a one-step pipeline and create a run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, PipelineDefinition(code="captures", steps={"capture": step}))
        run = await create_run(session, services, version)
    assert run is not None
    return run


async def work(sessions: async_sessionmaker[AsyncSession], services: EngineServices, workers: int) -> None:
    """Run every due unit on several workers at once, until none is left."""

    async def worker(name: str) -> None:
        engine = Engine(sessions, services, owner=name)
        while (unit := await engine.claim()) is not None:
            await engine.run_unit(unit)

    await asyncio.gather(*(worker(f"worker-{index}") for index in range(workers)))


async def reload(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> Run:
    """Read a run back."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return run


def published(root: Path, run_id: UUID) -> list[Path]:
    """Every object published under a run's scratch."""
    return [path for path in (root / "runs" / str(run_id)).rglob("*") if path.is_file() and ".partial" not in path.name]


async def test_many_small_captures_fail_the_step_at_the_write_that_passes_the_quota(
    quota_sessions: Any, quota_services: EngineServices, tmp_path: Path
) -> None:
    run = await start(
        quota_sessions,
        quota_services,
        StepDefinition(block="test.capturing", config={"captures": 40, "size": CAPTURE, "piece": 256}),
    )
    await work(quota_sessions, quota_services, 1)

    settled = await reload(quota_sessions, run.id)
    async with quota_sessions() as session:
        attempt = (await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))).scalar_one()
    assert settled.status is RunStatus.FAILED
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.error_code == REFUSED
    assert len(published(tmp_path / "artifacts", run.id)) == QUOTA // CAPTURE
    assert settled.stored_bytes == settled.chain_stored_bytes == QUOTA


async def test_items_written_at_once_by_eight_workers_never_pass_the_quota_together(
    quota_sessions: Any, quota_services: EngineServices, tmp_path: Path
) -> None:
    run = await start(
        quota_sessions,
        quota_services,
        StepDefinition(
            block="test.capturing",
            for_each=[f"item-{index}" for index in range(16)],
            config={"captures": 3, "size": CAPTURE, "piece": 256},
        ),
    )
    await work(quota_sessions, quota_services, 8)

    settled = await reload(quota_sessions, run.id)
    async with quota_sessions() as session:
        codes = list(
            (await session.execute(sa.select(StepAttempt.error_code).where(StepAttempt.run_id == run.id))).scalars()
        )
    assert REFUSED in codes
    assert settled.stored_bytes == settled.chain_stored_bytes == QUOTA
    assert sum(path.stat().st_size for path in published(tmp_path / "artifacts", run.id)) <= QUOTA


async def test_meters_writing_at_once_on_separate_connections_cannot_both_pass_the_quota(
    quota_sessions: Any, quota_services: EngineServices
) -> None:
    run = await start(quota_sessions, quota_services, StepDefinition(block="test.echo"))
    meters = [StorageMeter(quota_sessions, run.id, QUOTA) for _ in range(12)]
    piece = QUOTA // 4

    outcomes = await asyncio.gather(*(meter.take(piece) for meter in meters), return_exceptions=True)
    for meter in meters:
        await meter.settle()

    assert sum(outcome is None for outcome in outcomes) == 4
    assert all(isinstance(outcome, BlockFailure) for outcome in outcomes if outcome is not None)
    settled = await reload(quota_sessions, run.id)
    assert settled.stored_bytes == settled.chain_stored_bytes == 4 * piece
