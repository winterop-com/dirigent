"""``dg run --local``: run a document to completion with no server and no dependencies."""

import asyncio
import contextlib
import shutil
import tempfile
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID

import sqlalchemy as sa
import yaml
from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, LogLevel, RunStatus, TriggerKind
from dirigent_common import JsonMap
from dirigent_core import migrations
from dirigent_core.config import Settings, get_settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.documents import DocumentError, load_pipeline_text, safe_load
from dirigent_core.engine import Attribution, ParameterError, create_run
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.runs import RunCreationError, RunWindow
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import in_execution_order
from dirigent_core.models import ArtifactRef, Connection, LogEntry, Run, RunItem, StepAttempt
from dirigent_core.pipelines import apply_document
from dirigent_core.plugins import load_plugin_host
from dirigent_core.schemas import SchemaRefused, resolve_identity, store_schema
from dirigent_core.storage import scratch_prefix
from dirigent_core.worker import Worker

#: How long the driver waits between polls when the run keeps moving, and how far that
#: wait widens while nothing does.
POLL_SECONDS: Final = 0.1
POLL_WIDEN: Final = 1.5
POLL_CEILING: Final = 1.0

#: How many log entries one read takes, so a step that logged a million lines is streamed
#: rather than held in memory.
LOCAL_LOG_PAGE: Final = 500

DEFAULT_DEADLINE_SECONDS: Final = 600.0

TERMINAL: Final = (
    RunStatus.SUCCEEDED,
    RunStatus.COMPLETED_WITH_ERRORS,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
)


class LocalError(Exception):
    """A local run could not be set up; the message says what was wrong with the input."""


#: How long a fan-out element's key may be before the stream labels it by position instead.
ITEM_LABEL_MAX: Final = 24

#: Attempt states a run has finished with, which is what the end-of-run summary reads.
SETTLED: Final = (
    AttemptStatus.SUCCEEDED,
    AttemptStatus.FAILED,
    AttemptStatus.SKIPPED,
    AttemptStatus.CANCELLED,
)


class ConnectionSpec(BaseModel):
    """One connection a local run is given."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str | None = None
    kind: str = "http"
    config: JsonMap = Field(default_factory=dict)


class SchemaSpec(BaseModel):
    """One named schema a local run is given, so a document may reference it by code."""

    model_config = ConfigDict(frozen=True)

    body: JsonMap
    code: str | None = None
    """The code to store under; a carried schema's is its map key. A ``--schema`` file leaves
    this unset and takes its code from the body's ``$id`` or the filename."""

    fallback_code: str | None = None
    """The filename stem, used as the code when the schema names none through ``$id``."""


class LogLine(BaseModel):
    """One product-telemetry entry, streamed to the terminal."""

    model_config = ConfigDict(frozen=True)

    level: str
    step: str | None
    message: str
    at: datetime
    fields: JsonMap = Field(default_factory=dict)
    item: str | None = None
    """Which element of a fan-out wrote this, when one did."""


class LocalStarted(BaseModel):
    """The run exists; the first thing a local run yields."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    pipeline: str
    scratch: str
    """The prefix every URI this run writes sits under."""

    root: Path
    """The directory holding this run's database and artifacts."""

    steps: list[str] = Field(default_factory=list[str])
    """The step names in the order the document wrote them, which is how they are tracked."""


class Spill(BaseModel):
    """Where an output was written, when it was too large to inline on the attempt."""

    model_config = ConfigDict(frozen=True)

    uri: str
    size_bytes: int | None = None


class StepTransition(BaseModel):
    """One step changing state."""

    model_config = ConfigDict(frozen=True)

    step: str
    block: str
    attempt: int
    status: AttemptStatus
    at: datetime
    item: str | None = None
    """Which element of a fan-out moved, when the step fans out."""

    settled: bool = False
    """Whether this is the status the attempt finished on rather than one on the way."""

    duration_ms: int | None = None
    output: JsonMap | None = None
    spill: Spill | None = None


