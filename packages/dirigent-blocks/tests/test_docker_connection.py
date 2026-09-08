"""Tests for the docker connection kind: its shape, its materialised files, and its check."""

import asyncio
import os
import shutil
import stat
import subprocess as std_subprocess
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks.docker import (
    DAEMON_ENV,
    DaemonEndpoint,
    DockerConnectionConfig,
    DockerConnectionKind,
    DockerRunConfig,
    DockerRunOperator,
    daemon_environment,
    resolve_endpoint,
    sealed,
)
from dirigent_plugin import RemoteHandle
from dirigent_testing import FakeContext

CA = "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----"
CERT = "-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----"
KEY = "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----"

REMOTE = DockerConnectionConfig(
    host="tcp://dind:2376", tls_ca=SecretStr(CA), tls_cert=SecretStr(CERT), tls_key=SecretStr(KEY)
)
REGISTRY = DockerConnectionConfig(registry="ghcr.io", username="robot", password=SecretStr("s3cr3t"))


def found(name: str, **_: object) -> str:
    """Stand in for shutil.which on a host that has the docker CLI."""
    del name
    return "/usr/bin/docker"


def missing(name: str, **_: object) -> str | None:
    """Stand in for shutil.which on a host that has no docker CLI."""
    del name
    return None


class FakeProcess:
    """A finished subprocess: its streams already whole, its return code already known."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        """Hold the finished streams and the return code."""
        self.returncode = returncode
        self._out = stdout
        self._err = stderr
        child = std_subprocess.Popen(["true"])  # noqa: S603, S607
        child.wait()
        self.pid = child.pid
        self.stdin_seen: bytes | None = None

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self, stdin: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin_seen = stdin
        return self._out, self._err


def scripted(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[list[str]], FakeProcess]
) -> tuple[list[list[str]], list[FakeProcess]]:
    """Replace create_subprocess_exec with a script answering by argv, recording every call."""
    calls: list[list[str]] = []
    started: list[FakeProcess] = []

    async def fake_exec(*argv: str, **_: object) -> FakeProcess:
        calls.append(list(argv))
        process = respond(list(argv))
        started.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls, started


# -- the config's shape ----------------------------------------------------------


def test_a_connection_names_a_daemon_a_registry_or_both() -> None:
    assert DockerConnectionConfig(host="tcp://dind:2376").host == "tcp://dind:2376"
    assert REGISTRY.authenticates is True
    assert DockerConnectionConfig(host="ssh://build@host", username="u", password=SecretStr("p")).authenticates is True


def test_a_connection_that_names_neither_is_refused() -> None:
    with pytest.raises(ValidationError, match="names neither"):
        DockerConnectionConfig()


def test_a_host_of_an_unknown_form_is_refused() -> None:
    with pytest.raises(ValidationError, match="none of them"):
        DockerConnectionConfig(host="https://dind:2376")


def test_half_a_tls_triple_is_refused() -> None:
    with pytest.raises(ValidationError, match="all three"):
        DockerConnectionConfig(host="tcp://dind:2376", tls_key=SecretStr(KEY))


def test_tls_needs_a_tcp_daemon() -> None:
    with pytest.raises(ValidationError, match="tcp:// one"):
        DockerConnectionConfig(
            host="unix:///var/run/docker.sock", tls_ca=SecretStr(CA), tls_cert=SecretStr(CERT), tls_key=SecretStr(KEY)
        )


def test_half_a_registry_credential_is_refused() -> None:
    with pytest.raises(ValidationError, match="never one of them"):
        DockerConnectionConfig(host="tcp://dind:2376", username="robot")
    with pytest.raises(ValidationError, match="never one of them"):
        DockerConnectionConfig(host="tcp://dind:2376", password=SecretStr("s3cr3t"))


def test_a_registry_with_no_credential_authenticates_to_nothing() -> None:
    with pytest.raises(ValidationError, match="authenticates to nothing"):
        DockerConnectionConfig(host="tcp://dind:2376", registry="ghcr.io")


def test_a_credential_with_no_registry_means_docker_hub() -> None:
    assert REGISTRY.registry_name == "ghcr.io"
    assert DockerConnectionConfig(username="u", password=SecretStr("p")).registry_name == "docker.io"


# -- what a connection becomes on the filesystem ---------------------------------


def test_the_tls_triple_becomes_three_private_files_a_private_directory_holds(tmp_path: Path) -> None:
    with sealed(REMOTE, tmp_path) as material:
        directory = Path(material.environ["DOCKER_CERT_PATH"])
        assert material.environ["DOCKER_HOST"] == "tcp://dind:2376"
        assert material.environ["DOCKER_TLS_VERIFY"] == "1"
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        for name, pem in (("ca.pem", CA), ("cert.pem", CERT), ("key.pem", KEY)):
            written = directory / name
            assert written.read_text() == pem + "\n"
            assert stat.S_IMODE(written.stat().st_mode) == 0o600
        assert KEY in material.secrets
    assert not directory.exists()


def test_the_material_goes_when_the_step_fails(tmp_path: Path) -> None:
    held: Path | None = None
    with pytest.raises(RuntimeError), sealed(REMOTE, tmp_path) as material:
        held = Path(material.environ["DOCKER_CERT_PATH"])
        raise RuntimeError("the step failed")
    assert held is not None
    assert not held.exists()


def test_the_material_goes_when_the_step_is_cancelled(tmp_path: Path) -> None:
    held: Path | None = None
    with pytest.raises(asyncio.CancelledError), sealed(REMOTE, tmp_path) as material:
        held = Path(material.environ["DOCKER_CERT_PATH"])
        raise asyncio.CancelledError
    assert held is not None
    assert not held.exists()


def test_a_login_gets_a_docker_config_directory_of_its_own(tmp_path: Path) -> None:
    with sealed(REGISTRY, tmp_path, isolate_config=True) as material:
        config = Path(material.environ["DOCKER_CONFIG"])
        assert stat.S_IMODE(config.stat().st_mode) == 0o700
        assert "DOCKER_HOST" not in material.environ
        assert "s3cr3t" in material.secrets
    assert not config.exists()


def test_no_connection_leaves_the_workers_own_environment_alone(tmp_path: Path) -> None:
    with sealed(None, tmp_path) as material:
        assert material.environ == {}
        assert material.secrets == []


def test_a_connections_daemon_replaces_the_workers_own(tmp_path: Path) -> None:
    worker = {"DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CERT_PATH": "/certs/client", "PATH": "/bin"}
    with sealed(REMOTE, tmp_path) as material:
        built = daemon_environment(worker, material)
    assert built["DOCKER_HOST"] == "tcp://dind:2376"
    assert built["DOCKER_CERT_PATH"] != "/certs/client"
    assert built["PATH"] == "/bin"


def test_a_registry_only_connection_leaves_the_workers_daemon_where_it_was(tmp_path: Path) -> None:
    worker = {name: f"worker-{name}" for name in DAEMON_ENV}
    with sealed(REGISTRY, tmp_path, isolate_config=True) as material:
        built = daemon_environment(worker, material)
    assert {name: built[name] for name in DAEMON_ENV} == worker


def test_the_endpoint_is_resolved_from_the_connections_environment_rather_than_the_workers(tmp_path: Path) -> None:
    with sealed(REMOTE, tmp_path) as material:
        endpoint = resolve_endpoint(None, daemon_environment(dict(os.environ), material))
        assert endpoint.base_url == "https://dind:2376"
        assert endpoint.uds is None
        assert endpoint.cert == (
            str(Path(material.environ["DOCKER_CERT_PATH"]) / "cert.pem"),
            str(Path(material.environ["DOCKER_CERT_PATH"]) / "key.pem"),
        )


# -- the block reads its connection ----------------------------------------------


def test_docker_run_takes_a_connection_or_a_socket_path_and_never_both() -> None:
    with pytest.raises(ValidationError, match="either connection or socket_path"):
        DockerRunConfig(image="alpine", connection="dind", socket_path="/var/run/docker.sock")


async def test_a_run_against_a_connection_reaches_the_daemon_the_connection_names(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def daemon(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        if request.url.path == "/containers/create":
            return httpx2.Response(201, json={"Id": "abc", "Warnings": []})
        return httpx2.Response(204)

    def fake_open(endpoint: DaemonEndpoint, timeout: float) -> httpx2.AsyncClient:
        seen.append(endpoint.base_url)
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(daemon))

    monkeypatch.setattr("dirigent_blocks.docker.open_client", fake_open)
    local_ctx.connections["dind"] = REMOTE
    handle = await DockerRunOperator().execute(
        DockerRunConfig(image="alpine", connection="dind"), local_ctx.as_context()
    )
    assert isinstance(handle, RemoteHandle)
    assert "https://dind:2376" in seen


async def test_a_run_against_a_connection_leaves_no_key_behind(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def daemon(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/containers/create":
            return httpx2.Response(201, json={"Id": "abc", "Warnings": []})
        return httpx2.Response(204)

    def fake_open(endpoint: object, timeout: float) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(daemon))

    monkeypatch.setattr("dirigent_blocks.docker.open_client", fake_open)
    local_ctx.connections["dind"] = REMOTE
    await DockerRunOperator().execute(DockerRunConfig(image="alpine", connection="dind"), local_ctx.as_context())
    root = Path(local_ctx.scratch.removeprefix("file://"))
    assert list(root.glob("dirigent-docker-*")) == []


# -- the connection check --------------------------------------------------------


async def test_a_check_reads_the_daemons_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", found)
    calls, _started = scripted(monkeypatch, lambda argv: FakeProcess(0, b"27.1.1\n"))
    report = await DockerConnectionKind().check(DockerConnectionConfig(host="tcp://dind:2376"))
    assert report.healthy is True
    assert "27.1.1" in (report.detail or "")
    assert calls[0][1:] == ["version", "--format", "{{.Server.Version}}"]


async def test_a_check_logs_in_and_straight_out_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", found)
    calls, started = scripted(monkeypatch, lambda argv: FakeProcess(0, b"Login Succeeded\n"))
    report = await DockerConnectionKind().check(REGISTRY)
    assert report.healthy is True
    assert "ghcr.io" in (report.detail or "")
    assert calls[0][1:] == ["login", "--username", "robot", "--password-stdin", "ghcr.io"]
    assert started[0].stdin_seen == b"s3cr3t"
    assert calls[1][1:] == ["logout", "ghcr.io"]


def test_the_password_is_never_an_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", found)
    calls, _started = scripted(monkeypatch, lambda argv: FakeProcess(0, b"Login Succeeded\n"))
    asyncio.run(DockerConnectionKind().check(REGISTRY))
    assert all("s3cr3t" not in argument for call in calls for argument in call)


async def test_a_registry_that_refuses_the_credential_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", found)
    scripted(monkeypatch, lambda argv: FakeProcess(1, b"", b"unauthorized: incorrect username or password"))
    report = await DockerConnectionKind().check(REGISTRY)
    assert report.healthy is False
    assert "unauthorized" in (report.detail or "")


async def test_a_host_with_no_docker_cli_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", missing)
    report = await DockerConnectionKind().check(REMOTE)
    assert report.healthy is False
    assert "PATH" in (report.detail or "")
