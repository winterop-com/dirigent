"""The RabbitMQ blocks: wait for messages on a queue, and put one on an exchange.

A queue and a webhook are the same intent arriving by different transport, so a queue starts a
run the way a clock or a POST does: each poke takes what is there and succeeds the moment
there is enough, handing the batch downstream as its output.

Unlike a Kafka topic, a RabbitMQ queue keeps its own place: a message is held unacknowledged
until it is acked or nacked, so the broker rather than the cursor is the bookkeeping. What the
sensor decides is *when* to acknowledge, and the default is ``on_success``: a poke that parks
nacks everything it took back onto the queue with ``requeue``, so a batch too small to act on
is left for the next poke or another consumer rather than swallowed. The cursor here carries
nothing the sensor needs, only what a reader wants -- how many messages have gone past and the
last delivery tag seen.

``rabbitmq.publish`` goes the other way, and is the sink an upstream step hands a value to: it
puts one message on an exchange, or on the default exchange where a routing key is a queue name.

They are **ordinary** blocks: each reaches its connection's broker and nothing else.
"""

import asyncio
import base64
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, Protocol, cast
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, Field, JsonValue, SecretStr, model_validator

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

#: What a string body is sent as when the step names no content type.
TEXT_CONTENT_TYPE = "text/plain"

#: What any other body is sent as when the step names no content type.
JSON_CONTENT_TYPE = "application/json"

#: The two schemes an AMQP URL is written with: plain, and TLS.
AMQP_SCHEMES = ("amqp", "amqps")

#: How long a poke sleeps before asking an empty queue again.
IDLE_SLEEP = timedelta(milliseconds=250)

#: What a broker's error says when reaching it, rather than the request, is the problem.
UNREACHABLE = ("connection", "timeout", "timed out", "unreachable", "refused", "closed")

#: What a broker's error says when the request was understood and refused.
REFUSED = ("authentication", "access_refused", "access refused", "not_found", "no queue", "not found", "precondition")

type Payload = Literal["json", "text", "base64"]


class RabbitConnectionConfig(BlockModel):
    """One RabbitMQ broker, and the password that reaches it."""

    url: str = Field(min_length=1)
    """Where the broker is, as ``amqp://user@host:5672/vhost`` or the ``amqps://`` form.

    A URL carrying a password inline is refused: the secret belongs in ``password``, where it
    is encrypted at rest and redacted in every API response, and a plain field is neither."""

    password: SecretStr | None = None
    """The password, sealed, merged into the URL when a connection is opened and nowhere else."""

    @model_validator(mode="after")
    def _check_shape(self) -> "RabbitConnectionConfig":
        """Refuse a scheme that is not AMQP, and a password written into the URL."""
        split = urlsplit(self.url)
        if split.scheme not in AMQP_SCHEMES:
            raise ValueError(f"a rabbitmq url is amqp or amqps, and {self.url!r} is neither")
        if split.password is not None:
            raise ValueError(
                "this url carries a password inline, where it would sit unencrypted in a plain "
                "field; take it out of the url and set the sealed password field instead"
            )
        return self

    def dsn(self) -> str:
        """The URL a client is given, with the sealed password merged into it."""
        if self.password is None:
            return self.url
        split = urlsplit(self.url)
        user = quote(split.username or "guest", safe="")
        secret = quote(self.password.get_secret_value(), safe="")
        host = split.hostname or "localhost"
        authority = f"{user}:{secret}@{host}" + (f":{split.port}" if split.port else "")
        return urlunsplit(split._replace(netloc=authority))


class Delivery(Protocol):
    """The part of an incoming message this block uses, so a test can stand in for one."""

    body: bytes
    routing_key: str | None
    exchange: str | None
    delivery_tag: int | None
    headers: dict[str, Any]
    timestamp: datetime | None

    async def ack(self) -> None:
        """Tell the broker the message is dealt with and may be dropped."""
        ...

    async def nack(self, *, requeue: bool = True) -> None:
        """Hand the message back, so it is delivered again."""
        ...


class Queue(Protocol):
    """The part of a declared queue this block uses."""

    async def get(self, *, fail: bool = False, no_ack: bool = False) -> Delivery | None:
        """Take the next message, or answer None when the queue is empty."""
        ...


class Exchange(Protocol):
    """The part of an exchange this block uses."""

    async def publish(self, message: Any, routing_key: str, *, mandatory: bool = False) -> Any:
        """Put one message on the exchange under a routing key."""
        ...


