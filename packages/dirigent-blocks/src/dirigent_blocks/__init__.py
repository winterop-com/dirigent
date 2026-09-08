"""The built-in generic block pack: what a fresh install can already do."""

from dirigent_blocks.build import DockerBuildConfig, DockerBuildOperator, DockerBuildOutput
from dirigent_blocks.clock import (
    TimeSleepConfig,
    TimeSleepOutput,
    TimeSleepSensor,
    TimeWindowConfig,
    TimeWindowOutput,
    TimeWindowSensor,
)
from dirigent_blocks.compose import (
    DockerComposeDownConfig,
    DockerComposeDownOperator,
    DockerComposeDownOutput,
    DockerComposeUpConfig,
    DockerComposeUpOperator,
    DockerComposeUpOutput,
)
from dirigent_blocks.connections import HttpConnectionConfig, HttpConnectionKind
from dirigent_blocks.convert_std import StdConverter
from dirigent_blocks.docker import (
    DockerConnectionConfig,
    DockerConnectionKind,
    DockerRunConfig,
    DockerRunOperator,
    DockerRunOutput,
)
from dirigent_blocks.git import (
    GitCheckoutConfig,
    GitCheckoutOperator,
    GitCheckoutOutput,
    GitConnectionConfig,
    GitConnectionKind,
)
from dirigent_blocks.http import (
    HttpReadyConfig,
    HttpReadyOutput,
    HttpReadySensor,
    HttpRequestConfig,
    HttpRequestOperator,
    HttpRequestOutput,
)
from dirigent_blocks.kafka import (
    KafkaConnectionConfig,
    KafkaConnectionKind,
    KafkaConsumeConfig,
    KafkaConsumeOutput,
    KafkaConsumeSensor,
    KafkaMessage,
    KafkaProduceConfig,
    KafkaProduceOperator,
    KafkaProduceOutput,
)
from dirigent_blocks.notifiers import (
    EmailConnectionKind,
    EmailNotifier,
    EmailNotifierConfig,
    LogNotifier,
    LogNotifierConfig,
    SlackConnectionKind,
    SlackNotifier,
    SlackNotifierConfig,
    WebhookConnectionKind,
    WebhookNotifier,
    WebhookNotifierConfig,
)
from dirigent_blocks.pipelines import PipelineRunConfig, PipelineRunOperator, PipelineRunOutput
from dirigent_blocks.rabbitmq import (
    RabbitConnectionConfig,
    RabbitConnectionKind,
    RabbitConsumeConfig,
    RabbitConsumeOutput,
    RabbitConsumeSensor,
    RabbitMessage,
)
from dirigent_blocks.shell import ShellRunConfig, ShellRunOperator, ShellRunOutput
from dirigent_blocks.sql import (
    SqlConnectionConfig,
    SqlConnectionKind,
    SqlExecuteConfig,
    SqlExecuteOperator,
    SqlExecuteOutput,
    SqlQueryConfig,
    SqlQueryOperator,
    SqlQueryOutput,
)
from dirigent_blocks.storage import (
    StorageCopyConfig,
    StorageCopyOperator,
    StorageCopyOutput,
    StorageExistsConfig,
    StorageExistsOutput,
    StorageExistsSensor,
)
from dirigent_blocks.transform_jq import JqFilterer, JqMapper, JqTransformer
from dirigent_blocks.validate import ValidateSchemaConfig, ValidateSchemaOperator, ValidateSchemaOutput
from dirigent_blocks.values import ValueConstConfig, ValueConstOperator, ValueConstOutput
from dirigent_blocks.webhooks import WebhookPostConfig, WebhookPostOperator, WebhookPostOutput
from dirigent_plugin import Contribution, extension


class BuiltinBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the built-in operators, sensors, notifiers, and their connection kinds."""
        return Contribution(
            operators=[
                HttpRequestOperator(),
                StorageCopyOperator(),
                ShellRunOperator(),
                DockerRunOperator(),
                DockerComposeUpOperator(),
                DockerComposeDownOperator(),
                DockerBuildOperator(),
                GitCheckoutOperator(),
                SqlQueryOperator(),
                SqlExecuteOperator(),
                PipelineRunOperator(),
                KafkaProduceOperator(),
                WebhookPostOperator(),
                JqTransformer(),
                JqMapper(),
                JqFilterer(),
                StdConverter(),
                ValueConstOperator(),
                ValidateSchemaOperator(),
            ],
            sensors=[
                HttpReadySensor(),
                KafkaConsumeSensor(),
                RabbitConsumeSensor(),
                StorageExistsSensor(),
                TimeSleepSensor(),
                TimeWindowSensor(),
            ],
            notifiers=[LogNotifier(), WebhookNotifier(), SlackNotifier(), EmailNotifier()],
            connection_kinds=[
                HttpConnectionKind(),
                DockerConnectionKind(),
                GitConnectionKind(),
                KafkaConnectionKind(),
                RabbitConnectionKind(),
                SqlConnectionKind(),
                SlackConnectionKind(),
                EmailConnectionKind(),
                WebhookConnectionKind(),
            ],
        )


plugin = BuiltinBlocks()

__all__ = [
    "BuiltinBlocks",
    "DockerBuildConfig",
    "DockerBuildOperator",
    "DockerBuildOutput",
    "DockerComposeDownConfig",
    "DockerComposeDownOperator",
    "DockerComposeDownOutput",
    "DockerComposeUpConfig",
    "DockerComposeUpOperator",
    "DockerComposeUpOutput",
    "DockerConnectionConfig",
    "DockerConnectionKind",
    "DockerRunConfig",
    "DockerRunOperator",
    "DockerRunOutput",
    "EmailConnectionKind",
    "EmailNotifier",
    "EmailNotifierConfig",
    "GitCheckoutConfig",
    "GitCheckoutOperator",
    "GitCheckoutOutput",
    "GitConnectionConfig",
    "GitConnectionKind",
    "HttpConnectionConfig",
    "HttpConnectionKind",
    "HttpReadyConfig",
    "HttpReadyOutput",
    "HttpReadySensor",
    "HttpRequestConfig",
    "HttpRequestOperator",
    "HttpRequestOutput",
    "JqFilterer",
    "JqMapper",
    "JqTransformer",
    "KafkaConnectionConfig",
    "KafkaConnectionKind",
    "KafkaConsumeConfig",
    "KafkaConsumeOutput",
    "KafkaConsumeSensor",
    "KafkaMessage",
    "KafkaProduceConfig",
    "KafkaProduceOperator",
    "KafkaProduceOutput",
    "LogNotifier",
    "LogNotifierConfig",
    "PipelineRunConfig",
    "PipelineRunOperator",
    "PipelineRunOutput",
    "RabbitConnectionConfig",
    "RabbitConnectionKind",
    "RabbitConsumeConfig",
    "RabbitConsumeOutput",
    "RabbitConsumeSensor",
    "RabbitMessage",
    "ShellRunConfig",
    "ShellRunOperator",
    "ShellRunOutput",
    "SlackConnectionKind",
    "SlackNotifier",
    "SlackNotifierConfig",
    "SqlConnectionConfig",
    "SqlConnectionKind",
    "SqlExecuteConfig",
    "SqlExecuteOperator",
    "SqlExecuteOutput",
    "SqlQueryConfig",
    "SqlQueryOperator",
    "SqlQueryOutput",
    "StdConverter",
    "StorageCopyConfig",
    "StorageCopyOperator",
    "StorageCopyOutput",
    "StorageExistsConfig",
    "StorageExistsOutput",
    "StorageExistsSensor",
    "TimeSleepConfig",
    "TimeSleepOutput",
    "TimeSleepSensor",
    "TimeWindowConfig",
    "TimeWindowOutput",
    "TimeWindowSensor",
    "ValidateSchemaConfig",
    "ValidateSchemaOperator",
    "ValidateSchemaOutput",
    "ValueConstConfig",
    "ValueConstOperator",
    "ValueConstOutput",
    "WebhookConnectionKind",
    "WebhookNotifier",
    "WebhookNotifierConfig",
    "WebhookPostConfig",
    "WebhookPostOperator",
    "WebhookPostOutput",
    "plugin",
]
