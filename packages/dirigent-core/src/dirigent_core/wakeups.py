"""Wake-ups: a commit wakes whoever is waiting on what it changed, instead of their next poll.

Three channels exist. ``dirigent_work`` fires when a transaction queues an attempt that is
due, or brings a parked wait's next probe to now. ``dirigent_settled`` fires keyed by a run
id when one of its attempts moves or its own status changes. ``dirigent_sources`` is for input
sources: a change to a source row is published on it keyed by the source, so that whoever
holds the source restarts at once. Nothing in the engine publishes on it.

Every flush is observed, so a transaction that queues an attempt or moves a run publishes
without saying so. :func:`publish` is for a change the observer cannot see, such as a bulk
``UPDATE`` or a row of a table it does not watch.

On PostgreSQL a publish is ``pg_notify`` inside the transaction, which the server delivers
on commit and discards on rollback, and one listening connection per process fans each
notification out to the waiters in it. On SQLite, where every process is the only one, a
publish is held on the session and handed to the in-process :data:`hub` after commit.

A notification is only ever a hint to look sooner. Every waiter still wakes on its own
timeout and reads the database, so a lost notification costs the poll it replaced.
"""

import asyncio
import contextlib
import threading
import weakref
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime
from typing import Any, Final, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction, UOWTransaction
from sqlalchemy.pool import NullPool

from dirigent_client.enums import AttemptStatus, TriggerKind
from dirigent_core.logging import get_logger
from dirigent_core.models import Run, StepAttempt, utcnow

WORK: Final = "dirigent_work"

SETTLED: Final = "dirigent_settled"

SOURCES: Final = "dirigent_sources"

CHANNELS: Final = (WORK, SETTLED, SOURCES)

#: How often the listening connection is asked to answer, which is how a dead socket is found.
LISTENER_CHECK_SECONDS: Final = 10.0

#: The first pause before the listener reconnects, doubled per failure up to the ceiling.
LISTENER_RETRY_SECONDS: Final = 0.5

LISTENER_RETRY_MAX_SECONDS: Final = 10.0

#: Where a SQLite session holds what it publishes until it commits.
_OUTBOX: Final = "dirigent.wakeups"

#: Where a flush holds the topics it read off its rows until it has written them.
_FLUSHING: Final = "dirigent.wakeups.flushing"

type Topic = tuple[str, str | None]

_logger = get_logger("wakeups")


class _Signal:
    """One topic's generation counter and the futures waiting for it to move."""

    def __init__(self) -> None:
        self.generation = 0
        self.waiters: set[asyncio.Future[None]] = set()


class Mark(NamedTuple):
    """A topic's position, taken before a read, so a publish during the read is not lost."""

    signal: _Signal
    generation: int


def _resolve(future: asyncio.Future[None]) -> None:
    """Complete a waiter's future unless it already finished or was cancelled."""
    if not future.done():
        future.set_result(None)


class Hub:
    """The in-process fan-out: publishes bump a topic, and waiters on it return early.

    A keyed publish also moves the channel's unkeyed topic, so a waiter on the whole channel
    hears every key. Delivery is thread-safe, because a test client serves the API from a
    thread with its own event loop.
    """

    def __init__(self) -> None:
        """Start with no topic anyone is waiting on."""
        self._lock = threading.Lock()
        self._signals: weakref.WeakValueDictionary[Topic, _Signal] = weakref.WeakValueDictionary()

    def mark(self, channel: str, key: str | None = None) -> Mark:
        """Take a topic's position, to be waited on after the read it guards."""
        with self._lock:
            signal = self._signals.get((channel, key))
            if signal is None:
                signal = _Signal()
                self._signals[(channel, key)] = signal
            return Mark(signal, signal.generation)

    async def wait(self, mark: Mark, *, timeout: float) -> bool:
        """Wait until the topic moves past the mark, or the timeout passes; True if it moved."""
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        with self._lock:
            if mark.signal.generation != mark.generation:
                return True
            mark.signal.waiters.add(future)
        try:
            await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            return False
        finally:
            with self._lock:
                mark.signal.waiters.discard(future)
        return True

    def deliver(self, channel: str, key: str | None = None) -> None:
        """Move a topic, and the channel's unkeyed topic with it, waking everyone on either."""
        topics = [(channel, key)] if key is None else [(channel, key), (channel, None)]
        with self._lock:
            woken = [self._bump(topic) for topic in topics]
        for waiters in woken:
            _wake(waiters)

    def deliver_everything(self) -> None:
        """Move every topic, which is what a listener that may have missed some owes its waiters."""
        with self._lock:
            woken = [self._bump(topic) for topic in list(self._signals.keys())]
        for waiters in woken:
            _wake(waiters)

    def _bump(self, topic: Topic) -> list[asyncio.Future[None]]:
        """Advance one topic's generation and hand back its waiters; the lock is held."""
        signal = self._signals.get(topic)
        if signal is None:
            return []
        signal.generation += 1
        waiters = list(signal.waiters)
        signal.waiters.clear()
        return waiters


