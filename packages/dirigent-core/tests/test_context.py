"""Tests for the context the engine hands a block: where a capture lands."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from dirigent_block_http import connections
from dirigent_common import base_format_checker, build_client
from dirigent_core.engine import context
from dirigent_core.engine.context import BufferedLogger, EngineStepContext
from dirigent_core.secrets import SecretBox
from dirigent_core.storage import Storage, build_storage
from dirigent_plugin import BlockFailure
from dirigent_testing import FakeRuns

# -- where a captured stream lands -----------------------------------------------


def _context(
    storage: Storage, scratch: str, work_root: Path, *, attempt: int = 1, item: UUID | None = None
) -> EngineStepContext:
    """A context bound to one attempt of one step, carrying what a capture reads."""
    run_id = uuid4()
    return EngineStepContext(
        run_id=run_id,
        instance_id=uuid4(),
        step="load",
        run_item_id=item,
        attempt=attempt,
        started_at=datetime.now(UTC),
        inline_capture=8 * 1024,
        params={},
        log=BufferedLogger(run_id=run_id, step_name="load", limit=100, batch=10),
        storage=storage,
        scratch=scratch,
        work_root=str(work_root),
        connections={},
        connection_models={},
        secrets=SecretBox(None),
        runs=FakeRuns(),
        format_checker=base_format_checker(),
    )


def test_a_work_root_the_worker_cannot_write_is_named(tmp_path: Path) -> None:
    """A work root owned by someone else fails the step by name, not as an unexplained OSError."""
    taken = tmp_path / "work"
    taken.write_text("a file where the work root's directory should be")
    context = _context(build_storage(f"file://{tmp_path}"), f"file://{tmp_path}/runs/one", taken)

    with pytest.raises(BlockFailure) as raised:
        _ = context.work

    assert raised.value.code == "run.work_unwritable"
    assert raised.value.params["path"] == str(taken / "runs" / str(context.run_id))
    assert "DIRIGENT_WORK_ROOT" in raised.value.message


async def test_a_capture_is_named_under_the_scratch_prefix_and_reads_back(tmp_path: Path) -> None:
    scratch = f"file://{tmp_path}/runs/one"

    async with _context(build_storage(f"file://{tmp_path}"), scratch, tmp_path).capture("stdout") as sink:
        await sink.write(b"printed")

    assert sink.uri == f"{scratch}/load/attempt-1-stdout"
    assert (tmp_path / "runs/one/load/attempt-1-stdout").read_bytes() == b"printed"


async def test_two_attempts_of_one_step_capture_to_different_objects(tmp_path: Path) -> None:
    """The attempt is in the name, so a retry never writes over what the first attempt printed."""
    storage = build_storage(f"file://{tmp_path}")
    scratch = f"file://{tmp_path}/runs/one"

    async with _context(storage, scratch, tmp_path, attempt=1).capture("stdout") as first:
        await first.write(b"first")
    async with _context(storage, scratch, tmp_path, attempt=2).capture("stdout") as second:
        await second.write(b"second")

    assert first.uri != second.uri
    assert (tmp_path / "runs/one/load/attempt-1-stdout").read_bytes() == b"first"
    assert (tmp_path / "runs/one/load/attempt-2-stdout").read_bytes() == b"second"


async def test_a_fan_out_item_captures_under_its_own_path(tmp_path: Path) -> None:
    """Two items of one step run the same block at the same attempt, so the item id parts them."""
    scratch = f"file://{tmp_path}/runs/one"
    item = uuid4()

    async with _context(build_storage(f"file://{tmp_path}"), scratch, tmp_path, item=item).capture("err") as sink:
        await sink.write(b"one item")

    assert sink.uri == f"{scratch}/load/{item}/attempt-1-err"


def test_a_step_and_a_connection_check_build_their_client_with_one_function() -> None:
    assert context.build_client is connections.build_client is build_client
