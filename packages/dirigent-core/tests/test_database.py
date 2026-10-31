"""How a transaction is opened, and running one again when the database broke a deadlock."""

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
import sqlalchemy as sa
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.exc import DBAPIError, IntegrityError

from dirigent_core.config import Settings
from dirigent_core.database import (
    DEADLOCK,
    SQLITE_BUSY_TIMEOUT_MS,
    create_engine,
    create_session_factory,
    is_deadlock,
    open_sqlite,
    session_scope,
    storable_json,
    with_deadlock_retry,
)
from dirigent_core.models import Notification, RunItem, SourceInput, StepAttempt
from dirigent_core.types import SaidString, SaidText


class Aborted(Exception):
    """What asyncpg raises under SQLAlchemy, as far as this matters: a SQLSTATE."""

    def __init__(self, sqlstate: str) -> None:
        """Carry the SQLSTATE the database reported."""
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def deadlock() -> DBAPIError:
    """One deadlock, wrapped the way SQLAlchemy wraps a driver error."""
    return DBAPIError("SELECT 1", None, Aborted(DEADLOCK))


def test_a_deadlock_is_told_apart_from_every_other_database_error() -> None:
    assert is_deadlock(deadlock())
    assert not is_deadlock(DBAPIError("SELECT 1", None, Aborted("23505")))
    assert not is_deadlock(IntegrityError("INSERT", None, Exception("duplicate key")))
    assert not is_deadlock(RuntimeError("not a database error at all"))


async def test_a_transaction_the_database_aborted_is_run_again() -> None:
    attempts = 0

    async def work() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise deadlock()
        return "settled"

    assert await with_deadlock_retry(work) == "settled"
    assert attempts == 2, "the first was aborted, the second is the one that counted"


async def test_a_deadlock_that_will_not_clear_is_raised_rather_than_retried_forever() -> None:
    attempts = 0

    async def work() -> None:
        nonlocal attempts
        attempts += 1
        raise deadlock()

    with pytest.raises(DBAPIError):
        await with_deadlock_retry(work, attempts=3)
    assert attempts == 3, "it gives up rather than holding the worker on one unit"


async def test_any_other_failure_is_raised_the_first_time() -> None:
    """Only a deadlock is safe to run again; everything else is the caller's to see."""
    attempts = 0

    async def work() -> None:
        nonlocal attempts
        attempts += 1
        raise IntegrityError("INSERT", None, Exception("duplicate key"))

    with pytest.raises(IntegrityError):
        await with_deadlock_retry(work)
    assert attempts == 1


async def test_the_work_is_handed_the_same_state_on_the_second_run() -> None:
    """A retry must not run against something the first attempt consumed."""
    entries = ["one", "two"]
    written: list[list[str]] = []
    attempts = 0

    async def work() -> None:
        nonlocal attempts
        attempts += 1
        written.append(list(entries))
        if attempts == 1:
            raise deadlock()

    await with_deadlock_retry(work)
    assert written == [["one", "two"], ["one", "two"]], "the second run wrote what the first would have"


async def test_a_result_is_returned_untouched_when_nothing_deadlocks() -> None:
    async def work() -> dict[str, Any]:
        return {"claimed": 1}

    assert await with_deadlock_retry(work) == {"claimed": 1}


@pytest.fixture
def sqlite_settings(tmp_path: Path) -> Settings:
    """Point the settings at a throwaway file-backed SQLite database."""
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}")


async def test_every_connection_carries_the_pragmas(sqlite_settings: Settings) -> None:
    """The pragmas are the contract WAL concurrency stands on, busy_timeout included."""
    import sqlalchemy as sa

    engine = create_engine(sqlite_settings)
    try:
        async with engine.connect() as connection:
            wanted_pragmas = (("foreign_keys", 1), ("journal_mode", "wal"), ("busy_timeout", SQLITE_BUSY_TIMEOUT_MS))
            for pragma, wanted in wanted_pragmas:
                answered = (await connection.execute(sa.text(f"PRAGMA {pragma}"))).scalar()
                assert answered == wanted, f"{pragma} answered {answered!r}"
    finally:
        await engine.dispose()


