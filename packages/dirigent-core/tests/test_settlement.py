"""A sensor's batch is settled with its broker only once the engine has stored it.

``test.broker`` drains an in-process queue and answers with :class:`Taken`: every way the
success can be refused or lost after the poke leaves the batch on the queue, and the retry takes
the same messages again.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, RetryPolicy, StepDefinition
from dirigent_core.engine.executor import Engine, UnitRaised
from dirigent_core.engine.recovery import sweep_leases
from dirigent_core.engine.runs import cancel_run, create_run, retry_step, save_pipeline
from dirigent_core.models import Run, Source, StepAttempt, utcnow
from dirigent_core.pipelines import apply_document
from dirigent_core.sources import polling
from engineblocks import BrokerSensor

#: Retries in these tests are immediate, so a drained run does not wait on wall-clock time.
FAST_RETRY = RetryPolicy(max_attempts=3, backoff=timedelta(0), jitter=0.0)

#: No retry at all, so a failure stays failed for a manual retry to pick up.
NO_RETRY = RetryPolicy(max_attempts=1, backoff=timedelta(0), jitter=0.0)

#: The inline size and the run's quota: an output padded past the quota is refused.
INLINE = 1024
QUOTA = 4 * 1024

WORKER = "worker-under-test"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Instance settings with a quota one padded output can pass."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        lease=timedelta(seconds=30),
        run_storage_quota=QUOTA,
        inline_artifact_max=INLINE,
    )


def consuming(retry: RetryPolicy = FAST_RETRY, **config: Any) -> PipelineDefinition:
    """A one-step pipeline that takes a batch off the queue."""
    return PipelineDefinition(
        code="consuming",
        steps={"take": StepDefinition(block="test.broker", config=config, poll=timedelta(seconds=1), retry=retry)},
    )


async def start(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, definition: PipelineDefinition
) -> Run:
    """Save a pipeline version and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return run


async def drain(engine: Engine, *, moment: datetime | None = None) -> None:
    """Claim and run every due unit, advancing a virtual clock so waits and retries come due."""
    now = moment or datetime.now(UTC)
    for _ in range(100):
        unit = await engine.claim(now=now)
        if unit is None:
            return
        await engine.run_unit(unit, now=now)
        now += timedelta(seconds=2)
    raise AssertionError("the run never settled")


async def attempts_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[StepAttempt]:
    """Every attempt of a run, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run_id).order_by(StepAttempt.attempt)
        )
        return list(rows.scalars())


def queued(*messages: int) -> None:
    """Put messages on the default queue."""
    BrokerSensor.queues["default"] = list(messages)


def settled() -> list[tuple[str, list[int]]]:
    """How the default queue's batches were answered, in order."""
    return BrokerSensor.settled.get("default", [])


async def test_a_stored_success_is_acked_exactly_once(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2, 3)
    run = await start(sessions, services, consuming())

    await drain(engine)

    [attempt] = await attempts_of(sessions, run.id)
    assert attempt.status is AttemptStatus.SUCCEEDED
    assert attempt.output is not None and attempt.output["messages"] == [1, 2]
    assert settled() == [("ack", [1, 2])]
    assert BrokerSensor.queues["default"] == [3]


async def test_an_output_too_deep_to_store_leaves_the_batch_for_a_retry(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2, 3)
    run = await start(sessions, services, consuming(deep_times=1))
    await drain(engine)

    [failed] = await attempts_of(sessions, run.id)
    assert failed.status is AttemptStatus.FAILED
    assert settled() == [("nack", [1, 2])]

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await retry_step(session, services, stored, "take", idempotency_key="again")
    await drain(engine)

    assert settled() == [("nack", [1, 2]), ("ack", [1, 2])], "the retry took the batch the refusal handed back"
    assert BrokerSensor.queues["default"] == [3]


async def test_an_output_the_quota_refuses_leaves_the_batch_on_the_queue(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2, 3)
    run = await start(sessions, services, consuming(pad=QUOTA * 2))

    await drain(engine)

    attempts = await attempts_of(sessions, run.id)
    assert {attempt.status for attempt in attempts} == {AttemptStatus.FAILED}
    assert attempts[0].error_code == "run.storage_quota"
    assert settled() == [("nack", [1, 2])] * len(attempts), "every attempt took the same batch and handed it back"
    assert BrokerSensor.queues["default"] == [1, 2, 3]


