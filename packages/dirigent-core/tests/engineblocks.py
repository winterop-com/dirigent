"""Blocks the engine tests drive: one of every shape the engine has to handle."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, ClassVar

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel, Duration, StorageUri
from dirigent_plugin import (
    BlockFailure,
    Contribution,
    ErrorClass,
    NotYet,
    Operator,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    Sensor,
    SensorSpec,
    ShellString,
    StepContext,
    Transformer,
    TransformError,
    extension,
)


class EchoConfig(BlockModel):
    """What the echo operator is told."""

    value: str = "hello"
    upper: bool = False
    connection: str | None = None
    """Named like a real block's, so the connection checks have a config field to read."""

    json_schema: str | None = Field(alias="schema", default=None)
    """Named like validate.schema's, so the schema checks have a config field to read."""

    labels: dict[str, str] = {}
    """A free-form map, so a test has somewhere to write keys the format does not interpret."""

    stalls: Duration | None = None
    """How long to sleep before answering, so a step timeout has something to interrupt."""


class EchoOutput(BlockModel):
    """What the echo operator reports."""

    value: str
    length: int


class EchoOperator(Operator[EchoConfig, EchoOutput]):
    """A synchronous operator: it finishes in its own call and returns an output."""

    spec = OperatorSpec(id="test.echo", summary="Echo a value.", idempotent=True)
    config_model = EchoConfig
    output_model = EchoOutput
    calls: ClassVar[list[str]] = []

    async def execute(self, config: EchoConfig, ctx: StepContext) -> EchoOutput | RemoteHandle:
        """Return the configured value, recording that the call happened."""
        EchoOperator.calls.append(config.value)
        if config.stalls is not None:
            await asyncio.sleep(config.stalls.total_seconds())
        ctx.log.debug("echoing quietly", value=config.value)
        ctx.log.info("echoing", value=config.value)
        rendered = config.value.upper() if config.upper else config.value
        return EchoOutput(value=rendered, length=len(rendered))


class ShellishConfig(BaseModel):
    """A config with a field the block declares as being handed to a shell."""

    command: Annotated[str, ShellString()] = ""


class ShellishOutput(BaseModel):
    """What the shell-string operator saw after the engine resolved its config."""

    command: str


class ShellishOperator(Operator[ShellishConfig, ShellishOutput]):
    """Reports the command string it was given, so a test can read what the engine quoted."""

    spec = OperatorSpec(id="test.shellish", summary="Report a shell command string.", idempotent=True)
    config_model = ShellishConfig
    output_model = ShellishOutput

    async def execute(self, config: ShellishConfig, ctx: StepContext) -> ShellishOutput | RemoteHandle:
        """Return the command exactly as it arrived."""
        return ShellishOutput(command=config.command)


class FailConfig(BaseModel):
    """What the failing operator is told."""

    message: str = "boom"
    error_class: ErrorClass = ErrorClass.TRANSIENT
    fail_times: int = 1_000_000
    key: str = "default"


class FailOutput(BaseModel):
    """What the failing operator reports when it finally succeeds."""

    attempts: int


class FailOperator(Operator[FailConfig, FailOutput]):
    """Fails a configured number of times, then succeeds: the retry-policy exerciser."""

    spec = OperatorSpec(id="test.fail", summary="Fail a fixed number of times.", idempotent=True)
    config_model = FailConfig
    output_model = FailOutput
    attempts: ClassVar[dict[str, int]] = {}

    async def execute(self, config: FailConfig, ctx: StepContext) -> FailOutput | RemoteHandle:
        """Count the call, then fail or succeed according to configuration."""
        seen = FailOperator.attempts.get(config.key, 0) + 1
        FailOperator.attempts[config.key] = seen
        if seen <= config.fail_times:
            raise BlockFailure(config.message, error_class=config.error_class)
        return FailOutput(attempts=seen)


class NonIdempotentOperator(FailOperator):
    """The same failure behaviour, but the block refuses to declare itself repeatable."""

    spec = OperatorSpec(id="test.fragile", summary="Fail without declaring idempotence.")


class RemoteConfig(BaseModel):
    """What the remote operator is told."""

    ref: str = "job-1"
    statuses: list[ProbeStatus] = [ProbeStatus.SUCCEEDED]
    result: str = "done"
    poll_hint: timedelta | None = timedelta(seconds=1)
    """What the probe names as its own next interval; None leaves the choice to the engine."""

    says: str | None = None
    """What a running probe reports it is seeing."""

    shows: float | None = None
    """How far along a running probe reports the remote to be."""

    cursors: list[dict[str, str] | None] = []
    """What each probe in turn returns as the handle's new metadata; past the end is None."""


class RemoteOutput(BaseModel):
    """What the remote operator reports once fetched."""

    ref: str
    result: str


class RemoteOperator(Operator[RemoteConfig, RemoteOutput]):
    """An async operator: it submits, hands back a handle, and is probed until terminal."""

    spec = OperatorSpec(id="test.remote", summary="Submit, then be probed.", idempotent=True)
    config_model = RemoteConfig
    output_model = RemoteOutput
    submissions: ClassVar[list[str]] = []
    probes: ClassVar[list[str]] = []
    fetches: ClassVar[list[str]] = []
    cancellations: ClassVar[list[str]] = []
    probed_meta: ClassVar[list[dict[str, str]]] = []
    """The metadata each probe was handed, which is how a cursor test reads what advanced."""

    fetched_meta: ClassVar[list[dict[str, str]]] = []
    """The metadata each fetch was handed, which is the advance a terminal probe made."""

    async def execute(self, config: RemoteConfig, ctx: StepContext) -> RemoteOutput | RemoteHandle:
        """Submit exactly one unit of remote work and return a claim on it."""
        RemoteOperator.submissions.append(config.ref)
        return RemoteHandle(block_id=self.spec.id, ref=config.ref, meta={"result": config.result})

    async def probe(self, handle: RemoteHandle, config: RemoteConfig, ctx: StepContext) -> ProbeResult:
        """Report the next configured status, repeating the last one forever."""
        seen = len(RemoteOperator.probes)
        index = min(seen, len(config.statuses) - 1)
        cursor = config.cursors[seen] if seen < len(config.cursors) else None
        RemoteOperator.probes.append(handle.ref)
        RemoteOperator.probed_meta.append(dict(handle.meta))
        return ProbeResult(
            status=config.statuses[index],
            next_poll_in=config.poll_hint,
            message=config.says,
            progress=config.shows,
            meta=cursor,
        )

    async def fetch(self, handle: RemoteHandle, config: RemoteConfig, ctx: StepContext) -> RemoteOutput:
        """Collect the result after a probe reported success, counting every call."""
        RemoteOperator.fetches.append(handle.ref)
        RemoteOperator.fetched_meta.append(dict(handle.meta))
        return RemoteOutput(ref=handle.ref, result=handle.meta["result"])

    async def cancel(self, handle: RemoteHandle, config: RemoteConfig, ctx: StepContext) -> bool:
        """Record that the remote was told, which cancellation tests assert on."""
        RemoteOperator.cancellations.append(handle.ref)
        return True


class UnsafeConfig(BaseModel):
    """What the local-execution operator is told."""

    command: str = "true"


class UnsafeOutput(BaseModel):
    """What the local-execution operator reports."""

    command: str


class UnsafeOperator(Operator[UnsafeConfig, UnsafeOutput]):
    """Declares that it runs code on the worker, so the allowlist gate applies to it."""

    spec = OperatorSpec(id="test.unsafe", summary="Run code on the worker.", local_execution=True)
    config_model = UnsafeConfig
    output_model = UnsafeOutput
    calls: ClassVar[list[str]] = []

    async def execute(self, config: UnsafeConfig, ctx: StepContext) -> UnsafeOutput | RemoteHandle:
        """Record that the gate let this through."""
        UnsafeOperator.calls.append(config.command)
        return UnsafeOutput(command=config.command)


class StoringConfig(BaseModel):
    """One field a block publishes as a storage URI, and one that is not."""

    target: StorageUri = ""
    url: str = ""


class StoringOutput(BaseModel):
    """Where it says it put something."""

    target: str


class StoringOperator(Operator[StoringConfig, StoringOutput]):
    """Declares a storage URI, so an instance can check its scheme before a run."""

    spec = OperatorSpec(id="test.storing", summary="Address stored bytes.")
    config_model = StoringConfig
    output_model = StoringOutput

    async def execute(self, config: StoringConfig, ctx: StepContext) -> StoringOutput | RemoteHandle:
        """Report the target it was given."""
        return StoringOutput(target=config.target)


class TickConfig(BaseModel):
    """What the tick sensor is told."""

    ready_after: int = 0
    raises: bool = False
    key: str = "default"
    poll_hint: timedelta | None = timedelta(seconds=1)
    """What the poke names as its own next interval; None leaves the choice to the engine."""

    says: list[str] = []
    """What each poke reports it is seeing, the last entry repeating once exhausted."""


class TickOutput(BaseModel):
    """What the tick sensor observed."""

    pokes: int
    observed_at: datetime


class TickSensor(Sensor[TickConfig, TickOutput]):
    """Reports NotYet until it has been poked enough times, which never costs retry budget."""

    spec = SensorSpec(
        id="test.tick",
        summary="Wait for a number of pokes.",
        default_poll=timedelta(seconds=1),
        default_deadline=timedelta(hours=1),
    )
    config_model = TickConfig
    output_model = TickOutput
    pokes: ClassVar[dict[str, int]] = {}

    async def poke(self, config: TickConfig, ctx: StepContext) -> TickOutput | NotYet:
        """Observe once, read-only, and never sleep."""
        seen = TickSensor.pokes.get(config.key, 0) + 1
        TickSensor.pokes[config.key] = seen
        if config.raises:
            raise BlockFailure("the world is unreadable", error_class=ErrorClass.TRANSIENT)
        if seen <= config.ready_after:
            if config.says:
                return NotYet(
                    next_poll_in=config.poll_hint,
                    message=config.says[min(seen, len(config.says)) - 1],
                    progress=seen / (config.ready_after + 1),
                )
            return NotYet(next_poll_in=config.poll_hint)
        return TickOutput(pokes=seen, observed_at=datetime.now(UTC))


