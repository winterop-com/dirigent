"""The Kafka blocks: ``kafka.consume`` waits on a topic as a sensor, ``kafka.produce`` writes to one.

A queue and a webhook are the same intent arriving by different transport, so a topic starts a
run the way a clock or a POST does: each poke reads what has arrived since the last one and
succeeds the moment there is enough, handing the batch downstream as its output.

The place a poke has read to is the sensor's cursor. Without a ``group_id`` that is the whole
of the bookkeeping -- the offsets live in the attempt row and nowhere else, so nothing is
committed to the broker and two pipelines over one topic never take each other's messages.
With a ``group_id`` the broker keeps the group's offsets too, and the commit happens in the
poke that succeeds rather than in one that parks, so a batch too small to act on is read
again rather than lost. Either way the cursor is at-least-once, which is why the output
carries the offsets the batch actually covers.

``kafka.produce`` is the other direction on the same connection kind: a list of records, or an
NDJSON object streamed out of storage, published to one topic and acknowledged by the broker
before the step succeeds.

Both are **ordinary** blocks: each reaches its connection's brokers and nothing else.
"""

import asyncio
import base64
import json
import ssl
import time
from collections.abc import Awaitable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, Protocol, cast

from pydantic import BaseModel, Field, JsonValue, SecretStr, ValidationError, model_validator

from dirigent_common import BlockModel, Duration, HealthReport
from dirigent_plugin import (
    BlockFailure,
    ConnectionKind,
    ConnectionRef,
    ErrorClass,
    NotYet,
    Operator,
    OperatorSpec,
    Sensor,
    SensorSpec,
    StepContext,
)

#: How the config's word for a security setting is spelled to the client library.
SECURITY_PROTOCOLS = {
    "plaintext": "PLAINTEXT",
    "ssl": "SSL",
    "sasl_ssl": "SASL_SSL",
    "sasl_plaintext": "SASL_PLAINTEXT",
}

#: The settings that authenticate, and so need a username and a password.
SASL_SECURITY = ("sasl_ssl", "sasl_plaintext")

#: The settings that encrypt, and so are the only ones a CA certificate says anything about.
TLS_SECURITY = ("ssl", "sasl_ssl")

#: What a broker's error says when reaching it, rather than the request, is the problem.
UNREACHABLE = ("connection", "timeout", "timed out", "no brokers", "unavailable", "not available", "coordinator")

#: What a broker's error says when the request was understood and refused.
REFUSED = ("authentication", "authorization", "unauthorized", "sasl", "credential", "unknown topic", "invalid")

type Payload = Literal["json", "text", "base64"]


class KafkaConnectionConfig(BlockModel):
    """One Kafka cluster, and the credential that reaches it."""

    bootstrap_servers: list[str] = Field(min_length=1)
    """The brokers a client bootstraps from, each written ``host:port``."""

    security: Literal["plaintext", "ssl", "sasl_ssl", "sasl_plaintext"] = "plaintext"
    """How the connection is protected: not at all, by TLS, or by TLS or SASL with a credential."""

    sasl_mechanism: Literal["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"] = "PLAIN"
    """Which SASL exchange proves the credential, for a ``sasl_`` security setting."""

    username: str | None = None
    """The SASL user."""

    password: SecretStr | None = None
    """The SASL password, sealed like every other connection secret: encrypted at rest and
    redacted in every API response."""

    ca_certificate: str | None = None
    """The PEM the broker's certificate is checked against, when the cluster's CA is a private
    one. Unset trusts the host's own store.

    It is a plain field rather than a sealed one, and deliberately: a CA certificate is the
    public half of a trust anchor, published by whoever issued it, and it authenticates the
    broker to us rather than us to the broker. Sealing it would hide from an operator which CA
    their own connection trusts while protecting nothing that is not already public."""

    @model_validator(mode="after")
    def _check_shape(self) -> "KafkaConnectionConfig":
        """Refuse a credential that does not fit the security setting, in either direction."""
        if self.security in SASL_SECURITY and not (self.username and self.password):
            raise ValueError(f"security {self.security!r} authenticates, so it needs a username and a password")
        if self.security not in SASL_SECURITY and (self.username or self.password):
            raise ValueError(
                f"security {self.security!r} carries no credential, so a username or password would go unused; "
                "write sasl_ssl or sasl_plaintext to send one"
            )
        if self.ca_certificate is not None and self.security not in TLS_SECURITY:
            raise ValueError(f"security {self.security!r} does not use TLS, so a ca_certificate would go unused")
        return self