class StepFailure(BaseModel):
    """Everything needed to diagnose one failed step.

    A local run deletes its database when it ends, so anything not read out here is lost.
    """

    model_config = ConfigDict(frozen=True)

    step: str
    block: str
    attempt: int
    error_class: str | None = None
    error: str | None = None
    logs: list[str] = Field(default_factory=list[str])
    input: JsonMap | None = None
    """What the attempt was given, which is half of why it went wrong."""


class StepResult(BaseModel):
    """What one settled attempt amounted to, so a local run can be read after it ends."""

    model_config = ConfigDict(frozen=True)

    step: str
    block: str
    status: AttemptStatus
    depends_on: list[str] = Field(default_factory=list[str])
    """The steps this one waited for, which is why it ran when it did."""

    warnings: int = 0
    """How many warnings or errors this attempt logged, whatever it settled as."""

    item: str | None = None
    duration_ms: int | None = None
    output: JsonMap | None = None
    spill: Spill | None = None


class LocalOutcome(BaseModel):
    """What a local run amounted to."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    pipeline: str
    status: RunStatus
    error: str | None = None
    failures: list[StepFailure] = Field(default_factory=list[StepFailure])
    results: list[StepResult] = Field(default_factory=list[StepResult])
    """Every settled attempt, in the order it settled; a local run has nowhere else to read."""

    kept_at: Path | None = None
    """Where the instance was left, when --keep or --root asked for it to stay."""

    scratch: str | None = None
    """The prefix this run's files sit under, reported when the instance was kept."""

    @property
    def exit_code(self) -> int:
        """Map the outcome onto a process exit code."""
        return 0 if self.status is RunStatus.SUCCEEDED else 1

    @property
    def tolerated(self) -> bool:
        """Report whether this is the "finished, but something was tolerated" outcome."""
        return self.status is RunStatus.COMPLETED_WITH_ERRORS


def connections_for(definitions: Sequence[PipelineDefinition], given: Sequence[ConnectionSpec]) -> list[ConnectionSpec]:
    """Take the documents' own connections, and let one given by code replace it.

    A published document carries what it needs to run; ``--connections`` is how somebody
    points the same document at their own instance instead. Every document the run applies
    is read, supporting ones included, and the first to carry a code keeps it.
    """
    embedded: dict[str, ConnectionSpec] = {}
    for definition in definitions:
        for code, carried in definition.connections.items():
            embedded.setdefault(code, ConnectionSpec(code=code, kind=carried.kind, config=carried.config))
    replaced = {spec.code for spec in given}
    return [spec for code, spec in embedded.items() if code not in replaced] + list(given)


def schemas_for(definitions: Sequence[PipelineDefinition], given: Sequence[SchemaSpec]) -> list[SchemaSpec]:
    """Take the documents' own schemas, and let one given by code replace it.

    A published document carries the shapes it references; ``--schema`` is how somebody hands
    the same document a schema of their own instead. Every document the run applies is read,
    supporting ones included, so a child started through ``pipeline.run`` resolves the codes
    it carries; the first document to carry a code keeps it.
    """
    replaced = {code for spec in given if (code := _resolved_code(spec)) is not None}
    embedded: dict[str, SchemaSpec] = {}
    for definition in definitions:
        for code, body in definition.schemas.items():
            if code not in replaced:
                embedded.setdefault(code, SchemaSpec(body=body, code=code))
    return list(embedded.values()) + list(given)


def _resolved_code(spec: SchemaSpec) -> str | None:
    """Work out the code a schema spec will store under, or nothing when it names none."""
    try:
        code, _, _ = resolve_identity(
            spec.body, code=spec.code, name=None, description=None, fallback_code=spec.fallback_code
        )
    except SchemaRefused:
        return None
    return code


