"""``log.write``: one line into the run's own log, and the value carried on."""

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_plugin import Operator, OperatorSpec, RemoteHandle, StepContext


class LogLevel(StrEnum):
    """The levels the run's log carries, one per method of the logger a block is handed."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogWriteConfig(BlockModel):
    """What to say, how loudly, and what to say it about."""

    message: str
    """The line the run's log carries."""

    level: LogLevel = LogLevel.INFO
    """Which level the entry is written at, which is what a log filter selects on."""

    value: JsonValue = None
    """A value recorded as a field of the entry, and passed on as this step's output."""


class LogWriteOutput(BlockModel):
    """The value that was logged, so the step is a pass-through rather than a dead end."""

    value: JsonValue = None


class LogWriteOperator(Operator[LogWriteConfig, LogWriteOutput]):
    """Writes one entry to the run's log and hands its value on.

    The smallest sink there is: ``storage.read`` then ``log.write`` shows what was read,
    without a shell step or a receiver to POST it to. It touches nothing but the run's own
    timeline, so it runs on any worker with nothing on the allowlist.
    """

    spec = OperatorSpec(id="log.write", summary="Write a line to the run's log.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = LogWriteConfig
    output_model: ClassVar[type[BaseModel]] = LogWriteOutput

    async def execute(self, config: LogWriteConfig, ctx: StepContext) -> LogWriteOutput | RemoteHandle:
        """Write the entry at the configured level, and pass the value through."""
        match config.level:
            case LogLevel.DEBUG:
                ctx.log.debug(config.message, value=config.value)
            case LogLevel.INFO:
                ctx.log.info(config.message, value=config.value)
            case LogLevel.WARNING:
                ctx.log.warning(config.message, value=config.value)
            case LogLevel.ERROR:
                ctx.log.error(config.message, value=config.value)
        return LogWriteOutput(value=config.value)
