"""Test configuration shared by every package."""

import pytest

from dirigent_testing import pin_terminal

#: The terminal the suite is actually being watched in, read before the width below hides it.
REAL_WIDTH = pin_terminal()


@pytest.fixture(autouse=True)
def _ignore_the_developer_environment(defaults_only_environment: None) -> None:
    """Run every test in this repository against defaults, whatever the shell exports."""


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
