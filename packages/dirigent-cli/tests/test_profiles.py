"""Profiles: where they are found, what they may hold, and what wins over what."""

import os
from datetime import timedelta
from pathlib import Path

import pytest

from dirigent_cli import profiles
from dirigent_cli.profiles import (
    DEFAULT_URL,
    Profile,
    ProfileError,
    ProfileStore,
    candidate_paths,
    find_store,
    load_store,
    resolve_endpoint,
)
from dirigent_client import DEFAULT_CONNECT_TIMEOUT, DEFAULT_RETRIES, DEFAULT_TIMEOUT

FILE = """
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
    token: a-prod-token
"""


def write(root: Path, text: str = FILE) -> Path:
    """Write a project-local profiles file under a directory."""
    path = root / ".dirigent" / "profiles.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_project_profiles_file_is_found_by_walking_up(tmp_path: Path) -> None:
    write(tmp_path)
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    store = find_store(deep)
    assert store.default == "staging"
    assert set(store.profiles) == {"local", "staging", "prod"}


def test_the_project_file_comes_before_the_user_one(tmp_path: Path) -> None:
    paths = candidate_paths(tmp_path)
    assert paths[0] == tmp_path / ".dirigent" / "profiles.yaml"
    assert paths[-1].parts[-3:] == (".config", "dirigent", "profiles.yaml")


def test_no_profiles_file_anywhere_is_not_an_error(tmp_path: Path) -> None:
    store = find_store(tmp_path / "nowhere")
    assert store.profiles == {}
    assert store.select(None) is None


def test_a_profile_may_not_hold_a_database_url() -> None:
    with pytest.raises(ValueError, match="DIRIGENT_DATABASE_URL"):
        Profile(name="wrong", url="postgresql+asyncpg://dirigent@localhost/dirigent")
    with pytest.raises(ValueError, match="DIRIGENT_DATABASE_URL"):
        Profile(name="wrong", url="sqlite+aiosqlite:///./dirigent.db")


def test_a_database_url_in_a_file_is_refused_with_the_file_named(tmp_path: Path) -> None:
    path = write(tmp_path, "profiles:\n  bad:\n    url: postgresql://localhost/dirigent\n")
    with pytest.raises(ProfileError, match=str(path)):
        load_store(path)


def test_an_unreadable_or_malformed_file_says_which(tmp_path: Path) -> None:
    path = write(tmp_path, "this: is not: yaml: [[[\n")
    with pytest.raises(ProfileError, match="could not be read"):
        load_store(path)
    path = write(tmp_path, "profiles:\n  local: 3\n")
    with pytest.raises(ProfileError, match="not a mapping"):
        load_store(path)
    path = write(tmp_path, "- a list, not a mapping\n")
    with pytest.raises(ProfileError, match="should hold a mapping"):
        load_store(path)


def test_selecting_a_profile_that_does_not_exist_names_the_ones_that_do(tmp_path: Path) -> None:
    store = find_store(tmp_path) if write(tmp_path) else ProfileStore()
    with pytest.raises(ProfileError, match="staging"):
        store.select("nope")


def test_a_single_profile_is_selected_without_being_named(tmp_path: Path) -> None:
    write(tmp_path, "profiles:\n  only:\n    url: https://only.example.org\n")
    store = find_store(tmp_path)
    chosen = store.select(None)
    assert chosen is not None and chosen.name == "only"


def test_an_inline_token_is_used_as_it_stands() -> None:
    assert Profile(name="x", token="inline").resolve_token() == "inline"  # pyright: ignore[reportArgumentType]


def test_a_token_from_the_environment_is_read_and_a_missing_one_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = Profile(name="x", token_env="DG_TEST_TOKEN")
    with pytest.raises(ProfileError, match="DG_TEST_TOKEN"):
        profile.resolve_token()
    monkeypatch.setenv("DG_TEST_TOKEN", "from-the-environment")
    assert profile.resolve_token() == "from-the-environment"


def test_a_token_command_is_run_and_its_output_used() -> None:
    assert Profile(name="x", token_cmd="echo from-a-command").resolve_token() == "from-a-command"


def test_a_token_command_that_is_not_installed_says_so() -> None:
    with pytest.raises(ProfileError, match="not on PATH"):
        Profile(name="x", token_cmd="definitely-not-a-real-command").resolve_token()


def test_a_token_command_that_fails_or_prints_nothing_is_refused() -> None:
    with pytest.raises(ProfileError, match="failed"):
        Profile(name="x", token_cmd="false").resolve_token()
    with pytest.raises(ProfileError, match="printed nothing"):
        Profile(name="x", token_cmd="true").resolve_token()


def test_a_profile_with_no_token_mechanism_resolves_to_none() -> None:
    assert Profile(name="x").resolve_token() is None


