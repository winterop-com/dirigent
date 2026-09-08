"""``docker.run``: run one container on the worker, submitted once and then probed.

Reaching the Docker socket is reaching root on the host, so this block declares
``local_execution`` and the engine refuses it unless the instance allowlists its id.

The ``docker`` connection kind lives here too, because every block in the family resolves its
daemon through the same material: a ``DOCKER_HOST``, and for a tcp daemon the client TLS
triple as three 0600 files in a 0700 directory that goes when the step leaves.
"""

import contextlib
import errno
import json
import os
import shutil
import ssl
import stat
import tempfile
import time
from collections.abc import AsyncGenerator, AsyncIterator, Generator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import Annotated, ClassVar, NamedTuple, cast

import httpx2
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, model_validator

from dirigent_blocks import secrets, subprocess
from dirigent_blocks.capture import Drained, Ends, log_stream, scrub, tail
from dirigent_blocks.environment import allowed, reject_reserved
from dirigent_blocks.http import status_class
from dirigent_common import BlockModel, Duration, HealthReport, Size
from dirigent_plugin import (
    BlockFailure,
    ByteSink,
    ConnectionKind,
    ConnectionRef,
    ErrorClass,
    Operator,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    ShellString,
    StepContext,
    classify_default,
)

CONTAINER_POLL = timedelta(seconds=2)

DEFAULT_SOCKET_PATH = "/var/run/docker.sock"

#: The variables that name the daemon rather than carry a step's data, so the CLI blocks
#: inherit them from the worker without a document having to name them.
DAEMON_ENV = ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")

#: The socket carries no host, so the URL needs a placeholder authority the daemon ignores.
DAEMON_BASE_URL = "http://docker"

SHELL_ARGV = ("/bin/sh", "-c")

UNFINISHED_STATES = frozenset({"created", "running", "restarting", "paused"})

#: The handle key holding how far into the container's log a probe has read, as the unix
#: timestamp the daemon's ``since`` filter takes.
LOGS_SINCE = "logs_since"

#: Docker frames its log stream with an eight-byte header when the container has no TTY.
STREAM_HEADER_BYTES = 8

STDOUT_FRAME = 1

STDERR_FRAME = 2

#: The smallest memory limit the daemon accepts.
MINIMUM_MEMORY = 6 * 1024 * 1024

NANO_CPUS_PER_CPU = 1_000_000_000

COPY_CHUNK_BYTES = 1024 * 1024

#: The daemon answers 304 for a container already started and 409 for one not running.
NOT_MODIFIED = 304

#: How much of a daemon error body is quoted back in a failure message.
ERROR_DETAIL_CHARS = 8 * 1024
BAD_REQUEST = 400
NOT_FOUND = 404
CONFLICT = 409


#: The schemes a daemon URL may be written in, which are the ones the docker CLI accepts.
DAEMON_SCHEMES = ("tcp://", "ssh://", "unix://")

#: What a registry credential that names no registry authenticates to.
DOCKER_HUB = "docker.io"

#: How long one docker invocation made outside a step -- a connection check, a login -- may take.
CHECK_TIMEOUT_SECONDS = 60.0


class DockerConnectionConfig(BlockModel):
    """A daemon to reach, a registry to authenticate to, or both."""

    host: str = ""
    """The daemon, as ``tcp://host:2376``, ``ssh://user@host`` or ``unix:///var/run/docker.sock``.

    Left empty, a step using this connection reaches the daemon the worker's own environment
    names, which is what a step naming no connection does."""

    tls_ca: SecretStr | None = None
    """The CA the daemon's server certificate is checked against, in PEM form, for a ``tcp://`` host."""

    tls_cert: SecretStr | None = None
    """The client certificate presented to the daemon, in PEM form."""

    tls_key: SecretStr | None = None
    """The client key, in PEM form.

    Sealed like every other connection secret: a client key for a docker daemon is a
    credential for root on whatever that daemon runs on. It reaches the CLI and the API only
    as a 0600 file in a private directory that goes away when the step leaves."""

    registry: str = ""
    """The registry the credential below authenticates to, such as ``ghcr.io``.

    Empty means Docker Hub, which is what ``docker login`` with no argument means."""

    username: str = ""
    """The user half of the registry credential."""

    password: SecretStr | None = None
    """The password or token half, sealed, and handed to ``docker login`` on stdin so it never
    becomes an argument and never reaches the worker's own docker config."""

    @model_validator(mode="after")
    def _check_shape(self) -> "DockerConnectionConfig":
        """Refuse a daemon URL of an unknown form, half a TLS triple, and half a credential."""
        if self.host and not self.host.startswith(DAEMON_SCHEMES):
            raise ValueError(f"a docker host is one of {', '.join(DAEMON_SCHEMES)}, and {self.host!r} is none of them")
        pems = [self.tls_ca, self.tls_cert, self.tls_key]
        if any(pem is not None for pem in pems) and not all(pem is not None for pem in pems):
            raise ValueError("client TLS is all three of tls_ca, tls_cert and tls_key, or none of them")
        if self.tls_key is not None and not self.host.startswith("tcp://"):
            raise ValueError("client TLS is how a tcp:// daemon is reached, so the host must be a tcp:// one")
        if (self.password is not None) != bool(self.username):
            raise ValueError("a registry credential is a username and a password together, never one of them")
        if self.registry and self.password is None:
            raise ValueError(f"a registry ({self.registry!r}) with no username and password authenticates to nothing")
        if not self.host and self.password is None:
            raise ValueError(
                "a docker connection names a daemon, a registry credential, or both, and this names neither"
            )
        return self

    @property
    def secured(self) -> bool:
        """Whether this connection carries client TLS material for a tcp daemon."""
        return self.tls_key is not None

    @property
    def authenticates(self) -> bool:
        """Whether this connection carries a registry credential."""
        return self.password is not None

    @property
    def registry_name(self) -> str:
        """The registry a login addresses, named even where the config left it to the default."""
        return self.registry or DOCKER_HUB


