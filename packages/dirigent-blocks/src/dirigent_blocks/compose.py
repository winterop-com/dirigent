"""``docker.compose.up`` / ``docker.compose.down``: run a whole compose stack for a run.

The pair is a hybrid. Compose has no Engine HTTP API, so both blocks shell out to the
``docker compose`` CLI -- only the CLI can orchestrate a stack. The state ``up`` reports,
though, comes from the Engine HTTP API the same way ``docker.run`` reads a container: compose
labels every container ``com.docker.compose.project=<project>``, so the block lists the
project's containers by that label and inspects each into a structured ``ComposeService`` --
state, health, published ports and the network a later step joins -- rather than parsing CLI
text.

Reaching the Docker daemon is reaching root on the host when the daemon is the host's own, so
both blocks declare ``local_execution`` and the engine refuses them unless the instance
allowlists their ids. The daemon is whatever ``DOCKER_HOST`` names, or the one a ``docker``
connection names where the step carries one; a worker with its own daemon keeps a pipeline's
containers off the host. A stack exists only on the daemon that created it, so the ``up``, the
steps that drive it and the ``down`` all have to name the same one.

The lifecycle is two steps. ``docker.compose.up`` brings a stack up detached and it
**persists** for the run, so later steps drive it; a separate ``docker.compose.down`` step
with ``rule: all_done`` tears it down whether the drive step passed or failed. Both default
their project name deterministically from the run id, so the ``down`` addresses the same
project the ``up`` created with no wiring from the author. A bring-up that does not succeed --
a non-zero exit, a timeout, a cancelled step -- is the one case a block cleans up itself,
because a half-built stack should never be left behind.
"""

import asyncio
import contextlib
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import ClassVar, Literal

import httpx2
from pydantic import BaseModel, Field, model_validator

from dirigent_blocks import subprocess
from dirigent_blocks.capture import log_stream, tail
from dirigent_blocks.docker import (
    DAEMON_ENV,
    ContainerInspect,
    DockerConnectionConfig,
    DockerDaemon,
    daemon_environment,
    open_client,
    resolve_endpoint,
    sealed,
    write_cli_config,
)
from dirigent_blocks.environment import reject_reserved
from dirigent_common import BlockModel, Duration
from dirigent_plugin import (
    BlockFailure,
    ConnectionRef,
    ErrorClass,
    Operator,
    OperatorSpec,
    RemoteHandle,
    StepContext,
)

#: The label compose stamps on every container of a project, which is how the status read finds them.
PROJECT_LABEL = "com.docker.compose.project"

#: The label carrying a container's service name in the compose file.
SERVICE_LABEL = "com.docker.compose.service"

#: The deadline on the teardown of a bring-up that failed or was abandoned, so a step that has
#: already lost its own deadline, or been cancelled, cannot hang on the cleanup.
CLEANUP_TIMEOUT_SECONDS = 120.0

#: What a daemon that is not there or not ours says, a transient condition rather than a fault
#: in the stack: a worker has no daemon of its own unless the deployment gives it one.
DAEMON_UNREACHABLE = ("cannot connect to the docker daemon", "is the docker daemon running", "permission denied")


class ComposePublisher(BlockModel):
    """One host port a service published."""

    url: str = ""
    """The address the port was bound on, often ``0.0.0.0`` or a specific host."""

    target_port: int = 0
    """The port inside the container."""

    published_port: int = 0
    """The port on the host it was mapped to."""

    protocol: str = ""
    """``tcp`` or ``udp``."""


class ComposeService(BlockModel):
    """One service's container, as the Engine API reports it."""

    name: str
    """The container's name, which is what the daemon knows it by."""

    service: str
    """The service's name in the compose file."""

    image: str = ""
    """The image the container runs."""

    state: str = ""
    """The container's state: ``running``, ``exited``, and so on."""

    health: str = ""
    """The healthcheck's verdict when the service declares one, else empty."""

    exit_code: int = 0
    """The container's exit code, meaningful once it has stopped."""

    publishers: list[ComposePublisher] = Field(default_factory=list[ComposePublisher])
    """The host ports the service published, if any."""


# -- shared configuration --------------------------------------------------------


class DockerComposeUpConfig(BlockModel):
    """Which compose file to bring up, under what project, with which flags."""

    file: str | None = None
    """The compose file, as a path inside the run's work directory; never absolute, never climbing out.

    Exactly one of ``file`` or ``content`` is given. This form is for a file an upstream step
    produced, such as a ``git.checkout`` of the document's repository."""

    content: str | None = None
    """The compose file inline, written into the run's work directory before the CLI runs.

    Exactly one of ``file`` or ``content`` is given. This form keeps a small stack in the
    pipeline document itself."""

    project_name: str | None = None
    """The compose project (``-p``). Defaults to a deterministic name derived from the run id,

    so this ``up``, the steps that drive it, and a later ``down`` all address the same project,
    and two runs never collide."""

    profiles: list[str] = Field(default_factory=list[str])
    """Compose profiles to activate (``--profile``)."""

    env_files: list[str] = Field(default_factory=list[str])
    """Env files for compose to read, as paths inside the run's work directory (``--env-file``)."""

    env: dict[str, str] = Field(default_factory=dict[str, str])
    """Variables set for the CLI itself, such as those a compose file interpolates."""

    env_allowlist: list[str] = Field(default_factory=list[str])
    """Worker environment variables the CLI is allowed to inherit.

    Never the instance's own ``DIRIGENT_*`` variables: those hold this instance's secrets."""

    wait: bool = False
    """Wait until every service is running and healthy before the step returns (``--wait``)."""

    wait_timeout: Duration = timedelta(seconds=300)
    """How long ``--wait`` may wait before it gives up."""

    remove_orphans: bool = True
    """Remove containers for services no longer in the compose file (``--remove-orphans``)."""

    pull: Literal["always", "missing", "never"] = "missing"
    """When to pull images: ``missing`` pulls only what is absent, the compose default."""

    cleanup: bool = True
    """On a bring-up that does not succeed, best-effort ``down`` the same project before leaving.

    A non-zero exit, a timeout and a cancelled step all leave containers compose had already
    started. This never tears down a *successful* ``up`` -- that persists for the run by
    design."""

    command_path: list[str] = Field(default_factory=lambda: ["docker", "compose"])
    """The CLI to invoke, for a host that spells it ``docker-compose`` or wraps it."""

    connection: ConnectionRef | None = None
    """A ``docker`` connection naming the daemon this stack runs on.

    Absent, the stack runs on whatever daemon the worker's own environment names. The ``up``,
    the steps that drive it and the ``down`` should all name the same connection, because a
    stack only exists on the daemon that was told to create it."""

    socket_path: str | None = None
    """The daemon socket the status read speaks to, when neither the default nor ``DOCKER_HOST`` is right."""

    api_timeout: Duration = Field(default=timedelta(seconds=60), gt=timedelta(0))
    """How long one call to the daemon for the status read may take."""

    timeout: Duration = timedelta(minutes=10)
    """The overall deadline on the CLI invocation, after which it is killed as transient."""

    @model_validator(mode="after")
    def _check_shape(self) -> "DockerComposeUpConfig":
        """Reject a config that names both compose-file forms or neither, or a path that climbs out."""
        if bool(self.file) == bool(self.content):
            raise ValueError("docker.compose.up takes either file or content, and exactly one of them")
        _reject_escaping((self.file, *self.env_files))
        reject_reserved(self.env_allowlist)
        return self


class DockerComposeDownConfig(BlockModel):
    """Which project to tear down, and how thoroughly."""

    project_name: str | None = None
    """The compose project (``-p``). Defaults to the same deterministic name ``up`` derives from

    the run id, so a teardown step in the same run addresses the stack the ``up`` created with
    no wiring from the author."""

    file: str | None = None
    """A compose file, only if the CLI needs ``-f`` to resolve the project; a project tears down

    by its label alone otherwise. As a path inside the run's work directory."""

    content: str | None = None
    """A compose file inline, written to the run's work directory, for the same reason as ``file``."""

    profiles: list[str] = Field(default_factory=list[str])
    """Compose profiles to activate, only meaningful alongside a ``file``."""

    env_files: list[str] = Field(default_factory=list[str])
    """Env files for compose to read, as paths inside the run's work directory (``--env-file``)."""

    env: dict[str, str] = Field(default_factory=dict[str, str])
    """Variables set for the CLI itself, such as those a compose file interpolates."""

    env_allowlist: list[str] = Field(default_factory=list[str])
    """Worker environment variables the CLI is allowed to inherit; never the instance's ``DIRIGENT_*``."""

    down_volumes: bool = False
    """Also remove the named volumes the stack declared (``-v``)."""

    down_timeout: Duration = timedelta(seconds=10)
    """How long to wait for a container to stop before killing it (``--timeout``)."""

    down_remove_images: Literal["none", "local", "all"] = "none"
    """Which images to remove: ``none``, ``local`` (only untagged), or ``all`` (``--rmi``)."""

    remove_orphans: bool = True
    """Remove containers for services no longer in the compose file (``--remove-orphans``)."""

    connection: ConnectionRef | None = None
    """A ``docker`` connection naming the daemon this stack runs on.

    Absent, the stack runs on whatever daemon the worker's own environment names. The ``up``,
    the steps that drive it and the ``down`` should all name the same connection, because a
    stack only exists on the daemon that was told to create it."""

    command_path: list[str] = Field(default_factory=lambda: ["docker", "compose"])
    """The CLI to invoke, for a host that spells it ``docker-compose`` or wraps it."""

    timeout: Duration = timedelta(minutes=10)
    """The overall deadline on the CLI invocation, after which it is killed as transient."""

    @model_validator(mode="after")
    def _check_shape(self) -> "DockerComposeDownConfig":
        """Reject two compose-file forms at once, or a path that climbs out of the work directory."""
        if self.file and self.content:
            raise ValueError("docker.compose.down takes at most one of file or content")
        _reject_escaping((self.file, *self.env_files))
        reject_reserved(self.env_allowlist)
        return self


class DockerComposeUpOutput(BlockModel):
    """What the stack looks like once it is up, from the project's own containers."""

    project: str
    """The compose project brought up."""

    services: list[ComposeService] = Field(default_factory=list[ComposeService])
    """Every service's container, from the Engine API."""

    networks: list[str] = Field(default_factory=list[str])
    """The docker networks the project's containers are attached to, by the names the daemon knows."""

    default_network: str
    """The project's default network, which a downstream ``docker.run`` names to join the stack."""

    up: bool = True
    """Always true: the step returns only once the stack is up."""

    compose_file: str
    """The compose file the CLI was given, as a path inside the run's work directory.

    A later step that needs the same document -- a ``docker.compose.down`` of a stack this step
    brought up from inline content -- passes this back as its own ``file``."""

    stdout_uri: str
    """Where the whole of the CLI's stdout was written."""

    stderr_uri: str
    """Where the whole of the CLI's stderr was written."""


class DockerComposeDownOutput(BlockModel):
    """What the teardown did."""

    project: str
    """The compose project torn down."""

    torn_down: bool = True
    """Always true: the step returns only once the stack is down."""

    stdout_uri: str
    """Where the whole of the CLI's stdout was written."""

    stderr_uri: str
    """Where the whole of the CLI's stderr was written."""


# -- the operators, thin over the shared core ------------------------------------


class DockerComposeUpOperator(Operator[DockerComposeUpConfig, DockerComposeUpOutput]):
    """Brings a compose stack up detached and reports its state over the API, behind the allowlist."""

    spec = OperatorSpec(
        id="docker.compose.up",
        group="execute",
        summary="Bring a compose stack up on the worker.",
        idempotent=False,
        local_execution=True,
    )
    config_model: ClassVar[type[BaseModel]] = DockerComposeUpConfig
    output_model: ClassVar[type[BaseModel]] = DockerComposeUpOutput

    async def execute(self, config: DockerComposeUpConfig, ctx: StepContext) -> DockerComposeUpOutput | RemoteHandle:
        """Bring the stack up, clean up a bring-up that did not succeed, and report the project's state."""
        root = _workspace(ctx)
        compose_file = _compose_file(config.file, config.content, ctx, root)
        assert compose_file is not None
        project = config.project_name or _default_project(ctx)
        timeout = config.timeout.total_seconds()
        stdout_uri, stderr_uri = _artifact_uris(ctx, "up")

        with sealed(_connection(config.connection, ctx), root) as material:
            environ = daemon_environment(
                subprocess.environment([*DAEMON_ENV, *config.env_allowlist], config.env, root), material
            )
            write_cli_config(root / ".docker")
            try:
                code, out, err = await subprocess.run(
                    directory=root,
                    ctx=ctx,
                    stdout_uri=stdout_uri,
                    stderr_uri=stderr_uri,
                    timeout_seconds=timeout,
                    environ=environ,
                    argv=up_argv(config, project, compose_file, root),
                    what="docker compose up",
                )
            except BaseException:
                # The bring-up timed out or the step was cancelled, and whatever compose had
                # already started is running: tear it down before leaving, the same as a
                # non-zero exit does.
                if config.cleanup:
                    await _abandoned(config, project, compose_file, root, environ, ctx)
                raise
            log_stream(ctx, "stdout", out)
            log_stream(ctx, "stderr", err)
            ctx.log.info("docker compose up finished", project=project, exit_code=code)
            if code != 0:
                if config.cleanup:
                    await _cleanup(config, project, compose_file, root, environ, CLEANUP_TIMEOUT_SECONDS, ctx)
                detail = tail(err.tail) or tail(out.tail) or "no output"
                raise BlockFailure(f"docker compose up exited {code}: {detail}", error_class=_classify(err.tail))

            services, networks, default_network = await read_status(
                config.socket_path, config.api_timeout.total_seconds(), project, environ
            )
        return DockerComposeUpOutput(
            project=project,
            services=services,
            networks=networks,
            default_network=default_network,
            stdout_uri=stdout_uri,
            stderr_uri=stderr_uri,
            compose_file=_work_relative(compose_file, root),
        )


class DockerComposeDownOperator(Operator[DockerComposeDownConfig, DockerComposeDownOutput]):
    """Tears a compose stack down on the worker, behind the allowlist."""

    spec = OperatorSpec(
        id="docker.compose.down",
        group="execute",
        summary="Tear a compose stack down on the worker.",
        idempotent=False,
        local_execution=True,
    )
    config_model: ClassVar[type[BaseModel]] = DockerComposeDownConfig
    output_model: ClassVar[type[BaseModel]] = DockerComposeDownOutput

    async def execute(
        self, config: DockerComposeDownConfig, ctx: StepContext
    ) -> DockerComposeDownOutput | RemoteHandle:
        """Tear the stack down, by its project label alone unless a compose file was given."""
        root = _workspace(ctx)
        compose_file = _compose_file(config.file, config.content, ctx, root)
        project = config.project_name or _default_project(ctx)
        timeout = config.timeout.total_seconds()
        stdout_uri, stderr_uri = _artifact_uris(ctx, "down")

        with sealed(_connection(config.connection, ctx), root) as material:
            environ = daemon_environment(
                subprocess.environment([*DAEMON_ENV, *config.env_allowlist], config.env, root), material
            )
            write_cli_config(root / ".docker")
            code, out, err = await subprocess.run(
                directory=root,
                ctx=ctx,
                stdout_uri=stdout_uri,
                stderr_uri=stderr_uri,
                timeout_seconds=timeout,
                environ=environ,
                argv=down_argv(config, project, compose_file, root),
                what="docker compose down",
            )
        log_stream(ctx, "stdout", out)
        log_stream(ctx, "stderr", err)
        ctx.log.info("docker compose down finished", project=project, exit_code=code)
        if code != 0:
            detail = tail(err.tail) or tail(out.tail) or "no output"
            raise BlockFailure(f"docker compose down exited {code}: {detail}", error_class=_classify(err.tail))
        return DockerComposeDownOutput(project=project, stdout_uri=stdout_uri, stderr_uri=stderr_uri)


# -- the CLI, for up and down ----------------------------------------------------


def _global_flags(
    command_path: list[str],
    project: str,
    compose_file: Path | None,
    profiles: list[str],
    env_files: list[str],
    root: Path,
) -> list[str]:
    """The flags every compose invocation carries: the project, an optional file, profiles, env files.

    ``--project-directory`` is the run's work directory whatever directory the compose file itself
    sits in, so relative build contexts and env files in the document resolve against the run's
    own directory rather than against a generated file's directory.
    """
    flags = [*command_path, "--project-name", project, "--project-directory", str(root)]
    if compose_file is not None:
        flags += ["-f", str(compose_file)]
    for profile in profiles:
        flags += ["--profile", profile]
    for env_file in env_files:
        flags += ["--env-file", str(root / env_file)]
    return flags


def up_argv(config: DockerComposeUpConfig, project: str, compose_file: Path, root: Path) -> list[str]:
    """Assemble the ``up`` argv, flag by flag."""
    argv = [
        *_global_flags(config.command_path, project, compose_file, config.profiles, config.env_files, root),
        "up",
        "-d",
    ]
    if config.wait:
        argv += ["--wait", "--wait-timeout", str(int(config.wait_timeout.total_seconds()))]
    if config.remove_orphans:
        argv.append("--remove-orphans")
    argv += ["--pull", config.pull]
    return argv


def down_argv(config: DockerComposeDownConfig, project: str, compose_file: Path | None, root: Path) -> list[str]:
    """Assemble the ``down`` argv, flag by flag."""
    argv = [
        *_global_flags(config.command_path, project, compose_file, config.profiles, config.env_files, root),
        "down",
    ]
    if config.down_volumes:
        argv.append("-v")
    argv += ["--timeout", str(int(config.down_timeout.total_seconds()))]
    if config.remove_orphans:
        argv.append("--remove-orphans")
    if config.down_remove_images != "none":
        argv += ["--rmi", config.down_remove_images]
    return argv


def _cleanup_argv(config: DockerComposeUpConfig, project: str, compose_file: Path, root: Path) -> list[str]:
    """A plain ``down`` for the failed-up backstop, built from the ``up`` config."""
    argv = [
        *_global_flags(config.command_path, project, compose_file, config.profiles, config.env_files, root),
        "down",
    ]
    if config.remove_orphans:
        argv.append("--remove-orphans")
    return argv


async def _abandoned(
    config: DockerComposeUpConfig,
    project: str,
    compose_file: Path,
    root: Path,
    environ: dict[str, str],
    ctx: StepContext,
) -> None:
    """Tear down a bring-up nothing is waiting for any more, out of reach of the cancellation.

    A cancelled step is cancelled again as soon as it awaits, so the teardown runs as a task
    behind a shield and is bounded by its own deadline rather than the step's.
    """
    teardown = asyncio.ensure_future(
        _cleanup(config, project, compose_file, root, environ, CLEANUP_TIMEOUT_SECONDS, ctx)
    )
    try:
        await asyncio.shield(teardown)
    except asyncio.CancelledError:
        with contextlib.suppress(BaseException):
            await asyncio.shield(teardown)
        raise


async def _cleanup(
    config: DockerComposeUpConfig,
    project: str,
    compose_file: Path,
    root: Path,
    environ: dict[str, str],
    timeout: float,
    ctx: StepContext,
) -> None:
    """Best-effort tear down a stack whose own ``up`` did not succeed, so nothing half-built is left."""
    try:
        code, _, err = await subprocess.output(
            argv=_cleanup_argv(config, project, compose_file, root),
            directory=root,
            environ=environ,
            timeout_seconds=timeout,
            what="docker compose down",
        )
    except BlockFailure as error:
        ctx.log.warning("the failed stack could not be cleaned up", project=project, error=str(error))
        return
    if code != 0:
        ctx.log.warning("the failed stack could not be cleaned up", project=project, detail=tail(err))
    else:
        ctx.log.info("the failed stack was cleaned up", project=project)


# -- the status read, over the Engine API ----------------------------------------


def connect(socket_path: str | None, timeout: float, environ: Mapping[str, str] | None = None) -> httpx2.AsyncClient:
    """Open a client onto the daemon the status read speaks to."""
    return open_client(resolve_endpoint(socket_path, environ), timeout)


def _daemon(socket_path: str | None, timeout: float, environ: Mapping[str, str] | None = None) -> DockerDaemon:
    """Build the daemon facade the status read uses."""
    return DockerDaemon(connect(socket_path, timeout, environ), resolve_endpoint(socket_path, environ).socket)


def _connection(ref: ConnectionRef | None, ctx: StepContext) -> DockerConnectionConfig | None:
    """Resolve the step's ``docker`` connection, or report that it named none."""
    return ctx.connection(ref, DockerConnectionConfig) if ref else None


async def read_status(
    socket_path: str | None, timeout: float, project: str, environ: Mapping[str, str] | None = None
) -> tuple[list[ComposeService], list[str], str]:
    """List the project's containers by label, inspect each, and name the networks they are on."""
    default_network = f"{project}_default"
    networks: set[str] = {default_network}
    services: list[ComposeService] = []
    async with _daemon(socket_path, timeout, environ) as daemon:
        ids = await daemon.list_containers({"label": [f"{PROJECT_LABEL}={project}"]})
        for container in ids:
            inspected = await daemon.inspect(container)
            if inspected is None:
                continue
            services.append(_service_from(inspected))
            networks.update(inspected.network_settings.networks.keys())
    services.sort(key=lambda service: service.name)
    return services, sorted(networks), default_network


def _service_from(inspected: ContainerInspect) -> ComposeService:
    """Build one ``ComposeService`` from a container's inspect: its state, health and ports."""
    publishers: list[ComposePublisher] = []
    for spec, bindings in inspected.network_settings.ports.items():
        port, _, protocol = spec.partition("/")
        for binding in bindings or []:
            publishers.append(
                ComposePublisher(
                    url=binding.host_ip,
                    target_port=int(port) if port.isdigit() else 0,
                    published_port=int(binding.host_port) if binding.host_port.isdigit() else 0,
                    protocol=protocol,
                )
            )
    return ComposeService(
        name=inspected.name.lstrip("/"),
        service=inspected.config.labels.get(SERVICE_LABEL, ""),
        image=inspected.config.image,
        state=inspected.state.status,
        health=inspected.state.health.status,
        exit_code=inspected.state.exit_code,
        publishers=publishers,
    )


# -- paths and naming ------------------------------------------------------------


def _reject_escaping(paths: tuple[str | None, ...]) -> None:
    """Refuse a work-directory-relative path that is absolute or climbs out of the run's work directory."""
    for path in paths:
        if path and (Path(path).is_absolute() or ".." in Path(path).parts):
            raise ValueError(
                "a compose file or env file is a path inside the run's work directory, so it cannot "
                "be absolute or climb out"
            )


def _workspace(ctx: StepContext) -> Path:
    """The run's work directory, which the compose CLI needs a real filesystem for."""
    return subprocess.local_root(ctx)


def _compose_file(file: str | None, content: str | None, ctx: StepContext, root: Path) -> Path | None:
    """Resolve the compose file: inline content, a file named in the work directory, or none.

    Inline content is written under ``compose/{step}[/{item}]/attempt-{n}`` so two compose steps
    of one run, or two items of one fan-out, never write over each other's document. A named file
    is the author's own path, which stays relative to the run's work directory.
    """
    if content is not None:
        directory = subprocess.workspace(ctx, "compose")
        path = directory / "docker-compose.yaml"
        path.write_text(content)
        return path
    if file is not None:
        return root / file
    return None


def _work_relative(path: Path, root: Path) -> str:
    """A compose file's path as a later step would name it, relative to the run's work directory."""
    return str(path.relative_to(root))


def _artifact_uris(ctx: StepContext, action: str) -> tuple[str, str]:
    """Where the CLI's two streams are written for this attempt."""
    root = f"{subprocess.prefix(ctx, 'compose')}-{action}"
    return f"{root}-stdout.txt", f"{root}-stderr.txt"


def _default_project(ctx: StepContext) -> str:
    """A project name that is the same across a run's up, drive and down, and unique between runs."""
    return f"dirigent-{ctx.run_id.hex}"


def _classify(stderr_tail: bytes) -> ErrorClass:
    """A daemon that cannot be reached is transient; a stack that would not come up is not."""
    text = stderr_tail.decode("utf-8", errors="replace").lower()
    if any(marker in text for marker in DAEMON_UNREACHABLE):
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN
