"""The runner protocol: a program engine whose programs are compiled and run in a process of its own.

An engine that computes inside a C extension holding the interpreter's lock holds the
worker's event loop from a thread as firmly as from the loop itself, and a thread cannot be
cancelled: the step's timeout never fires, the lease heartbeat never runs, and the sweeper
hands the attempt to another worker while this one is still computing. Such an engine names
the ``command`` that starts a runner, and its programs run there, where killing the process
is what ends them.

A runner reads one JSON object per line and answers one JSON object per line, one reply per
request and in the order the requests arrived:

- ``{"kind": "compile", "id": ..., "program": ...}``, answered with ``{"ok": true}``, or
  with ``{"error": "..."}`` carrying the runner's own message about a program it refuses.
  A program that compiled is held under the id it was named by.
- ``{"kind": "run", "id": ..., "value": ...}``, answered with ``{"outputs": [...]}``, the
  stream the program produced, or with ``{"error": "..."}``.
- ``{"kind": "forget", "id": ...}``, answered with ``{"ok": true}``: the program is released.

A step's program therefore crosses the pipe once, however many elements it is run over. The
pipe closing is how the parent says it is done.
"""

import asyncio
import atexit
import json
import subprocess
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from typing import IO, Any, ClassVar, cast
from uuid import uuid4

from pydantic import BaseModel, JsonValue

from dirigent_common import Issue
from dirigent_plugin.messages import PROGRAM_REFUSED
from dirigent_plugin.transforms import Engine, ProgramConfig, TransformError

#: What a step is told when the process running its program stopped on its own. It is not a
#: TransformError, because nothing about the program says it will happen again.
RUNNER_STOPPED = "the process running the program stopped before it answered"