class DockerConnectionKind(ConnectionKind):
    """The connection kind the ``docker.*`` blocks resolve their daemon and registry through."""

    id: ClassVar[str] = "docker"
    config_model: ClassVar[type[BaseModel]] = DockerConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Ask the daemon its version, and log in and out of the registry, for whichever is configured.

        The login is a dry run against a config directory of its own, undone by a logout
        before this returns, so nothing about it persists on the host.
        """
        settings = DockerConnectionConfig.model_validate(config.model_dump())
        binary = shutil.which("docker")
        if binary is None:
            return HealthReport(healthy=False, detail="docker is not on this host's PATH")
        with tempfile.TemporaryDirectory(prefix="dirigent-docker-check-") as home:
            root = Path(home)
            with sealed(settings, root, isolate_config=settings.authenticates) as material:
                environ = daemon_environment(subprocess.environment([], {}, root), material)
                verified: list[str] = []
                for verify in (_verify_daemon, _verify_registry):
                    reached = await verify(binary, root, environ, material, settings)
                    if isinstance(reached, HealthReport):
                        return reached
                    if reached:
                        verified.append(reached)
                return HealthReport(healthy=True, detail=", ".join(verified))


async def _verify_daemon(
    binary: str,
    root: Path,
    environ: dict[str, str],
    material: "Sealed",
    settings: DockerConnectionConfig,
) -> "str | HealthReport":
    """Read the daemon's own version, which is the smallest thing that proves reach and TLS."""
    if not settings.host:
        return ""
    try:
        code, out, err = await subprocess.output(
            argv=[binary, "version", "--format", "{{.Server.Version}}"],
            directory=root,
            environ=environ,
            timeout_seconds=CHECK_TIMEOUT_SECONDS,
            what="docker version",
        )
    except BlockFailure as error:
        return HealthReport(healthy=False, detail=scrub(str(error), material.secrets))
    if code != 0:
        return HealthReport(healthy=False, detail=tail(err, redact=material.secrets) or f"docker exited {code}")
    return f"daemon {out.decode('utf-8', errors='replace').strip()} at {settings.host}"


async def _verify_registry(
    binary: str,
    root: Path,
    environ: dict[str, str],
    material: "Sealed",
    settings: DockerConnectionConfig,
) -> "str | HealthReport":
    """Log in to the registry and out again, leaving the host as it was found."""
    if not settings.authenticates:
        return ""
    try:
        code, err = await login(binary, root, environ, settings)
    except BlockFailure as error:
        return HealthReport(healthy=False, detail=scrub(str(error), material.secrets))
    if code != 0:
        return HealthReport(healthy=False, detail=tail(err, redact=material.secrets) or f"docker login exited {code}")
    await logout(binary, root, environ, settings)
    return f"registry {settings.registry_name} as {settings.username}"


async def login(
    binary: str,
    directory: Path,
    environ: Mapping[str, str],
    settings: DockerConnectionConfig,
) -> tuple[int, bytes]:
    """Sign in to the registry, handing the password over on stdin rather than in an argument."""
    assert settings.password is not None
    argv = [binary, "login", "--username", settings.username, "--password-stdin"]
    if settings.registry:
        argv.append(settings.registry)
    code, _out, err = await subprocess.output(
        argv=argv,
        directory=directory,
        environ=dict(environ),
        timeout_seconds=CHECK_TIMEOUT_SECONDS,
        what="docker login",
        stdin=settings.password.get_secret_value().encode(),
    )
    return code, err


async def logout(binary: str, directory: Path, environ: Mapping[str, str], settings: DockerConnectionConfig) -> None:
    """Sign out again, so the credential does not outlive the step even in a private config directory."""
    argv = [binary, "logout"]
    if settings.registry:
        argv.append(settings.registry)
    with contextlib.suppress(BlockFailure, OSError):
        await subprocess.output(
            argv=argv,
            directory=directory,
            environ=dict(environ),
            timeout_seconds=CHECK_TIMEOUT_SECONDS,
            what="docker logout",
        )


class Sealed(NamedTuple):
    """What a connection became for one invocation: an environment, and the strings never to log."""

    environ: dict[str, str]
    secrets: list[str]


@contextlib.contextmanager
def sealed(settings: DockerConnectionConfig | None, parent: Path, *, isolate_config: bool = False) -> Generator[Sealed]:
    """Materialise a connection's daemon and registry material, and take it away again.

    The TLS triple becomes three 0600 files in a 0700 directory that ``DOCKER_CERT_PATH``
    names, and a login gets a ``DOCKER_CONFIG`` directory of its own beside them. The tree
    goes whether the step succeeded, failed, or was cancelled. Without a connection there is
    nothing to materialise and the worker's own environment stands.
    """
    if settings is None:
        yield Sealed({}, [])
        return
    with secrets.private_directory(parent, "dirigent-docker-") as directory:
        yield _materialise(settings, directory, isolate_config=isolate_config)


def _materialise(settings: DockerConnectionConfig, directory: Path, *, isolate_config: bool) -> Sealed:
    """Write the connection's files and name the environment that points docker at them."""
    environ: dict[str, str] = {}
    hidden: list[str] = []
    if settings.host:
        environ["DOCKER_HOST"] = settings.host
    if settings.tls_key is not None:
        for name, pem in (("ca.pem", settings.tls_ca), ("cert.pem", settings.tls_cert), ("key.pem", settings.tls_key)):
            assert pem is not None
            secrets.write(directory / name, pem.get_secret_value().rstrip("\n") + "\n")
        environ["DOCKER_TLS_VERIFY"] = "1"
        environ["DOCKER_CERT_PATH"] = str(directory)
        hidden.append(settings.tls_key.get_secret_value())
    if isolate_config:
        config = directory / "config"
        config.mkdir(mode=stat.S_IRWXU)
        environ["DOCKER_CONFIG"] = str(config)
    if settings.password is not None:
        hidden.append(settings.password.get_secret_value())
    return Sealed(environ, hidden)