class Consumer(Protocol):
    """The part of a Kafka consumer this block uses, so a test can stand in for one."""

    async def start(self) -> None:
        """Connect to the cluster and take up the assignment."""
        ...

    async def stop(self) -> None:
        """Leave the group, if there is one, and close the connection."""
        ...

    async def topics(self) -> set[str]:
        """Every topic the cluster's metadata names."""
        ...

    async def getmany(self, *, timeout_ms: int, max_records: int) -> dict[Any, list[Any]]:
        """Fetch what has arrived, by partition, waiting no longer than the timeout."""
        ...

    async def commit(self) -> None:
        """Commit the group's offsets for what has been fetched."""
        ...

    def assign(self, partitions: list[Any]) -> None:
        """Take a fixed assignment, with no group to negotiate one."""
        ...

    def assignment(self) -> set[Any]:
        """The partitions this consumer holds, however it came by them."""
        ...

    def subscribe(self, topics: list[str]) -> None:
        """Join the group's subscription to a topic."""
        ...

    def seek(self, partition: Any, offset: int) -> None:
        """Read the next record of a partition from an offset."""
        ...

    async def seek_to_beginning(self, *partitions: Any) -> None:
        """Read a partition from the oldest record the broker still holds."""
        ...

    async def seek_to_end(self, *partitions: Any) -> None:
        """Read a partition from whatever arrives next."""
        ...

    async def position(self, partition: Any) -> int:
        """The offset this consumer reads next on a partition it is assigned."""
        ...

    async def prime(self, topic: str) -> None:
        """Fetch one topic's metadata into the client's cache."""
        ...

    def partitions_for_topic(self, topic: str) -> set[int] | None:
        """The partitions of a primed topic, or None when the cluster has no such topic."""
        ...


class PrimedConsumer:
    """The client library's consumer, plus the metadata fetch it does not expose in the open.

    ``partitions_for_topic`` answers out of the client's own cache, and only a topic the client
    has been told to track is ever in it; fetching every topic's metadata does not put it
    there. Nothing public says "track this one", so the private call lives here, alone.
    """

    def __init__(self, inner: Any) -> None:
        """Wrap one consumer."""
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        """Hand every other call straight to the consumer being wrapped."""
        return getattr(self._inner, name)

    async def prime(self, topic: str) -> None:
        """Put one topic in the client's tracked set, which is what fetches its metadata."""
        await self._inner._client.set_topics([topic])  # noqa: SLF001


def consumer_for(settings: KafkaConnectionConfig, *, group_id: str | None, start: str) -> Consumer:
    """Build the client one poke reads through, with the connection's security applied."""
    from aiokafka import AIOKafkaConsumer

    keywords: dict[str, Any] = {
        "bootstrap_servers": list(settings.bootstrap_servers),
        "security_protocol": SECURITY_PROTOCOLS[settings.security],
        "enable_auto_commit": False,
        "auto_offset_reset": start,
        "group_id": group_id,
    }
    if settings.security in TLS_SECURITY:
        keywords["ssl_context"] = ssl.create_default_context(cadata=settings.ca_certificate)
    if settings.security in SASL_SECURITY:
        password = settings.password.get_secret_value() if settings.password else None
        keywords.update(
            sasl_mechanism=settings.sasl_mechanism,
            sasl_plain_username=settings.username,
            sasl_plain_password=password,
        )
    return cast("Consumer", PrimedConsumer(AIOKafkaConsumer(**keywords)))


class KafkaConnectionKind(ConnectionKind):
    """The connection kind ``kafka.consume`` resolves its cluster and credential through."""

    id: ClassVar[str] = "kafka"
    config_model: ClassVar[type[BaseModel]] = KafkaConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Fetch the cluster's metadata, which is the smallest thing that proves reach and credential."""
        settings = KafkaConnectionConfig.model_validate(config.model_dump())
        consumer = consumer_for(settings, group_id=None, start="latest")
        try:
            await consumer.start()
            topics = await consumer.topics()
        except Exception as error:  # every client error is a health answer, never a raise
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        finally:
            # A consumer whose start failed is still open, and the library reports one that
            # is dropped that way as an error on the event loop.
            await close(consumer)
        return HealthReport(healthy=True, detail=f"{len(topics)} topics")