class Channel(Protocol):
    """The part of a channel this block uses."""

    default_exchange: Exchange
    """The nameless exchange, where a routing key is a queue name."""

    async def get_queue(self, name: str, *, ensure: bool = True) -> Queue:
        """Look a queue up, declaring passively so a missing one is an error rather than a creation."""
        ...

    async def get_exchange(self, name: str, *, ensure: bool = True) -> Exchange:
        """Look an exchange up, declaring passively so a missing one is an error rather than a creation."""
        ...


class Connection(Protocol):
    """The part of a connection this block uses."""

    async def channel(self) -> Channel:
        """Open a channel on the connection."""
        ...

    async def close(self) -> None:
        """Close the connection and everything on it."""
        ...


async def connect(settings: RabbitConnectionConfig) -> Connection:
    """Open the connection one poke works through, with the sealed password merged in."""
    import aio_pika

    return cast("Connection", await aio_pika.connect(settings.dsn()))


class RabbitConnectionKind(ConnectionKind):
    """The connection kind ``rabbitmq.consume`` resolves its broker and credential through."""

    id: ClassVar[str] = "rabbitmq"
    config_model: ClassVar[type[BaseModel]] = RabbitConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Open a connection and a channel, which is the smallest thing that proves reach and credential."""
        settings = RabbitConnectionConfig.model_validate(config.model_dump())
        try:
            connection = await connect(settings)
            try:
                await connection.channel()
            finally:
                await connection.close()
        except Exception as error:  # every client error is a health answer, never a raise
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        return HealthReport(healthy=True, detail="a channel opened")


class RabbitConsumeConfig(BlockModel):
    """Which queue to wait on, how much to take, and when to acknowledge it."""

    connection: ConnectionRef
    """The ``rabbitmq`` connection naming the broker and holding its password."""

    queue: str = Field(min_length=1)
    """The queue to read. It must already exist: this block declares nothing."""

    min_messages: int = Field(default=1, ge=1)
    """How many messages a batch needs before the sensor succeeds."""

    max_messages: int = Field(default=100, ge=1)
    """The most messages one poke takes, which bounds the output a step carries."""

    poll_timeout: Duration = timedelta(seconds=5)
    """How long one poke waits on the broker before answering with what it has, such as ``5s``."""

    poll_every: Duration | None = None
    """How long to park between pokes; unset leaves the cadence to the step's own ``poll``."""

    ack: Literal["on_success", "always"] = "on_success"
    """When a message is acknowledged.

    ``on_success`` acknowledges only in the poke that succeeds, and a poke that parks nacks what
    it took back onto the queue with ``requeue``, so nothing is lost to a batch that was too
    small and another consumer may take it instead. ``always`` acknowledges every message the
    moment it is taken, which suits a queue nothing else reads and a step that would rather
    drop a partial batch than see it twice."""

    value_format: Payload = "json"
    """How a message body is decoded."""

    @model_validator(mode="after")
    def _check_shape(self) -> "RabbitConsumeConfig":
        """Refuse a batch that can never reach the size it is waiting for."""
        if self.min_messages > self.max_messages:
            raise ValueError(
                f"min_messages {self.min_messages} is above max_messages {self.max_messages}, "
                "so this sensor would wait for a batch it never takes"
            )
        return self


class RabbitMessage(BlockModel):
    """One message, as a downstream step reads it."""

    routing_key: str | None = None
    exchange: str | None = None
    delivery_tag: int | None = None
    body: JsonValue = None
    headers: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    timestamp: datetime | None = None
    """When the publisher stamped the message, when it stamped one at all."""


class RabbitConsumeOutput(BlockModel):
    """The batch a poke succeeded on."""

    messages: list[RabbitMessage]
    count: int


class RabbitConsumeSensor(Sensor[RabbitConsumeConfig, RabbitConsumeOutput]):
    """Waits for messages on a queue; each poke is one bounded drain of what is there."""

    spec = SensorSpec(
        id="rabbitmq.consume",
        summary="Wait for messages on a RabbitMQ queue.",
        default_poll=timedelta(seconds=30),
    )
    config_model: ClassVar[type[BaseModel]] = RabbitConsumeConfig
    output_model: ClassVar[type[BaseModel]] = RabbitConsumeOutput

    async def poke(self, config: RabbitConsumeConfig, ctx: StepContext) -> RabbitConsumeOutput | NotYet:
        """Take what is on the queue, and either succeed on it or hand it back."""
        settings = ctx.connection(config.connection, RabbitConnectionConfig)
        try:
            connection = await connect(settings)
        except Exception as error:
            raise BlockFailure(
                f"the rabbitmq broker refused the connection: {error}", error_class=classify(error)
            ) from error
        try:
            queue = await _queue(connection, config)
            taken = await _drain(queue, config)
            if config.ack == "always":
                for delivery in taken:
                    await delivery.ack()
            if len(taken) < config.min_messages:
                if config.ack == "on_success":
                    for delivery in taken:
                        await delivery.nack(requeue=True)
                ctx.log.debug(
                    "not enough on the queue yet",
                    queue=config.queue,
                    count=len(taken),
                    min_messages=config.min_messages,
                )
                return NotYet(
                    cursor=_cursor(ctx.cursor, taken),
                    next_poll_in=config.poll_every,
                    message=f"{len(taken)} of {config.min_messages} messages",
                )
            if config.ack == "on_success":
                for delivery in taken:
                    await delivery.ack()
            messages = [_read(delivery, config) for delivery in taken]
            ctx.log.info("consumed", queue=config.queue, count=len(messages), ack=config.ack)
            return RabbitConsumeOutput(messages=messages, count=len(messages))
        except BlockFailure:
            raise
        except Exception as error:
            raise BlockFailure(f"reading {config.queue!r} failed: {error}", error_class=classify(error)) from error
        finally:
            await connection.close()

    def classify_error(self, error: Exception) -> ErrorClass:
        """A broker that could not be reached is transient; one that said no is not."""
        return classify(error)