def _wake(waiters: Iterable[asyncio.Future[None]]) -> None:
    """Complete each waiter's future on the loop that owns it."""
    for future in waiters:
        loop = future.get_loop()
        if loop.is_closed():
            continue
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _resolve(future)
        else:
            loop.call_soon_threadsafe(_resolve, future)


hub: Final = Hub()


def settled_mark(run_id: UUID) -> Mark:
    """Take a run's settle position, which a waiter for its outcome waits on after reading it."""
    return hub.mark(SETTLED, str(run_id))


async def wait_settled(mark: Mark, *, timeout: float) -> bool:
    """Wait for the run a mark was taken on to move, or the timeout; True if it moved."""
    return await hub.wait(mark, timeout=timeout)


def _is_postgres(session: Session) -> bool:
    """Report whether a session speaks PostgreSQL."""
    return session.get_bind().dialect.name == "postgresql"


def _notify_statement(topics: Iterable[Topic]) -> sa.TextClause | None:
    """Build one ``SELECT pg_notify(...)`` for a set of topics, or None when there are none."""
    ordered = sorted(topics, key=lambda topic: (topic[0], topic[1] or ""))
    if not ordered:
        return None
    calls = ", ".join(f"pg_notify(:channel_{index}, :key_{index})" for index in range(len(ordered)))
    bound: dict[str, str] = {}
    for index, (channel, key) in enumerate(ordered):
        bound[f"channel_{index}"] = channel
        bound[f"key_{index}"] = key or ""
    return sa.text(f"SELECT {calls}").bindparams(**bound)  # noqa: S608 - the names are placeholders


def _hold(session: Session, topics: Iterable[Topic]) -> None:
    """Keep topics on a SQLite session until its transaction commits."""
    outbox: set[Topic] = session.info.setdefault(_OUTBOX, set())
    outbox.update(topics)


async def publish(session: AsyncSession, channel: str, key: str | None = None) -> None:
    """Publish a topic from inside a transaction, delivered only when that transaction commits."""
    sync = session.sync_session
    if _is_postgres(sync):
        statement = _notify_statement([(channel, key)])
        assert statement is not None  # one topic always builds a statement
        await session.execute(statement)
    else:
        _hold(sync, [(channel, key)])


def _moved(state: Any, *names: str) -> bool:
    """Report whether a flushed row is new or had any of these attributes changed."""
    if state.pending or state.transient:
        return True
    return any(state.attrs[name].history.has_changes() for name in names)


def _due(when: datetime | None, now: datetime) -> bool:
    """Report whether a due time has come, counting an unset one as now."""
    return when is None or when <= now


def _attempt_topics(attempt: StepAttempt, state: Any, now: datetime) -> list[Topic]:
    """Name what one flushed attempt changed: new due work, and the run's story."""
    topics: list[Topic] = []
    if not _moved(state, "status", "available_at", "next_poll_at"):
        return topics
    queued = attempt.status is AttemptStatus.QUEUED and _due(attempt.available_at, now)
    probing = attempt.status is AttemptStatus.WAITING and _due(attempt.next_poll_at, now)
    if queued or probing:
        topics.append((WORK, None))
    if _moved(state, "status"):
        topics.extend(_settled(attempt.run_id))
    return topics


def _settled(run_id: UUID | None) -> list[Topic]:
    """Name a run's settle topic, or nothing for a row whose id the flush has yet to assign."""
    return [] if run_id is None else [(SETTLED, str(run_id))]


def flushed_topics(session: Session) -> set[Topic]:
    """Read what a flush is about to write for the topics it wakes."""
    now = utcnow()
    topics: set[Topic] = set()
    for row in (*session.new, *session.dirty):
        if isinstance(row, StepAttempt):
            topics.update(_attempt_topics(row, sa.inspect(row), now))
        elif isinstance(row, Run) and _moved(sa.inspect(row), "status"):
            topics.update(_settled(row.id))
    return topics


def _observe(session: Session, _flush: UOWTransaction, _instances: object) -> None:
    """Note what the flush will change, while the changes can still be read off the rows."""
    session.info[_FLUSHING] = flushed_topics(session)


def _announce(session: Session, _flush: UOWTransaction) -> None:
    """Notify inside the transaction on PostgreSQL, or hold the topics until commit on SQLite."""
    topics: set[Topic] = session.info.pop(_FLUSHING, set())
    if not topics:
        return
    if _is_postgres(session):
        statement = _notify_statement(topics)
        if statement is not None:
            session.connection().execute(statement)
    else:
        _hold(session, topics)


def _deliver(session: Session) -> None:
    """Hand a committed SQLite transaction's topics to the in-process hub, once its root commits."""
    if session.in_nested_transaction():
        return
    for channel, key in session.info.pop(_OUTBOX, set()):
        hub.deliver(channel, key)