class KafkaConsumeConfig(BlockModel):
    """Which topic to wait on, how much to take, and how to read what is in it."""

    connection: ConnectionRef
    """The ``kafka`` connection naming the cluster and holding its credential."""

    topic: str = Field(min_length=1)
    """The topic to read."""

    group_id: str | None = None
    """The consumer group to commit through, or unset to track offsets in the cursor alone.

    Unset, nothing is committed to the broker: the offsets live on the waiting attempt, so two
    pipelines reading one topic each see every message. Set, the group's offsets are committed
    by the poke that succeeds, never by one that parks, and the cursor still carries the
    offsets the batch covers so a replay reads the same ground rather than skipping it. A poke
    that parks leaves its place in the cursor too, so the next one reads on from there rather
    than from the group's last commit."""

    start: Literal["latest", "earliest"] = "latest"
    """Where a poke with no cursor begins: at whatever arrives next, or at the oldest record
    the broker still holds. It applies to the first poke of an attempt only; after that the
    cursor says where to read from."""

    min_messages: int = Field(default=1, ge=1)
    """How many messages a batch needs before the sensor succeeds. Below it the poke parks,
    keeping the offsets it read so the next poke carries on from there."""

    max_messages: int = Field(default=100, ge=1)
    """The most messages one poke takes, which bounds the output a step carries."""

    poll_timeout: Duration = timedelta(seconds=5)
    """How long one poke waits on the broker before answering with what it has, such as ``5s``.

    It bounds the poke, not the wait: a sensor that finds nothing parks and is poked again."""

    poll_every: Duration | None = None
    """How long to park between pokes; unset leaves the cadence to the step's own ``poll``."""

    key_format: Payload = "base64"
    """How a message key is decoded. ``base64`` carries any bytes through unharmed, which is
    what a key that is not text needs."""

    value_format: Payload = "json"
    """How a message value is decoded."""

    @model_validator(mode="after")
    def _check_shape(self) -> "KafkaConsumeConfig":
        """Refuse a batch that can never reach the size it is waiting for."""
        if self.min_messages > self.max_messages:
            raise ValueError(
                f"min_messages {self.min_messages} is above max_messages {self.max_messages}, "
                "so this sensor would wait for a batch it never takes"
            )
        return self


