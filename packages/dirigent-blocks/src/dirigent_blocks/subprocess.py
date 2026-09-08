"""Running a child process on the worker: its workspace, its environment, and its lifetime.

Three blocks run code on the worker -- ``shell.run`` a command, ``docker.compose`` the
compose CLI, ``docker.build`` buildx -- and all three want the same containment: a process in
a session of its own so what it starts dies with it, an environment built from an allowlist
rather than inherited wholesale, and a workspace of its own inside the run's work directory.
That shared machinery lives here so a block is only the argv it assembles and the output it
parses.
"""

import asyncio
import contextlib
import os
import signal
from collections.abc import Sequence
from pathlib import Path

from dirigent_blocks.capture import Drained, LiveLines, drain
from dirigent_blocks.environment import allowed
from dirigent_plugin import BlockFailure, ErrorClass, StepContext

#: Inherited whether or not a step's allowlist names them.
BASELINE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


def local_root(ctx: StepContext) -> Path:
    """The run's directory on this worker's own filesystem, made if it is not there yet.

    A block that must hand a real path to a tool -- a compose file, a build context, a bind
    mount -- needs a directory the filesystem can open, and paths it is given are relative to
    this one. It is the run's work directory, not its scratch prefix: scratch is storage,
    which on any multi-node instance is a bucket rather than a path.

    What is left here is reachable only by the worker that wrote it, so anything a later step
    must read goes to scratch through storage.
    """
    return ctx.work


def segment(ctx: StepContext, name: str) -> str:
    """The path this attempt's files sit at, under either of the run's two roots.

    ``{name}/{step}[/{item}]/attempt-{n}``. Both roots are the run's, so the step key and,
    inside a fan-out, the item id are what keep two steps of one run and two items of one step
    out of each other's files and working directories.
    """
    item = f"/{ctx.run_item_id}" if ctx.run_item_id is not None else ""
    return f"{name}/{ctx.step}{item}/attempt-{ctx.attempt}"


def prefix(ctx: StepContext, name: str) -> str:
    """The storage URI this attempt's artifact names are built on, under the run's scratch prefix."""
    return f"{ctx.scratch.rstrip('/')}/{segment(ctx, name)}"


def workspace(ctx: StepContext, name: str) -> Path:
    """This attempt's working directory inside the run's work directory, made if absent."""
    directory = local_root(ctx) / segment(ctx, name)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def environment(env_allowlist: list[str], env: dict[str, str], home: Path) -> dict[str, str]:
    """Build the process environment from an allowlist, never from wholesale inheritance."""
    built = allowed({*BASELINE_ENV, *env_allowlist})
    built["HOME"] = str(home)
    built.update(env)
    return built


async def run(
    *,
    directory: Path,
    ctx: StepContext,
    stdout_uri: str,
    stderr_uri: str,
    timeout_seconds: float,
    environ: dict[str, str],
    argv: list[str] | None = None,
    command: str | None = None,
    what: str = "the command",
    redact: Sequence[str] = (),
) -> tuple[int, Drained, Drained]:
    """Start the process, drain it under the timeout, and leave nothing of it behind.

    Both pipes are read as the process writes them and written straight through to storage,
    so what is held is two bounded ends of each stream rather than all of it: a process that
    prints more than the worker has memory for is a file, not a dead worker. Each stream's
    first lines go into the run log where they are printed, so a long command is visible
    working; ``redact`` names the strings it was handed that must not reach one of them.

    The process leads a session of its own, so what it starts is killable with it: a command
    is usually ``sh -c``, and killing the shell alone leaves the children doing the work.

    Nothing survives this function. The block's own timeout is one way out of it; the
    engine's step timeout, which cancels the coroutine from outside, is another, and a
    process that outlived that would run on under a worker that had stopped waiting for it.
    """
    started = (
        asyncio.create_subprocess_shell(
            command,
            cwd=directory,
            env=environ,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if command is not None
        else asyncio.create_subprocess_exec(
            *(argv or []),
            cwd=directory,
            env=environ,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    )
    process = await started
    pgid = group_of(process)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with ctx.storage.open_write(stdout_uri) as out_sink, ctx.storage.open_write(stderr_uri) as err_sink:
                out, err = await asyncio.gather(
                    drain(
                        process.stdout,
                        out_sink,
                        head_limit=ctx.inline_capture,
                        live=LiveLines(ctx, "stdout", redact=redact),
                    ),
                    drain(
                        process.stderr,
                        err_sink,
                        head_limit=ctx.inline_capture,
                        live=LiveLines(ctx, "stderr", redact=redact),
                    ),
                )
            await process.wait()
    except TimeoutError as error:
        raise BlockFailure(
            f"{what} did not finish within {timeout_seconds}s",
            error_class=ErrorClass.TRANSIENT,
        ) from error
    finally:
        await end(process, pgid)
    return process.returncode or 0, out, err


async def output(
    *,
    argv: list[str],
    directory: Path,
    environ: dict[str, str],
    timeout_seconds: float,
    what: str = "the command",
    stdin: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Run a short read-only command to completion and hand back both streams whole.

    For the small, bounded reads a block makes of a tool's own state -- ``compose ps``,
    ``compose config`` -- where the answer is parsed rather than streamed to an artifact.

    ``stdin`` is written to the process and the pipe closed, which is how a credential
    reaches a tool without ever being an argument.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=directory,
        env=environ,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    pgid = group_of(process)
    try:
        async with asyncio.timeout(timeout_seconds):
            out, err = await process.communicate(stdin)
    except TimeoutError as error:
        raise BlockFailure(
            f"{what} did not finish within {timeout_seconds}s",
            error_class=ErrorClass.TRANSIENT,
        ) from error
    finally:
        await end(process, pgid)
    return process.returncode or 0, out, err


def group_of(process: asyncio.subprocess.Process) -> int:
    """The process group to signal at the end, read while the leader is certainly still alive.

    ``os.getpgid`` fails once the leader has been reaped, so the group id is taken at the
    start and held: it outlives the leader for as long as any member of the group lives.
    """
    with contextlib.suppress(OSError):
        return os.getpgid(process.pid)
    return process.pid  # pragma: no cover - only reachable if the process is already gone


async def end(process: asyncio.subprocess.Process, pgid: int) -> None:
    """Kill the process group and reap it, whatever the reason for leaving.

    The group is signalled whether or not the leader is still running: a shell that
    backgrounded its work exits 0 while the work it started keeps the group alive, and that
    work must not outlive the step. A group the worker may not signal is not one this can do
    anything about, and neither that nor a group already gone is worth failing a step over.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        kill(pgid, process.pid)
    with contextlib.suppress(ProcessLookupError):
        await process.wait()


def kill(pgid: int, pid: int) -> None:
    """Kill a process group and everything in it, and never anything else.

    The group is only the command's own because it was started in a session of its own. A
    process that is not its group's leader shares the worker's group, and signalling that
    would kill the worker: kill just the process instead rather than everything running
    beside it.
    """
    if pgid > 1 and pgid != os.getpgrp():
        os.killpg(pgid, signal.SIGKILL)
    else:  # pragma: no cover - only reachable if the process stops leading its own session
        os.kill(pid, signal.SIGKILL)


__all__ = [
    "BASELINE_ENV",
    "end",
    "environment",
    "group_of",
    "kill",
    "local_root",
    "output",
    "prefix",
    "run",
    "segment",
    "workspace",
]