def _discard(session: Session, transaction: SessionTransaction) -> None:
    """Forget whatever a root transaction that ended without committing would have published."""
    if transaction.parent is None:
        session.info.pop(_OUTBOX, None)
        session.info.pop(_FLUSHING, None)


_OBSERVERS: Final = (
    ("before_flush", _observe),
    ("after_flush", _announce),
    ("after_commit", _deliver),
    ("after_transaction_end", _discard),
)


def observe() -> None:
    """Watch every session's flushes and commits for the topics they wake, once per process."""
    for name, handler in _OBSERVERS:
        if not event.contains(Session, name, handler):
            event.listen(Session, name, handler)


async def hasten_parent(session: AsyncSession, run: Run, now: datetime) -> None:
    """Bring forward the probe of a parent step waiting on this run, so it reads the settle now.

    A row another transaction holds is skipped: whoever holds it is probing it already.
    """
    if run.triggered_by_kind is not TriggerKind.PIPELINE or run.triggered_by_id is None:
        return
    statement = sa.select(StepAttempt).where(
        StepAttempt.run_id == run.triggered_by_id,
        StepAttempt.status == AttemptStatus.WAITING,
        StepAttempt.next_poll_at > now,
    )
    if _is_postgres(session.sync_session):
        statement = statement.with_for_update(skip_locked=True)
    for attempt in (await session.execute(statement)).scalars():
        if (attempt.remote_handle or {}).get("ref") == str(run.id):
            attempt.next_poll_at = now


class Listener:
    """One PostgreSQL connection per process, listening on every channel for the hub.

    It reconnects whenever the connection drops, and wakes every waiter on reconnecting,
    since what was published while it was away is unknown.
    """

    def __init__(self, url: str) -> None:
        """Bind the listener to a database it has not connected to yet."""
        self.url = url
        self.connected = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start listening in the background."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop listening and close the connection."""
        self._stopping.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        """Hold a listening connection until stopped, reconnecting with a widening pause."""
        pause = LISTENER_RETRY_SECONDS
        engine = sa_engine(self.url)
        try:
            while not self._stopping.is_set():
                try:
                    await self._listen(engine)
                    pause = LISTENER_RETRY_SECONDS
                except Exception as error:  # a dropped listener is recovered, never fatal
                    _logger.warning("wake-up listener lost its connection", error=str(error))
                self.connected.clear()
                if self._stopping.is_set():
                    return
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=pause)
                pause = min(pause * 2, LISTENER_RETRY_MAX_SECONDS)
        finally:
            await engine.dispose()

    async def _listen(self, engine: AsyncEngine) -> None:
        """Listen on one connection until it drops or the listener is stopped."""
        async with engine.connect() as connection:
            raw = await connection.get_raw_connection()
            driver: Any = raw.driver_connection
            dropped = asyncio.Event()
            driver.add_termination_listener(lambda _connection: dropped.set())  # pyright: ignore[reportUnknownLambdaType] - the driver is untyped
            for channel in CHANNELS:
                await driver.add_listener(channel, _received)
            self.connected.set()
            hub.deliver_everything()
            _logger.debug("wake-up listener connected", channels=list(CHANNELS))
            while not self._stopping.is_set() and not dropped.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(_first(self._stopping, dropped), timeout=LISTENER_CHECK_SECONDS)
                if self._stopping.is_set():
                    for channel in CHANNELS:
                        await driver.remove_listener(channel, _received)
                    return
                if not dropped.is_set():
                    await asyncio.wait_for(connection.execute(sa.text("SELECT 1")), timeout=LISTENER_CHECK_SECONDS)
            raise ConnectionError("the listening connection was closed")


async def _first(*events: asyncio.Event) -> None:
    """Return once any of these events is set."""
    waits = [asyncio.ensure_future(one.wait()) for one in events]
    try:
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for one in waits:
            one.cancel()


def _received(_connection: object, _pid: int, channel: str, payload: str) -> None:
    """Hand one notification to the hub."""
    hub.deliver(channel, payload or None)


def sa_engine(url: str) -> AsyncEngine:
    """Build the engine the listener draws its one held connection from."""
    return create_async_engine(url, poolclass=NullPool, future=True)


class _Held:
    """A process's listener and how many callers are using it."""

    def __init__(self, listener: Listener) -> None:
        """Hold a listener nobody is using yet."""
        self.listener = listener
        self.users = 0


_listeners: dict[str, _Held] = {}


@contextlib.asynccontextmanager
async def listening(url: str) -> AsyncGenerator[Listener | None]:
    """Hold this process's listener for a database while the block runs; SQLite needs none."""
    if not url.startswith("postgresql"):
        yield None
        return
    held = _listeners.get(url)
    if held is None:
        held = _listeners[url] = _Held(Listener(url))
        held.listener.start()
    held.users += 1
    try:
        yield held.listener
    finally:
        held.users -= 1
        if held.users == 0:
            _listeners.pop(url, None)
            await held.listener.stop()
