"""The channel every instance already has: an alert written to the process log.

It is the one notifier with no connection kind beside it, because there is no credential to
mint: an instance with nothing configured still says something.
"""

from typing import ClassVar, Literal

import structlog
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_plugin import AlertMessage, Notifier

#: Must match the logger chain dirigent-core configures.
ALERT_LOGGER = "dirigent.alert"

#: The event a run that stopped moving raises, which has no outcome to name yet.
STUCK = "run_stuck"


class LogNotifierConfig(BlockModel):
    """What the log notifier needs, which is nothing but the level to write at."""

    level: Literal["debug", "info", "warning", "error"] = "warning"
    """The process-log level an alert is written at; a channel with no credential has little else to say."""


class LogNotifier(Notifier):
    """Writes an alert to the process log, so an instance with no channel configured still says something."""

    id: ClassVar[str] = "log"
    config_model: ClassVar[type[BaseModel]] = LogNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Write one alert as one structured line, at the configured level.

        The line carries the facts as fields rather than the body a text channel renders, and
        a field with nothing to say is left off.
        """
        settings = LogNotifierConfig.model_validate(config.model_dump())
        logger: structlog.stdlib.BoundLogger = structlog.get_logger(ALERT_LOGGER)
        write = getattr(logger, settings.level, logger.warning)
        context = message.context
        run = context.get("run")
        # A message about no run, a test, renders its templates over a stand-in run it does not report.
        run = run if isinstance(run, dict) and message.run_id is not None else {}
        fields: dict[str, JsonValue] = {
            "event_kind": message.event,
            "run_id": str(message.run_id) if message.run_id else None,
            "pipeline": message.pipeline,
            "status": run.get("status"),
            "failing_step": context.get("failing_step"),
            "item": context.get("failing_item"),
            "error": context.get("error"),
            "error_code": context.get("error_code"),
            "trigger": run.get("trigger"),
            "duration_ms": run.get("duration_ms"),
            "url": message.url,
        }
        write(headline(message), **{name: value for name, value in fields.items() if value is not None})


def headline(message: AlertMessage) -> str:
    """Say in a few words what happened to which pipeline, and where: ``nightly failed at load``.

    A message about no run, which is what a test message is, says its own subject.
    """
    context = message.context
    run = context.get("run")
    status = run.get("status") if isinstance(run, dict) else None
    if message.run_id is None or not message.pipeline or not isinstance(status, str):
        return message.subject
    if message.event == STUCK:
        return f"{message.pipeline} has not progressed"
    said = f"{message.pipeline} {status.replace('_', ' ')}"
    step = context.get("failing_step")
    return f"{said} at {step}" if isinstance(step, str) and step else said
