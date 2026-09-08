"""Tests for the kafka blocks, against a fake client rather than a cluster."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks import kafka
from dirigent_blocks.kafka import (
    KafkaConnectionConfig,
    KafkaConnectionKind,
    KafkaConsumeConfig,
    KafkaConsumeSensor,
    KafkaProduceConfig,
    KafkaProduceOperator,
    classify,
    read_cursor,
)
from dirigent_plugin import BlockFailure, ErrorClass, NotYet
from dirigent_testing import FakeContext, FakeStorage

#: When every fake record says it was written.
STAMPED = datetime(2026, 6, 1, 12, tzinfo=UTC)


class Partition:
    """A topic partition, as the client library names one."""

    def __init__(self, topic: str, partition: int) -> None:
        """Name one partition of one topic."""
        self.topic = topic
        self.partition = partition

    def __hash__(self) -> int:
        """Hash by topic and number, so a fetch can key a dict by partition."""
        return hash((self.topic, self.partition))

    def __eq__(self, other: object) -> bool:
        """Two partitions are the same when the topic and the number are."""
        return isinstance(other, Partition) and (self.topic, self.partition) == (other.topic, other.partition)


class Record:
    """One message as the client library hands it over."""

    def __init__(
        self,
        offset: int,
        value: bytes,
        *,
        key: bytes | None = None,
        partition: int = 0,
        headers: tuple[tuple[str, bytes], ...] = (),
    ) -> None:
        """Record one message at an offset, stamped at the moment every fake record is."""
        self.topic = "orders"
        self.partition = partition
        self.offset = offset
        self.key = key
        self.value = value
        self.timestamp = int(STAMPED.timestamp() * 1000)
        self.headers = headers


class FakeConsumer:
    """A cluster of one topic, holding a log per partition and answering fetches from it."""

    def __init__(self, log: dict[int, list[Record]] | None = None, *, topics: set[str] | None = None) -> None:
        """Hold the log this consumer reads and the topics the cluster admits to having."""
        self.log: dict[int, list[Record]] = log if log is not None else {0: []}
        self.known: set[str] = topics if topics is not None else {"orders"}
        self.primed: list[str] = []
        self.assigned: list[Partition] = []
        self.subscribed: list[str] = []
        self.positions: dict[int, int] = {}
        self.start_at = "latest"
        self.commits = 0
        self.started = False
        self.stopped = False
        self.fail_on_start: Exception | None = None

    async def start(self) -> None:
        if self.fail_on_start is not None:
            raise self.fail_on_start
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def topics(self) -> set[str]:
        return self.known

    async def prime(self, topic: str) -> None:
        self.primed.append(topic)

    def partitions_for_topic(self, topic: str) -> set[int] | None:
        return set(self.log) if topic in self.known else None

    def assign(self, partitions: list[Any]) -> None:
        self.assigned = list(partitions)

    def assignment(self) -> set[Any]:
        return set(self.assigned)

    def subscribe(self, topics: list[str]) -> None:
        # Joining a group is what hands a subscriber its partitions and puts each one where
        # auto_offset_reset says, which the client does inside the first fetch.
        self.subscribed = list(topics)
        self.assigned = [Partition("orders", number) for number in sorted(self.log)]
        for number, records in self.log.items():
            self.positions[number] = len(records) if self.start_at == "latest" else 0

    def seek(self, partition: Any, offset: int) -> None:
        self.positions[partition.partition] = offset

    async def seek_to_beginning(self, *partitions: Any) -> None:
        for partition in partitions:
            self.positions[partition.partition] = 0

    async def seek_to_end(self, *partitions: Any) -> None:
        for partition in partitions:
            self.positions[partition.partition] = len(self.log[partition.partition])

    async def position(self, partition: Any) -> int:
        return self.positions.get(partition.partition, 0)

    async def getmany(self, *, timeout_ms: int, max_records: int) -> dict[Any, list[Any]]:
        fetched: dict[Any, list[Record]] = {}
        for number, records in self.log.items():
            at = self.positions.get(number, 0)
            taken = [record for record in records if record.offset >= at][:max_records]
            if taken:
                fetched[Partition("orders", number)] = taken
        return fetched

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def cluster(monkeypatch: pytest.MonkeyPatch) -> FakeConsumer:
    """Install one fake cluster in place of the client library, and hand it to the test."""
    consumer = FakeConsumer()

    def build(*_args: Any, **keywords: Any) -> FakeConsumer:
        consumer.start_at = keywords.get("start", "latest")
        return consumer

    monkeypatch.setattr(kafka, "consumer_for", build)
    # The block names TopicPartition where it uses it, so the fake has to be in aiokafka itself.
    monkeypatch.setattr(pytest.importorskip("aiokafka"), "TopicPartition", Partition)
    return consumer


def connected(ctx: FakeContext) -> FakeContext:
    """Give the fake context the kafka connection every config below names."""
    ctx.connections["cluster"] = KafkaConnectionConfig(bootstrap_servers=["localhost:9092"])
    return ctx


def config(**overrides: Any) -> KafkaConsumeConfig:
    """One consume config, with the fields a test does not care about already filled in."""
    return KafkaConsumeConfig.model_validate({"connection": "cluster", "topic": "orders", **overrides})


# -- the connection kind ---------------------------------------------------------


def test_a_sasl_connection_needs_a_credential() -> None:
    with pytest.raises(ValidationError, match="needs a username and a password"):
        KafkaConnectionConfig(bootstrap_servers=["h:9092"], security="sasl_ssl", username="reader")


def test_a_plaintext_connection_refuses_a_credential_that_would_go_unused() -> None:
    with pytest.raises(ValidationError, match="carries no credential"):
        KafkaConnectionConfig(bootstrap_servers=["h:9092"], username="reader", password=SecretStr("s3cret"))


def test_a_connection_without_tls_refuses_a_ca_certificate() -> None:
    with pytest.raises(ValidationError, match="does not use TLS"):
        KafkaConnectionConfig(bootstrap_servers=["h:9092"], ca_certificate="-----BEGIN CERTIFICATE-----")


def test_the_password_is_the_only_sealed_field_and_never_renders() -> None:
    settings = KafkaConnectionConfig(
        bootstrap_servers=["h:9092"],
        security="sasl_plaintext",
        username="reader",
        password=SecretStr("s3cret"),
    )
    assert isinstance(settings.password, SecretStr)
    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings.model_dump())


async def test_a_health_check_reports_the_topics_the_cluster_named(cluster: FakeConsumer) -> None:
    report = await KafkaConnectionKind().check(KafkaConnectionConfig(bootstrap_servers=["h:9092"]))

    assert (report.healthy, report.detail) == (True, "1 topics")
    assert cluster.stopped


async def test_a_health_check_answers_rather_than_raises_when_the_cluster_is_down(cluster: FakeConsumer) -> None:
    cluster.fail_on_start = ConnectionError("no brokers available")

    report = await KafkaConnectionKind().check(KafkaConnectionConfig(bootstrap_servers=["h:9092"]))

    assert report.healthy is False
    assert "no brokers available" in (report.detail or "")


# -- the sensor ------------------------------------------------------------------


async def test_an_empty_topic_parks_with_the_cursor_it_started_from(ctx: FakeContext, cluster: FakeConsumer) -> None:
    parked = await KafkaConsumeSensor().poke(config(), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert parked.cursor == {"offsets": {"0": 0}}


async def test_a_message_arriving_between_two_pokes_is_read_by_the_second(
    ctx: FakeContext, cluster: FakeConsumer
) -> None:
    """The first poke seeks to the end and keeps that place, so the next one carries on from it."""
    cluster.log[0] = [Record(0, b'{"id": 1}')]

    parked = await KafkaConsumeSensor().poke(config(), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert parked.cursor == {"offsets": {"0": 1}}, "latest is the end of the topic, written down"

    cluster.log[0].append(Record(1, b'{"id": 2}'))
    later = connected(ctx)
    later.cursor = parked.cursor

    output = await KafkaConsumeSensor().poke(config(), later.as_context())

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 2}]


async def test_a_batch_at_the_minimum_succeeds_and_reports_where_it_ended(
    ctx: FakeContext, cluster: FakeConsumer
) -> None:
    cluster.log[0] = [Record(0, b'{"id": 1}'), Record(1, b'{"id": 2}')]

    output = await KafkaConsumeSensor().poke(config(start="earliest"), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert output.count == 2
    assert [message.value for message in output.messages] == [{"id": 1}, {"id": 2}]
    assert output.cursor == {"0": 2}, "an offset is the next one to read"


async def test_a_batch_below_the_minimum_parks_with_the_offsets_it_read(
    ctx: FakeContext, cluster: FakeConsumer
) -> None:
    cluster.log[0] = [Record(0, b'{"id": 1}')]

    parked = await KafkaConsumeSensor().poke(config(start="earliest", min_messages=3), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert parked.cursor == {"offsets": {"0": 1}}, "the next poke carries on rather than reading it again"


async def test_a_poke_reads_on_from_the_cursor_it_was_handed(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b'{"id": 1}'), Record(1, b'{"id": 2}')]
    ready = connected(ctx)
    ready.cursor = {"offsets": {"0": 1}}

    output = await KafkaConsumeSensor().poke(config(), ready.as_context())

    assert not isinstance(output, NotYet)
    assert [message.offset for message in output.messages] == [1]


async def test_the_batch_never_runs_past_max_messages(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(number, b"{}") for number in range(10)]

    output = await KafkaConsumeSensor().poke(config(start="earliest", max_messages=4), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert (output.count, output.cursor) == (4, {"0": 4})


async def test_a_batch_that_can_never_be_taken_is_refused_at_apply() -> None:
    with pytest.raises(ValidationError, match="above max_messages"):
        config(min_messages=10, max_messages=2)


async def test_the_start_setting_applies_only_until_there_is_a_cursor(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b"{}"), Record(1, b"{}")]

    parked = await KafkaConsumeSensor().poke(config(min_messages=5), connected(ctx).as_context())

    assert isinstance(parked, NotYet), "latest begins at whatever arrives next, so this poke saw nothing"
    assert cluster.positions == {0: 2}


# -- how a message is read -------------------------------------------------------


async def test_a_key_is_base64_and_a_value_is_json_by_default(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b'{"id": 1}', key=b"\xff\xfe", headers=(("source", b"till"),))]

    output = await KafkaConsumeSensor().poke(config(start="earliest"), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    message = output.messages[0]
    assert message.key == base64.b64encode(b"\xff\xfe").decode()
    assert message.value == {"id": 1}
    assert message.headers == {"source": "till"}
    assert message.timestamp == STAMPED


async def test_a_text_format_hands_the_bytes_over_as_a_string(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b"not json at all", key=b"k")]

    output = await KafkaConsumeSensor().poke(
        config(start="earliest", key_format="text", value_format="text"),
        connected(ctx).as_context(),
    )

    assert not isinstance(output, NotYet)
    assert (output.messages[0].key, output.messages[0].value) == ("k", "not json at all")


async def test_a_value_that_is_not_the_json_it_was_promised_is_rejected(
    ctx: FakeContext, cluster: FakeConsumer
) -> None:
    cluster.log[0] = [Record(0, b"not json at all")]

    with pytest.raises(BlockFailure) as raised:
        await KafkaConsumeSensor().poke(config(start="earliest"), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


# -- offsets and the group -------------------------------------------------------


async def test_without_a_group_nothing_is_committed_to_the_broker(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b"{}")]

    await KafkaConsumeSensor().poke(config(start="earliest"), connected(ctx).as_context())

    assert (cluster.commits, cluster.subscribed) == (0, [])
    assert cluster.assigned == [Partition("orders", 0)]


async def test_a_group_commits_in_the_poke_that_succeeded(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b"{}")]

    output = await KafkaConsumeSensor().poke(config(group_id="pickers", start="earliest"), connected(ctx).as_context())

    assert not isinstance(output, NotYet)
    assert (cluster.commits, cluster.subscribed) == (1, ["orders"])


async def test_a_group_does_not_commit_a_poke_that_parked(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b"{}")]

    parked = await KafkaConsumeSensor().poke(
        config(group_id="pickers", start="earliest", min_messages=4), connected(ctx).as_context()
    )

    assert isinstance(parked, NotYet)
    assert cluster.commits == 0, "an uncommitted batch is read again rather than lost"


async def test_a_group_poke_that_parked_leaves_its_place_in_the_cursor(ctx: FakeContext, cluster: FakeConsumer) -> None:
    """A group commits only on success, so a parked poke carries its position in the cursor."""
    parked = await KafkaConsumeSensor().poke(config(group_id="pickers"), connected(ctx).as_context())

    assert isinstance(parked, NotYet)
    assert (cluster.commits, parked.cursor) == (0, {"offsets": {"0": 0}})

    cluster.log[0] = [Record(0, b'{"id": 1}')]
    later = connected(ctx)
    later.cursor = parked.cursor

    output = await KafkaConsumeSensor().poke(config(group_id="pickers"), later.as_context())

    assert not isinstance(output, NotYet)
    assert [message.value for message in output.messages] == [{"id": 1}]
    assert cluster.assigned == [Partition("orders", 0)], "the cursor seeks rather than rejoining at latest"


async def test_a_partition_left_out_of_a_capped_batch_is_read_again(ctx: FakeContext, cluster: FakeConsumer) -> None:
    """A fetch cut short by max_messages leaves the untaken partition where it stood."""
    cluster.log = {0: [Record(0, b"{}"), Record(1, b"{}")], 1: [Record(0, b"{}", partition=1)]}

    output = await KafkaConsumeSensor().poke(
        config(group_id="pickers", start="earliest", max_messages=2, min_messages=2), connected(ctx).as_context()
    )

    assert not isinstance(output, NotYet)
    assert output.cursor == {"0": 2, "1": 0}, "the partition nothing was taken from is not seeked past"


def test_a_cursor_that_says_nothing_reads_as_no_offsets() -> None:
    assert read_cursor(None) == {}
    assert read_cursor({}) == {}
    assert read_cursor({"offsets": {"0": 12}}) == {"0": 12}


# -- what went wrong -------------------------------------------------------------


async def test_a_topic_the_cluster_does_not_have_is_rejected_by_name(ctx: FakeContext, cluster: FakeConsumer) -> None:
    with pytest.raises(BlockFailure, match="no topic 'missing'") as raised:
        await KafkaConsumeSensor().poke(config(topic="missing"), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_cluster_that_cannot_be_reached_is_transient(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.fail_on_start = ConnectionError("no brokers available")

    with pytest.raises(BlockFailure) as raised:
        await KafkaConsumeSensor().poke(config(), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.TRANSIENT


async def test_an_auth_failure_is_rejected_rather_than_retried(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.fail_on_start = RuntimeError("Authentication failed for user reader")

    with pytest.raises(BlockFailure) as raised:
        await KafkaConsumeSensor().poke(config(), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


def test_an_error_nobody_recognises_stays_unknown() -> None:
    assert classify(RuntimeError("something else entirely")) is ErrorClass.UNKNOWN
    assert KafkaConsumeSensor().classify_error(TimeoutError("timed out")) is ErrorClass.TRANSIENT


async def test_the_consumer_is_closed_however_the_poke_left(ctx: FakeContext, cluster: FakeConsumer) -> None:
    cluster.log[0] = [Record(0, b"not json at all")]

    with pytest.raises(BlockFailure):
        await KafkaConsumeSensor().poke(config(start="earliest"), connected(ctx).as_context())

    assert cluster.stopped


def test_a_poll_timeout_is_written_as_a_duration() -> None:
    assert config(poll_timeout="2s").poll_timeout == timedelta(seconds=2)


# -- kafka.produce ---------------------------------------------------------------


class Acknowledged:
    """What the broker answers a send with, as the client library hands it over."""

    def __init__(self, partition: int, offset: int) -> None:
        """Say where the record landed."""
        self.topic = "orders"
        self.partition = partition
        self.offset = offset


class Sent:
    """One record as the fake producer received it."""

    def __init__(self, topic: str, value: bytes | None, key: bytes | None, headers: Any) -> None:
        """Hold what was handed to the client for one record."""
        self.topic = topic
        self.value = value
        self.key = key
        self.headers = headers


class FakeProducer:
    """A topic that takes records, round-robins them across partitions, and remembers them."""

    def __init__(self, partitions: int = 1) -> None:
        """Hold an empty topic of the given width."""
        self.partitions = partitions
        self.known = {"orders"}
        self.sent: list[Sent] = []
        self.offsets: dict[int, int] = {}
        self.started = False
        self.stopped = False
        self.fail_on_start: Exception | None = None
        self.fail_on_send: Exception | None = None

    async def start(self) -> None:
        if self.fail_on_start is not None:
            raise self.fail_on_start
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def topics(self) -> set[str]:
        return self.known

    async def send(
        self,
        topic: str,
        value: bytes | None,
        key: bytes | None = None,
        headers: Any = None,
    ) -> Any:
        if self.fail_on_send is not None:
            raise self.fail_on_send
        partition = len(self.sent) % self.partitions
        offset = self.offsets.get(partition, -1) + 1
        self.offsets[partition] = offset
        self.sent.append(Sent(topic, value, key, headers))
        acknowledged: asyncio.Future[Acknowledged] = asyncio.get_running_loop().create_future()
        acknowledged.set_result(Acknowledged(partition, offset))
        return acknowledged


class Recorder:
    """Stands in for the client library's producer, keeping the keywords it was built with."""

    keywords: ClassVar[dict[str, Any]] = {}

    def __init__(self, **given: Any) -> None:
        """Record one construction."""
        Recorder.keywords = dict(given)


