"""Test configuration shared by every package."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.pool import Pool

from dirigent_core.config import ENV_FILE, Settings
from dirigent_testing import pin_terminal

#: The terminal the suite is actually being watched in, read before the width below hides it.
REAL_WIDTH = pin_terminal()

#: Every database connection a pool has opened and not closed again, by identity.
_open_connections: set[int] = set()


@event.listens_for(Pool, "connect")
def _connection_opened(dbapi_connection: Any, _record: Any) -> None:
    """Record a connection a pool has just opened."""
    _open_connections.add(id(dbapi_connection))


@event.listens_for(Pool, "close")
def _connection_closed(dbapi_connection: Any, _record: Any) -> None:
    """Forget a connection a pool has closed."""
    _open_connections.discard(id(dbapi_connection))


@event.listens_for(Pool, "close_detached")
def _detached_connection_closed(dbapi_connection: Any) -> None:
    """Forget a connection closed after it was detached from its pool."""
    _open_connections.discard(id(dbapi_connection))


@pytest.fixture(autouse=True)
def _no_connection_outlives_its_loop() -> Iterator[None]:
    """Fail a test that ends with a database connection it opened still open.

    aiosqlite drives every connection from a worker thread that answers the event loop the
    connection was opened in. One still open when that loop closes is torn down later, by the
    garbage collector, and the thread then calls into a loop that is gone: a RuntimeError
    raised in a thread, which pytest reports against whichever test happens to be running at
    that moment rather than against the one that left the connection behind.
    """
    held = set(_open_connections)
    yield
    leaked = _open_connections - held
    assert not leaked, (
        f"{len(leaked)} database connection(s) this test opened were never closed: "
        "dispose every engine and close every session before the test ends"
    )


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
