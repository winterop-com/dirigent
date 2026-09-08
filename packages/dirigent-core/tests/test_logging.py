"""Tests for the one structlog chain every dirigent process logs through."""

import json
import logging
from collections.abc import Iterator
from uuid import uuid4

import pytest
import structlog

from dirigent_client.enums import LogLevel
from dirigent_core.engine.context import (
    MAX_MESSAGE_CHARS,
    BufferedLogger,
    buffer_full,
    kept_level,
)
from dirigent_core.logging import (
    BRIDGED_LOGGERS,
    PACKAGE_LOGGER,
    GrammarRenderer,
    RedactAccessPath,
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    log_context,
    own_handlers,
    redact_path,
    unbind_context,
)


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Leave the root logger and structlog exactly as the test session found them."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_config = structlog.get_config()
    bridged = {name: logging.getLogger(name).level for name in BRIDGED_LOGGERS}
    try:
        yield
    finally:
        clear_context()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        for name, level in bridged.items():
            logging.getLogger(name).setLevel(level)
        structlog.configure(**saved_config)


def _capture(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Render the records the shared handler formatted, as the handler would write them."""
    handler = own_handlers(logging.getLogger())[0]
    return [handler.format(record) for record in caplog.records]


def test_json_format_produces_parseable_lines(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", "json")
    with caplog.at_level(logging.INFO):
        get_logger("engine").info("claimed", step="push")
    payload = json.loads(_capture(caplog)[0])
    assert payload["event"] == "claimed"
    assert payload["step"] == "push"
    assert payload["level"] == "info"
    assert payload["logger"] == "dirigent.engine"
    assert payload["timestamp"].endswith("Z")


def test_bound_context_reaches_every_line(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", "json")
    bind_context(run_id="0198", step="push", attempt=2, worker="worker-1")
    with caplog.at_level(logging.INFO):
        get_logger("engine").info("executing")
        unbind_context("step")
        get_logger("engine").info("finished")
    first, second = (json.loads(line) for line in _capture(caplog))
    assert first["run_id"] == "0198"
    assert first["step"] == "push"
    assert first["attempt"] == 2
    assert first["worker"] == "worker-1"
    assert "step" not in second
    assert second["run_id"] == "0198"


def test_log_context_restores_what_was_bound_before_it(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", "json")
    bind_context(run_id="outer")
    with caplog.at_level(logging.INFO):
        with log_context(run_id="inner"):
            get_logger().info("inside")
        get_logger().info("outside")
    inside, outside = (json.loads(line) for line in _capture(caplog))
    assert inside["run_id"] == "inner"
    assert outside["run_id"] == "outer"


def test_console_format_renders_a_human_line(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", "console")
    with caplog.at_level(logging.INFO):
        get_logger("engine").warning("slow claim", waited_ms=120)
    rendered = _capture(caplog)[0]
    assert "slow claim" in rendered
    assert "waited_ms=120" in rendered


def test_library_stdlib_records_flow_through_the_bridge(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", "json")
    bind_context(run_id="0198")
    with caplog.at_level(logging.INFO, logger="sqlalchemy.engine"):
        logging.getLogger("sqlalchemy.engine").info("BEGIN (implicit)")
    payload = json.loads(_capture(caplog)[0])
    assert payload["event"] == "BEGIN (implicit)"
    assert payload["logger"] == "sqlalchemy.engine"
    assert payload["run_id"] == "0198"


def test_configuring_twice_does_not_stack_handlers() -> None:
    configure_logging("INFO", "json")
    configure_logging("DEBUG", "console")
    assert len(own_handlers(logging.getLogger())) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_the_package_logger_names_its_children(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", "json")
    assert PACKAGE_LOGGER == "dirigent"
    with caplog.at_level(logging.INFO):
        get_logger("worker").info("named")
        get_logger().info("unnamed")
    named, unnamed = (json.loads(line) for line in _capture(caplog))
    assert named["logger"] == "dirigent.worker"
    assert unnamed["logger"] == "dirigent"


def test_the_access_log_never_prints_a_webhook_token(caplog: pytest.LogCaptureFixture) -> None:
    """A delivery's path *is* its credential, so uvicorn's access line must not carry it."""
    configure_logging("INFO", "json")
    access = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:51000",
            "POST",
            "/hooks/wht_thisisthesecret",
            "1.1",
            201,
        )
    line = _capture(caplog)[0]
    assert "thisisthesecret" not in line
    assert "/hooks/{token}" in line


def test_the_access_log_keeps_a_path_that_is_not_a_credential(caplog: pytest.LogCaptureFixture) -> None:
    """Only credential-bearing paths are scrubbed; a run id in a log line is the point."""
    configure_logging("INFO", "json")
    access = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:51000", "GET", "/api/v1/runs/abc", "1.1", 200)
    assert "/api/v1/runs/abc" in _capture(caplog)[0]


def test_configuring_twice_does_not_stack_the_access_log_scrubber() -> None:
    configure_logging("INFO", "json")
    configure_logging("INFO", "json")
    access = logging.getLogger("uvicorn.access")
    assert len([f for f in access.filters if isinstance(f, RedactAccessPath)]) == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/hooks/abc123", "/hooks/{token}"),
        ("/hooks/", "/hooks/{token}"),
        ("/api/v1/pipelines/demo", "/api/v1/pipelines/demo"),
        ("/health/ready", "/health/ready"),
    ],
)
def test_redacting_a_path_touches_only_the_credential_bearing_ones(path: str, expected: str) -> None:
    assert redact_path(path) == expected


#: What the buffer tests give an attempt to log, and the gate they watch, both small
#: enough to reach in a loop.
LIMIT = 20
BATCH = 5


def test_a_block_may_log_a_field_named_level_or_event() -> None:
    """Both names are keywords the process logger already uses for its own two things."""
    log = BufferedLogger(run_id=uuid4(), step_name="noisy", limit=LIMIT, batch=BATCH)
    log.info("classified", level="secret", event="landing")
    row = log.drain()[0]
    assert row["fields"] == {"level": "secret", "event": "landing"}
    assert row["message"] == "classified"


def test_the_buffer_keeps_info_and_up_unless_asked_for_more() -> None:
    """Debug is something a run asks for, so the default gate drops it at record time."""
    log = BufferedLogger(run_id=uuid4(), step_name="quiet", limit=LIMIT, batch=BATCH)
    log.debug("dropped")
    log.info("kept")
    log.warning("kept too")
    assert [row["message"] for row in log.drain()] == ["kept", "kept too"]


def test_a_debug_keep_lets_everything_through() -> None:
    log = BufferedLogger(run_id=uuid4(), step_name="loud", keep=LogLevel.DEBUG, limit=LIMIT, batch=BATCH)
    log.debug("kept")
    assert [row["message"] for row in log.drain()] == ["kept"]


def test_a_warning_keep_drops_info() -> None:
    log = BufferedLogger(run_id=uuid4(), step_name="terse", keep=LogLevel.WARNING, limit=LIMIT, batch=BATCH)
    log.info("dropped")
    log.error("kept")
    assert [row["message"] for row in log.drain()] == ["kept"]


def test_the_full_buffer_warning_survives_any_keep() -> None:
    """The ceiling is about memory, not severity, so its warning outranks the gate."""
    log = BufferedLogger(run_id=uuid4(), step_name="noisy", keep=LogLevel.ERROR, limit=LIMIT, batch=BATCH)
    for index in range(LIMIT + 5):
        log.error(f"line {index}")
    rows = log.drain()
    assert rows[-1]["message"] == buffer_full(LIMIT)
    assert rows[-1]["level"] is LogLevel.WARNING


def test_kept_level_resolves_the_most_specific_pattern() -> None:
    """The longest matching pattern wins, with the bare star last of all."""
    levels = {"*": "warning", "weather.*": "debug", "weather.observations": "error"}
    assert kept_level(None, "shell.run") is LogLevel.INFO
    assert kept_level({}, "shell.run") is LogLevel.INFO
    assert kept_level(levels, "shell.run") is LogLevel.WARNING
    assert kept_level(levels, "weather.stations") is LogLevel.DEBUG
    assert kept_level(levels, "weather.observations") is LogLevel.ERROR
    assert kept_level({"http.*": "debug"}, "shell.run") is LogLevel.INFO


def test_a_step_that_logs_without_stopping_fills_the_buffer_and_no_further() -> None:
    """The buffer is held until the outcome writes it, so it needs a ceiling of its own."""
    log = BufferedLogger(run_id=uuid4(), step_name="noisy", limit=LIMIT, batch=BATCH)
    for index in range(LIMIT + 500):
        log.info(f"line {index}")
    rows = log.drain()
    assert len(rows) == LIMIT + 1
    assert rows[-1]["message"] == buffer_full(LIMIT)
    assert rows[-1]["level"] is LogLevel.WARNING


def test_a_message_longer_than_the_cap_is_truncated_and_says_so() -> None:
    log = BufferedLogger(run_id=uuid4(), step_name="noisy", limit=LIMIT, batch=BATCH)
    log.info("x" * (MAX_MESSAGE_CHARS + 100))
    message = log.drain()[0]["message"]
    assert len(message) < MAX_MESSAGE_CHARS + 100
    assert "truncated" in message


def test_the_size_gate_is_set_at_the_batch_and_cleared_by_a_drain() -> None:
    """The flusher waits on the event, so a buffer at the batch is written without a tick."""
    log = BufferedLogger(run_id=uuid4(), step_name="noisy", limit=LIMIT, batch=BATCH)
    for index in range(BATCH - 1):
        log.info(f"line {index}")
    assert not log.full.is_set()
    log.info("the line that fills it")
    assert log.full.is_set()
    log.drain()
    assert not log.full.is_set()


def test_entries_put_back_by_a_failed_flush_leave_the_gate_set() -> None:
    """A restored buffer is over the gate, and the next tick must not have to find that out."""
    log = BufferedLogger(run_id=uuid4(), step_name="noisy", limit=LIMIT, batch=BATCH)
    for index in range(BATCH):
        log.info(f"line {index}")
    rows = log.drain()
    log.restore(rows)
    assert log.full.is_set()


def test_a_logging_event_renders_as_the_record_grammar() -> None:
    """A command's diagnostics read like its story: one grammar, both streams."""
    rendered = GrammarRenderer()(
        None,
        "info",
        {
            "event": "pipeline applied",
            "level": "info",
            "logger": "dirigent.pipelines",
            "timestamp": "2026-08-30T18:00:00.000000Z",
            "action": "create",
        },
    )
    assert "[info    ]" in rendered
    assert "pipeline applied" in rendered
    assert "[log dirigent.pipelines]" in rendered, "the logger is what wrote the line"
    assert "action=create" in rendered
    assert "logger=" not in rendered, "and a line does not say one thing twice"


def test_a_logging_event_about_a_step_is_sourced_to_the_step() -> None:
    """What a line is about beats where in the program it came from, which stays in the tail."""
    rendered = GrammarRenderer()(
        None,
        "info",
        {
            "event": "attempt settled",
            "level": "info",
            "logger": "dirigent.engine",
            "timestamp": "2026-08-30T18:00:00.000000Z",
            "step": "greet",
        },
    )
    assert "[log greet]" in rendered
    assert "logger=dirigent.engine" in rendered


def test_an_event_that_is_not_a_record_still_renders() -> None:
    """A renderer that fails on an unexpected event loses the diagnostic that explains why."""
    assert GrammarRenderer()(None, "info", {"level": "info"})
