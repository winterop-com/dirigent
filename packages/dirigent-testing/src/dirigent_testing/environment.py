"""Putting a test suite in a known environment: dirigent's own variables, colour, and width.

Both are explicit calls rather than import side effects, so installing the plugin never
rewrites the environment of a suite that did not ask for it.
"""

import os
import shutil

import pytest

#: Prefixes of variables that configure dirigent at runtime.
CONFIGURING_PREFIXES = ("DIRIGENT_", "DG_", "OTEL_")

#: Width rich renders at under test, so an assertion never depends on the terminal.
TEST_WIDTH = "200"

_real_width: int | None = None


def pin_terminal() -> int:
    """Fix width and colour for everything built afterwards, and return the real width.

    A console reads both when it is built, which happens at import, so this belongs at the
    top of a conftest rather than in a fixture. The width returned is the one the terminal
    reported the first time, which the pinning then hides.
    """
    global _real_width
    if _real_width is None:
        _real_width = shutil.get_terminal_size().columns
    os.environ["COLUMNS"] = TEST_WIDTH
    os.environ["TERMINAL_WIDTH"] = TEST_WIDTH  # typer renders help at this width
    # A test that reads what a command printed must see the same text whether or not a
    # terminal is attached, and rich decides colour when a console is built.
    os.environ["NO_COLOR"] = "1"
    return _real_width


def scrub_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take every variable configuring dirigent out of one test's environment.

    A developer with DIRIGENT_ENABLED_UNSAFE_BLOCKS set for manual testing would otherwise
    turn the tests that prove the guard refuses into passes.
    """
    for name in list(os.environ):
        if name.startswith(CONFIGURING_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COLUMNS", TEST_WIDTH)
