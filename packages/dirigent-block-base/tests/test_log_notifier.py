"""Tests for the log channel: the alert an instance with nothing configured still writes."""

import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from pydantic import ValidationError
from structlog.testing import capture_logs
from structlog.typing import EventDict

from dirigent_block_base.log_notifier import ALERT_LOGGER, LogNotifier, LogNotifierConfig
from dirigent_plugin import AlertMessage

RUN_ID = UUID("0192f0a0-1111-7000-8000-000000000001")


@pytest.fixture(autouse=True)
def _permissive_structlog() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Let every level through while a test runs, and restore the session's own configuration.

    ``capture_logs`` swaps the processors but leaves the wrapper class alone, so a suite that
    has already configured logging at INFO would silently swallow the debug-level assertion.
    """
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    yield
    structlog.configure(**saved)


def an_alert(
    *,
    subject: str = "nightly run failed",
    run_id: UUID | None = RUN_ID,
    pipeline: str | None = "nightly",
    url: str | None = "https://dirigent.test/runs/nightly",
) -> AlertMessage:
    """Build the message an alert rule hands a notifier."""
    return AlertMessage(
        event="run_failed",
        subject=subject,
        body="status: failed",
        run_id=run_id,
        pipeline=pipeline,
        url=url,
        context={"run": {"pipeline": pipeline}},
    )


def alert_entries(entries: list[EventDict]) -> list[EventDict]:
    """Keep only the entries this module's assertions are about."""
    return [entry for entry in entries if entry.get("pipeline") is not None or "event_kind" in entry]


async def test_an_alert_reaches_the_process_log_with_the_facts_on_it() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    entry = alert_entries(entries)[0]
    assert entry["event"] == "nightly run failed"
    assert entry["event_kind"] == "run_failed"
    assert entry["run_id"] == str(RUN_ID)
    assert entry["pipeline"] == "nightly"
    assert entry["url"] == "https://dirigent.test/runs/nightly"
    assert entry["body"] == "status: failed"


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
async def test_an_alert_is_written_at_the_configured_level(level: str) -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig.model_validate({"level": level}))
    assert alert_entries(entries)[0]["log_level"] == level


async def test_the_default_level_is_the_one_an_operator_would_notice() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    assert alert_entries(entries)[0]["log_level"] == "warning"


async def test_an_alert_about_no_run_says_so_rather_than_inventing_an_id() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(run_id=None, pipeline=None, url=None), LogNotifierConfig())
    entry = [line for line in entries if "event_kind" in line][0]
    assert entry["run_id"] is None
    assert entry["pipeline"] is None
    assert entry["url"] is None


def test_the_channel_writes_under_the_logger_the_engine_configures() -> None:
    assert ALERT_LOGGER == "dirigent.alert"
    assert LogNotifier.id == "log"
    assert LogNotifier.config_model is LogNotifierConfig


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
def test_the_four_levels_are_accepted(level: str) -> None:
    assert LogNotifierConfig.model_validate({"level": level}).level == level


@pytest.mark.parametrize("level", ["critical", "trace", "WARNING", ""])
def test_anything_but_the_four_levels_is_refused(level: str) -> None:
    with pytest.raises(ValidationError):
        LogNotifierConfig.model_validate({"level": level})
