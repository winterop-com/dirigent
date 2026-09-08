"""Tests for the layered instance configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from dirigent_core.config import (
    CONFIG_FILE_ENV,
    POOL_HEADROOM,
    STATE_DIR,
    Settings,
    candidate_config_paths,
)


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
    assert candidate_config_paths() == [named]
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