async def _queue(connection: Connection, config: RabbitConsumeConfig) -> Queue:
    """Look the queue up, saying which one is missing when the broker has no such queue."""
    channel = await connection.channel()
    try:
        return await channel.get_queue(config.queue, ensure=True)
    except Exception as error:
        raise BlockFailure(
            f"the broker has no queue {config.queue!r}: {error}",
            error_class=ErrorClass.REJECTED,
        ) from error


async def _drain(queue: Queue, config: RabbitConsumeConfig) -> list[Delivery]:
    """Take up to the batch size, waiting no longer than the poke's own timeout."""
    deadline = time.monotonic() + config.poll_timeout.total_seconds()
    taken: list[Delivery] = []
    while len(taken) < config.max_messages:
        delivery = await queue.get(fail=False, no_ack=False)
        if delivery is not None:
            taken.append(delivery)
            continue
        if len(taken) >= config.min_messages:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(IDLE_SLEEP.total_seconds(), remaining))
    return taken


def _cursor(held: dict[str, JsonValue] | None, taken: list[Delivery]) -> dict[str, JsonValue]:
    """What a reader is told about a wait the broker is doing the bookkeeping for."""
    seen = int(cast("int", (held or {}).get("seen", 0))) + len(taken)
    tag = taken[-1].delivery_tag if taken else (held or {}).get("last_delivery_tag")
    return {"seen": seen, "last_delivery_tag": tag}


def _read(delivery: Delivery, config: RabbitConsumeConfig) -> RabbitMessage:
    """Turn one delivery into the message a downstream step reads."""
    return RabbitMessage(
        routing_key=delivery.routing_key,
        exchange=delivery.exchange,
        delivery_tag=delivery.delivery_tag,
        body=decode(delivery.body, config.value_format),
        headers={str(name): _plain(value) for name, value in (delivery.headers or {}).items()},
        timestamp=_stamp(delivery.timestamp),
    )