def load_schema_specs(path: Path) -> SchemaSpec:
    """Read one JSON Schema file into a spec, taking its fallback code from the filename."""
    try:
        loaded = safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise LocalError(f"{path} could not be read: {error}") from error
    if not isinstance(loaded, dict):
        raise LocalError(f"{path} is not a JSON Schema: a schema is an object")
    return SchemaSpec(body=cast("JsonMap", loaded), fallback_code=path.stem)


def load_connection_specs(path: Path) -> list[ConnectionSpec]:
    """Read a connections file: a mapping of codes to kinds and configs, or a list of them."""
    try:
        loaded = safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise LocalError(f"{path} could not be read: {error}") from error
    if isinstance(loaded, dict) and "connections" in loaded:
        loaded = cast("dict[str, Any]", loaded)["connections"]
    if isinstance(loaded, dict):
        return [
            ConnectionSpec(code=code, **cast("dict[str, Any]", body))
            for code, body in cast("dict[str, Any]", loaded).items()
        ]
    if isinstance(loaded, list):
        return [ConnectionSpec(**cast("dict[str, Any]", body)) for body in cast("list[object]", loaded)]
    raise LocalError(f"{path} should hold a connections mapping or a list of connections")


def prepare_root(root: Path) -> Path:
    """Make the directory a local run is being held in, refusing a path that is not one."""
    if root.exists() and not root.is_dir():
        raise LocalError(f"{root} is not a directory, so a local run cannot be held there")
    root.mkdir(parents=True, exist_ok=True)
    return root


def local_settings(root: Path, *, inherited: Settings | None = None) -> Settings:
    """Build the settings a local run uses: a throwaway database, the host's own policy.

    The unsafe-block allowlist must stay inherited: a local run may execute no block the
    host has not allowlisted.
    """
    base = inherited or get_settings()
    return Settings(
        database_url=f"sqlite+aiosqlite:///{root / 'dirigent.db'}",
        artifact_root=f"file://{root / 'artifacts'}",
        work_root=str(root / "work"),
        secret_key=SecretStr(Fernet.generate_key().decode()),
        enabled_unsafe_blocks=list(base.enabled_unsafe_blocks),
        storage_connections=dict(base.storage_connections),
        inline_artifact_max=base.inline_artifact_max,
        log_level=base.log_level,
        log_format=base.log_format,
        claim_idle=timedelta(milliseconds=50),
        heartbeat=timedelta(seconds=5),
        sweep_interval=timedelta(seconds=5),
        worker_concurrency=base.worker_concurrency,
    )


async def _seed_connections(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    specs: Sequence[ConnectionSpec],
) -> None:
    """Store the connections a local run was given, sealed with its ephemeral key."""
    for spec in specs:
        contributed = services.host.connection_kinds.get(spec.kind)
        if contributed is None:
            known = ", ".join(sorted(services.host.connection_kinds)) or "none are installed"
            raise LocalError(f"no connection kind {spec.kind!r} is installed ({known})")
        validated = contributed.config_model.model_validate(spec.config)
        public, envelope, key_id = services.secrets.encrypt_config(contributed.config_model, validated)
        async with session_scope(sessions) as session:
            session.add(
                Connection(
                    code=spec.code,
                    name=spec.name,
                    kind=spec.kind,
                    config=public,
                    secret_envelope=envelope,
                    secret_key_id=key_id,
                )
            )


async def _seed_schemas(
    sessions: async_sessionmaker[AsyncSession],
    specs: Sequence[SchemaSpec],
) -> None:
    """Store the named schemas a local run was given, so a document may reference them by code."""
    for spec in specs:
        try:
            async with session_scope(sessions) as session:
                await store_schema(session, spec.body, code=spec.code, fallback_code=spec.fallback_code)
        except SchemaRefused as error:
            raise LocalError(str(error)) from error