class ProgramRunner:
    """One runner process, and the two pipes a program and its outputs cross."""

    def __init__(self, command: Sequence[str]) -> None:
        """Start the process the command names and hold the pipes it is spoken to over."""
        self.command = tuple(command)
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        # Popen types both pipes as optional; both were asked for.
        self._to = cast("IO[bytes]", self.process.stdin)
        self._from = cast("IO[bytes]", self.process.stdout)
        self._compiled: set[str] = set()

    @property
    def alive(self) -> bool:
        """Whether this process is still there to run a program."""
        return self.process.poll() is None

    def compile(self, source: str) -> str:
        """Compile one program in this process and hand back the id it is run by."""
        identifier = uuid4().hex
        self._exchange({"kind": "compile", "id": identifier, "program": source})
        # Held only once it has compiled, so a refused program is never one to forget.
        self._compiled.add(identifier)
        return identifier

    def run(self, identifier: str, value: JsonValue) -> list[JsonValue]:
        """Run the program compiled under an id over one value and read the outputs it produced."""
        answered = self._exchange({"kind": "run", "id": identifier, "value": value})
        return cast("list[JsonValue]", answered["outputs"])

    def forget(self, identifier: str) -> None:
        """Release one compiled program."""
        self._compiled.discard(identifier)
        self._exchange({"kind": "forget", "id": identifier})

    def release(self) -> None:
        """Forget every program compiled here, so a runner outliving a step keeps none of them.

        A runner that has stopped took its programs with it, and there is nothing to say to
        a closed pipe.
        """
        if not self.alive:
            self._compiled.clear()
            return
        for identifier in sorted(self._compiled):
            self.forget(identifier)

    def kill(self) -> None:
        """End whatever is running, which is the only way to stop a program, and close it out.

        Waiting is what makes the process dead rather than dying, so the pool sees at once
        that this one is not to be handed out again; a killed process is reaped at once.
        Closing the pipes waits for the read a step's thread is still blocked in, which the
        kill has just ended, and leaves no descriptor behind for a collection to complain of.
        """
        self.process.kill()
        self.process.wait()
        self._to.close()
        self._from.close()

    def _exchange(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send one request, read the one reply to it, and raise what the runner refused."""
        try:
            self._to.write(json.dumps(request).encode() + b"\n")
            self._to.flush()
            reply = self._from.readline()
        except OSError as error:
            raise RuntimeError(RUNNER_STOPPED) from error
        if not reply:
            # A killed process, which is how a cancelled step ends its program, and how a
            # program that ran the process out of memory ends itself.
            raise RuntimeError(RUNNER_STOPPED)
        answered = cast("dict[str, Any]", json.loads(reply))
        refusal = answered.get("error")
        if refusal is not None:
            raise TransformError(cast("str", refusal))
        return answered


class _Runners:
    """The runner processes this worker keeps: one per command, and one per step running at a time.

    A step holds one for as long as its program runs and gives it back after, so two steps
    never meet on one pipe. A process is started when there is none to hand out and then
    lives on, because starting one costs more than every program a step runs through it; it
    ends when the worker does, its pipe closing under it. A process that was killed is not
    handed out again.
    """

    def __init__(self) -> None:
        """Start with no processes; the first step that needs one starts it."""
        self._idle: dict[tuple[str, ...], list[ProgramRunner]] = {}

    async def take(self, command: Sequence[str]) -> ProgramRunner:
        """Hand out an idle process for a command, starting one off the event loop when there is none."""
        idle = self._idle.setdefault(tuple(command), [])
        while idle:
            runner = idle.pop()
            if runner.alive:
                return runner
        starting = asyncio.ensure_future(asyncio.to_thread(ProgramRunner, command))
        try:
            return await asyncio.shield(starting)
        except asyncio.CancelledError:
            # A step can be cancelled while its process is still starting. The start is
            # shielded so the process is finished and kept, rather than left running for a
            # step that is already gone.
            starting.add_done_callback(self._started)
            raise

    def give_back(self, runner: ProgramRunner) -> None:
        """Take a process back for the next step that runs its command, unless it was killed."""
        if runner.alive:
            self._idle.setdefault(runner.command, []).append(runner)

    def shutdown(self) -> None:
        """Kill every idle process, so none is left running when this one exits."""
        for idle in self._idle.values():
            while idle:
                idle.pop().kill()

    def _started(self, starting: "asyncio.Future[ProgramRunner]") -> None:
        """Keep a process whose step gave up on it while it was starting."""
        if not starting.cancelled() and starting.exception() is None:
            self.give_back(starting.result())


#: The runner processes this worker keeps. One pool for every engine, keyed by the command
#: that starts a runner: a step holds a runner, not a verb.
_RUNNERS = _Runners()

atexit.register(_RUNNERS.shutdown)

#: The runner the step running on this task talks to. A program is compiled and run from
#: inside the thread offload() hands the step's work to, which is where the engine reads it.
_RUNNING: ContextVar[ProgramRunner] = ContextVar("dirigent_program_runner")


def _running() -> ProgramRunner:
    """The runner this step holds, which only a step running through offload() has."""
    try:
        return _RUNNING.get()
    except LookupError as error:
        missing = "a runner engine is called through offload(), which takes the process its program runs in"
        raise RuntimeError(missing) from error


class RunnerEngine(Engine):
    """A program engine whose programs are compiled and run in a runner process.

    The engine supplies the command that starts one and the source its runner compiles; the
    step holds one runner for its whole run, its program is compiled there once, every
    element is run through the id that compile answered with, and the id is forgotten when
    the runner is given back.

    The three program verbs are what this is for: ``convert`` has no program, so a codec
    engine has no runner either.
    """

    command: ClassVar[Sequence[str]]
    """What starts one runner process for this engine."""

    def source(self, program: str) -> str:
        """The source the runner compiles: the author's program, wrapped as the engine needs it."""
        return program

    def check_program(self, program: str) -> None:
        """Refuse a bad program at apply by raising TransformError, where an engine can read its own language.

        There is no runner outside a step, so an engine that cannot parse its language on
        the worker leaves a bad program to be refused when the step compiles it.
        """
        return

    def compile(self, program: str) -> object:
        """Compile the program in the runner this step holds and hand back the id it is run by."""
        return _running().compile(self.source(program))

    def outputs(self, compiled: object, value: JsonValue) -> list[JsonValue]:
        """Run a compiled program over one value in this step's runner and read its outputs."""
        return _running().run(cast("str", compiled), value)

    async def offload[T](self, work: Callable[[], T]) -> T:
        """Hold a runner for the step, and kill it if the step is cancelled or times out."""
        runner = await _RUNNERS.take(self.command)
        token = _RUNNING.set(runner)
        try:
            return await asyncio.to_thread(work)
        except asyncio.CancelledError:
            # Cancelling the await does not stop the thread: it is inside a blocking read,
            # and killing the process is both what ends the program and what lets that read
            # return, so nothing is left running behind a step that has already failed.
            runner.kill()
            raise
        finally:
            _RUNNING.reset(token)
            runner.release()
            _RUNNERS.give_back(runner)

    def check_config(self, config: BaseModel) -> list[Issue]:
        """Check the program at apply, where the engine's own reading of it is all there is."""
        if not isinstance(config, ProgramConfig):
            return []
        try:
            self.check_program(config.program)
        except TransformError as error:
            return [Issue.of(PROGRAM_REFUSED, detail=str(error))]
        return []
