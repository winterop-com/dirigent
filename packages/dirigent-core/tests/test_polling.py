"""Polled sources: a worker leases what is due, and each object a storage source finds becomes one run."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import InputOutcome, SourceState
from dirigent_client.schemas import PlanAction
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine.runs import create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Pipeline, Run, Source, SourceInput, StepAttempt
from dirigent_core.pipelines import apply_document
from dirigent_core.sources import polling
from dirigent_core.sources.rows import set_paused, state_of
from dirigent_core.sources.storage import StorageConfig, StorageSource

WORKER = "worker-under-test"


def landing(directory: Path, *, extra: str = "") -> str:
    """A pipeline that takes every CSV landing in a directory, and echoes where it is."""
    return f"""
format: dirigent/v1
kind: pipeline
code: landing
steps:
  arrived:
    source:
      kind: storage
      uri: file://{directory}/*.csv
      poll: 1m
{extra}
  note:
    block: test.echo
    depends_on: [arrived]
    config:
      value: ${{steps.arrived.output.uri}}
"""


def put(directory: Path, name: str, at: datetime) -> Path:
    """Write an object and date it."""
    path = directory / name
    path.write_text("id,value\n1,2\n")
    os.utime(path, (at.timestamp(), at.timestamp()))
    return path


def inbox_of(tmp_path: Path, name: str = "inbox") -> Path:
    """A directory under the instance's artifact root, which is where ``file://`` storage reads."""
    directory = tmp_path / "artifacts" / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def apply(sessions: async_sessionmaker[AsyncSession], services: EngineServices, text: str) -> None:
    """Apply a document in its own transaction."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(text))


async def the_source(sessions: async_sessionmaker[AsyncSession]) -> Source:
    """Read the one source row back."""
    async with sessions() as session:
        return (await session.execute(sa.select(Source))).scalar_one()


async def entered(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    """The URI each run was entered with, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt.output)
            .join(Run, Run.id == StepAttempt.run_id)
            .where(StepAttempt.step_name == "arrived")
            .order_by(Run.created_at, Run.id)
        )
        return [str(output["uri"]) for output in rows.scalars() if output is not None]


