"""Polled sources: a worker leases what is due, and each object a storage source finds becomes one run."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import InputOutcome, SourceState
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
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
    assert row.cursor == {"modified_at": (base + timedelta(minutes=2)).isoformat(), "uri": f"file://{inbox}/b.csv"}
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
