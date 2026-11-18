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
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import NamedTuple, cast

from dirigent_block_execute.capture import Drained, LiveLines, drain
from dirigent_block_execute.environment import allowed
from dirigent_block_execute.messages import PATH_LEAVES_THE_WORK_DIRECTORY, PROGRAM_NOT_FOUND, TIMED_OUT
from dirigent_plugin import BlockFailure, ErrorClass, StepContext

#: Inherited whether or not a step's allowlist names them.
BASELINE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")

#: How long the pipes may stay open once the process has exited, held by what it left running.
PIPE_GRACE_SECONDS = 2.0

#: How often a process whose pipes are still open is checked for having exited.
EXIT_POLL_SECONDS = 0.1

#: How long a killed group's members that became the worker's own children are waited for.
REAP_SECONDS = 1.0


class Ran(NamedTuple):
    """What one child process left behind: how it exited, both streams, and where they were written."""

    code: int
    out: Drained
    err: Drained
    stdout_uri: str
    stderr_uri: str


def segment(ctx: StepContext, name: str) -> str:
    """The path this attempt's files sit at, inside the run's work directory.

    ``{name}/{step}[/{item}]/attempt-{n}``. The step key, and inside a fan-out the item id,
    are what keep two steps of one run and two items of one step out of each other's files.
    """
    item = f"/{ctx.run_item_id}" if ctx.run_item_id is not None else ""
    return f"{name}/{ctx.step}{item}/attempt-{ctx.attempt}"


def inside_work(root: Path, relative: str) -> Path:
    """A path the document named in the run's work directory, refused if a link leads it elsewhere.

    The config refuses one that is absolute or climbs out, which is a check on the text. A link a
    checkout or an earlier step left there is not, and a tool opening this path would follow it.
    """
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise BlockFailure(PATH_LEAVES_THE_WORK_DIRECTORY, error_class=ErrorClass.REJECTED, path=repr(relative))
    return path


def workspace(ctx: StepContext, name: str) -> Path:
    """This attempt's working directory inside the run's work directory, made if absent."""
    directory = ctx.work / segment(ctx, name)
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
    timeout_seconds: float,
    environ: dict[str, str],
    stdout_name: str = "stdout",
    stderr_name: str = "stderr",
    argv: list[str] | None = None,
    command: str | None = None,
    what: str = "the command",
    redact: Sequence[str] = (),
) -> Ran:
    """Start the process, drain it under the timeout, and leave nothing of it behind.

    Both pipes are read as the process writes them and written straight through to a capture
    the context opens and names, so what is held is two bounded ends of each stream rather
    than all of it: a process that prints more than the worker has memory for is a file, not
    a dead worker. The two names distinguish one command's streams from another's where a
    step runs more than one. Each stream's first lines go into the run log where they are
    printed, so a long command is visible working; ``redact`` names the strings it was
    handed that must not reach one of them.

    The process leads a session of its own, so what it starts is killable with it: a command
    is usually ``sh -c``, and killing the shell alone leaves the children doing the work. The
    process is done when it exits, not when its pipes close: a child it left running in the
    background holds them open, so once it has exited the pipes get a short grace and then the
    group is killed, and the step ends with the exit code it gave.

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
    try:
        process = await _started(started)
    except FileNotFoundError as error:
        program = (argv or ["the command"])[0]
        raise BlockFailure(PROGRAM_NOT_FOUND, error_class=ErrorClass.REJECTED, program=program, what=what) from error
    pgid = group_of(process)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with ctx.capture(stdout_name) as out_sink, ctx.capture(stderr_name) as err_sink:
                out, err = await _drained(
                    process,
                    pgid,
                    ctx,
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
        raise BlockFailure(TIMED_OUT, error_class=ErrorClass.TRANSIENT, what=what, seconds=timeout_seconds) from error
    finally:
        await end(process, pgid)
    return Ran(process.returncode or 0, out, err, out_sink.uri, err_sink.uri)


async def _drained(
    process: asyncio.subprocess.Process,
    pgid: int,
    ctx: StepContext,
    stdout: Coroutine[None, None, Drained],
    stderr: Coroutine[None, None, Drained],
) -> tuple[Drained, Drained]:
    """Read both pipes to their end, which comes at most a grace after the process has exited.

    A drain that fails stops the other, so neither writes to a capture that is being closed.
    """
    pipes = [asyncio.ensure_future(stdout), asyncio.ensure_future(stderr)]
    try:
        # The exit is read from the return code: waiting on the process also waits for its pipes.
        while not all(pipe.done() for pipe in pipes) and process.returncode is None:
            await asyncio.wait(pipes, timeout=EXIT_POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            _raise_failed(pipes)
        if not all(pipe.done() for pipe in pipes):
            await asyncio.wait(pipes, timeout=PIPE_GRACE_SECONDS, return_when=asyncio.FIRST_EXCEPTION)
            _raise_failed(pipes)
            if not all(pipe.done() for pipe in pipes):
                ctx.log.warning(
                    "the command exited and left processes holding its output; they were killed",
                    exit_code=process.returncode,
                )
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    kill(pgid, process.pid)
        return await pipes[0], await pipes[1]
    finally:
        for pipe in pipes:
            pipe.cancel()
        await asyncio.gather(*pipes, return_exceptions=True)


def _raise_failed(pipes: Sequence[asyncio.Future[Drained]]) -> None:
    """Raise what a drain that has failed raised."""
    for pipe in pipes:
        if pipe.done() and not pipe.cancelled() and pipe.exception() is not None:
            raise cast("BaseException", pipe.exception())


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
    try:
        process = await _started(
            asyncio.create_subprocess_exec(
                *argv,
                cwd=directory,
                env=environ,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        )
    except FileNotFoundError as error:
        raise BlockFailure(PROGRAM_NOT_FOUND, error_class=ErrorClass.REJECTED, program=argv[0], what=what) from error
    pgid = group_of(process)
    try:
        async with asyncio.timeout(timeout_seconds):
            out, err = await process.communicate(stdin)
    except TimeoutError as error:
        raise BlockFailure(TIMED_OUT, error_class=ErrorClass.TRANSIENT, what=what, seconds=timeout_seconds) from error
    finally:
        await end(process, pgid)
    return process.returncode or 0, out, err


async def _started(starting: Coroutine[None, None, asyncio.subprocess.Process]) -> asyncio.subprocess.Process:
    """The process once it has started, its group killed if the step is cancelled meanwhile.

    A cancel landing while asyncio is still connecting the pipes kills only the process it
    made, not what that process has already started; the start is let finish instead, and the
    whole group goes.
    """
    starting_task = asyncio.ensure_future(starting)
    try:
        return await asyncio.shield(starting_task)
    except asyncio.CancelledError:

        async def ended() -> None:
            process = await starting_task
            await end(process, group_of(process))

        with contextlib.suppress(Exception):
            await _through_cancels(ended())
        raise


def group_of(process: asyncio.subprocess.Process) -> int:
    """The process group to signal at the end, read while the leader is certainly still alive.

    ``os.getpgid`` fails once the leader has been reaped, so the group id is taken at the
    start and held: it outlives the leader for as long as any member of the group lives.
    """
    with contextlib.suppress(OSError):
        return os.getpgid(process.pid)
    return process.pid  # pragma: no cover - only reachable if the process is already gone


async def end(process: asyncio.subprocess.Process, pgid: int) -> None:
    """Kill the process group, reap it, and close its pipes, whatever the reason for leaving.

    The group is signalled whether or not the leader is still running: a shell that
    backgrounded its work exits 0 while the work it started keeps the group alive, and that
    work must not outlive the step. A group the worker may not signal is not one this can do
    anything about, and neither that nor a group already gone is worth failing a step over.

    A cancel that arrives while the group is being reaped does not stop the reaping: it is
    raised once the pipes are closed. Left half done, the process's pipes stay open with
    nothing reading them, and the descriptors outlive the step.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        kill(pgid, process.pid)
    await _through_cancels(_closed(process, pgid))