async def _new_logs(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, after: int, labels: Mapping[UUID, str]
) -> tuple[list[LogLine], int, bool]:
    """Read one page of the log entries written since the last poll.

    The third value says the page came back full, which is how the caller knows to read
    again before it sleeps.
    """
    async with session_scope(sessions) as session:
        rows = await session.execute(
            sa.select(LogEntry)
            .where(LogEntry.run_id == run_id, LogEntry.id > after)
            .order_by(LogEntry.id)
            .limit(LOCAL_LOG_PAGE + 1)
        )
        entries = list(rows.scalars())
    lines = [
        LogLine(
            level=entry.level.value,
            step=entry.step_name,
            message=entry.message,
            at=entry.created_at,
            fields=dict(entry.fields or {}),
            item=labels.get(entry.step_attempt_id) if entry.step_attempt_id else None,
        )
        for entry in entries
    ]
    return lines, entries[-1].id if entries else after, len(entries) > LOCAL_LOG_PAGE


async def _warnings(session: AsyncSession, run_id: UUID) -> dict[UUID, int]:
    """Count the warnings and errors each attempt logged, which a succeeded step can still have."""
    rows = await session.execute(
        sa.select(LogEntry.step_attempt_id, sa.func.count())
        .where(LogEntry.run_id == run_id, LogEntry.level.in_((LogLevel.WARNING, LogLevel.ERROR)))
        .group_by(LogEntry.step_attempt_id)
    )
    return {attempt_id: count for attempt_id, count in rows.all() if attempt_id is not None}


async def _item_indexes(session: AsyncSession, run_id: UUID) -> dict[UUID, int]:
    """Map each attempt of a fan-out step to the position of the element it was created for."""
    rows = await session.execute(
        sa.select(StepAttempt.id, RunItem.item_index)
        .join(RunItem, RunItem.id == StepAttempt.run_item_id)
        .where(StepAttempt.run_id == run_id)
    )
    return {attempt_id: index for attempt_id, index in rows.all()}


async def _item_labels(session: AsyncSession, run_id: UUID) -> dict[UUID, str]:
    """Map each attempt of a fan-out step to the element it was created for."""
    rows = await session.execute(
        sa.select(StepAttempt.id, RunItem.item_index, RunItem.item_key)
        .join(RunItem, RunItem.id == StepAttempt.run_item_id)
        .where(StepAttempt.run_id == run_id)
    )
    return {attempt_id: item_label(index, key) for attempt_id, index, key in rows.all()}


def item_label(index: int, key: str) -> str:
    """Render one fan-out element the way the stream shows it: its key, or its position."""
    trimmed = key.strip()
    return trimmed if trimmed and len(trimmed) <= ITEM_LABEL_MAX else str(index)


FAILURE_LOG_LINES: Final = 20


async def _failures(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, order: Sequence[str] = ()
) -> list[StepFailure]:
    """Gather every failed attempt with its error and its own log lines."""
    async with session_scope(sessions) as session:
        rows = await session.execute(
            sa.select(StepAttempt, RunItem.item_index)
            .outerjoin(RunItem, RunItem.id == StepAttempt.run_item_id)
            .where(StepAttempt.run_id == run_id, StepAttempt.status == AttemptStatus.FAILED)
        )
        found = rows.all()
        indexes = {attempt.id: index for attempt, index in found if index is not None}
        attempts = in_execution_order([attempt for attempt, _ in found], indexes, order)
        failures: list[StepFailure] = []
        for attempt in attempts:
            logs = await session.execute(
                sa.select(LogEntry)
                .where(LogEntry.step_attempt_id == attempt.id)
                .order_by(LogEntry.id.desc())
                .limit(FAILURE_LOG_LINES)
            )
            failures.append(
                StepFailure(
                    step=attempt.step_name,
                    block=attempt.block_id,
                    attempt=attempt.attempt,
                    error_class=attempt.error_class,
                    error=attempt.error,
                    logs=[f"{entry.level.value}: {entry.message}" for entry in reversed(list(logs.scalars()))],
                    input=dict(attempt.input) if attempt.input else None,
                )
            )
    return failures


