"""Tests for docker.compose.up / docker.compose.down: argv assembly, the API status read, lifecycle."""

import asyncio
import json
import subprocess as std_subprocess
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from pydantic import ValidationError

from dirigent_blocks.compose import (
    DockerComposeDownConfig,
    DockerComposeDownOperator,
    DockerComposeDownOutput,
    DockerComposeUpConfig,
    DockerComposeUpOperator,
    DockerComposeUpOutput,
    down_argv,
    read_status,
    up_argv,
)
from dirigent_blocks.subprocess import local_root
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext

WEB_CONTAINER: dict[str, object] = {
    "Id": "web123",
    "Name": "/proj-web-1",
    "State": {"Status": "running", "Running": True, "ExitCode": 0, "Health": {"Status": "healthy"}},
    "Config": {
        "Image": "nginx:alpine",
        "Labels": {"com.docker.compose.project": "proj", "com.docker.compose.service": "web"},
    },
    "NetworkSettings": {
        "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
        "Networks": {"proj_default": {}},
    },
}

DB_CONTAINER: dict[str, object] = {
    "Id": "db456",
    "Name": "/proj-db-1",
    "State": {"Status": "running", "Running": True, "ExitCode": 0, "Health": {"Status": "healthy"}},
    "Config": {
        "Image": "postgres:16",
        "Labels": {"com.docker.compose.project": "proj", "com.docker.compose.service": "db"},
    },
    "NetworkSettings": {"Ports": {}, "Networks": {"proj_default": {}}},
}


class FakeComposeDaemon:
    """A daemon that answers the status read: a label-filtered container list, then each inspect."""

    def __init__(self, containers: list[dict[str, object]]) -> None:
        """Hold the containers a label filter will find."""
        self.containers = {str(c["Id"]): c for c in containers}
        self.filters: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Answer one Engine API call."""
        path = request.url.path
        if path == "/containers/json":
            self.filters.append(request.url.params.get("filters", ""))
            return httpx2.Response(200, json=[{"Id": cid} for cid in self.containers])
        if path.endswith("/json"):
            cid = path.split("/")[2]
            return httpx2.Response(200, json=self.containers[cid])
        raise AssertionError(f"unexpected call: {request.method} {path}")


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
    """A finished subprocess: its streams already whole, its return code already known."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"", delay: float = 0.0) -> None:
        """Hold the finished streams, the return code, and an optional wait delay."""
        self.returncode = returncode
        self.stdout = FakeReader(stdout)
        self.stderr = FakeReader(stderr)
        self._out = stdout
        self._err = stderr
        self._delay = delay
        self.pid = reaped_pid()

    async def wait(self) -> int:
        if self._delay:
            await asyncio.sleep(self._delay)
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