async def _closed(process: asyncio.subprocess.Process, pgid: int) -> None:
    """Wait for a killed process and its pipes, close the pipes whatever still holds them, and reap the group.

    The wait ends at the exit only when the pipes have closed too, and a process outside the
    group may still hold them, so the wait is bounded.
    """
    try:
        with contextlib.suppress(ProcessLookupError, TimeoutError):
            async with asyncio.timeout(PIPE_GRACE_SECONDS):
                await process.wait()
    finally:
        # asyncio.subprocess.Process has no public way to close its pipes.
        transport = cast("asyncio.SubprocessTransport | None", vars(process).get("_transport"))
        if transport is not None:
            transport.close()
    await reap(pgid)


async def _through_cancels[T](work: Coroutine[None, None, T]) -> T:
    """Run ``work`` to its end even when the caller is cancelled meanwhile, and raise the cancel after.

    An anyio cancel scope cancels again at every await, so one shielded await is not enough.
    """
    task = asyncio.ensure_future(work)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return task.result()


async def reap(pgid: int) -> None:
    """Collect the members of a killed group that were handed to the worker when their parent died.

    A process whose parent exits is reparented to the first process of its namespace, or to the
    nearest subreaper. In a container the worker is that process, and nothing else waits on
    them, so each would stay a zombie holding a process slot. Only children in ``pgid`` are
    waited for, never one asyncio is waiting on: those lead groups of their own.
    """
    if pgid <= 1 or pgid == os.getpgrp():
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + REAP_SECONDS
    while True:
        try:
            pid, _ = os.waitpid(-pgid, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            if loop.time() >= deadline:
                return
            await asyncio.sleep(EXIT_POLL_SECONDS / 10)


def kill(pgid: int, pid: int) -> None:
    """Kill a process group and everything in it, and never anything else.

    The group is only the command's own because it was started in a session of its own. A
    process that is not its group's leader shares the worker's group, and signalling that
    would kill the worker: kill just the process instead rather than everything running
    beside it.

    The group is stopped before it is killed. On macOS a group killed in one signal can lose a
    child before its shell, and the shell, woken by that, runs its next command before it dies.
    """
    if pgid > 1 and pgid != os.getpgrp():
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGSTOP)
        os.killpg(pgid, signal.SIGKILL)
    else:  # pragma: no cover - only reachable if the process stops leading its own session
        os.kill(pid, signal.SIGKILL)


__all__ = [
    "BASELINE_ENV",
    "Ran",
    "end",
    "environment",
    "group_of",
    "kill",
    "output",
    "reap",
    "run",
    "segment",
    "workspace",
]
