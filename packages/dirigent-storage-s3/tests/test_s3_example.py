"""``examples/s3/s3-round-trip.yaml``, executed for real against an S3-compatible server."""

from pathlib import Path
from typing import Any

import pytest

from dirigent_cli.local import ConnectionSpec, LocalOutcome, local_settings, run_document
from dirigent_client.enums import RunStatus
from dirigent_storage_s3 import S3StorageBackend, S3StorageConfig
from s3server import ACCESS_KEY, BUCKET, SECRET_KEY

pytestmark = pytest.mark.s3

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "s3" / "s3-round-trip.yaml"

#: The connection name the example requires, and the scheme it configures.
CONNECTION = "artifacts"
SCHEME = "s3"

DAY = "2026-01-01"


def connection_for(endpoint: str) -> ConnectionSpec:
    """Build the connection the example's header tells an operator to create."""
    return ConnectionSpec(
        code=CONNECTION,
        kind=SCHEME,
        config={
            "endpoint_url": endpoint,
            "access_key_id": ACCESS_KEY,
            "secret_access_key": SECRET_KEY,
            "path_style": True,
            "bucket": BUCKET,
        },
    )


async def test_the_s3_example_runs_as_written_and_the_object_lands(
    tmp_path: Path, s3_server: str, config: S3StorageConfig
) -> None:
    settings = local_settings(tmp_path).model_copy(update={"storage_connections": {SCHEME: CONNECTION}})
    outcome: LocalOutcome | None = None
    failures: list[Any] = []

    async for item in run_document(
        EXAMPLE.read_text(),
        params={"day": DAY, "bucket": BUCKET},
        connections=[connection_for(s3_server)],
        inherited=settings,
    ):
        if isinstance(item, LocalOutcome):
            outcome = item
            failures = list(item.failures)

    assert outcome is not None
    assert outcome.status is RunStatus.SUCCEEDED, [f"{f.step}: {f.error}" for f in failures]

    backend = S3StorageBackend(config)
    landed = await backend.stat(f"s3://{BUCKET}/daily/{DAY}.json")
    assert landed is not None, "the example claims to upload the artifact, and it did not"
    assert landed.size > 0

    body = b"".join([chunk async for chunk in backend.open_read(f"s3://{BUCKET}/daily/{DAY}.json")])
    assert DAY.encode() in body, "the object that landed is the one the run produced"


async def test_naming_a_connection_the_instance_does_not_have_fails_at_the_step_that_needs_it(
    tmp_path: Path, s3_server: str
) -> None:
    """The scheme binding is a real lookup, so a typo in it is a named refusal and not a silence."""
    settings = local_settings(tmp_path).model_copy(update={"storage_connections": {SCHEME: "no-such-connection"}})
    outcome: LocalOutcome | None = None
    async for item in run_document(
        EXAMPLE.read_text(),
        params={"day": DAY, "bucket": BUCKET},
        connections=[connection_for(s3_server)],
        inherited=settings,
    ):
        if isinstance(item, LocalOutcome):
            outcome = item

    assert outcome is not None
    assert outcome.status is RunStatus.FAILED
    upload = [failure for failure in outcome.failures if failure.step == "upload"]
    assert upload and "no connection coded 'no-such-connection'" in (upload[0].error or "")
