"""Held sources: a worker keeps each one's consumer open under a lease, and makes a run of each message.

Each worker takes up the held sources nobody holds, up to ``source_held_max``, by writing its
name and a lease expiry on the row, and keeps the lease alive for as long as the consumer is
open. A source whose lease runs out, because its worker died, is free for any other worker.

A message becomes a run in a transaction of its own batch, under the pipeline's lock, and is
acknowledged only after that transaction commits: an input is never lost, and after a crash
between the two it is delivered again. A batch no run can be made of in full commits nothing
and is not acknowledged, so the broker delivers it again once the consumer is opened anew.

The consumer is closed and the lease let go when the source is paused, redeclared, removed or
its pipeline deactivated, which a change to its row publishes on ``dirigent_sources``; it is
then taken up again from its new declaration on a later tick.
"""

import asyncio
import contextlib
from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_common import JsonMap, scrub
from dirigent_core import wakeups
from dirigent_core.database import session_scope
from dirigent_core.engine.context import ConnectionRecord, load_connections, open_record
from dirigent_core.engine.references import ReferenceScope, resolve
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.logging import get_logger
from dirigent_core.messages import RUN_UNKNOWN_CONNECTION
from dirigent_core.models import Pipeline, Source, utcnow
from dirigent_core.sources.polling import InputRefused, backoff_for, enter_input
from dirigent_core.sources.rows import held, in_flight, max_in_flight
from dirigent_plugin import ConnectionRef, Logger, Storage
from dirigent_plugin.sources import HeldSource

#: How long a held source waits before it looks again, while as many of its runs are in flight as it allows.
BACKLOGGED_SECONDS: Final = 1.0

_logger = get_logger("sources.holding")


class Taken(BaseModel):
    """One held source a worker has just taken the lease on."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    pipeline_id: UUID
    pipeline: str
    code: str


class Holder:
    """One worker's held sources: which it holds, and the task keeping each one's consumer open."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], services: EngineServices, *, owner: str) -> None:
        """Bind the holder to the database, the services, and the worker it holds for."""
        self.sessions = sessions
        self.services = services
        self.owner = owner
        self.holding: dict[UUID, asyncio.Task[None]] = {}
        self._stopping = asyncio.Event()

    async def tick(self, *, now: datetime | None = None) -> list[UUID]:
        """Take up whatever held sources nobody holds, as many as this worker has room for."""
        for source_id, task in list(self.holding.items()):
            if task.done():
                del self.holding[source_id]
        room = self.services.settings.source_held_max - len(self.holding)
        if room <= 0 or self._stopping.is_set():
            return []
        async with session_scope(self.sessions) as session:
            taken = await take_free(session, self.services, owner=self.owner, now=now or utcnow(), limit=room)
        for one in taken:
            self.holding[one.source_id] = asyncio.create_task(self._hold(one))
        return [one.source_id for one in taken]

    async def stop(self) -> None:
        """Close every consumer this worker holds and let its lease go."""
        self._stopping.set()
        tasks = list(self.holding.values())
        await asyncio.gather(*tasks, return_exceptions=True)
        self.holding.clear()

    async def _hold(self, taken: Taken) -> None:
        """Keep one source's consumer open until it is let go, then release or back off its lease."""
        opened: set[str] = set()
        try:
            await hold(self.sessions, self.services, taken, owner=self.owner, stopping=self._stopping, opened=opened)
        except Exception as error:  # the source's failure, recorded on its row and backed off
            said = _said(error, opened)
            await _failed(self.sessions, self.services, taken.source_id, owner=self.owner, error=said)
            return
        await _release(self.sessions, taken.source_id, owner=self.owner)


