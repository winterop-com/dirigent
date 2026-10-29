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
from datetime import datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import InputOutcome, TriggerKind
from dirigent_common import JsonMap
from dirigent_core import telemetry
from dirigent_core.database import session_scope
from dirigent_core.engine.references import ReferenceScope, resolve
from dirigent_core.engine.runs import Attribution, Entry, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.errors import DomainError
from dirigent_core.logging import get_logger
from dirigent_core.messages import SOURCE_RUN_REFUSED, SOURCE_RUN_SKIPPED
from dirigent_core.models import Pipeline, PipelineVersion, Source, SourceInput, utcnow
from dirigent_core.sources.rows import in_flight, max_in_flight, polled
from dirigent_plugin import Logger, Storage
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
        cursor = row.cursor if row is not None else None
    if row is None or found is None:
        return PollOutcome(source_id=claimed.source_id, runs=[])
    kind = found[0]
    started = time.monotonic()
    try:
        config = kind.config_model.model_validate(
            resolve(cast("JsonValue", row.config), ReferenceScope(artifacts=services.storage.artifact_root))
        )
        answer = await kind.poll(config, cursor, _PollContext(storage=storage), claimed.room)
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
    """Make a run of each input, store the cursor, and due the next poll, in one transaction."""
    moment = utcnow()
    runs: list[UUID] = []
    async with session_scope(sessions) as session:
        await lock_pipeline(session, claimed.pipeline_id)
        row = await session.get(Source, claimed.source_id, populate_existing=True)
        pipeline = await session.get(Pipeline, claimed.pipeline_id)
        if row is None or pipeline is None or row.lease_owner != owner:
            return PollOutcome(source_id=claimed.source_id, runs=[])
        version = await _current_version(session, pipeline)
        took = round((time.monotonic() - started) * 1000)
        for output in answer.inputs[: claimed.room]:
            made = output.model_dump(mode="json")
            label = kind.label_of(output)
            run_id = await _enter(session, services, row, pipeline, version, made, label=label, duration_ms=took)
            if run_id is not None:
                runs.append(run_id)
        row.cursor = answer.cursor
        row.polled_at = moment
        row.failures = 0
        row.last_error = None
        row.next_poll_at = moment + kind.poll_every(kind.config_model.model_validate(row.config))
        row.lease_owner = None
        row.lease_expires_at = None
    if runs:
        _logger.info("source polled", source=str(claimed.source_id), runs=len(runs))
    return PollOutcome(source_id=claimed.source_id, runs=runs)


async def _enter(
    session: AsyncSession,
    services: EngineServices,
    row: Source,
    pipeline: Pipeline,
    version: PipelineVersion | None,
    output: JsonMap,
    *,
    label: str | None,
    duration_ms: int,
) -> UUID | None:
    """Create the run one input enters, and journal it as accepted or refused."""
    refusal: str | None = None
    code: str | None = None
    run = None
    if version is None:
        code, refusal = SOURCE_RUN_REFUSED.code, SOURCE_RUN_REFUSED.render(detail="the pipeline has no version")
    else:
        entry = Entry(step=row.code, output=output, via="poll", note=f"polled {label}" if label else "polled")
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
            code, refusal = SOURCE_RUN_REFUSED.code, SOURCE_RUN_REFUSED.render(detail=str(error))
        if run is None and refusal is None:
            code = SOURCE_RUN_SKIPPED.code
            refusal = SOURCE_RUN_SKIPPED.render(pipeline=repr(pipeline.code))
    outcome = InputOutcome.ACCEPTED if run is not None else InputOutcome.REFUSED
    moment = utcnow()
    session.add(
        SourceInput(
            source_id=row.id,
            run_id=run.id if run is not None else None,
            created_at=moment,
            outcome=outcome,
            code=code,
            reason=refusal,
            label=label,
            duration_ms=duration_ms,
        )
    )
    if run is not None:
        row.accepted += 1
    else:
        row.refused += 1
    row.last_input_at = moment
    telemetry.record_input(outcome.value, None)
    return run.id if run is not None else None


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
    """What a polled kind reaches while it polls."""

    def __init__(self, *, storage: Storage) -> None:
        """Hold the storage bound for this poll."""
        self._storage = storage

    @property
    def log(self) -> Logger:
        """Where the kind says what it found."""
        return _ProcessLog()

    @property
    def storage(self) -> Storage:
        """Storage, every scheme configured from the connection the instance names for it."""
        return self._storage


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
