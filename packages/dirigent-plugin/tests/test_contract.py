"""Tests for the dirigent block contract."""

import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx2
import pytest
from jsonschema import FormatChecker
from pluginkit import PluginManager
from pydantic import BaseModel, JsonValue, ValidationError

import dirigent_plugin
from dirigent_common import API_VERSION, SHELL_MEDIA_TYPE, JsonMap, base_format_checker
from dirigent_plugin import (
    ByteSink,
    Contribution,
    ErrorClass,
    Logger,
    NotYet,
    OperatorSpec,
    ProbeStatus,
    RemoteHandle,
    RunId,
    RunRefused,
    Runs,
    RunSnapshot,
    RunState,
    SensorSpec,
    ShellString,
    StartedRun,
    StatResult,
    StepContext,
    Storage,
    classify_default,
    contribute,
    markers,
    merge_contributions,
    shell_string_fields,
)
from toy import EchoConfig, EchoOperator, TickConfig, TickSensor, ToyPlugin, plugin


class NullLogger:
    """A logger that discards everything, standing in for the engine's batched writer."""

    def debug(self, message: str, **fields: JsonValue) -> None:
        """Discard a debug entry."""

    def info(self, message: str, **fields: JsonValue) -> None:
        """Discard an info entry."""

    def warning(self, message: str, **fields: JsonValue) -> None:
        """Discard a warning entry."""

    def error(self, message: str, **fields: JsonValue) -> None:
        """Discard an error entry."""


class NullStorage:
    """A storage facade that holds nothing."""

    def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream the object at a URI."""
        raise NotImplementedError

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a streamed writer for a URI."""
        raise NotImplementedError

    async def stat(self, uri: str) -> StatResult | None:
        """Describe the object at a URI."""
        return None

    def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the objects under a URI prefix."""
        raise NotImplementedError

    async def delete(self, uri: str) -> None:
        """Remove the object at a URI."""


class NullRuns:
    """A runs facade that holds no runs, which is enough to satisfy the protocol."""

    async def start(self, pipeline: str, params: Mapping[str, JsonValue], *, max_depth: int) -> StartedRun:
        """Refuse every start, since this instance has no pipelines."""
        raise RunRefused(f"this instance has no pipeline coded {pipeline!r}")

    async def snapshot(self, run_id: RunId) -> RunSnapshot | None:
        """Report that no such run exists."""
        return None

    async def cancel(self, run_id: RunId, *, reason: str) -> bool:
        """Report that there was nothing to cancel."""
        return False


class FakeContext:
    """A StepContext good enough to drive a block in a unit test."""

    def __init__(self) -> None:
        """Build a context for a fresh, single-attempt run."""
        self.run_id: RunId = uuid4()
        self.step = "step"
        self.run_item_id: UUID | None = None
        self.attempt = 1
        self.started_at = datetime.now(UTC)
        self.inline_capture = 8 * 1024
        self.cursor: JsonMap | None = None
        self.params: Mapping[str, JsonValue] = {}
        self.log: Logger = NullLogger()
        self._storage: Storage = NullStorage()
        self._runs: Runs = NullRuns()

    def connection[C: BaseModel](self, ref: str, model: type[C]) -> C:
        """Resolve a named connection into the requested model."""
        return model()

    def storage_connection[C: BaseModel](self, scheme: str, model: type[C]) -> C | None:
        """This contract fake binds no scheme to a connection."""
        return None

    def http(self, ref: str) -> httpx2.AsyncClient:
        """Build an HTTP client for a named connection."""
        return httpx2.AsyncClient(base_url="http://localhost")

    def schema(self, code: str) -> JsonMap:
        """Resolve a named schema; this fake holds none."""
        raise KeyError(code)

    def format_checker(self) -> FormatChecker:
        """The base formats, which is all a contract test needs."""
        return base_format_checker()

    @property
    def storage(self) -> Storage:
        """Access URI-addressed storage."""
        return self._storage

    @property
    def scratch(self) -> str:
        """Return the run-scoped URI prefix."""
        return f"memory://runs/{self.run_id}"

    @property
    def work(self) -> Path:
        """Return the run's directory on this worker's own filesystem."""
        directory = Path(tempfile.gettempdir()) / "dirigent-contract" / str(self.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def runs(self) -> Runs:
        """Access this instance's own runs."""
        return self._runs


@pytest.fixture
def ctx() -> StepContext:
    """Provide a step context for block calls."""
    return FakeContext()


