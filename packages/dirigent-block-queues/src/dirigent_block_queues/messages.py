"""Every refusal the queues family makes, catalogued under the ``queues`` prefix."""

from dirigent_common import Catalogue

QUEUES = Catalogue("queues")

RABBIT_CONNECTION_REFUSED = QUEUES.define(
    "rabbit.connection_refused",
    "the rabbitmq broker refused the connection: {detail}",
)

RABBIT_READ_FAILED = QUEUES.define("rabbit.read_failed", "reading {queue} failed: {detail}")

RABBIT_NO_QUEUE = QUEUES.define("rabbit.no_queue", "the broker has no queue {queue}: {detail}")

RABBIT_DELIVERY_UNREADABLE = QUEUES.define(
    "rabbit.delivery_unreadable",
    "delivery {tag} of the {taken} taken did not read: {detail}",
)

RABBIT_BODY_NOT_JSON = QUEUES.define(
    "rabbit.body_not_json",
    "a message body is not the json this step reads: {detail}",
)

RABBIT_NOTHING_BOUND = QUEUES.define(
    "rabbit.nothing_bound",
    "nothing on exchange {exchange} takes routing key {routing_key}: "
    "declare the queue, or name an exchange it is bound to",
)

RABBIT_PUBLISH_TIMED_OUT = QUEUES.define(
    "rabbit.publish_timed_out",
    "publishing to {routing_key} did not finish within {timeout}",
)

RABBIT_PUBLISH_FAILED = QUEUES.define("rabbit.publish_failed", "publishing to {routing_key} failed: {detail}")

RABBIT_NO_EXCHANGE = QUEUES.define("rabbit.no_exchange", "the broker has no exchange {exchange}: {detail}")

KAFKA_CONNECTION_REFUSED = QUEUES.define(
    "kafka.connection_refused",
    "the kafka cluster refused the connection: {detail}",
)

KAFKA_READ_FAILED = QUEUES.define("kafka.read_failed", "reading {topic} failed: {detail}")

KAFKA_PUBLISH_TIMED_OUT = QUEUES.define(
    "kafka.publish_timed_out",
    "publishing to {topic} did not finish within {timeout}",
)

KAFKA_PUBLISH_FAILED = QUEUES.define("kafka.publish_failed", "publishing to {topic} failed: {detail}")

KAFKA_NO_TOPIC = QUEUES.define("kafka.no_topic", "the cluster has no topic {topic}")

KAFKA_BAD_ENVELOPE = QUEUES.define(
    "kafka.bad_envelope",
    "a record envelope is not one this step can send: {detail}",
)

KAFKA_PART_NOT_JSON = QUEUES.define(
    "kafka.part_not_json",
    "a message {part} is not the json this step reads: {detail}",
)

KAFKA_NO_KEY_FIELD = QUEUES.define("kafka.no_key_field", "a record has no field {field} to take its key from")