async def _spills(session: AsyncSession, run_id: UUID) -> dict[UUID, Spill]:
    """Map each attempt whose output was written to storage to where it went.

    An artifact with an inline value is not a spill: the attempt row carries it already.
    """
    rows = await session.execute(
        sa.select(ArtifactRef.step_attempt_id, ArtifactRef.uri, ArtifactRef.size_bytes).where(
            ArtifactRef.run_id == run_id, ArtifactRef.uri.is_not(None)
        )
    )
    return {
        attempt_id: Spill(uri=uri, size_bytes=size)
        for attempt_id, uri, size in rows.all()
        if attempt_id is not None and uri is not None
    }


async def _results(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    edges: Mapping[str, Sequence[str]],
    order: Sequence[str] = (),
) -> list[StepResult]:
    """Gather every settled attempt with its output, which a deleted database cannot be asked for."""
    async with session_scope(sessions) as session:
        labels = await _item_labels(session, run_id)
        spills = await _spills(session, run_id)
        warned = await _warnings(session, run_id)
        rows = await session.execute(
            sa.select(StepAttempt, RunItem.item_index)
            .outerjoin(RunItem, RunItem.id == StepAttempt.run_item_id)
            .where(StepAttempt.run_id == run_id, StepAttempt.status.in_(SETTLED))
        )
        found = rows.all()
        indexes = {attempt.id: index for attempt, index in found if index is not None}
        return [
            StepResult(
                step=attempt.step_name,
                block=attempt.block_id,
                status=attempt.status,
                depends_on=list(edges.get(attempt.step_name, ())),
                warnings=warned.get(attempt.id, 0),
                item=labels.get(attempt.id),
                duration_ms=_duration_ms(attempt),
                output=dict(attempt.output) if attempt.output else None,
                spill=spills.get(attempt.id),
            )
            for attempt in in_execution_order([attempt for attempt, _ in found], indexes, order)
        ]


def _duration_ms(attempt: StepAttempt) -> int | None:
    """Report how long one attempt took, or nothing when it never started or never finished."""
    if attempt.started_at is None or attempt.finished_at is None:
        return None
    return round((attempt.finished_at - attempt.started_at).total_seconds() * 1000)


class _Items:
    """A run's fan-out labels and positions, re-read only when a new attempt turns up."""

    def __init__(self) -> None:
        """Start knowing no attempt at all."""
        self.known: set[UUID] = set()
        self.labels: dict[UUID, str] = {}
        self.indexes: dict[UUID, int] = {}

    async def see(self, session: AsyncSession, run_id: UUID, attempts: Sequence[StepAttempt]) -> None:
        """Take the attempts one poll read, and re-read the maps if any of them is new."""
        ids = {attempt.id for attempt in attempts}
        if ids <= self.known:
            return
        self.known = ids
        self.labels = await _item_labels(session, run_id)
        self.indexes = await _item_indexes(session, run_id)


class Tick(BaseModel):
    """What one poll of a run's own tables saw: what moved, and where the run stands."""

    transitions: list[StepTransition]
    status: RunStatus | None
    error: str | None


