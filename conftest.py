"""Test configuration shared by every package."""

import logging
from collections.abc import Iterator

import pytest
import structlog

from dirigent_core import config
from dirigent_testing import pin_terminal

#: The terminal the suite is actually being watched in, read before the width below hides it.
REAL_WIDTH = pin_terminal()


@pytest.fixture(autouse=True)
def _no_connection_outlives_its_loop(no_connection_outlives_its_loop: None) -> None:
    """Hold every test in this repository to the packaged connection guard."""


@pytest.fixture(autouse=True)
def _ignore_the_developer_environment(defaults_only_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test against defaults, whatever the shell exports or this checkout's .env holds.

    The dotenv layer reads the working directory, which under test is the checkout, and a
    developer keeps a real .env there. A test about that layer asks for ``dotenv_layer``.
    """
    monkeypatch.setattr(config, "ENV_FILE", None)


@pytest.fixture(autouse=True)
def _logging_left_as_found() -> Iterator[None]:
    """Put structlog's configuration and every logger's level, propagation and switch back after each test.

    A command run in-process configures logging for the whole process, and its level filter
    would otherwise decide what a later test on the same worker can capture. A logger the
    test brought into being goes back to the defaults it was born with.
    """
    saved = structlog.get_config()
    disabled = logging.root.manager.disable
    found = {logging.getLogger(), *_existing_loggers()}
    states = [(logger, logger.level, logger.propagate, logger.disabled) for logger in found]
    yield
    structlog.configure(**saved)
    logging.disable(disabled)
    for logger, level, propagate, off in states:
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = off
    for born in _existing_loggers() - found:
        born.setLevel(logging.NOTSET)
        born.propagate = True
        born.disabled = False


def _existing_loggers() -> set[logging.Logger]:
    """List every named logger the process has created so far."""
    return {logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)}


@pytest.fixture
def dotenv_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put back the dotenv layer the fixture above hides, for a test that is about it."""
    monkeypatch.setattr(config, "ENV_FILE", ".env")


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Keep pytest's own output at the width of the terminal watching it.

    ``COLUMNS`` is fixed above so a rendering under test never depends on the window, and
    pytest reads the same variable for its progress line -- which would otherwise be written
    200 columns wide whatever the terminal is, and wrap.
    """
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter._tw.fullwidth = REAL_WIDTH  # noqa: SLF001 - the reporter's writer is its own
