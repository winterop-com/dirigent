"""The base block family: what a pipeline needs whatever it integrates with."""

from dirigent_block_base.clock import TimeSleepSensor, TimeWindowSensor
from dirigent_block_base.convert_std import StdConverter
from dirigent_block_base.log_notifier import LogNotifier
from dirigent_block_base.logging import LogWriteOperator
from dirigent_block_base.pipelines import PipelineRunOperator
from dirigent_block_base.playground import PlaygroundConfig, PlaygroundOperator, PlaygroundOutput
from dirigent_block_base.report import ReportRenderOperator
from dirigent_block_base.validate import ValidateSchemaOperator
from dirigent_block_base.values import ValueConstOperator
from dirigent_plugin import Contribution, extension


class BaseBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the base blocks and the log channel, which needs no credential to deliver."""
        return Contribution(
            operators=[
                LogWriteOperator(),
                ReportRenderOperator(),
                ValidateSchemaOperator(),
                ValueConstOperator(),
                PipelineRunOperator(),
                PlaygroundOperator(),
                StdConverter(),
            ],
            sensors=[TimeSleepSensor(), TimeWindowSensor()],
            notifiers=[LogNotifier()],
        )


plugin = BaseBlocks()

__all__ = [
    "BaseBlocks",
    "LogNotifier",
    "LogWriteOperator",
    "PipelineRunOperator",
    "PlaygroundConfig",
    "PlaygroundOperator",
    "PlaygroundOutput",
    "ReportRenderOperator",
    "StdConverter",
    "TimeSleepSensor",
    "TimeWindowSensor",
    "ValidateSchemaOperator",
    "ValueConstOperator",
    "plugin",
]
