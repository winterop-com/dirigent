"""Tests for docker.run: the framed log stream, the daemon conversation, and a real container."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from pydantic import JsonValue, ValidationError

from dirigent_blocks.docker import (
    LOGS_SINCE,
    STDERR_FRAME,
    STDOUT_FRAME,
    DaemonEndpoint,
    DockerRunConfig,
    DockerRunOperator,
    DockerRunOutput,
    cli_plugin_dirs,
    demultiplex,
    open_client,
    resolve_endpoint,
    socket_path,
    split_image,
    write_cli_config,
)
from dirigent_common import SHELL_MEDIA_TYPE
from dirigent_plugin import BlockFailure, ErrorClass, ProbeResult, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext

CONTAINER_ID = "c0ffee1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


def frame(stream: int, payload: bytes) -> bytes:
    """Build one frame of Docker's multiplexed log stream."""
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


class FakeDaemon:
    """A Docker daemon good enough to drive the block, remembering everything it was asked."""

    def __init__(self) -> None:
        """Start with a running container, no logs, and no scripted refusals."""
        self.requests: list[httpx2.Request] = []
        self.state: dict[str, JsonValue] = {"Status": "running", "Running": True, "ExitCode": 0}
        self.logs = b""
        self.log_reads: list[str] = []
        """The ``since`` each log read asked for, which is how a cursor test reads the advance."""

        self.known = True
        self.pulled: list[str] = []
        self.removed: list[str] = []
        self.killed: list[str] = []
        self.kill_status = 204
        self.create_response: httpx2.Response | None = None

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Answer one Docker Engine API call."""
        self.requests.append(request)
        path = request.url.path
        if path == "/images/create":
            self.pulled.append(f"{request.url.params['fromImage']}:{request.url.params['tag']}")
            return httpx2.Response(200, content=b'{"status":"Downloaded"}')
        if path == "/containers/create":
            return self.create_response or httpx2.Response(201, json={"Id": CONTAINER_ID, "Warnings": []})
        if path.endswith("/start"):
            return httpx2.Response(204)
        if path.endswith("/json"):
            if not self.known:
                return httpx2.Response(404, json={"message": "No such container"})
            return httpx2.Response(200, json={"Id": CONTAINER_ID, "State": self.state})
        if path.endswith("/logs"):
            self.log_reads.append(request.url.params.get("since", ""))
            return httpx2.Response(200, content=self.logs)
        if path.endswith("/kill"):
            self.killed.append(path)
            if self.kill_status == 204:
                return httpx2.Response(204)
            return httpx2.Response(self.kill_status, json={"message": "the container is not running"})
        if request.method == "DELETE":
            self.removed.append(path)
            return httpx2.Response(204)
        raise AssertionError(f"the block made an unexpected call: {request.method} {path}")

    def creation(self) -> dict[str, JsonValue]:
        """Read back the body the block posted to /containers/create."""
        for request in self.requests:
            if request.url.path == "/containers/create":
                return cast("dict[str, JsonValue]", json.loads(request.content))
        raise AssertionError("the block never created a container")

    def exited(self, code: int) -> None:
        """Script the container as finished with a given exit code."""
        self.state = {"Status": "exited", "Running": False, "ExitCode": code}


@pytest.fixture
def daemon(monkeypatch: pytest.MonkeyPatch) -> FakeDaemon:
    """Install a fake daemon behind the block's socket client."""
    fake = FakeDaemon()

    def fake_connect(config: DockerRunConfig, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(fake))

    monkeypatch.setattr("dirigent_blocks.docker.connect", fake_connect)
    return fake


def handle_for(config: DockerRunConfig, ref: str = CONTAINER_ID) -> RemoteHandle:
    """Build the handle a previous execute would have returned."""
    return RemoteHandle(block_id="docker.run", ref=ref, meta={"image": config.image})


# -- the log demultiplexer -------------------------------------------------------


def test_an_empty_stream_demultiplexes_to_two_empty_streams() -> None:
    assert demultiplex(b"") == (b"", b"")


def test_one_frame_lands_on_the_stream_its_header_names() -> None:
    assert demultiplex(frame(STDOUT_FRAME, b"hello\n")) == (b"hello\n", b"")
    assert demultiplex(frame(STDERR_FRAME, b"oops\n")) == (b"", b"oops\n")


def test_many_frames_are_joined_in_order() -> None:
    payload = frame(STDOUT_FRAME, b"one\n") + frame(STDOUT_FRAME, b"two\n") + frame(STDOUT_FRAME, b"three\n")
    assert demultiplex(payload) == (b"one\ntwo\nthree\n", b"")


def test_interleaved_frames_are_split_by_stream_and_keep_their_own_order() -> None:
    payload = (
        frame(STDOUT_FRAME, b"out1\n")
        + frame(STDERR_FRAME, b"err1\n")
        + frame(STDOUT_FRAME, b"out2\n")
        + frame(STDERR_FRAME, b"err2\n")
    )
    assert demultiplex(payload) == (b"out1\nout2\n", b"err1\nerr2\n")


def test_a_frame_longer_than_the_buffer_contributes_what_actually_arrived() -> None:
    truncated = frame(STDOUT_FRAME, b"the whole line\n")[:-6]
    assert demultiplex(truncated) == (b"the whole", b"")


