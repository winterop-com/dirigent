"""Sensor sources: a sensor poked outside any run, each success starting one."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Run, Source, StepAttempt
from dirigent_core.pipelines import apply_document
from dirigent_core.sources import polling
from engineblocks import StreamSensor

WORKER = "worker-under-test"


def tailing(block: str = "test.stream", config: str = "{key: tail, parks: 1, batch: 2}") -> str:
    """A pipeline whose source pokes a sensor, and echoes where each batch ended."""
    return f"""
format: dirigent/v1
kind: pipeline
code: tailing
steps:
  tail:
    source:
      kind: sensor
      block: {block}
      config: {config}
      poll: 1m
  note:
    block: test.echo
    depends_on: [tail]
    config:
      value: ${{steps.tail.output.next_offset}}
"""


async def the_source(sessions: async_sessionmaker[AsyncSession]) -> Source:
    """Read the one source row back."""
    async with sessions() as session:
        return (await session.execute(sa.select(Source))).scalar_one()


async def entered(sessions: async_sessionmaker[AsyncSession]) -> list[object]:
    """The offsets each run was entered with, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt.output)
            .join(Run, Run.id == StepAttempt.run_id)
            .where(StepAttempt.step_name == "tail")
            .order_by(Run.created_at, Run.id)
        )
        return [output["offsets"] for output in rows.scalars() if output is not None]


async def test_a_success_starts_a_run_and_the_next_wait_reads_on_from_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tailing()))

    [parked] = await polling.tick(sessions, services, owner=WORKER)
    assert parked.runs == [], "a poke that answers not yet starts nothing"
    row = await the_source(sessions)
    assert row.cursor is not None
    assert row.cursor["cursor"] == {"offset": 0, "parked": 1}
    assert row.next_poll_at is not None and row.polled_at is not None
    assert row.next_poll_at - row.polled_at == timedelta(seconds=1), "the sensor's own next_poll_in wins"

    later = datetime.now(UTC) + timedelta(seconds=2)
    [arrived] = await polling.tick(sessions, services, owner=WORKER, now=later)
    assert len(arrived.runs) == 1
    assert await entered(sessions) == [[0, 1]]
    row = await the_source(sessions)
    assert row.cursor is not None and row.cursor["cursor"] == {"offset": 2}
    assert row.next_poll_at == row.polled_at, "a success is poked again at once"

    [again] = await polling.tick(sessions, services, owner=WORKER, now=later + timedelta(seconds=1))
    assert again.runs == []
    assert StreamSensor.seen["tail"][-1] == {"offset": 2}, "the next wait starts where the batch ended"


async def test_a_sensor_reading_part_of_a_run_fails_the_poll(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tailing(block="test.scratch", config="{}")))
    [failed] = await polling.tick(sessions, services, owner=WORKER)
    assert failed.error is not None and "scratch" in failed.error
    row = await the_source(sessions)
    assert (row.failures, row.cursor) == (1, None)


@pytest.mark.parametrize(
    ("block", "config", "code", "location"),
    [
        ("test.nowhere", "{}", "source.sensor_unknown", "steps.tail.source.block"),
        ("test.cursor", "{}", "source.sensor_not_a_source", "steps.tail.source.block"),
        ("test.echo", "{}", "source.sensor_unknown", "steps.tail.source.block"),
        ("test.stream", "{parks: many}", None, "steps.tail.source.config.parks"),
    ],
)
async def test_apply_refuses_what_a_source_cannot_poke(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    block: str,
    config: str,
    code: str | None,
    location: str,
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(tailing(block=block, config=config)), dry_run=True)
    [issue] = result.plan.issues
    assert issue.location == location
    if code is not None:
        assert issue.code == code