class ChattyConfig(BaseModel):
    """What the chatty operator is told."""

    lines: int = 1
    gate: bool = False
    """Whether the call waits at the gate after its lines, so a test can read the run's log
    while the attempt is still running."""

    last: bool = True
    """Whether the call logs one more line after the gate, or leaves the buffer empty."""


class ChattyOutput(BaseModel):
    """What the chatty operator reports."""

    lines: int


class ChattyOperator(Operator[ChattyConfig, ChattyOutput]):
    """Logs a line at a time, and can be held mid-call while a test reads what it logged."""

    spec = OperatorSpec(id="test.chatty", summary="Log a number of lines.", idempotent=True)
    config_model = ChattyConfig
    output_model = ChattyOutput
    at_gate: ClassVar[asyncio.Event] = asyncio.Event()
    released: ClassVar[asyncio.Event] = asyncio.Event()

    async def execute(self, config: ChattyConfig, ctx: StepContext) -> ChattyOutput | RemoteHandle:
        """Log the configured lines, wait at the gate if asked, and log a last line unless told not to."""
        for index in range(config.lines):
            ctx.log.info(f"line {index}")
        if config.gate:
            ChattyOperator.at_gate.set()
            await ChattyOperator.released.wait()
        if config.last:
            ctx.log.info("done")
        return ChattyOutput(lines=config.lines + int(config.last))


class CursorConfig(BaseModel):
    """What the cursor sensor is told: how far to read, and how far each poke gets."""

    need: int = 0
    """The offset the cursor must reach before a poke succeeds."""

    batch: int = 5
    """How far one poke advances the cursor."""

    advances: int = 100
    """How many pokes carry an advance; every poke after that parks without one."""

    extra: dict[str, JsonValue] = {}
    """Written into the first advance only, so a test can watch a dropped key go."""

    key: str = "default"


class CursorOutput(BaseModel):
    """What the cursor sensor was holding when it finally succeeded."""

    cursor: dict[str, JsonValue] | None


class CursorSensor(Sensor[CursorConfig, CursorOutput]):
    """Reads a notional stream by offset, keeping its place in the cursor between pokes."""

    spec = SensorSpec(
        id="test.cursor",
        summary="Wait while writing down how far it has read.",
        default_poll=timedelta(seconds=1),
        default_deadline=timedelta(hours=1),
    )
    config_model = CursorConfig
    output_model = CursorOutput
    seen: ClassVar[dict[str, list[dict[str, JsonValue] | None]]] = {}

    async def poke(self, config: CursorConfig, ctx: StepContext) -> CursorOutput | NotYet:
        """Note what the engine handed over, then either succeed or park with an advance."""
        history = CursorSensor.seen.setdefault(config.key, [])
        handed = dict(ctx.cursor) if ctx.cursor is not None else None
        history.append(handed)
        offset = int((handed or {}).get("offset", 0))
        if offset >= config.need:
            return CursorOutput(cursor=handed)
        if len(history) > config.advances:
            return NotYet(next_poll_in=timedelta(seconds=1))
        advance: dict[str, JsonValue] = {"offset": offset + config.batch}
        if offset == 0:
            advance.update(config.extra)
        return NotYet(cursor=advance, next_poll_in=timedelta(seconds=1))


CASES = ("upper", "lower")


class CasingTransformer(Transformer):
    """A transform engine whose whole language is the two words in CASES."""

    kind = "upper"
    summary = "Change the case of every string in a value."

    def compile(self, program: str) -> object:
        """Accept one of the two words this engine knows, and nothing else."""
        if program not in CASES:
            raise TransformError(f"{program!r} is not a case: write one of {', '.join(CASES)}")
        return program

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Recase a string and leave anything else alone."""
        if isinstance(value, str):
            return value.upper() if compiled == "upper" else value.lower()
        return value


def reset_blocks() -> None:
    """Forget every recorded call, so one test cannot read another's history."""
    EchoOperator.calls.clear()
    FailOperator.attempts.clear()
    RemoteOperator.submissions.clear()
    RemoteOperator.probes.clear()
    RemoteOperator.fetches.clear()
    RemoteOperator.cancellations.clear()
    RemoteOperator.probed_meta.clear()
    RemoteOperator.fetched_meta.clear()
    UnsafeOperator.calls.clear()
    TickSensor.pokes.clear()
    CursorSensor.seen.clear()
    ChattyOperator.at_gate = asyncio.Event()
    ChattyOperator.released = asyncio.Event()


class EngineTestPlugin:
    """The plugin the engine tests install into the host."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute one block of every shape the engine has to handle."""
        return Contribution(
            operators=[
                CasingTransformer(),
                ChattyOperator(),
                EchoOperator(),
                FailOperator(),
                NonIdempotentOperator(),
                RemoteOperator(),
                ShellishOperator(),
                StoringOperator(),
                UnsafeOperator(),
            ],
            sensors=[TickSensor(), CursorSensor()],
        )