def daemon_environment(base: dict[str, str], material: Sealed) -> dict[str, str]:
    """Overlay a connection's variables on an environment, taking the worker's own daemon out of the way.

    A connection that names a host names the whole daemon, so the worker's ``DOCKER_HOST`` and
    its certificate path go rather than half of each surviving. A connection with only a
    registry credential leaves the worker's daemon exactly as it was.
    """
    kept = {name: value for name, value in base.items() if name not in DAEMON_ENV}
    return {**(kept if "DOCKER_HOST" in material.environ else base), **material.environ}


def private_parent(ctx: StepContext) -> Path:
    """Where a connection's material is written: the run's own work directory."""
    return subprocess.local_root(ctx)


class DockerRunConfig(BlockModel):
    """Which image to run, with what command, environment, mounts, and limits."""

    image: str = Field(min_length=1)
    """The image reference, tag included; ``latest`` is assumed when none is given."""

    argv: list[str] = Field(default_factory=list[str])
    """The command as an argument vector, which replaces the image's ``CMD``."""

    command: Annotated[str | None, ShellString()] = None
    """The command as a shell string, run through ``/bin/sh -c`` inside the container.

    Every ``${...}`` substituted into it is shell-quoted by the engine, so a value that came
    from a webhook payload is one word rather than one program. Prefer ``argv``: it involves
    no shell at all."""

    workdir: str | None = None
    """The working directory inside the container, overriding the image's own."""

    env: dict[str, str] = Field(default_factory=dict[str, str])
    """Variables set explicitly for this container."""

    env_allowlist: list[str] = Field(default_factory=list[str])
    """Worker environment variables this container is allowed to inherit.

    Never the instance's own ``DIRIGENT_*`` variables: those hold this instance's secrets,
    and a container that could inherit them could print the envelope key into the run log."""

    inputs: dict[str, str] = Field(default_factory=dict[str, str])
    """Files to stage into the read-only input mount, as ``name inside the mount -> storage URI``."""

    outputs: dict[str, str] = Field(default_factory=dict[str, str])
    """Files the container writes to the output mount, as ``name inside the mount -> storage URI``."""

    inputs_path: str = "/dirigent/inputs"
    """Where the staged inputs appear inside the container."""

    outputs_path: str = "/dirigent/outputs"
    """Where the container is expected to write its declared outputs."""

    network: str = "none"
    """The daemon's network mode. It defaults to ``none``: an image the pipeline named should
    not reach the worker's network, or anything the worker can reach, unless the step says so."""

    pull: bool = False
    """Pull the image before creating the container, rather than requiring it to be present."""

    memory: Size | None = Field(default=None, ge=MINIMUM_MEMORY)
    """A hard memory limit, such as ``64mb``; the container is OOM-killed rather than the worker."""

    cpus: float | None = Field(default=None, gt=0.0)
    """A CPU quota expressed the way ``docker run --cpus`` expresses it."""

    nano_cpus: int | None = Field(default=None, gt=0)
    """The same quota expressed the way the daemon counts it, for a config that prefers exactness."""

    pids_limit: int | None = Field(default=None, gt=0)
    """A cap on how many processes the container may create."""

    connection: ConnectionRef | None = None
    """A ``docker`` connection naming the daemon this container runs on.

    Absent, the container runs on whatever daemon the worker's own environment names. A
    ``docker.run`` and the ``docker.compose.down`` that tears its stack away should name the
    same connection, so both address the same daemon."""

    socket_path: str | None = None
    """The daemon socket, when neither the default nor ``DOCKER_HOST`` is right."""

    api_timeout: Duration = Field(default=timedelta(seconds=60), gt=timedelta(0))
    """How long one call to the daemon may take. This is not the container's runtime: the
    container runs under the step's deadline, which the engine owns and this block never waits on."""

    pull_timeout: Duration = Field(default=timedelta(minutes=10), gt=timedelta(0))
    """How long a pull may take, which is a different order of magnitude from an API call."""

    @model_validator(mode="after")
    def _check_shape(self) -> "DockerRunConfig":
        """Reject a config that names two commands, two CPU quotas, or a mount that climbs out."""
        if self.argv and self.command is not None:
            raise ValueError(
                "docker.run takes either argv or command, and never both; omit both to run the image's own entrypoint"
            )
        if self.cpus is not None and self.nano_cpus is not None:
            raise ValueError("docker.run takes either cpus or nano_cpus, and never both")
        if self.connection is not None and self.socket_path is not None:
            raise ValueError("a connection names the daemon, so docker.run takes either connection or socket_path")
        for name in (*self.inputs, *self.outputs):
            if not name or Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("a mounted file is named inside its mount, so it cannot be absolute or climb out")
        reject_reserved(self.env_allowlist)
        return self


class DockerRunOutput(BlockModel):
    """What the container did, with its full streams and produced files addressable as artifacts."""

    exit_code: int

    stdout: str
    """The head of what the container printed, cut at the instance's inline capture size.

    Verbatim, including the trailing newline a command like ``echo`` ends with."""

    stderr: str
    """The head of what the container printed to stderr, cut the same way."""

    stdout_uri: str
    """Where the whole of stdout was written; never truncated, whatever the field above holds."""

    stderr_uri: str
    """Where the whole of stderr was written; never truncated either."""

    stdout_bytes: int
    """How much the container printed to stdout altogether, inlined or not."""

    stderr_bytes: int
    """How much it printed to stderr altogether."""

    stdout_truncated: bool
    """Whether ``stdout`` above is short of the stream. Only the inline copy is ever cut."""

    stderr_truncated: bool
    """Whether ``stderr`` above is short of the stream, which is an independent question."""

    container_id: str
    image: str
    outputs: dict[str, str] = Field(default_factory=dict[str, str])
    """Where each declared output was written, by the name the config gave it."""


