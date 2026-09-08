"""The doubles behave like the thing they stand in for, or a block tested against them lies."""

from pathlib import Path

import httpx2
import pytest
from pydantic import BaseModel

from dirigent_plugin import RunState
from dirigent_testing import FakeContext, FakeRuns, FakeStorage, RecordingLogger


async def write(storage: FakeStorage, uri: str, payload: bytes) -> None:
    async with storage.open_write(uri) as sink:
        await sink.write(payload)


async def read(storage: FakeStorage, uri: str) -> list[bytes]:
    return [chunk async for chunk in storage.open_read(uri)]


async def test_what_was_written_reads_back_whole_but_never_in_one_chunk(block_storage: FakeStorage) -> None:
    await write(block_storage, "file://nested/one.txt", b"a stream of bytes")

    chunks = await read(block_storage, "file://nested/one.txt")

    assert len(chunks) == 2
    assert b"".join(chunks) == b"a stream of bytes"


async def test_a_single_byte_object_still_reads_back(block_storage: FakeStorage) -> None:
    await write(block_storage, "file://tiny.txt", b"x")

    assert await read(block_storage, "file://tiny.txt") == [b"x"]


async def test_stat_describes_an_object_and_reports_nothing_for_one_that_is_absent(
    block_storage: FakeStorage,
) -> None:
    await write(block_storage, "file://one.txt", b"12345")

    found = await block_storage.stat("file://one.txt")

    assert found is not None
    assert found.size == 5
    assert await block_storage.stat("file://missing.txt") is None


async def test_listing_a_glob_is_ordered_and_skips_directories(block_storage: FakeStorage) -> None:
    for name in ("c.txt", "a.txt", "b.txt"):
        await write(block_storage, f"file://drop/{name}", b"x")
    (block_storage.root / "drop" / "sub").mkdir()

    listed = [entry.uri async for entry in block_storage.list("file://drop/*")]

    assert listed == ["file://drop/a.txt", "file://drop/b.txt", "file://drop/c.txt"]


async def test_delete_removes_an_object_and_forgives_one_that_is_gone(block_storage: FakeStorage) -> None:
    await write(block_storage, "file://one.txt", b"x")

    await block_storage.delete("file://one.txt")
    await block_storage.delete("file://one.txt")

    assert await block_storage.stat("file://one.txt") is None


def test_an_absolute_uri_is_left_where_it_points(tmp_path: Path, block_storage: FakeStorage) -> None:
    target = tmp_path / "elsewhere" / "one.txt"

    assert block_storage.path_for(f"file://{target}") == target


def test_the_logger_keeps_every_level_with_its_fields() -> None:
    log = RecordingLogger()

    log.debug("looking")
    log.info("found", count=1)
    log.warning("slow")
    log.error("failed", reason="timeout")

    assert log.messages() == ["looking", "found", "slow", "failed"]
    assert log.entries[1] == ("info", "found", {"count": 1})
    assert log.entries[3] == ("error", "failed", {"reason": "timeout"})


async def test_the_runs_double_starts_skips_and_refuses_as_the_test_installs_it() -> None:
    runs = FakeRuns()

    started = await runs.start("daily", {"day": "2026-08-31"}, max_depth=3)

    assert started.run_id is not None
    assert runs.started == [("daily", {"day": "2026-08-31"}, 3)]
    snapshot = await runs.snapshot(started.run_id)
    assert snapshot is not None
    assert snapshot.state is RunState.QUEUED

    runs.skip.add("hourly")
    assert (await runs.start("hourly", {}, max_depth=3)).skipped


async def test_cancelling_a_run_settles_it_and_cancelling_a_settled_one_reports_nothing_to_stop() -> None:
    runs = FakeRuns()
    run_id = runs.hold("daily", RunState.RUNNING, total_steps=2, finished_steps=1)

    assert await runs.cancel(run_id, reason="operator asked") is True
    assert await runs.cancel(run_id, reason="again") is False
    assert runs.snapshots[run_id].error == "operator asked"


class Credential(BaseModel):
    token: str


def test_the_context_resolves_a_connection_the_test_installed(block_ctx: FakeContext) -> None:
    block_ctx.connections["dhis2"] = Credential(token="secret")

    assert block_ctx.connection("dhis2", Credential).token == "secret"


async def test_the_context_builds_a_client_on_the_handler_the_test_installed(block_ctx: FakeContext) -> None:
    block_ctx.handler = lambda request: httpx2.Response(200, json={"path": request.url.path})

    async with block_ctx.http("service") as client:
        response = await client.get("/health")

    assert response.json() == {"path": "/health"}


def test_asking_for_a_client_without_a_handler_says_so(block_ctx: FakeContext) -> None:
    with pytest.raises(AssertionError, match="installed no handler"):
        block_ctx.http("service")


def test_the_local_context_scratch_is_a_directory_a_shell_can_write_to(local_block_ctx: FakeContext) -> None:
    assert local_block_ctx.scratch.startswith("file://")
    assert local_block_ctx.storage.root.is_dir()