async def take_free(
    session: AsyncSession, services: EngineServices, *, owner: str, now: datetime, limit: int
) -> list[Taken]:
    """Write this worker's lease on up to ``limit`` held sources that nobody holds and that are due."""
    names = [name for name, kind in services.sources.items() if isinstance(kind, HeldSource)]
    if not names:
        return []
    statement = (
        sa.select(Source, Pipeline.code)
        .join(Pipeline, Pipeline.id == Source.pipeline_id)
        .where(
            Source.kind.in_(names),
            Source.next_poll_at.is_not(None),
            Source.next_poll_at <= now,
            Source.paused.is_(False),
            Pipeline.active.is_(True),
            sa.or_(Source.lease_expires_at.is_(None), Source.lease_expires_at <= now),
        )
        .order_by(Source.next_poll_at)
        .limit(limit)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(of=Source, skip_locked=True)
    taken: list[Taken] = []
    for row, pipeline in await session.execute(statement):
        row.lease_owner = owner
        row.lease_expires_at = now + services.settings.source_poll_lease
        taken.append(Taken(source_id=row.id, pipeline_id=row.pipeline_id, pipeline=pipeline, code=row.code))
    return taken


async def hold(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    taken: Taken,
    *,
    owner: str,
    stopping: asyncio.Event,
    opened: set[str],
) -> None:
    """Open the source's consumer and turn what it receives into runs, until the source is let go.

    ``opened`` collects the secrets the consumer opens, for whoever writes what stopped it.
    """
    async with sessions() as session:
        row = await session.get(Source, taken.source_id)
        found = held(services.sources, row) if row is not None else None
        connections = await load_connections(session)
        storage = await services.bound_storage(session)
    if row is None or found is None:
        return
    kind = found[0]
    declared = dict(row.config)
    config = kind.config_model.model_validate(
        resolve(cast("JsonValue", declared), ReferenceScope(artifacts=services.storage.artifact_root))
    )
    mark = wakeups.hub.mark(wakeups.SOURCES, f"{taken.pipeline}/{taken.code}")
    ctx = _HoldContext(storage=storage, connections=connections, services=services, opened=opened)
    settings = services.settings
    async with kind.listen(config, ctx) as listener:
        await _opened(sessions, taken.source_id, owner=owner)
        _logger.info("source held", source=taken.code, pipeline=taken.pipeline, worker=owner)
        renew_at = asyncio.get_running_loop().time() + settings.source_poll_lease.total_seconds() / 2
        while not stopping.is_set():
            if wakeups.hub.moved(mark):
                mark = wakeups.hub.mark(wakeups.SOURCES, f"{taken.pipeline}/{taken.code}")
                if not await _still_wanted(sessions, services, taken.source_id, declared, owner=owner):
                    return
            if asyncio.get_running_loop().time() >= renew_at:
                if not await _renew(sessions, services, taken.source_id, owner=owner):
                    return
                renew_at = asyncio.get_running_loop().time() + settings.source_poll_lease.total_seconds() / 2
            room = await _room(sessions, services, taken.source_id)
            if room <= 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stopping.wait(), timeout=BACKLOGGED_SECONDS)
                continue
            inputs = await listener.receive(min(room, settings.source_poll_batch), settings.source_hold_wait)
            if inputs:
                await _enter_all(sessions, services, taken, kind, inputs, owner=owner)
                await listener.ack()


async def _enter_all(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    taken: Taken,
    kind: HeldSource[Any, Any],
    inputs: list[Any],
    *,
    owner: str,
) -> list[UUID]:
    """Make a run of every input in one transaction, or of none; raise when none can be made."""
    runs: list[UUID] = []
    async with session_scope(sessions) as session:
        await lock_pipeline(session, taken.pipeline_id)
        row = await session.get(Source, taken.source_id, populate_existing=True)
        pipeline = await session.get(Pipeline, taken.pipeline_id)
        if row is None or pipeline is None or row.lease_owner != owner:
            raise InputRefused("the source is no longer held by this worker")
        for output in inputs:
            runs.append(
                await enter_input(
                    session,
                    services,
                    row,
                    pipeline,
                    output.model_dump(mode="json"),
                    via="hold",
                    label=kind.label_of(output),
                    duration_ms=0,
                )
            )
        row.failures = 0
        row.last_error = None
    _logger.info("source received", source=taken.code, runs=len(runs))
    return runs


async def _opened(sessions: async_sessionmaker[AsyncSession], source_id: UUID, *, owner: str) -> None:
    """Mark a source as held: its consumer opened, so it is no longer starting."""
    async with session_scope(sessions) as session:
        await session.execute(
            sa.update(Source)
            .where(Source.id == source_id, Source.lease_owner == owner)
            .values(polled_at=utcnow(), failures=0, last_error=None)
        )