class DockerRunOperator(Operator[DockerRunConfig, DockerRunOutput]):
    """Starts a container on the worker and lets the engine probe it, behind the allowlist."""

    spec = OperatorSpec(
        id="docker.run",
        group="execute",
        summary="Run a container on the worker.",
        idempotent=False,
        local_execution=True,
        default_poll=CONTAINER_POLL,
    )
    config_model: ClassVar[type[BaseModel]] = DockerRunConfig
    output_model: ClassVar[type[BaseModel]] = DockerRunOutput

    async def execute(self, config: DockerRunConfig, ctx: StepContext) -> DockerRunOutput | RemoteHandle:
        """Stage the inputs, create the container, start it, and hand back the claim on it."""
        mounts = _mounts(config, ctx)
        with _material(config, ctx) as environ:
            async with _daemon(config, environ) as daemon:
                if config.pull:
                    await daemon.pull(config.image, config.pull_timeout.total_seconds())
                await _stage_inputs(config, ctx, mounts)
                container = await daemon.create(_creation(config, ctx, mounts))
                await daemon.start(container)
        ctx.log.info("container started", container_id=container[:12], image=config.image, network=config.network)
        meta = {"image": config.image}
        if mounts.outputs is not None:
            meta["outputs_dir"] = str(mounts.outputs)
        return RemoteHandle(block_id=self.spec.id, ref=container, meta=meta)

    async def probe(self, handle: RemoteHandle, config: DockerRunConfig, ctx: StepContext) -> ProbeResult:
        """Ask the daemon what the container is doing, and map its vocabulary onto a probe status."""
        with _material(config, ctx) as environ:
            async with _daemon(config, environ) as daemon:
                inspected = await daemon.inspect(handle.ref)
                if inspected is None:
                    return ProbeResult(
                        status=ProbeStatus.GONE,
                        message=f"the daemon no longer knows container {handle.ref[:12]}",
                    )
                state = inspected.state
                if state.running or state.status in UNFINISHED_STATES:
                    advanced = await _stream_since(daemon, handle, ctx)
                    return ProbeResult(status=ProbeStatus.RUNNING, message=state.status or "running", meta=advanced)
                if state.exit_code == 0:
                    return ProbeResult(status=ProbeStatus.SUCCEEDED, message=state.status or "exited")
                stdout, stderr = await drain_logs(daemon, handle.ref, ctx.inline_capture)
                # A failed container settles here, and fetch is only ever called after a
                # successful probe, so this is the last chance to take it off the worker.
                await _discard(daemon, handle, ctx)
        detail = tail(stderr.tail) or tail(stdout.tail) or state.error or "no output"
        return ProbeResult(status=ProbeStatus.FAILED, message=f"the container exited {state.exit_code}: {detail}")

    async def fetch(self, handle: RemoteHandle, config: DockerRunConfig, ctx: StepContext) -> DockerRunOutput:
        """Collect the exit code, the streams, and the declared files, then drop the container."""
        artifacts = subprocess.prefix(ctx, "docker")
        stdout_uri = f"{artifacts}-stdout.txt"
        stderr_uri = f"{artifacts}-stderr.txt"
        with _material(config, ctx) as environ:
            async with _daemon(config, environ) as daemon:
                inspected = await daemon.inspect(handle.ref)
                if inspected is None:
                    raise BlockFailure(
                        f"container {handle.ref[:12]} disappeared before its result could be collected",
                        error_class=ErrorClass.TRANSIENT,
                    )
                async with (
                    ctx.storage.open_write(stdout_uri) as out_sink,
                    ctx.storage.open_write(stderr_uri) as err_sink,
                ):
                    stdout, stderr = await drain_logs(
                        daemon, handle.ref, ctx.inline_capture, sinks=(out_sink, err_sink)
                    )
                collected = await _collect_outputs(config, handle, ctx)
                # The run log gets only what the probes have not already streamed: the segment
                # between the last committed cursor and the exit. The full read above is for
                # storage and the output, not for saying every line a second time.
                fresh_out, fresh_err = await drain_logs(
                    daemon, handle.ref, ctx.inline_capture, since=handle.meta.get(LOGS_SINCE, "")
                )
                await _discard(daemon, handle, ctx)

        log_stream(ctx, "stdout", fresh_out)
        log_stream(ctx, "stderr", fresh_err)
        ctx.log.info(
            "container finished",
            container_id=handle.ref[:12],
            exit_code=inspected.state.exit_code,
            stdout_bytes=stdout.total_bytes,
            stderr_bytes=stderr.total_bytes,
        )
        printed = stdout.captured(ctx.inline_capture)
        failed = stderr.captured(ctx.inline_capture)
        return DockerRunOutput(
            exit_code=inspected.state.exit_code,
            stdout=printed.text,
            stderr=failed.text,
            stdout_uri=stdout_uri,
            stderr_uri=stderr_uri,
            stdout_bytes=printed.total_bytes,
            stderr_bytes=failed.total_bytes,
            stdout_truncated=printed.truncated,
            stderr_truncated=failed.truncated,
            container_id=handle.ref,
            image=handle.meta.get("image", config.image),
            outputs=collected,
        )

    async def cancel(self, handle: RemoteHandle, config: DockerRunConfig, ctx: StepContext) -> bool:
        """Kill the container. A container that has already stopped is cancelled; one that is gone is not."""
        try:
            with _material(config, ctx) as environ:
                async with _daemon(config, environ) as daemon:
                    killed = await daemon.kill(handle.ref)
                    await _discard(daemon, handle, ctx)
        except (httpx2.HTTPError, OSError, BlockFailure) as error:
            ctx.log.warning("the daemon could not be told to kill the container", error=str(error))
            return False
        ctx.log.info(
            "container cancelled" if killed else "the container was already gone", container_id=handle.ref[:12]
        )
        return killed

    def classify_error(self, error: Exception) -> ErrorClass:
        """A daemon that cannot be reached is transient; everything else keeps the default reading."""
        if isinstance(error, OSError):
            return ErrorClass.TRANSIENT
        return classify_default(error)