async def _transitions(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    seen: dict[UUID, AttemptStatus],
    items: _Items,
    order: Sequence[str] = (),
) -> Tick:
    """Report every attempt whose status changed since the last poll, and the run's own status."""
    async with session_scope(sessions) as session:
        run = await session.get(Run, run_id)
        status = run.status if run else None
        error = run.error if run else None
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run_id))
        found = list(rows.scalars())
        await items.see(session, run_id, found)
        labels, indexes = items.labels, items.indexes
        attempts = in_execution_order(found, indexes, order)
        spills = await _spills(session, run_id)
    changed: list[StepTransition] = []
    for attempt in attempts:
        # Keyed on the attempt itself. Every element of a fan-out is attempt 1 of the same
        # step, so a key built from the step name needs the item to tell them apart -- and an
        # item whose label is not readable yet leaves two of them sharing one key, which
        # announces one and swallows the rest. The id is the identity of the thing that moved.
        if seen.get(attempt.id) is attempt.status:
            continue
        seen[attempt.id] = attempt.status
        if attempt.status is AttemptStatus.PENDING:
            continue
        settled = attempt.status in SETTLED
        changed.append(
            StepTransition(
                step=attempt.step_name,
                block=attempt.block_id,
                attempt=attempt.attempt,
                status=attempt.status,
                at=attempt.finished_at or attempt.started_at or attempt.available_at or attempt.updated_at,
                item=labels.get(attempt.id),
                settled=settled,
                duration_ms=_duration_ms(attempt) if settled else None,
                output=dict(attempt.output) if settled and attempt.output else None,
                spill=spills.get(attempt.id) if settled else None,
            )
        )
    # Stable, so steps that became claimable in the same transaction -- which is every root
    # of a run -- keep the order in_execution_order put them in, which is the written one.
    return Tick(transitions=sorted(changed, key=lambda item: item.at), status=status, error=error)


async def run_document(
    text: str,
    *,
    params: JsonMap | None = None,
    window: RunWindow | None = None,
    log_levels: JsonMap | None = None,
    connections: Sequence[ConnectionSpec] = (),
    schemas: Sequence[SchemaSpec] = (),
    also: Sequence[str] = (),
    inherited: Settings | None = None,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    keep: bool = False,
    root: Path | None = None,
) -> AsyncIterator[LocalStarted | LogLine | StepTransition | LocalOutcome]:
    """Apply and run a document in a throwaway instance, yielding logs then the outcome.

    The last item yielded is always the outcome. ``also`` holds documents to apply first
    and not run, for a pipeline that composes another one. ``root`` names a directory to hold
    the instance in and keep, so a later run reads what this one wrote.
    """
    held = prepare_root(root) if root is not None else Path(tempfile.mkdtemp(prefix="dirigent-local-"))
    leave = keep or root is not None
    definition = load_pipeline_text(text)
    # The instance is a directory rather than a context manager because ``keep`` leaves it
    # behind: a run whose database is deleted cannot be asked what it produced.
    try:
        settings = local_settings(held, inherited=inherited)
        await migrations.upgrade_async(settings=settings)
        services = EngineServices.build(settings, load_plugin_host())
        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            supporting = [_parse_supporting(extra) for extra in also]
            carried = [definition, *supporting]
            await _seed_connections(sessions, services, connections_for(carried, connections))
            await _seed_schemas(sessions, schemas_for(carried, schemas))
            for extra_definition in supporting:
                async with session_scope(sessions) as session:
                    await _apply_supporting(session, services, extra_definition)
            async with session_scope(sessions) as session:
                applied = await apply_document(session, services, definition)
                if not applied.plan.ok:
                    raise LocalError(
                        "the document does not validate against the installed catalog:\n"
                        + "\n".join(f"  {issue}" for issue in applied.plan.issues)
                    )
                version = await _current_version(session, definition.code)
                try:
                    run = await create_run(
                        session,
                        services,
                        version,
                        params=params or {},
                        attribution=Attribution(kind=TriggerKind.USER, label="dg run --local"),
                        window=window,
                        log_levels=log_levels,
                    )
                except (RunCreationError, ParameterError) as error:
                    raise LocalError(str(error)) from error
            if run is None:  # pragma: no cover - a throwaway instance has no other runs
                raise LocalError("the run was skipped by the pipeline's concurrency policy")
            run_id = run.id
            scratch = scratch_prefix(settings.artifact_root, run_id)
            yield LocalStarted(
                run_id=run_id,
                pipeline=definition.code,
                scratch=scratch,
                root=held,
                steps=list(definition.steps),
            )
            kept = {"kept_at": held, "scratch": scratch}
            edges = {name: list(step.depends_on) for name, step in definition.steps.items()}
            async for item in _drive(
                sessions, services, run_id, definition.code, edges, list(definition.steps), deadline_seconds
            ):
                yield item.model_copy(update=kept) if leave and isinstance(item, LocalOutcome) else item
        finally:
            await engine.dispose()
    finally:
        if not leave:
            shutil.rmtree(held, ignore_errors=True)


