"""What a retention sweep deletes, what it leaves, and what it refuses to orphan."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, LogLevel, RunStatus, TriggerKind
from dirigent_core import retention
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import create_run, retry_step, save_pipeline
from dirigent_core.models import LogEntry, Pipeline, PipelineVersion, Run, StepAttempt
from dirigent_core.storage import Storage, build_storage

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

#: Long enough that nothing a test writes is old enough to go.
FOREVER = timedelta(days=3650)


async def a_run(session: AsyncSession, *, finished_at: datetime | None, age: timedelta | None = None) -> Run:
    """Store one run of its own pipeline, settled at the moment the test names."""
    pipeline = Pipeline(id=uuid4(), code=f"p-{uuid4().hex[:8]}")
    version = PipelineVersion(
        id=uuid4(),
        pipeline_id=pipeline.id,
        version=1,
        document={"kind": "pipeline"},
        digest=uuid4().hex,
    )
    run = Run(
        id=uuid4(),
        pipeline_id=pipeline.id,
        pipeline_version_id=version.id,
        status=RunStatus.SUCCEEDED if finished_at else RunStatus.RUNNING,
        params={},
        triggered_by_kind=TriggerKind.ADHOC,
        triggered_by_label="a test",
        started_at=finished_at,
        finished_at=finished_at,
    )
    session.add_all([pipeline, version, run])
    await session.flush()
    if age is not None:
        await session.execute(sa.update(Run).where(Run.id == run.id).values(finished_at=NOW - age))
    return run


async def a_log(session: AsyncSession, run: Run, *, age: timedelta) -> None:
    """Store one log line against a run, logged however long ago the test names."""
    entry = LogEntry(run_id=run.id, level=LogLevel.INFO, message="something happened")
    session.add(entry)
    await session.flush()
    await session.execute(sa.update(LogEntry).where(LogEntry.id == entry.id).values(created_at=NOW - age))


async def counted(session: AsyncSession, model: type[Run] | type[LogEntry] | type[StepAttempt]) -> int:
    """Count what is left of one table."""
    return int((await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one())


@pytest.fixture
async def session(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One session per test, committed the way a sweep's caller commits it."""
    async with session_scope(sessions) as opened:
        yield opened


async def test_a_run_older_than_its_age_is_deleted(session: AsyncSession) -> None:
    await a_run(session, finished_at=NOW, age=timedelta(days=40))
    kept = await a_run(session, finished_at=NOW, age=timedelta(days=2))

    swept = await retention.sweep(session, retention.Policy(runs=timedelta(days=30)), now=NOW)

    assert swept.counts == {"runs": 1}
    left = list((await session.execute(sa.select(Run.id))).scalars())
    assert left == [kept.id]


async def test_an_unfinished_run_is_never_pruned(session: AsyncSession) -> None:
    """An unfinished run is either still running or the evidence of something that went wrong."""
    await a_run(session, finished_at=None)

    swept = await retention.sweep(session, retention.Policy(runs=timedelta(seconds=0)), now=NOW)

    assert swept.counts == {}
    assert await counted(session, Run) == 1


async def test_pruning_a_run_takes_what_the_database_cascades_from_it(session: AsyncSession) -> None:
    """A run's logs go with it, so a short log age is a trim rather than the only sweep."""
    run = await a_run(session, finished_at=NOW, age=timedelta(days=40))
    await a_log(session, run, age=timedelta(seconds=1))

    await retention.sweep(session, retention.Policy(runs=timedelta(days=30)), now=NOW)

    assert await counted(session, Run) == 0
    assert await counted(session, LogEntry) == 0, "a log entry outlived the run it belongs to"


async def test_a_log_entry_is_pruned_on_its_own_age(session: AsyncSession) -> None:
    """Logs are the bulk of it and are worth losing first, while their run is still kept."""
    run = await a_run(session, finished_at=NOW, age=timedelta(days=2))
    await a_log(session, run, age=timedelta(days=20))
    await a_log(session, run, age=timedelta(hours=1))

    swept = await retention.sweep(session, retention.Policy(logs=timedelta(days=7)), now=NOW)

    assert swept.counts == {"logs": 1}
    assert await counted(session, Run) == 1
    assert await counted(session, LogEntry) == 1


