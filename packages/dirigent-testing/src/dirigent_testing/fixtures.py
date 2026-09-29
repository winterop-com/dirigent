"""The pytest plugin: the fixtures a block author gets from installing this package.

Registered by entry point, so the names live in every consumer's suite. They are prefixed
to say what they are handed by, because a consumer's own fixtures got there first.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from dirigent_testing.doubles import FakeContext, FakeStorage
from dirigent_testing.environment import scrub_configuration

#: The server the lanes that need a real PostgreSQL start for themselves.
POSTGRES_IMAGE: Final = "postgres:17-alpine"

#: Every database connection a pool has opened and not closed again, by identity.
_open_connections: set[int] = set()

#: Whether the listeners that fill the set above have been registered yet.
_watching_pools = False


def _watch_pools() -> None:
    """Register the pool listeners the connection guard counts with, once per process.

    SQLAlchemy is not a dependency of this package, so it is imported on first use: a pack
    without it installs the plugin, and has no pool to watch.
    """
    global _watching_pools
    if _watching_pools:
        return
    _watching_pools = True
    try:
        from sqlalchemy import event
        from sqlalchemy.pool import Pool
    except ModuleNotFoundError:  # pragma: no cover - a suite without SQLAlchemy opens no pooled connection
        return

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


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start a real PostgreSQL for the session, and hand back an asyncpg URL.

    Session-scoped, so every lane that asks for it shares one container.
    """
    postgres = pytest.importorskip("testcontainers.community.postgres")
    with postgres.PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture
def block_storage(tmp_path: Path) -> FakeStorage:
    """A storage facade over a throwaway directory."""
    return FakeStorage(tmp_path)


@pytest.fixture
def block_ctx(block_storage: FakeStorage, tmp_path: Path) -> FakeContext:
    """A context wired to that storage, with a scratch prefix inside it."""
    return FakeContext(block_storage, "file://scratch", work=tmp_path / "work" / "runs" / "one")


@pytest.fixture
def local_block_ctx(tmp_path: Path) -> FakeContext:
    """A context whose scratch is a real file:// prefix, for a block that reads it as files."""
    root = tmp_path / "artifacts"
    root.mkdir()
    return FakeContext(FakeStorage(root), f"file://{root}/runs/one", work=tmp_path / "work" / "runs" / "one")


@pytest.fixture
def defaults_only_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run a test against defaults, whatever the shell exports.

    Requested rather than autouse: a distributed plugin must not strip the environment of a
    suite that never asked it to, so a consumer opts in -- once, from its own conftest.
    """
    scrub_configuration(monkeypatch)


@pytest.fixture
def no_connection_outlives_its_loop() -> Iterator[None]:
    """Fail a test that ends with a database connection it opened still open.

    aiosqlite drives every connection from a worker thread that answers the event loop the
    connection was opened in. One still open when that loop closes is torn down later, by the
    garbage collector, and the thread then calls into a loop that is gone: a RuntimeError
    raised in a thread, which pytest reports against whichever test happens to be running at
    that moment rather than against the one that left the connection behind.

    Requested rather than autouse: a distributed plugin must not fail a run that never asked
    it to, so a consumer opts in -- once, from its own conftest.
    """
    _watch_pools()
    held = set(_open_connections)
    yield
    leaked = _open_connections - held
    assert not leaked, (
        f"{len(leaked)} database connection(s) this test opened were never closed: "
        "dispose every engine and close every session before the test ends"
    )
