"""Every script under examples/python must stay runnable against a real instance."""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from cryptography.fernet import Fernet

SCRIPTS = Path(__file__).resolve().parents[3] / "examples" / "python"

STARTUP_TIMEOUT = 60.0
SCRIPT_TIMEOUT = 120.0


def scripts() -> list[Path]:
    """List the example scripts, in a stable order."""
    return sorted(SCRIPTS.glob("*.py"))


EXAMPLES = scripts()
NAMES = [path.name for path in EXAMPLES]


def test_there_are_example_scripts_to_check() -> None:
    assert SCRIPTS.is_dir(), f"{SCRIPTS} is missing"
    assert EXAMPLES, "there are no example scripts to check"


@pytest.mark.parametrize("path", EXAMPLES, ids=NAMES)
def test_an_example_says_what_it_shows_and_how_to_run_it(path: Path) -> None:
    text = path.read_text()
    assert text.startswith('"""'), f"{path.name} has no header saying what it shows"
    header = text.split('"""')[1]
    assert f"examples/python/{path.name}" in header, f"{path.name} does not name the command that runs it"
    assert "from dirigent_client import" in text, f"{path.name} does not use the SDK"
    compile(text, str(path), "exec")


@pytest.mark.parametrize("path", EXAMPLES, ids=NAMES)
def test_an_example_is_listed_in_the_index(path: Path) -> None:
    assert path.name in (SCRIPTS / "README.md").read_text(), f"{path.name} is missing from examples/python/README.md"


def free_port() -> int:
    """Reserve a port by binding and releasing it."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = int(holder.getsockname()[1])
    holder.close()
    return port


def dg_path() -> Path:
    """Find the installed dg console script."""
    candidate = Path(sys.executable).parent / "dg"
    if not candidate.exists():  # pragma: no cover - only on an unusual installation layout
        pytest.skip(f"the dg console script is not installed at {candidate}")
    return candidate


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """A real dg dev process, and the environment a script needs to reach it."""
    tmp_path = tmp_path_factory.mktemp("examples")
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        f'database_url: "sqlite+aiosqlite:///{tmp_path / "dirigent.db"}"\n'
        f'artifact_root: "file://{tmp_path / "artifacts"}"\n'
        "enabled_unsafe_blocks: [shell.run]\n"
        'log_level: "WARNING"\n'
    )
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        "DIRIGENT_CONFIG_FILE": str(settings),
        "DIRIGENT_SECRET_KEY": Fernet.generate_key().decode(),
        "COLUMNS": "200",
        "NO_COLOR": "1",
    }
    environment.pop("DG_URL", None)
    environment.pop("DG_TOKEN", None)
    process = subprocess.Popen(  # noqa: S603 - the argv is this test's own
        [str(dg_path()), "dev", "--port", str(port)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        token = _token_of(process)
        _wait_for_health(url, process)
        yield {**environment, "DG_URL": url, "DG_TOKEN": token}
    finally:
        process.terminate()
        process.wait(timeout=30)
        if process.stdout is not None:
            process.stdout.close()


def _token_of(process: subprocess.Popen[str]) -> str:
    """Read the token dg dev mints once, off the record that carries it."""
    assert process.stdout is not None
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:  # pragma: no cover - only when dg dev dies during startup
            break
        try:
            loaded: object = json.loads(line)
        except ValueError:  # pragma: no cover - a line that is not a record
            continue
        if not isinstance(loaded, dict):  # pragma: no cover - a JSON line that is not an object
            continue
        record = cast("dict[str, Any]", loaded)
        if record.get("kind") == "process" and "token" in record:
            return str(record["token"])
    raise AssertionError("dg dev did not emit a token")  # pragma: no cover


def _wait_for_health(url: str, process: subprocess.Popen[str]) -> None:
    """Wait until the server answers its liveness probe."""
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


@pytest.mark.e2e
@pytest.mark.parametrize("path", EXAMPLES, ids=NAMES)
def test_an_example_runs_against_a_real_instance(path: Path, instance: dict[str, str]) -> None:
    finished = subprocess.run(  # noqa: S603 - the argv is this test's own
        [sys.executable, str(path)],
        env=instance,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT,
        check=False,
    )
    assert finished.returncode == 0, f"{path.name} exited {finished.returncode}:\n{finished.stdout}{finished.stderr}"
    assert finished.stdout.strip(), f"{path.name} printed nothing"
