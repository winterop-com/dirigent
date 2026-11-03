"""Tests for the log channel: the alert an instance with nothing configured still writes."""

import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from pydantic import JsonValue, ValidationError
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
    event: str = "run_failed",
    run_id: UUID | None = RUN_ID,
    pipeline: str | None = "nightly",
    url: str | None = "https://dirigent.test/runs/nightly",
    context: dict[str, JsonValue] | None = None,
) -> AlertMessage:
    """Build the message an alert rule hands a notifier, over the context a failed run raises."""
    return AlertMessage(
        event=event,
        subject=subject,
        body="Failed at step load: RuntimeError: refused\nRun: https://dirigent.test/runs/nightly",
        run_id=run_id,
        pipeline=pipeline,
        url=url,
        context=context if context is not None else FAILED_CONTEXT,
    )


FAILED_CONTEXT: dict[str, JsonValue] = {
    "run": {
        "id": str(RUN_ID),
        "pipeline": "nightly",
        "status": "failed",
        "params": {"delay": "1s"},
        "trigger": "agent (token mcp-trial)",
        "duration_ms": 1022,
        "url": "https://dirigent.test/runs/nightly",
    },
    "failing_step": "load",
    "failing_item": None,
    "error": "RuntimeError: refused",
    "error_code": "run.block_raised",
}


def alert_entries(entries: list[EventDict]) -> list[EventDict]:
    """Keep only the entries this module's assertions are about."""
    return [entry for entry in entries if "event_kind" in entry]


async def test_an_alert_is_one_structured_line_with_the_facts_as_fields() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    entry = alert_entries(entries)[0]
    assert {name: value for name, value in entry.items() if name != "log_level"} == {
        "event": "nightly failed at load",
        "event_kind": "run_failed",
        "run_id": str(RUN_ID),
        "pipeline": "nightly",
        "status": "failed",
        "failing_step": "load",
        "error": "RuntimeError: refused",
        "error_code": "run.block_raised",
        "trigger": "agent (token mcp-trial)",
        "duration_ms": 1022,
        "url": "https://dirigent.test/runs/nightly",
    }


async def test_the_line_carries_no_body_and_no_params_a_rule_did_not_ask_for() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    entry = alert_entries(entries)[0]
    assert "body" not in entry
    assert "params" not in entry
    assert not any(isinstance(value, str) and "\n" in value for value in entry.values())


async def test_a_failed_element_of_a_fan_out_is_named_by_its_key() -> None:
    context: dict[str, JsonValue] = {**FAILED_CONTEXT, "failing_item": "b-2"}
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(context=context), LogNotifierConfig())
    assert alert_entries(entries)[0]["item"] == "b-2"


async def test_a_run_that_succeeded_says_so_and_names_no_failure() -> None:
    context: dict[str, JsonValue] = {
        "run": {"pipeline": "nightly", "status": "succeeded", "trigger": "schedule", "duration_ms": 5},
        "failing_step": None,
        "failing_item": None,
        "error": None,
        "error_code": None,
    }
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(event="run_succeeded", context=context), LogNotifierConfig())
    entry = alert_entries(entries)[0]
    assert entry["event"] == "nightly succeeded"
    assert entry["status"] == "succeeded"
    assert not {"failing_step", "item", "error", "error_code"} & set(entry)


async def test_a_run_with_errors_and_a_stuck_run_say_so_in_words() -> None:
    errors: dict[str, JsonValue] = {**FAILED_CONTEXT, "run": {"pipeline": "nightly", "status": "completed_with_errors"}}
    stuck: dict[str, JsonValue] = {"run": {"pipeline": "nightly", "status": "running"}}
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(event="run_completed_with_errors", context=errors), LogNotifierConfig())
        await LogNotifier().send(an_alert(event="run_stuck", context=stuck), LogNotifierConfig())
    said = [entry["event"] for entry in alert_entries(entries)]
    assert said == ["nightly completed with errors at load", "nightly has not progressed"]
    assert alert_entries(entries)[1]["event_kind"] == "run_stuck"


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
async def test_an_alert_is_written_at_the_configured_level(level: str) -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig.model_validate({"level": level}))
    assert alert_entries(entries)[0]["log_level"] == level


async def test_the_default_level_is_the_one_an_operator_would_notice() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    assert alert_entries(entries)[0]["log_level"] == "warning"


async def test_an_alert_about_no_run_names_none_rather_than_inventing_an_id() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(run_id=None, pipeline=None, url=None), LogNotifierConfig())
    entry = alert_entries(entries)[0]
    assert entry["event"] == "nightly run failed", "a message about no run says its own subject"
    assert not {"run_id", "pipeline", "url"} & set(entry)


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