class KafkaMessage(BlockModel):
    """One message, as a downstream step reads it."""

    topic: str
    partition: int
    offset: int
    key: JsonValue = None
    value: JsonValue = None
    timestamp: datetime
    """When the broker recorded the message."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])


class KafkaConsumeOutput(BlockModel):
    """The batch a poke succeeded on, and where it left the topic."""

    messages: list[KafkaMessage]
    count: int
    cursor: dict[str, int]
    """The offset each partition is read up to, keyed by partition number as a string.

    An offset is the next one to read: one past the last message of the batch on a partition
    that carried any, and where the poke began on a partition that carried none."""


class KafkaConsumeSensor(Sensor[KafkaConsumeConfig, KafkaConsumeOutput]):
    """Waits for messages on a topic; each poke is one bounded fetch from the offsets it holds."""

    spec = SensorSpec(
        id="kafka.consume",
        summary="Wait for messages on a Kafka topic.",
        default_poll=timedelta(seconds=30),
    )
    config_model: ClassVar[type[BaseModel]] = KafkaConsumeConfig
    output_model: ClassVar[type[BaseModel]] = KafkaConsumeOutput

    async def poke(self, config: KafkaConsumeConfig, ctx: StepContext) -> KafkaConsumeOutput | NotYet:
        """Read what has arrived since the cursor, and succeed once the batch is big enough."""
        settings = ctx.connection(config.connection, KafkaConnectionConfig)
        offsets = read_cursor(ctx.cursor)
        consumer = consumer_for(settings, group_id=config.group_id, start=config.start)
        try:
            await consumer.start()
        except Exception as error:
            await close(consumer)
            raise BlockFailure(
                f"the kafka cluster refused the connection: {error}", error_class=classify(error)
            ) from error
        try:
            await _position(consumer, config, offsets)
            fetched = await consumer.getmany(
                timeout_ms=int(config.poll_timeout.total_seconds() * 1000),
                max_records=config.max_messages,
            )
            messages = _read(fetched, config, offsets)
            await _record_unfetched(consumer, config, offsets)
            if len(messages) < config.min_messages:
                ctx.log.debug(
                    "not enough on the topic yet",
                    topic=config.topic,
                    count=len(messages),
                    min_messages=config.min_messages,
                )
                return NotYet(
                    cursor={"offsets": offsets},
                    next_poll_in=config.poll_every,
                    message=f"{len(messages)} of {config.min_messages} messages",
                )
            if config.group_id is not None:
                await consumer.commit()
            ctx.log.info("consumed", topic=config.topic, count=len(messages), group_id=config.group_id)
            return KafkaConsumeOutput(messages=messages, count=len(messages), cursor=offsets)
        except BlockFailure:
            raise
        except Exception as error:
            raise BlockFailure(f"reading {config.topic!r} failed: {error}", error_class=classify(error)) from error
        finally:
            await close(consumer)

    def classify_error(self, error: Exception) -> ErrorClass:
        """A cluster that could not be reached is transient; one that said no is not."""
        return classify(error)


#: How many sends may be in flight before the block waits on them, so a document streaming a
#: million records grows a bounded list of futures rather than one per line.
IN_FLIGHT = 500

#: How the config's word for an acknowledgement setting is spelled to the client library.
ACKS: dict[str, Any] = {"all": "all", "1": 1, "0": 0}

#: The keys an element of ``records`` may carry to be read as an envelope rather than a value.
ENVELOPE = frozenset({"key", "value", "headers"})

type Acks = Literal["all", "1", "0"]


class Producer(Protocol):
    """The part of a Kafka producer this block uses, so a test can stand in for one."""

    async def start(self) -> None:
        """Connect to the cluster and take a producer id."""
        ...

    async def stop(self) -> None:
        """Flush what is still buffered and close the connection."""
        ...

    async def topics(self) -> set[str]:
        """Every topic the cluster's metadata names."""
        ...

    async def send(
        self,
        topic: str,
        value: bytes | None,
        key: bytes | None = None,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> Awaitable[Any]:
        """Buffer one record and answer with what completes when the broker acknowledges it."""
        ...


class ListingProducer:
    """The client library's producer, plus the topic listing it keeps on its client.

    A producer waits on a topic's metadata for the whole request timeout before it gives up, so
    asking it about a topic nobody created costs forty seconds and answers with a timeout. The
    cluster's metadata answers the same question at once.
    """

    def __init__(self, inner: Any) -> None:
        """Wrap one producer."""
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        """Hand every other call straight to the producer being wrapped."""
        return getattr(self._inner, name)

    async def topics(self) -> set[str]:
        """Every topic the cluster names, fetched rather than read from the client's cache."""
        metadata = await self._inner.client.fetch_all_metadata()
        return cast("set[str]", metadata.topics())


def producer_for(settings: KafkaConnectionConfig, *, acks: Acks) -> Producer:
    """Build the client one step publishes through, with the connection's security applied."""
    from aiokafka import AIOKafkaProducer

    keywords: dict[str, Any] = {
        "bootstrap_servers": list(settings.bootstrap_servers),
        "security_protocol": SECURITY_PROTOCOLS[settings.security],
        "acks": ACKS[acks],
        # The broker drops a duplicate the client itself retried, which the protocol only
        # allows where every write is acknowledged by the whole in-sync set.
        "enable_idempotence": acks == "all",
    }
    if settings.security in TLS_SECURITY:
        keywords["ssl_context"] = ssl.create_default_context(cadata=settings.ca_certificate)
    if settings.security in SASL_SECURITY:
        password = settings.password.get_secret_value() if settings.password else None
        keywords.update(
            sasl_mechanism=settings.sasl_mechanism,
            sasl_plain_username=settings.username,
            sasl_plain_password=password,
        )
    return cast("Producer", ListingProducer(AIOKafkaProducer(**keywords)))


class OutgoingRecord(BlockModel):
    """One record written as an envelope, for a topic where the value alone does not say enough."""

    value: JsonValue = None
    """What the record carries. A string is sent as UTF-8 text and anything else as compact
    JSON, so a topic of JSON documents and a topic of plain lines are both writable. Null sends
    no value at all, which is what a compacted topic reads as a tombstone."""

    key: JsonValue = None
    """The partitioning key, spelled the way a value is. Unset spreads the records across the
    topic's partitions; set puts every record sharing a key on one."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    """Headers sent beside the record, each value UTF-8 text."""


class KafkaProduceConfig(BlockModel):
    """What to publish to which topic, and how sure to be that the broker took it."""

    connection: ConnectionRef
    """The ``kafka`` connection naming the cluster and holding its credential."""

    topic: str = Field(min_length=1)
    """The topic to publish to, which must already exist.

    A name the cluster's metadata does not carry is rejected before a record is sent, on a
    cluster that would have auto-created it as much as on one that would not."""

    records: list[JsonValue]
    """The records to publish, written inline or referenced from an earlier step's output.

    An element is read as an **envelope** when it is an object carrying ``value`` and nothing
    besides ``key``, ``value`` and ``headers``; every other element is itself the value. Two
    shapes rather than one because most topics carry values alone -- a list of JSON documents
    an earlier step produced is publishable unchanged -- while a key or a header has to be
    written somewhere, and the envelope is that place. An object that means to be a value and
    would read as an envelope is written ``{"value": {...}}``. Records held in storage reach
    this through ``storage.read``."""

    key: str | None = None
    """The name of a field of each record's value whose content becomes the message key.

    A record whose envelope names a ``key`` keeps that one. A record that is not an object, or
    that lacks the field, fails the step: a key silently dropped repartitions a topic, which is
    not a thing to discover from the consumer's side a week later."""

    acks: Acks = "all"
    """How many replicas must hold a record before it counts as published.

    ``all`` waits for the whole in-sync set, and is the only setting an idempotent producer
    runs under. ``1`` waits for the leader alone and ``0`` waits for nothing; both give up
    de-duplication with it, so a client retry under either may publish a record twice."""

    timeout: Duration = timedelta(seconds=30)
    """How long the whole publish may take, such as ``30s``, counted from the first send to the
    last acknowledgement. How the records are batched inside it is the client's own."""


class KafkaProduceOutput(BlockModel):
    """What one publish put on the topic, and where the broker put it."""

    produced: int
    """How many records the broker acknowledged."""

    topic: str

    offsets: dict[str, int]
    """The offset of the last record written to each partition, keyed by partition number as a
    string. A partition this publish did not write to is not in the map."""

    duration_ms: int

    sent_bytes: int
    """How many bytes of keys and values were handed to the client."""


class KafkaProduceOperator(Operator[KafkaProduceConfig, KafkaProduceOutput]):
    """Publishes records to a topic and reports what the broker acknowledged.

    The producer is idempotent under the default ``acks: all``: the broker recognises a record
    the client itself retried and writes it once, so a connection that stumbles inside one step
    does not double-publish. That holds for one producer session and no further. A **retry of
    the step** opens a new session with a new producer id, and every record goes again -- the
    broker has no way to tell it is the same batch. A pipeline that must not publish twice
    either does not retry this step, or gives its records keys and lets a compacted topic or
    the reader settle the duplicates.

    It is an **ordinary** block: it reaches its connection's brokers and nothing else.
    """

    spec = OperatorSpec(
        id="kafka.produce",
        summary="Publish records to a Kafka topic.",
        idempotent=False,
    )
    config_model: ClassVar[type[BaseModel]] = KafkaProduceConfig
    output_model: ClassVar[type[BaseModel]] = KafkaProduceOutput

    async def execute(self, config: KafkaProduceConfig, ctx: StepContext) -> KafkaProduceOutput:
        """Publish every record and wait for the acknowledgements."""
        settings = ctx.connection(config.connection, KafkaConnectionConfig)
        started = time.monotonic()
        producer = producer_for(settings, acks=config.acks)
        try:
            await producer.start()
        except Exception as error:
            raise BlockFailure(
                f"the kafka cluster refused the connection: {error}", error_class=classify(error)
            ) from error
        offsets: dict[str, int] = {}
        produced = 0
        sent_bytes = 0
        try:
            async with asyncio.timeout(config.timeout.total_seconds()):
                await _check_topic(producer, config.topic)
                pending: list[Awaitable[Any]] = []
                for record in _outgoing(config):
                    sent, size = await _publish(producer, config.topic, record)
                    pending.append(sent)
                    sent_bytes += size
                    if len(pending) >= IN_FLIGHT:
                        produced += await _settle(pending, offsets)
                        pending = []
                produced += await _settle(pending, offsets)
        except BlockFailure:
            raise
        except TimeoutError as error:
            raise BlockFailure(
                f"publishing to {config.topic!r} did not finish within {config.timeout}",
                error_class=ErrorClass.TRANSIENT,
            ) from error
        except Exception as error:
            raise BlockFailure(
                f"publishing to {config.topic!r} failed: {error}", error_class=classify(error)
            ) from error
        finally:
            await producer.stop()
        ctx.log.info("produced", topic=config.topic, produced=produced, sent_bytes=sent_bytes)
        return KafkaProduceOutput(
            produced=produced,
            topic=config.topic,
            offsets=offsets,
            duration_ms=int((time.monotonic() - started) * 1000),
            sent_bytes=sent_bytes,
        )

    def classify_error(self, error: Exception) -> ErrorClass:
        """A cluster that could not be reached is transient; one that said no is not."""
        return classify(error)


async def _check_topic(producer: Producer, topic: str) -> None:
    """Refuse a topic the cluster does not have, before a record is handed to the client."""
    if topic not in await producer.topics():
        raise BlockFailure(f"the cluster has no topic {topic!r}", error_class=ErrorClass.REJECTED)


def _outgoing(config: KafkaProduceConfig) -> Iterator[OutgoingRecord]:
    """Read each configured element as the record it means, keyed as the step asked."""
    for element in config.records:
        yield _keyed(_envelope(element), config.key)


def _envelope(element: JsonValue) -> OutgoingRecord:
    """Read one element as the envelope it is, or as the value it otherwise means."""
    if isinstance(element, dict) and "value" in element and element.keys() <= ENVELOPE:
        try:
            return OutgoingRecord.model_validate(element)
        except ValidationError as error:
            raise BlockFailure(
                f"a record envelope is not one this step can send: {error}",
                error_class=ErrorClass.REJECTED,
            ) from error
    return OutgoingRecord(value=element)


def _keyed(record: OutgoingRecord, field: str | None) -> OutgoingRecord:
    """Take a record's key from a named field of its value, leaving one it already carries."""
    if field is None or record.key is not None:
        return record
    if not isinstance(record.value, dict) or field not in record.value:
        raise BlockFailure(f"a record has no field {field!r} to take its key from", error_class=ErrorClass.REJECTED)
    return record.model_copy(update={"key": record.value[field]})


async def _publish(producer: Producer, topic: str, record: OutgoingRecord) -> tuple[Awaitable[Any], int]:
    """Hand one record to the client, and say how many bytes of it went."""
    value = encode(record.value)
    key = encode(record.key)
    headers = [(name, text.encode("utf-8")) for name, text in record.headers.items()]
    sent = await producer.send(topic, value=value, key=key, headers=headers or None)
    return sent, len(value or b"") + len(key or b"")


async def _settle(pending: list[Awaitable[Any]], offsets: dict[str, int]) -> int:
    """Wait for a group of sends and write down where each partition ended."""
    for metadata in await asyncio.gather(*pending):
        offsets[str(metadata.partition)] = metadata.offset
    return len(pending)


def encode(value: JsonValue) -> bytes | None:
    """Write one record part: a string as UTF-8 text, anything else as compact JSON."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


async def close(consumer: Consumer) -> None:
    """Close a consumer without letting the client library's own cancellation out.

    Closing a consumer that joined no group cancels an internal task and then awaits it, so the
    CancelledError that ends that task escapes as though this step had been cancelled. Only a
    cancellation actually aimed at this task is passed on.
    """
    try:
        await consumer.stop()
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is None or task.cancelling() > 0:
            raise


def read_cursor(cursor: dict[str, JsonValue] | None) -> dict[str, int]:
    """The offsets a poke starts from: what the last committed one wrote, or nothing."""
    held = (cursor or {}).get("offsets")
    if not isinstance(held, dict):
        return {}
    return {str(partition): int(cast("int", offset)) for partition, offset in held.items()}


async def _position(consumer: Consumer, config: KafkaConsumeConfig, offsets: dict[str, int]) -> None:
    """Point the consumer at what to read next, by cursor, by group, or by the start setting.

    Fetching the topic's metadata is also what proves it exists, so it happens before either
    route: a document naming a topic nobody created is refused rather than waiting forever.
    """
    from aiokafka import TopicPartition

    await consumer.prime(config.topic)
    partitions = consumer.partitions_for_topic(config.topic)
    if not partitions:
        raise BlockFailure(f"the cluster has no topic {config.topic!r}", error_class=ErrorClass.REJECTED)
    if config.group_id is not None and not offsets:
        consumer.subscribe([config.topic])
        return
    assigned = [TopicPartition(config.topic, number) for number in sorted(partitions)]
    consumer.assign(assigned)
    for partition in assigned:
        held = offsets.get(str(partition.partition))
        if held is not None:
            consumer.seek(partition, held)
            continue
        if config.start == "earliest":
            await consumer.seek_to_beginning(partition)
        else:
            await consumer.seek_to_end(partition)
        # Where a first poke stood is its cursor, whether or not it read anything: without
        # this a poke that found an empty topic would seek to the end again and never see the
        # message that arrived between the two.
        offsets[str(partition.partition)] = await consumer.position(partition)


async def _record_unfetched(consumer: Consumer, config: KafkaConsumeConfig, offsets: dict[str, int]) -> None:
    """Write down where a partition the fetch handed nothing back from stands.

    A poke that subscribes takes its position from the broker rather than from a seek, so it is
    the fetch that settles where it is. Without this a group's poke that read nothing would
    park with an empty cursor, and the next one would join the group and reset to ``start``
    again, past whatever arrived in between.
    """
    for partition in consumer.assignment():
        if partition.topic != config.topic or str(partition.partition) in offsets:
            continue
        offsets[str(partition.partition)] = await consumer.position(partition)


def _read(
    fetched: dict[Any, list[Any]],
    config: KafkaConsumeConfig,
    offsets: dict[str, int],
) -> list[KafkaMessage]:
    """Turn what the broker handed back into messages, advancing the offsets as it goes."""
    messages: list[KafkaMessage] = []
    for partition, records in sorted(fetched.items(), key=lambda pair: pair[0].partition):
        if records:
            # Where the partition stood before anything was taken, so a batch cut short by
            # max_messages leaves the rest to be read again rather than seeked past.
            offsets.setdefault(str(partition.partition), records[0].offset)
        for record in records:
            if len(messages) >= config.max_messages:
                return messages
            messages.append(
                KafkaMessage(
                    topic=record.topic,
                    partition=record.partition,
                    offset=record.offset,
                    key=decode(record.key, config.key_format, "key"),
                    value=decode(record.value, config.value_format, "value"),
                    timestamp=datetime.fromtimestamp(record.timestamp / 1000, tz=UTC),
                    headers={name: _text(value) for name, value in (record.headers or ())},
                )
            )
            offsets[str(partition.partition)] = record.offset + 1
    return messages


def decode(raw: bytes | None, form: Payload, what: str) -> JsonValue:
    """Read one message part the way the config says it is written."""
    if raw is None:
        return None
    if form == "base64":
        return base64.b64encode(raw).decode("ascii")
    if form == "text":
        return _text(raw)
    try:
        return cast("JsonValue", json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BlockFailure(
            f"a message {what} is not the json this step reads: {error}",
            error_class=ErrorClass.REJECTED,
        ) from error


def _text(raw: bytes) -> str:
    """Decode bytes as text, keeping what a broker sent even when it is not valid UTF-8."""
    return raw.decode("utf-8", errors="replace")


def classify(error: Exception) -> ErrorClass:
    """A broker that could not be reached is transient; a refusal or a missing topic is not."""
    if isinstance(error, BlockFailure):
        return error.error_class
    text = f"{type(error).__name__}: {error}".lower()
    if any(marker in text for marker in REFUSED):
        return ErrorClass.REJECTED
    if any(marker in text for marker in UNREACHABLE):
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN
