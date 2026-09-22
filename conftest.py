"""Test configuration shared by every package."""

import pytest

from dirigent_core.config import ENV_FILE, Settings
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
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def dotenv_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put back the dotenv layer the fixture above hides, for a test that is about it."""
    monkeypatch.setitem(Settings.model_config, "env_file", ENV_FILE)


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
