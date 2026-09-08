"""Tests for shell.run: the block that runs code on the worker, and what contains it."""

import os
from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dirigent_blocks.shell import ShellRunConfig, ShellRunOperator, ShellRunOutput
from dirigent_common import SHELL_MEDIA_TYPE
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext


async def run(ctx: FakeContext, config: ShellRunConfig) -> ShellRunOutput:
    """Run the block and narrow its result, which is never a remote handle."""
    output = await ShellRunOperator().execute(config, ctx.as_context())
    assert isinstance(output, ShellRunOutput)
    return output


def test_the_block_declares_that_it_executes_locally() -> None:
    assert ShellRunOperator.spec.local_execution is True
    assert ShellRunOperator.spec.idempotent is False


async def test_an_argv_command_runs_and_reports_its_output(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(argv=["echo", "hello"]))
    assert output.exit_code == 0
    assert output.stdout.strip() == "hello"
    assert output.stderr == ""
    assert output.stdout_bytes == len("hello\n")
    assert output.stdout_truncated is False
    assert output.stderr_truncated is False


async def test_a_shell_command_runs_through_a_shell(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(command="echo one && echo two"))
    assert output.stdout.split() == ["one", "two"]


async def test_both_streams_are_stored_as_artifacts(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(command="echo out; echo err 1>&2"))
    assert output.stdout_uri.startswith(local_ctx.scratch)
    assert local_ctx.storage.path_for(output.stdout_uri).read_bytes().strip() == b"out"
    assert local_ctx.storage.path_for(output.stderr_uri).read_bytes().strip() == b"err"
    assert "command finished" in local_ctx.log.messages()


async def test_a_non_zero_exit_fails_with_the_last_line_of_output(local_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await run(local_ctx, ShellRunConfig(command="echo bad things 1>&2; exit 3"))
    assert raised.value.error_class is ErrorClass.UNKNOWN
    assert "exited 3" in str(raised.value)
    assert "bad things" in str(raised.value)


async def test_a_command_that_outlives_its_timeout_is_killed_as_transient(local_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await run(local_ctx, ShellRunConfig(argv=["sleep", "5"], timeout=timedelta(milliseconds=200)))
    assert raised.value.error_class is ErrorClass.TRANSIENT
    assert "did not finish" in str(raised.value)


async def test_the_command_runs_inside_the_run_scratch_space(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(command="pwd"))
    assert "runs/one/shell" in output.stdout


async def test_two_steps_of_one_run_do_not_share_artifacts_or_a_workspace(local_ctx: FakeContext) -> None:
    """The scratch prefix is the run's, so the step key is what separates one step from another."""
    local_ctx.step = "first"
    first = await run(local_ctx, ShellRunConfig(command="pwd"))
    local_ctx.step = "second"
    second = await run(local_ctx, ShellRunConfig(command="pwd"))

    assert first.stdout_uri != second.stdout_uri
    assert first.stderr_uri != second.stderr_uri
    assert first.stdout.strip() != second.stdout.strip()
    assert local_ctx.storage.path_for(first.stdout_uri).exists()
    assert local_ctx.storage.path_for(second.stdout_uri).exists()


async def test_two_fan_out_items_of_one_step_do_not_share_artifacts_or_a_workspace(
    local_ctx: FakeContext,
) -> None:
    """Two items run the same step key, so the item id is what separates them."""
    local_ctx.run_item_id = uuid4()
    first = await run(local_ctx, ShellRunConfig(command="pwd"))
    local_ctx.run_item_id = uuid4()
    second = await run(local_ctx, ShellRunConfig(command="pwd"))

    assert first.stdout_uri != second.stdout_uri
    assert first.stderr_uri != second.stderr_uri
    assert first.stdout.strip() != second.stdout.strip()
    assert str(local_ctx.run_item_id) in second.stdout


async def test_a_relative_work_root_becomes_an_absolute_workspace(
    local_ctx: FakeContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A work root may be written relative to the worker's own working directory.

    Both helpers, because a block takes its working directory from one and the paths it hands
    a tool from the other.
    """
    from dirigent_blocks import subprocess

    monkeypatch.chdir(tmp_path)
    local_ctx.work_dir = Path("./state/work/runs/one")

    directory = subprocess.workspace(local_ctx.as_context(), "shell")
    root = subprocess.local_root(local_ctx.as_context())
    output = await run(local_ctx, ShellRunConfig(command="pwd"))

    assert directory.is_absolute()
    assert root.is_absolute()
    printed = Path(output.stdout.strip())
    assert printed.is_absolute()
    assert printed.is_relative_to(Path.cwd() / "state/work/runs/one")


async def test_a_command_runs_in_the_work_directory_not_the_scratch_prefix(
    block_ctx: FakeContext, tmp_path: Path
) -> None:
    """A scratch prefix that is no filesystem at all is no obstacle to running a command."""
    block_ctx.scratch_uri = "s3://bucket/artifacts/runs/one"
    output = await run(block_ctx, ShellRunConfig(command="pwd"))
    assert Path(output.stdout.strip()).is_relative_to(block_ctx.work)


async def test_a_relative_cwd_is_created_inside_the_workspace(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(command="pwd", cwd="work/inner"))
    assert output.stdout.strip().endswith("work/inner")


def test_an_escaping_cwd_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        ShellRunConfig(argv=["true"], cwd="/etc")
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        ShellRunConfig(argv=["true"], cwd="../../etc")


def test_exactly_one_command_form_is_required() -> None:
    with pytest.raises(ValidationError, match="exactly one of them"):
        ShellRunConfig()
    with pytest.raises(ValidationError, match="exactly one of them"):
        ShellRunConfig(argv=["true"], command="true")


def test_the_shell_form_publishes_itself_as_shell_source() -> None:
    """The form generating itself from this schema edits the shell string as a program."""
    published = ShellRunConfig.model_json_schema()["properties"]["command"]

    assert published["contentMediaType"] == SHELL_MEDIA_TYPE


async def test_the_environment_is_an_allowlist_and_not_an_inheritance(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLOCKTEST_SECRET", "do-not-leak")
    monkeypatch.setenv("BLOCKTEST_SHARED", "passed-through")

    hidden = await run(local_ctx, ShellRunConfig(command="echo [$BLOCKTEST_SECRET]"))
    assert hidden.stdout.strip() == "[]"

    shared = await run(
        local_ctx,
        ShellRunConfig(command="echo [$BLOCKTEST_SHARED]", env_allowlist=["BLOCKTEST_SHARED"]),
    )
    assert shared.stdout.strip() == "[passed-through]"


async def test_explicit_environment_variables_are_set(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(command="echo [$GREETING]", env={"GREETING": "hei"}))
    assert output.stdout.strip() == "[hei]"


async def test_path_is_always_available_so_ordinary_commands_run(local_ctx: FakeContext) -> None:
    output = await run(local_ctx, ShellRunConfig(command="echo $PATH"))
    assert output.stdout.strip() == os.environ.get("PATH", "")


def test_a_step_cannot_allowlist_the_instances_own_configuration() -> None:
    """``env_allowlist`` is a pipeline-document field, so it must not reach DIRIGENT_*."""
    with pytest.raises(ValidationError) as raised:
        ShellRunConfig(command="echo hi", env_allowlist=["DIRIGENT_SECRET_KEY"])
    assert "DIRIGENT_SECRET_KEY" in str(raised.value)


async def test_a_reserved_variable_is_filtered_even_if_a_stored_document_names_one(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation is where a person is told; the filter is what holds for what is already stored."""
    monkeypatch.setenv("DIRIGENT_SECRET_KEY", "do-not-leak")
    config = ShellRunConfig(command="echo [$DIRIGENT_SECRET_KEY]")
    object.__setattr__(config, "env_allowlist", ["DIRIGENT_SECRET_KEY"])
    output = await run(local_ctx, config)
    assert output.stdout.strip() == "[]"


async def test_a_stream_past_the_inline_cap_is_cut_in_the_output_and_whole_in_the_artifact(
    local_ctx: FakeContext,
) -> None:
    """Two streams overflow independently, so one boolean could only have been wrong about one."""
    local_ctx.inline_capture = 16
    output = await run(local_ctx, ShellRunConfig(command="printf 'x%.0s' $(seq 1 100)"))
    assert output.stdout == "x" * 16
    assert output.stdout_bytes == 100
    assert output.stdout_truncated is True
    assert output.stderr_truncated is False, "the other stream printed nothing and was not cut"
    assert local_ctx.storage.path_for(output.stdout_uri).read_bytes() == b"x" * 100


async def test_a_cancelled_step_does_not_leave_the_command_running(local_ctx: FakeContext) -> None:
    """The engine's own step timeout cancels the coroutine; the process has to go with it.

    A block that only kills on its own timeout leaves the command running under a worker that
    has stopped waiting for it, which is what `docs/security.md` promises cannot happen.
    """
    import asyncio

    marker = Path(local_ctx.storage.root) / "still-running"
    task = asyncio.create_task(run(local_ctx, ShellRunConfig(command=f"sleep 1; touch {marker}")))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(1.5)
    assert not marker.exists(), "the command outlived the step that was cancelled"


async def test_a_timeout_takes_the_commands_children_with_it(local_ctx: FakeContext) -> None:
    """`sh -c` is the process that is killed; what it started is what actually does the work."""
    import asyncio

    marker = Path(local_ctx.storage.root) / "child-survived"
    with pytest.raises(BlockFailure):
        await run(
            local_ctx,
            ShellRunConfig(command=f"(sleep 1; touch {marker}) & wait", timeout=timedelta(milliseconds=200)),
        )

    await asyncio.sleep(1.5)
    assert not marker.exists(), "killing the shell left its child running"


async def test_output_is_streamed_to_storage_rather_than_held_whole(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command's output reaches storage as it arrives, so its size is not the worker's problem.

    One write is the proof that the whole stream was buffered before any of it was stored.
    """
    from contextlib import asynccontextmanager

    writes: list[int] = []
    real = local_ctx.storage.open_write

    class Recording:
        """A sink that writes through and remembers how many times it was asked to."""

        def __init__(self, inner: object) -> None:
            self.inner = inner

        async def write(self, data: bytes) -> int:
            writes.append(len(data))
            return await self.inner.write(data)  # type: ignore[attr-defined,no-any-return]

    @asynccontextmanager
    async def recording(uri: str) -> AsyncGenerator[Recording]:
        async with real(uri) as sink:
            yield Recording(sink)

    monkeypatch.setattr(local_ctx.storage, "open_write", recording)
    printed = 400 * 1024

    output = await run(local_ctx, ShellRunConfig(command=f"head -c {printed} /dev/zero | tr '\\0' 'x'"))

    assert output.stdout_bytes == printed
    assert sum(writes) == printed, "not all of it reached storage"
    assert len([count for count in writes if count]) > 1, "the whole stream was buffered first"


async def test_a_stream_too_large_to_inline_still_says_how_much_there_was(local_ctx: FakeContext) -> None:
    """The head is what inlines; the count is of everything, and the artifact holds it all."""
    printed = 200 * 1024

    output = await run(local_ctx, ShellRunConfig(command=f"head -c {printed} /dev/zero | tr '\\0' 'x'"))

    assert output.stdout_bytes == printed
    assert output.stdout_truncated is True
    assert len(output.stdout) <= local_ctx.inline_capture
    stored = local_ctx.storage.path_for(output.stdout_uri).read_bytes()
    assert len(stored) == printed, "the artifact is short of what the command printed"


def _alive(pid: int) -> bool:
    """Whether a pid still names a process this worker could signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - the pid was recycled by another user
        return True
    return True


@pytest.mark.skipif(os.name != "posix", reason="process groups are a posix notion")
async def test_a_backgrounded_child_does_not_outlive_the_shell_that_started_it(local_ctx: FakeContext) -> None:
    """The shell exits 0 the moment it has backgrounded its work, and the work keeps running.

    Nothing is left to kill by return code, so the group is what the step takes with it.
    """
    import asyncio

    pidfile = Path(local_ctx.storage.root) / "child.pid"
    output = await run(local_ctx, ShellRunConfig(command=f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}"))
    assert output.exit_code == 0

    child = int(pidfile.read_text().strip())
    for _ in range(50):
        if not _alive(child):
            break
        await asyncio.sleep(0.1)
    assert not _alive(child), "the backgrounded child outlived the step"