def test_a_profile_without_its_token_still_names_the_server_when_none_is_needed(tmp_path: Path) -> None:
    write(tmp_path)
    with pytest.raises(ProfileError, match="DG_STAGING_TOKEN"):
        resolve_endpoint(start=tmp_path, environ={})
    endpoint = resolve_endpoint(start=tmp_path, environ={}, needs_token=False)
    assert endpoint.url == "https://dirigent-staging.example.org"
    assert endpoint.token is None


def test_precedence_is_flags_then_environment_then_profile(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / ".env").write_text("DG_STAGING_TOKEN=staging-token\n")
    environment: dict[str, str] = {}

    from_profile = resolve_endpoint(start=tmp_path, environ=environment)
    assert from_profile.url == "https://dirigent-staging.example.org"
    assert from_profile.token == "staging-token"
    assert from_profile.source == "profile staging"

    from_env = resolve_endpoint(start=tmp_path, environ={**environment, "DG_URL": "https://env.example.org"})
    assert from_env.url == "https://env.example.org"
    assert from_env.source == "environment"

    from_flag = resolve_endpoint(
        url="https://flag.example.org",
        token="flag-token",
        start=tmp_path,
        environ={**environment, "DG_URL": "https://env.example.org", "DG_TOKEN": "env-token"},
    )
    assert from_flag.url == "https://flag.example.org"
    assert from_flag.token == "flag-token"
    assert from_flag.source == "flag"


def test_the_profile_can_be_chosen_by_environment_too(tmp_path: Path) -> None:
    write(tmp_path)
    chosen = resolve_endpoint(start=tmp_path, environ={"DG_PROFILE": "prod"})
    assert chosen.profile == "prod"
    assert chosen.token == "a-prod-token"


def test_with_nothing_configured_the_cli_assumes_the_dev_server(tmp_path: Path) -> None:
    endpoint = resolve_endpoint(start=tmp_path / "empty", environ={})
    assert endpoint.url == DEFAULT_URL
    assert endpoint.token is None
    assert endpoint.source == "default"


def test_a_trailing_slash_never_reaches_the_client(tmp_path: Path) -> None:
    assert resolve_endpoint(url="https://x.example.org/", start=tmp_path, environ={}).url == "https://x.example.org"


def test_the_project_env_file_stands_in_for_an_unset_token_variable(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / ".env").write_text("DG_STAGING_TOKEN=from-the-env-file\n")
    endpoint = resolve_endpoint(start=tmp_path, environ={})
    assert endpoint.profile == "staging"
    assert endpoint.token == "from-the-env-file"


def test_the_environment_wins_over_the_project_env_file(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / ".env").write_text("DG_STAGING_TOKEN=from-the-env-file\n")
    environment = {"DG_URL": "https://env.example.org", "DG_STAGING_TOKEN": "from-the-shell"}
    endpoint = resolve_endpoint(start=tmp_path, environ=environment)
    assert endpoint.token == "from-the-shell"


def test_the_project_env_file_is_found_from_a_subdirectory(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / ".env").write_text("DG_STAGING_TOKEN=from-the-env-file\n")
    deep = tmp_path / "pipelines" / "nested"
    deep.mkdir(parents=True)
    assert resolve_endpoint(start=deep, environ={}).token == "from-the-env-file"


def test_a_project_file_may_not_name_a_command_and_the_command_never_runs(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    path = write(tmp_path, f"profiles:\n  p:\n    url: http://127.0.0.1:9\n    token_cmd: touch {marker}\n")
    with pytest.raises(ProfileError, match="may not name a command") as raised:
        resolve_endpoint(start=tmp_path, environ={})
    assert str(path) in str(raised.value)
    assert not marker.exists()


def test_the_user_file_may_name_a_command(tmp_path: Path) -> None:
    path = tmp_path / ".config" / "dirigent" / "profiles.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("profiles:\n  prod:\n    url: https://x.example.org\n    token_cmd: echo from-a-command\n")
    assert load_store(path).profiles["prod"].resolve_token() == "from-a-command"


def test_a_project_file_another_user_owns_is_passed_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path)
    monkeypatch.setattr(os, "getuid", lambda: tmp_path.stat().st_uid + 1)
    assert not find_store(tmp_path).is_project


def test_a_project_file_anyone_may_rewrite_is_passed_over(tmp_path: Path) -> None:
    write(tmp_path).chmod(0o666)
    assert not find_store(tmp_path).is_project


def test_a_project_env_file_anyone_may_rewrite_is_not_read(tmp_path: Path) -> None:
    write(tmp_path)
    env = tmp_path / ".env"
    env.write_text("DG_STAGING_TOKEN=planted\n")
    env.chmod(0o666)
    assert resolve_endpoint(start=tmp_path, environ={}, needs_token=False).token is None


