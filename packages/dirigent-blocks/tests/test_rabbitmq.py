"""Tests for the rabbitmq blocks, against a fake broker rather than a real one."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import aio_pika.exceptions
import pytest
from aio_pika import DeliveryMode
from pydantic import SecretStr, ValidationError

from dirigent_blocks import rabbitmq
from dirigent_blocks.rabbitmq import (
    RabbitConnectionConfig,
    RabbitConnectionKind,
    RabbitConsumeConfig,
    RabbitConsumeSensor,
    RabbitPublishConfig,
    RabbitPublishOperator,
    RabbitPublishOutput,
    classify,
)
from dirigent_plugin import BlockFailure, ErrorClass, NotYet
from dirigent_testing import FakeContext, call_block

#: When every fake delivery says it was published.
STAMPED = datetime(2026, 6, 1, 12, tzinfo=UTC)


class FakeDelivery:
    """One message the broker handed over, remembering how it was settled."""

    def __init__(self, tag: int, body: bytes, *, headers: dict[str, Any] | None = None) -> None:
        """Hold one delivery, unsettled until the block acks or nacks it."""
        self.delivery_tag = tag
        self.body = body
        self.routing_key = "orders.new"
        self.exchange = "shop"
        self.headers = headers if headers is not None else {}
        self.timestamp = STAMPED
        self.settled: str | None = None

    async def ack(self) -> None:
        self.settled = "ack"

    async def nack(self, *, requeue: bool = True) -> None:
        self.settled = f"nack requeue={requeue}"


class FakeBroker:
    """A broker of one queue, handing deliveries out in order and recording what was asked of it."""

    def __init__(self) -> None:
        """Start with an empty queue and nothing taken from it."""
        self.queued: list[FakeDelivery] = []
        self.known = {"orders"}
        self.exchanges = {"shop"}
        self.taken: list[FakeDelivery] = []
        self.published: list[tuple[str, Any]] = []
        # The routing keys something is bound to; None means the broker routes everything.
        self.routes: set[str] | None = None
        self.closed = False
        self.dsn: str | None = None
        self.fail_on_connect: Exception | None = None

    async def channel(self) -> "FakeBroker":
        return self

    async def close(self) -> None:
        self.closed = True

    async def get_queue(self, name: str, *, ensure: bool = True) -> "FakeBroker":
        if name not in self.known:
            raise RuntimeError(f"NOT_FOUND - no queue '{name}'")
        return self

    @property
    def default_exchange(self) -> "FakeBroker":
        return self

    async def get_exchange(self, name: str, *, ensure: bool = True) -> "FakeBroker":
        if name not in self.exchanges:
            raise RuntimeError(f"NOT_FOUND - no exchange '{name}'")
        return self

    async def publish(self, message: Any, routing_key: str, *, mandatory: bool = False) -> None:
        if mandatory and self.routes is not None and routing_key not in self.routes:
            raise aio_pika.exceptions.DeliveryError(message, cast("Any", None))
        self.published.append((routing_key, message))

    async def get(self, *, fail: bool = False, no_ack: bool = False) -> FakeDelivery | None:
        if not self.queued:
            return None
        delivery = self.queued.pop(0)
        self.taken.append(delivery)
        return delivery


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> FakeBroker:
    """Install one fake broker in place of the client library, and hand it to the test."""
    fake = FakeBroker()

    async def connect(settings: RabbitConnectionConfig) -> FakeBroker:
        if fake.fail_on_connect is not None:
            raise fake.fail_on_connect
        fake.dsn = settings.dsn()
        return fake

    monkeypatch.setattr(rabbitmq, "connect", connect)
    return fake


def connected(ctx: FakeContext) -> FakeContext:
    """Give the fake context the rabbitmq connection every config below names."""
    ctx.connections["broker"] = RabbitConnectionConfig(url="amqp://reader@localhost:5672/shop")
    return ctx


def config(**overrides: Any) -> RabbitConsumeConfig:
    """One consume config, with the fields a test does not care about already filled in."""
    return RabbitConsumeConfig.model_validate(
        {"connection": "broker", "queue": "orders", "poll_timeout": "0s", **overrides}
    )


# -- the connection kind ---------------------------------------------------------


def test_a_url_that_is_not_amqp_is_refused() -> None:
    with pytest.raises(ValidationError, match="is amqp or amqps"):
        RabbitConnectionConfig(url="https://localhost/shop")


def test_a_password_written_into_the_url_is_refused() -> None:
    with pytest.raises(ValidationError, match="carries a password inline"):
        RabbitConnectionConfig(url="amqp://reader:s3cret@localhost/shop")


def test_the_sealed_password_is_merged_in_only_at_connect_time() -> None:
    settings = RabbitConnectionConfig(url="amqp://reader@localhost:5672/shop", password=SecretStr("s3 cret"))

    assert "s3" not in settings.url
    assert "s3 cret" not in repr(settings)
    assert settings.dsn() == "amqp://reader:s3%20cret@localhost:5672/shop"


def test_a_connection_with_no_password_is_handed_over_as_written() -> None:
    settings = RabbitConnectionConfig(url="amqp://guest@localhost/shop")

    assert settings.dsn() == "amqp://guest@localhost/shop"


async def test_a_health_check_opens_a_channel(broker: FakeBroker) -> None:
    report = await RabbitConnectionKind().check(RabbitConnectionConfig(url="amqp://guest@localhost/"))

    assert (report.healthy, report.detail) == (True, "a channel opened")
    assert broker.closed


async def test_a_health_check_answers_rather_than_raises_when_the_broker_is_down(broker: FakeBroker) -> None:
    broker.fail_on_connect = ConnectionError("connection refused")

    report = await RabbitConnectionKind().check(RabbitConnectionConfig(url="amqp://guest@localhost/"))

    assert report.healthy is False
    assert "connection refused" in (report.detail or "")


# -- the sensor ------------------------------------------------------------------


async def test_an_empty_queue_parks_and_takes_nothing(ctx: FakeContext, broker: FakeBroker) -> None:
    parked = await RabbitConsumeSensor().poke(config(), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert parked.cursor == {"seen": 0, "last_delivery_tag": None}
    assert broker.taken == []


async def test_a_batch_at_the_minimum_succeeds_and_reads_the_message(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b'{"id": 1}', headers={"source": b"till"})]

    output = await RabbitConsumeSensor().poke(config(), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert output.count == 1
    message = output.messages[0]
    assert (message.body, message.routing_key, message.exchange) == ({"id": 1}, "orders.new", "shop")
    assert (message.delivery_tag, message.headers, message.timestamp) == (1, {"source": "till"}, STAMPED)


async def test_the_batch_never_runs_past_max_messages(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(tag, b"{}") for tag in range(1, 11)]

    output = await RabbitConsumeSensor().poke(config(max_messages=4), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert output.count == 4
    assert len(broker.queued) == 6, "what was not taken is still on the queue"


async def test_a_batch_that_can_never_be_taken_is_refused_at_apply() -> None:
    with pytest.raises(ValidationError, match="above max_messages"):
        config(min_messages=10, max_messages=2)


async def test_the_cursor_counts_what_has_gone_past_for_a_reader(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(7, b"{}")]
    ready = connected(ctx)
    ready.cursor = {"seen": 3, "last_delivery_tag": 6}

    parked = await RabbitConsumeSensor().poke(config(min_messages=5), ready.as_context())

    assert isinstance(parked, NotYet)
    assert parked.cursor == {"seen": 4, "last_delivery_tag": 7}


# -- when a message is acknowledged ----------------------------------------------


async def test_on_success_acks_only_in_the_poke_that_succeeded(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b"{}"), FakeDelivery(2, b"{}")]

    await RabbitConsumeSensor().poke(config(min_messages=2), connected(ctx).as_context())

    assert [delivery.settled for delivery in broker.taken] == ["ack", "ack"]


async def test_on_success_hands_a_batch_that_was_too_small_back_to_the_queue(
    ctx: FakeContext, broker: FakeBroker
) -> None:
    broker.queued = [FakeDelivery(1, b"{}")]

    parked = await RabbitConsumeSensor().poke(config(min_messages=3), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert [delivery.settled for delivery in broker.taken] == ["nack requeue=True"]


async def test_always_acks_a_batch_that_was_too_small_too(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b"{}")]

    parked = await RabbitConsumeSensor().poke(config(min_messages=3, ack="always"), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert [delivery.settled for delivery in broker.taken] == ["ack"]


# -- how a message is read -------------------------------------------------------


async def test_a_text_format_hands_the_body_over_as_a_string(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b"not json at all")]

    output = await RabbitConsumeSensor().poke(config(value_format="text"), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert output.messages[0].body == "not json at all"


async def test_a_base64_format_carries_any_bytes_through(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b"\xff\xfe")]

    output = await RabbitConsumeSensor().poke(config(value_format="base64"), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert output.messages[0].body == "//4="


async def test_a_body_that_is_not_the_json_it_was_promised_is_rejected(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b"not json at all")]

    with pytest.raises(BlockFailure) as raised:
        await RabbitConsumeSensor().poke(config(), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


# -- what went wrong -------------------------------------------------------------


async def test_a_queue_the_broker_does_not_have_is_rejected_by_name(ctx: FakeContext, broker: FakeBroker) -> None:
    with pytest.raises(BlockFailure, match="no queue 'missing'") as raised:
        await RabbitConsumeSensor().poke(config(queue="missing"), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_broker_that_cannot_be_reached_is_transient(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.fail_on_connect = ConnectionError("connection refused")

    with pytest.raises(BlockFailure) as raised:
        await RabbitConsumeSensor().poke(config(), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.TRANSIENT


async def test_an_auth_failure_is_rejected_rather_than_retried(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.fail_on_connect = RuntimeError("ACCESS_REFUSED - Login was refused")

    with pytest.raises(BlockFailure) as raised:
        await RabbitConsumeSensor().poke(config(), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


def test_an_error_nobody_recognises_stays_unknown() -> None:
    assert classify(RuntimeError("something else entirely")) is ErrorClass.UNKNOWN
    assert RabbitConsumeSensor().classify_error(TimeoutError("timed out")) is ErrorClass.TRANSIENT


async def test_the_connection_is_closed_however_the_poke_left(ctx: FakeContext, broker: FakeBroker) -> None:
    broker.queued = [FakeDelivery(1, b"not json at all")]

    with pytest.raises(BlockFailure):
        await RabbitConsumeSensor().poke(config(), connected(ctx).as_context())

    assert broker.closed


def test_a_poll_timeout_is_written_as_a_duration() -> None:
    assert config(poll_timeout="2s").poll_timeout == timedelta(seconds=2)


# -- the publish operator --------------------------------------------------------


async def test_a_publish_puts_one_message_on_the_default_exchange(ctx: FakeContext, broker: FakeBroker) -> None:
    output = await call_block(
        RabbitPublishOperator(),
        {"connection": "broker", "routing_key": "shop-orders", "message": {"order": 1}},
        connected(ctx),
    )

    assert isinstance(output, RabbitPublishOutput)
    assert (output.published, output.message_bytes) == (1, 11)
    routing_key, message = broker.published[0]
    assert (routing_key, message.body) == ("shop-orders", b'{"order":1}')
    assert (message.content_type, message.delivery_mode) == ("application/json", DeliveryMode.PERSISTENT)
    assert broker.closed


async def test_a_string_is_sent_as_text_and_anything_else_as_json(ctx: FakeContext, broker: FakeBroker) -> None:
    await call_block(
        RabbitPublishOperator(),
        {"connection": "broker", "routing_key": "shop-orders", "message": "# a report\n"},
        connected(ctx),
    )

    _, message = broker.published[0]
    assert (message.body, message.content_type) == (b"# a report\n", "text/plain")


async def test_a_content_type_the_step_names_wins(ctx: FakeContext, broker: FakeBroker) -> None:
    await call_block(
        RabbitPublishOperator(),
        {
            "connection": "broker",
            "routing_key": "shop-orders",
            "message": "# a report",
            "content_type": "text/markdown",
        },
        connected(ctx),
    )

    _, message = broker.published[0]
    assert message.content_type == "text/markdown"


async def test_a_message_the_broker_need_not_keep_says_so(ctx: FakeContext, broker: FakeBroker) -> None:
    await call_block(
        RabbitPublishOperator(),
        {"connection": "broker", "routing_key": "shop-orders", "message": "hi", "persistent": False},
        connected(ctx),
    )

    _, message = broker.published[0]
    assert message.delivery_mode is DeliveryMode.NOT_PERSISTENT


async def test_a_named_exchange_is_the_one_the_message_goes_to(ctx: FakeContext, broker: FakeBroker) -> None:
    await call_block(
        RabbitPublishOperator(),
        {"connection": "broker", "exchange": "shop", "routing_key": "orders.new", "message": {"order": 1}},
        connected(ctx),
    )

    assert broker.published[0][0] == "orders.new"


async def test_an_exchange_the_broker_does_not_have_is_rejected_by_name(ctx: FakeContext, broker: FakeBroker) -> None:
    with pytest.raises(BlockFailure, match="no exchange 'missing'") as raised:
        await call_block(
            RabbitPublishOperator(),
            {"connection": "broker", "exchange": "missing", "routing_key": "orders.new", "message": {}},
            connected(ctx),
        )

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_broker_that_refuses_the_publish_connection_is_classified_as_the_sensor_classifies_it(
    ctx: FakeContext, broker: FakeBroker
) -> None:
    broker.fail_on_connect = RuntimeError("ACCESS_REFUSED - Login was refused")

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            RabbitPublishOperator(),
            {"connection": "broker", "routing_key": "shop-orders", "message": {}},
            connected(ctx),
        )

    assert raised.value.error_class is ErrorClass.REJECTED

    broker.fail_on_connect = ConnectionError("connection refused")
    with pytest.raises(BlockFailure) as unreachable:
        await call_block(
            RabbitPublishOperator(),
            {"connection": "broker", "routing_key": "shop-orders", "message": {}},
            connected(ctx),
        )

    assert unreachable.value.error_class is ErrorClass.TRANSIENT


def test_a_publish_declares_itself_not_idempotent() -> None:
    assert RabbitPublishOperator.spec.idempotent is False


async def test_a_publish_nothing_takes_is_refused_rather_than_dropped(ctx: FakeContext, broker: FakeBroker) -> None:
    """The default exchange drops a message whose routing key names no queue unless the publish is mandatory."""
    broker.routes = {"shop-reports"}

    with pytest.raises(BlockFailure) as raised:
        await RabbitPublishOperator().execute(
            RabbitPublishConfig(connection="broker", routing_key="nobody-listens", message="hello"),
            connected(ctx).as_context(),
        )

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "nobody-listens" in str(raised.value)
    assert broker.published == []
