"""Polled sources: a worker leases each due source, asks its kind what is new, and makes a run of each input.

A tick claims every due source in one transaction, writing a lease so that two workers never
poll one source at once, and commits before polling: a poll does I/O, and no row lock is held
across it. Each source's outcome is then settled in a transaction of its own under the
pipeline's lock, the one run creation takes: the inputs become runs in the order the kind gave
them, the cursor is stored, and the next poll is due one cadence later. A poll that raises
leaves the cursor where it was and backs off.

A source's config is resolved before each poll with ``${artifacts}`` in scope and nothing else:
there is no run yet, so a reference to one fails the poll.
"""

import time
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import UUID

import httpx2
import sqlalchemy as sa
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import InputOutcome, TriggerKind
from dirigent_common import JsonMap
from dirigent_core import telemetry
from dirigent_core.database import session_scope
from dirigent_core.engine.context import ConnectionRecord, build_http_client, load_connections
from dirigent_core.engine.references import ReferenceScope, resolve
from dirigent_core.engine.runs import Attribution, Entry, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.errors import DomainError
from dirigent_core.logging import get_logger
from dirigent_core.messages import (
    RUN_UNKNOWN_CONNECTION,
    SENSOR_OUTSIDE_RUN,
    SOURCE_RUN_REFUSED,
    SOURCE_RUN_SKIPPED,
    UNKNOWN_CONNECTION_KIND,
)
from dirigent_core.models import Pipeline, PipelineVersion, Source, SourceInput, utcnow
from dirigent_core.sources.rows import in_flight, max_in_flight, polled
from dirigent_plugin import BlockFailure, Capture, ConnectionRef, ErrorClass, Logger, Runs, StepContext, Storage
from dirigent_plugin.sources import Polled, PolledSource

#: How many doublings the backoff takes before the cap is all that is left of it.
MAX_BACKOFF_DOUBLINGS: Final = 30

_logger = get_logger("sources.polling")


class Claimed(BaseModel):
    """One source a worker holds the lease on, and how many inputs it may hand over this poll."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    pipeline_id: UUID
    room: int


class PollOutcome(BaseModel):
    """What one poll of one source came to."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    runs: list[UUID]
    error: str | None = None


def backoff_for(failures: int, services: EngineServices) -> timedelta:
    """How long a polled source waits after this many polls in a row failed."""
    settings = services.settings
    doubled = settings.source_backoff * float(2 ** min(max(failures - 1, 0), MAX_BACKOFF_DOUBLINGS))
    return min(doubled, settings.source_backoff_max)


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    *,
    owner: str,
    now: datetime | None = None,
) -> list[PollOutcome]:
    """Poll every polled source that is due and not held by another worker."""
    moment = now or utcnow()
    async with session_scope(sessions) as session:
        claimed = await claim_due(session, services, owner=owner, now=moment)
    outcomes: list[PollOutcome] = []
    for one in claimed:
        outcomes.append(await poll_one(sessions, services, one, owner=owner))
    return outcomes


