"""Settling a sensor's batch with its broker once the engine knows whether the success is stored."""

import asyncio
from datetime import timedelta
from typing import Final

from dirigent_common import raised_detail
from dirigent_core.logging import get_logger
from dirigent_plugin import Settlement

_logger = get_logger("engine")

#: How long a settle or a release may take before the engine stops waiting on the broker.
SETTLE_TIMEOUT: Final = timedelta(seconds=30)


async def conclude(settlement: Settlement | None, *, stored: bool, **where: str) -> None:
    """Settle the batch when its success was stored, and release it otherwise; never raise.

    A settle that fails leaves the batch with the broker beside a stored success, so it is
    delivered again; a release that fails leaves it to the broker's own redelivery.
    """
    if settlement is None:
        return
    call = "settle" if stored else "release"
    try:
        async with asyncio.timeout(SETTLE_TIMEOUT.total_seconds()):
            await (settlement.settle() if stored else settlement.release())
    except Exception as error:
        _logger.warning(
            "a batch could not be settled with its broker",
            **where,
            call=call,
            raised_kind=type(error).__name__,
            raised_detail=raised_detail(error),
        )
