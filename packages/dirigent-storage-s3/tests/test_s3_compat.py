"""The s3 lane: the claims only a real S3 API can prove, run against an S3-compatible server."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from pydantic import SecretStr

from dirigent_storage_s3 import S3Sink, S3StorageBackend, S3StorageConfig, open_client
from dirigent_storage_s3.connection import S3ConnectionKind
from s3server import BUCKET, LARGE_SIZE, payload, pending_uploads, uri

pytestmark = pytest.mark.s3


async def read_all(backend: S3StorageBackend, location: str) -> bytes:
    """Drain a streamed read into one value, which only the tests may do."""
    return b"".join([chunk async for chunk in backend.open_read(location)])


async def test_a_small_object_round_trips(backend: S3StorageBackend) -> None:
    data = b"the reference is the artifact\n"
    async with backend.open_write(uri("round/trip.txt")) as sink:
        assert await sink.write(data) == len(data)
        assert isinstance(sink, S3Sink)
        assert sink.upload_id is None
    assert await read_all(backend, uri("round/trip.txt")) == data


async def test_a_large_object_goes_out_multipart_and_comes_back_byte_identical(
    backend: S3StorageBackend,
) -> None:
    data = payload(LARGE_SIZE)
    async with backend.open_write(uri("large/object.bin")) as sink:
        for offset in range(0, len(data), 64 * 1024):
            await sink.write(data[offset : offset + 64 * 1024])
        assert isinstance(sink, S3Sink)
        assert sink.upload_id is not None
    described = await backend.stat(uri("large/object.bin"))
    assert described is not None
    assert described.size == LARGE_SIZE
    assert await read_all(backend, uri("large/object.bin")) == data


async def test_stat_describes_a_present_object_and_returns_none_for_an_absent_one(
    backend: S3StorageBackend,
) -> None:
    data = b"twelve bytes"
    async with backend.open_write(uri("stat/present.txt")) as sink:
        await sink.write(data)
    described = await backend.stat(uri("stat/present.txt"))
    assert described is not None
    assert described.uri == uri("stat/present.txt")
    assert described.size == len(data)
    assert described.modified_at.tzinfo is not None
    assert await backend.stat(uri("stat/absent.txt")) is None


async def test_list_takes_a_prefix_and_reaches_every_depth_below_it(backend: S3StorageBackend) -> None:
    keys = ["listing/a.csv", "listing/b.json", "listing/deep/c.csv", "elsewhere/d.csv"]
    for key in keys:
        async with backend.open_write(uri(key)) as sink:
            await sink.write(key.encode())
    found = sorted([result.uri async for result in backend.list(uri("listing/"))])
    assert found == [uri("listing/a.csv"), uri("listing/b.json"), uri("listing/deep/c.csv")]
    sizes = {result.uri: result.size async for result in backend.list(uri("listing/"))}
    assert sizes[uri("listing/a.csv")] == len(b"listing/a.csv")


async def test_list_takes_a_glob_whose_star_crosses_a_slash(backend: S3StorageBackend) -> None:
    for key in ["globbed/a.csv", "globbed/b.json", "globbed/deep/c.csv"]:
        async with backend.open_write(uri(key)) as sink:
            await sink.write(b"x")
    found = sorted([result.uri async for result in backend.list(uri("globbed/*.csv"))])
    assert found == [uri("globbed/a.csv"), uri("globbed/deep/c.csv")]


async def test_delete_removes_an_object_and_is_happy_about_one_that_is_gone(
    backend: S3StorageBackend,
) -> None:
    async with backend.open_write(uri("delete/me.txt")) as sink:
        await sink.write(b"transient")
    assert await backend.stat(uri("delete/me.txt")) is not None
    await backend.delete(uri("delete/me.txt"))
    assert await backend.stat(uri("delete/me.txt")) is None
    await backend.delete(uri("delete/me.txt"))
    await backend.delete(uri("delete/never-existed.txt"))


async def test_a_small_write_that_fails_never_puts_the_object(backend: S3StorageBackend) -> None:
    with pytest.raises(RuntimeError, match="mid-write"):
        async with backend.open_write(uri("aborted/small.txt")) as sink:
            await sink.write(b"half a thought")
            raise RuntimeError("mid-write")
    assert await backend.stat(uri("aborted/small.txt")) is None


async def test_a_multipart_write_that_fails_aborts_the_upload_and_leaves_no_object(
    backend: S3StorageBackend, config: S3StorageConfig
) -> None:
    with pytest.raises(RuntimeError, match="mid-write"):
        async with backend.open_write(uri("aborted/large.bin")) as sink:
            await sink.write(payload(LARGE_SIZE))
            assert isinstance(sink, S3Sink)
            assert sink.upload_id is not None
            raise RuntimeError("mid-write")
    assert await backend.stat(uri("aborted/large.bin")) is None
    assert await pending_uploads(config, "aborted/large.bin") == []


class RefusingComplete:
    """An S3 client that answers everything the real one does, except completing an upload."""

    def __init__(self, client: Any) -> None:
        """Wrap the real client."""
        self._client = client

    def __getattr__(self, name: str) -> Any:
        """Forward everything else to it."""
        return getattr(self._client, name)

    async def complete_multipart_upload(self, **kwargs: Any) -> Any:
        raise RuntimeError("completion refused")


async def test_a_multipart_upload_that_fails_to_complete_is_aborted(
    backend: S3StorageBackend, config: S3StorageConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finishing a write is part of it: a failure completing the upload leaves none outstanding."""

    @asynccontextmanager
    async def refusing(passed: S3StorageConfig) -> AsyncGenerator[Any]:
        async with open_client(passed) as client:
            yield RefusingComplete(client)

    monkeypatch.setattr("dirigent_storage_s3.backend.open_client", refusing)

    with pytest.raises(RuntimeError, match="completion refused"):
        async with backend.open_write(uri("refused/large.bin")) as sink:
            await sink.write(payload(LARGE_SIZE))
            assert isinstance(sink, S3Sink)
            assert sink.upload_id is not None

    monkeypatch.undo()
    assert await pending_uploads(config, "refused/large.bin") == []
    assert await backend.stat(uri("refused/large.bin")) is None


async def test_the_connection_check_reports_a_reachable_bucket(config: S3StorageConfig) -> None:
    report = await S3ConnectionKind().check(config)
    assert report.healthy is True
    assert BUCKET in (report.detail or "")


async def test_the_connection_check_lists_buckets_when_none_is_named(config: S3StorageConfig) -> None:
    report = await S3ConnectionKind().check(config.model_copy(update={"bucket": None}))
    assert report.healthy is True
    assert "buckets visible" in (report.detail or "")


async def test_the_connection_check_reports_a_bad_credential_rather_than_raising(
    config: S3StorageConfig,
) -> None:
    wrong = config.model_copy(update={"secret_access_key": SecretStr("not-the-secret")})
    report = await S3ConnectionKind().check(wrong)
    assert report.healthy is False
    assert report.detail