async def _discard(daemon: "DockerDaemon", handle: RemoteHandle, ctx: StepContext) -> None:
    """Take a settled container off the worker.

    Every terminal path removes: a container that failed, one that was cancelled, and one
    whose result was collected. A removal that does not work is logged and swallowed,
    because the result is already in hand by the time this runs and must not be lost to a
    container that would not delete.
    """
    try:
        await daemon.remove(handle.ref)
    except (httpx2.HTTPError, OSError) as error:
        ctx.log.warning("the container could not be removed", container_id=handle.ref[:12], error=str(error))


# -- the container's creation ----------------------------------------------------


class Mounts(BaseModel):
    """The local directories backing this attempt's mounts, when it asked for any."""

    inputs: Path | None = None
    outputs: Path | None = None

    def binds(self, config: DockerRunConfig) -> list[JsonValue]:
        """Render the mounts the way the daemon's ``HostConfig.Binds`` wants them."""
        binds: list[JsonValue] = []
        if self.inputs is not None:
            binds.append(f"{self.inputs}:{config.inputs_path}:ro")
        if self.outputs is not None:
            binds.append(f"{self.outputs}:{config.outputs_path}:rw")
        return binds


def _mounts(config: DockerRunConfig, ctx: StepContext) -> Mounts:
    """Place this attempt's mounts inside the run's work directory, which a bind needs to be local."""
    if not config.inputs and not config.outputs:
        return Mounts()
    workspace = subprocess.local_root(ctx) / subprocess.segment(ctx, "docker")
    mounts = Mounts(
        inputs=workspace / "inputs" if config.inputs else None,
        outputs=workspace / "outputs" if config.outputs else None,
    )
    for directory in (mounts.inputs, mounts.outputs):
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
    return mounts


def _creation(config: DockerRunConfig, ctx: StepContext, mounts: Mounts) -> dict[str, JsonValue]:
    """Build the ``/containers/create`` body: the command, the environment, and the containment."""
    host: dict[str, JsonValue] = {
        "NetworkMode": config.network,
        "Binds": mounts.binds(config),
        "AutoRemove": False,
        "Memory": config.memory or 0,
        "NanoCpus": _nano_cpus(config) or 0,
    }
    if config.pids_limit is not None:
        host["PidsLimit"] = config.pids_limit
    payload: dict[str, JsonValue] = {
        "Image": config.image,
        "Env": _environment(config),
        "Tty": False,
        "Labels": {"dirigent.run": str(ctx.run_id), "dirigent.attempt": str(ctx.attempt)},
        "HostConfig": host,
    }
    command = _command(config)
    if command is not None:
        payload["Cmd"] = command
    if config.workdir is not None:
        payload["WorkingDir"] = config.workdir
    return payload


def _command(config: DockerRunConfig) -> list[JsonValue] | None:
    """Resolve the command: the argument vector, the shell form, or the image's own entrypoint."""
    if config.argv:
        return list(config.argv)
    if config.command is not None:
        return [*SHELL_ARGV, config.command]
    return None


def _environment(config: DockerRunConfig) -> list[JsonValue]:
    """Build the container's environment from an allowlist, never from wholesale inheritance."""
    inherited = allowed(config.env_allowlist)
    return [f"{name}={value}" for name, value in {**inherited, **config.env}.items()]


def _nano_cpus(config: DockerRunConfig) -> int | None:
    """Express whichever CPU quota the config gave the way the daemon counts them."""
    if config.nano_cpus is not None:
        return config.nano_cpus
    if config.cpus is not None:
        return round(config.cpus * NANO_CPUS_PER_CPU)
    return None


# -- data across the boundary ----------------------------------------------------


async def _stage_inputs(config: DockerRunConfig, ctx: StepContext, mounts: Mounts) -> None:
    """Stream every declared input into the directory that becomes the read-only mount."""
    if mounts.inputs is None:
        return
    for name, uri in config.inputs.items():
        target = mounts.inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            async for chunk in ctx.storage.open_read(uri):
                handle.write(chunk)
        ctx.log.debug("input staged", name=name, uri=uri)


async def _collect_outputs(config: DockerRunConfig, handle: RemoteHandle, ctx: StepContext) -> dict[str, str]:
    """Move every declared output back into storage, so it outlives the container that wrote it."""
    if not config.outputs:
        return {}
    directory = Path(handle.meta["outputs_dir"])
    collected: dict[str, str] = {}
    for name, uri in config.outputs.items():
        produced = directory / name
        if not produced.is_file():
            raise BlockFailure(
                f"the container did not write the declared output {name!r} to {config.outputs_path}",
                error_class=ErrorClass.REJECTED,
            )
        written = 0
        with produced.open("rb") as source:
            async with ctx.storage.open_write(uri) as sink:
                while chunk := source.read(COPY_CHUNK_BYTES):
                    written += await sink.write(chunk)
        ctx.log.info("output collected", name=name, uri=uri, bytes_written=written)
        collected[name] = uri
    return collected


async def _stream_since(daemon: "DockerDaemon", handle: RemoteHandle, ctx: StepContext) -> dict[str, str]:
    """Put what the container printed since the last probe into the run, and advance the cursor.

    The cursor is a reading of the daemon's clock, which is this worker's: the container runs
    here. It is taken before the read, so a line printed during the read is read again rather
    than skipped, and a probe whose outcome never committed is read from again. Only the ends
    of each stream are kept, so a chatty container cannot flood the run. This is the live view
    of a stream still being written, and it may repeat a line or never reach the ones printed
    between the last probe and the container exiting; fetch stores the whole of both streams.
    """
    reached = f"{time.time():.9f}"
    stdout, stderr = await drain_logs(daemon, handle.ref, ctx.inline_capture, since=handle.meta.get(LOGS_SINCE, ""))
    log_stream(ctx, "stdout", stdout)
    log_stream(ctx, "stderr", stderr)
    return {**handle.meta, LOGS_SINCE: reached}