def install(monkeypatch: pytest.MonkeyPatch, producer: FakeProducer) -> FakeProducer:
    """Put one fake producer in place of the client library, whatever a step asks for."""

    def build(*_args: Any, **_keywords: Any) -> FakeProducer:
        return producer

    monkeypatch.setattr(kafka, "producer_for", build)
    return producer


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> FakeProducer:
    """Install one fake producer in place of the client library, and hand it to the test."""
    return install(monkeypatch, FakeProducer())


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> type[Recorder]:
    """Build producers that connect to nothing and remember how they were configured."""
    monkeypatch.setattr(pytest.importorskip("aiokafka"), "AIOKafkaProducer", Recorder)
    return Recorder


def produce(**overrides: Any) -> KafkaProduceConfig:
    """One produce config, with the fields a test does not care about already filled in."""
    return KafkaProduceConfig.model_validate({"connection": "cluster", "topic": "orders", **overrides})


async def test_a_publish_reports_what_the_broker_took(ctx: FakeContext, broker: FakeProducer) -> None:
    output = await KafkaProduceOperator().execute(produce(records=[{"id": 1}, {"id": 2}]), connected(ctx).as_context())

    assert (output.produced, output.topic) == (2, "orders")
    assert output.offsets == {"0": 1}, "the last offset of every partition written to"
    assert output.sent_bytes == len(b'{"id":1}') + len(b'{"id":2}')
    assert [one.value for one in broker.sent] == [b'{"id":1}', b'{"id":2}']
    assert broker.stopped


