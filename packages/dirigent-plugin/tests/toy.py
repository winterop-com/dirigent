"""A minimal plugin used across the contract tests: one operator, one sensor, one of each surface."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from dirigent_common import HealthReport
from dirigent_plugin import (
    AlertMessage,
    ByteSink,
    ConnectionKind,
    Contribution,
    Notifier,
    NotYet,
    Operator,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    Sensor,
    SensorSpec,
    StatResult,
    StepContext,
    StorageBackend,
    extension,
)


class EchoConfig(BaseModel):
    """Configuration of the toy operator."""

    value: str
    remote: bool = False


class EchoOutput(BaseModel):
    """Output of the toy operator."""

    value: str


class EchoOperator(Operator[EchoConfig, EchoOutput]):
    """Returns its input, synchronously or through a fake remote handle."""

    spec = OperatorSpec(id="toy.echo", summary="Echo a value back.", idempotent=True)
    config_model = EchoConfig
    output_model = EchoOutput

    async def execute(self, config: EchoConfig, ctx: StepContext) -> EchoOutput | RemoteHandle:
        """Echo synchronously, or hand the engine a handle to probe."""
        if config.remote:
            return RemoteHandle(block_id=self.spec.id, ref="job-1", meta={"value": config.value})
        return EchoOutput(value=config.value)

    async def probe(self, handle: RemoteHandle, config: EchoConfig, ctx: StepContext) -> ProbeResult:
        """Report the fake remote job as finished immediately."""
        return ProbeResult(status=ProbeStatus.SUCCEEDED)

    async def fetch(self, handle: RemoteHandle, config: EchoConfig, ctx: StepContext) -> EchoOutput:
        """Collect the value the handle carried."""
        return EchoOutput(value=handle.meta["value"])

    async def cancel(self, handle: RemoteHandle, config: EchoConfig, ctx: StepContext) -> bool:
        """Pretend the remote accepted the cancellation."""
        return True


class TickConfig(BaseModel):
    """Configuration of the toy sensor."""

    ready: bool = False


class TickOutput(BaseModel):
    """Output of the toy sensor."""

    observed_at: datetime


class TickSensor(Sensor[TickConfig, TickOutput]):
    """Reports NotYet until its configuration says the world is ready."""

    spec = SensorSpec(
        id="toy.tick",
        summary="Wait until the configuration says ready.",
        default_poll=timedelta(seconds=30),
        default_deadline=timedelta(hours=1),
    )
    config_model = TickConfig
    output_model = TickOutput

    async def poke(self, config: TickConfig, ctx: StepContext) -> TickOutput | NotYet:
        """Observe once, without changing anything."""
        if not config.ready:
            return NotYet(next_poll_in=timedelta(seconds=5))
        return TickOutput(observed_at=datetime.now(UTC))


class MemoryStorageConfig(BaseModel):
    """Configuration of the toy storage backend."""

    root: str = "memory://"


class MemoryStorageBackend(StorageBackend):
    """A storage backend that knows one scheme and nothing else."""

    scheme = "memory"
    config_model = MemoryStorageConfig

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
        return None


class NullNotifierConfig(BaseModel):
    """Configuration of the toy notifier."""

    label: str = "null"


class NullNotifier(Notifier):
    """Accepts every message and drops it."""

    id = "null"
    config_model = NullNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Drop the message."""
        return None


class ToyConnectionConfig(BaseModel):
    """Configuration of the toy connection kind."""

    base_url: str = "http://localhost"


class ToyConnectionKind(ConnectionKind):
    """A connection kind that always reports itself healthy."""

    id = "toy"
    config_model = ToyConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Report the connection as healthy."""
        return HealthReport(healthy=True, detail="toy")


class ToyPlugin:
    """The plugin object a package would expose under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute one block of every kind."""
        return Contribution(
            operators=[EchoOperator()],
            sensors=[TickSensor()],
            storage_backends=[MemoryStorageBackend()],
            notifiers=[NullNotifier()],
            connection_kinds=[ToyConnectionKind()],
        )


plugin = ToyPlugin()
