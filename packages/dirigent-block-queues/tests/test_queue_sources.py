"""The queue source kinds as a catalog and a hand run see them, without a broker."""

from datetime import UTC, datetime

from dirigent_block_queues import plugin
from dirigent_block_queues.sources import KafkaSource, KafkaSourceConfig, RabbitSource, RabbitSourceConfig
from dirigent_plugin.sources import HeldSource, SourceHosting

AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_the_pack_contributes_both_held_kinds() -> None:
    kinds = {source.spec.kind: source for source in plugin.contribute().sources}
    assert set(kinds) == {"kafka", "rabbitmq"}
    assert all(isinstance(kind, HeldSource) and kind.spec.hosting is SourceHosting.HELD for kind in kinds.values())


def test_a_kafka_hand_run_is_a_message_on_the_sources_topic() -> None:
    config = KafkaSourceConfig(connection="cluster", topic="orders", group_id="dirigent-orders")
    kind = KafkaSource()
    made = kind.complete(config, {"value": {"id": 1}}, received_at=AT)
    assert (made.topic, made.value, made.timestamp, made.received_at) == ("orders", {"id": 1}, AT, AT)
    assert kind.summary_of(config) == "orders as dirigent-orders"
    assert kind.label_of(made) == "orders/0@0"


def test_a_rabbit_hand_run_is_a_message_on_the_sources_queue() -> None:
    config = RabbitSourceConfig(connection="broker", queue="intake")
    kind = RabbitSource()
    made = kind.complete(config, {"body": {"id": 1}, "routing_key": "new"}, received_at=AT)
    assert (made.queue, made.body, made.received_at) == ("intake", {"id": 1}, AT)
    assert kind.summary_of(config) == "intake"
    assert kind.label_of(made) == "intake new"
