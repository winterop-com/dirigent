"""The artifact bucket, made by the instance that writes to it, against a real S3 API."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from dirigent_cli.main import app
from dirigent_core.config import CONFIG_FILE_ENV, reset_settings_cache
from dirigent_storage_s3 import S3StorageBackend, S3StorageConfig
from s3server import ACCESS_KEY, BUCKET, SECRET_KEY

pytestmark = pytest.mark.s3

runner = CliRunner()

#: The bucket the backend makes, which no fixture creates first.
MADE = "dirigent-ensured"

#: The bucket the command makes, addressed by an instance's artifact root.
FROM_THE_CLI = "dirigent-from-the-cli"

#: The connection code the compose stack bootstraps, and the scheme it serves.
CONNECTION = "artifacts"

PROOF = b"the reference is the artifact\n"


def only(stdout: str, kind: str) -> dict[str, Any]:
    """Take the one record of a kind out of a command's NDJSON."""
    written = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    found = [record for record in written if record.get("kind") == kind]
    assert len(found) == 1, f"expected one {kind} record, got {len(found)}: {stdout}"
    return dict(found[0])


@pytest.fixture
def instance(tmp_path: Path, s3_server: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A migrated instance whose artifact root is a bucket nothing has created yet."""
    config_file = tmp_path / "dirigent.yaml"
    config_file.write_text(
        f'database_url: "sqlite+aiosqlite:///{tmp_path / "dirigent.db"}"\n'
        f'secret_key: "{Fernet.generate_key().decode()}"\n'
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config_file))
    monkeypatch.setenv("DIRIGENT_ARTIFACT_ROOT", f"s3://{FROM_THE_CLI}/artifacts")
    monkeypatch.setenv("DIRIGENT_STORAGE_CONNECTIONS", f"s3={CONNECTION}")
    reset_settings_cache()
    assert runner.invoke(app, ["--json", "db", "upgrade"]).exit_code == 0
    yield
    reset_settings_cache()


async def test_ensure_container_makes_the_bucket_and_then_finds_it(config: S3StorageConfig) -> None:
    backend = S3StorageBackend(config)
    made = await backend.ensure_container(f"s3://{MADE}/artifacts")
    assert (made.container, made.created, made.endpoint) == (MADE, True, config.endpoint_url)

    again = await backend.ensure_container(f"s3://{MADE}/artifacts")
    assert (again.container, again.created) == (MADE, False), "a second call makes nothing"

    already = await backend.ensure_container(f"s3://{BUCKET}/artifacts")
    assert (already.container, already.created) == (BUCKET, False)


async def test_an_object_lands_in_the_bucket_that_was_made(config: S3StorageConfig) -> None:
    """The proof the bucket is usable and not merely named: a write goes into it."""
    backend = S3StorageBackend(config)
    await backend.ensure_container(f"s3://{MADE}/artifacts")
    async with backend.open_write(f"s3://{MADE}/artifacts/proof.txt") as sink:
        await sink.write(PROOF)
    landed = await backend.stat(f"s3://{MADE}/artifacts/proof.txt")
    assert landed is not None and landed.size == len(PROOF)


def test_dg_storage_ensure_makes_the_bucket_the_artifact_root_addresses(instance: None, s3_server: str) -> None:
    """The stack's bootstrap, run the way the compose file runs it: the connection, then the bucket."""
    stored = runner.invoke(
        app,
        [
            "--json",
            "connection",
            "ensure",
            "s3",
            CONNECTION,
            "--set",
            f"endpoint_url={s3_server}",
            "--set",
            f"bucket={FROM_THE_CLI}",
            "--set",
            f"access_key_id={ACCESS_KEY}",
            "--set",
            f"secret_access_key={SECRET_KEY}",
            "--set",
            "path_style=true",
        ],
    )
    assert stored.exit_code == 0, stored.output

    result = runner.invoke(app, ["--json", "storage", "ensure"])
    assert result.exit_code == 0, result.output
    made = only(result.output, "storage.ensured")
    assert (made["bucket"], made["created"], made["endpoint"]) == (FROM_THE_CLI, True, s3_server)
    assert made["message"] == "created"
    assert SECRET_KEY not in result.output, "the credential is never part of the record"

    again = runner.invoke(app, ["--json", "storage", "ensure"])
    assert again.exit_code == 0, again.output
    assert only(again.output, "storage.ensured")["created"] is False, "re-running the stack makes nothing"