async def claim_due(session: AsyncSession, services: EngineServices, *, owner: str, now: datetime) -> list[Claimed]:
    """Take the lease on each due polled source, and work out how many inputs each may hand over."""
    kinds = services.sources
    names = [name for name, kind in kinds.items() if isinstance(kind, PolledSource)]
    if not names:
        return []
    statement = (
        sa.select(Source)
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
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(of=Source, skip_locked=True)
    rows = list((await session.execute(statement)).scalars())
    unsettled = await in_flight(session, [row.id for row in rows])
    lease = services.settings.source_poll_lease
    claimed: list[Claimed] = []
    for row in rows:
        bound = max_in_flight(kinds, row)
        room = services.settings.source_poll_batch
        if bound is not None:
            room = min(room, bound - unsettled.get(row.id, 0))
        if room <= 0:
            found = polled(kinds, row)
            row.next_poll_at = now + (found[0].poll_every(found[1]) if found else lease)
            continue
        row.lease_owner = owner
        row.lease_expires_at = now + lease
        claimed.append(Claimed(source_id=row.id, pipeline_id=row.pipeline_id, room=room))
    return claimed


async def poll_one(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, claimed: Claimed, *, owner: str
) -> PollOutcome:
    """Poll one leased source outside any transaction, then settle what it found."""
    async with sessions() as session:
        row = await session.get(Source, claimed.source_id)
        found = polled(services.sources, row) if row is not None else None
        storage = await services.bound_storage(session)
        connections = await load_connections(session)
        cursor = row.cursor if row is not None else None
    if row is None or found is None:
        return PollOutcome(source_id=claimed.source_id, runs=[])
    kind = found[0]
    started = time.monotonic()
    try:
        config = kind.config_model.model_validate(
            resolve(cast("JsonValue", row.config), ReferenceScope(artifacts=services.storage.artifact_root))
        )
        ctx = _PollContext(storage=storage, services=services, step=row.code, connections=connections)
        answer = await kind.poll(config, cursor, ctx, claimed.room)
    except Exception as error:  # a kind's failure is the source's, recorded and backed off
        return await _failed(sessions, services, claimed, owner=owner, error=str(error) or type(error).__name__)
    return await _settle(sessions, services, claimed, kind, answer, owner=owner, started=started)


async def _settle(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    claimed: Claimed,
    kind: PolledSource[Any, Any],
    answer: Polled[Any],
    *,
    owner: str,
    started: float,
) -> PollOutcome:
    """Make a run of every input, store the cursor, and due the next poll, all in one transaction.

    An input no run can be made of fails the whole poll: nothing is committed, the cursor stays
    where it was, and the next poll offers the same inputs again after a backoff.
    """
    moment = utcnow()
    runs: list[UUID] = []
    try:
        async with session_scope(sessions) as session:
            await lock_pipeline(session, claimed.pipeline_id)
            row = await session.get(Source, claimed.source_id, populate_existing=True)
            pipeline = await session.get(Pipeline, claimed.pipeline_id)
            if row is None or pipeline is None or row.lease_owner != owner:
                return PollOutcome(source_id=claimed.source_id, runs=[])
            took = round((time.monotonic() - started) * 1000)
            for output in answer.inputs[: claimed.room]:
                runs.append(
                    await enter_input(
                        session,
                        services,
                        row,
                        pipeline,
                        output.model_dump(mode="json"),
                        via="poll",
                        label=kind.label_of(output),
                        duration_ms=took,
                    )
                )
            row.cursor = answer.cursor
            row.polled_at = moment
            row.failures = 0
            row.last_error = None
            cadence = kind.poll_every(kind.config_model.model_validate(row.config))
            row.next_poll_at = moment + (answer.next_poll_in if answer.next_poll_in is not None else cadence)
            row.lease_owner = None
            row.lease_expires_at = None
    except InputRefused as refused:
        return await _failed(sessions, services, claimed, owner=owner, error=str(refused))
    if runs:
        _logger.info("source polled", source=str(claimed.source_id), runs=len(runs))
    return PollOutcome(source_id=claimed.source_id, runs=runs)


class InputRefused(Exception):
    """No run could be made of an input a worker took, which fails the whole batch it came in."""


async def enter_input(
    session: AsyncSession,
    services: EngineServices,
    row: Source,
    pipeline: Pipeline,
    output: JsonMap,
    *,
    via: Literal["poll", "hold"],
    label: str | None,
    duration_ms: int,
) -> UUID:
    """Create the run one input a worker took enters, and journal it, or raise when none can be made."""
    version = await _current_version(session, pipeline)
    if version is None:
        raise InputRefused(SOURCE_RUN_REFUSED.render(detail="the pipeline has no version"))
    entry = Entry(step=row.code, output=output, via=via, note=f"{via} {label}" if label else None)
    try:
        async with session.begin_nested():
            run = await create_run(
                session,
                services,
                version,
                attribution=Attribution(kind=TriggerKind.SOURCE, id=row.id, label=f"source {row.code}"),
                entry=entry,
            )
    except DomainError as error:
        raise InputRefused(SOURCE_RUN_REFUSED.render(detail=str(error))) from error
    if run is None:
        raise InputRefused(SOURCE_RUN_SKIPPED.render(pipeline=repr(pipeline.code)))
    moment = utcnow()
    session.add(
        SourceInput(
            source_id=row.id,
            run_id=run.id,
            created_at=moment,
            outcome=InputOutcome.ACCEPTED,
            label=label,
            duration_ms=duration_ms,
        )
    )
    row.accepted += 1
    row.last_input_at = moment
    telemetry.record_input(InputOutcome.ACCEPTED.value, None)
    return run.id


async def _failed(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    claimed: Claimed,
    *,
    owner: str,
    error: str,
) -> PollOutcome:
    """Record a failed poll on its row, keep the cursor, and back off."""
    async with session_scope(sessions) as session:
        row = await session.get(Source, claimed.source_id, populate_existing=True)
        if row is None or row.lease_owner != owner:
            return PollOutcome(source_id=claimed.source_id, runs=[], error=error)
        row.failures += 1
        row.last_error = error
        row.next_poll_at = utcnow() + backoff_for(row.failures, services)
        row.lease_owner = None
        row.lease_expires_at = None
        failures = row.failures
    _logger.warning("source poll failed", source=str(claimed.source_id), failures=failures, error=error)
    return PollOutcome(source_id=claimed.source_id, runs=[], error=error)


async def _current_version(session: AsyncSession, pipeline: Pipeline) -> PipelineVersion | None:
    """Read the version a pipeline's new runs are made of."""
    found = await session.execute(
        sa.select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version
        )
    )
    return found.scalar_one_or_none()


