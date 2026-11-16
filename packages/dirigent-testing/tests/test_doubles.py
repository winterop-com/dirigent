"""The doubles behave like the thing they stand in for, or a block tested against them lies."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from dirigent_common import loggable
from dirigent_plugin import BlockFailure, ErrorClass, RunState
from dirigent_testing import FakeContext, FakeRuns, FakeStorage, RecordingLogger
from dirigent_testing.doubles import StorageRefused
from dirigent_testing.messages import TEST_REFUSAL


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


def test_an_absolute_uri_inside_the_root_is_left_where_it_points(tmp_path: Path, block_storage: FakeStorage) -> None:
    target = tmp_path / "inside" / "one.txt"

    assert block_storage.path_for(f"file://{target}") == target


@pytest.mark.parametrize(
    ("uri", "code"),
    [
        ("gopher://one.txt", "testing.unknown_scheme"),
        ("file:///etc/passwd", "testing.outside_root"),
        ("file://../outside.txt", "testing.outside_root"),
    ],
    ids=["unknown-scheme", "absolute-outside", "relative-outside"],
)
async def test_storage_refuses_a_scheme_it_does_not_serve_and_a_path_outside_its_root(
    tmp_path: Path, uri: str, code: str
) -> None:
    storage = FakeStorage(tmp_path / "root")
    with pytest.raises(StorageRefused) as refused:
        await write(storage, uri, b"x")
    assert refused.value.code == code
    assert not (tmp_path / "outside.txt").exists()


async def test_a_scheme_the_test_names_is_served_from_the_root(tmp_path: Path) -> None:
    storage = FakeStorage(tmp_path, schemes=("file", "s3"))
    await write(storage, "s3://bucket/one.txt", b"x")

    assert (tmp_path / "bucket" / "one.txt").read_bytes() == b"x"


async def test_an_absolute_scratch_lists_what_it_wrote(local_block_ctx: FakeContext) -> None:
    scratch = local_block_ctx.scratch
    await write(local_block_ctx.storage, f"{scratch}/a.txt", b"x")
    await write(local_block_ctx.storage, f"{scratch}/deeper/b.txt", b"y")

    assert await local_block_ctx.storage.stat(f"{scratch}/a.txt") is not None
    assert [entry.uri async for entry in local_block_ctx.storage.list(f"{scratch}/*")] == [f"{scratch}/a.txt"]
    assert [entry.uri async for entry in local_block_ctx.storage.list(scratch)] == [
        f"{scratch}/a.txt",
        f"{scratch}/deeper/b.txt",
    ]


async def test_a_failed_overwrite_leaves_the_object_as_it_was(block_storage: FakeStorage) -> None:
    await write(block_storage, "file://one.txt", b"whole")
    with pytest.raises(RuntimeError):
        async with block_storage.open_write("file://one.txt", content_type="text/csv") as sink:
            await sink.write(b"part")
            raise RuntimeError("the producer failed")

    assert await read(block_storage, "file://one.txt") == [b"wh", b"ole"]
    assert "file://one.txt" not in block_storage.content_types
    assert [path.name for path in block_storage.root.iterdir()] == ["one.txt"]


class _Installed(BaseModel):
    x: int = 1


class _Wanted(BaseModel):
    y: str = "y"


def _unknown_connection(ctx: FakeContext) -> object:
    return ctx.connection("nope", _Installed)


def _another_model(ctx: FakeContext) -> object:
    return ctx.connection("installed", _Wanted)


def _client_for_an_unknown_connection(ctx: FakeContext) -> object:
    return ctx.http("nope")


def _unknown_schema(ctx: FakeContext) -> object:
    return ctx.schema("nope")


@pytest.mark.parametrize(
    ("ask", "code"),
    [
        (_unknown_connection, "testing.unknown_connection"),
        (_another_model, "testing.connection_wrong_model"),
        (_client_for_an_unknown_connection, "testing.unknown_connection"),
        (_unknown_schema, "testing.unknown_schema"),
    ],
    ids=["unknown-connection", "wrong-model", "client-for-unknown-connection", "unknown-schema"],
)
def test_the_context_refuses_what_the_engine_refuses_and_as_the_engine_does(
    block_ctx: FakeContext, ask: Callable[[FakeContext], object], code: str
) -> None:
    block_ctx.connections["installed"] = _Installed()
    block_ctx.handler = lambda _request: httpx2.Response(200)
    with pytest.raises(BlockFailure) as refused:
        ask(block_ctx)
    assert (refused.value.code, refused.value.error_class) == (code, ErrorClass.REJECTED)


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

    assert await runs.cancel(run_id, TEST_REFUSAL, detail="an operator asked") is True
    assert await runs.cancel(run_id, TEST_REFUSAL, detail="again") is False
    assert runs.snapshots[run_id].error == "an operator asked"
    assert runs.snapshots[run_id].error_code == TEST_REFUSAL.code
    assert runs.snapshots[run_id].error_params == {"detail": "an operator asked"}


class Credential(BaseModel):
    token: str


async def test_a_capture_lands_under_the_scratch_prefix_with_the_type_it_was_opened_with(
    block_ctx: FakeContext,
) -> None:
    """The double names a capture as the engine does, so a block's URI assertions hold in a test."""
    async with block_ctx.capture("stdout") as sink:
        await sink.write(b"printed")

    assert sink.uri == f"{block_ctx.scratch}/step/attempt-1-stdout"
    assert block_ctx.storage.path_for(sink.uri).read_bytes() == b"printed"
    assert block_ctx.storage.content_types[sink.uri] == "text/plain"


async def test_two_attempts_of_one_step_capture_to_different_objects(block_ctx: FakeContext) -> None:
    async with block_ctx.capture("stdout") as first:
        await first.write(b"first")
    block_ctx.attempt = 2
    async with block_ctx.capture("stdout") as second:
        await second.write(b"second")

    assert first.uri != second.uri
    assert block_ctx.storage.path_for(first.uri).read_bytes() == b"first"
    assert block_ctx.storage.path_for(second.uri).read_bytes() == b"second"


def test_the_context_resolves_a_connection_the_test_installed(block_ctx: FakeContext) -> None:
    block_ctx.connections["acme"] = Credential(token="secret")

    assert block_ctx.connection("acme", Credential).token == "secret"


async def test_the_context_builds_a_client_on_the_handler_the_test_installed(block_ctx: FakeContext) -> None:
    block_ctx.connections["service"] = _Installed()
    block_ctx.handler = lambda request: httpx2.Response(200, json={"path": request.url.path})

    async with block_ctx.http("service") as client:
        response = await client.get("/health")

    assert response.json() == {"path": "/health"}


def test_asking_for_a_client_without_a_handler_says_so(block_ctx: FakeContext) -> None:
    block_ctx.connections["service"] = _Installed()
    with pytest.raises(AssertionError, match="installed no handler"):
        block_ctx.http("service")


def test_the_local_context_scratch_is_a_directory_a_shell_can_write_to(local_block_ctx: FakeContext) -> None:
    assert local_block_ctx.scratch.startswith("file://")
    assert local_block_ctx.storage.root.is_dir()


def test_the_recording_logger_keeps_each_field_in_the_shape_the_engine_stores() -> None:
    log = RecordingLogger()
    when = datetime(2026, 9, 6, 13, 45, tzinfo=UTC)
    fields: dict[str, Any] = {
        "when": when,
        "amount": Decimal("1.250"),
        "seen": {"b", "a"},
        "ratio": float("nan"),
        "raw": b"\x01",
    }
    log.info("done", **fields)
    assert log.entries == [
        (
            "info",
            "done",
            {"when": "2026-09-06T13:45:00+00:00", "amount": "1.250", "seen": ["a", "b"], "ratio": "NaN", "raw": "AQ=="},
        )
    ]
    assert log.entries[0][2]["when"] == loggable(when)
