"""Tests for the layered instance configuration."""

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from dirigent_core import config
from dirigent_core.config import (
    CONFIG_FILE_ENV,
    HOST_ONLY_SETTINGS,
    POOL_HEADROOM,
    STATE_DIR,
    Settings,
    host_config_paths,
    ignored_project_settings,
    project_config_paths,
)
from dirigent_core.configdocs import SCAFFOLDED


def test_a_key_file_supplies_the_secret_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A trailing newline is how a file ends, and is no part of the key."""
    held = tmp_path / "key"
    held.write_text("a-key-from-a-file\n")
    monkeypatch.setenv("DIRIGENT_SECRET_KEY_FILE", str(held))
    secret_key = Settings().secret_key
    assert secret_key is not None
    assert secret_key.get_secret_value() == "a-key-from-a-file"


def test_a_key_named_two_ways_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    held = tmp_path / "key"
    held.write_text("one")
    monkeypatch.setenv("DIRIGENT_SECRET_KEY_FILE", str(held))
    monkeypatch.setenv("DIRIGENT_SECRET_KEY", "another")
    with pytest.raises(ValidationError, match="both set"):
        Settings()


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_a_key_file_that_holds_no_key_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    """An instance that started without its key would fail far later, on the first secret."""
    held = tmp_path / "key"
    if content is not None:
        held.write_text(content)
    monkeypatch.setenv("DIRIGENT_SECRET_KEY_FILE", str(held))
    with pytest.raises(ValidationError, match="cannot be read as a key"):
        Settings()


@pytest.mark.skipif(not Path("/proc/self/environ").exists(), reason="/proc holds an environment only on Linux")
def test_dropping_the_variable_leaves_the_kernels_copy_of_the_environment() -> None:
    """What docs/security.md says the drop does not do, held so the page stays true."""
    program = (
        "import os\n"
        "from dirigent_core.config import drop_secret_key_variable\n"
        "drop_secret_key_variable()\n"
        "assert 'DIRIGENT_SECRET_KEY' not in os.environ\n"
        "print(b'the-envelope-key' in open('/proc/self/environ', 'rb').read())\n"
    )
    finished = subprocess.run(  # noqa: S603 - a fixed program, run by this interpreter
        [sys.executable, "-c", program],
        env={"DIRIGENT_SECRET_KEY": "the-envelope-key"},
        capture_output=True,
        check=True,
    )
    assert finished.stdout.strip() == b"True"


def test_defaults_target_sqlite_for_development() -> None:
    settings = Settings()
    assert settings.database_url.startswith("sqlite+aiosqlite")
    assert settings.is_sqlite is True
    assert settings.api_prefix == "/api/v1"
    assert settings.environment == "local"


def test_every_local_default_lives_under_one_state_directory() -> None:
    settings = Settings()
    assert settings.database_url == f"sqlite+aiosqlite:///./{STATE_DIR}/dirigent.db"
    assert settings.artifact_root == f"file://./{STATE_DIR}/artifacts"
    assert settings.sqlite_path == Path(f"./{STATE_DIR}/dirigent.db")


def test_a_database_with_no_file_of_its_own_has_no_sqlite_path() -> None:
    assert Settings(database_url="postgresql+asyncpg://u:p@localhost/dirigent").sqlite_path is None
    assert Settings(database_url="sqlite+aiosqlite://").sqlite_path is None
    assert Settings(database_url="sqlite+aiosqlite:///:memory:").sqlite_path is None


def test_query_parameters_are_not_part_of_the_sqlite_path() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:////var/lib/dirigent.db?mode=rw")
    assert settings.sqlite_path == Path("/var/lib/dirigent.db")


def test_environment_variables_use_the_dirigent_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIRIGENT_PORT", "9001")
    monkeypatch.setenv("DIRIGENT_LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.port == 9001
    assert settings.log_level == "DEBUG"


def test_worker_tags_are_read_as_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """One environment variable carries what a repeated --tag would."""
    monkeypatch.setenv("DIRIGENT_WORKER_TAGS", "docker,gpu")
    assert Settings().worker_tags == ["docker", "gpu"]


def test_a_yaml_file_supplies_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "dirigent.yaml"
    config_file.write_text('environment: "prod"\nworker_concurrency: 32\n')
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config_file))
    settings = Settings()
    assert settings.environment == "prod"
    assert settings.worker_concurrency == 32


def test_the_environment_outranks_the_yaml_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "dirigent.yaml"
    config_file.write_text('environment: "prod"\n')
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config_file))
    monkeypatch.setenv("DIRIGENT_ENVIRONMENT", "staging")
    settings = Settings()
    assert settings.environment == "staging"


def test_a_dotenv_in_the_working_directory_supplies_the_secret_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None
) -> None:
    """A project's .env is a settings layer, so the key dg init wrote there is the instance's."""
    (tmp_path / ".env").write_text("DG_TOKEN=a-token\nDIRIGENT_SECRET_KEY=a-key-from-the-file\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.secret_key is not None
    assert settings.secret_key.get_secret_value() == "a-key-from-the-file"


def test_the_environment_outranks_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None
) -> None:
    (tmp_path / ".env").write_text("DIRIGENT_SECRET_KEY=from-the-file\nDIRIGENT_ENVIRONMENT=staging\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIRIGENT_SECRET_KEY", "from-the-shell")

    settings = Settings()

    assert settings.secret_key is not None
    assert settings.secret_key.get_secret_value() == "from-the-shell"
    assert settings.environment == "staging", "the file still supplies what the shell does not"


def test_the_dotenv_file_outranks_the_yaml_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None
) -> None:
    config_file = tmp_path / "dirigent.yaml"
    config_file.write_text('environment: "prod"\n')
    (tmp_path / ".env").write_text("DIRIGENT_ENVIRONMENT=staging\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config_file))
    monkeypatch.chdir(tmp_path)

    assert Settings().environment == "staging"


def test_a_dotenv_is_read_from_the_working_directory_and_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None
) -> None:
    """The layer is the directory a command runs in, so a project's .env travels no further."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("DIRIGENT_SECRET_KEY=a-key-from-the-file\n")
    monkeypatch.chdir(tmp_path)

    assert Settings().secret_key is None