def test_remote_handle_is_frozen() -> None:
    handle = RemoteHandle(block_id="toy.echo", ref="job-1")
    with pytest.raises(ValidationError):
        handle.ref = "job-2"  # type: ignore[misc]


def test_remote_handle_rejects_a_malformed_block_id() -> None:
    with pytest.raises(ValidationError):
        RemoteHandle(block_id="NotABlockId", ref="job-1")


def test_remote_handle_rejects_an_empty_ref() -> None:
    with pytest.raises(ValidationError):
        RemoteHandle(block_id="toy.echo", ref="")


def test_operator_spec_requires_a_namespaced_id() -> None:
    with pytest.raises(ValidationError):
        OperatorSpec(id="echo", summary="No namespace.")
    assert OperatorSpec(id="toy.echo", summary="Fine.").idempotent is False


def test_sensor_spec_carries_engine_defaults() -> None:
    spec = SensorSpec(id="toy.tick", summary="Tick.")
    assert spec.default_poll == timedelta(minutes=1)
    assert spec.default_deadline == timedelta(hours=24)


def test_a_spec_that_declares_no_group_falls_back_to_the_ids_first_half() -> None:
    assert OperatorSpec(id="toy.echo", summary="Echo.").group == "toy"
    assert SensorSpec(id="toy.tick", summary="Tick.").group == "toy"


def test_a_block_shelves_itself_wherever_it_says_rather_than_where_its_id_reads() -> None:
    assert OperatorSpec(id="map.jq", summary="Map.", group="transform").group == "transform"
    assert SensorSpec(id="toy.tick", summary="Tick.", group="time").group == "time"


def test_a_group_is_one_bare_word() -> None:
    with pytest.raises(ValidationError):
        OperatorSpec(id="toy.echo", summary="Echo.", group="not a word")
    with pytest.raises(ValidationError):
        OperatorSpec(id="toy.echo", summary="Echo.", group="two.words")


def test_probe_result_rejects_progress_outside_the_unit_interval() -> None:
    with pytest.raises(ValidationError):
        dirigent_plugin.ProbeResult(status=ProbeStatus.RUNNING, progress=1.5)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx2.ConnectError("down"), ErrorClass.TRANSIENT),
        (httpx2.ReadError("reset"), ErrorClass.TRANSIENT),
        (httpx2.WriteError("broken"), ErrorClass.TRANSIENT),
        (httpx2.ProxyError("refused"), ErrorClass.TRANSIENT),
        (httpx2.ConnectTimeout("slow"), ErrorClass.TRANSIENT),
        (httpx2.ReadTimeout("slow"), ErrorClass.TRANSIENT),
        (httpx2.WriteTimeout("slow"), ErrorClass.TRANSIENT),
        (httpx2.PoolTimeout("saturated"), ErrorClass.TRANSIENT),
        (httpx2.TimeoutException("slow"), ErrorClass.TRANSIENT),
        (httpx2.RemoteProtocolError("garbled"), ErrorClass.TRANSIENT),
        (TimeoutError("slow"), ErrorClass.TRANSIENT),
        (ConnectionError("reset"), ErrorClass.TRANSIENT),
        (ValueError("nonsense"), ErrorClass.UNKNOWN),
    ],
)
def test_classify_default_maps_transport_errors(error: Exception, expected: ErrorClass) -> None:
    assert classify_default(error) == expected


def test_every_httpx2_transport_error_is_transient() -> None:
    """The whole TransportError branch retries, so a new httpx2 subclass never reads as unknown."""
    subclasses = [cls for cls in httpx2.TransportError.__subclasses__() if cls is not httpx2.TimeoutException]
    assert subclasses
    for subclass in [*subclasses, *httpx2.TimeoutException.__subclasses__()]:
        assert classify_default(subclass("boom")) is ErrorClass.TRANSIENT


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (500, ErrorClass.TRANSIENT),
        (503, ErrorClass.TRANSIENT),
        (400, ErrorClass.REJECTED),
        (401, ErrorClass.REJECTED),
        (404, ErrorClass.REJECTED),
        (302, ErrorClass.UNKNOWN),
    ],
)
def test_classify_default_maps_http_status(status: int, expected: ErrorClass) -> None:
    request = httpx2.Request("GET", "http://localhost/x")
    error = httpx2.HTTPStatusError("boom", request=request, response=httpx2.Response(status, request=request))
    assert classify_default(error) == expected


