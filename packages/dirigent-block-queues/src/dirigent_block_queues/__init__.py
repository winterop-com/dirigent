"""The queue block family: producing to and consuming from Kafka and RabbitMQ."""

from dirigent_block_queues.kafka import KafkaConnectionKind, KafkaConsumeSensor, KafkaProduceOperator
from dirigent_block_queues.rabbitmq import RabbitConnectionKind, RabbitConsumeSensor, RabbitPublishOperator
from dirigent_plugin import Contribution, extension


class QueuesBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute both brokers' blocks and the connection kinds they are addressed through."""
        return Contribution(
            operators=[KafkaProduceOperator(), RabbitPublishOperator()],
            sensors=[KafkaConsumeSensor(), RabbitConsumeSensor()],
            connection_kinds=[KafkaConnectionKind(), RabbitConnectionKind()],
        )


plugin = QueuesBlocks()

__all__ = [
    "KafkaConnectionKind",
    "KafkaConsumeSensor",
    "KafkaProduceOperator",
    "QueuesBlocks",
    "RabbitConnectionKind",
    "RabbitConsumeSensor",
    "RabbitPublishOperator",
    "plugin",
]