class _PollContext:
    """What a polled kind reaches while it polls, and what a sensor it pokes is handed."""

    def __init__(
        self, *, storage: Storage, services: EngineServices, step: str, connections: dict[str, ConnectionRecord]
    ) -> None:
        """Hold the storage bound for this poll and the connection snapshot it was taken with."""
        self._storage = storage
        self._services = services
        self._step = step
        self._connections = connections

    def sensor_context(self, *, block: str, cursor: JsonMap | None, started_at: datetime) -> StepContext:
        """A context for one poke outside any run, whose run id is a property that refuses."""
        outside = _OutsideRun(
            block=block,
            step=self._step,
            cursor=cursor,
            started_at=started_at,
            storage=self._storage,
            services=self._services,
            connections=self._connections,
        )
        return cast("StepContext", outside)

    @property
    def log(self) -> Logger:
        """Where the kind says what it found."""
        return _ProcessLog()

    @property
    def storage(self) -> Storage:
        """Storage, every scheme configured from the connection the instance names for it."""
        return self._storage


class _OutsideRun:
    """A sensor's context outside any run: connections, storage and its cursor, and nothing of a run."""

    run_item_id: UUID | None = None
    attempt: int = 1

    def __init__(
        self,
        *,
        block: str,
        step: str,
        cursor: JsonMap | None,
        started_at: datetime,
        storage: Storage,
        services: EngineServices,
        connections: dict[str, ConnectionRecord],
    ) -> None:
        """Bind the context to one poke."""
        self._block = block
        self.step = step
        self.cursor = cursor
        self.started_at = started_at
        self.inline_capture = services.settings.inline_capture
        self.params: Mapping[str, JsonValue] = {}
        self.log: Logger = _ProcessLog()
        self._storage = storage
        self._services = services
        self._connections = connections

    @property
    def run_id(self) -> UUID:
        """Refuse: a poke outside a run has no run."""
        raise self._refused("the run id")

    @property
    def storage(self) -> Storage:
        """Storage, every scheme configured from the connection the instance names for it."""
        return self._storage

    @property
    def scratch(self) -> str:
        """Refuse: a poke outside a run has no scratch."""
        raise self._refused("the run's scratch")

    @property
    def work(self) -> Path:
        """Refuse: a poke outside a run has no work directory."""
        raise self._refused("the run's work directory")

    @property
    def runs(self) -> Runs:
        """Refuse: a poke outside a run has no run to attribute others to."""
        raise self._refused("the runs handle")

    def capture(self, name: str, *, content_type: str = "text/plain") -> AbstractAsyncContextManager[Capture]:
        """Refuse: a capture is written under the run's scratch."""
        raise self._refused("a capture")

    def schema(self, code: str) -> JsonMap:
        """Refuse: a run's schemas are pinned when it is created."""
        raise self._refused("a schema")

    def format_checker(self) -> FormatChecker:
        """The instance's assembled checker: base formats plus every contributed one."""
        return self._services.format_checker

    def connection[C: BaseModel](self, ref: ConnectionRef, model: type[C]) -> C:
        """Resolve a connection by code, opened and validated against the sensor's own model."""
        record = self._record(ref)
        return self._services.secrets.decrypt_config(model, record.config, record.envelope, key_id=record.key_id)

    def storage_connection[C: BaseModel](self, scheme: str, model: type[C]) -> C | None:
        """Resolve the connection this instance configures a storage scheme from, or None."""
        ref = self._services.settings.storage_connections.get(scheme)
        return None if ref is None else self.connection(ref, model)

    def http(self, ref: ConnectionRef) -> httpx2.AsyncClient:
        """Build an HTTP client for a connection read by code, already carrying its settings."""
        record = self._record(ref)
        model = self._services.connection_models.get(record.kind)
        if model is None:
            raise LookupError(UNKNOWN_CONNECTION_KIND.render(ref=repr(ref), kind=repr(record.kind)))
        return build_http_client(self.connection(ref, model))

    def _record(self, ref: ConnectionRef) -> ConnectionRecord:
        """The connection a sensor names, or a refusal naming those there are."""
        record = self._connections.get(ref)
        if record is None:
            known = ", ".join(sorted(self._connections)) or "none are configured"
            raise LookupError(RUN_UNKNOWN_CONNECTION.render(ref=repr(ref), available=known))
        return record

    def _refused(self, what: str) -> BlockFailure:
        """The failure a sensor reading part of a run is answered with."""
        return BlockFailure(SENSOR_OUTSIDE_RUN, error_class=ErrorClass.REJECTED, block=repr(self._block), what=what)


class _ProcessLog:
    """A polled kind's log, written to the worker's own: no run exists yet to hold it."""

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