def test_classify_default_honours_an_explicit_block_failure() -> None:
    failure = dirigent_plugin.BlockFailure("refused", error_class=ErrorClass.REJECTED)
    assert classify_default(failure) == ErrorClass.REJECTED
    assert str(failure) == "refused"


def test_operator_classify_error_defaults_to_the_shared_helper() -> None:
    assert EchoOperator().classify_error(httpx2.ConnectError("down")) == ErrorClass.TRANSIENT


async def test_synchronous_operator_returns_its_output(ctx: StepContext) -> None:
    result = await EchoOperator().execute(EchoConfig(value="hello"), ctx)
    assert not isinstance(result, RemoteHandle)
    assert result.value == "hello"


async def test_async_operator_round_trips_submit_probe_fetch(ctx: StepContext) -> None:
    operator = EchoOperator()
    config = EchoConfig(value="hello", remote=True)
    handle = await operator.execute(config, ctx)
    assert isinstance(handle, RemoteHandle)
    probe = await operator.probe(handle, config, ctx)
    assert probe.status is ProbeStatus.SUCCEEDED
    output = await operator.fetch(handle, config, ctx)
    assert output.value == "hello"
    assert await operator.cancel(handle, config, ctx) is True


async def test_operator_without_probe_support_raises(ctx: StepContext) -> None:
    class Bare(dirigent_plugin.Operator[EchoConfig, dirigent_plugin.NotYet]):
        """An operator that never returns a handle, so it implements nothing else."""

        spec = OperatorSpec(id="toy.bare", summary="Bare.")
        config_model = EchoConfig
        output_model = NotYet

        async def execute(self, config: EchoConfig, ctx: StepContext) -> NotYet | RemoteHandle:
            """Return an empty output."""
            return NotYet()

    handle = RemoteHandle(block_id="toy.bare", ref="job-1")
    with pytest.raises(NotImplementedError):
        await Bare().probe(handle, EchoConfig(value="x"), ctx)
    with pytest.raises(NotImplementedError):
        await Bare().fetch(handle, EchoConfig(value="x"), ctx)
    assert await Bare().cancel(handle, EchoConfig(value="x"), ctx) is False


async def test_sensor_returns_not_yet_until_the_world_is_ready(ctx: StepContext) -> None:
    sensor = TickSensor()
    waiting = await sensor.poke(TickConfig(ready=False), ctx)
    assert isinstance(waiting, NotYet)
    assert waiting.next_poll_in == timedelta(seconds=5)
    observed = await sensor.poke(TickConfig(ready=True), ctx)
    assert not isinstance(observed, NotYet)


def test_contribution_rejects_a_foreign_api_version() -> None:
    with pytest.raises(ValidationError):
        Contribution(api_version=API_VERSION + 1)


def test_contribution_rejects_duplicate_block_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate block id"):
        Contribution(operators=[EchoOperator(), EchoOperator()])


def test_contribution_rejects_duplicate_notifier_ids() -> None:
    from toy import NullNotifier

    with pytest.raises(ValidationError, match="duplicate notifier id"):
        Contribution(notifiers=[NullNotifier(), NullNotifier()])


def test_contribution_is_frozen() -> None:
    contribution = Contribution()
    with pytest.raises(ValidationError):
        contribution.api_version = 2  # type: ignore[misc]


def test_merge_contributions_flattens_every_surface() -> None:
    class OtherTick(TickSensor):
        """A second sensor under its own id."""

        spec = SensorSpec(id="toy.other_tick", summary="Tick again.")

    merged = merge_contributions([ToyPlugin().contribute(), Contribution(sensors=[OtherTick()])])
    assert merged.block_ids() == ["toy.echo", "toy.tick", "toy.other_tick"]
    assert len(merged.connection_kinds) == 1


def test_merge_contributions_refuses_two_plugins_claiming_one_block_id() -> None:
    with pytest.raises(ValidationError, match="duplicate block id"):
        merge_contributions([Contribution(sensors=[TickSensor()]), Contribution(sensors=[TickSensor()])])


def test_contribution_carries_contributed_formats() -> None:
    """A pack names a format checker by format name, and the merge gathers it whole."""
    contribution = Contribution(formats={"even-digits": lambda value: isinstance(value, str) and len(value) % 2 == 0})
    merged = merge_contributions([contribution, Contribution(formats={"odd-digits": lambda value: True})])
    assert set(merged.formats) == {"even-digits", "odd-digits"}
    assert merged.formats["even-digits"]("abcd") is True
    assert merged.formats["even-digits"]("abc") is False