async def test_a_read_sees_a_write_another_session_just_committed(sqlite_settings: Settings) -> None:
    """A request reads what the request before it wrote, or an API contradicts itself.

    In WAL a reader sees the snapshot its transaction began with, so a connection returned to
    a pool with one still open answers from before the write. Repeated, because the failure it
    guards against was intermittent: one attempt proves nothing.
    """
    from dirigent_core.models import Base, Pipeline

    engine = create_engine(sqlite_settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        for index in range(25):
            code = f"written-{index}"
            async with session_scope(sessions) as session:
                session.add(Pipeline(code=code))
            async with session_scope(sessions) as session:
                found = await session.execute(sa.select(Pipeline.code).where(Pipeline.code == code))
                assert found.scalar_one_or_none() == code, f"the write of {code} was not visible to the next read"
    finally:
        await engine.dispose()


#: How long the holding transaction keeps the write lock before it commits.
HELD_SECONDS = 0.3


async def test_a_transaction_that_reads_before_it_writes_waits_for_the_lock(sqlite_settings: Settings) -> None:
    """The shape an apply has, against the write lock a worker holds.

    Applying a document opens a savepoint, reads the pipeline row, and inserts it when there
    is none. A transaction that began as a reader and then asks to write is the one case
    SQLite refuses outright rather than waiting: the busy timeout never runs, and the apply
    fails with "database is locked" the instant a worker's claim or outcome holds the lock.
    Opening every transaction with ``BEGIN IMMEDIATE`` is what puts the wait back.
    """
    from dirigent_core.models import Base, Pipeline

    engine = create_engine(sqlite_settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)

        holder = sessions()
        holder.add(Pipeline(code="held-by-the-worker"))
        await holder.flush()

        async def release() -> None:
            await asyncio.sleep(HELD_SECONDS)
            await holder.commit()
            await holder.close()

        releasing = asyncio.create_task(release())
        started = time.monotonic()
        async with session_scope(sessions) as session, session.begin_nested():
            found = await session.execute(sa.select(Pipeline).where(Pipeline.code == "applied"))
            assert found.scalar_one_or_none() is None
            session.add(Pipeline(code="applied"))
            await session.flush()
        waited = time.monotonic() - started
        await releasing

        assert waited >= HELD_SECONDS, "it returned before the lock was free, so it never took it"
        assert waited < SQLITE_BUSY_TIMEOUT_MS / 1000, "it waited out the busy timeout rather than the holder"
        async with session_scope(sessions) as session:
            codes = (await session.execute(sa.select(Pipeline.code).order_by(Pipeline.code))).scalars().all()
        assert list(codes) == ["applied", "held-by-the-worker"], "both transactions committed"
    finally:
        await engine.dispose()


async def test_a_connection_that_never_opened_takes_its_thread_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every SQLite connection answers the loop from a worker thread, a refused one included.

    A thread still running when the loop closes reports into nothing, which surfaces as a
    RuntimeError raised in a thread against whatever happens to be running then.
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    threads: list[threading.Thread] = []
    connect = aiosqlite.connect

    def recording(*args: Any, **kwargs: Any) -> aiosqlite.Connection:
        connection = connect(*args, **kwargs)
        threads.append(connection._thread)  # pyright: ignore[reportPrivateUsage] - the thread under test
        return connection

    monkeypatch.setattr(aiosqlite, "connect", recording)
    with pytest.raises(sqlite3.OperationalError):
        await open_sqlite(str(blocker / "dirigent.db"))
    assert threads and not threads[0].is_alive(), "the connection's thread outlived the attempt that failed"


def test_said_text_writes_what_utf8_cannot_as_its_escape() -> None:
    said = SaidText()
    assert said.process_bind_param("held \udc80 here", DefaultDialect()) == "held \\udc80 here"
    assert said.process_bind_param("held \x00 here", DefaultDialect()) == "held \\u0000 here"
    assert said.process_bind_param("blå", DefaultDialect()) == "blå"
    assert said.process_bind_param(None, DefaultDialect()) is None


def test_a_json_column_holds_half_a_surrogate_pair_as_the_text_of_its_escape() -> None:
    held = json.loads(storable_json({"lone \udc80": ["a \ud800 b"], "pair": "\U0001f600", "slash": "\\udc80"}))
    assert held == {"lone \\udc80": ["a \\ud800 b"], "pair": "\U0001f600", "slash": "\\udc80"}
    assert storable_json({"plain": [1, None, True, "blå"]}) == '{"plain": [1, null, true, "blå"]}'


def test_a_json_column_holds_a_nul_as_the_text_of_its_escape() -> None:
    held = json.loads(storable_json({"nul \x00": ["a \x00 b"], "said": "\\u0000", "slash": "\\\x00", "tab": "\t"}))
    assert held == {"nul \\u0000": ["a \\u0000 b"], "said": "\\u0000", "slash": "\\\\u0000", "tab": "\t"}


def test_said_string_writes_its_escape_and_cuts_it_to_the_column() -> None:
    said = SaidString(12)
    assert said.process_bind_param("key \x00", DefaultDialect()) == "key \\u0000"
    assert said.process_bind_param("held \udc80 here", DefaultDialect()) == "held \\udc80 "
    assert said.process_bind_param("blå", DefaultDialect()) == "blå"
    assert said.process_bind_param(None, DefaultDialect()) is None


@pytest.mark.parametrize(
    ("column", "kind"),
    [
        (RunItem.item_key, SaidString),
        (StepAttempt.waiting_message, SaidString),
        (Notification.subject, SaidText),
        (Notification.body, SaidText),
        (SourceInput.path, SaidString),
        (SourceInput.label, SaidString),
    ],
    ids=["item_key", "waiting_message", "notification_subject", "notification_body", "input_path", "input_label"],
)
def test_text_a_run_a_caller_or_a_service_produced_is_written_as_said(column: Any, kind: type) -> None:
    """Each of these holds text from outside the instance, which can carry a NUL or half a surrogate pair."""
    assert isinstance(column.type, kind)