async def test_a_lost_lease_leaves_the_batch_for_the_attempt_that_took_over(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2, 3)
    run = await start(sessions, services, consuming())
    unit = await engine.claim()
    assert unit is not None
    async with session_scope(sessions) as session:
        await sweep_leases(session, now=utcnow() + services.settings.lease + timedelta(minutes=1))

    await engine.run_unit(unit)

    assert settled() == [("nack", [1, 2])]
    await drain(engine, moment=utcnow() + services.settings.lease + timedelta(minutes=2))
    [attempt] = await attempts_of(sessions, run.id)
    assert attempt.status is AttemptStatus.SUCCEEDED
    assert settled() == [("nack", [1, 2]), ("ack", [1, 2])]


async def test_a_run_cancelled_under_the_poke_leaves_the_batch_on_the_queue(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2)
    run = await start(sessions, services, consuming())
    unit = await engine.claim()
    assert unit is not None
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)

    await engine.run_unit(unit)

    assert settled() == [("nack", [1, 2])]
    assert BrokerSensor.queues["default"] == [1, 2]


async def test_an_outcome_that_failed_to_commit_leaves_the_batch_on_the_queue(
    engine: Engine,
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued(1, 2)
    await start(sessions, services, consuming())

    async def refused(self: Engine, *args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(Engine, "_record_once", refused)
    unit = await engine.claim()
    assert unit is not None

    with pytest.raises(UnitRaised):
        await engine.run_unit(unit)

    assert settled() == [("nack", [1, 2])]
    assert BrokerSensor.queues["default"] == [1, 2]


async def test_a_settle_that_fails_after_the_commit_leaves_the_success_standing(
    engine: Engine,
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued(1, 2)
    run = await start(sessions, services, consuming())

    async def unreachable(self: object) -> None:
        raise ConnectionError("the broker went away")

    monkeypatch.setattr("engineblocks.BrokerSettlement.settle", unreachable)

    await drain(engine)

    [attempt] = await attempts_of(sessions, run.id)
    assert attempt.status is AttemptStatus.SUCCEEDED


async def test_an_automatic_retry_reads_from_the_cursor_the_failed_attempt_stood_at(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2)
    run = await start(sessions, services, consuming(parks=1, fail_times=1))

    await drain(engine)

    attempts = await attempts_of(sessions, run.id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED]
    assert BrokerSensor.cursors["default"] == [None, {"parked": 1}, {"parked": 1}], (
        "the retry read on from where the failed attempt stood"
    )
    assert settled() == [("ack", [1, 2])]


async def test_a_manual_retry_reads_from_the_cursor_the_failed_attempt_stood_at(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2)
    run = await start(sessions, services, consuming(NO_RETRY, parks=1, deep_times=1))
    await drain(engine)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None and stored.status is RunStatus.FAILED
        retried = await retry_step(session, services, stored, "take", idempotency_key="again")

    assert retried.poke_cursor == {"parked": 1}
    await drain(engine)
    assert BrokerSensor.cursors["default"][-1] == {"parked": 1}
    assert settled() == [("nack", [1, 2]), ("ack", [1, 2])]


# -- a sensor source --------------------------------------------------------------

SOURCED = """
format: dirigent/v1
kind: pipeline
code: sourced
steps:
  take:
    source:
      kind: sensor
      block: test.broker
      config: {}
      poll: 1m
  note:
    block: test.echo
    depends_on: [take]
"""


async def test_a_source_acks_a_batch_once_its_run_is_committed(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    queued(1, 2, 3)
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(SOURCED))

    [polled] = await polling.tick(sessions, services, owner=WORKER)

    assert len(polled.runs) == 1
    assert settled() == [("ack", [1, 2])]


async def test_a_source_whose_run_was_refused_hands_the_batch_back(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued(1, 2, 3)
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(SOURCED))

    async def refused(*args: Any, **kwargs: Any) -> UUID:
        raise polling.InputRefused("no run can be made")

    monkeypatch.setattr(polling, "enter_input", refused)
    [polled] = await polling.tick(sessions, services, owner=WORKER)

    assert polled.runs == [] and polled.error is not None
    assert settled() == [("nack", [1, 2])]
    async with sessions() as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
    assert row.cursor is None, "the cursor stays where the batch began"


async def test_a_source_whose_commit_failed_hands_the_batch_back(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued(1, 2)
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(SOURCED))

    async def broken(*args: Any, **kwargs: Any) -> UUID:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(polling, "enter_input", broken)
    await polling.tick(sessions, services, owner=WORKER)

    assert settled() == [("nack", [1, 2])]
