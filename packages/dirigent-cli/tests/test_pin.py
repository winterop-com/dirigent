"""A project's pinned dirigent-cli, and the dg that is not it."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clisupport import only, refusal
from dirigent_cli import main
from dirigent_cli.main import app
from dirigent_cli.pin import ALLOW_ENV, find_pin, read_pin

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

RUNNING = "0.32.0"


def project(root: Path, dependency: str, *, extra: str = "") -> Path:
    """Write a project whose pyproject.toml depends on dirigent-cli as given."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "trial"\nversion = "0.1.0"\ndependencies = ["{dependency}"]\n{extra}'
    )
    return root


@pytest.fixture
def running(monkeypatch: pytest.MonkeyPatch) -> str:
    """Make the running dg this version, whatever is installed."""

    def installed(_name: str) -> str:
        return RUNNING

    monkeypatch.setattr(main, "distribution_version", installed)
    monkeypatch.delenv(ALLOW_ENV, raising=False)
    return RUNNING


def test_an_exact_pin_is_read_from_the_nearest_project(tmp_path: Path) -> None:
    project(tmp_path, "dirigent-cli==0.32.0")
    deep = tmp_path / "pipelines" / "nested"
    deep.mkdir(parents=True)
    pin = find_pin(deep)
    assert pin is not None
    assert (pin.project, pin.specifier) == (tmp_path, "==0.32.0")
    assert pin.allows("0.32.0")
    assert not pin.allows("0.21.0")


def test_a_range_is_satisfied_by_any_version_inside_it(tmp_path: Path) -> None:
    pin = read_pin(project(tmp_path, "dirigent-cli>=0.32,<0.33") / "pyproject.toml")
    assert pin is not None
    assert pin.allows("0.32.4")
    assert not pin.allows("0.33.0")


def test_a_dependency_without_a_version_is_no_pin(tmp_path: Path) -> None:
    assert read_pin(project(tmp_path, "dirigent-cli") / "pyproject.toml") is None


def test_a_pyproject_that_does_not_name_dirigent_is_walked_past(tmp_path: Path) -> None:
    project(tmp_path, "dirigent_cli==0.32.0")
    inner = project(tmp_path / "tools", "httpx2>=2")
    pin = find_pin(inner)
    assert pin is not None
    assert pin.project == tmp_path


def test_a_dependency_group_pin_counts(tmp_path: Path) -> None:
    project(tmp_path, "pyyaml", extra='\n[dependency-groups]\ndev = ["dirigent-cli==0.31.0"]\n')
    pin = find_pin(tmp_path)
    assert pin is not None
    assert pin.specifier == "==0.31.0"


def test_another_dg_is_refused_before_it_does_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str
) -> None:
    project(tmp_path, "dirigent-cli==0.33.0")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--json", "dev"])
    assert result.exit_code == 3, result.output
    refused = refusal(result.stdout)
    assert refused["code"] == "cli.version_mismatch"
    assert refused["params"] == {"running": running, "pinned": "==0.33.0", "project": str(tmp_path.resolve())}
    hints = [problem["code"] for problem in refused["problems"]]
    assert hints == ["cli.use_the_projects_dg", "cli.or_allow_any_version"]
    assert refused["problems"][0]["params"] == {"command": "dev"}
    assert not (tmp_path / ".dirigent").exists(), "a refused dg dev must not have touched the state"


def test_a_read_only_command_is_refused_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str) -> None:
    project(tmp_path, "dirigent-cli==0.21.0")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--json", "config", "show"])
    assert result.exit_code == 3
    assert refusal(result.stdout)["code"] == "cli.version_mismatch"


def test_the_pinned_version_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str) -> None:
    project(tmp_path, "dirigent-cli>=0.32,<0.33")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--json", "config", "show"])
    assert result.exit_code == 0, result.output
    assert only(result.stdout, "config")


def test_the_override_runs_another_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str) -> None:
    project(tmp_path, "dirigent-cli==0.33.0")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ALLOW_ENV, "1")
    result = runner.invoke(app, ["--json", "config", "show"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("argv", [["dev", "--help"], ["--help"], ["secret-key"]])
def test_help_and_the_commands_that_touch_nothing_answer_anyway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str, argv: list[str]
) -> None:
    project(tmp_path, "dirigent-cli==0.33.0")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert "version_mismatch" not in result.output