def test_a_dotenv_reads_a_setting_the_way_the_environment_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None
) -> None:
    """Same prefix, same spelling for a list, and a line without the prefix is no setting."""
    (tmp_path / ".env").write_text(
        "DIRIGENT_WORKER_TAGS=docker,gpu\nDIRIGENT_ENABLED_UNSAFE_BLOCKS=\nS3_ACCESS_KEY=dirigent\nPORT=8080\n"
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.worker_tags == ["docker", "gpu"]
    assert settings.enabled_unsafe_blocks == []
    assert settings.port == 3333


def test_the_api_prefix_is_normalised() -> None:
    assert Settings(api_prefix="api/v1/").api_prefix == "/api/v1"


def test_settings_are_frozen() -> None:
    settings = Settings()
    with pytest.raises(ValueError, match="frozen"):
        settings.port = 1234  # type: ignore[misc]


def test_postgres_urls_are_not_sqlite() -> None:
    settings = Settings(database_url="postgresql+asyncpg://u:p@localhost/dirigent")
    assert settings.is_sqlite is False
    assert settings.sync_database_url == "postgresql+psycopg://u:p@localhost/dirigent"


def test_an_explicit_config_file_is_taken_at_its_word(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DIRIGENT_CONFIG_FILE names the file, so nothing else on disk is consulted or refused."""
    named = tmp_path / "wherever.yaml"
    named.write_text('environment: "prod"\n')
    monkeypatch.setenv(CONFIG_FILE_ENV, str(named))
    assert host_config_paths() == [named]
    assert project_config_paths() == []
    assert Settings().environment == "prod"


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("", {}),
        ("   ", {}),
        ("s3=archive", {"s3": "archive"}),
        ("s3=archive, gs=cold", {"s3": "archive", "gs": "cold"}),
        ('{"s3": "archive"}', {"s3": "archive"}),
        ("{not json at all", {"{not json at all": ""}),
    ],
)
def test_a_mapping_setting_reads_the_spellings_a_person_and_a_manifest_write(
    written: str, expected: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty variable means an empty mapping, so a .env listing every setting still loads."""
    monkeypatch.setenv("DIRIGENT_STORAGE_CONNECTIONS", written)
    assert Settings().storage_connections == expected


def test_a_storage_scheme_with_no_named_connection_keeps_what_its_package_contributed() -> None:
    assert Settings().storage_connections == {}


def test_the_default_pool_covers_the_default_concurrency() -> None:
    """The shipped defaults must not be the configuration that starves the heartbeat."""
    settings = Settings(database_url="postgresql+asyncpg://u:p@host/db")
    assert settings.database_pool_size + settings.database_max_overflow >= settings.worker_concurrency + POOL_HEADROOM


def test_a_pool_too_small_for_its_concurrency_is_refused() -> None:
    """Silently under-provisioning the pool is how non-idempotent work gets run twice."""
    with pytest.raises(ValidationError) as raised:
        Settings(
            database_url="postgresql+asyncpg://u:p@host/db",
            database_pool_size=5,
            database_max_overflow=0,
            worker_concurrency=8,
        )
    assert "worker_concurrency" in str(raised.value)


def test_sqlite_is_exempt_from_the_pool_check_because_it_has_no_pool() -> None:
    assert Settings(database_pool_size=1, database_max_overflow=0, worker_concurrency=32).is_sqlite


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (".env", "DIRIGENT_ENABLED_UNSAFE_BLOCKS=shell.run\nDIRIGENT_ENVIRONMENT=staging\n"),
        ("dirigent.yaml", "enabled_unsafe_blocks: [shell.run]\nenvironment: staging\n"),
        (".dirigent/dirigent.yaml", "enabled_unsafe_blocks: [shell.run]\nenvironment: staging\n"),
    ],
)
def test_a_working_directory_file_cannot_set_the_allowlist_but_still_sets_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None, name: str, text: str
) -> None:
    path = tmp_path / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "no-such-home-file.yaml")

    settings = Settings()

    assert settings.enabled_unsafe_blocks == []
    assert settings.environment == "staging"


