"""Fixtures the client tests share."""

import pytest


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every backoff the client asks for, and let none of them actually wait."""
    waits: list[float] = []

    async def instant(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("asyncio.sleep", instant)
    return waits