def test_a_project_file_its_group_may_rewrite_is_passed_over(tmp_path: Path) -> None:
    write(tmp_path).chmod(0o664)
    assert not find_store(tmp_path).is_project


def test_a_project_env_file_its_group_may_rewrite_is_not_read(tmp_path: Path) -> None:
    write(tmp_path)
    env = tmp_path / ".env"
    env.write_text("DG_STAGING_TOKEN=planted\n")
    env.chmod(0o660)
    assert resolve_endpoint(start=tmp_path, environ={}, needs_token=False).token is None


def test_a_symlinked_project_file_is_passed_over(tmp_path: Path) -> None:
    held = tmp_path / "elsewhere.yaml"
    held.write_text(FILE)
    (tmp_path / "project" / ".dirigent").mkdir(parents=True)
    (tmp_path / "project" / ".dirigent" / "profiles.yaml").symlink_to(held)
    assert not find_store(tmp_path / "project").is_project


def test_a_symlinked_dirigent_directory_is_passed_over(tmp_path: Path) -> None:
    held = tmp_path / "held"
    held.mkdir()
    (held / "profiles.yaml").write_text(FILE)
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / ".dirigent").symlink_to(held)
    assert not find_store(tmp_path / "project").is_project


def test_a_project_file_that_is_a_fifo_is_passed_over_without_blocking(tmp_path: Path) -> None:
    (tmp_path / ".dirigent").mkdir()
    os.mkfifo(tmp_path / ".dirigent" / "profiles.yaml")
    assert not find_store(tmp_path).is_project


@pytest.mark.parametrize("key", ["DG_TOKEN", "aws_secret_access_key"])
def test_a_symlinked_env_file_supplies_no_token(tmp_path: Path, key: str) -> None:
    held = tmp_path / "credentials"
    held.write_text(f"{key}=held-elsewhere\n")
    project = tmp_path / "project"
    write(project, f"profiles:\n  p:\n    url: https://project.example.org\n    token_env: {key}\n")
    (project / ".env").symlink_to(held)
    assert resolve_endpoint(start=project, environ={}, needs_token=False).token is None


@pytest.mark.parametrize(
    ("profile", "env_line"),
    [
        ("profiles:\n  p:\n    url: https://project.example.org\n", "DG_TOKEN=${SHELL_SECRET}\n"),
        ("profiles:\n  p:\n    url: https://project.example.org\n    token_env: T\n", "T=${SHELL_SECRET}\n"),
    ],
)
def test_an_env_file_cannot_copy_a_variable_out_of_the_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str, env_line: str
) -> None:
    write(tmp_path, profile)
    (tmp_path / ".env").write_text(env_line)
    monkeypatch.setenv("SHELL_SECRET", "held-in-the-shell")
    endpoint = resolve_endpoint(start=tmp_path, environ={"SHELL_SECRET": "held-in-the-shell"})
    assert endpoint.token == "${SHELL_SECRET}"


def test_a_literal_token_in_a_regular_env_file_still_reaches_the_projects_server(tmp_path: Path) -> None:
    write(tmp_path, "profiles:\n  p:\n    url: https://project.example.org\n")
    (tmp_path / ".env").write_text("DG_TOKEN=the-projects-own\n")
    endpoint = resolve_endpoint(start=tmp_path, environ={})
    assert (endpoint.url, endpoint.token) == ("https://project.example.org", "the-projects-own")


PROJECT_SERVER = "profiles:\n  p:\n    url: https://project.example.org\n    token_env: DG_TOKEN\n"


@pytest.mark.parametrize(
    ("project_file", "environment", "flag"),
    [
        (PROJECT_SERVER, {"DG_TOKEN": "real"}, None),
        (PROJECT_SERVER.replace("DG_TOKEN", "GITHUB_TOKEN"), {"GITHUB_TOKEN": "real"}, None),
        (PROJECT_SERVER.replace("    token_env: DG_TOKEN\n", ""), {"DG_TOKEN": "real"}, None),
        (PROJECT_SERVER.replace("    token_env: DG_TOKEN\n", ""), {}, "real"),
        (
            PROJECT_SERVER.replace("https://project.example.org", "http://127.0.0.1@project.example.org"),
            {"DG_TOKEN": "real"},
            None,
        ),
    ],
)
def test_a_token_from_the_shell_does_not_follow_a_url_the_project_chose(
    tmp_path: Path, project_file: str, environment: dict[str, str], flag: str | None
) -> None:
    write(tmp_path, project_file)
    with pytest.raises(ProfileError, match="name the server yourself"):
        resolve_endpoint(token=flag, start=tmp_path, environ=environment)
    assert resolve_endpoint(token=flag, start=tmp_path, environ=environment, needs_token=False).token is None


