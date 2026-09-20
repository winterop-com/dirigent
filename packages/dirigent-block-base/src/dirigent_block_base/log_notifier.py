"""The channel every instance already has: an alert written to the process log.

It is the one notifier with no connection kind beside it, because there is no credential to
mint: an instance with nothing configured still says something.
"""

from typing import ClassVar, Literal

import structlog
from pydantic import BaseModel

from dirigent_common import BlockModel
from dirigent_plugin import AlertMessage, Notifier

#: Must match the logger chain dirigent-core configures.
ALERT_LOGGER = "dirigent.alert"


class LogNotifierConfig(BlockModel):
    """What the log notifier needs, which is nothing but the level to write at."""

    level: Literal["debug", "info", "warning", "error"] = "warning"
    """The process-log level an alert is written at; a channel with no credential has little else to say."""


class LogNotifier(Notifier):
    """Writes an alert to the process log, so an instance with no channel configured still says something."""

    id: ClassVar[str] = "log"
    config_model: ClassVar[type[BaseModel]] = LogNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Write one alert through the shared structlog chain, at the configured level."""
        settings = LogNotifierConfig.model_validate(config.model_dump())
        logger: structlog.stdlib.BoundLogger = structlog.get_logger(ALERT_LOGGER)
        write = getattr(logger, settings.level, logger.warning)
        write(
            message.subject,
            event_kind=message.event,
            run_id=str(message.run_id) if message.run_id else None,
            pipeline=message.pipeline,
            url=message.url,
            body=message.body,
        )