def failing_run(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    """Replace the streaming run with one that leaves the way a timeout or a cancellation does."""

    async def fake_run(**_: object) -> tuple[int, object, object]:
        raise error

    monkeypatch.setattr("dirigent_blocks.subprocess.run", fake_run)


def install_daemon(monkeypatch: pytest.MonkeyPatch, daemon: FakeComposeDaemon) -> None:
    """Point the status read at a fake daemon behind a mock transport."""

    def fake_connect(socket_path: str | None, timeout: float, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(daemon))

    monkeypatch.setattr("dirigent_blocks.compose.connect", fake_connect)


# -- the block declares itself unsafe --------------------------------------------


def test_both_blocks_declare_that_they_execute_locally() -> None:
    assert DockerComposeUpOperator.spec.local_execution is True
    assert DockerComposeDownOperator.spec.local_execution is True
    assert DockerComposeUpOperator.spec.idempotent is False


# -- config validators -----------------------------------------------------------


def test_up_requires_exactly_one_of_file_or_content() -> None:
    with pytest.raises(ValidationError, match="exactly one of them"):
        DockerComposeUpConfig()
    with pytest.raises(ValidationError, match="exactly one of them"):
        DockerComposeUpConfig(file="a.yaml", content="services: {}")


def test_up_refuses_a_compose_file_that_climbs_out_of_scratch() -> None:
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerComposeUpConfig(file="/etc/compose.yaml")
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerComposeUpConfig(file="../compose.yaml")


def test_up_refuses_to_inherit_the_instances_own_configuration() -> None:
    with pytest.raises(ValidationError) as raised:
        DockerComposeUpConfig(content="services: {}", env_allowlist=["DIRIGENT_SECRET_KEY"])
    assert "DIRIGENT_SECRET_KEY" in str(raised.value)


def test_down_takes_at_most_one_compose_file_form() -> None:
    with pytest.raises(ValidationError, match="at most one"):
        DockerComposeDownConfig(file="a.yaml", content="services: {}")
    DockerComposeDownConfig()  # neither is fine: down works by project label alone


# -- argv assembly ---------------------------------------------------------------


def test_up_argv_is_assembled_flag_by_flag() -> None:
    config = DockerComposeUpConfig(content="services: {}", wait=True, wait_timeout=timedelta(seconds=90))
    argv = up_argv(config, "proj", Path("/scratch/docker-compose.yaml"), Path("/scratch"))
    assert argv == [
        "docker",
        "compose",
        "--project-name",
        "proj",
        "--project-directory",
        "/scratch",
        "-f",
        "/scratch/docker-compose.yaml",
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "90",
        "--remove-orphans",
        "--pull",
        "missing",
    ]


def test_up_argv_carries_profiles_and_env_files() -> None:
    config = DockerComposeUpConfig(
        content="services: {}", profiles=["gpu"], env_files=[".env"], remove_orphans=False, pull="always"
    )
    argv = up_argv(config, "proj", Path("/scratch/docker-compose.yaml"), Path("/scratch"))
    assert "--profile" in argv and "gpu" in argv
    assert "--env-file" in argv and "/scratch/.env" in argv
    assert "--remove-orphans" not in argv
    assert argv[-2:] == ["--pull", "always"]


def test_down_argv_is_assembled_flag_by_flag() -> None:
    config = DockerComposeDownConfig(down_volumes=True, down_timeout=timedelta(seconds=25), down_remove_images="all")
    argv = down_argv(config, "proj", None, Path("/scratch"))
    assert argv == [
        "docker",
        "compose",
        "--project-name",
        "proj",
        "--project-directory",
        "/scratch",
        "down",
        "-v",
        "--timeout",
        "25",
        "--remove-orphans",
        "--rmi",
        "all",
    ]


# -- the API status read ---------------------------------------------------------


async def test_read_status_parses_services_health_ports_and_networks(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = FakeComposeDaemon([WEB_CONTAINER, DB_CONTAINER])
    install_daemon(monkeypatch, daemon)

    services, networks, default_network = await read_status(None, 60.0, "proj")

    assert [service.name for service in services] == ["proj-db-1", "proj-web-1"], "services are sorted by name"
    web = next(service for service in services if service.service == "web")
    assert web.image == "nginx:alpine"
    assert web.state == "running"
    assert web.health == "healthy"
    assert web.publishers[0].published_port == 8080
    assert web.publishers[0].target_port == 80
    assert web.publishers[0].protocol == "tcp"
    assert web.publishers[0].url == "0.0.0.0"
    assert default_network == "proj_default"
    assert networks == ["proj_default"]
    assert "com.docker.compose.project=proj" in daemon.filters[0]


# -- execute: up -----------------------------------------------------------------


async def test_up_brings_the_stack_up_then_reports_its_state(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0, stdout=b"Started\n"))
    install_daemon(monkeypatch, FakeComposeDaemon([WEB_CONTAINER]))

    output = await DockerComposeUpOperator().execute(
        DockerComposeUpConfig(content="services:\n  web:\n    image: nginx:alpine", wait=True), local_ctx.as_context()
    )

    assert isinstance(output, DockerComposeUpOutput)
    assert output.up is True
    assert output.project == f"dirigent-{local_ctx.run_id.hex}"
    assert output.default_network == f"{output.project}_default"
    assert [service.service for service in output.services] == ["web"]
    assert output.services[0].health == "healthy"
    assert output.stdout_uri.startswith(local_ctx.scratch)
    up_call = next(call for call in calls if "up" in call)
    assert up_call[:4] == ["docker", "compose", "--project-name", output.project]
    assert "--wait" in up_call


async def test_a_failed_up_cleans_up_the_project_before_failing(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(argv: list[str]) -> FakeProcess:
        if "up" in argv:
            return FakeProcess(1, stderr=b"service web failed to build\n")
        return FakeProcess(0)

    calls = scripted_exec(monkeypatch, respond)

    with pytest.raises(BlockFailure) as raised:
        await DockerComposeUpOperator().execute(
            DockerComposeUpConfig(content="services:\n  web:\n    image: nope"), local_ctx.as_context()
        )

    assert raised.value.error_class is ErrorClass.UNKNOWN
    assert "up exited 1" in str(raised.value)
    down_calls = [call for call in calls if "down" in call]
    assert len(down_calls) == 1, "a failed up tears its own half-built project down"


async def test_a_failed_up_without_cleanup_leaves_the_project_alone(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(1, stderr=b"boom\n"))

    with pytest.raises(BlockFailure):
        await DockerComposeUpOperator().execute(
            DockerComposeUpConfig(content="services: {}", cleanup=False), local_ctx.as_context()
        )

    assert not [call for call in calls if "down" in call], "cleanup off means no teardown"


async def test_an_unreachable_daemon_on_up_is_transient(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(argv: list[str]) -> FakeProcess:
        if "up" in argv:
            return FakeProcess(1, stderr=b"Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n")
        return FakeProcess(0)

    scripted_exec(monkeypatch, respond)

    with pytest.raises(BlockFailure) as raised:
        await DockerComposeUpOperator().execute(DockerComposeUpConfig(content="services: {}"), local_ctx.as_context())
    assert raised.value.error_class is ErrorClass.TRANSIENT


async def test_an_up_that_outlives_its_timeout_is_transient(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_exec(monkeypatch, lambda argv: FakeProcess(0, delay=5.0))

    with pytest.raises(BlockFailure) as raised:
        await DockerComposeUpOperator().execute(
            DockerComposeUpConfig(content="services: {}", timeout=timedelta(milliseconds=200)),
            local_ctx.as_context(),
        )
    assert raised.value.error_class is ErrorClass.TRANSIENT
    assert "did not finish" in str(raised.value)


async def test_two_compose_steps_of_one_run_each_write_their_own_file(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two steps differ only in their key, and the generated file is per attempt, not per run."""
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    install_daemon(monkeypatch, FakeComposeDaemon([WEB_CONTAINER]))
    root = local_root(local_ctx.as_context())
    assert root is not None

    local_ctx.step = "first"
    first = await DockerComposeUpOperator().execute(
        DockerComposeUpConfig(content="services:\n  first: {}"), local_ctx.as_context()
    )
    local_ctx.step = "second"
    second = await DockerComposeUpOperator().execute(
        DockerComposeUpConfig(content="services:\n  second: {}"), local_ctx.as_context()
    )

    assert isinstance(first, DockerComposeUpOutput)
    assert isinstance(second, DockerComposeUpOutput)
    assert first.compose_file != second.compose_file
    assert (root / first.compose_file).read_text() == "services:\n  first: {}"
    assert (root / second.compose_file).read_text() == "services:\n  second: {}"

    files = [call[call.index("-f") + 1] for call in calls if "-f" in call]
    assert files == [str(root / first.compose_file), str(root / second.compose_file)]
    for call in calls:
        assert call[call.index("--project-directory") + 1] == str(root), "the project directory stays the run root"


async def test_two_fan_out_items_of_one_step_each_write_their_own_file(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    install_daemon(monkeypatch, FakeComposeDaemon([WEB_CONTAINER]))

    local_ctx.run_item_id = uuid4()
    await DockerComposeUpOperator().execute(
        DockerComposeUpConfig(content="services:\n  one: {}"), local_ctx.as_context()
    )
    local_ctx.run_item_id = uuid4()
    await DockerComposeUpOperator().execute(
        DockerComposeUpConfig(content="services:\n  two: {}"), local_ctx.as_context()
    )

    files = {call[call.index("-f") + 1] for call in calls if "-f" in call}
    assert len(files) == 2


async def test_a_named_file_still_resolves_against_the_run_root(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    install_daemon(monkeypatch, FakeComposeDaemon([WEB_CONTAINER]))
    root = local_root(local_ctx.as_context())
    assert root is not None
    (root / "stack.yaml").write_text("services: {}")

    output = await DockerComposeUpOperator().execute(DockerComposeUpConfig(file="stack.yaml"), local_ctx.as_context())

    assert isinstance(output, DockerComposeUpOutput)
    assert output.compose_file == "stack.yaml"
    up_call = next(call for call in calls if "up" in call)
    assert up_call[up_call.index("-f") + 1] == str(root / "stack.yaml")


async def test_an_up_that_times_out_tears_the_half_built_stack_down(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI never reports an exit code, and containers it already started are still up."""
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    failing_run(monkeypatch, BlockFailure("docker compose up did not finish", error_class=ErrorClass.TRANSIENT))

    with pytest.raises(BlockFailure):
        await DockerComposeUpOperator().execute(DockerComposeUpConfig(content="services: {}"), local_ctx.as_context())

    assert [call for call in calls if "down" in call], "a bring-up that timed out cleans up after itself"


async def test_a_cancelled_up_tears_the_half_built_stack_down(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine cancels the step from outside, and the teardown runs anyway."""
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    failing_run(monkeypatch, asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await DockerComposeUpOperator().execute(DockerComposeUpConfig(content="services: {}"), local_ctx.as_context())

    assert [call for call in calls if "down" in call], "a cancelled bring-up cleans up after itself"


async def test_an_abandoned_up_with_cleanup_off_leaves_the_project_alone(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    failing_run(monkeypatch, asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await DockerComposeUpOperator().execute(
            DockerComposeUpConfig(content="services: {}", cleanup=False), local_ctx.as_context()
        )

    assert not calls


async def test_a_compose_file_is_written_to_the_work_directory_whatever_scratch_is(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compose CLI opens a real file, so it comes from the work directory, not storage."""
    local_ctx.scratch_uri = "s3://bucket/artifacts/runs/one"
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    await DockerComposeUpOperator().execute(DockerComposeUpConfig(content="services: {}"), local_ctx.as_context())
    named = next(argv[argv.index("-f") + 1] for argv in calls if "-f" in argv)
    assert Path(named).is_relative_to(local_ctx.work)


# -- execute: down ---------------------------------------------------------------


async def test_down_tears_the_project_down_by_its_deterministic_name(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))

    output = await DockerComposeDownOperator().execute(DockerComposeDownConfig(), local_ctx.as_context())

    assert isinstance(output, DockerComposeDownOutput)
    assert output.torn_down is True
    assert output.project == f"dirigent-{local_ctx.run_id.hex}"
    down_call = calls[0]
    assert down_call[:4] == ["docker", "compose", "--project-name", output.project]
    assert "down" in down_call and "-f" not in down_call, "down works by project label without a file"


async def test_up_and_down_default_their_project_name_so_a_run_matches_itself(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither config names a project, so both derive the same one from the run id."""
    calls = scripted_exec(monkeypatch, lambda argv: FakeProcess(0))
    install_daemon(monkeypatch, FakeComposeDaemon([WEB_CONTAINER]))

    up = await DockerComposeUpOperator().execute(DockerComposeUpConfig(content="services: {}"), local_ctx.as_context())
    down = await DockerComposeDownOperator().execute(DockerComposeDownConfig(), local_ctx.as_context())

    assert isinstance(up, DockerComposeUpOutput)
    assert isinstance(down, DockerComposeDownOutput)
    assert up.project == down.project == f"dirigent-{local_ctx.run_id.hex}"
    up_project = next(call for call in calls if "up" in call)[3]
    down_project = next(call for call in calls if "down" in call)[3]
    assert up_project == down_project


async def test_a_failed_down_reports_the_reason(local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted_exec(monkeypatch, lambda argv: FakeProcess(1, stderr=b"no such project\n"))
    with pytest.raises(BlockFailure) as raised:
        await DockerComposeDownOperator().execute(DockerComposeDownConfig(), local_ctx.as_context())
    assert "down exited 1" in str(raised.value)
    assert "no such project" in str(raised.value)


def test_the_filters_sent_are_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = FakeComposeDaemon([WEB_CONTAINER])
    install_daemon(monkeypatch, daemon)
    asyncio.run(read_status(None, 60.0, "proj"))
    parsed = json.loads(daemon.filters[0])
    assert parsed == {"label": ["com.docker.compose.project=proj"]}


# -- against a real daemon -------------------------------------------------------

from dirigent_blocks.docker import DockerRunConfig, DockerRunOperator, socket_path  # noqa: E402
from dirigent_plugin import ProbeStatus, RemoteHandle  # noqa: E402

requires_daemon = pytest.mark.skipif(
    not Path(socket_path(DockerRunConfig(image="alpine:3"))).exists(),
    reason="no Docker daemon socket is reachable",
)

TWO_SERVICE_STACK = """
services:
  first:
    image: alpine:3
    command: sleep 300
  second:
    image: alpine:3
    command: sleep 300
"""


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
async def test_a_real_stack_comes_up_is_joined_and_torn_down(local_ctx: FakeContext) -> None:
    up = await DockerComposeUpOperator().execute(
        DockerComposeUpConfig(content=TWO_SERVICE_STACK, wait=True), local_ctx.as_context()
    )
    assert isinstance(up, DockerComposeUpOutput)
    try:
        assert sorted(service.service for service in up.services) == ["first", "second"]
        assert all(service.state == "running" for service in up.services)
        assert up.default_network in up.networks

        # A docker.run step joins the compose network by the name the up step reported and
        # resolves a service on it, which is the whole point of bringing the stack up.
        drive = DockerRunConfig(
            image="alpine:3",
            command="getent hosts first",
            network=up.default_network,
        )
        handle = await DockerRunOperator().execute(drive, local_ctx.as_context())
        assert isinstance(handle, RemoteHandle)
        assert await _drive_until_terminal(handle, drive, local_ctx) is ProbeStatus.SUCCEEDED
    finally:
        down = await DockerComposeDownOperator().execute(
            DockerComposeDownConfig(project_name=up.project, down_volumes=True), local_ctx.as_context()
        )
        assert isinstance(down, DockerComposeDownOutput)
        assert down.torn_down is True