def _parse_supporting(text: str) -> PipelineDefinition:
    """Read one document a run depends on but does not run."""
    try:
        return load_pipeline_text(text)
    except DocumentError as error:
        raise LocalError(f"a supporting document does not parse: {error}") from error


async def _apply_supporting(session: AsyncSession, services: EngineServices, supporting: PipelineDefinition) -> None:
    """Apply one document a run depends on, without running it."""
    applied = await apply_document(session, services, supporting)
    if not applied.plan.ok:
        raise LocalError(
            f"the supporting document {supporting.code!r} does not validate:\n"
            + "\n".join(f"  {issue}" for issue in applied.plan.issues)
        )


async def _current_version(session: AsyncSession, code: str) -> Any:
    """Read the version the apply just wrote."""
    from dirigent_core.pipelines import get_version, require_pipeline

    return await get_version(session, await require_pipeline(session, code))


def _merged(transitions: list[StepTransition], lines: list[LogLine]) -> list[StepTransition | LogLine]:
    """Interleave transitions and log lines in the order they actually happened.

    The engine commits an attempt's log entries while it runs and the rest with its outcome,
    so a poll can hold both and only the timestamps order the two lists against each other.
    Each list keeps its own order rather than being re-sorted: steps that have not started
    have only the microseconds of their row's creation to sort on, which is not an order
    anybody wrote or watched.
    """
    merged: list[StepTransition | LogLine] = []
    left, right = list(transitions), list(lines)
    while left and right:
        merged.append(left.pop(0) if left[0].at <= right[0].at else right.pop(0))
    merged.extend(left)
    merged.extend(right)
    return merged


async def _drive(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    run_id: UUID,
    pipeline: str,
    edges: Mapping[str, Sequence[str]],
    order: Sequence[str],
    deadline_seconds: float,
) -> AsyncIterator[LogLine | StepTransition | LocalOutcome]:
    """Run an embedded worker until the run settles, streaming transitions and logs."""
    worker = Worker(sessions, services, name="local", sweeper=False)
    task = asyncio.create_task(worker.run())
    cursor = 0
    waited = 0.0
    interval = POLL_SECONDS
    seen: dict[UUID, AttemptStatus] = {}
    items = _Items()
    try:
        while waited < deadline_seconds:
            # The status is read before the log is: a run that had settled by then wrote its
            # last entry before it settled, so the pages below carry the whole of it.
            tick = await _transitions(sessions, run_id, seen, items, order)
            moved = bool(tick.transitions)
            transitions = tick.transitions
            while True:
                lines, cursor, more = await _new_logs(sessions, run_id, cursor, items.labels)
                moved = moved or bool(lines)
                for event in _merged(transitions, lines):
                    yield event
                transitions = []
                if not more:
                    break
            if tick.status in TERMINAL:
                yield LocalOutcome(
                    run_id=run_id,
                    pipeline=pipeline,
                    status=cast("RunStatus", tick.status),
                    error=tick.error,
                    failures=await _failures(sessions, run_id, order),
                    results=await _results(sessions, run_id, edges, order),
                )
                return
            interval = POLL_SECONDS if moved else min(interval * POLL_WIDEN, POLL_CEILING)
            await asyncio.sleep(interval)
            waited += interval
        yield LocalOutcome(
            run_id=run_id,
            pipeline=pipeline,
            status=RunStatus.FAILED,
            error=f"the run did not finish within {deadline_seconds:.0f}s",
            failures=await _failures(sessions, run_id, order),
            results=await _results(sessions, run_id, edges, order),
        )
    finally:
        worker.request_stop()
        with contextlib.suppress(asyncio.CancelledError):
            await task