async def _renew(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, source_id: UUID, *, owner: str
) -> bool:
    """Push this worker's lease out again; False when another worker has taken the source."""
    async with session_scope(sessions) as session:
        renewed = await session.execute(
            sa.update(Source)
            .where(Source.id == source_id, Source.lease_owner == owner)
            .values(lease_expires_at=utcnow() + services.settings.source_poll_lease)
        )
    return bool(cast("Any", renewed).rowcount)


async def _still_wanted(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    source_id: UUID,
    declared: JsonMap,
    *,
    owner: str,
) -> bool:
    """Say whether the source is still to be held as it was opened: not paused, not redeclared, still this worker's."""
    async with sessions() as session:
        row = await session.get(Source, source_id)
        pipeline = await session.get(Pipeline, row.pipeline_id) if row is not None else None
    if row is None or pipeline is None:
        return False
    return (
        not row.paused
        and pipeline.active
        and row.lease_owner == owner
        and dict(row.config) == declared
        and held(services.sources, row) is not None
    )


async def _room(sessions: async_sessionmaker[AsyncSession], services: EngineServices, source_id: UUID) -> int:
    """Say how many inputs the source may take now, under its own ``max_in_flight``."""
    async with sessions() as session:
        row = await session.get(Source, source_id)
        if row is None:
            return 0
        bound = max_in_flight(services.sources, row)
        if bound is None:
            return services.settings.source_poll_batch
        unsettled = (await in_flight(session, [source_id])).get(source_id, 0)
    return bound - unsettled


async def _release(sessions: async_sessionmaker[AsyncSession], source_id: UUID, *, owner: str) -> None:
    """Let go of a lease this worker still holds, so the source is free to be taken up again at once."""
    async with session_scope(sessions) as session:
        await session.execute(
            sa.update(Source)
            .where(Source.id == source_id, Source.lease_owner == owner)
            .values(lease_owner=None, lease_expires_at=None, next_poll_at=utcnow())
        )


async def _failed(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    source_id: UUID,
    *,
    owner: str,
    error: str,
) -> None:
    """Record a held source's failure, let its lease go, and take it up again after a backoff."""
    async with session_scope(sessions) as session:
        row = await session.get(Source, source_id, populate_existing=True)
        if row is None or row.lease_owner != owner:
            return
        row.failures += 1
        row.last_error = error
        row.next_poll_at = utcnow() + backoff_for(row.failures, services)
        row.lease_owner = None
        row.lease_expires_at = None
        failures = row.failures
    _logger.warning("held source failed", source=str(source_id), failures=failures, error=error)


def _said(error: Exception, secrets: set[str]) -> str:
    """The line a failure is recorded with, with no secret the source opened in it."""
    return scrub(str(error), secrets) or type(error).__name__


class _HoldContext:
    """What a held kind reaches while it listens."""

    def __init__(
        self,
        *,
        storage: Storage,
        connections: dict[str, ConnectionRecord],
        services: EngineServices,
        opened: set[str],
    ) -> None:
        """Hold the storage and the connection snapshot this consumer was opened with."""
        self._storage = storage
        self._connections = connections
        self._services = services
        self._opened = opened

    @property
    def log(self) -> Logger:
        """Where the kind says what it is doing."""
        return _ProcessLog()

    @property
    def storage(self) -> Storage:
        """Storage, every scheme configured from the connection the instance names for it."""
        return self._storage

    def connection[C: BaseModel](self, ref: ConnectionRef, model: type[C]) -> C:
        """Resolve a connection by code, opened and validated against the kind's own model."""
        record = self._connections.get(ref)
        if record is None:
            known = ", ".join(sorted(self._connections)) or "none are configured"
            raise LookupError(RUN_UNKNOWN_CONNECTION.render(ref=repr(ref), available=known))
        return open_record(self._services.secrets, record, model, self._services.connection_models, opened=self._opened)


class _ProcessLog:
    """A held kind's log, written to the worker's own: no run exists yet to hold it."""

    def debug(self, message: str, **fields: JsonValue) -> None:
        """Record a debug-level entry."""
        _logger.debug(message, **fields)

    def info(self, message: str, **fields: JsonValue) -> None:
        """Record an info-level entry."""
        _logger.info(message, **fields)

    def warning(self, message: str, **fields: JsonValue) -> None:
        """Record a warning-level entry."""
        _logger.warning(message, **fields)

    def error(self, message: str, **fields: JsonValue) -> None:
        """Record an error-level entry."""
        _logger.error(message, **fields)