async def test_a_family_with_no_age_is_never_pruned(session: AsyncSession) -> None:
    """A prune deletes what it was asked to delete and never guesses at an age."""
    run = await a_run(session, finished_at=NOW, age=timedelta(days=4000))
    await a_log(session, run, age=timedelta(days=4000))

    swept = await retention.sweep(session, retention.Policy(), now=NOW)

    assert swept.counts == {}
    assert await counted(session, Run) == 1
    assert await counted(session, LogEntry) == 1


async def test_a_sweep_deletes_no_more_than_its_batch(session: AsyncSession) -> None:
    """One transaction never holds locks over a year's backlog."""
    for _ in range(5):
        await a_run(session, finished_at=NOW, age=timedelta(days=40))

    swept = await retention.sweep(session, retention.Policy(runs=timedelta(days=30)), now=NOW, limit=2)

    assert swept.counts == {"runs": 2}
    assert await counted(session, Run) == 3


async def test_counted_reports_what_would_go_without_deleting_it(session: AsyncSession) -> None:
    await a_run(session, finished_at=NOW, age=timedelta(days=40))

    counts = await retention.counted(session, retention.Policy(runs=timedelta(days=30)), now=NOW)

    assert counts == {"runs": 1}
    assert await counted(session, Run) == 1, "a dry run deleted something"


