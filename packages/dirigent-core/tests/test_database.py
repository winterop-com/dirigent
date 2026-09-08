"""How a transaction is opened, and running one again when the database broke a deadlock."""

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from dirigent_core.config import Settings
from dirigent_core.database import (
    DEADLOCK,
    SQLITE_BUSY_TIMEOUT_MS,
    create_engine,
    create_session_factory,
    is_deadlock,
    session_scope,
    with_deadlock_retry,
)


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
