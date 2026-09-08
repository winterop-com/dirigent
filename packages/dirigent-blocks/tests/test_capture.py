"""Tests for what a drained stream puts into the run log, and when it puts it there."""

import asyncio

from dirigent_blocks.capture import LOGGED_LINES, REDACTED, Drained, LiveLines, log_stream
from dirigent_blocks.shell import ShellRunConfig, ShellRunOperator, ShellRunOutput
from dirigent_testing import FakeContext

BUDGET = LOGGED_LINES // 2


async def run(ctx: FakeContext, config: ShellRunConfig) -> ShellRunOutput:
    """Run the block and narrow its result, which is never a remote handle."""
    output = await ShellRunOperator().execute(config, ctx.as_context())
    assert isinstance(output, ShellRunOutput)
    return output


def logged(ctx: FakeContext, stream: str) -> list[str]:
    """The messages the run log holds for one stream, in order."""
    return [message for _, message, fields in ctx.log.entries if fields.get("stream") == stream]


async def test_a_line_reaches_the_log_while_the_process_is_still_running(local_ctx: FakeContext) -> None:
    """A command that prints, waits, then prints has its first line logged during the wait."""
    call = asyncio.create_task(run(local_ctx, ShellRunConfig(command="echo one; sleep 3; echo two")))
    try:
        for _ in range(100):
            if "one" in logged(local_ctx, "stdout"):
                break
            await asyncio.sleep(0.05)
        assert "one" in logged(local_ctx, "stdout"), "the first line waited for the process to exit"
        assert "two" not in logged(local_ctx, "stdout"), "the second line was logged before it was printed"
        assert not call.done()
    finally:
        await call
    assert logged(local_ctx, "stdout") == ["one", "two"]


async def test_the_live_budget_holds_and_the_tail_is_not_a_repeat(local_ctx: FakeContext) -> None:
    """A stream past the budget is logged from both ends, and no line is logged twice."""
    await run(local_ctx, ShellRunConfig(command="seq 1 100"))

    lines = logged(local_ctx, "stdout")
    head = [str(number) for number in range(1, BUDGET + 1)]
    tail = [str(number) for number in range(101 - BUDGET, 101)]
    assert lines == [*head, f"... {100 - 2 * BUDGET} more lines, see the stdout artifact ...", *tail]
    assert len(set(lines)) == len(lines), "a line was logged twice"


async def test_a_stream_inside_the_budget_is_logged_once_and_only_live(local_ctx: FakeContext) -> None:
    await run(local_ctx, ShellRunConfig(command=f"seq 1 {BUDGET}"))

    assert logged(local_ctx, "stdout") == [str(number) for number in range(1, BUDGET + 1)]


async def test_a_stream_just_past_the_budget_logs_only_what_was_never_said(local_ctx: FakeContext) -> None:
    """The tail is capped by what is left unsaid, not by half the budget."""
    await run(local_ctx, ShellRunConfig(command=f"seq 1 {BUDGET + 2}"))

    assert logged(local_ctx, "stdout") == [str(number) for number in range(1, BUDGET + 3)]


async def test_a_last_line_without_a_newline_is_logged_when_the_stream_closes(local_ctx: FakeContext) -> None:
    await run(local_ctx, ShellRunConfig(command="printf 'unterminated'"))

    assert logged(local_ctx, "stdout") == ["unterminated"]


async def test_both_streams_are_logged_independently_and_at_their_own_levels(local_ctx: FakeContext) -> None:
    await run(local_ctx, ShellRunConfig(command="echo out; echo err 1>&2"))

    assert logged(local_ctx, "stdout") == ["out"]
    assert logged(local_ctx, "stderr") == ["err"]
    levels = {stream: level for level, _, fields in local_ctx.log.entries if (stream := fields.get("stream"))}
    assert levels == {"stdout": "info", "stderr": "warning"}


async def test_a_secret_never_reaches_a_live_line(local_ctx: FakeContext) -> None:
    """The redaction a block asks for applies to a line logged as it is printed."""
    from dirigent_blocks import subprocess

    workspace = subprocess.workspace(local_ctx.as_context(), "shell")
    code, out, err = await subprocess.run(
        directory=workspace,
        ctx=local_ctx.as_context(),
        stdout_uri=f"{local_ctx.scratch}/out.txt",
        stderr_uri=f"{local_ctx.scratch}/err.txt",
        timeout_seconds=30,
        environ=subprocess.environment([], {}, workspace),
        command="echo 'token s3cret in the clear'; echo 's3cret again' 1>&2",
        redact=["s3cret"],
    )
    log_stream(local_ctx.as_context(), "stdout", out, ["s3cret"])
    log_stream(local_ctx.as_context(), "stderr", err, ["s3cret"])

    assert code == 0
    assert logged(local_ctx, "stdout") == [f"token {REDACTED} in the clear"]
    assert logged(local_ctx, "stderr") == [f"{REDACTED} again"]


async def test_a_chatty_process_drains_whole_while_the_log_gets_only_the_budget(local_ctx: FakeContext) -> None:
    """A hundred thousand lines are a file; the log holds both ends of it and nothing more."""
    printed = 100_000

    output = await run(local_ctx, ShellRunConfig(command=f"seq 1 {printed}"))

    stored = local_ctx.storage.path_for(output.stdout_uri).read_text()
    assert stored.count("\n") == printed
    lines = logged(local_ctx, "stdout")
    assert len(lines) == 2 * BUDGET + 1
    assert lines[0] == "1"
    assert lines[-1] == str(printed)
    assert lines[BUDGET] == f"... {printed - 2 * BUDGET} more lines, see the stdout artifact ..."


def test_a_stream_nobody_logged_live_is_still_logged_from_both_ends(ctx: FakeContext) -> None:
    """The path docker.run takes, where the ends are read from a container rather than a pipe."""
    log_stream(ctx.as_context(), "stdout", Drained(head=b"one\ntwo\n", tail=b"one\ntwo\n", total_bytes=8))

    assert logged(ctx, "stdout") == ["one", "two"]


def test_a_blank_line_is_neither_logged_nor_counted(ctx: FakeContext) -> None:
    live = LiveLines(ctx.as_context(), "stdout")
    live.feed(b"one\n\n   \ntwo\n")
    live.close()

    assert live.logged() == (2, 2)
    assert logged(ctx, "stdout") == ["one", "two"]


def test_a_line_split_across_chunks_is_logged_whole(ctx: FakeContext) -> None:
    live = LiveLines(ctx.as_context(), "stdout")
    live.feed(b"be")
    live.feed(b"gin")
    live.feed(b"ning\nrest")
    live.close()

    assert logged(ctx, "stdout") == ["beginning", "rest"]