def test_a_token_from_the_shell_does_not_follow_a_url_from_the_project_env_file(tmp_path: Path) -> None:
    write(tmp_path, "profiles: {}\n")
    (tmp_path / ".env").write_text("DG_URL=https://project.example.org\n")
    with pytest.raises(ProfileError, match="name the server yourself"):
        resolve_endpoint(start=tmp_path, environ={"DG_TOKEN": "real"})


def test_a_token_from_the_shell_reaches_a_server_the_shell_named(tmp_path: Path) -> None:
    write(tmp_path, PROJECT_SERVER)
    environment = {"DG_TOKEN": "real", "DG_URL": "https://mine.example.org"}
    assert resolve_endpoint(start=tmp_path, environ=environment).url == "https://mine.example.org"
    flagged = resolve_endpoint(url="https://flag.example.org", start=tmp_path, environ={"DG_TOKEN": "real"})
    assert flagged.token == "real"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_a_token_from_the_shell_may_reach_this_host_from_a_project_file(tmp_path: Path, host: str) -> None:
    write(tmp_path, f"profiles:\n  p:\n    url: http://{host}:3333\n    token_env: DG_TOKEN\n")
    assert resolve_endpoint(start=tmp_path, environ={"DG_TOKEN": "real"}).token == "real"


def test_a_token_the_project_supplied_itself_reaches_the_project_server(tmp_path: Path) -> None:
    write(tmp_path, PROJECT_SERVER)
    (tmp_path / ".env").write_text("DG_TOKEN=the-projects-own\n")
    endpoint = resolve_endpoint(start=tmp_path, environ={})
    assert (endpoint.url, endpoint.token) == ("https://project.example.org", "the-projects-own")


def test_a_token_from_the_shell_may_follow_a_url_the_user_file_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_file = tmp_path / "user" / "profiles.yaml"
    user_file.parent.mkdir()
    user_file.write_text(PROJECT_SERVER)
    monkeypatch.setattr(profiles, "USER_PROFILES", user_file)
    assert resolve_endpoint(start=tmp_path, environ={"DG_TOKEN": "real"}).token == "real"


def test_an_instance_on_a_slow_link_may_be_given_longer_to_answer(tmp_path: Path) -> None:
    write(
        tmp_path,
        """
profiles:
  far:
    url: https://dirigent.example.org
    token: a-token
    timeout: 2m
    connect_timeout: 10s
    retries: 4
""",
    )
    endpoint = resolve_endpoint(start=tmp_path, environ={})
    assert endpoint.timeout == timedelta(minutes=2)
    assert endpoint.connect_timeout == timedelta(seconds=10)
    assert endpoint.retries == 4


def test_a_profile_that_says_nothing_about_patience_gets_the_client_defaults(tmp_path: Path) -> None:
    endpoint = resolve_endpoint(start=tmp_path / "empty", environ={})
    assert endpoint.connect_timeout == timedelta(seconds=DEFAULT_CONNECT_TIMEOUT)
    assert endpoint.timeout == timedelta(seconds=DEFAULT_TIMEOUT)
    assert endpoint.retries == DEFAULT_RETRIES


def test_a_server_a_project_names_off_this_host_is_marked(tmp_path: Path) -> None:
    write(tmp_path, PROJECT_SERVER)
    assert resolve_endpoint(start=tmp_path, environ={}, needs_token=False).named_by_a_project


def test_a_server_a_project_env_file_names_off_this_host_is_marked(tmp_path: Path) -> None:
    write(tmp_path, "profiles: {}\n")
    (tmp_path / ".env").write_text("DG_URL=https://project.example.org\n")
    assert resolve_endpoint(start=tmp_path, environ={}, needs_token=False).named_by_a_project


@pytest.mark.parametrize(
    ("flag", "environment"),
    [("https://flag.example.org", {}), (None, {"DG_URL": "https://mine.example.org"})],
    ids=["flag", "shell"],
)
def test_a_server_the_person_named_is_not_marked(tmp_path: Path, flag: str | None, environment: dict[str, str]) -> None:
    write(tmp_path, PROJECT_SERVER)
    endpoint = resolve_endpoint(url=flag, start=tmp_path, environ=environment, needs_token=False)
    assert not endpoint.named_by_a_project


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_a_server_a_project_names_on_this_host_is_not_marked(tmp_path: Path, host: str) -> None:
    write(tmp_path, f"profiles:\n  p:\n    url: http://{host}:3333\n")
    assert not resolve_endpoint(start=tmp_path, environ={}, needs_token=False).named_by_a_project


def test_a_server_the_user_s_own_profile_names_is_not_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = tmp_path / "user-profiles.yaml"
    user.write_text("profiles:\n  p:\n    url: https://mine.example.org\n")
    monkeypatch.setattr("dirigent_cli.profiles.USER_PROFILES", user)
    assert not resolve_endpoint(start=tmp_path, environ={}, needs_token=False).named_by_a_project