def test_a_frame_cut_short_stops_the_walk_rather_than_misreading_the_rest() -> None:
    payload = frame(STDERR_FRAME, b"first\n") + frame(STDOUT_FRAME, b"second")[:-3]
    assert demultiplex(payload) == (b"sec", b"first\n")


def test_a_partial_header_at_the_end_is_ignored() -> None:
    assert demultiplex(frame(STDOUT_FRAME, b"done\n") + b"\x01\x00\x00") == (b"done\n", b"")


def test_a_zero_length_frame_contributes_nothing() -> None:
    payload = frame(STDOUT_FRAME, b"") + frame(STDOUT_FRAME, b"after\n")
    assert demultiplex(payload) == (b"after\n", b"")


def test_the_stdin_frame_type_is_read_as_stdout() -> None:
    assert demultiplex(frame(0, b"raw\n")) == (b"raw\n", b"")


# -- the CLI's plugin directories ------------------------------------------------


def test_the_plugin_directory_is_found_under_the_named_docker_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugins = tmp_path / "config" / "cli-plugins"
    plugins.mkdir(parents=True)
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "config"))
    assert cli_plugin_dirs() == [plugins]


def test_the_plugin_directory_is_found_under_home_when_no_config_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugins = tmp_path / ".docker" / "cli-plugins"
    plugins.mkdir(parents=True)
    monkeypatch.delenv("DOCKER_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert cli_plugin_dirs() == [plugins]


def test_a_worker_with_no_plugin_directory_has_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "config"))
    assert cli_plugin_dirs() == []


def test_the_run_config_names_the_workers_plugin_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugins = tmp_path / "config" / "cli-plugins"
    plugins.mkdir(parents=True)
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "config"))

    write_cli_config(tmp_path / "run" / ".docker")

    written = json.loads((tmp_path / "run" / ".docker" / "config.json").read_text())
    assert written == {"cliPluginsExtraDirs": [str(plugins)]}


def test_no_plugin_directory_writes_no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "config"))
    write_cli_config(tmp_path / "run" / ".docker")
    assert not (tmp_path / "run").exists()


# -- the spec and the config -----------------------------------------------------


def test_the_block_declares_that_it_executes_locally() -> None:
    assert DockerRunOperator.spec.id == "docker.run"
    assert DockerRunOperator.spec.local_execution is True
    assert DockerRunOperator.spec.idempotent is False


def test_a_config_naming_both_command_forms_is_refused() -> None:
    with pytest.raises(ValidationError, match="never both"):
        DockerRunConfig(image="alpine", argv=["true"], command="true")


def test_a_config_naming_neither_command_form_is_accepted() -> None:
    config = DockerRunConfig(image="alpine")
    assert config.argv == []
    assert config.command is None


def test_the_shell_form_publishes_itself_as_shell_source() -> None:
    """The form generating itself from this schema edits the shell string as a program."""
    published = DockerRunConfig.model_json_schema()["properties"]["command"]

    assert published["contentMediaType"] == SHELL_MEDIA_TYPE


def test_a_config_naming_two_cpu_quotas_is_refused() -> None:
    with pytest.raises(ValidationError, match="either cpus or nano_cpus"):
        DockerRunConfig(image="alpine", cpus=1.5, nano_cpus=1_500_000_000)


def test_a_mount_that_climbs_out_of_its_directory_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerRunConfig(image="alpine", inputs={"/etc/passwd": "file://x"})
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerRunConfig(image="alpine", outputs={"../escape.txt": "file://x"})


def test_an_output_landing_in_the_work_directory_cannot_be_absolute_or_climb_out() -> None:
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerRunConfig(image="alpine", outputs={"result.txt": "/etc/passwd"})
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        DockerRunConfig(image="alpine", outputs={"result.txt": "../escape.txt"})


def test_a_memory_limit_below_the_daemon_minimum_is_refused() -> None:
    with pytest.raises(ValidationError):
        DockerRunConfig(image="alpine", memory=1024)


def test_the_socket_is_resolved_from_the_config_then_the_environment_then_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    assert socket_path(DockerRunConfig(image="alpine")) == "/var/run/docker.sock"
    monkeypatch.setenv("DOCKER_HOST", "unix:///home/u/.docker/run/docker.sock")
    assert socket_path(DockerRunConfig(image="alpine")) == "/home/u/.docker/run/docker.sock"
    assert socket_path(DockerRunConfig(image="alpine", socket_path="/tmp/d.sock")) == "/tmp/d.sock"


def test_a_unix_docker_host_resolves_to_a_socket_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    default = resolve_endpoint(None)
    assert default.uds == "/var/run/docker.sock"
    assert default.base_url == "http://docker"
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/d.sock")
    named = resolve_endpoint(None)
    assert named.uds == "/run/d.sock"
    assert resolve_endpoint("/tmp/explicit.sock").uds == "/tmp/explicit.sock"


def test_a_tcp_docker_host_resolves_to_an_http_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_TLS_VERIFY", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://192.0.2.1:2375")
    endpoint = resolve_endpoint(None)
    assert endpoint.uds is None, "a tcp daemon is reached over http, not a unix socket"
    assert endpoint.base_url == "http://192.0.2.1:2375"
    assert endpoint.socket is None
    assert endpoint.verify is True
    assert endpoint.cert is None


