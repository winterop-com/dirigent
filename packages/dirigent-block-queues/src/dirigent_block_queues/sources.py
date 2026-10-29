"""The queue source kinds: a Kafka topic and a RabbitMQ queue, each consumed for as long as a worker holds it.

Every message becomes one run, and is acknowledged only once that run exists: a Kafka group's
offsets are committed, and a RabbitMQ delivery is acked. A consumer closed before that leaves
the message to the broker, which delivers it again.

A message whose body is not what ``value_format`` says fails the source, and since it is never
acknowledged the broker hands it over again on the next attempt; a topic or queue carrying such
a message is read as ``text`` or ``base64`` to get past it.
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, JsonValue

from dirigent_block_queues.kafka import (
    Consumer,
    KafkaConnectionConfig,
    Payload,
    close,
    consumer_for,
)
from dirigent_block_queues.kafka import decode as decode_part
from dirigent_block_queues.messages import KAFKA_NO_TOPIC, RABBIT_NO_QUEUE
from dirigent_block_queues.rabbitmq import (
    IDLE_SLEEP,
    Connection,
    Delivery,
    Queue,
    RabbitConnectionConfig,
    connect,
)
from dirigent_block_queues.rabbitmq import decode as decode_body
from dirigent_common import BlockModel, JsonMap
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass
from dirigent_plugin.sources import HeldSource, HoldContext, SourceHosting, SourceSpec


class KafkaSourceConfig(BlockModel):
    """A topic to consume, through a consumer group whose committed offsets say where it carries on."""

    connection: ConnectionRef
    """The ``kafka`` connection naming the cluster and holding its credential."""

    topic: str = Field(min_length=1)
    """The topic to consume."""

    group_id: str = Field(min_length=1)
    """The consumer group. Its offsets are committed once each message has become a run, which is
    where a worker that takes the source over carries on from."""

    start: Literal["latest", "earliest"] = "latest"
    """Where a group with no committed offsets begins: at what arrives next, or at the oldest record kept."""

    key_format: Payload = "base64"
    """How a message key is decoded."""

    value_format: Payload = "json"
    """How a message value is decoded."""

    max_in_flight: int | None = Field(default=None, ge=1)
    """How many unsettled runs from this source may exist before the consumer waits for one to settle."""


class KafkaInput(BlockModel):
    """One message off the topic."""

    topic: str
    partition: int = 0
    offset: int = 0
    key: JsonValue = None
    value: JsonValue = None
    timestamp: datetime
    """When the broker recorded the message."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    received_at: datetime
    """When the worker took it, or when a hand run supplied it."""


class KafkaSource(HeldSource[KafkaSourceConfig, KafkaInput]):
    """A Kafka topic, consumed by one worker at a time through a consumer group."""

    spec = SourceSpec(kind="kafka", summary="A message on a Kafka topic", hosting=SourceHosting.HELD)
    config_model: ClassVar[type[BaseModel]] = KafkaSourceConfig
    output_model: ClassVar[type[BaseModel]] = KafkaInput

    def max_in_flight(self, config: KafkaSourceConfig) -> int | None:
        """Bound the unsettled runs the way the source declares."""
        return config.max_in_flight

    def summary_of(self, config: KafkaSourceConfig) -> str | None:
        """Name the topic and the group."""
        return f"{config.topic} as {config.group_id}"

    def label_of(self, output: KafkaInput) -> str | None:
        """Name a message by where it was read."""
        return f"{output.topic}/{output.partition}@{output.offset}"

    def complete(self, config: KafkaSourceConfig, given: JsonMap, *, received_at: datetime) -> KafkaInput:
        """Make a hand run's input whole: a message on the source's topic, stamped now."""
        return KafkaInput.model_validate(
            {"topic": config.topic, "timestamp": received_at, **given, "received_at": received_at}
        )

    def listen(self, config: KafkaSourceConfig, ctx: HoldContext) -> AbstractAsyncContextManager["KafkaListener"]:
        """Join the group on the topic for as long as the worker holds the source."""
        return _kafka(config, ctx)


@asynccontextmanager
async def _kafka(config: KafkaSourceConfig, ctx: HoldContext) -> AsyncGenerator["KafkaListener"]:
    """Open a consumer in the group, subscribed to the topic, and close it however the hold ends."""
    settings = ctx.connection(config.connection, KafkaConnectionConfig)
    consumer = consumer_for(settings, group_id=config.group_id, start=config.start)
    try:
        await consumer.start()
        await consumer.prime(config.topic)
        if not consumer.partitions_for_topic(config.topic):
            raise BlockFailure(KAFKA_NO_TOPIC, error_class=ErrorClass.REJECTED, topic=repr(config.topic))
        consumer.subscribe([config.topic])
        ctx.log.info("consuming", topic=config.topic, group_id=config.group_id)
        yield KafkaListener(consumer, config)
    finally:
        await close(consumer)


class KafkaListener:
    """Fetches from the topic, and commits the group's offsets once what it fetched has become runs."""

    def __init__(self, consumer: Consumer, config: KafkaSourceConfig) -> None:
        """Hold the started consumer."""
        self.consumer = consumer
        self.config = config

    async def receive(self, limit: int, wait: timedelta) -> list[KafkaInput]:
        """Fetch at most ``limit`` messages, waiting no longer than ``wait``."""
        fetched = await self.consumer.getmany(timeout_ms=int(wait.total_seconds() * 1000), max_records=limit)
        now = datetime.now(UTC)
        taken: list[KafkaInput] = []
        for _partition, records in sorted(fetched.items(), key=lambda pair: pair[0].partition):
            for record in records:
                taken.append(
                    KafkaInput(
                        topic=record.topic,
                        partition=record.partition,
                        offset=record.offset,
                        key=decode_part(record.key, self.config.key_format, "key"),
                        value=decode_part(record.value, self.config.value_format, "value"),
                        timestamp=datetime.fromtimestamp(record.timestamp / 1000, tz=UTC),
                        headers={name: _text(value) for name, value in (record.headers or ())},
                        received_at=now,
                    )
                )
        return taken

    async def ack(self) -> None:
        """Commit the group's offsets for everything fetched so far."""
        await self.consumer.commit()


class RabbitSourceConfig(BlockModel):
    """A queue to consume."""

    connection: ConnectionRef
    """The ``rabbitmq`` connection naming the broker and holding its password."""

    queue: str = Field(min_length=1)
    """The queue to consume. It must already exist: the source declares nothing."""

    value_format: Payload = "json"
    """How a message body is decoded."""

    max_in_flight: int | None = Field(default=None, ge=1)
    """How many unsettled runs from this source may exist before the consumer waits for one to settle."""


class RabbitInput(BlockModel):
    """One message off the queue."""

    queue: str
    routing_key: str | None = None
    exchange: str | None = None
    body: JsonValue = None
    headers: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    timestamp: datetime | None = None
    """When the publisher stamped the message, when it stamped one at all."""

    received_at: datetime
    """When the worker took it, or when a hand run supplied it."""


class RabbitSource(HeldSource[RabbitSourceConfig, RabbitInput]):
    """A RabbitMQ queue, consumed by one worker at a time."""

    spec = SourceSpec(kind="rabbitmq", summary="A message on a RabbitMQ queue", hosting=SourceHosting.HELD)
    config_model: ClassVar[type[BaseModel]] = RabbitSourceConfig
    output_model: ClassVar[type[BaseModel]] = RabbitInput

    def max_in_flight(self, config: RabbitSourceConfig) -> int | None:
        """Bound the unsettled runs the way the source declares."""
        return config.max_in_flight

    def summary_of(self, config: RabbitSourceConfig) -> str | None:
        """Name the queue."""
        return config.queue

    def label_of(self, output: RabbitInput) -> str | None:
        """Name a message by its queue and routing key."""
        return output.queue if output.routing_key is None else f"{output.queue} {output.routing_key}"

    def complete(self, config: RabbitSourceConfig, given: JsonMap, *, received_at: datetime) -> RabbitInput:
        """Make a hand run's input whole: a message on the source's queue."""
        return RabbitInput.model_validate({"queue": config.queue, **given, "received_at": received_at})

    def listen(self, config: RabbitSourceConfig, ctx: HoldContext) -> AbstractAsyncContextManager["RabbitListener"]:
        """Consume the queue for as long as the worker holds the source."""
        return _rabbit(config, ctx)


@asynccontextmanager
async def _rabbit(config: RabbitSourceConfig, ctx: HoldContext) -> AsyncGenerator["RabbitListener"]:
    """Open a connection and find the queue; closing it hands every unacknowledged delivery back."""
    connection: Connection = await connect(ctx.connection(config.connection, RabbitConnectionConfig))
    try:
        channel = await connection.channel()
        try:
            queue = await channel.get_queue(config.queue, ensure=True)
        except Exception as error:
            raise BlockFailure(
                RABBIT_NO_QUEUE, error_class=ErrorClass.REJECTED, queue=repr(config.queue), detail=str(error)
            ) from error
        ctx.log.info("consuming", queue=config.queue)
        yield RabbitListener(queue, config)
    finally:
        await connection.close()


class RabbitListener:
    """Takes deliveries off the queue, and acks them once they have become runs."""

    def __init__(self, queue: Queue, config: RabbitSourceConfig) -> None:
        """Hold the queue, and nothing taken yet."""
        self.queue = queue
        self.config = config
        self.pending: list[Delivery] = []

    async def receive(self, limit: int, wait: timedelta) -> list[RabbitInput]:
        """Take at most ``limit`` deliveries, waiting no longer than ``wait`` for the first."""
        deadline = time.monotonic() + wait.total_seconds()
        taken: list[Delivery] = []
        while len(taken) < limit:
            delivery = await self.queue.get(fail=False, no_ack=False)
            if delivery is not None:
                taken.append(delivery)
                continue
            remaining = deadline - time.monotonic()
            if taken or remaining <= 0:
                break
            await asyncio.sleep(min(IDLE_SLEEP.total_seconds(), remaining))
        self.pending.extend(taken)
        now = datetime.now(UTC)
        return [
            RabbitInput(
                queue=self.config.queue,
                routing_key=delivery.routing_key,
                exchange=delivery.exchange,
                body=decode_body(delivery.body, self.config.value_format),
                headers={str(name): _plain(value) for name, value in (delivery.headers or {}).items()},
                timestamp=_stamp(delivery.timestamp),
                received_at=now,
            )
            for delivery in taken
        ]

    async def ack(self) -> None:
        """Ack every delivery taken so far."""
        pending, self.pending = self.pending, []
        for delivery in pending:
            await delivery.ack()


def _text(raw: bytes) -> str:
    """Decode bytes as text, keeping what a broker sent even when it is not valid UTF-8."""
    return raw.decode("utf-8", errors="replace")


def _plain(value: Any) -> JsonValue:
    """One header value, as JSON carries it; anything exotic becomes its own text."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _stamp(value: datetime | None) -> datetime | None:
    """A publisher's timestamp, given the timezone AMQP leaves off it."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
