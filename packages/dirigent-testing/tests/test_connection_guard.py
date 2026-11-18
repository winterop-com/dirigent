"""The connection guard: it passes a test that closes what it opened, and fails one that does not."""

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sa = pytest.importorskip("sqlalchemy")

LEAKY_SUITE = """
from sqlalchemy import create_engine


def test_it_leaves_a_connection_open(no_connection_outlives_its_loop):
    engine = create_engine("sqlite://")
    engine.connect()
"""


def test_it_passes_a_test_that_closed_every_connection(no_connection_outlives_its_loop: None) -> None:
    engine = sa.create_engine("sqlite://")

    with engine.connect() as connection:
        connection.execute(sa.text("select 1"))
    engine.dispose()


def test_it_passes_a_test_whose_connection_failed_while_it_was_set_up(no_connection_outlives_its_loop: None) -> None:
    """A connect listener that raises, as a cancellation landing in one does, strands its connection.

    The pool closes a stranded connection itself, and dispatches no close event for it.
    """
    engine = sa.create_engine("sqlite://")
    stranded: list[Any] = []

    @sa.event.listens_for(engine, "connect")
    def _cancelled(dbapi_connection: Any, _record: Any) -> None:  # pyright: ignore[reportUnusedFunction] - the event registers it
        stranded.append(dbapi_connection)
        raise RuntimeError("cancelled while the connection was set up")

    with pytest.raises(RuntimeError, match="cancelled"):
        engine.connect()
    engine.dispose()

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        stranded[0].execute("select 1")


def test_it_fails_a_test_that_left_one_open(tmp_path: Path) -> None:
    """Run the leak in its own pytest, because a leak here would fail this suite's own guard."""
    (tmp_path / "test_leak.py").write_text(LEAKY_SUITE)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "database connection(s) this test opened were never closed" in result.stdout
