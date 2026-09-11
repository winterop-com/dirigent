"""The queue lane: the kafka and rabbitmq blocks against the brokers in infra/compose.queues.yaml.

The fakes cover each block's own decisions. What only a real broker proves is the part the
client library owns: that an assignment and a seek land where they say, that a group's commit
survives the connection that made it, that a nacked message comes back, and that what a publish
put on a topic is what the sensor reads back off it.

    docker compose -f infra/compose.queues.yaml up -d
    make test-queues
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from dirigent_blocks.kafka import (
    KafkaConnectionConfig,
    KafkaConnectionKind,
    KafkaConsumeConfig,
    KafkaConsumeSensor,
    KafkaProduceConfig,
    KafkaProduceOperator,
)
from dirigent_blocks.rabbitmq import (
    RabbitConnectionConfig,
    RabbitConnectionKind,
    RabbitConsumeConfig,
    RabbitConsumeSensor,
)
from dirigent_blocks.storage import StorageReadConfig, StorageReadOperator, StorageReadOutput
from dirigent_plugin import BlockFailure, ConnectionKind, ErrorClass, NotYet
from dirigent_testing import FakeContext, FakeStorage

pytestmark = pytest.mark.queues

#: Where the compose stack puts the brokers, overridable for a stack started elsewhere.
BOOTSTRAP = os.environ.get("DIRIGENT_TEST_KAFKA", "127.0.0.1:9092")
AMQP_HOST = os.environ.get("DIRIGENT_TEST_RABBITMQ_HOST", "127.0.0.1")
AMQP_PORT = os.environ.get("DIRIGENT_TEST_RABBITMQ_PORT", "5672")
AMQP_USER = os.environ.get("DIRIGENT_TEST_RABBITMQ_USER", "dirigent")
AMQP_PASSWORD = os.environ.get("DIRIGENT_TEST_RABBITMQ_PASSWORD", "dirigent")

#: How long a lane test waits for a broker that may still be coming up.
READY_TIMEOUT = 60.0


def kafka_connection() -> KafkaConnectionConfig:
    """The connection every Kafka test in this lane resolves through."""
    return KafkaConnectionConfig(bootstrap_servers=[BOOTSTRAP])


def rabbit_connection() -> RabbitConnectionConfig:
    """The connection every RabbitMQ test in this lane resolves through."""
    return RabbitConnectionConfig(
        url=f"amqp://{AMQP_USER}@{AMQP_HOST}:{AMQP_PORT}/",
        password=SecretStr(AMQP_PASSWORD),
    )


async def until_healthy(kind: ConnectionKind, settings: BaseModel, what: str) -> None:
    """Wait for a broker to answer its own health check, skipping the lane when it never does."""
    deadline = asyncio.get_running_loop().time() + READY_TIMEOUT
    detail = "never answered"
    while asyncio.get_running_loop().time() < deadline:
        report = await kind.check(settings)
        if report.healthy:
            return
        detail = report.detail or detail
        await asyncio.sleep(1.0)
    pytest.skip(f"{what} is not reachable, so this lane has no broker to run against: {detail}")


@pytest.fixture
async def topic() -> AsyncIterator[str]:
    """Create a one-partition topic for one test, and take it away again."""
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic

    await until_healthy(KafkaConnectionKind(), kafka_connection(), "the Kafka broker")
    name = f"dirigent-{uuid.uuid4().hex[:12]}"
    admin: Any = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(name, num_partitions=1, replication_factor=1)])
        yield name
        await admin.delete_topics([name])
    finally:
        await admin.close()


async def publish(topic: str, values: list[bytes], *, key: bytes | None = None) -> None:
    """Put messages on a topic and wait until the broker has them."""
    from aiokafka import AIOKafkaProducer

    producer: Any = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        for value in values:
            await producer.send_and_wait(topic, value=value, key=key)
    finally:
        await producer.stop()


@pytest.fixture
async def queue() -> AsyncIterator[str]:
    """Declare a queue for one test, and delete it again."""
    import aio_pika

    await until_healthy(RabbitConnectionKind(), rabbit_connection(), "the RabbitMQ broker")
    name = f"dirigent-{uuid.uuid4().hex[:12]}"
    connection: Any = await aio_pika.connect(rabbit_connection().dsn())
    try:
        channel = await connection.channel()
        await channel.declare_queue(name, durable=False, auto_delete=False)
        yield name
        channel = await connection.channel()
        declared = await channel.get_queue(name)
        await declared.delete(if_unused=False, if_empty=False)
    finally:
        await connection.close()


async def enqueue(queue: str, bodies: list[bytes]) -> None:
    """Publish messages straight to a queue through the default exchange."""
    import aio_pika

    connection: Any = await aio_pika.connect(rabbit_connection().dsn())
    try:
        channel = await connection.channel()
        for body in bodies:
            await channel.default_exchange.publish(aio_pika.Message(body=body), routing_key=queue)
    finally:
        await connection.close()


def kafka_ctx(ctx: FakeContext) -> FakeContext:
    """Give the fake context the live Kafka connection."""
    ctx.connections["cluster"] = kafka_connection()
    return ctx


def rabbit_ctx(ctx: FakeContext) -> FakeContext:
    """Give the fake context the live RabbitMQ connection."""
    ctx.connections["broker"] = rabbit_connection()
    return ctx


# -- kafka.consume ---------------------------------------------------------------


async def test_a_cursorless_poke_reads_the_topic_from_the_beginning(ctx: FakeContext, topic: str) -> None:
    await publish(topic, [b'{"id": 1}', b'{"id": 2}'])
    config = KafkaConsumeConfig(connection="cluster", topic=topic, start="earliest", poll_timeout=timedelta(seconds=5))

    output = await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 1}, {"id": 2}]
    assert output.cursor == {"0": 2}


async def test_the_next_poke_carries_on_from_the_cursor(ctx: FakeContext, topic: str) -> None:
    await publish(topic, [b'{"id": 1}', b'{"id": 2}'])
    config = KafkaConsumeConfig(connection="cluster", topic=topic, start="earliest", poll_timeout=timedelta(seconds=5))
    ready = kafka_ctx(ctx)
    ready.cursor = {"offsets": {"0": 1}}

    output = await KafkaConsumeSensor().poke(config, ready.as_context())

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 2}]


async def test_an_empty_topic_parks_rather_than_failing(ctx: FakeContext, topic: str) -> None:
    config = KafkaConsumeConfig(connection="cluster", topic=topic, start="earliest", poll_timeout=timedelta(seconds=2))

    parked = await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())

    assert isinstance(parked, NotYet)


async def test_a_message_published_between_two_pokes_is_read_by_the_second(ctx: FakeContext, topic: str) -> None:
    """A poke starting at latest writes down the end it seeked to, so nothing after it is lost."""
    config = KafkaConsumeConfig(connection="cluster", topic=topic, poll_timeout=timedelta(seconds=2))

    parked = await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())
    assert isinstance(parked, NotYet)
    assert parked.cursor == {"offsets": {"0": 0}}

    await publish(topic, [b'{"id": 1}'])
    later = kafka_ctx(ctx)
    later.cursor = parked.cursor

    output = await KafkaConsumeSensor().poke(config, later.as_context())

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 1}]


async def test_a_group_commits_what_it_succeeded_on(ctx: FakeContext, topic: str) -> None:
    """A second attempt with the same group starts where the first one committed."""
    await publish(topic, [b'{"id": 1}', b'{"id": 2}'])
    group = f"g-{uuid.uuid4().hex[:8]}"
    config = KafkaConsumeConfig(
        connection="cluster",
        topic=topic,
        group_id=group,
        start="earliest",
        max_messages=1,
        poll_timeout=timedelta(seconds=5),
    )

    first = await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())
    assert not isinstance(first, NotYet)
    assert [message.offset for message in first.messages] == [0]

    second = await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())
    assert not isinstance(second, NotYet)
    assert [message.offset for message in second.messages] == [1], "the commit moved the group on"


async def test_a_group_poke_that_parked_reads_on_rather_than_rejoining_at_latest(ctx: FakeContext, topic: str) -> None:
    """A group commits nothing on a park, so the place it read to travels in the cursor."""
    config = KafkaConsumeConfig(
        connection="cluster",
        topic=topic,
        group_id=f"g-{uuid.uuid4().hex[:8]}",
        poll_timeout=timedelta(seconds=5),
    )

    parked = await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())
    assert isinstance(parked, NotYet)
    assert parked.cursor == {"offsets": {"0": 0}}

    await publish(topic, [b'{"id": 1}'])
    later = kafka_ctx(ctx)
    later.cursor = parked.cursor

    output = await KafkaConsumeSensor().poke(config, later.as_context())

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 1}]


async def test_a_topic_that_does_not_exist_is_rejected(ctx: FakeContext, topic: str) -> None:
    config = KafkaConsumeConfig(connection="cluster", topic=f"{topic}-absent", poll_timeout=timedelta(seconds=2))

    with pytest.raises(BlockFailure, match="no topic"):
        await KafkaConsumeSensor().poke(config, kafka_ctx(ctx).as_context())


# -- kafka.produce ---------------------------------------------------------------


async def test_what_the_producer_published_is_what_the_sensor_reads_back(ctx: FakeContext, topic: str) -> None:
    """The round trip: keys, headers and values as a real broker stored and returned them."""
    published = await KafkaProduceOperator().execute(
        KafkaProduceConfig(
            connection="cluster",
            topic=topic,
            key="region",
            records=[
                {"region": "north", "id": 1},
                {"key": "south", "value": {"id": 2}, "headers": {"source": "till"}},
            ],
        ),
        kafka_ctx(ctx).as_context(),
    )

    assert (published.produced, published.topic) == (2, topic)
    assert published.offsets == {"0": 1}, "the last offset the one partition was written to"
    assert published.sent_bytes > 0

    output = await KafkaConsumeSensor().poke(
        KafkaConsumeConfig(
            connection="cluster",
            topic=topic,
            start="earliest",
            min_messages=2,
            key_format="text",
            poll_timeout=timedelta(seconds=5),
        ),
        kafka_ctx(ctx).as_context(),
    )

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"region": "north", "id": 1}, {"id": 2}]
    assert [message.key for message in output.messages] == ["north", "south"]
    assert output.messages[1].headers == {"source": "till"}


async def test_records_read_out_of_storage_reach_the_topic(ctx: FakeContext, storage: FakeStorage, topic: str) -> None:
    """The composed path: storage.read takes the records in, and the publish sends what it read."""
    (storage.root / "orders.json").write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')

    read = await StorageReadOperator().execute(StorageReadConfig(source="file://orders.json"), ctx.as_context())
    assert isinstance(read, StorageReadOutput)
    assert isinstance(read.value, list)

    published = await KafkaProduceOperator().execute(
        KafkaProduceConfig(connection="cluster", topic=topic, records=read.value),
        kafka_ctx(ctx).as_context(),
    )

    assert published.produced == 3

    output = await KafkaConsumeSensor().poke(
        KafkaConsumeConfig(
            connection="cluster", topic=topic, start="earliest", min_messages=3, poll_timeout=timedelta(seconds=5)
        ),
        kafka_ctx(ctx).as_context(),
    )

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 1}, {"id": 2}, {"id": 3}]


async def test_a_topic_the_cluster_does_not_have_is_rejected_rather_than_waited_on(
    ctx: FakeContext, topic: str
) -> None:
    """The metadata answers at once, where a send would wait out the client's whole request timeout."""
    config = KafkaProduceConfig(
        connection="cluster", topic=f"{topic}-absent", records=[{"id": 1}], timeout=timedelta(seconds=10)
    )

    with pytest.raises(BlockFailure, match="no topic") as raised:
        await KafkaProduceOperator().execute(config, kafka_ctx(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_kafka_health_check_reaches_the_cluster() -> None:
    await until_healthy(KafkaConnectionKind(), kafka_connection(), "the Kafka broker")

    report = await KafkaConnectionKind().check(kafka_connection())

    assert report.healthy is True


# -- rabbitmq.consume ------------------------------------------------------------


async def test_a_poke_takes_what_is_on_the_queue_and_acks_it(ctx: FakeContext, queue: str) -> None:
    await enqueue(queue, [b'{"id": 1}', b'{"id": 2}'])
    config = RabbitConsumeConfig(connection="broker", queue=queue, min_messages=2, poll_timeout=timedelta(seconds=5))

    output = await RabbitConsumeSensor().poke(config, rabbit_ctx(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert [message.body for message in output.messages] == [{"id": 1}, {"id": 2}]

    again = await RabbitConsumeSensor().poke(
        RabbitConsumeConfig(connection="broker", queue=queue, poll_timeout=timedelta(seconds=2)),
        rabbit_ctx(ctx).as_context(),
    )
    assert isinstance(again, NotYet), "an acked message does not come back"


async def test_on_success_puts_a_batch_that_was_too_small_back(ctx: FakeContext, queue: str) -> None:
    await enqueue(queue, [b'{"id": 1}'])
    config = RabbitConsumeConfig(connection="broker", queue=queue, min_messages=3, poll_timeout=timedelta(seconds=2))

    parked = await RabbitConsumeSensor().poke(config, rabbit_ctx(ctx).as_context())
    assert isinstance(parked, NotYet)

    taken = await RabbitConsumeSensor().poke(
        RabbitConsumeConfig(connection="broker", queue=queue, poll_timeout=timedelta(seconds=5)),
        rabbit_ctx(ctx).as_context(),
    )
    assert not isinstance(taken, NotYet)
    assert taken.count == 1, "the nacked message was requeued rather than swallowed"


async def test_always_takes_a_message_off_even_when_the_batch_parks(ctx: FakeContext, queue: str) -> None:
    await enqueue(queue, [b'{"id": 1}'])
    config = RabbitConsumeConfig(
        connection="broker", queue=queue, min_messages=3, ack="always", poll_timeout=timedelta(seconds=2)
    )

    parked = await RabbitConsumeSensor().poke(config, rabbit_ctx(ctx).as_context())
    assert isinstance(parked, NotYet)

    again = await RabbitConsumeSensor().poke(
        RabbitConsumeConfig(connection="broker", queue=queue, poll_timeout=timedelta(seconds=2)),
        rabbit_ctx(ctx).as_context(),
    )
    assert isinstance(again, NotYet), "the message was acknowledged and is gone"


async def test_a_queue_that_does_not_exist_is_rejected(ctx: FakeContext, queue: str) -> None:
    config = RabbitConsumeConfig(connection="broker", queue=f"{queue}-absent", poll_timeout=timedelta(seconds=2))

    with pytest.raises(BlockFailure, match="no queue"):
        await RabbitConsumeSensor().poke(config, rabbit_ctx(ctx).as_context())


async def test_a_rabbitmq_health_check_opens_a_channel() -> None:
    await until_healthy(RabbitConnectionKind(), rabbit_connection(), "the RabbitMQ broker")

    report = await RabbitConnectionKind().check(rabbit_connection())

    assert report.healthy is True