async def test_each_object_becomes_one_run_oldest_first_and_none_twice(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    put(inbox, "b.csv", base + timedelta(minutes=2))
    put(inbox, "a.csv", base + timedelta(minutes=1))
    (inbox / "skip.txt").write_text("not matched")
    await apply(sessions, services, landing(inbox))

    starting = await the_source(sessions)
    assert starting.next_poll_at is not None, "an applied polled source is due at once"
    assert state_of(starting, pipeline_active=True, unsettled=0, bound=None, is_polled=True) is SourceState.STARTING

    [outcome] = await polling.tick(sessions, services, owner=WORKER)
    assert len(outcome.runs) == 2
    assert await entered(sessions) == [f"file://{inbox}/a.csv", f"file://{inbox}/b.csv"]

    row = await the_source(sessions)
    assert row.lease_owner is None
    assert row.cursor == {
        "seen": {
            f"file://{inbox}/a.csv": (base + timedelta(minutes=1)).isoformat(),
            f"file://{inbox}/b.csv": (base + timedelta(minutes=2)).isoformat(),
        }
    }
    assert state_of(row, pipeline_active=True, unsettled=0, bound=None, is_polled=True) is SourceState.LISTENING

    assert await polling.tick(sessions, services, owner=WORKER) == [], "nothing is due until a cadence passes"
    put(inbox, "c.csv", base + timedelta(minutes=3))
    later = datetime.now(UTC) + timedelta(minutes=2)
    [again] = await polling.tick(sessions, services, owner=WORKER, now=later)
    assert len(again.runs) == 1
    assert (await entered(sessions))[-1] == f"file://{inbox}/c.csv"

    async with sessions() as session:
        journal = (await session.execute(sa.select(SourceInput).order_by(SourceInput.id))).scalars().all()
    assert [(entry.outcome, entry.label, entry.status) for entry in journal] == [
        (InputOutcome.ACCEPTED, f"file://{inbox}/a.csv", None),
        (InputOutcome.ACCEPTED, f"file://{inbox}/b.csv", None),
        (InputOutcome.ACCEPTED, f"file://{inbox}/c.csv", None),
    ]


async def test_an_object_that_lands_late_with_an_old_date_is_still_handed_over(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    base = datetime(2026, 1, 2, tzinfo=UTC)
    put(inbox, "today.csv", base)
    await apply(sessions, services, landing(inbox))
    await polling.tick(sessions, services, owner=WORKER)
    put(inbox, "yesterday.csv", base - timedelta(days=1))
    [late] = await polling.tick(sessions, services, owner=WORKER, now=datetime.now(UTC) + timedelta(minutes=2))
    assert len(late.runs) == 1, "a copy that kept its original date is new all the same"
    assert (await entered(sessions))[-1] == f"file://{inbox}/yesterday.csv"


@pytest.mark.parametrize(("rerun_changed", "runs"), [(False, 0), (True, 1)])
async def test_a_redated_object_runs_again_only_when_asked_and_a_removed_one_leaves_the_cursor(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    tmp_path: Path,
    rerun_changed: bool,
    runs: int,
) -> None:
    inbox = inbox_of(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    put(inbox, "a.csv", base)
    put(inbox, "b.csv", base)
    await apply(sessions, services, landing(inbox, extra=f"      rerun_changed: {str(rerun_changed).lower()}"))
    await polling.tick(sessions, services, owner=WORKER)
    put(inbox, "a.csv", base + timedelta(hours=1))
    (inbox / "b.csv").unlink()
    [again] = await polling.tick(sessions, services, owner=WORKER, now=datetime.now(UTC) + timedelta(minutes=2))
    assert len(again.runs) == runs
    stamp = base + timedelta(hours=1) if rerun_changed else base
    assert (await the_source(sessions)).cursor == {"seen": {f"file://{inbox}/a.csv": stamp.isoformat()}}


async def test_a_failed_poll_keeps_the_cursor_and_backs_off(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    await apply(sessions, services, landing(inbox_of(tmp_path)).replace("file://", "nowhere://"))
    [outcome] = await polling.tick(sessions, services, owner=WORKER)
    assert outcome.error is not None
    row = await the_source(sessions)
    assert (row.failures, row.cursor, row.lease_owner) == (1, None, None)
    assert row.last_error == outcome.error
    assert row.next_poll_at is not None
    assert row.next_poll_at - datetime.now(UTC) > timedelta(seconds=20), "it waits out the backoff"
    assert state_of(row, pipeline_active=True, unsettled=0, bound=None, is_polled=True) is SourceState.FAILING


async def test_a_paused_source_or_an_inactive_pipeline_is_not_polled(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    put(inbox, "a.csv", datetime(2026, 1, 1, tzinfo=UTC))
    await apply(sessions, services, landing(inbox))
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
        pipeline = await session.get(Pipeline, row.pipeline_id)
        assert pipeline is not None
        await set_paused(session, pipeline, row, paused=True)
    assert await polling.tick(sessions, services, owner=WORKER) == []
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
        pipeline = await session.get(Pipeline, row.pipeline_id)
        assert pipeline is not None
        await set_paused(session, pipeline, row, paused=False)
        pipeline.active = False
    assert await polling.tick(sessions, services, owner=WORKER) == []


async def test_a_paused_apply_inserts_a_polled_source_paused_and_only_a_resume_starts_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    put(inbox, "a.csv", datetime(2026, 1, 1, tzinfo=UTC))
    async with session_scope(sessions) as session:
        applied = await apply_document(session, services, load_text(landing(inbox)), paused=True)
    assert applied.sources.created == ["arrived"]
    assert applied.sources.paused == ["arrived"]

    row = await the_source(sessions)
    assert row.paused is True
    assert row.next_poll_at is not None, "it is due, and paused is all that holds it back"
    assert await polling.tick(sessions, services, owner=WORKER) == []
    assert await entered(sessions) == []

    async with session_scope(sessions) as session:
        held = (await session.execute(sa.select(Source))).scalar_one()
        pipeline = await session.get(Pipeline, held.pipeline_id)
        assert pipeline is not None
        await set_paused(session, pipeline, held, paused=False)
    [outcome] = await polling.tick(sessions, services, owner=WORKER)
    assert len(outcome.runs) == 1


async def test_a_paused_apply_never_changes_a_polled_source_the_instance_already_holds(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    await apply(sessions, services, landing(inbox))
    assert (await the_source(sessions)).paused is False

    async with session_scope(sessions) as session:
        redeclared = load_text(landing(inbox).replace("poll: 1m", "poll: 2m"))
        again = await apply_document(session, services, redeclared, paused=True)
    assert again.sources.updated == ["arrived"]
    assert again.sources.paused == []
    assert (await the_source(sessions)).paused is False, "a live source is not paused by the flag"

    async with session_scope(sessions) as session:
        held = (await session.execute(sa.select(Source))).scalar_one()
        pipeline = await session.get(Pipeline, held.pipeline_id)
        assert pipeline is not None
        await set_paused(session, pipeline, held, paused=True)
    await apply(sessions, services, landing(inbox))
    assert (await the_source(sessions)).paused is True, "a paused source is not resumed by leaving the flag off"


async def test_a_paused_apply_of_an_unchanged_document_inserts_a_missing_polled_source_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    text = landing(inbox_of(tmp_path))
    await apply(sessions, services, text)
    async with session_scope(sessions) as session:
        await session.execute(sa.delete(Source))

    async with session_scope(sessions) as session:
        applied = await apply_document(session, services, load_text(text), paused=True)
    assert applied.plan.action is PlanAction.UNCHANGED
    assert applied.sources.paused == ["arrived"]
    assert (await the_source(sessions)).paused is True


async def test_a_source_held_by_another_worker_is_left_alone_until_its_lease_runs_out(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    put(inbox, "a.csv", datetime(2026, 1, 1, tzinfo=UTC))
    await apply(sessions, services, landing(inbox))
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
        row.lease_owner = "another-worker"
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    assert await polling.tick(sessions, services, owner=WORKER) == []
    later = datetime.now(UTC) + timedelta(minutes=6)
    [outcome] = await polling.tick(sessions, services, owner=WORKER, now=later)
    assert len(outcome.runs) == 1


async def test_max_in_flight_bounds_how_many_inputs_one_poll_hands_over(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for minute, name in enumerate(["a.csv", "b.csv", "c.csv"]):
        put(inbox, name, base + timedelta(minutes=minute))
    await apply(sessions, services, landing(inbox, extra="      max_in_flight: 2"))
    [outcome] = await polling.tick(sessions, services, owner=WORKER)
    assert len(outcome.runs) == 2, "the third waits for a run to settle"
    later = datetime.now(UTC) + timedelta(minutes=2)
    assert await polling.tick(sessions, services, owner=WORKER, now=later) == [], "both runs are unsettled"


async def test_moving_the_location_resets_the_cursor(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path)
    put(inbox, "a.csv", datetime(2026, 1, 1, tzinfo=UTC))
    await apply(sessions, services, landing(inbox))
    await polling.tick(sessions, services, owner=WORKER)
    assert (await the_source(sessions)).cursor is not None
    elsewhere = inbox_of(tmp_path, "elsewhere")
    await apply(sessions, services, landing(elsewhere))
    row = await the_source(sessions)
    assert row.cursor is None
    assert row.next_poll_at is not None


def test_a_hand_run_names_the_object_and_is_dated_now() -> None:
    kind = StorageSource()
    config = StorageConfig(uri="s3://landing/in/")
    received = datetime(2026, 1, 1, tzinfo=UTC)
    made = kind.complete(config, {"uri": "s3://landing/in/a.csv"}, received_at=received)
    assert (made.uri, made.modified_at, made.received_at, made.size_bytes) == (
        "s3://landing/in/a.csv",
        received,
        received,
        0,
    )


async def test_a_source_looks_under_the_instance_root_it_names_as_artifacts(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    inbox = inbox_of(tmp_path, "landing")
    put(inbox, "a.csv", datetime(2026, 1, 1, tzinfo=UTC))
    await apply(sessions, services, landing(inbox).replace(f"file://{inbox}", "${artifacts}/landing"))
    [outcome] = await polling.tick(sessions, services, owner=WORKER)
    assert outcome.error is None
    assert len(outcome.runs) == 1


async def test_an_input_no_run_can_be_made_of_fails_the_poll_and_keeps_the_cursor(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox = inbox_of(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    put(inbox, "a.csv", base)
    put(inbox, "b.csv", base + timedelta(minutes=1))
    await apply(sessions, services, landing(inbox))
    made = 0

    async def refuse_the_second(*args: object, **kwargs: object) -> object:
        nonlocal made
        made += 1
        return None if made == 2 else await create_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(polling, "create_run", refuse_the_second)
    [outcome] = await polling.tick(sessions, services, owner=WORKER)
    assert outcome.runs == []
    assert outcome.error is not None
    row = await the_source(sessions)
    assert (row.cursor, row.failures, row.accepted) == (None, 1, 0), "nothing of the batch is kept"
    assert await entered(sessions) == []

    monkeypatch.undo()
    later = datetime.now(UTC) + timedelta(hours=1)
    [again] = await polling.tick(sessions, services, owner=WORKER, now=later)
    assert len(again.runs) == 2, "the same inputs are offered again"


async def test_skip_is_refused_beside_a_polled_source(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    text = landing(inbox_of(tmp_path)).replace("code: landing\n", "code: landing\nconcurrency: skip\n")
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(text), dry_run=True)
    assert [issue.code for issue in result.plan.issues] == ["source.replace_on_held"]