def test_a_tcp_docker_host_with_tls_resolves_to_https_with_client_certs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://dind:2376")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DOCKER_CERT_PATH", "/certs/client")
    endpoint = resolve_endpoint(None)
    assert endpoint.base_url == "https://dind:2376"
    assert endpoint.verify == "/certs/client/ca.pem"
    assert endpoint.cert == ("/certs/client/cert.pem", "/certs/client/key.pem")


def test_a_tls_endpoint_opens_a_client_carrying_the_client_chain(tmp_path: Path) -> None:
    pem = _self_signed(tmp_path)
    endpoint = DaemonEndpoint(
        base_url="https://dind:2376", uds=None, verify=str(pem), cert=(str(pem), str(pem)), socket=None
    )
    client = open_client(endpoint, 5.0)
    assert str(client.base_url) == "https://dind:2376"


def _self_signed(directory: Path) -> Path:
    """One PEM file standing in for the CA, the certificate and the key a dind sidecar writes."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "dind")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = directory / "bundle.pem"
    pem.write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return pem


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("alpine", ("alpine", "latest")),
        ("alpine:3", ("alpine", "3")),
        ("ghcr.io/org/thing:v2", ("ghcr.io/org/thing", "v2")),
        ("registry.test:5000/thing", ("registry.test:5000/thing", "latest")),
    ],
)
def test_an_image_reference_splits_into_a_repository_and_a_tag(image: str, expected: tuple[str, str]) -> None:
    assert split_image(image) == expected


# -- execute ---------------------------------------------------------------------


async def test_execute_creates_and_starts_a_container_and_returns_a_handle(
    daemon: FakeDaemon, ctx: FakeContext
) -> None:
    config = DockerRunConfig(image="alpine:3", argv=["echo", "hello"])
    handle = await DockerRunOperator().execute(config, ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    assert handle.block_id == "docker.run"
    assert handle.ref == CONTAINER_ID
    assert handle.meta["image"] == "alpine:3"

    calls = [(request.method, request.url.path) for request in daemon.requests]
    assert calls == [("POST", "/containers/create"), ("POST", f"/containers/{CONTAINER_ID}/start")]
    assert daemon.creation()["Cmd"] == ["echo", "hello"]
    assert "container started" in ctx.log.messages()


async def test_the_shell_form_of_a_command_runs_through_sh(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine", command="echo a && echo b"), ctx.as_context())
    assert daemon.creation()["Cmd"] == ["/bin/sh", "-c", "echo a && echo b"]


async def test_no_command_leaves_the_image_entrypoint_alone(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine"), ctx.as_context())
    assert "Cmd" not in daemon.creation()


async def test_the_container_gets_no_network_unless_the_step_asks(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine"), ctx.as_context())
    host = cast("dict[str, JsonValue]", daemon.creation()["HostConfig"])
    assert host["NetworkMode"] == "none"
    assert host["AutoRemove"] is False


async def test_a_declared_network_reaches_the_daemon(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine", network="bridge"), ctx.as_context())
    host = cast("dict[str, JsonValue]", daemon.creation()["HostConfig"])
    assert host["NetworkMode"] == "bridge"


async def test_the_environment_is_an_allowlist_and_not_an_inheritance(
    daemon: FakeDaemon, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLOCKTEST_SECRET", "do-not-leak")
    monkeypatch.setenv("BLOCKTEST_SHARED", "passed-through")
    config = DockerRunConfig(
        image="alpine",
        env={"GREETING": "hei"},
        env_allowlist=["BLOCKTEST_SHARED", "BLOCKTEST_ABSENT"],
    )
    await DockerRunOperator().execute(config, ctx.as_context())
    environment = cast("list[str]", daemon.creation()["Env"])
    assert "BLOCKTEST_SHARED=passed-through" in environment
    assert "GREETING=hei" in environment
    assert not [entry for entry in environment if entry.startswith("BLOCKTEST_SECRET")]
    assert not [entry for entry in environment if entry.startswith("BLOCKTEST_ABSENT")]


async def test_the_resource_limits_reach_the_create_payload(daemon: FakeDaemon, ctx: FakeContext) -> None:
    config = DockerRunConfig(image="alpine", memory=64 * 1024 * 1024, cpus=1.5, pids_limit=32, workdir="/work")
    await DockerRunOperator().execute(config, ctx.as_context())
    payload = daemon.creation()
    host = cast("dict[str, JsonValue]", payload["HostConfig"])
    assert host["Memory"] == 64 * 1024 * 1024
    assert host["NanoCpus"] == 1_500_000_000
    assert host["PidsLimit"] == 32
    assert payload["WorkingDir"] == "/work"
    assert payload["Tty"] is False


async def test_nano_cpus_are_passed_through_unrounded(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine", nano_cpus=250_000_000), ctx.as_context())
    host = cast("dict[str, JsonValue]", daemon.creation()["HostConfig"])
    assert host["NanoCpus"] == 250_000_000


async def test_the_container_is_labelled_with_the_run_it_belongs_to(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine"), ctx.as_context())
    labels = cast("dict[str, JsonValue]", daemon.creation()["Labels"])
    assert labels["dirigent.run"] == str(ctx.run_id)
    assert labels["dirigent.attempt"] == "1"


async def test_a_pull_is_requested_only_when_the_step_asks_for_one(daemon: FakeDaemon, ctx: FakeContext) -> None:
    await DockerRunOperator().execute(DockerRunConfig(image="alpine:3"), ctx.as_context())
    assert daemon.pulled == []
    await DockerRunOperator().execute(DockerRunConfig(image="alpine:3", pull=True), ctx.as_context())
    assert daemon.pulled == ["alpine:3"]


async def test_an_unknown_image_is_a_rejection_rather_than_a_retry(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.create_response = httpx2.Response(404, json={"message": "No such image: nope:latest"})
    with pytest.raises(BlockFailure) as raised:
        await DockerRunOperator().execute(DockerRunConfig(image="nope"), ctx.as_context())
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "No such image" in str(raised.value)


async def test_a_daemon_server_error_is_transient(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.create_response = httpx2.Response(500, json={"message": "daemon is unhappy"})
    with pytest.raises(BlockFailure) as raised:
        await DockerRunOperator().execute(DockerRunConfig(image="alpine"), ctx.as_context())
    assert raised.value.error_class is ErrorClass.TRANSIENT


def test_an_unreachable_daemon_is_transient() -> None:
    operator = DockerRunOperator()
    assert operator.classify_error(FileNotFoundError("no socket there")) is ErrorClass.TRANSIENT
    assert operator.classify_error(httpx2.ConnectError("refused")) is ErrorClass.TRANSIENT
    assert operator.classify_error(BlockFailure("no", error_class=ErrorClass.REJECTED)) is ErrorClass.REJECTED


async def test_a_mount_is_bound_from_the_work_directory_whatever_scratch_is(
    daemon: FakeDaemon, local_ctx: FakeContext
) -> None:
    """A bind is a path on the daemon's filesystem, so it comes from the work directory."""
    local_ctx.scratch_uri = "s3://bucket/artifacts/runs/one"
    config = DockerRunConfig(image="alpine", outputs={"result.txt": "file://out/result.txt"})
    await DockerRunOperator().execute(config, local_ctx.as_context())
    host = cast("dict[str, JsonValue]", daemon.creation()["HostConfig"])
    bound = [str(bind).split(":")[0] for bind in cast("list[JsonValue]", host["Binds"])]
    assert bound and all(Path(path).is_relative_to(local_ctx.work) for path in bound)


async def test_inputs_are_staged_into_a_read_only_mount(daemon: FakeDaemon, local_ctx: FakeContext) -> None:
    source = local_ctx.storage.path_for("file://in/data.csv")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"a,b\n1,2\n")
    config = DockerRunConfig(
        image="alpine",
        inputs={"data.csv": "file://in/data.csv"},
        outputs={"result.txt": "file://out/result.txt"},
    )
    handle = await DockerRunOperator().execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)

    host = cast("dict[str, JsonValue]", daemon.creation()["HostConfig"])
    binds = cast("list[str]", host["Binds"])
    assert binds[0].endswith(":/dirigent/inputs:ro")
    assert binds[1].endswith(":/dirigent/outputs:rw")
    staged = Path(binds[0].split(":")[0]) / "data.csv"
    assert staged.read_bytes() == b"a,b\n1,2\n"
    assert handle.meta["outputs_dir"].endswith("/outputs")


# -- probe -----------------------------------------------------------------------


async def test_a_running_container_probes_as_running(daemon: FakeDaemon, ctx: FakeContext) -> None:
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING


async def test_a_created_but_not_yet_running_container_probes_as_running(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.state = {"Status": "created", "Running": False, "ExitCode": 0}
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING


async def test_a_container_that_exited_cleanly_probes_as_succeeded(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.exited(0)
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.SUCCEEDED


async def test_a_failed_container_probes_as_failed_with_the_tail_of_its_logs(
    daemon: FakeDaemon, ctx: FakeContext
) -> None:
    daemon.exited(3)
    daemon.logs = frame(STDOUT_FRAME, b"working\n") + frame(STDERR_FRAME, b"first problem\nlast problem\n")
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.FAILED
    assert "exited 3" in (probed.message or "")
    assert "last problem" in (probed.message or "")


async def test_a_failed_container_with_only_stdout_still_explains_itself(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.exited(1)
    daemon.logs = frame(STDOUT_FRAME, b"that did not work\n")
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert "that did not work" in (probed.message or "")


async def test_a_silent_failure_still_reports_its_exit_code(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.exited(137)
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.message == "the container exited 137: no output"


async def test_a_container_the_daemon_forgot_probes_as_gone(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.known = False
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.GONE


async def test_a_container_that_exited_non_zero_leaves_nothing_behind(daemon: FakeDaemon, ctx: FakeContext) -> None:
    """Fetch never runs for a failed container, so the failing probe is what removes it."""
    daemon.exited(3)
    daemon.logs = frame(STDERR_FRAME, b"it broke\n")
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.FAILED
    assert daemon.removed == [f"/containers/{CONTAINER_ID}"]


async def test_a_removal_that_fails_does_not_lose_the_probe_result(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDaemon()
    fake.exited(9)

    def refuse_removal(request: httpx2.Request) -> httpx2.Response:
        if request.method == "DELETE":
            raise httpx2.ConnectError("the daemon went away")
        return fake(request)

    def fake_connect(config: DockerRunConfig, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(refuse_removal))

    monkeypatch.setattr("dirigent_blocks.docker.connect", fake_connect)
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())
    assert probed.status is ProbeStatus.FAILED
    assert "exited 9" in (probed.message or "")
    assert "could not be removed" in " ".join(ctx.log.messages())


async def test_a_running_container_streams_what_it_printed_into_the_run(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.logs = frame(STDOUT_FRAME, b"halfway there\n") + frame(STDERR_FRAME, b"a warning\n")
    config = DockerRunConfig(image="alpine")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())

    assert probed.status is ProbeStatus.RUNNING
    assert "halfway there" in ctx.log.messages()
    assert "a warning" in ctx.log.messages()


async def test_a_probe_reads_only_what_was_printed_since_the_last_one(daemon: FakeDaemon, ctx: FakeContext) -> None:
    """The cursor is what makes the live log incremental rather than the same lines again."""
    daemon.logs = frame(STDOUT_FRAME, b"first\n")
    config = DockerRunConfig(image="alpine")
    operator = DockerRunOperator()
    first = await operator.probe(handle_for(config), config, ctx.as_context())
    assert first.meta is not None
    advanced = handle_for(config).model_copy(update={"meta": first.meta})

    daemon.logs = frame(STDOUT_FRAME, b"second\n")
    second = await operator.probe(advanced, config, ctx.as_context())

    assert daemon.log_reads == ["", first.meta[LOGS_SINCE]]
    assert second.meta is not None
    assert second.meta[LOGS_SINCE] > first.meta[LOGS_SINCE]
    assert ctx.log.messages() == ["first", "second"]


async def test_an_advancing_probe_keeps_the_metadata_the_submit_wrote(daemon: FakeDaemon, ctx: FakeContext) -> None:
    """The advance replaces the handle's metadata, so what fetch needs is copied forward."""
    config = DockerRunConfig(image="alpine:3")
    probed = await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())

    assert probed.meta is not None
    assert probed.meta["image"] == "alpine:3"


async def test_a_quiet_container_adds_no_lines_to_the_run(daemon: FakeDaemon, ctx: FakeContext) -> None:
    config = DockerRunConfig(image="alpine")
    await DockerRunOperator().probe(handle_for(config), config, ctx.as_context())

    assert ctx.log.messages() == []


async def test_probing_twice_changes_nothing(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.exited(0)
    config = DockerRunConfig(image="alpine")
    operator = DockerRunOperator()
    first = await operator.probe(handle_for(config), config, ctx.as_context())
    second = await operator.probe(handle_for(config), config, ctx.as_context())
    assert first.status is second.status
    assert daemon.removed == []
    assert daemon.killed == []
    assert {request.method for request in daemon.requests} == {"GET"}


# -- fetch -----------------------------------------------------------------------


async def test_fetch_reports_the_streams_and_stores_them_as_artifacts(
    daemon: FakeDaemon, local_ctx: FakeContext
) -> None:
    daemon.exited(0)
    daemon.logs = frame(STDOUT_FRAME, b"hello\n") + frame(STDERR_FRAME, b"a warning\n")
    config = DockerRunConfig(image="alpine:3")
    output = await DockerRunOperator().fetch(handle_for(config), config, local_ctx.as_context())
    assert isinstance(output, DockerRunOutput)
    assert output.exit_code == 0
    assert output.stdout == "hello\n"
    assert output.stderr == "a warning\n"
    assert output.image == "alpine:3"
    assert output.container_id == CONTAINER_ID
    assert output.stdout_bytes == len(b"hello\n")
    assert output.stderr_bytes == len(b"a warning\n")
    assert output.stdout_truncated is False
    assert output.stderr_truncated is False
    assert local_ctx.storage.path_for(output.stdout_uri).read_bytes() == b"hello\n"
    assert local_ctx.storage.path_for(output.stderr_uri).read_bytes() == b"a warning\n"
    assert "hello" in local_ctx.log.messages()
    assert "container finished" in local_ctx.log.messages()


async def test_fetch_logs_only_what_the_probes_have_not_streamed(daemon: FakeDaemon, local_ctx: FakeContext) -> None:
    """The full read is for storage and the output; the run log gets the rest of the stream.

    A probed container's lines are already in the run log, streamed live by the cursor. The
    daemon filters by ``since``, so asking from the cursor is what keeps fetch from saying
    every line a second time.
    """
    daemon.exited(0)
    daemon.logs = frame(STDOUT_FRAME, b"early\nlate\n")
    config = DockerRunConfig(image="alpine")
    handle = handle_for(config).model_copy(update={"meta": {"image": "alpine", LOGS_SINCE: "123.000000000"}})

    output = await DockerRunOperator().fetch(handle, config, local_ctx.as_context())

    assert daemon.log_reads == ["", "123.000000000"]
    assert output.stdout == "early\nlate\n"


async def test_fetch_on_an_unprobed_container_logs_the_whole_stream(daemon: FakeDaemon, local_ctx: FakeContext) -> None:
    """A container that exited before any probe ran has no cursor: the whole stream logs once."""
    daemon.exited(0)
    daemon.logs = frame(STDOUT_FRAME, b"hello\n")
    config = DockerRunConfig(image="alpine")

    await DockerRunOperator().fetch(handle_for(config), config, local_ctx.as_context())

    assert daemon.log_reads == ["", ""]
    assert "hello" in local_ctx.log.messages()


async def test_fetch_removes_the_container_it_collected(daemon: FakeDaemon, local_ctx: FakeContext) -> None:
    daemon.exited(0)
    config = DockerRunConfig(image="alpine")
    await DockerRunOperator().fetch(handle_for(config), config, local_ctx.as_context())
    assert daemon.removed == [f"/containers/{CONTAINER_ID}"]


async def test_a_removal_that_fails_does_not_lose_a_collected_result(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDaemon()
    fake.exited(0)
    fake.logs = frame(STDOUT_FRAME, b"the work happened\n")

    def refuse_removal(request: httpx2.Request) -> httpx2.Response:
        if request.method == "DELETE":
            raise httpx2.ConnectError("the daemon went away")
        return fake(request)

    def fake_connect(config: DockerRunConfig, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(refuse_removal))

    monkeypatch.setattr("dirigent_blocks.docker.connect", fake_connect)
    config = DockerRunConfig(image="alpine")
    collected = await DockerRunOperator().fetch(handle_for(config), config, local_ctx.as_context())
    assert collected.exit_code == 0
    assert "the work happened" in collected.stdout
    assert "could not be removed" in " ".join(local_ctx.log.messages())


async def test_fetch_collects_the_declared_outputs_back_into_storage(
    daemon: FakeDaemon, local_ctx: FakeContext
) -> None:
    daemon.exited(0)
    config = DockerRunConfig(image="alpine", outputs={"result.txt": "file://out/result.txt"})
    handle = await DockerRunOperator().execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    produced = Path(handle.meta["outputs_dir"]) / "result.txt"
    produced.write_bytes(b"the answer\n")

    output = await DockerRunOperator().fetch(handle, config, local_ctx.as_context())
    assert output.outputs == {"result.txt": "file://out/result.txt"}
    assert local_ctx.storage.path_for("file://out/result.txt").read_bytes() == b"the answer\n"


async def test_fetch_collects_an_output_without_a_scheme_into_the_work_directory(
    daemon: FakeDaemon, local_ctx: FakeContext
) -> None:
    daemon.exited(0)
    config = DockerRunConfig(image="alpine", outputs={"result.txt": "context/result.txt"})
    handle = await DockerRunOperator().execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    produced = Path(handle.meta["outputs_dir"]) / "result.txt"
    produced.write_bytes(b"the answer\n")

    output = await DockerRunOperator().fetch(handle, config, local_ctx.as_context())
    assert output.outputs == {"result.txt": "context/result.txt"}
    assert (local_ctx.work / "context/result.txt").read_bytes() == b"the answer\n"


async def test_a_declared_output_the_container_never_wrote_is_a_rejection(
    daemon: FakeDaemon, local_ctx: FakeContext
) -> None:
    daemon.exited(0)
    config = DockerRunConfig(image="alpine", outputs={"result.txt": "file://out/result.txt"})
    handle = await DockerRunOperator().execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    with pytest.raises(BlockFailure) as raised:
        await DockerRunOperator().fetch(handle, config, local_ctx.as_context())
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "did not write the declared output" in str(raised.value)


async def test_fetch_on_a_container_that_vanished_is_transient(daemon: FakeDaemon, local_ctx: FakeContext) -> None:
    daemon.known = False
    config = DockerRunConfig(image="alpine")
    with pytest.raises(BlockFailure) as raised:
        await DockerRunOperator().fetch(handle_for(config), config, local_ctx.as_context())
    assert raised.value.error_class is ErrorClass.TRANSIENT


async def test_long_output_is_elided_in_the_log_but_whole_in_the_artifact(
    daemon: FakeDaemon, local_ctx: FakeContext
) -> None:
    daemon.exited(0)
    lines = b"".join(f"line {index}\n".encode() for index in range(200))
    daemon.logs = frame(STDOUT_FRAME, lines)
    config = DockerRunConfig(image="alpine")
    output = await DockerRunOperator().fetch(handle_for(config), config, local_ctx.as_context())
    assert local_ctx.storage.path_for(output.stdout_uri).read_bytes() == lines
    assert any("more lines, see the stdout artifact" in message for message in local_ctx.log.messages())


# -- cancel ----------------------------------------------------------------------


async def test_cancel_kills_the_container(daemon: FakeDaemon, ctx: FakeContext) -> None:
    config = DockerRunConfig(image="alpine")
    assert await DockerRunOperator().cancel(handle_for(config), config, ctx.as_context()) is True
    assert daemon.killed == [f"/containers/{CONTAINER_ID}/kill"]


async def test_a_cancelled_container_leaves_nothing_behind(daemon: FakeDaemon, ctx: FakeContext) -> None:
    config = DockerRunConfig(image="alpine")
    await DockerRunOperator().cancel(handle_for(config), config, ctx.as_context())
    assert daemon.removed == [f"/containers/{CONTAINER_ID}"]


async def test_cancelling_a_stopped_container_still_counts_as_cancelled(daemon: FakeDaemon, ctx: FakeContext) -> None:
    daemon.kill_status = 409
    config = DockerRunConfig(image="alpine")
    assert await DockerRunOperator().cancel(handle_for(config), config, ctx.as_context()) is True


async def test_cancelling_a_container_the_daemon_forgot_is_not_an_exception(
    daemon: FakeDaemon, ctx: FakeContext
) -> None:
    daemon.kill_status = 404
    config = DockerRunConfig(image="alpine")
    assert await DockerRunOperator().cancel(handle_for(config), config, ctx.as_context()) is False


async def test_cancel_survives_a_daemon_it_cannot_reach(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no daemon")

    def fake_connect(config: DockerRunConfig, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(refuse))

    monkeypatch.setattr("dirigent_blocks.docker.connect", fake_connect)
    config = DockerRunConfig(image="alpine")
    assert await DockerRunOperator().cancel(handle_for(config), config, ctx.as_context()) is False
    assert "could not be told" in " ".join(ctx.log.messages())


async def test_a_missing_socket_is_named_rather_than_an_errno(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ConnectError: [Errno 2]` is what a containerized worker sees; the failure has to say why."""

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection failed") from FileNotFoundError(2, "No such file or directory")

    def fake_connect(config: DockerRunConfig, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(refuse))

    monkeypatch.setattr("dirigent_blocks.docker.connect", fake_connect)
    config = DockerRunConfig(image="alpine")
    with pytest.raises(BlockFailure) as failure:
        await DockerRunOperator().execute(config, ctx.as_context())
    assert "root on the host" in str(failure.value)
    assert failure.value.error_class is ErrorClass.REJECTED


async def test_a_daemon_that_is_merely_down_stays_transient(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused") from ConnectionRefusedError(61, "Connection refused")

    def fake_connect(config: DockerRunConfig, environ: object = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(refuse))

    monkeypatch.setattr("dirigent_blocks.docker.connect", fake_connect)
    config = DockerRunConfig(image="alpine")
    with pytest.raises(BlockFailure) as failure:
        await DockerRunOperator().execute(config, ctx.as_context())
    assert failure.value.error_class is ErrorClass.TRANSIENT


# -- against a real daemon -------------------------------------------------------

TEST_IMAGE = "alpine:3"

requires_daemon = pytest.mark.skipif(
    not Path(socket_path(DockerRunConfig(image=TEST_IMAGE))).exists(),
    reason="no Docker daemon socket is reachable",
)


async def until_terminal(handle: RemoteHandle, config: DockerRunConfig, ctx: FakeContext) -> ProbeResult:
    """Poll the way the engine polls, because the block itself never waits."""
    operator = DockerRunOperator()
    for _ in range(300):
        probed = await operator.probe(handle, config, ctx.as_context())
        if probed.status is not ProbeStatus.RUNNING:
            ctx.log.info("last probe", detail=probed.message or "")
            return probed
        await asyncio.sleep(0.1)
    raise AssertionError("the container never finished")


@pytest.mark.docker
@requires_daemon
async def test_a_real_container_runs_end_to_end(local_ctx: FakeContext) -> None:
    config = DockerRunConfig(image=TEST_IMAGE, argv=["/bin/sh", "-c", "echo hello; echo trouble 1>&2"])
    operator = DockerRunOperator()
    handle = await operator.execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    assert (await until_terminal(handle, config, local_ctx)).status is ProbeStatus.SUCCEEDED

    output = await operator.fetch(handle, config, local_ctx.as_context())
    assert output.exit_code == 0
    assert output.stdout.strip() == "hello"
    assert output.stderr.strip() == "trouble"
    assert local_ctx.storage.path_for(output.stdout_uri).read_bytes().strip() == b"hello"

    probed = await operator.probe(handle, config, local_ctx.as_context())
    assert probed.status is ProbeStatus.GONE, "fetch removed the container it collected"


@pytest.mark.docker
@requires_daemon
async def test_a_real_container_has_its_log_streamed_as_it_runs(local_ctx: FakeContext) -> None:
    """The cursor is a timestamp the daemon interprets, so only a real daemon proves it filters."""
    config = DockerRunConfig(image=TEST_IMAGE, command="echo first; sleep 1; echo second; sleep 1")
    operator = DockerRunOperator()
    handle = await operator.execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)

    cursor, settled = handle, None
    for _ in range(200):
        probed = await operator.probe(cursor, config, local_ctx.as_context())
        if probed.status is not ProbeStatus.RUNNING:
            settled = probed
            break
        assert probed.meta is not None
        cursor = cursor.model_copy(update={"meta": probed.meta})
        await asyncio.sleep(0.05)

    assert settled is not None, "the container never finished"
    assert settled.status is ProbeStatus.SUCCEEDED
    assert local_ctx.log.messages().count("first") == 1, "the cursor let a line arrive twice"
    assert local_ctx.log.messages().count("second") == 1, "a line printed mid-run never arrived"

    output = await operator.fetch(cursor, config, local_ctx.as_context())
    assert output.stdout.split() == ["first", "second"], "fetch still stores the whole of both streams"


@pytest.mark.docker
@requires_daemon
async def test_a_real_container_that_exits_non_zero_probes_as_failed(local_ctx: FakeContext) -> None:
    config = DockerRunConfig(image=TEST_IMAGE, command="echo bad things 1>&2; exit 3")
    operator = DockerRunOperator()
    handle = await operator.execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    settled = await until_terminal(handle, config, local_ctx)
    assert settled.status is ProbeStatus.FAILED
    assert "exited 3" in (settled.message or "")
    assert "bad things" in (settled.message or "")

    probed = await operator.probe(handle, config, local_ctx.as_context())
    assert probed.status is ProbeStatus.GONE, "the failing probe removed the container it read"


@pytest.mark.docker
@requires_daemon
async def test_a_real_container_sees_its_environment_and_no_network(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLOCKTEST_SECRET", "do-not-leak")
    config = DockerRunConfig(
        image=TEST_IMAGE,
        command="echo [$GREETING] [$BLOCKTEST_SECRET]; ip -o addr show scope global | wc -l",
        env={"GREETING": "hei"},
    )
    operator = DockerRunOperator()
    handle = await operator.execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    assert (await until_terminal(handle, config, local_ctx)).status is ProbeStatus.SUCCEEDED
    output = await operator.fetch(handle, config, local_ctx.as_context())
    assert "[hei] []" in output.stdout, "the container sees what the step set and nothing the worker has"
    assert output.stdout.strip().splitlines()[-1].strip() == "0", "the container has no routable address"


@pytest.mark.docker
@requires_daemon
async def test_a_real_container_reads_an_input_and_writes_an_output(local_ctx: FakeContext) -> None:
    source = local_ctx.storage.path_for("file://in/data.txt")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"seven\n")
    config = DockerRunConfig(
        image=TEST_IMAGE,
        command="tr a-z A-Z < /dirigent/inputs/data.txt > /dirigent/outputs/result.txt",
        inputs={"data.txt": "file://in/data.txt"},
        outputs={"result.txt": "file://out/result.txt"},
    )
    operator = DockerRunOperator()
    handle = await operator.execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    assert (await until_terminal(handle, config, local_ctx)).status is ProbeStatus.SUCCEEDED

    output = await operator.fetch(handle, config, local_ctx.as_context())
    assert output.outputs == {"result.txt": "file://out/result.txt"}
    assert local_ctx.storage.path_for("file://out/result.txt").read_bytes() == b"SEVEN\n"


@pytest.mark.docker
@requires_daemon
async def test_a_real_container_can_be_cancelled_while_it_runs(local_ctx: FakeContext) -> None:
    config = DockerRunConfig(image=TEST_IMAGE, argv=["sleep", "120"])
    operator = DockerRunOperator()
    handle = await operator.execute(config, local_ctx.as_context())
    assert isinstance(handle, RemoteHandle)
    assert await operator.cancel(handle, config, local_ctx.as_context()) is True
    probed = await operator.probe(handle, config, local_ctx.as_context())
    assert probed.status is ProbeStatus.GONE, "cancel removed the container it killed"


def test_a_container_cannot_allowlist_the_instances_own_configuration() -> None:
    """The same escalation as ``shell.run``, through the same document field."""
    with pytest.raises(ValidationError) as raised:
        DockerRunConfig(image="alpine", env_allowlist=["DIRIGENT_SECRET_KEY"])
    assert "DIRIGENT_SECRET_KEY" in str(raised.value)


async def test_container_logs_are_written_while_they_are_still_arriving() -> None:
    """Writing only once the stream has ended means holding all of it to get there.

    Counting writes proves nothing: a write per frame happens either way. What separates
    streaming from buffering is whether any of it reaches storage while more is still coming.
    """
    from contextlib import asynccontextmanager

    from dirigent_blocks.docker import drain_logs

    delivered = 0
    wrote_while_arriving = False

    async def arriving() -> AsyncGenerator[bytes]:
        nonlocal delivered
        for index in range(8):
            delivered += 1
            yield frame(STDOUT_FRAME, f"line {index}\n".encode())

    class Stub:
        """A daemon that hands its log stream over in pieces."""

        @asynccontextmanager
        async def streamed_logs(self, container: str, since: str = "") -> AsyncGenerator[Any]:
            yield arriving()

    class Watching:
        """A sink that notices whether the stream was still going when it was written to."""

        async def write(self, data: bytes) -> int:
            nonlocal wrote_while_arriving
            if delivered < 8:
                wrote_while_arriving = True
            return len(data)

    stdout, _ = await drain_logs(cast("Any", Stub()), "abc", 4096, sinks=(Watching(), Watching()))

    assert stdout.total_bytes > 0
    assert wrote_while_arriving, "nothing was stored until the whole stream had arrived"


async def test_a_frame_split_across_chunks_is_not_lost(daemon: FakeDaemon, local_ctx: FakeContext) -> None:
    """A chunk off the wire is not a frame, so a frame arriving in pieces has to survive them."""
    from dirigent_blocks.docker import Frames

    payload = frame(STDOUT_FRAME, b"a message that spans chunks")
    frames = Frames()

    found: list[tuple[bool, bytes]] = []
    for index in range(0, len(payload), 3):
        found.extend(frames.take(payload[index : index + 3]))

    assert found == [(False, b"a message that spans chunks")]
