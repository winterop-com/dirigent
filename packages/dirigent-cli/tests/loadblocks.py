"""The block the load lane drives: one that logs a great many lines at a set pace."""

import asyncio
import time
from datetime import timedelta
from typing import ClassVar

from dirigent_common import BlockModel, Duration
from dirigent_plugin import Contribution, Operator, OperatorSpec, RemoteHandle, StepContext, extension


class ChattyConfig(BlockModel):
    """What the chatty operator is told."""

    lines: int = 100
    """How many entries the call logs."""

    pace: Duration = timedelta(milliseconds=1)
    """How long the call sleeps between one line and the next."""


class ChattyOutput(BlockModel):
    """What the chatty operator reports."""

    lines: int
    duration_ms: int


class ChattyOperator(Operator[ChattyConfig, ChattyOutput]):
    """Logs at a fixed pace, and records how long the call itself took."""

    spec = OperatorSpec(id="load.chatty", summary="Log a number of lines at a set pace.", idempotent=True)
    config_model = ChattyConfig
    output_model = ChattyOutput
    elapsed: ClassVar[list[float]] = []
    """Seconds each call spent, which is the paced sleeping plus the cost of ``ctx.log``."""

    async def execute(self, config: ChattyConfig, ctx: StepContext) -> ChattyOutput | RemoteHandle:
        """Log the configured lines, sleeping the configured pace between them."""
        pace = config.pace.total_seconds()
        started = time.monotonic()
        for index in range(config.lines):
            ctx.log.info(f"line {index}", index=index)
            await asyncio.sleep(pace)
        seconds = time.monotonic() - started
        ChattyOperator.elapsed.append(seconds)
        return ChattyOutput(lines=config.lines, duration_ms=int(seconds * 1000))


class LoadTestPlugin:
    """The plugin the load lane installs into the host."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the one block the load lane runs."""
        return Contribution(operators=[ChattyOperator()])