def test_merge_contributions_refuses_two_plugins_claiming_one_format() -> None:
    with pytest.raises(ValueError, match="duplicate format"):
        merge_contributions(
            [
                Contribution(formats={"dhis2-uid": lambda value: True}),
                Contribution(formats={"dhis2-uid": lambda value: True}),
            ]
        )


def make_manager() -> PluginManager:
    """Build a plugin manager wired to the dirigent extension point."""
    manager = PluginManager(dirigent_plugin.PROJECT_NAME)
    manager.add_extension_points(markers)
    return manager


def test_a_plugin_round_trips_through_a_plugin_manager() -> None:
    manager = make_manager()
    manager.register(plugin, name="toy")
    contributions: list[Any] = manager.caller(contribute)()
    assert len(contributions) == 1
    catalog = merge_contributions(contributions)
    assert catalog.api_version == API_VERSION
    assert catalog.block_ids() == ["toy.echo", "toy.tick"]
    assert [backend.scheme for backend in catalog.storage_backends] == ["memory"]
    assert [notifier.id for notifier in catalog.notifiers] == ["null"]
    assert [connection.id for connection in catalog.connection_kinds] == ["toy"]


def test_an_unregistered_plugin_contributes_nothing() -> None:
    manager = make_manager()
    manager.register(plugin, name="toy")
    manager.unregister("toy")
    assert manager.caller(contribute)() == []


def test_the_entry_point_group_is_version_pinned() -> None:
    assert dirigent_plugin.ENTRY_POINT_GROUP == "dirigent.plugins.v1"


# -- the runs facade -------------------------------------------------------------


def test_a_run_state_knows_whether_it_has_settled() -> None:
    assert not RunState.QUEUED.settled
    assert not RunState.RUNNING.settled
    assert all(state.settled for state in (RunState.SUCCEEDED, RunState.COMPLETED_WITH_ERRORS, RunState.FAILED))
    assert RunState.CANCELLED.settled


def test_a_started_run_reports_a_concurrency_skip_as_no_run_at_all() -> None:
    started = StartedRun(pipeline="child")
    assert started.skipped
    assert not StartedRun(pipeline="child", run_id=uuid4(), state=RunState.QUEUED).skipped


def test_a_snapshot_turns_finished_steps_into_progress() -> None:
    run_id = uuid4()
    snapshot = RunSnapshot(run_id=run_id, pipeline="child", state=RunState.RUNNING, total_steps=4, finished_steps=1)
    assert snapshot.progress == 0.25
    assert RunSnapshot(run_id=run_id, pipeline="child", state=RunState.QUEUED).progress is None


def test_a_snapshot_never_reports_more_than_finished() -> None:
    snapshot = RunSnapshot(run_id=uuid4(), pipeline="child", state=RunState.SUCCEEDED, total_steps=2, finished_steps=3)
    assert snapshot.progress == 1.0


def test_a_refused_run_is_never_retried() -> None:
    refusal = RunRefused("this instance has no pipeline coded 'child'")
    assert refusal.error_class is ErrorClass.REJECTED
    assert classify_default(refusal) is ErrorClass.REJECTED


async def test_the_null_runs_facade_satisfies_the_protocol(ctx: StepContext) -> None:
    runs: Runs = ctx.runs
    assert await runs.snapshot(uuid4()) is None
    assert await runs.cancel(uuid4(), reason="because") is False
    with pytest.raises(RunRefused, match="no pipeline coded 'child'"):
        await runs.start("child", {}, max_depth=5)


def test_an_operator_may_declare_its_own_probe_cadence() -> None:
    assert OperatorSpec(id="toy.echo", summary="Echo.").default_poll is None
    spec = OperatorSpec(id="toy.slow", summary="Slow.", default_poll=timedelta(seconds=5))
    assert spec.default_poll == timedelta(seconds=5)


def test_a_shell_string_publishes_the_language_it_holds_and_still_validates_nothing() -> None:
    """The marker says in the schema that the field is shell source, and leaves validation alone."""

    class Ran(BaseModel):
        command: Annotated[str | None, ShellString()] = None

    published = Ran.model_json_schema()["properties"]["command"]

    assert published["contentMediaType"] == SHELL_MEDIA_TYPE
    assert Ran(command="tar cf - . | gzip").command == "tar cf - . | gzip"
    assert Ran().command is None
    assert shell_string_fields(Ran) == frozenset({"command"})