async def test_a_pruned_runs_artifacts_are_deleted_from_storage(
    session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    """The bytes go with the rows, or the prune has freed no space at all."""
    storage = build_storage(settings.artifact_root, [])
    old = await a_run(session, finished_at=NOW, age=timedelta(days=40))
    young = await a_run(session, finished_at=NOW, age=timedelta(days=1))
    for run in (old, young):
        await storage.write_bytes(f"{storage.scratch_for(run.id)}/outputs/one.json", b"{}")

    swept = await retention.sweep(session, retention.Policy(runs=timedelta(days=30)), storage=storage, now=NOW)

    assert swept.scratch_deleted == 1
    assert not await _exists(storage, old.id), "the pruned run's artifacts are still there"
    assert await _exists(storage, young.id), "and the kept run's are gone"


async def test_a_run_whose_artifacts_cannot_be_deleted_keeps_its_rows(
    session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rows deleted before their bytes leaves a prefix nothing points at and nothing finds."""
    storage = build_storage(settings.artifact_root, [])
    run = await a_run(session, finished_at=NOW, age=timedelta(days=40))
    await storage.write_bytes(f"{storage.scratch_for(run.id)}/outputs/one.json", b"{}")

    async def refuse(_uri: str) -> int:
        raise OSError("the volume is read-only")

    monkeypatch.setattr(storage, "delete_prefix", refuse)
    swept = await retention.sweep(session, retention.Policy(runs=timedelta(days=30)), storage=storage, now=NOW)

    assert swept.counts == {}
    assert swept.scratch_failed == 1
    assert await counted(session, Run) == 1, "the row went while its bytes stayed"


async def test_a_run_retried_while_its_artifacts_are_cleared_keeps_its_rows(
    session: AsyncSession, settings: Settings, services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage is cleared before the rows go, and a retry in that window reopens the run."""
    storage = build_storage(settings.artifact_root, [])
    definition = PipelineDefinition(code="reopened", steps={"only": StepDefinition(block="test.echo")})
    version = await save_pipeline(session, definition)
    run = await create_run(session, services, version)
    assert run is not None
    await session.execute(
        sa.update(StepAttempt)
        .where(StepAttempt.run_id == run.id)
        .values(status=AttemptStatus.FAILED, finished_at=NOW - timedelta(days=40))
    )
    await session.execute(
        sa.update(Run).where(Run.id == run.id).values(status=RunStatus.FAILED, finished_at=NOW - timedelta(days=40))
    )
    await session.refresh(run)
    await storage.write_bytes(f"{storage.scratch_for(run.id)}/outputs/one.json", b"{}")

    async def retry_while_clearing(_uri: str) -> int:
        """Reopen the run the sweep has already selected, the way an operator would."""
        reopened = await session.get(Run, run.id)
        assert reopened is not None
        await retry_step(session, services, reopened, "only", idempotency_key="mid-sweep")
        return 1

    monkeypatch.setattr(storage, "delete_prefix", retry_while_clearing)
    swept = await retention.sweep(session, retention.Policy(runs=timedelta(days=30)), storage=storage, now=NOW)

    assert swept.counts == {}
    assert await counted(session, Run) == 1, "a run reopened mid-sweep was deleted anyway"
    assert (await session.get(Run, run.id)) is not None


async def test_scratch_can_be_left_alone(session: AsyncSession, settings: Settings) -> None:
    """An instance whose artifacts are somebody else's to reap says so."""
    storage = build_storage(settings.artifact_root, [])
    run = await a_run(session, finished_at=NOW, age=timedelta(days=40))
    await storage.write_bytes(f"{storage.scratch_for(run.id)}/outputs/one.json", b"{}")

    policy = retention.Policy(runs=timedelta(days=30), scratch=False)
    swept = await retention.sweep(session, policy, storage=storage, now=NOW)

    assert swept.counts == {"runs": 1}
    assert swept.scratch_deleted == 0
    assert await _exists(storage, run.id)


def test_a_policy_reads_the_configured_ages(settings: Settings) -> None:
    configured = settings.model_copy(update={"retention_runs": timedelta(days=30), "retention_scratch": False})

    policy = retention.policy_from(configured)

    assert policy.runs == timedelta(days=30)
    assert policy.logs is None
    assert policy.scratch is False


def test_nothing_configured_is_reported_as_nothing_to_do(settings: Settings) -> None:
    """A sweep with no age would read every table to delete nothing."""
    assert not retention.configured(retention.policy_from(settings))
    assert retention.configured(retention.Policy(logs=FOREVER))


async def test_a_work_directory_goes_when_its_run_has_outlived_the_policy(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The scheduler's sweep cannot reach a worker's disk, so each worker sweeps its own."""
    old = await a_run(session, finished_at=NOW, age=timedelta(days=40))
    young = await a_run(session, finished_at=NOW, age=timedelta(days=2))
    pruned = uuid4()
    root = tmp_path / "work"
    for run_id in (old.id, young.id, pruned):
        (root / "runs" / str(run_id) / "checkout").mkdir(parents=True)
    (root / "runs" / "not-a-run").mkdir()

    swept = await retention.sweep_work(session, str(root), retention.Policy(runs=timedelta(days=30)), now=NOW)

    assert swept == 2, "the outlived run and the one whose row is already gone"
    assert not (root / "runs" / str(old.id)).exists()
    assert not (root / "runs" / str(pruned)).exists()
    assert (root / "runs" / str(young.id)).exists()
    assert (root / "runs" / "not-a-run").exists(), "a directory no run made is left alone"


async def test_no_run_age_sweeps_no_work_directory(session: AsyncSession, tmp_path: Path) -> None:
    """The work directory follows the same policy as the scratch it sits beside."""
    run = await a_run(session, finished_at=NOW, age=timedelta(days=40))
    root = tmp_path / "work"
    (root / "runs" / str(run.id)).mkdir(parents=True)

    assert await retention.sweep_work(session, str(root), retention.Policy(), now=NOW) == 0
    assert await retention.sweep_work(session, str(root), retention.Policy(runs=FOREVER, scratch=False), now=NOW) == 0
    assert (root / "runs" / str(run.id)).exists()


async def _exists(storage: Storage, run_id: UUID) -> bool:
    """Report whether a run's scratch prefix still holds anything."""
    return bool([found async for found in storage.list(storage.scratch_for(run_id))])
