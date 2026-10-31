"""The run-wide storage quota on SQLite: what a run writes is counted, and the write past it fails the step."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import JsonValue, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus, TriggerKind
from dirigent_core.artifacts import canonical_json
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import Attribution, create_run, save_pipeline
from dirigent_core.models import Run, StepAttempt

#: Small enough that a test fills it with a few kilobytes of captures.
QUOTA = 10 * 1024

#: One capture's worth: the quota holds exactly ten of them.
CAPTURE = 1024

#: The code a step the quota refused fails with.
REFUSED = "run.storage_quota"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Instance settings with a quota a test can fill, and an output past a kilobyte stored."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        lease=timedelta(seconds=30),
        run_storage_quota=QUOTA,
        inline_artifact_max=CAPTURE,
    )


async def start(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    definition: PipelineDefinition,
    attribution: Attribution | None = None,
) -> Run:
    """Save a pipeline version and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version, attribution=attribution)
    assert run is not None
    return run


async def drain(engine: Engine) -> None:
    """Claim and run every due unit until nothing is left."""
    moment = datetime.now(UTC)
    for _ in range(200):
        unit = await engine.claim(now=moment)
        if unit is None:
            return
        await engine.run_unit(unit, now=moment)
        moment += timedelta(seconds=5)
    raise AssertionError("the run never settled")


async def reload(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> Run:
    """Read a run back."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return run


async def only_attempt(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> StepAttempt:
    """Read the one attempt a single-step run has."""
    async with sessions() as session:
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run_id))
        return rows.scalar_one()


def stored_objects(root: Path, run_id: UUID) -> list[Path]:
    """Every object published under a run's scratch, leaving out a write that never finished."""
    scratch = root / "runs" / str(run_id)
    return sorted(path for path in scratch.rglob("*") if path.is_file() and not path.name.endswith(".partial"))


def capturing(code: str, **config: Any) -> PipelineDefinition:
    """A one-step pipeline whose step captures streams in small writes."""
    return PipelineDefinition(code=code, steps={"capture": StepDefinition(block="test.capturing", config=config)})


async def test_many_small_captures_fail_the_step_at_the_write_that_passes_the_quota(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, engine: Engine, tmp_path: Path
) -> None:
    run = await start(sessions, services, capturing("many-captures", captures=40, size=CAPTURE, piece=256))
    await drain(engine)

    settled = await reload(sessions, run.id)
    attempt = await only_attempt(sessions, run.id)
    assert settled.status is RunStatus.FAILED
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.error_code == REFUSED
    assert attempt.error_params == {
        "run": str(run.id),
        "stored_bytes": QUOTA,
        "size_bytes": 256,
        "quota": "10kb",
    }
    published = stored_objects(tmp_path / "artifacts", run.id)
    assert len(published) == QUOTA // CAPTURE
    assert sum(path.stat().st_size for path in published) == QUOTA
    assert settled.stored_bytes == QUOTA
    assert settled.chain_stored_bytes == QUOTA


async def test_a_block_that_catches_the_refusal_still_fails_its_step(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, engine: Engine
) -> None:
    run = await start(sessions, services, capturing("swallowed", captures=40, size=CAPTURE, swallow=True))
    await drain(engine)

    attempt = await only_attempt(sessions, run.id)
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.error_code == REFUSED


async def test_writes_under_the_quota_are_counted_exactly_once_the_step_settles(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, engine: Engine
) -> None:
    run = await start(sessions, services, capturing("under", captures=3, size=CAPTURE, piece=100))
    await drain(engine)

    settled = await reload(sessions, run.id)
    assert settled.status is RunStatus.SUCCEEDED
    assert settled.stored_bytes == 3 * CAPTURE
    assert settled.chain_stored_bytes == 3 * CAPTURE


async def test_an_output_too_large_to_inline_counts_and_one_past_the_quota_fails_its_step(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, engine: Engine
) -> None:
    fits = "a" * (services.settings.inline_artifact_max + 1)
    definition = PipelineDefinition(
        code="stored-output", steps={"echo": StepDefinition(block="test.echo", config={"value": fits})}
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    settled = await reload(sessions, run.id)
    assert settled.status is RunStatus.SUCCEEDED
    assert settled.stored_bytes == len(canonical_json((await only_attempt(sessions, run.id)).output))

    too_big = "b" * (QUOTA + 1)
    definition = PipelineDefinition(
        code="past-quota", steps={"echo": StepDefinition(block="test.echo", config={"value": too_big})}
    )
    refused = await start(sessions, services, definition)
    await drain(engine)
    attempt = await only_attempt(sessions, refused.id)
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.error_code == REFUSED
    assert (await reload(sessions, refused.id)).stored_bytes == 0


async def test_a_run_started_by_another_spends_from_the_quota_of_the_run_that_began_the_chain(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, engine: Engine
) -> None:
    parent = await start(sessions, services, capturing("parent", captures=0))
    await drain(engine)
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Run).where(Run.id == parent.id).values(chain_stored_bytes=QUOTA - CAPTURE))
    child = await start(
        sessions,
        services,
        capturing("child", captures=3, size=CAPTURE),
        attribution=Attribution(kind=TriggerKind.PIPELINE, id=parent.id, label="a step of the parent"),
    )
    await drain(engine)

    attempt = await only_attempt(sessions, child.id)
    assert attempt.error_code == REFUSED
    assert attempt.error_params is not None
    assert attempt.error_params["run"] == str(parent.id)
    assert (await reload(sessions, child.id)).stored_bytes == CAPTURE
    assert (await reload(sessions, child.id)).chain_stored_bytes == 0
    assert (await reload(sessions, parent.id)).chain_stored_bytes == QUOTA


async def test_items_written_at_once_by_several_workers_never_pass_the_quota_together(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    items: list[JsonValue] = [f"item-{index}" for index in range(8)]
    definition = PipelineDefinition(
        code="fanned-captures",
        steps={
            "capture": StepDefinition(
                block="test.capturing", for_each=items, config={"captures": 3, "size": CAPTURE, "piece": 256}
            )
        },
    )
    run = await start(sessions, services, definition)

    async def worker(name: str) -> None:
        engine = Engine(sessions, services, owner=name)
        while (unit := await engine.claim()) is not None:
            await engine.run_unit(unit)

    await asyncio.gather(*(worker(f"worker-{index}") for index in range(4)))

    settled = await reload(sessions, run.id)
    async with sessions() as session:
        rows = await session.execute(sa.select(StepAttempt.error_code).where(StepAttempt.run_id == run.id))
        codes = list(rows.scalars())
    assert REFUSED in codes
    assert settled.chain_stored_bytes == settled.stored_bytes == QUOTA
    assert sum(path.stat().st_size for path in stored_objects(tmp_path / "artifacts", run.id)) <= QUOTA
