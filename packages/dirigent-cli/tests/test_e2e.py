"""The whole product, driven the way a person drives it: dg dev, dg apply, dg run, dg runs."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cryptography.fernet import Fernet

from clisupport import asking_for_the_rendering, closing, of_kind, records

pytestmark = pytest.mark.e2e

STARTUP_TIMEOUT = 60.0
RUN_TIMEOUT = 120.0

PAYLOAD = {"dataset": "climate", "rows": 3}


class Handler(BaseHTTPRequestHandler):
    """Answers every GET with one small JSON document."""

    def do_GET(self) -> None:  # noqa: N802 - the stdlib names the hook
        """Answer with the payload the pipeline expects."""
        body = json.dumps(PAYLOAD).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the stdlib server out of the test output."""


def free_port() -> int:
    """Reserve a port by binding and releasing it."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = int(holder.getsockname()[1])
    holder.close()
    return port


@pytest.fixture
def service() -> Iterator[str]:
    """A tiny HTTP service the pipeline calls, in place of the network."""
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/data"
    finally:
        server.shutdown()
        server.server_close()


def dg_path() -> Path:
    """Find the installed console script."""
    candidate = Path(sys.executable).parent / "dg"
    if not candidate.exists():  # pragma: no cover - only on an unusual installation layout
        pytest.skip(f"the dg console script is not installed at {candidate}")
    return candidate


def document(url: str) -> str:
    """A three-step pipeline over three different built-in blocks."""
    return f"""\
# The end-to-end proof: call a service, archive what it said, announce the result.
format: dirigent/v1
kind: pipeline
code: e2e-demo
description: One HTTP call, one storage copy, one command on the worker.

params:
  type: object
  required: [day]
  properties:
    day:
      type: string
      format: date

steps:
  fetch:
    block: http.request
    config:
      url: {url}
      method: GET
      query:
        day: "${{params.day}}"
      save_to: "${{run.scratch}}/incoming/${{params.day}}.json"

  archive:
    block: storage.copy
    depends_on: [fetch]
    config:
      source: "${{steps.fetch.output.body_uri}}"
      target: "${{run.scratch}}/archive/${{params.day}}.json"

  announce:
    block: shell.run
    depends_on: [archive]
    config:
      argv:
        - echo
        - "fetched ${{steps.fetch.output.status}}, archived ${{steps.archive.output.bytes_copied}} bytes"
"""


@pytest.fixture
def project(tmp_path: Path, service: str) -> Path:
    """A directory with a settings file, ready for dg init."""
    (tmp_path / "settings.yaml").write_text(
        f'database_url: "sqlite+aiosqlite:///{tmp_path / "dirigent.db"}"\n'
        f'artifact_root: "file://{tmp_path / "artifacts"}"\n'
        "enabled_unsafe_blocks: [shell.run]\n"
        'log_level: "WARNING"\n'
    )
    return tmp_path


def environment(project: Path, *, url: str | None = None, token: str | None = None) -> dict[str, str]:
    """Build the environment every subprocess in this test runs under."""
    env = {
        **os.environ,
        "DIRIGENT_CONFIG_FILE": str(project / "settings.yaml"),
        "DIRIGENT_SECRET_KEY": Fernet.generate_key().decode(),
        "COLUMNS": "200",
        "NO_COLOR": "1",
    }
    env.pop("DG_URL", None)
    env.pop("DG_TOKEN", None)
    if url:
        env["DG_URL"] = url
    if token:
        env["DG_TOKEN"] = token
    return env


def run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    """Run one dg command and return everything it said.

    This test reads what a person reads, so it asks for the rendering; NDJSON is what a
    command writes when nobody says.
    """
    return subprocess.run(  # noqa: S603 - the argv is this test's own
        [str(dg_path()), *asking_for_the_rendering(argv)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def wait_for_health(url: str, process: subprocess.Popen[str]) -> None:
    """Wait until the server answers its liveness probe, or say why it never did."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:  # pragma: no cover - only when dg dev fails to start
            raise AssertionError(f"dg dev exited with {process.returncode}")
        try:
            if httpx2.get(f"{url}/health", timeout=1.0).status_code == 200:
                return
        except httpx2.HTTPError:
            time.sleep(0.1)
    raise AssertionError("dg dev never became healthy")  # pragma: no cover


def read_records(process: subprocess.Popen[str], deadline: float) -> Iterator[dict[str, Any]]:
    """Read dg dev's stream, yielding the records and passing over anything that is not one."""
    assert process.stdout is not None
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:  # pragma: no cover - only when dg dev dies during startup
            return
        try:
            record = json.loads(line)
        except ValueError:  # pragma: no cover - a line that is not a record
            continue
        if isinstance(record, dict):
            yield record


def read_token(process: subprocess.Popen[str], deadline: float) -> str:
    """Read the token dg dev mints once, off the record that carries it."""
    for record in read_records(process, deadline):
        if record.get("kind") == "process" and "token" in record:
            return str(record["token"])
    raise AssertionError("dg dev did not emit a token")  # pragma: no cover


def _discard(process: subprocess.Popen[str]) -> None:
    """Read and throw away whatever the server keeps saying, so its pipe never fills."""
    assert process.stdout is not None
    try:
        for _ in process.stdout:
            pass
    except ValueError:  # pragma: no cover - the pipe was closed while being read
        pass


@pytest.fixture
def dev(project: Path) -> Iterator[tuple[str, str]]:
    """A real ``dg dev`` process: API, embedded worker, one SQLite file, its own token."""
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(  # noqa: S603 - the argv is this test's own
        [str(dg_path()), "dev", "--port", str(port)],
        cwd=project,
        env=environment(project),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    drain: threading.Thread | None = None
    try:
        token = read_token(process, time.monotonic() + STARTUP_TIMEOUT)
        # Nothing reads dg dev's output after the token, and an unread pipe eventually
        # fills and blocks the process it belongs to.
        drain = threading.Thread(target=_discard, args=(process,), daemon=True)
        drain.start()
        wait_for_health(url, process)
        yield url, token
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - only when shutdown hangs
            process.kill()
            process.wait(timeout=10)
        if drain is not None:
            drain.join(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def test_a_person_can_scaffold_apply_run_and_read_a_pipeline(project: Path, service: str, dev: tuple[str, str]) -> None:
    """The whole loop: init, apply, run, runs."""
    url, token = dev
    env = environment(project, url=url, token=token)

    scaffolded = run(["init", "--documents-only", "."], cwd=project, env=env)
    assert scaffolded.returncode == 0, scaffolded.stderr or scaffolded.stdout
    assert (project / "dirigent.yaml").is_file()
    assert (project / "pipelines" / "hello-world.yaml").is_file()

    (project / "pipelines" / "e2e-demo.yaml").write_text(document(service))

    offline = run(["validate"], cwd=project, env=env)
    assert offline.returncode == 0, offline.stdout + offline.stderr
    assert "e2e-demo" in offline.stdout

    planned = run(["apply", "--dry-run"], cwd=project, env=env)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    assert "create" in planned.stdout
    assert "dry run" in planned.stdout

    applied = run(["apply"], cwd=project, env=env)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "e2e-demo" in applied.stdout
    assert "hello-world" in applied.stdout

    again = run(["apply"], cwd=project, env=env)
    assert "unchanged" in again.stdout, "applying the same documents twice must write nothing"

    listed = run(["pipeline", "list", "--json"], cwd=project, env=env)
    assert {row["code"] for row in rows_of(listed)} == {"e2e-demo", "hello-world"}

    started = run(["run", "e2e-demo", "-p", "day=2026-01-01", "--watch"], cwd=project, env=env, timeout=RUN_TIMEOUT)
    assert started.returncode == 0, started.stdout + started.stderr
    assert "succeeded" in started.stdout
    assert "http call" in started.stdout, "--watch streams block output, not only transitions"

    watched = run(
        ["run", "e2e-demo", "-p", "day=2026-01-01", "--watch", "--json"],
        cwd=project,
        env=env,
        timeout=RUN_TIMEOUT,
    )
    assert watched.returncode == 0, watched.stdout + watched.stderr
    stream = [json.loads(line) for line in watched.stdout.splitlines() if line.strip()]
    assert [event["kind"] for event in stream][0] == "run"
    assert stream[-1]["kind"] == "run"
    assert stream[-1]["message"] == "succeeded"
    assert {step["step"] for step in stream[-1]["steps"]} == {"fetch", "archive", "announce"}
    assert any(event["kind"] == "step" for event in stream)
    assert "succeeded  run" not in watched.stdout, "no rich rendering survives --json"

    runs = rows_of(run(["runs", "list", "--json"], cwd=project, env=env))
    assert len(runs) == 2
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["pipeline"] == "e2e-demo"
    run_id = runs[0]["id"]

    shown = run(["runs", "show", run_id], cwd=project, env=env)
    assert shown.returncode == 0
    for step in ("fetch", "archive", "announce"):
        assert step in shown.stdout
    assert "http.request" in shown.stdout
    assert "storage.copy" in shown.stdout
    assert "shell.run" in shown.stdout

    logs = run(["runs", "logs", run_id], cwd=project, env=env)
    assert logs.returncode == 0
    assert "http call" in logs.stdout
    assert "fetched 200, archived" in logs.stdout, "the command's own output must reach the run log"

    summary = payload_of(run(["runs", "report", run_id, "--json"], cwd=project, env=env))
    assert summary["status"] == "succeeded"
    assert [step["outcome"] for step in summary["steps"]] == ["succeeded", "succeeded", "succeeded"]

    exported = run(["export", "e2e-demo"], cwd=project, env=env)
    assert exported.stdout.startswith("format: dirigent/v1\n")
    (project / "exported.yaml").write_text(exported.stdout)
    round_tripped = run(["apply", str(project / "exported.yaml")], cwd=project, env=env)
    assert "unchanged" in round_tripped.stdout, "export then apply must be a no-op"

    info = payload_of(run(["system", "info", "--json"], cwd=project, env=env))
    assert info["workers_live"] >= 1, "dg dev runs an embedded worker, and it should be registered"
    assert "shell.run" in info["unsafe_blocks_enabled"]

    workers = rows_of(run(["system", "workers", "--json"], cwd=project, env=env))
    assert workers and workers[0]["code_matches_server"]

    deleted = run(["pipeline", "delete", "e2e-demo"], cwd=project, env=env)
    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    gone = run(["pipeline", "delete", "e2e-demo"], cwd=project, env=env)
    assert gone.returncode == 1, "the pipeline and every run of it are gone"


def test_the_same_document_runs_with_no_server_at_all(project: Path, service: str) -> None:
    """``dg run --local`` is the same engine on a throwaway database, and must agree."""
    path = project / "e2e-demo.yaml"
    path.write_text(document(service))
    env = environment(project)
    result = run(
        ["-o", "json", "run", "--local", str(path), "-p", "day=2026-01-01"],
        cwd=project,
        env=env,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    stream = records(result.stdout)
    assert closing(result.stdout)["message"] == "succeeded"
    assert any("fetched 200, archived" in event["message"] for event in of_kind(stream, "log"))


def test_an_unauthenticated_call_is_refused_by_the_running_server(project: Path, dev: tuple[str, str]) -> None:
    """Nothing under /api/v1 is reachable without a credential, on a real server."""
    url, _ = dev
    assert httpx2.get(f"{url}/health").status_code == 200
    assert httpx2.get(f"{url}/api/v1/pipelines").status_code == 401
    assert httpx2.get(f"{url}/openapi.json").status_code == 200


SCHEDULED = Path(__file__).resolve().parents[3] / "examples" / "triggers" / "managed-and-manual.yaml"

# What an upstream system POSTs, and what the example's params_from_payload maps it onto.
UPSTREAM = {"published": {"date": "2026-03-14"}, "target": {"environment": "production"}}
MAPPED = {"day": "2026-03-14", "environment": "production"}

TERMINAL = frozenset({"succeeded", "failed", "completed_with_errors", "cancelled"})
POLL_INTERVAL = 0.25


def payload_of(result: subprocess.CompletedProcess[str]) -> Any:
    """Read the one record a ``--json`` command printed, and hand back what it carries."""
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout)
    assert record.get("kind"), f"a command's answer is a record naming its kind: {result.stdout!r}"
    return record["fields"]


def rows_of(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    """Read a listing back: the row each record it wrote carries."""
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line)["fields"] for line in result.stdout.splitlines() if line.strip()]


def instant(text: str) -> datetime:
    """Read a timestamp the API printed as an aware instant, however it spelled UTC."""
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def minted_token(output: str) -> str:
    """Pick the one-time token out of what ``dg webhook rotate-token`` printed.

    A document-declared webhook's token is minted server-side and never shown, so rotating
    is the only way to come to hold one.
    """
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Token "):
            return stripped.removeprefix("Token ").strip()
    raise AssertionError(f"dg webhook rotate-token printed no token:\n{output}")


def settled(run_id: str, *, project: Path, env: dict[str, str]) -> dict[str, Any]:
    """Poll one run until the worker is done with it."""
    deadline = time.monotonic() + RUN_TIMEOUT
    seen = "nothing at all"
    while time.monotonic() < deadline:
        detail: dict[str, Any] = payload_of(run(["runs", "show", run_id, "--json"], cwd=project, env=env))
        row: dict[str, Any] = detail["run"]
        if row["status"] in TERMINAL:
            return row
        seen = str(row["status"])
        time.sleep(POLL_INTERVAL)
    raise AssertionError(f"run {run_id} never reached a terminal status within {RUN_TIMEOUT}s (last saw {seen})")


def test_a_document_declares_its_triggers_and_the_webhook_starts_a_real_run(
    project: Path, dev: tuple[str, str]
) -> None:
    """Applying examples/triggers/managed-and-manual.yaml materialises its clocks and its webhook."""
    url, token = dev
    env = environment(project, url=url, token=token)

    applied = run(["apply", str(SCHEDULED)], cwd=project, env=env)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "managed-and-manual" in applied.stdout

    schedules: dict[str, Any] = {row["code"]: row for row in rows_of(run(_schedules(), cwd=project, env=env))}
    assert set(schedules) == {"nightly", "staging-hourly"}
    assert schedules["nightly"]["cron"] == "0 5 * * *"
    assert schedules["nightly"]["timezone"] == "Europe/Oslo"
    assert schedules["nightly"]["params"] == {"day": "2026-01-01", "environment": "production"}
    assert schedules["staging-hourly"]["interval"] == "1h"
    assert schedules["staging-hourly"]["timezone"] == "UTC"
    now = datetime.now(UTC)
    for name, row in schedules.items():
        assert row["managed"] is True, f"the document declared {name}, so the instance must own it"
        assert row["paused"] is False
        assert row["next_fire_at"] is not None, f"{name} was declared without a computed first firing"
        assert instant(row["next_fire_at"]) > now, f"{name} next fires at {row['next_fire_at']}, which is not ahead"

    hooks: list[Any] = rows_of(run(_webhooks(), cwd=project, env=env))
    assert [hook["code"] for hook in hooks] == ["from-upstream"]
    hook: dict[str, Any] = hooks[0]
    assert hook["params_from_payload"] == {"day": "$.published.date", "environment": "$.target.environment"}
    assert hook["managed"] is True
    assert hook["active"] is True
    assert hook["signed"] is False
    assert hook["token_prefix"], "a listing shows enough of the token to tell two webhooks apart"
    assert "token" not in hook, "a listing must never carry the token itself, only its prefix"

    rotated = run(["webhook", "rotate-token", "managed-and-manual", "from-upstream"], cwd=project, env=env)
    assert rotated.returncode == 0, rotated.stdout + rotated.stderr
    secret = minted_token(rotated.stdout)
    assert secret.startswith(str(rows_of(run(_webhooks(), cwd=project, env=env))[0]["token_prefix"]))
    assert secret not in run(_webhooks(), cwd=project, env=env).stdout, "the token is readable exactly once"

    accepted = httpx2.post(f"{url}/hooks/{secret}", json=UPSTREAM, timeout=30.0)
    assert accepted.status_code == 201, accepted.text
    body: dict[str, Any] = accepted.json()
    assert body["outcome"] == "accepted"
    assert body["run_id"], "an accepted delivery answers with the run it started"
    run_id = str(body["run_id"])

    finished = settled(run_id, project=project, env=env)
    assert finished["status"] == "succeeded", finished["error"]
    assert finished["params"] == MAPPED, "the run must carry what the mapping produced, and nothing else"
    assert finished["triggered_by_kind"] == "webhook"
    assert finished["triggered_by_label"] == "webhook from-upstream"

    detail: dict[str, Any] = payload_of(run(["runs", "show", run_id, "--json"], cwd=project, env=env))
    outcomes = {node["code"]: node["outcome"] for node in detail["dag"]["nodes"]}
    assert outcomes == {"load": "succeeded", "verify": "succeeded"}

    history: list[Any] = rows_of(run(_deliveries(), cwd=project, env=env))
    assert [entry["outcome"] for entry in history] == ["accepted"]
    assert history[0]["run_id"] == run_id
    assert history[0]["mapped_params"] == MAPPED

    refused = httpx2.post(f"{url}/hooks/{secret}", json={"nothing": "useful"}, timeout=30.0)
    assert refused.status_code == 400, refused.text
    refusal: dict[str, Any] = refused.json()
    assert refusal["outcome"] == "rejected"
    assert refusal["run_id"] is None
    assert "published" in str(refusal["detail"]), "the caller is told which path was missing"

    both: list[Any] = rows_of(run(_deliveries(), cwd=project, env=env))
    assert [entry["outcome"] for entry in both] == ["rejected", "accepted"], "a refusal is evidence, so it is kept"
    assert both[0]["run_id"] is None
    assert "published" in str(both[0]["reason"])

    started: list[Any] = rows_of(
        run(["runs", "list", "--pipeline", "managed-and-manual", "--json"], cwd=project, env=env)
    )
    assert [entry["id"] for entry in started] == [run_id], "the refused delivery must have started nothing"


def _schedules() -> list[str]:
    """The command that lists the example's schedules verbatim."""
    return ["schedule", "list", "managed-and-manual", "--json"]


def _webhooks() -> list[str]:
    """The command that lists the example's webhooks verbatim."""
    return ["webhook", "list", "managed-and-manual", "--json"]


def _deliveries() -> list[str]:
    """The command that reads the webhook's delivery history verbatim."""
    return ["webhook", "deliveries", "managed-and-manual", "from-upstream", "--json"]


def test_dg_dev_announces_itself_as_records_and_not_a_schema_history(tmp_path: Path) -> None:
    """Someone starting a dev instance wants to start working, not to read alembic."""
    port = free_port()
    env = {
        **os.environ,
        "COLUMNS": "200",
        "NO_COLOR": "1",
        "DIRIGENT_SECRET_KEY": Fernet.generate_key().decode(),
    }
    env.pop("DIRIGENT_CONFIG_FILE", None)
    env.pop("DIRIGENT_DATABASE_URL", None)
    process = subprocess.Popen(  # noqa: S603 - the argv is this test's own
        [str(dg_path()), "dev", "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    emitted: list[dict[str, Any]] = []
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        for record in read_records(process, deadline):
            emitted.append(record)
            if record.get("kind") == "process" and record.get("message") == "ready":
                break
        else:  # pragma: no cover - only when startup outlives the timeout
            raise AssertionError("dg dev never said it was ready")
    finally:
        process.terminate()
        process.wait(timeout=30)
        if process.stdout is not None:
            process.stdout.close()

    assert emitted, "dg dev wrote nothing to its stream"
    assert all(record.get("v") == 1 for record in emitted), "every line is a record of this protocol"
    started = next(r for r in emitted if r.get("kind") == "process" and r.get("message") == "starting")
    assert started["api"] == f"http://127.0.0.1:{port}", "the URL it names is the one it bound"
    assert started["state"] == str((tmp_path / ".dirigent" / "state").resolve()), "and the state it is using"
    assert started["admin"] == "dev"
    assert started["token"], "the token is minted once and carried on the record"
    assert started["migrated"], "one field for a schema that was created, not six lines"
    assert started["at"], "a record carries the moment it happened"
    messages = [str(record.get("message", "")) for record in emitted]
    for noise in ("Running upgrade", "user created", "token issued", "Application startup complete"):
        assert noise not in messages, f"{noise!r} is detail, and detail is what -v is for"