async def drain_logs(
    daemon: "DockerDaemon",
    container: str,
    head_limit: int,
    sinks: "tuple[ByteSink, ByteSink] | None" = None,
    since: str = "",
) -> tuple[Drained, Drained]:
    """Read a container's logs as they arrive, keeping both ends of each stream.

    With sinks, each stream is written through to storage as it is split, so a container that
    printed more than the worker can hold is a file. Without them, only the ends are kept,
    which is all a failure message needs. A ``since`` reads only what was printed after that
    timestamp, which is what a probe following a running container asks for.
    """
    frames = Frames()
    out, err = Ends(head_limit), Ends(head_limit)
    async with daemon.streamed_logs(container, since) as stream:
        async for chunk in stream:
            for is_stderr, body in frames.take(chunk):
                ends = err if is_stderr else out
                ends.add(body)
                if sinks is not None:
                    await sinks[1 if is_stderr else 0].write(body)
        for is_stderr, body in frames.rest():
            ends = err if is_stderr else out
            ends.add(body)
            if sinks is not None:
                await sinks[1 if is_stderr else 0].write(body)
    return out.drained(), err.drained()


class Frames:
    """Docker's framed log stream, split as it arrives rather than once it has all arrived.

    A frame is an eight-byte header -- a stream type byte, three zero bytes, then a big-endian
    length -- and that many payload bytes. A chunk off the wire is not a frame, so what is
    held is the part of one that has arrived and no more.
    """

    def __init__(self) -> None:
        """Start with nothing buffered."""
        self._buffer = bytearray()

    def take(self, chunk: bytes) -> list[tuple[bool, bytes]]:
        """Take one chunk and return the frames it completed, each as (is_stderr, body)."""
        self._buffer.extend(chunk)
        found: list[tuple[bool, bytes]] = []
        while len(self._buffer) >= STREAM_HEADER_BYTES:
            length = int.from_bytes(self._buffer[4:STREAM_HEADER_BYTES], "big")
            end = STREAM_HEADER_BYTES + length
            if len(self._buffer) < end:
                break
            found.append((self._buffer[0] == STDERR_FRAME, bytes(self._buffer[STREAM_HEADER_BYTES:end])))
            del self._buffer[:end]
        return found

    def rest(self) -> list[tuple[bool, bytes]]:
        """Return what a stream cut short left, which still carries the lines that explain why."""
        if len(self._buffer) <= STREAM_HEADER_BYTES:
            return []
        body = bytes(self._buffer[STREAM_HEADER_BYTES:])
        stderr = self._buffer[0] == STDERR_FRAME
        self._buffer.clear()
        return [(stderr, body)]


def demultiplex(payload: bytes) -> tuple[bytes, bytes]:
    """Split Docker's framed log stream into the container's stdout and stderr.

    A container created without a TTY has its output multiplexed onto one connection: each
    frame is an eight-byte header -- a stream type byte, three zero bytes, then a big-endian
    length -- followed by that many payload bytes. Anything that is not stderr counts as
    stdout, and a truncated final frame contributes whatever arrived, because a stream cut
    short still carries the lines that explain why.
    """
    stdout: list[bytes] = []
    stderr: list[bytes] = []
    offset = 0
    while offset + STREAM_HEADER_BYTES <= len(payload):
        header = payload[offset : offset + STREAM_HEADER_BYTES]
        length = int.from_bytes(header[4:STREAM_HEADER_BYTES], "big")
        body = payload[offset + STREAM_HEADER_BYTES : offset + STREAM_HEADER_BYTES + length]
        (stderr if header[0] == STDERR_FRAME else stdout).append(body)
        if len(body) < length:
            break
        offset += STREAM_HEADER_BYTES + length
    return b"".join(stdout), b"".join(stderr)


# -- the daemon ------------------------------------------------------------------


class ContainerHealth(BaseModel):
    """A container's healthcheck verdict, when it declares one."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    status: str = Field(default="", alias="Status")


class ContainerState(BaseModel):
    """The part of a container's state the block reads, named the way the daemon names it."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    status: str = Field(default="", alias="Status")
    running: bool = Field(default=False, alias="Running")
    exit_code: int = Field(default=0, alias="ExitCode")
    error: str = Field(default="", alias="Error")
    oom_killed: bool = Field(default=False, alias="OOMKilled")
    health: ContainerHealth = Field(default_factory=ContainerHealth, alias="Health")


class ContainerConfig(BaseModel):
    """The part of a container's ``Config`` the compose status read names it and its service by."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    image: str = Field(default="", alias="Image")
    labels: dict[str, str] = Field(default_factory=dict[str, str], alias="Labels")


class PortBinding(BaseModel):
    """One host binding of a container port, as ``NetworkSettings.Ports`` maps it."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    host_ip: str = Field(default="", alias="HostIp")
    host_port: str = Field(default="", alias="HostPort")


class NetworkSettings(BaseModel):
    """The part of ``NetworkSettings`` the compose status read draws ports and networks from."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ports: dict[str, list[PortBinding] | None] = Field(
        default_factory=dict[str, "list[PortBinding] | None"], alias="Ports"
    )
    networks: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue], alias="Networks")


class ContainerInspect(BaseModel):
    """The part of ``/containers/{id}/json`` the blocks read."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(default="", alias="Id")
    name: str = Field(default="", alias="Name")
    state: ContainerState = Field(default_factory=ContainerState, alias="State")
    config: ContainerConfig = Field(default_factory=ContainerConfig, alias="Config")
    network_settings: NetworkSettings = Field(default_factory=NetworkSettings, alias="NetworkSettings")


