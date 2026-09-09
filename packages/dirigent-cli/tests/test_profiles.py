"""Profiles: where they are found, what they may hold, and what wins over what."""

from pathlib import Path

import pytest

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
    token_cmd: echo a-command-token
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
    environment = {"DG_STAGING_TOKEN": "staging-token"}

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
    assert chosen.token == "a-command-token"


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
    endpoint = resolve_endpoint(start=tmp_path, environ={"DG_STAGING_TOKEN": "from-the-shell"})
    assert endpoint.token == "from-the-shell"


def test_the_project_env_file_is_found_from_a_subdirectory(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / ".env").write_text("DG_STAGING_TOKEN=from-the-env-file\n")
    deep = tmp_path / "pipelines" / "nested"
    deep.mkdir(parents=True)
    assert resolve_endpoint(start=deep, environ={}).token == "from-the-env-file"
