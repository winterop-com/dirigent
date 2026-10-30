"""The queue lane for sensor sources: ``kafka.consume`` poked by a source reading a real topic, run after run.

docker compose -f infra/compose.queues.yaml up -d
make test-queues
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_block_queues import plugin as queues_plugin
from dirigent_block_queues.kafka import KafkaConnectionConfig, KafkaConnectionKind
from dirigent_client.enums import AttemptStatus
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Connection, Run, Source, StepAttempt
from dirigent_core.pipelines import apply_document
from dirigent_core.plugins import PluginHost
from dirigent_core.sources import polling
from engineblocks import EngineTestPlugin

pytestmark = pytest.mark.queues

#: Where the compose stack puts the broker, overridable for a stack started elsewhere.
BOOTSTRAP = os.environ.get("DIRIGENT_TEST_KAFKA", "127.0.0.1:9092")

#: How long the lane waits for a broker that may still be coming up.
READY_TIMEOUT = 60.0


@pytest.fixture
def host() -> PluginHost:
    """The engine's test blocks beside the real queue blocks."""
    return PluginHost({"engine-tests": EngineTestPlugin().contribute(), "block-queues": queues_plugin.contribute()})


@pytest.fixture
def services(settings: Settings, host: PluginHost) -> EngineServices:
    """The services every engine path shares, over the host with the queue blocks in it."""
    return EngineServices.build(settings, host)


@pytest.fixture
async def topic() -> AsyncIterator[str]:
    """Create a one-partition topic holding six messages, and take it away again."""
    from aiokafka import AIOKafkaProducer
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic

    connection = KafkaConnectionConfig(bootstrap_servers=[BOOTSTRAP])
    deadline = asyncio.get_running_loop().time() + READY_TIMEOUT
    while not (await KafkaConnectionKind().check(connection)).healthy:
        if asyncio.get_running_loop().time() > deadline:
            pytest.skip("the Kafka broker is not reachable, so this lane has nothing to run against")
        await asyncio.sleep(1.0)
    name = f"dirigent-sensor-{uuid.uuid4().hex[:12]}"
    admin: Any = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(name, num_partitions=1, replication_factor=1)])
        producer: Any = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
        await producer.start()
        try:
            for number in range(6):
                await producer.send_and_wait(name, value=f'{{"n": {number}}}'.encode())
        finally:
            await producer.stop()
        yield name
        await admin.delete_topics([name])
    finally:
        await admin.close()


async def batches(sessions: async_sessionmaker[AsyncSession]) -> list[list[int]]:
    """The offsets each batch the source handed over took, in the order the runs were started."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt.output)
            .join(Run, Run.id == StepAttempt.run_id)
            .where(StepAttempt.step_name == "tail", StepAttempt.status == AttemptStatus.SUCCEEDED)
            .order_by(Run.created_at, Run.id)
        )
        return [[message["offset"] for message in output["messages"]] for output in rows.scalars() if output]


async def test_a_topic_poked_by_a_source_is_read_on_run_after_run_with_no_consumer_group(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, topic: str
) -> None:
    async with session_scope(sessions) as session:
        session.add(Connection(code="cluster", kind="kafka", config={"bootstrap_servers": [BOOTSTRAP]}))
    document = f"""
format: dirigent/v1
kind: pipeline
code: tailing-kafka
steps:
  tail:
    source:
      kind: sensor
      block: kafka.consume
      config: {{connection: cluster, topic: {topic}, start: earliest, max_messages: 2}}
      poll: 1s
  load:
    block: test.echo
    depends_on: [tail]
    config: {{value: loaded}}
"""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(document))

    moment = datetime.now(UTC)
    for _ in range(60):
        if len(await batches(sessions)) >= 3:
            break
        await polling.tick(sessions, services, owner="queue-lane", now=moment)
        moment += timedelta(seconds=2)

    assert await batches(sessions) == [[0, 1], [2, 3], [4, 5]]
    async with sessions() as session:
        source = (await session.execute(sa.select(Source))).scalar_one()
    assert source.cursor is not None and source.cursor["cursor"] == {"offsets": {"0": 6}}
