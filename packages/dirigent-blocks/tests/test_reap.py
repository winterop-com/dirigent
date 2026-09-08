"""Tests for the orphan reaper: which projects it chooses, and what it does to them."""

import asyncio
import subprocess as std_subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest

from dirigent_blocks import reap
from dirigent_blocks.reap import RunFact

GRACE = timedelta(minutes=10)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

ACTIVE = RunFact(status="running", active=True)

FINISHED = RunFact(status="failed", active=False)


def container(project: str, created: datetime, name: str = "web") -> dict[str, object]:
    """One container as ``/containers/json`` lists it, labelled into a compose project."""
    return {
        "Id": f"{project}-{name}",
        "Created": int(created.timestamp()),
        "Labels": {"com.docker.compose.project": project, "com.docker.compose.service": name},
    }


def daemon_listing(containers: list[dict[str, object]]) -> Callable[[httpx2.Request], httpx2.Response]:
    """A daemon that answers one label-filtered container listing."""

    def answer(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/containers/json"
        return httpx2.Response(200, json=containers)

    return answer


def install(monkeypatch: pytest.MonkeyPatch, containers: list[dict[str, object]]) -> None:
    """Point the reaper's daemon read at a fake listing."""
    answer = daemon_listing(containers)

    def fake_open(endpoint: object, timeout: float) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url="http://docker", transport=httpx2.MockTransport(answer))

    monkeypatch.setattr("dirigent_blocks.reap.open_client", fake_open)


def lookup(facts: dict[UUID, RunFact]) -> reap.RunLookup:
    """A run lookup over a fixed table; a run not in it does not exist."""

    async def look_up(run_id: UUID) -> RunFact | None:
        return facts.get(run_id)

    return look_up


class FakeProcess:
    """A finished subprocess with both streams already whole."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        """Hold the finished streams and the return code."""
        self.returncode = returncode
        self._out = stdout
        self._err = stderr
        child = std_subprocess.Popen(["true"])  # noqa: S603, S607
        child.wait()
        self.pid = child.pid

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self, stdin: bytes | None = None) -> tuple[bytes, bytes]:
        return self._out, self._err


def scripted(monkeypatch: pytest.MonkeyPatch, code: int = 0, stderr: bytes = b"") -> list[list[str]]:
    """Replace create_subprocess_exec with one that records every teardown."""
    calls: list[list[str]] = []

    async def fake_exec(*argv: str, **_: object) -> FakeProcess:
        calls.append(list(argv))
        return FakeProcess(code, stderr=stderr)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def project_of(run_id: UUID) -> str:
    """The compose project name a run of this id would have created."""
    return f"dirigent-{run_id.hex}"


# -- reading the daemon's projects -----------------------------------------------


async def test_a_projects_age_is_its_newest_container(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid4()
    name = project_of(run_id)
    install(
        monkeypatch,
        [
            container(name, NOW - timedelta(hours=2), "db"),
            container(name, NOW - timedelta(minutes=1), "web"),
        ],
    )
    async with reap.daemon({}) as client:
        found = await reap.projects(client)
    assert [one.name for one in found] == [name]
    assert found[0].run_id == run_id
    assert found[0].created == (NOW - timedelta(minutes=1))


async def test_a_project_this_instance_did_not_create_is_not_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        [
            container("somebody-elses-stack", NOW - timedelta(hours=1)),
            container("dirigent-not-a-uuid", NOW - timedelta(hours=1)),
        ],
    )
    async with reap.daemon({}) as client:
        assert await reap.projects(client) == []


# -- the selection rule ----------------------------------------------------------


async def test_a_terminal_runs_stack_is_an_orphan() -> None:
    run_id = uuid4()
    project = reap.Project(project_of(run_id), run_id, NOW - timedelta(hours=1))
    chosen = await reap.orphans([project], lookup({run_id: FINISHED}), grace=GRACE, now=NOW)
    assert [(one.name, status) for one, status in chosen] == [(project.name, "failed")]


async def test_an_active_runs_stack_is_left_alone() -> None:
    run_id = uuid4()
    project = reap.Project(project_of(run_id), run_id, NOW - timedelta(hours=1))
    assert await reap.orphans([project], lookup({run_id: ACTIVE}), grace=GRACE, now=NOW) == []


async def test_a_stack_whose_run_the_instance_no_longer_holds_is_an_orphan() -> None:
    run_id = uuid4()
    project = reap.Project(project_of(run_id), run_id, NOW - timedelta(hours=1))
    chosen = await reap.orphans([project], lookup({}), grace=GRACE, now=NOW)
    assert [status for _project, status in chosen] == ["unknown"]


async def test_a_project_younger_than_the_grace_is_left_alone_whatever_its_run_says() -> None:
    run_id = uuid4()
    project = reap.Project(project_of(run_id), run_id, NOW - timedelta(minutes=1))
    assert await reap.orphans([project], lookup({}), grace=GRACE, now=NOW) == []
    assert await reap.orphans([project], lookup({run_id: FINISHED}), grace=GRACE, now=NOW) == []


# -- the pass --------------------------------------------------------------------


async def test_a_pass_takes_each_orphan_down_with_its_volumes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_id = uuid4()
    install(monkeypatch, [container(project_of(run_id), NOW - timedelta(hours=1))])
    calls = scripted(monkeypatch)
    reaped = await reap.reap({}, tmp_path, lookup({run_id: FINISHED}), grace=GRACE, now=NOW)
    assert [one.project for one in reaped] == [project_of(run_id)]
    assert reaped[0].run_status == "failed"
    assert reaped[0].torn_down is True
    assert calls == [["docker", "compose", "-p", project_of(run_id), "down", "-v", "--remove-orphans"]]


async def test_a_dry_run_takes_nothing_down_and_still_says_what_it_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = uuid4()
    install(monkeypatch, [container(project_of(run_id), NOW - timedelta(hours=1))])
    calls = scripted(monkeypatch)
    reaped = await reap.reap({}, tmp_path, lookup({}), grace=GRACE, dry_run=True, now=NOW)
    assert [one.project for one in reaped] == [project_of(run_id)]
    assert reaped[0].torn_down is False
    assert calls == []


async def test_a_teardown_that_fails_is_reported_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = uuid4()
    install(monkeypatch, [container(project_of(run_id), NOW - timedelta(hours=1))])
    scripted(monkeypatch, code=1, stderr=b"network in use")
    reaped = await reap.reap({}, tmp_path, lookup({run_id: FINISHED}), grace=GRACE, now=NOW)
    assert reaped[0].torn_down is False
    assert "network in use" in reaped[0].detail


async def test_a_pass_with_nothing_to_reap_runs_no_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_id = uuid4()
    install(monkeypatch, [container(project_of(run_id), NOW - timedelta(hours=1))])
    calls = scripted(monkeypatch)
    assert await reap.reap({}, tmp_path, lookup({run_id: ACTIVE}), grace=GRACE, now=NOW) == []
    assert calls == []


# -- against a real daemon -------------------------------------------------------

import os  # noqa: E402

from dirigent_blocks.docker import DockerRunConfig, socket_path  # noqa: E402

requires_daemon = pytest.mark.skipif(
    not Path(socket_path(DockerRunConfig(image="alpine:3"))).exists(),
    reason="no Docker daemon socket is reachable",
)

ONE_SERVICE_STACK = """
services:
  only:
    image: alpine:3
    command: sleep 300
"""


async def _compose(argv: list[str], directory: Path) -> int:
    """Run the real compose CLI in the test's own environment, and hand back its exit code."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        *argv,
        cwd=directory,
        env=dict(os.environ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.communicate()
    return process.returncode or 0


@pytest.mark.docker
@requires_daemon
async def test_a_real_stack_whose_run_is_gone_is_reaped(tmp_path: Path) -> None:
    run_id = uuid4()
    project = project_of(run_id)
    compose_file = tmp_path / "docker-compose.yaml"
    compose_file.write_text(ONE_SERVICE_STACK)
    assert await _compose(["-p", project, "-f", str(compose_file), "up", "-d"], tmp_path) == 0
    try:
        # The grace is zero here: the project was created a moment ago, and the rule under
        # test is the run lookup rather than the age.
        reaped = await reap.reap(dict(os.environ), tmp_path, lookup({}), grace=timedelta(0))
        assert [one.project for one in reaped] == [project]
        assert reaped[0].torn_down is True
        assert reaped[0].run_status == "unknown"
        async with reap.daemon(dict(os.environ)) as client:
            assert [one.name for one in await reap.projects(client) if one.name == project] == []
    finally:
        await _compose(["-p", project, "-f", str(compose_file), "down", "-v", "--remove-orphans"], tmp_path)


@pytest.mark.docker
@requires_daemon
async def test_a_real_stack_whose_run_is_active_is_left_running(tmp_path: Path) -> None:
    run_id = uuid4()
    project = project_of(run_id)
    compose_file = tmp_path / "docker-compose.yaml"
    compose_file.write_text(ONE_SERVICE_STACK)
    assert await _compose(["-p", project, "-f", str(compose_file), "up", "-d"], tmp_path) == 0
    try:
        assert await reap.reap(dict(os.environ), tmp_path, lookup({run_id: ACTIVE}), grace=timedelta(0)) == []
        async with reap.daemon(dict(os.environ)) as client:
            assert [one.name for one in await reap.projects(client) if one.name == project] == [project]
    finally:
        await _compose(["-p", project, "-f", str(compose_file), "down", "-v", "--remove-orphans"], tmp_path)
