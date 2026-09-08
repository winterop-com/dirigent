"""The pytest plugin: the fixtures a block author gets from installing this package.

Registered by entry point, so the names live in every consumer's suite. They are prefixed
to say what they are handed by, because a consumer's own fixtures got there first.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from dirigent_testing.doubles import FakeContext, FakeStorage
from dirigent_testing.environment import scrub_configuration

#: The server the lanes that need a real PostgreSQL start for themselves.
POSTGRES_IMAGE: Final = "postgres:17-alpine"


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
