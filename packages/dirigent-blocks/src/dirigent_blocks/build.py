"""``docker.build``: build an image from a context on the worker, with buildx.

The block shells out to ``docker buildx build`` -- BuildKit, its cache and multi-stage builds
come for free -- and reads the built image's id from an ``--iidfile`` rather than scraping the
log. The image lands in the worker's own daemon store, so a later ``docker.run`` or
``docker.compose`` step on the same worker references it by tag.

Reaching the Docker daemon is reaching root on the host when the daemon is the host's own, so
the block declares ``local_execution`` and the engine refuses it unless the instance allowlists
its id.

``push`` needs a ``docker`` connection carrying a registry credential, and is refused without
one. The login goes to a ``DOCKER_CONFIG`` directory of its own under scratch -- never the
worker's own config -- with the password on stdin rather than in an argument, and the
directory and the session in it go when the step leaves.
"""

import re
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from dirigent_blocks import subprocess
from dirigent_blocks.capture import log_stream, scrub, tail
from dirigent_blocks.docker import (
    DAEMON_ENV,
    DockerConnectionConfig,
    Sealed,
    daemon_environment,
    login,
    logout,
    sealed,
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

#: What a daemon that is not there or not ours says, a transient condition rather than a broken build.
DAEMON_UNREACHABLE = ("cannot connect to the docker daemon", "is the docker daemon running", "permission denied")

#: What ``docker push`` prints once the registry has taken a tag, which is where its digest is.
PUSHED_DIGEST = re.compile(r"digest:\s*(sha256:[0-9a-f]{64})")


class DockerBuildConfig(BlockModel):
    """Which context to build, with what Dockerfile, tags, and build arguments."""

    context: str
    """The build context, as a directory inside the run's scratch space; never absolute, never climbing out."""

    dockerfile: str = "Dockerfile"
    """The Dockerfile, as a path relative to the context."""

    tags: list[str] = Field(default_factory=list[str])
    """Tags to give the built image (``--tag``); a later step references the image by one of them."""

    build_args: dict[str, str] = Field(default_factory=dict[str, str])
    """Build arguments the Dockerfile reads (``--build-arg``)."""

    target: str | None = None
    """The stage to stop at in a multi-stage build (``--target``)."""

    platform: str | None = None
    """The platform to build for, such as ``linux/amd64`` (``--platform``)."""

    pull: bool = False
    """Always attempt to pull a newer version of the base image (``--pull``)."""

    no_cache: bool = False
    """Build every layer from scratch, ignoring the cache (``--no-cache``)."""

    push: bool = False
    """Push every tag the build produced to the registry the connection names.

    Needs a ``connection`` carrying a registry username and password: an anonymous push is
    refused rather than attempted."""

    connection: ConnectionRef | None = None
    """A ``docker`` connection naming the daemon to build on, the registry to push to, or both.

    Absent, the build runs against whatever daemon the worker's own environment names and
    nothing is pushed."""

    env: dict[str, str] = Field(default_factory=dict[str, str])
    """Variables set for the CLI itself, such as BuildKit's own toggles."""

    env_allowlist: list[str] = Field(default_factory=list[str])
    """Worker environment variables the CLI is allowed to inherit; never the instance's ``DIRIGENT_*``."""

    command_path: list[str] = Field(default_factory=lambda: ["docker", "buildx", "build"])
    """The CLI to invoke, for a host that wraps buildx."""

    timeout: Duration = timedelta(minutes=30)
    """The overall deadline on the build, after which it is killed as transient."""

    @model_validator(mode="after")
    def _check_shape(self) -> "DockerBuildConfig":
        """Refuse an unbacked push, a context or Dockerfile that climbs out, and a reserved env inheritance."""
        if self.push and self.connection is None:
            raise ValueError(
                "docker.build cannot push without a connection: set connection to a docker connection "
                "holding registry, username and password"
            )
        if self.push and not self.tags:
            raise ValueError("docker.build pushes the tags it built, so a push needs at least one tag")
        for path in (self.context, self.dockerfile):
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError(
                    "the context and Dockerfile are paths inside the run's scratch space, so they "
                    "cannot be absolute or climb out"
                )
        reject_reserved(self.env_allowlist)
        return self


class DockerBuildOutput(BlockModel):
    """The image the build produced, with its full log addressable as an artifact."""

    image_id: str
    """The built image's id, read from the ``--iidfile`` the daemon wrote, not scraped from the log."""

    tags: list[str] = Field(default_factory=list[str])
    """The tags the image was given, by which a later step on the same worker references it."""

    size_bytes: int = 0
    """The image's size on disk, from the daemon; zero when it could not be read."""

    pushed: list[str] = Field(default_factory=list[str])
    """The tags that reached the registry, empty when the step pushed nothing."""

    digests: dict[str, str] = Field(default_factory=dict[str, str])
    """The registry's digest for each pushed tag, for the tags the CLI reported one for."""

    build_log_uri: str
    """Where the whole of the build log (buildx's progress on stderr) was written."""

    stdout_uri: str
    """Where the whole of the CLI's stdout was written."""


class DockerBuildOperator(Operator[DockerBuildConfig, DockerBuildOutput]):
    """Builds an image from a scratch context with buildx, behind the allowlist."""

    spec = OperatorSpec(
        id="docker.build",
        group="execute",
        summary="Build a container image on the worker.",
        idempotent=False,
        local_execution=True,
    )
    config_model: ClassVar[type[BaseModel]] = DockerBuildConfig
    output_model: ClassVar[type[BaseModel]] = DockerBuildOutput

    async def execute(self, config: DockerBuildConfig, ctx: StepContext) -> DockerBuildOutput | RemoteHandle:
        """Build the image, read its id from the iidfile, and report its size and tags."""
        root = subprocess.local_root(ctx)
        context = root / config.context
        iidfile = Path(f"{root / subprocess.segment(ctx, 'build')}.iid")
        iidfile.parent.mkdir(parents=True, exist_ok=True)
        settings = ctx.connection(config.connection, DockerConnectionConfig) if config.connection else None
        if config.push and (settings is None or not settings.authenticates):
            raise BlockFailure(
                "docker.build cannot push through a connection with no registry credential: set "
                "username and password on the docker connection, and registry unless it is Docker Hub",
                error_class=ErrorClass.REJECTED,
            )
        timeout = config.timeout.total_seconds()
        artifacts = subprocess.prefix(ctx, "build")
        stdout_uri = f"{artifacts}-stdout.txt"
        build_log_uri = f"{artifacts}-build.log"

        with sealed(settings, root, isolate_config=config.push) as material:
            environ = daemon_environment(
                subprocess.environment([*DAEMON_ENV, *config.env_allowlist], config.env, root), material
            )
            code, out, err = await subprocess.run(
                directory=root,
                ctx=ctx,
                stdout_uri=stdout_uri,
                stderr_uri=build_log_uri,
                timeout_seconds=timeout,
                environ=environ,
                argv=build_argv(config, context, iidfile),
                what="docker buildx build",
                redact=material.secrets,
            )
            log_stream(ctx, "stdout", out, material.secrets)
            log_stream(ctx, "stderr", err, material.secrets)
            ctx.log.info("docker build finished", exit_code=code, tags=", ".join(config.tags))
            if code != 0:
                detail = (
                    tail(err.tail, redact=material.secrets) or tail(out.tail, redact=material.secrets) or "no output"
                )
                raise BlockFailure(f"docker build exited {code}: {detail}", error_class=_classify(err.tail))

            image_id = iidfile.read_text().strip() if iidfile.exists() else ""
            if not image_id:
                raise BlockFailure(
                    "docker build reported success but wrote no image id to the iidfile",
                    error_class=ErrorClass.UNKNOWN,
                )
            size_bytes = await _image_size(config, image_id, root, environ, timeout)
            pushed, digests = await _push(config, settings, root, environ, material, timeout, ctx)
        ctx.log.info("image built", image_id=image_id[:19], size_bytes=size_bytes, tags=", ".join(config.tags))
        return DockerBuildOutput(
            image_id=image_id,
            tags=config.tags,
            size_bytes=size_bytes,
            pushed=pushed,
            digests=digests,
            build_log_uri=build_log_uri,
            stdout_uri=stdout_uri,
        )


def build_argv(config: DockerBuildConfig, context: Path, iidfile: Path) -> list[str]:
    """Assemble the ``buildx build`` argv, flag by flag, with the context last."""
    argv = [*config.command_path, "--file", str(context / config.dockerfile), "--iidfile", str(iidfile)]
    for tag in config.tags:
        argv += ["--tag", tag]
    for name, value in config.build_args.items():
        argv += ["--build-arg", f"{name}={value}"]
    if config.target is not None:
        argv += ["--target", config.target]
    if config.platform is not None:
        argv += ["--platform", config.platform]
    if config.pull:
        argv.append("--pull")
    if config.no_cache:
        argv.append("--no-cache")
    # Load the result into the worker's daemon store, so a later step can run it by tag; the
    # container-driver default would otherwise leave the image only in the builder's cache.
    argv.append("--load")
    argv.append(str(context))
    return argv


async def _push(
    config: DockerBuildConfig,
    settings: DockerConnectionConfig | None,
    root: Path,
    environ: dict[str, str],
    material: Sealed,
    timeout: float,
    ctx: StepContext,
) -> tuple[list[str], dict[str, str]]:
    """Log in, push every tag the build produced, and log out again.

    The login lives in the ``DOCKER_CONFIG`` directory the sealed material made, so it reaches
    neither the worker's own config nor any later step, and the logout takes even that away.
    """
    if not config.push:
        return [], {}
    assert settings is not None
    docker = config.command_path[0] if config.command_path else "docker"
    code, err = await login(docker, root, environ, settings)
    if code != 0:
        detail = tail(err, redact=material.secrets) or f"docker login exited {code}"
        raise BlockFailure(
            f"docker login to {settings.registry_name} failed: {detail}", error_class=ErrorClass.REJECTED
        )
    pushed: list[str] = []
    digests: dict[str, str] = {}
    try:
        for tag in config.tags:
            code, out, err = await subprocess.output(
                argv=[docker, "push", tag],
                directory=root,
                environ=environ,
                timeout_seconds=timeout,
                what="docker push",
            )
            if code != 0:
                detail = tail(err, redact=material.secrets) or tail(out, redact=material.secrets) or "no output"
                raise BlockFailure(f"docker push {tag} exited {code}: {detail}", error_class=_classify(err))
            found = PUSHED_DIGEST.search(scrub(out.decode("utf-8", errors="replace"), material.secrets))
            if found is not None:
                digests[tag] = found.group(1)
            pushed.append(tag)
            ctx.log.info("image pushed", tag=tag, registry=settings.registry_name, digest=digests.get(tag, ""))
    finally:
        await logout(docker, root, environ, settings)
    return pushed, digests


async def _image_size(
    config: DockerBuildConfig, image_id: str, root: Path, environ: dict[str, str], timeout: float
) -> int:
    """Read the built image's size from the daemon, best effort; zero when it cannot be read."""
    docker = config.command_path[0] if config.command_path else "docker"
    try:
        _code, out, _err = await subprocess.output(
            argv=[docker, "image", "inspect", "--format", "{{.Size}}", image_id],
            directory=root,
            environ=environ,
            timeout_seconds=timeout,
            what="docker image inspect",
        )
    except BlockFailure:
        return 0
    text = out.decode("utf-8", errors="replace").strip()
    return int(text) if text.isdigit() else 0


def _classify(stderr_tail: bytes) -> ErrorClass:
    """A daemon that cannot be reached is transient; a build that would not compile is not."""
    text = stderr_tail.decode("utf-8", errors="replace").lower()
    if any(marker in text for marker in DAEMON_UNREACHABLE):
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN
