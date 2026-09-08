"""Async engine and session plumbing."""

import asyncio
import random
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dirigent_core.config import Settings

_logger = structlog.get_logger("dirigent.database")


#: How long a SQLite connection waits for the write lock before it gives up.
#:
#: Every transaction takes the lock at ``BEGIN IMMEDIATE`` and holds it to commit, so this is
#: how long one caller waits behind the callers ahead of it. A fan-out settling forty items
#: puts forty short transactions in that queue, and an apply arriving mid-fan-out waits for
#: all of them; fifteen seconds outlasts that queue on a laptop whose fsync stalls, and is
#: still short enough that a transaction nothing will ever release fails rather than hangs.
SQLITE_BUSY_TIMEOUT_MS: Final = 15_000

#: What every SQLite connection is configured with, in order.
#:
#: SQLite enforces no foreign key without being asked to, per connection, and the engine
#: relies on them: an attempt's run and a log entry's attempt are what make an orphan
#: impossible. WAL is what lets the API, the scheduler and a worker share one file, since a
#: reader no longer blocks a writer; ``NORMAL`` is the durability that goes with it, losing
#: at most the last commits to a power cut and nothing to a crashed process. WAL still
#: allows one writer at a time, and without a busy timeout the second writer fails with
#: "database is locked" instead of waiting its turn.
SQLITE_PRAGMAS: Final[tuple[str, ...]] = (
    "foreign_keys = ON",
    "journal_mode = WAL",
    "synchronous = NORMAL",
    f"busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}",
)


def _configure_sqlite(engine: AsyncEngine) -> None:
    """Apply the pragmas to every SQLite connection, and open every transaction immediate.

    The busy timeout only covers a connection that waits for the write lock. It does not
    cover the one case SQLite refuses outright: a transaction that began as a reader and
    then asks to write while another connection holds the write lock. SQLite fails that
    upgrade with "database is locked" the instant it is asked, because the reader's snapshot
    is what the writer ahead of it is invalidating and waiting could only deadlock. An apply
    reads the pipeline, its versions and the plan before it inserts, which is exactly that
    shape whenever a worker is claiming or settling an attempt at the same moment.

    ``BEGIN IMMEDIATE`` takes the write lock at the start of the transaction instead, where
    waiting is safe, so the busy timeout covers it. Every transaction opens that way rather
    than only the ones that write: which statements a session will run is not known when it
    begins, and one process is what SQLite is sanctioned for here.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(connection: Any, _record: Any) -> None:  # pyright: ignore[reportUnusedFunction] - the event registers it
        # None hands transaction control to SQLAlchemy: the driver stops emitting its own
        # deferred BEGIN before a write, and the begin below is what opens every transaction.
        connection.isolation_level = None
        cursor = connection.cursor()
        try:
            for pragma in SQLITE_PRAGMAS:
                cursor.execute(f"PRAGMA {pragma}")
        finally:
            cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _immediate(connection: Any) -> None:  # pyright: ignore[reportUnusedFunction] - the event registers it
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine for the configured database."""
    if settings.is_sqlite:
        ensure_sqlite_directory(settings)
        engine = create_async_engine(settings.database_url, echo=settings.database_echo, future=True)
        _configure_sqlite(engine)
        return engine
    return create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout.total_seconds(),
        pool_recycle=int(settings.database_pool_recycle.total_seconds()) if settings.database_pool_recycle else -1,
        pool_pre_ping=True,
        future=True,
    )


def ensure_sqlite_directory(settings: Settings) -> None:
    """Create the directory a SQLite file lives in; the driver opens a file, never a path.

    A directory that cannot be created is left to surface as the connection error it causes.
    """
    path = settings.sqlite_path
    if path is None:
        return
    with suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)


def create_lock_engine(settings: Settings) -> AsyncEngine:
    """Build an engine for a connection that is held, not pooled.

    The scheduler's advisory lock is session-scoped, so its connection is held for the
    process's lifetime; taking it from the API's pool would permanently consume a slot.
    """
    return create_async_engine(settings.database_url, poolclass=NullPool, pool_pre_ping=True, future=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory the engine and the API share."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession]:
    """Run a unit of work in one transaction: one commit per state transition."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


#: PostgreSQL's SQLSTATE for a deadlock it broke by aborting one of the transactions.
DEADLOCK: Final = "40P01"

#: How many times a transaction aborted by a deadlock is run again before it is raised.
DEADLOCK_ATTEMPTS: Final = 3


def is_deadlock(error: BaseException) -> bool:
    """Report whether the database aborted this transaction to break a deadlock."""
    original = getattr(error, "orig", None)
    return getattr(original, "sqlstate", None) == DEADLOCK


async def with_deadlock_retry[T](work: Callable[[], Awaitable[T]], *, attempts: int = DEADLOCK_ATTEMPTS) -> T:
    """Run one transaction again when the database aborted it to break a deadlock.

    The claim orders its locks attempt-then-run and an outcome orders them run-then-attempt,
    which two workers can close into a cycle. Both transactions re-read everything they
    decide on, so the one PostgreSQL picked off is safe to run again; nothing of it survived
    the rollback.
    """
    for remaining in range(attempts - 1, -1, -1):
        try:
            return await work()
        except DBAPIError as error:
            if remaining == 0 or not is_deadlock(error):
                raise
            _logger.debug("transaction retried after a deadlock", attempts_left=remaining)
            await asyncio.sleep(random.uniform(0.01, 0.05))
    raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover


async def ping(engine: AsyncEngine) -> bool:
    """Report whether the database answers."""
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.text("SELECT 1"))
    except Exception:
        return False
    return True
