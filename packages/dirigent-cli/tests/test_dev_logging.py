"""How loud ``dg dev`` is, and the log file it keeps in its state directory."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog

from dirigent_cli import main
from dirigent_cli.context import CliState
from dirigent_core.config import Settings
from dirigent_core.logging import ACCESS_LOGGER, BRIDGED_LOGGERS, NOISY_LOGGERS, STEP_LOGGER, get_logger, own_handlers


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Leave the root logger and structlog as the test found them, closing any file opened."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_config = structlog.get_config()
    touched = {*BRIDGED_LOGGERS, *NOISY_LOGGERS, STEP_LOGGER}
    levels = {name: logging.getLogger(name).level for name in touched}
    try:
        yield
    finally:
        for handler in own_handlers(root):
            if handler not in saved_handlers:
                handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)
        structlog.configure(**saved_config)


def _settings(tmp_path: Path, **fields: Any) -> Settings:
    """Settings whose state directory is under the test's own directory."""
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / '.dirigent' / 'state' / 'dirigent.db'}", **fields)


def _lines(path: Path) -> list[dict[str, Any]]:
    """Read every record the log file holds, flushing the handlers that write it first."""
    for handler in own_handlers(logging.getLogger()):
        handler.flush()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _speak() -> None:
    """Log one line of each family whose level differs between a quiet and a verbose dev."""
    get_logger("audit").info("connection created", subject_kind="connection", subject_code="warehouse")
    get_logger("engine.steps").info("attempt settled", status="succeeded")
    logging.getLogger(ACCESS_LOGGER).info('127.0.0.1 - "GET /api/v1/runs HTTP/1.1" 200')
    get_logger("engine").debug("claimed", attempt_id="x")


def test_dev_logs_at_info_unless_asked_otherwise(tmp_path: Path) -> None:
    assert main.dev_log_level(None, _settings(tmp_path)) == "INFO"
    assert main.dev_log_level(CliState(), _settings(tmp_path)) == "INFO"


def test_a_log_level_the_settings_name_is_respected(tmp_path: Path) -> None:
    assert main.dev_log_level(CliState(), _settings(tmp_path, log_level="WARNING")) == "WARNING"


def test_a_flag_wins_over_the_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path, log_level="WARNING")
    assert main.dev_log_level(CliState(verbose=1), settings) == "INFO"
    assert main.dev_log_level(CliState(debug=True), settings) == "DEBUG"


def test_the_log_file_is_in_the_state_directory(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert main.dev_log_path(settings) == tmp_path / ".dirigent" / "state" / "dev.log"


def test_the_starting_and_ready_records_name_the_log_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    record = main.dev_started(settings, bound="http://127.0.0.1:4999", admin="admin", token=None, migrated=None)
    assert record["log"] == str((tmp_path / ".dirigent" / "state" / "dev.log").resolve())
    assert main.dev_facts(settings, admin="admin")["log"] == record["log"], "the ready record carries it too"


def test_the_log_file_is_ndjson_and_quiet_at_info(tmp_path: Path) -> None:
    """Audited changes reach the file; the request log and step-level detail do not."""
    settings = _settings(tmp_path)
    main._dev_logging(CliState(output="console"), settings, to_file=True)  # pyright: ignore[reportPrivateUsage]
    _speak()

    lines = _lines(tmp_path / ".dirigent" / "state" / "dev.log")
    events = [line["event"] for line in lines]
    assert events == ["connection created"]
    assert lines[0]["logger"] == "dirigent.audit"
    assert lines[0]["subject_code"] == "warehouse"
    assert lines[0]["level"] == "info"


def test_verbose_adds_the_request_log_and_step_detail(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    main._dev_logging(CliState(verbose=1), settings, to_file=True)  # pyright: ignore[reportPrivateUsage]
    _speak()

    loggers = [line["logger"] for line in _lines(tmp_path / ".dirigent" / "state" / "dev.log")]
    assert loggers == ["dirigent.audit", STEP_LOGGER, ACCESS_LOGGER]


def test_a_settings_level_quiets_the_file_too(tmp_path: Path) -> None:
    settings = _settings(tmp_path, log_level="WARNING")
    main._dev_logging(CliState(), settings, to_file=True)  # pyright: ignore[reportPrivateUsage]
    _speak()
    get_logger("audit").warning("kept")

    assert [line["event"] for line in _lines(tmp_path / ".dirigent" / "state" / "dev.log")] == ["kept"]


def test_the_log_file_rotates_by_size(tmp_path: Path) -> None:
    settings = _settings(tmp_path, dev_log_max_size="1KB", dev_log_backups=2)
    main._dev_logging(CliState(), settings, to_file=True)  # pyright: ignore[reportPrivateUsage]
    for index in range(100):
        get_logger("audit").info("connection updated", subject_code=f"warehouse-{index}")

    state = tmp_path / ".dirigent" / "state"
    assert sorted(path.name for path in state.glob("dev.log*")) == ["dev.log", "dev.log.1", "dev.log.2"]
    assert all(path.stat().st_size <= 1024 + 512 for path in state.glob("dev.log*"))