def _stamp(value: datetime | None) -> datetime | None:
    """A publisher's timestamp, given the timezone AMQP leaves off it."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _plain(value: Any) -> JsonValue:
    """One header value, as JSON carries it; anything exotic becomes its own text."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def decode(raw: bytes, form: Payload) -> JsonValue:
    """Read a message body the way the config says it is written."""
    if form == "base64":
        return base64.b64encode(raw).decode("ascii")
    if form == "text":
        return raw.decode("utf-8", errors="replace")
    try:
        return cast("JsonValue", json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BlockFailure(
            f"a message body is not the json this step reads: {error}",
            error_class=ErrorClass.REJECTED,
        ) from error


class RabbitPublishConfig(BlockModel):
    """What to publish, where to put it, and how durably."""

    connection: ConnectionRef
    """The ``rabbitmq`` connection naming the broker and holding its password."""

    exchange: str = ""
    """The exchange to publish to; empty is the default exchange, where a routing key is a queue."""

    routing_key: str = Field(min_length=1)
    """What the broker routes the message by, which on the default exchange is a queue name."""

    message: JsonValue
    """The body: a string is sent as UTF-8 text, anything else as canonical JSON."""

    content_type: str | None = None
    """What the body is, sent with the message.

    Unset, it is ``text/plain`` for a string and ``application/json`` for anything else; an
    explicit one wins, which is how a markdown page or a csv says what it is."""

    persistent: bool = True
    """Whether the broker writes the message to disk, so a durable queue keeps it across a restart."""

    timeout: Duration = timedelta(seconds=30)
    """How long the whole publish may take, such as ``30s``."""

    def payload(self) -> bytes:
        """The bytes this step sends, in the encoding its content type promises."""
        if isinstance(self.message, str):
            return self.message.encode()
        # The engine's canonical JSON: sorted keys and no spaces, written as UTF-8.
        return json.dumps(self.message, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def declared_content_type(self) -> str:
        """What the body is: the step's own answer, or the default for what it carries."""
        if self.content_type is not None:
            return self.content_type
        return TEXT_CONTENT_TYPE if isinstance(self.message, str) else JSON_CONTENT_TYPE


class RabbitPublishOutput(BlockModel):
    """What one publish put on the broker."""

    published: int
    """How many messages the broker took, which is one."""

    message_bytes: int


class RabbitPublishOperator(Operator[RabbitPublishConfig, RabbitPublishOutput]):
    """Publishes one message to an exchange and reports what it sent.

    A publish is not idempotent: the broker has no way to tell a message from the same message
    sent again, so a retry of this step puts a second copy on the queue. A pipeline that must
    not publish twice either does not retry it, or gives the consumer a key to settle the
    duplicates by.

    It is an **ordinary** block: it reaches its connection's broker and nothing else.
    """

    spec = OperatorSpec(id="rabbitmq.publish", summary="Publish one message to an exchange.", idempotent=False)
    config_model: ClassVar[type[BaseModel]] = RabbitPublishConfig
    output_model: ClassVar[type[BaseModel]] = RabbitPublishOutput

    async def execute(self, config: RabbitPublishConfig, ctx: StepContext) -> RabbitPublishOutput:
        """Open a channel, put one message on the exchange, and wait for the broker to take it."""
        from aio_pika.exceptions import DeliveryError

        settings = ctx.connection(config.connection, RabbitConnectionConfig)
        try:
            connection = await connect(settings)
        except Exception as error:
            raise BlockFailure(
                f"the rabbitmq broker refused the connection: {error}", error_class=classify(error)
            ) from error
        body = config.payload()
        content_type = config.declared_content_type()
        try:
            async with asyncio.timeout(config.timeout.total_seconds()):
                channel = await connection.channel()
                exchange = await _exchange(channel, config)
                # Mandatory: a routing key no queue answers to is refused by the broker rather
                # than dropped, which on the default exchange is a queue that does not exist.
                await exchange.publish(
                    _message(body, content_type, persistent=config.persistent), config.routing_key, mandatory=True
                )
        except BlockFailure:
            raise
        except DeliveryError as error:
            raise BlockFailure(
                f"nothing on exchange {config.exchange!r} takes routing key {config.routing_key!r}: "
                "declare the queue, or name an exchange it is bound to",
                error_class=ErrorClass.REJECTED,
            ) from error
        except TimeoutError as error:
            raise BlockFailure(
                f"publishing to {config.routing_key!r} did not finish within {config.timeout}",
                error_class=ErrorClass.TRANSIENT,
            ) from error
        except Exception as error:
            raise BlockFailure(
                f"publishing to {config.routing_key!r} failed: {error}", error_class=classify(error)
            ) from error
        finally:
            await connection.close()
        ctx.log.info(
            "published",
            exchange=config.exchange,
            routing_key=config.routing_key,
            message_bytes=len(body),
            content_type=content_type,
        )
        return RabbitPublishOutput(published=1, message_bytes=len(body))

    def classify_error(self, error: Exception) -> ErrorClass:
        """A broker that could not be reached is transient; one that said no is not."""
        return classify(error)


async def _exchange(channel: Channel, config: RabbitPublishConfig) -> Exchange:
    """Resolve the exchange, saying which one is missing when the broker has no such exchange."""
    if not config.exchange:
        return channel.default_exchange
    try:
        return await channel.get_exchange(config.exchange, ensure=True)
    except Exception as error:
        raise BlockFailure(
            f"the broker has no exchange {config.exchange!r}: {error}",
            error_class=ErrorClass.REJECTED,
        ) from error


def _message(body: bytes, content_type: str, *, persistent: bool) -> Any:
    """Build the message the client sends, stamped with what the body is and how durable it is."""
    import aio_pika

    delivery = aio_pika.DeliveryMode.PERSISTENT if persistent else aio_pika.DeliveryMode.NOT_PERSISTENT
    return aio_pika.Message(body=body, content_type=content_type, delivery_mode=delivery)


def classify(error: Exception) -> ErrorClass:
    """A broker that could not be reached is transient; a refusal or a missing queue is not."""
    if isinstance(error, BlockFailure):
        return error.error_class
    text = f"{type(error).__name__}: {error}".lower()
    if any(marker in text for marker in REFUSED):
        return ErrorClass.REJECTED
    if any(marker in text for marker in UNREACHABLE):
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN
