"""Tests for docker.build: argv assembly, the iidfile read, size, and how a build ends."""

import asyncio
import subprocess as std_subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks.build import (
    DockerBuildConfig,
    DockerBuildOperator,
    DockerBuildOutput,
    build_argv,
)
from dirigent_blocks.capture import Drained
from dirigent_blocks.docker import DockerConnectionConfig
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext

IMAGE_ID = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def reaped_pid() -> int:
    """A pid whose process has certainly exited, so the teardown's group kill finds nothing."""
    child = std_subprocess.Popen(["true"])  # noqa: S603, S607
    child.wait()
    return child.pid


class FakeReader:
    """A stream reader that hands its bytes over once and then reports end."""

    def __init__(self, data: bytes) -> None:
        """Hold the bytes to hand over."""
        self._data = data

    async def read(self, count: int) -> bytes:
        chunk, self._data = self._data[:count], self._data[count:]
        return chunk


class FakeProcess:
    """A finished subprocess with both streams already whole."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        """Hold the finished streams and the return code."""
        self.returncode = returncode
        self.stdout = FakeReader(stdout)
        self.stderr = FakeReader(stderr)
        self._out = stdout
        self._err = stderr
        self.pid = reaped_pid()

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self, stdin: bytes | None = None) -> tuple[bytes, bytes]:
        return self._out, self._err


def scripted_exec(monkeypatch: pytest.MonkeyPatch, respond: Callable[[list[str]], "FakeProcess"]) -> list[list[str]]:
    """Replace create_subprocess_exec with a script that answers by argv, recording every call."""
    calls: list[list[str]] = []

    async def fake_exec(*argv: str, **_: object) -> FakeProcess:
        calls.append(list(argv))
        return respond(list(argv))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def build_and_inspect(argv: list[str]) -> FakeProcess:
    """Answer a build by writing the iidfile, and an inspect by printing a size."""
    if "inspect" in argv:
        return FakeProcess(0, stdout=b"104857600\n")
    Path(argv[argv.index("--iidfile") + 1]).write_text(IMAGE_ID)
    return FakeProcess(0, stderr=b"#1 building\n")


# -- the block declares itself unsafe --------------------------------------------


def test_the_block_declares_that_it_executes_locally() -> None:
    assert DockerBuildOperator.spec.local_execution is True
    assert DockerBuildOperator.spec.idempotent is False


# -- config validators -----------------------------------------------------------


def test_a_push_with_no_connection_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot push without a connection"):
        DockerBuildConfig(context=".", push=True, tags=["ghcr.io/o/i:1"])


def test_a_push_with_no_tag_has_nothing_to_push() -> None:
    with pytest.raises(ValidationError, match="at least one tag"):
        DockerBuildConfig(context=".", push=True, connection="ghcr")


def test_a_context_or_dockerfile_that_climbs_out_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerBuildConfig(context="/etc")
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerBuildConfig(context="app", dockerfile="../Dockerfile")


def test_a_build_refuses_to_inherit_the_instances_own_configuration() -> None:
    with pytest.raises(ValidationError) as raised:
        DockerBuildConfig(context=".", env_allowlist=["DIRIGENT_SECRET_KEY"])
    assert "DIRIGENT_SECRET_KEY" in str(raised.value)


# -- argv assembly ---------------------------------------------------------------


def test_build_argv_is_assembled_flag_by_flag() -> None:
    config = DockerBuildConfig(
        context="app",
        dockerfile="docker/Dockerfile",
        tags=["myimage:1", "myimage:latest"],
        build_args={"VERSION": "1.2.3"},
        target="runtime",
        platform="linux/amd64",
        pull=True,
        no_cache=True,
    )
    argv = build_argv(config, Path("/scratch/app"), Path("/scratch/build/attempt-1.iid"))
    assert argv == [
        "docker",
        "buildx",
        "build",
        "--file",
        "/scratch/app/docker/Dockerfile",
        "--iidfile",
        "/scratch/build/attempt-1.iid",
        "--tag",
        "myimage:1",
        "--tag",
        "myimage:latest",
        "--build-arg",
        "VERSION=1.2.3",
        "--target",
        "runtime",
        "--platform",
        "linux/amd64",
        "--pull",
        "--no-cache",
        "--load",
        "/scratch/app",
    ]


def test_build_argv_defaults_to_the_dockerfile_in_the_context_root() -> None:
    config = DockerBuildConfig(context="app", tags=["x:1"])
    argv = build_argv(config, Path("/scratch/app"), Path("/scratch/build/attempt-1.iid"))
    assert "--file" in argv
    assert argv[argv.index("--file") + 1] == "/scratch/app/Dockerfile"
    assert argv[-1] == "/scratch/app"


# -- execute ---------------------------------------------------------------------


async def test_a_build_reports_the_image_id_tags_and_size(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, build_and_inspect)

    output = await DockerBuildOperator().execute(
        DockerBuildConfig(context=".", tags=["myimage:1"]), local_ctx.as_context()
    )

    assert isinstance(output, DockerBuildOutput)
    assert output.image_id == IMAGE_ID
    assert output.tags == ["myimage:1"]
    assert output.size_bytes == 104857600
    assert output.build_log_uri.startswith(local_ctx.scratch)
    assert any("inspect" in call for call in calls), "the size read inspects the image"


async def test_a_build_that_reports_success_but_writes_no_id_fails(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    with pytest.raises(BlockFailure, match="wrote no image id"):
        await DockerBuildOperator().execute(DockerBuildConfig(context="."), local_ctx.as_context())


async def test_a_failed_build_reports_the_reason(local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted_exec(monkeypatch, lambda argv: FakeProcess(1, stderr=b"COPY failed: no such file\n"))
    with pytest.raises(BlockFailure) as raised:
        await DockerBuildOperator().execute(DockerBuildConfig(context="."), local_ctx.as_context())
    assert raised.value.error_class is ErrorClass.UNKNOWN
    assert "build exited 1" in str(raised.value)
    assert "COPY failed" in str(raised.value)


async def test_an_unreachable_daemon_on_build_is_transient(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(
        monkeypatch,
        lambda argv: FakeProcess(1, stderr=b"ERROR: Cannot connect to the Docker daemon\n"),
    )
    with pytest.raises(BlockFailure) as raised:
        await DockerBuildOperator().execute(DockerBuildConfig(context="."), local_ctx.as_context())
    assert raised.value.error_class is ErrorClass.TRANSIENT


async def test_a_build_context_comes_from_the_work_directory_whatever_scratch_is(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build context is a directory, so it is the run's work directory and never storage."""
    local_ctx.scratch_uri = "s3://bucket/artifacts/runs/one"
    calls = scripted_exec(monkeypatch, build_and_inspect)
    await DockerBuildOperator().execute(DockerBuildConfig(context="."), local_ctx.as_context())
    build = next(argv for argv in calls if "build" in argv)
    assert str(local_ctx.work) in build