async def test_a_bare_element_is_the_value_and_an_envelope_carries_the_rest(
    ctx: FakeContext, broker: FakeProducer
) -> None:
    output = await KafkaProduceOperator().execute(
        produce(
            records=[
                {"id": 1},
                {"key": "north", "value": {"id": 2}, "headers": {"source": "till"}},
                "a plain line",
            ]
        ),
        connected(ctx).as_context(),
    )

    assert output.produced == 3
    assert [one.key for one in broker.sent] == [None, b"north", None]
    assert [one.value for one in broker.sent] == [b'{"id":1}', b'{"id":2}', b"a plain line"]
    assert [one.headers for one in broker.sent] == [None, [("source", b"till")], None]


async def test_an_object_that_is_not_an_envelope_is_published_as_the_value(
    ctx: FakeContext, broker: FakeProducer
) -> None:
    await KafkaProduceOperator().execute(produce(records=[{"value": 1, "unit": "kg"}]), connected(ctx).as_context())

    assert [one.value for one in broker.sent] == [b'{"value":1,"unit":"kg"}']


async def test_the_key_field_names_where_each_record_takes_its_key_from(ctx: FakeContext, broker: FakeProducer) -> None:
    await KafkaProduceOperator().execute(
        produce(key="region", records=[{"region": "north"}, {"key": "kept", "value": {"region": "south"}}]),
        connected(ctx).as_context(),
    )

    assert [one.key for one in broker.sent] == [b"north", b"kept"], "an envelope's own key wins"


async def test_a_record_missing_the_key_field_is_rejected(ctx: FakeContext, broker: FakeProducer) -> None:
    with pytest.raises(BlockFailure, match="no field 'region'") as raised:
        await KafkaProduceOperator().execute(produce(key="region", records=[{"id": 1}]), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_ndjson_is_published_a_line_at_a_time_rather_than_held(
    ctx: FakeContext, storage: FakeStorage, broker: FakeProducer
) -> None:
    """Storage hands the object over in chunks that cut a line in half, and every line still goes."""
    (storage.root / "orders.ndjson").write_text("".join(f'{{"id": {number}}}\n' for number in range(20)))

    output = await KafkaProduceOperator().execute(
        produce(records_from="file://orders.ndjson"), connected(ctx).as_context()
    )

    assert output.produced == 20
    assert [one.value for one in broker.sent] == [f'{{"id":{number}}}'.encode() for number in range(20)]


async def test_a_last_line_without_a_newline_is_still_published(
    ctx: FakeContext, storage: FakeStorage, broker: FakeProducer
) -> None:
    (storage.root / "orders.ndjson").write_text('{"id": 1}\n{"id": 2}')

    output = await KafkaProduceOperator().execute(
        produce(records_from="file://orders.ndjson"), connected(ctx).as_context()
    )

    assert output.produced == 2


async def test_a_uri_holding_nothing_is_rejected_before_anything_is_sent(
    ctx: FakeContext, broker: FakeProducer
) -> None:
    with pytest.raises(BlockFailure, match="nothing at file://absent.ndjson") as raised:
        await KafkaProduceOperator().execute(produce(records_from="file://absent.ndjson"), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED
    assert broker.sent == []


async def test_a_line_that_is_not_json_is_rejected(
    ctx: FakeContext, storage: FakeStorage, broker: FakeProducer
) -> None:
    (storage.root / "orders.ndjson").write_text('{"id": 1}\nnot json at all\n')

    with pytest.raises(BlockFailure, match="is not JSON") as raised:
        await KafkaProduceOperator().execute(produce(records_from="file://orders.ndjson"), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_the_offsets_are_the_last_one_of_every_partition_written_to(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeProducer(partitions=2))

    output = await KafkaProduceOperator().execute(produce(records=[1, 2, 3, 4, 5]), connected(ctx).as_context())

    assert output.produced == 5
    assert output.offsets == {"0": 2, "1": 1}


async def test_a_cluster_that_cannot_be_reached_is_transient_for_a_publish(
    ctx: FakeContext, broker: FakeProducer
) -> None:
    broker.fail_on_start = ConnectionError("no brokers available")

    with pytest.raises(BlockFailure) as raised:
        await KafkaProduceOperator().execute(produce(records=[{"id": 1}]), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.TRANSIENT


async def test_a_topic_the_cluster_does_not_have_is_rejected_before_anything_is_sent(
    ctx: FakeContext, broker: FakeProducer
) -> None:
    with pytest.raises(BlockFailure, match="no topic 'invented'") as raised:
        await KafkaProduceOperator().execute(
            produce(topic="invented", records=[{"id": 1}]), connected(ctx).as_context()
        )

    assert raised.value.error_class is ErrorClass.REJECTED
    assert broker.sent == []
    assert broker.stopped, "the producer is closed however the step left"


async def test_a_broker_that_refuses_a_send_is_not_retried(ctx: FakeContext, broker: FakeProducer) -> None:
    broker.fail_on_send = RuntimeError("UnknownTopicOrPartitionError: unknown topic or partition")

    with pytest.raises(BlockFailure, match="publishing to 'orders' failed") as raised:
        await KafkaProduceOperator().execute(produce(records=[{"id": 1}]), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.REJECTED
    assert broker.stopped


async def test_a_publish_that_runs_past_its_timeout_is_transient(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Slow(FakeProducer):
        async def send(self, topic: str, value: bytes | None, key: bytes | None = None, headers: Any = None) -> Any:
            await asyncio.sleep(1)
            return await super().send(topic, value, key, headers)

    install(monkeypatch, Slow())

    with pytest.raises(BlockFailure, match="did not finish within") as raised:
        await KafkaProduceOperator().execute(produce(records=[{"id": 1}], timeout="10ms"), connected(ctx).as_context())

    assert raised.value.error_class is ErrorClass.TRANSIENT


def test_a_publish_names_its_records_in_exactly_one_place() -> None:
    with pytest.raises(ValidationError, match="names neither"):
        produce()
    with pytest.raises(ValidationError, match="not both"):
        produce(records=[1], records_from="file://orders.ndjson")


def test_a_publish_timeout_is_written_as_a_duration() -> None:
    assert produce(records=[1], timeout="45s").timeout == timedelta(seconds=45)


def test_the_default_acks_is_the_one_an_idempotent_producer_needs(recorder: type[Recorder]) -> None:
    settings = KafkaConnectionConfig(bootstrap_servers=["h:9092"])

    kafka.producer_for(settings, acks="all")
    assert (recorder.keywords["acks"], recorder.keywords["enable_idempotence"]) == ("all", True)

    kafka.producer_for(settings, acks="1")
    assert (recorder.keywords["acks"], recorder.keywords["enable_idempotence"]) == (1, False)


def test_a_sasl_credential_reaches_the_producer_without_appearing_in_the_connection(
    recorder: type[Recorder],
) -> None:
    settings = KafkaConnectionConfig(
        bootstrap_servers=["h:9092"],
        security="sasl_plaintext",
        username="writer",
        password=SecretStr("s3cret"),
    )

    kafka.producer_for(settings, acks="all")

    assert recorder.keywords["sasl_plain_password"] == "s3cret"
    assert "s3cret" not in repr(settings)
