"""The storage meter: grants, hand-backs, the chain a count belongs to, and writers that race."""

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import TriggerKind
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.quota import GRANT, StorageMeter, chain_root
from dirigent_core.engine.runs import Attribution, create_run, save_pipeline
from dirigent_core.messages import STORAGE_QUOTA
from dirigent_core.models import Run
from dirigent_core.storage import FileStorageBackend, Storage
from dirigent_plugin import BlockFailure

QUOTA = 10 * 1024


async def start(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    code: str,
    attribution: Attribution | None = None,
) -> Run:
    """Create one run of a one-step pipeline, nothing of it executed."""
    definition = PipelineDefinition(code=code, steps={"echo": StepDefinition(block="test.echo")})
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version, attribution=attribution)
    assert run is not None
    return run


async def counts(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> tuple[int, int]:
    """A run's own count and its chain's."""
    async with sessions() as session:
        row = (await session.execute(sa.select(Run.stored_bytes, Run.chain_stored_bytes).where(Run.id == run_id))).one()
        return row.stored_bytes, row.chain_stored_bytes


async def test_meters_of_one_run_writing_at_once_cannot_both_pass_the_quota(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await start(sessions, services, "contended")
    meters = [StorageMeter(sessions, run.id, QUOTA) for _ in range(8)]
    piece = QUOTA // 3

    outcomes = await asyncio.gather(*(meter.take(piece) for meter in meters), return_exceptions=True)
    for meter in meters:
        await meter.settle()

    assert sum(outcome is None for outcome in outcomes) == 3
    assert all(isinstance(outcome, BlockFailure) for outcome in outcomes if outcome is not None)
    assert await counts(sessions, run.id) == (3 * piece, 3 * piece)


async def test_a_meter_takes_a_grant_and_hands_back_what_it_did_not_write(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await start(sessions, services, "granted")
    meter = StorageMeter(sessions, run.id, 4 * GRANT)

    await meter.take(10)
    assert await counts(sessions, run.id) == (GRANT, GRANT)
    await meter.take(20)
    await meter.settle()
    assert await counts(sessions, run.id) == (30, 30)


async def test_a_meter_refuses_every_write_after_the_one_it_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    run = await start(sessions, services, "refused")
    meter = StorageMeter(sessions, run.id, QUOTA)

    with pytest.raises(BlockFailure) as refused:
        await meter.take(QUOTA + 1)
    with pytest.raises(BlockFailure):
        await meter.take(1)

    assert refused.value.code == STORAGE_QUOTA.code
    assert meter.refusal is not None
    assert meter.refusal.params == {"run": str(run.id), "stored_bytes": 0, "size_bytes": QUOTA + 1, "quota": "10kb"}
    assert await counts(sessions, run.id) == (0, 0)


async def test_a_chain_is_counted_on_the_run_that_began_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await start(sessions, services, "parent")
    child = await start(sessions, services, "child", Attribution(kind=TriggerKind.PIPELINE, id=parent.id))
    grandchild = await start(sessions, services, "grandchild", Attribution(kind=TriggerKind.PIPELINE, id=child.id))

    meter = StorageMeter(sessions, grandchild.id, QUOTA)
    await meter.take(100)
    await meter.settle()

    async with sessions() as session:
        assert await chain_root(session, grandchild.id) == parent.id
    assert await counts(sessions, grandchild.id) == (100, 0)
    assert await counts(sessions, child.id) == (0, 0)
    assert await counts(sessions, parent.id) == (0, 100)


async def test_a_chain_whose_first_run_is_gone_counts_on_what_is_left_of_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    parent = await start(sessions, services, "pruned-parent")
    child = await start(sessions, services, "orphan", Attribution(kind=TriggerKind.PIPELINE, id=parent.id))
    meter = StorageMeter(sessions, child.id, 4 * GRANT)
    await meter.take(1)
    async with session_scope(sessions) as session:
        await session.execute(sa.delete(Run).where(Run.id == parent.id))

    await meter.take(GRANT)
    await meter.settle()

    stored, _ = await counts(sessions, child.id)
    assert stored == GRANT + 1


async def test_a_metered_facade_counts_what_is_written_through_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    run = await start(sessions, services, "facade")
    root = f"{tmp_path}/objects"
    storage = Storage({"file": FileStorageBackend(root)}, f"file://{root}").bound_by(lambda _scheme, backend: backend)
    meter = StorageMeter(sessions, run.id, QUOTA)
    counted = storage.metered(meter)

    await counted.write_bytes(f"file://{root}/one", b"x" * 300)
    await storage.write_bytes(f"file://{root}/two", b"y" * 300)
    with pytest.raises(BlockFailure):
        await counted.write_bytes(f"file://{root}/three", b"z" * QUOTA)
    await meter.settle()

    assert await counts(sessions, run.id) == (300, 300)
    assert await storage.stat(f"file://{root}/three") is None