async def test_a_size_read_that_fails_leaves_the_size_zero(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(argv: list[str]) -> FakeProcess:
        if "inspect" in argv:
            return FakeProcess(1, stderr=b"no such image\n")
        Path(argv[argv.index("--iidfile") + 1]).write_text(IMAGE_ID)
        return FakeProcess(0)

    scripted_exec(monkeypatch, respond)
    output = await DockerBuildOperator().execute(DockerBuildConfig(context="."), local_ctx.as_context())
    assert isinstance(output, DockerBuildOutput)
    assert output.size_bytes == 0


# -- against a real daemon -------------------------------------------------------

from dirigent_blocks.docker import DockerRunConfig, DockerRunOperator, socket_path  # noqa: E402
from dirigent_plugin import ProbeStatus, RemoteHandle  # noqa: E402

requires_daemon = pytest.mark.skipif(
    not Path(socket_path(DockerRunConfig(image="alpine:3"))).exists(),
    reason="no Docker daemon socket is reachable",
)

TINY_DOCKERFILE = 'FROM alpine:3\nRUN echo built > /built.txt\nCMD ["cat", "/built.txt"]\n'


async def _drive_until_terminal(handle: RemoteHandle, config: DockerRunConfig, ctx: FakeContext) -> ProbeStatus:
    """Poll a docker.run container the way the engine would, since the block never waits."""
    operator = DockerRunOperator()
    for _ in range(300):
        probed = await operator.probe(handle, config, ctx.as_context())
        if probed.status is not ProbeStatus.RUNNING:
            return probed.status
        await asyncio.sleep(0.1)
    raise AssertionError("the container never finished")


@pytest.mark.docker
@requires_daemon
async def test_a_real_build_lands_an_image_a_later_step_runs(local_ctx: FakeContext) -> None:
    root = Path(local_ctx.storage.root) / "runs" / "one"
    root.mkdir(parents=True, exist_ok=True)
    (root / "Dockerfile").write_text(TINY_DOCKERFILE)

    output = await DockerBuildOperator().execute(
        DockerBuildConfig(context=".", tags=["dirigent-build-test:latest"]), local_ctx.as_context()
    )
    assert isinstance(output, DockerBuildOutput)
    assert output.image_id.startswith("sha256:")
    assert output.size_bytes > 0

    # The image is in the worker's daemon store now, so a docker.run step runs it by tag.
    run = DockerRunConfig(image="dirigent-build-test:latest")
    handle = await DockerRunOperator().execute(run, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    assert await _drive_until_terminal(handle, run, local_ctx) is ProbeStatus.SUCCEEDED
    result = await DockerRunOperator().fetch(handle, run, local_ctx.as_context())
    assert result.stdout.strip() == "built"


# -- pushing ---------------------------------------------------------------------

REGISTRY = DockerConnectionConfig(registry="ghcr.io", username="robot", password=SecretStr("s3cr3t"))

TAGS = ["ghcr.io/owner/app:1.2.3", "ghcr.io/owner/app:latest"]


class PushingCli:
    """The docker CLI as a build that pushes sees it: build, inspect, login, push, logout."""

    def __init__(self, push_code: int = 0, digest: bool = True) -> None:
        """Script how the pushes go, and remember what each invocation was given."""
        self.push_code = push_code
        self.digest = digest
        self.stdins: list[bytes | None] = []

    def __call__(self, argv: list[str]) -> FakeProcess:
        if "login" in argv:
            return _Recording(self, 0, stdout=b"Login Succeeded\n")
        if "logout" in argv:
            return FakeProcess(0, stdout=b"Removing login credentials\n")
        if "push" in argv:
            printed = b"latest: digest: sha256:" + b"a" * 64 + b" size: 1234\n" if self.digest else b"pushed\n"
            return FakeProcess(self.push_code, stdout=printed, stderr=b"" if self.push_code == 0 else b"denied")
        return build_and_inspect(argv)


class _Recording(FakeProcess):
    """A fake process that hands its stdin back to the script that made it."""

    def __init__(self, cli: PushingCli, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        """Hold the script this process reports its stdin to."""
        super().__init__(returncode, stdout, stderr)
        self._cli = cli

    async def communicate(self, stdin: bytes | None = None) -> tuple[bytes, bytes]:
        self._cli.stdins.append(stdin)
        return await super().communicate(stdin)


async def test_a_push_reports_the_tags_and_their_digests(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = PushingCli()
    calls = scripted_exec(monkeypatch, cli)
    local_ctx.connections["ghcr"] = REGISTRY
    built = await DockerBuildOperator().execute(
        DockerBuildConfig(context="app", tags=TAGS, push=True, connection="ghcr"), local_ctx.as_context()
    )
    assert isinstance(built, DockerBuildOutput)
    assert built.pushed == TAGS
    assert set(built.digests) == set(TAGS)
    assert all(value.startswith("sha256:") for value in built.digests.values())
    pushed = [call for call in calls if "push" in call]
    assert [call[-1] for call in pushed] == TAGS


async def test_a_push_logs_in_on_stdin_against_a_config_directory_of_its_own(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = PushingCli()
    calls = scripted_exec(monkeypatch, cli)
    local_ctx.connections["ghcr"] = REGISTRY
    await DockerBuildOperator().execute(
        DockerBuildConfig(context="app", tags=TAGS[:1], push=True, connection="ghcr"), local_ctx.as_context()
    )
    login = next(call for call in calls if "login" in call)
    assert login[1:] == ["login", "--username", "robot", "--password-stdin", "ghcr.io"]
    assert cli.stdins == [b"s3cr3t"]
    assert all("s3cr3t" not in argument for call in calls for argument in call)
    assert any("logout" in call for call in calls)


async def test_a_push_leaves_no_login_behind(local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted_exec(monkeypatch, PushingCli())
    local_ctx.connections["ghcr"] = REGISTRY
    await DockerBuildOperator().execute(
        DockerBuildConfig(context="app", tags=TAGS[:1], push=True, connection="ghcr"), local_ctx.as_context()
    )
    root = Path(local_ctx.scratch.removeprefix("file://"))
    assert list(root.glob("dirigent-docker-*")) == []


async def test_a_push_through_a_connection_with_no_registry_credential_is_refused(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(monkeypatch, PushingCli())
    local_ctx.connections["dind"] = DockerConnectionConfig(host="tcp://dind:2376")
    with pytest.raises(BlockFailure) as raised:
        await DockerBuildOperator().execute(
            DockerBuildConfig(context="app", tags=TAGS[:1], push=True, connection="dind"), local_ctx.as_context()
        )
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "username and password" in str(raised.value)


async def test_a_push_the_registry_refuses_fails_the_step_without_the_credential(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(monkeypatch, PushingCli(push_code=1))
    local_ctx.connections["ghcr"] = REGISTRY
    with pytest.raises(BlockFailure) as raised:
        await DockerBuildOperator().execute(
            DockerBuildConfig(context="app", tags=TAGS[:1], push=True, connection="ghcr"), local_ctx.as_context()
        )
    assert "denied" in str(raised.value)
    assert "s3cr3t" not in str(raised.value)


async def test_a_push_that_reports_no_digest_still_reports_the_tag(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(monkeypatch, PushingCli(digest=False))
    local_ctx.connections["ghcr"] = REGISTRY
    built = await DockerBuildOperator().execute(
        DockerBuildConfig(context="app", tags=TAGS[:1], push=True, connection="ghcr"), local_ctx.as_context()
    )
    assert isinstance(built, DockerBuildOutput)
    assert built.pushed == TAGS[:1]
    assert built.digests == {}


async def test_a_build_that_pushes_nothing_reports_nothing_pushed(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(monkeypatch, build_and_inspect)
    built = await DockerBuildOperator().execute(DockerBuildConfig(context="app", tags=TAGS[:1]), local_ctx.as_context())
    assert isinstance(built, DockerBuildOutput)
    assert built.pushed == []
    assert built.digests == {}


async def test_a_build_against_a_connection_reaches_the_daemon_it_names(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, str]] = []

    async def fake_run(**kwargs: Any) -> tuple[int, object, object]:
        seen.append(dict(cast("dict[str, str]", kwargs["environ"])))
        Path(str(kwargs["directory"])).mkdir(parents=True, exist_ok=True)
        argv = cast("list[str]", kwargs["argv"])
        Path(argv[argv.index("--iidfile") + 1]).write_text(IMAGE_ID)
        return 0, _empty(), _empty()

    monkeypatch.setattr("dirigent_blocks.subprocess.run", fake_run)
    scripted_exec(monkeypatch, build_and_inspect)
    local_ctx.connections["dind"] = DockerConnectionConfig(host="tcp://dind:2376")
    await DockerBuildOperator().execute(
        DockerBuildConfig(context="app", tags=TAGS[:1], connection="dind"), local_ctx.as_context()
    )
    assert seen[0]["DOCKER_HOST"] == "tcp://dind:2376"


def _empty() -> Drained:
    """A drained stream with nothing in either end."""
    return Drained(head=b"", tail=b"", total_bytes=0)
