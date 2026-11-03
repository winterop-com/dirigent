"""`dg profile list` and `dg profile show`: what applies here, what is selected, and never a token."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clisupport import only, refusal, rows
from dirigent_cli import profiles
from dirigent_cli.main import app

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

PROJECT = """
default: staging

profiles:
  local:
    url: http://127.0.0.1:3333
    token: a-local-token

  staging:
    url: https://dirigent-staging.example.org
    token_env: DG_STAGING_TOKEN

  prod:
    url: https://dirigent.example.org
    connect_timeout: 10s
"""

USER = """
profiles:
  remote:
    url: https://far.example.org
    token_cmd: pass show dirigent/remote
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a profiles file, a user file beside it, and a shell that sets none of the DG_ variables."""
    root = tmp_path / "project"
    (root / ".dirigent").mkdir(parents=True)
    (root / ".dirigent" / "profiles.yaml").write_text(PROJECT)
    user = tmp_path / "home" / "profiles.yaml"
    user.parent.mkdir()
    user.write_text(USER)
    monkeypatch.setattr(profiles, "USER_PROFILES", user)
    for variable in ("DG_URL", "DG_TOKEN", "DG_PROFILE", "DG_STAGING_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(root)
    return root


def test_list_names_every_profile_its_file_and_how_it_gets_a_token(project: Path) -> None:
    result = runner.invoke(app, ["--json", "profile", "list"])
    assert result.exit_code == 0, result.output
    listed = {row["name"]: row for row in rows(result.stdout, "profile")}
    assert list(listed) == ["local", "staging", "prod", "remote"]
    assert {name: row["token"] for name, row in listed.items()} == {
        "local": "token",
        "staging": "token_env DG_STAGING_TOKEN",
        "prod": None,
        "remote": "token_cmd",
    }
    assert [name for name, row in listed.items() if row["selected"]] == ["staging"]
    assert [name for name, row in listed.items() if row["default"]] == ["staging"]
    assert listed["local"]["scope"] == "project"
    assert listed["local"]["file"] == str((project / ".dirigent" / "profiles.yaml").resolve())
    assert (listed["remote"]["scope"], listed["remote"]["active"]) == ("user", False)
    assert listed["local"]["url"] == "http://127.0.0.1:3333"
    assert "a-local-token" not in result.stdout


def test_dg_profile_and_the_flag_select_another(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DG_PROFILE", "prod")
    listed = rows(runner.invoke(app, ["--json", "profile", "list"]).stdout, "profile")
    assert [row["name"] for row in listed if row["selected"]] == ["prod"]
    shown = only(runner.invoke(app, ["--json", "profile", "show"]).stdout, "profile")["fields"]
    assert (shown["name"], shown["selected_by"]) == ("prod", "DG_PROFILE")
    flagged = only(runner.invoke(app, ["--json", "--profile", "local", "profile", "show"]).stdout, "profile")
    assert (flagged["fields"]["name"], flagged["fields"]["selected_by"]) == ("local", "--profile")


def test_show_resolves_the_selected_profile_without_its_token(project: Path) -> None:
    result = runner.invoke(app, ["--json", "profile", "show", "local"])
    assert result.exit_code == 0, result.output
    shown = only(result.stdout, "profile")["fields"]
    assert shown["url"] == "http://127.0.0.1:3333"
    assert shown["api_prefix"] == "/api/v1"
    assert (shown["timeout"], shown["connect_timeout"], shown["retries"]) == ("30s", "2s", 2)
    assert (shown["token"], shown["token_available"], shown["token_problem"]) == ("token", True, None)
    assert shown["selected_by"] == "argument"
    assert shown["overridden_by"] == []
    assert "a-local-token" not in result.stdout


def test_show_says_a_token_is_missing_and_why(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = only(runner.invoke(app, ["--json", "profile", "show"]).stdout, "profile")["fields"]
    assert (missing["name"], missing["token_available"]) == ("staging", False)
    assert "DG_STAGING_TOKEN" in missing["token_problem"]
    monkeypatch.setenv("DG_STAGING_TOKEN", "a-staging-token")
    result = runner.invoke(app, ["--json", "profile", "show"])
    assert only(result.stdout, "profile")["fields"]["token_available"] is True
    assert "a-staging-token" not in result.stdout


def test_show_names_the_variables_that_win_over_the_profile(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DG_URL", "http://127.0.0.1:4444")
    monkeypatch.setenv("DG_TOKEN", "a-shell-token")
    result = runner.invoke(app, ["--json", "profile", "show", "prod"])
    shown = only(result.stdout, "profile")["fields"]
    assert shown["overridden_by"] == ["DG_URL", "DG_TOKEN"]
    assert shown["token_available"] is True
    assert "a-shell-token" not in result.stdout


def test_a_user_profile_a_project_file_shadows_is_refused_with_the_reason(project: Path) -> None:
    result = runner.invoke(app, ["--json", "profile", "show", "remote"])
    assert result.exit_code == 2
    said = refusal(result.stdout)
    assert said["code"] == "cli.profile_not_here"
    assert "commands here read" in said["message"]


def test_an_unknown_profile_is_refused(project: Path) -> None:
    said = refusal(runner.invoke(app, ["--json", "profile", "show", "nowhere"]).stdout)
    assert said["code"] == "cli.profile_not_here"
    assert "local, prod, staging" in said["message"]


def test_the_rendering_reads_at_a_terminal(project: Path) -> None:
    assert runner.invoke(app, ["-o", "console", "profile", "list"]).exit_code == 0
    shown = runner.invoke(app, ["-o", "console", "profile", "show", "local"])
    assert shown.exit_code == 0, shown.output
    assert "a-local-token" not in shown.output