def test_the_environment_still_sets_the_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIRIGENT_ENABLED_UNSAFE_BLOCKS", "shell.run")
    assert Settings().enabled_unsafe_blocks == ["shell.run"]


def test_a_named_file_still_sets_the_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    named = tmp_path / "host.yaml"
    named.write_text("enabled_unsafe_blocks: [shell.run]\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(named))
    assert Settings().enabled_unsafe_blocks == ["shell.run"]


def test_the_users_file_still_sets_the_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    held = tmp_path / "home.yaml"
    held.write_text("enabled_unsafe_blocks: [shell.run]\n")
    monkeypatch.setattr(config, "USER_CONFIG_PATH", held)
    assert Settings().enabled_unsafe_blocks == ["shell.run"]


def test_the_users_file_is_still_outranked_by_a_project_file_for_any_other_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dirigent.yaml").write_text("environment: staging\n")
    held = tmp_path / "home.yaml"
    held.write_text("environment: prod\nport: 4444\n")
    monkeypatch.setattr(config, "USER_CONFIG_PATH", held)
    settings = Settings()
    assert (settings.environment, settings.port) == ("staging", 4444)


#: A value for each host-only setting, as a hostile checkout would write it.
HOSTILE: dict[str, str] = {
    "alert_base_url": "https://attacker.example.org",
    "apply_dir": "/somewhere/else",
    "apply_lock_key": "7",
    "apply_prune": "true",
    "artifact_root": "s3://attacker/artifacts",
    "database_url": "postgresql+asyncpg://u:p@attacker.example.org/dirigent",
    "enabled_unsafe_blocks": "shell.run",
    "host": "0.0.0.0",  # noqa: S104 - the value under test, never bound
    "retention_firings": "1s",
    "retention_inputs": "1s",
    "retention_logs": "1s",
    "retention_notifications": "1s",
    "retention_runs": "1s",
    "scheduler_lock_key": "7",
    "storage_connections": "s3=attacker",
    "ui_dir": "/somewhere/else",
    "work_root": "/somewhere/else",
}


def test_every_host_only_setting_has_a_hostile_value_under_test() -> None:
    assert set(HOSTILE) | {"secret_key_file"} == HOST_ONLY_SETTINGS


@pytest.mark.parametrize("name", sorted(HOSTILE))
@pytest.mark.parametrize("layer", [".env", "dirigent.yaml", ".dirigent/dirigent.yaml"])
def test_a_working_directory_file_cannot_set_a_host_only_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None, name: str, layer: str
) -> None:
    default = getattr(Settings(), name)
    path = tmp_path / layer
    path.parent.mkdir(exist_ok=True)
    written = f"DIRIGENT_{name.upper()}={HOSTILE[name]}\n" if layer == ".env" else f"{name}: {HOSTILE[name]}\n"
    path.write_text(written)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "no-such-home-file.yaml")

    assert getattr(Settings(), name) == default
    assert ignored_project_settings() == [name]


@pytest.mark.parametrize("layer", [".env", "dirigent.yaml"])
def test_a_working_directory_file_cannot_name_a_file_to_read_as_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv_layer: None, layer: str
) -> None:
    held = tmp_path / "held"
    held.write_text("read-from-a-file-the-checkout-named\n")
    written = f"DIRIGENT_SECRET_KEY_FILE={held}\n" if layer == ".env" else f"secret_key_file: {held}\n"
    (tmp_path / layer).write_text(written)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "no-such-home-file.yaml")

    settings = Settings()

    assert settings.secret_key is None
    assert settings.secret_key_file is None


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_the_environment_and_a_named_file_still_set_a_host_only_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    default = getattr(Settings(), name)
    monkeypatch.chdir(tmp_path)
    named = tmp_path / "host.yaml"
    named.write_text(f"{name}: {HOSTILE[name]}\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(named))
    assert getattr(Settings(), name) != default

    named.write_text("")
    monkeypatch.setenv(f"DIRIGENT_{name.upper()}", HOSTILE[name])
    assert getattr(Settings(), name) != default


def test_the_users_file_still_sets_a_host_only_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    held = tmp_path / "home.yaml"
    held.write_text("work_root: /kept/here\n")
    monkeypatch.setattr(config, "USER_CONFIG_PATH", held)
    assert Settings().work_root == "/kept/here"
    assert ignored_project_settings() == []


def test_a_scaffolded_project_sets_no_host_only_setting() -> None:
    assert not HOST_ONLY_SETTINGS.intersection(SCAFFOLDED)


@pytest.mark.parametrize("name", sorted(Settings.model_fields))
def test_a_setting_naming_a_path_or_an_address_is_host_only(name: str) -> None:
    """A new setting that names a file, a directory or a URL has to be decided on, not inherited."""
    annotation = str(Settings.model_fields[name].annotation)
    places = "Path" in annotation or name.endswith(("_url", "_root", "_dir", "_file", "_connections"))
    assert not places or name in HOST_ONLY_SETTINGS
