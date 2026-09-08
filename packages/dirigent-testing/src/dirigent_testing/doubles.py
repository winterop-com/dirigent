"""The engine's side of a block call, faked: a step context, storage, logs, and runs."""

import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
from jsonschema import FormatChecker
from pydantic import BaseModel, JsonValue

from dirigent_common import format_checker_with
from dirigent_plugin import (
    ByteSink,
    FormatCheck,
    RunRefused,
    RunSnapshot,
    RunState,
    StartedRun,
    StatResult,
    StepContext,
)


class RecordingLogger:
    """Keeps every entry a block wrote, so tests can assert on what it reported."""

    def __init__(self) -> None:
        """Start with an empty log."""
        self.entries: list[tuple[str, str, dict[str, JsonValue]]] = []

    def debug(self, message: str, **fields: JsonValue) -> None:
        """Record a debug entry."""
        self.entries.append(("debug", message, dict(fields)))

    def info(self, message: str, **fields: JsonValue) -> None:
        """Record an info entry."""
        self.entries.append(("info", message, dict(fields)))

    def warning(self, message: str, **fields: JsonValue) -> None:
        """Record a warning entry."""
        self.entries.append(("warning", message, dict(fields)))

    def error(self, message: str, **fields: JsonValue) -> None:
        """Record an error entry."""
        self.entries.append(("error", message, dict(fields)))

    def messages(self) -> list[str]:
        """List just the messages, which is what most assertions want."""
        return [message for _, message, _ in self.entries]


class FakeSink:
    """The write end of a local file, standing in for a storage backend's sink."""

    def __init__(self, path: Path) -> None:
        """Open the file for writing."""
        self.path = path
        self._handle = path.open("wb")

    async def write(self, data: bytes) -> int:
        """Append bytes."""
        return self._handle.write(data)

    def close(self) -> None:
        """Finish the file."""
        self._handle.close()


class FakeStorage:
    """A storage facade over one directory, backing the storage blocks in a test."""

    def __init__(self, root: Path) -> None:
        """Root the facade at a throwaway directory."""
        self.root = root

    def path_for(self, uri: str) -> Path:
        """Map a URI onto a local path: absolute as given, relative under the root."""
        _, _, location = uri.partition("://")
        path = Path(location)
        return path if path.is_absolute() else self.root / location

    async def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream an object in two chunks, so callers cannot assume one."""
        payload = self.path_for(uri).read_bytes()
        middle = max(len(payload) // 2, 1)
        yield payload[:middle]
        if payload[middle:]:
            yield payload[middle:]

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a writer for a URI, creating the directories it needs."""

        @asynccontextmanager
        async def writer() -> AsyncGenerator[ByteSink]:
            path = self.path_for(uri)
            path.parent.mkdir(parents=True, exist_ok=True)
            sink = FakeSink(path)
            try:
                yield sink
            finally:
                sink.close()

        return writer()

    async def stat(self, uri: str) -> StatResult | None:
        """Describe an object, or report that it is not there."""
        path = self.path_for(uri)
        if not path.is_file():
            return None
        info = path.stat()
        return StatResult(uri=uri, size=info.st_size, modified_at=datetime.fromtimestamp(info.st_mtime, tz=UTC))

    async def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the objects matching a pattern, in a stable order."""
        scheme, _, pattern = uri.partition("://")
        for path in sorted(self.root.glob(pattern.lstrip("/"))):
            if not path.is_file():
                continue
            info = path.stat()
            yield StatResult(
                uri=f"{scheme}://{path.relative_to(self.root)}",
                size=info.st_size,
                modified_at=datetime.fromtimestamp(info.st_mtime, tz=UTC),
            )

    async def delete(self, uri: str) -> None:
        """Remove an object."""
        self.path_for(uri).unlink(missing_ok=True)


class FakeRuns:
    """The runs facade, faked: an in-memory instance a composition block can drive."""

    def __init__(self) -> None:
        """Start with no pipelines and no runs."""
        self.pipelines: set[str] = set()
        self.snapshots: dict[UUID, RunSnapshot] = {}
        self.started: list[tuple[str, dict[str, JsonValue], int]] = []
        self.cancelled: list[UUID] = []
        self.skip: set[str] = set()
        self.refusal: str | None = None

    def hold(
        self,
        pipeline: str,
        state: RunState = RunState.QUEUED,
        *,
        total_steps: int = 0,
        finished_steps: int = 0,
    ) -> UUID:
        """Install a run this instance holds, and return the id a handle would name."""
        run_id = uuid4()
        self.pipelines.add(pipeline)
        self.snapshots[run_id] = RunSnapshot(
            run_id=run_id,
            pipeline=pipeline,
            state=state,
            total_steps=total_steps,
            finished_steps=finished_steps,
        )
        return run_id

    async def start(self, pipeline: str, params: Mapping[str, JsonValue], *, max_depth: int) -> StartedRun:
        """Record the start and answer with a run, a skip, or the refusal the test installed."""
        self.started.append((pipeline, dict(params), max_depth))
        if self.refusal is not None:
            raise RunRefused(self.refusal)
        if pipeline in self.skip:
            return StartedRun(pipeline=pipeline)
        run_id = self.hold(pipeline)
        return StartedRun(pipeline=pipeline, run_id=run_id, state=RunState.QUEUED)

    async def snapshot(self, run_id: UUID) -> RunSnapshot | None:
        """Describe a run this fake instance holds."""
        return self.snapshots.get(run_id)

    async def cancel(self, run_id: UUID, *, reason: str) -> bool:
        """Cancel a run, unless it had already settled or was never here."""
        self.cancelled.append(run_id)
        held = self.snapshots.get(run_id)
        if held is None or held.state.settled:
            return False
        self.snapshots[run_id] = held.model_copy(update={"state": RunState.CANCELLED, "error": reason})
        return True


class FakeContext:
    """The engine's side of the bargain, faked: real storage, a recording log, a fake client."""

    def __init__(self, storage: FakeStorage, scratch: str, work: Path | None = None) -> None:
        """Bind the context to a storage root, a scratch prefix, and a local work directory."""
        self.run_id: UUID = uuid4()
        self.step = "step"
        self.run_item_id: UUID | None = None
        self.attempt = 1
        self.started_at = datetime.now(UTC)
        self.inline_capture = 8 * 1024
        self.cursor: dict[str, JsonValue] | None = None
        """What the last committed ``NotYet`` returned, which a test sets to poke again."""
        self.params: dict[str, JsonValue] = {}
        self.log = RecordingLogger()
        self.connections: dict[str, BaseModel] = {}
        self.storage_connections: dict[str, str] = {}
        """Which connection code serves each storage scheme, as ``storage_connections`` maps them."""
        self.schemas: dict[str, Any] = {}
        self.formats: dict[str, FormatCheck] = {}
        """Contributed format checkers a test installs, so a block can exercise ``format: <name>``."""
        self.handler: Callable[[httpx2.Request], httpx2.Response] | None = None
        self.scratch_uri = scratch
        self.work_dir = work if work is not None else Path(tempfile.mkdtemp(prefix="dirigent-work-"))
        self._storage = storage
        self._runs = FakeRuns()

    @property
    def storage(self) -> FakeStorage:
        """The storage facade."""
        return self._storage

    @property
    def scratch(self) -> str:
        """The run-scoped URI prefix."""
        return self.scratch_uri

    @property
    def work(self) -> Path:
        """The run's directory on this worker's own filesystem, made on first read.

        Absolute whatever it was set to, as the engine's own is: a child process is given
        both a working directory and the paths it is to touch.
        """
        directory = self.work_dir.absolute()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def runs(self) -> FakeRuns:
        """The instance's own runs, as a composition block reaches them."""
        return self._runs

    def as_context(self) -> StepContext:
        """Present the fake as the protocol a block is typed against.

        The fake keeps its own logger and its own params dictionary so a test can assert on
        them, and a protocol's mutable attribute matches neither of those narrower types.
        """
        return cast("StepContext", self)

    def connection(self, ref: str, model: type[Any]) -> Any:
        """Resolve a named connection the test installed."""
        return self.connections[ref]

    def storage_connection(self, scheme: str, model: type[Any]) -> Any:
        """Resolve the connection the test bound to a storage scheme, or None where it bound none."""
        ref = self.storage_connections.get(scheme)
        return None if ref is None else self.connections[ref]

    def schema(self, code: str) -> Any:
        """Resolve a named schema the test installed; an unknown code fails as the engine's does."""
        return self.schemas[code]

    def format_checker(self) -> FormatChecker:
        """The base formats plus any the test installed on ``formats``."""
        return format_checker_with(self.formats)

    def http(self, ref: str) -> httpx2.AsyncClient:
        """Build a client whose transport is the test's own handler."""
        if self.handler is None:
            raise AssertionError("this test asked for an HTTP client but installed no handler")
        return httpx2.AsyncClient(base_url="http://service.test", transport=httpx2.MockTransport(self.handler))