class ListedContainer(BaseModel):
    """The part of ``/containers/json`` a listing reads: when it was created, and its labels."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(default="", alias="Id")
    created: int = Field(default=0, alias="Created")
    """The unix second the container was created at, which is the daemon's clock."""

    labels: dict[str, str] = Field(default_factory=dict[str, str], alias="Labels")


class CreatedContainer(BaseModel):
    """What the daemon answers when it has created a container."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(alias="Id")
    warnings: list[str] = Field(default_factory=list[str], alias="Warnings")


class DockerDaemon:
    """The slice of the Docker Engine API this block speaks."""

    def __init__(self, client: httpx2.AsyncClient, socket: str | None = None) -> None:
        """Bind to an already-built client, so a caller can supply its own."""
        self.client = client
        self.socket = socket

    async def __aenter__(self) -> "DockerDaemon":
        """Enter the client's lifetime."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the connection to the socket, naming the daemon a connect error hides.

        `ConnectError: [Errno 2] No such file or directory` is the whole of what httpx says
        about a socket that is not there, which is exactly what a worker in a container sees:
        it has no daemon of its own, and mounting the host's socket into it hands the
        container root on the host. The sentence a run shows has to say that.
        """
        await self.client.aclose()
        if isinstance(exc, httpx2.ConnectError) and self.socket is not None:
            cause = exc.__cause__ if isinstance(exc.__cause__, OSError) else None
            missing = cause is not None and cause.errno == errno.ENOENT
            raise BlockFailure(
                f"the Docker daemon at {self.socket} did not answer ({exc}); a worker in a "
                f"container has no daemon unless the host's socket is mounted into it, and "
                f"mounting it grants the container root on the host",
                error_class=ErrorClass.REJECTED if missing else ErrorClass.TRANSIENT,
            ) from exc

    async def pull(self, image: str, timeout: float) -> None:
        """Pull an image, reading the progress stream to completion so the pull actually finishes."""
        repository, tag = split_image(image)
        response = await self.client.post(
            "/images/create",
            params={"fromImage": repository, "tag": tag},
            timeout=timeout,
        )
        _require_ok(response, f"pull {image}")

    async def create(self, payload: dict[str, JsonValue]) -> str:
        """Create a container and return its id."""
        response = await self.client.post("/containers/create", json=payload)
        _require_ok(response, "create the container")
        return CreatedContainer.model_validate(response.json()).id

    async def start(self, container: str) -> None:
        """Start a created container, detached."""
        response = await self.client.post(f"/containers/{container}/start")
        if response.status_code == NOT_MODIFIED:
            return
        _require_ok(response, "start the container")

    async def inspect(self, container: str) -> ContainerInspect | None:
        """Describe a container, or report that the daemon no longer knows it."""
        response = await self.client.get(f"/containers/{container}/json")
        if response.status_code == NOT_FOUND:
            return None
        _require_ok(response, "inspect the container")
        return ContainerInspect.model_validate(response.json())

    async def list_containers(self, filters: dict[str, list[str]]) -> list[str]:
        """List the ids of every container matching a filter, stopped ones included.

        Compose labels each of a project's containers with
        ``com.docker.compose.project``, so a label filter is how the status read finds a
        stack's containers without the CLI.
        """
        response = await self.client.get("/containers/json", params={"all": "1", "filters": json.dumps(filters)})
        _require_ok(response, "list the project's containers")
        listed = cast("list[dict[str, JsonValue]]", response.json())
        return [str(item["Id"]) for item in listed if item.get("Id")]

    async def list_labelled(self, filters: dict[str, list[str]]) -> list[ListedContainer]:
        """List every container matching a filter with its labels and its creation time.

        The reaper groups these by compose project, which is a label, and ages each project by
        the newest container in it.
        """
        response = await self.client.get("/containers/json", params={"all": "1", "filters": json.dumps(filters)})
        _require_ok(response, "list the daemon's containers")
        return [ListedContainer.model_validate(item) for item in cast("list[JsonValue]", response.json())]

    @asynccontextmanager
    async def streamed_logs(self, container: str, since: str = "") -> AsyncGenerator[AsyncIterator[bytes]]:
        """Hand over the container's log stream in pieces, framed as the daemon sends it.

        A container that printed more than the worker can hold is still a container whose
        output belongs in storage, so nothing here reads it whole. A ``since`` -- a unix
        timestamp -- narrows the read to what was printed after it.
        """
        params = {"stdout": "1", "stderr": "1", "tail": "all"}
        if since:
            params["since"] = since
        request = self.client.build_request("GET", f"/containers/{container}/logs", params=params)
        response = await self.client.send(request, stream=True)
        try:
            if response.status_code == NOT_FOUND:
                yield _nothing()
                return
            _require_ok(response, "read the container's logs")
            yield response.aiter_bytes()
        finally:
            await response.aclose()

    async def kill(self, container: str) -> bool:
        """Kill a container; a container that has already stopped counts as killed, a missing one does not."""
        response = await self.client.post(f"/containers/{container}/kill")
        if response.status_code == NOT_FOUND:
            return False
        if response.status_code == CONFLICT:
            return True
        _require_ok(response, "kill the container")
        return True

    async def remove(self, container: str) -> None:
        """Remove a container and its anonymous volumes, best effort.

        The status is deliberately not checked: the result has already been collected by the
        time this runs, and a result must not be lost to a container that would not delete.
        """
        await self.client.delete(f"/containers/{container}", params={"v": "1", "force": "1"})


class DaemonEndpoint(NamedTuple):
    """Where the daemon is and how to speak to it, resolved from the config and the environment.

    A ``uds`` names a local unix socket the client speaks plain HTTP over; otherwise ``base_url``
    is a ``tcp://`` daemon reached as ``http(s)://host:port``, with ``verify`` and ``cert``
    carrying the TLS material when the environment asks for it. ``socket`` is the unix path a
    connect error names, and is ``None`` for a tcp daemon.
    """

    base_url: str
    uds: str | None
    verify: bool | str
    cert: tuple[str, str] | None
    socket: str | None


def resolve_endpoint(explicit_socket: str | None, environ: Mapping[str, str] | None = None) -> DaemonEndpoint:
    """Resolve the daemon: an explicit socket, then ``DOCKER_HOST`` (unix or tcp+TLS), else the default.

    A ``tcp://`` ``DOCKER_HOST`` points the worker at a daemon of its own -- a docker-in-docker
    sidecar, say -- rather than the host's socket, which is the deployment that keeps a
    pipeline's containers off the host. ``DOCKER_TLS_VERIFY`` with ``DOCKER_CERT_PATH`` turns
    that into https with client certificates, the way the docker CLI reads the same variables.

    ``environ`` is what a step with a ``docker`` connection reads instead of the worker's own.
    """
    source = os.environ if environ is None else environ
    if explicit_socket:
        return DaemonEndpoint(DAEMON_BASE_URL, explicit_socket, True, None, explicit_socket)
    host = source.get("DOCKER_HOST", "")
    if host.startswith("tcp://"):
        secure = source.get("DOCKER_TLS_VERIFY", "") not in ("", "0")
        authority = host.removeprefix("tcp://")
        base_url = f"{'https' if secure else 'http'}://{authority}"
        verify: bool | str = True
        cert: tuple[str, str] | None = None
        cert_path = source.get("DOCKER_CERT_PATH", "")
        if secure and cert_path:
            verify = str(Path(cert_path) / "ca.pem")
            cert = (str(Path(cert_path) / "cert.pem"), str(Path(cert_path) / "key.pem"))
        return DaemonEndpoint(base_url, None, verify, cert, None)
    if host.startswith("unix://"):
        socket = host.removeprefix("unix://") or DEFAULT_SOCKET_PATH
        return DaemonEndpoint(DAEMON_BASE_URL, socket, True, None, socket)
    return DaemonEndpoint(DAEMON_BASE_URL, DEFAULT_SOCKET_PATH, True, None, DEFAULT_SOCKET_PATH)


def socket_path(config: DockerRunConfig) -> str:
    """The unix socket a real-daemon check looks for; the default stands in for a tcp daemon."""
    return resolve_endpoint(config.socket_path).uds or DEFAULT_SOCKET_PATH


def open_client(endpoint: DaemonEndpoint, timeout: float) -> httpx2.AsyncClient:
    """Open a client onto a resolved endpoint: the unix socket, or the tcp daemon with its TLS."""
    if endpoint.uds is not None:
        return httpx2.AsyncClient(
            base_url=endpoint.base_url,
            transport=httpx2.AsyncHTTPTransport(uds=endpoint.uds),
            timeout=timeout,
        )
    return httpx2.AsyncClient(base_url=endpoint.base_url, verify=_tls(endpoint), timeout=timeout)


def _tls(endpoint: DaemonEndpoint) -> ssl.SSLContext | bool | str:
    """Fold the CA and the client chain into one context, which is how httpx2 takes a client certificate."""
    if endpoint.cert is None or not isinstance(endpoint.verify, str):
        return endpoint.verify
    context = ssl.create_default_context(cafile=endpoint.verify)
    context.load_cert_chain(*endpoint.cert)
    return context


def connect(config: DockerRunConfig, environ: Mapping[str, str] | None = None) -> httpx2.AsyncClient:
    """Open a client onto the daemon this config resolves to."""
    return open_client(resolve_endpoint(config.socket_path, environ), config.api_timeout.total_seconds())


def split_image(image: str) -> tuple[str, str]:
    """Split an image reference into its repository and tag, defaulting to ``latest``."""
    repository, separator, tag = image.rpartition(":")
    if separator and "/" not in tag:
        return repository, tag
    return image, "latest"


async def _nothing() -> AsyncIterator[bytes]:
    """An empty stream, for a container the daemon no longer knows."""
    return
    yield b""  # pragma: no cover - unreachable, and what makes this a generator


def _daemon(config: DockerRunConfig, environ: Mapping[str, str] | None = None) -> DockerDaemon:
    """Build the daemon facade one call uses."""
    return DockerDaemon(connect(config, environ), resolve_endpoint(config.socket_path, environ).socket)


@contextlib.contextmanager
def _material(config: DockerRunConfig, ctx: StepContext) -> Generator[dict[str, str]]:
    """Resolve the step's connection into an environment, and take its files away afterwards.

    Every entry point does this for itself -- execute, probe, fetch and cancel are four calls
    with nothing shared between them -- so a client key is on the worker's filesystem only for
    the length of one call, whichever way that call leaves.
    """
    settings = ctx.connection(config.connection, DockerConnectionConfig) if config.connection else None
    with sealed(settings, private_parent(ctx)) as sealed_material:
        yield daemon_environment(dict(os.environ), sealed_material)


def _require_ok(response: httpx2.Response, action: str) -> None:
    """Turn a daemon error into a classified block failure, carrying the message it gave."""
    if response.status_code < BAD_REQUEST:
        return
    raise BlockFailure(
        f"the daemon refused to {action}: {_daemon_message(response)}",
        error_class=status_class(response.status_code),
    )


def _daemon_message(response: httpx2.Response) -> str:
    """Read the daemon's own explanation, which it puts in a JSON ``message`` field."""
    body: object = None
    with contextlib.suppress(ValueError):
        body = response.json()
    if isinstance(body, dict):
        message = cast("dict[str, object]", body).get("message")
        if isinstance(message, str):
            return message
    return response.text[:ERROR_DETAIL_CHARS].strip() or f"HTTP {response.status_code}"
