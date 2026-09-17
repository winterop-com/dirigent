"""The ``jq`` engines: a jq program as the transform, map, and filter verbs' program.

A program is compiled here, where a bad one is refused with jq's own message, and evaluated
in a jq process of its own. jq is a C extension that holds the GIL for as long as a program
runs, so evaluating one on the worker would hold the event loop with it and starve the step
timeout and the lease heartbeat that share it. A program cannot be interrupted and a thread
cannot be cancelled, so the step's timeout ends a program the only way there is: the process
running it is killed, and the step fails with it.
"""

import asyncio
import atexit
import json
import subprocess
import sys
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import IO, Annotated, Any, ClassVar, cast

import jq
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import JQ_MEDIA_TYPE
from dirigent_plugin import Engine, Filterer, Mapper, ProgramConfig, Transformer, TransformError

#: What a program producing nothing is told to write instead.
NO_OUTPUT = (
    "the program produced no output, and a transform step has to produce one; "
    "a program that means 'possibly nothing' emits [] or null explicitly"
)

#: Wraps the author's program so jq's ``env`` and ``$ENV`` read an empty object instead of
#: the worker's environment, which is where dirigent's own secrets live. The program keeps
#: its own line numbers because the message a bad one is refused with comes from compiling
#: the author's text, unwrapped.
SANDBOX = "{} as $ENV | def env: {}; (\n"

#: The script a jq process runs, started by path so that it imports jq and the standard
#: library and nothing else.
RUNNER = Path(__file__).with_name("jq_runner.py")

#: What a step is told when the process running its program stopped on its own. It is not a
#: TransformError, because nothing about the program says it will happen again.
PROCESS_STOPPED = "the process running the jq program stopped before it answered"

#: Typed ``Any`` because the jq binding is a C extension that ships no type information.
libjq: Any = jq


def _compile(program: str) -> object:
    """Compile a jq program with env and $ENV shadowed, refusing a bad one with jq's own message.

    What is handed on is the sandboxed source rather than the compiled program, because the
    process that evaluates it compiles its own copy: compiling here is what refuses a bad
    program, at apply and again on the worker.
    """
    sandboxed = f"{SANDBOX}{program}\n)"
    try:
        # The author's text is compiled first, so a refusal carries jq's message about their
        # program and not about the wrapper.
        libjq.compile(program)
        libjq.compile(sandboxed)
    except ValueError as error:
        raise TransformError(str(error).strip()) from error
    return sandboxed


def _outputs(compiled: object, value: JsonValue) -> list[JsonValue]:
    """Run a compiled program over one value in this step's jq process and read its outputs."""
    return _running().run(cast("str", compiled), value)


class _Process:
    """One jq process, and the two pipes a program and its outputs cross."""

    def __init__(self) -> None:
        """Start the process and hold the pipes it is spoken to over."""
        self.process = subprocess.Popen(
            [sys.executable, str(RUNNER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        # Popen types both pipes as optional; both were asked for.
        self._to = cast("IO[bytes]", self.process.stdin)
        self._from = cast("IO[bytes]", self.process.stdout)

    @property
    def alive(self) -> bool:
        """Whether this process is still there to run a program."""
        return self.process.poll() is None

    def run(self, program: str, value: JsonValue) -> list[JsonValue]:
        """Send one program and one value, and read back the stream of outputs it produced."""
        try:
            self._to.write(json.dumps({"program": program, "value": value}).encode() + b"\n")
            self._to.flush()
            reply = self._from.readline()
        except OSError as error:
            raise RuntimeError(PROCESS_STOPPED) from error
        if not reply:
            # A killed process, which is how a cancelled step ends its program, and how a
            # program that ran the process out of memory ends itself.
            raise RuntimeError(PROCESS_STOPPED)
        answered = cast("dict[str, Any]", json.loads(reply))
        refusal = answered.get("error")
        if refusal is not None:
            raise TransformError(cast("str", refusal))
        return cast("list[JsonValue]", answered["outputs"])

    def kill(self) -> None:
        """End whatever is running, which is the only way to stop a jq program, and close it out.

        Waiting is what makes the process dead rather than dying, so the pool sees at once
        that this one is not to be handed out again; a killed process is reaped at once.
        Closing the pipes waits for the read a step's thread is still blocked in, which the
        kill has just ended, and leaves no descriptor behind for a collection to complain of.
        """
        self.process.kill()
        self.process.wait()
        self._to.close()
        self._from.close()


class _Processes:
    """The jq processes this worker keeps, one per transform step running at a time.

    A step holds one for as long as its program runs and gives it back after, so two steps
    never meet on one pipe. A process is started when there is none to hand out and then
    lives on, because starting one costs more than every program a step runs through it; it
    ends when the worker does, its pipe closing under it. A process that was killed is not
    handed out again.
    """

    def __init__(self) -> None:
        """Start with no processes; the first step that needs one starts it."""
        self._idle: list[_Process] = []

    async def take(self) -> _Process:
        """Hand out an idle process, starting one off the event loop when there is none."""
        while self._idle:
            process = self._idle.pop()
            if process.alive:
                return process
        starting = asyncio.ensure_future(asyncio.to_thread(_Process))
        try:
            return await asyncio.shield(starting)
        except asyncio.CancelledError:
            # A step can be cancelled while its process is still starting. The start is
            # shielded so the process is finished and kept, rather than left running for a
            # step that is already gone.
            starting.add_done_callback(self._started)
            raise

    def give_back(self, process: _Process) -> None:
        """Take a process back for the next step, unless it was killed."""
        if process.alive:
            self._idle.append(process)

    def shutdown(self) -> None:
        """Kill every idle process, so none is left running when this one exits."""
        while self._idle:
            self._idle.pop().kill()

    def _started(self, starting: "asyncio.Future[_Process]") -> None:
        """Keep a process whose step gave up on it while it was starting."""
        if not starting.cancelled() and starting.exception() is None:
            self.give_back(starting.result())


#: The jq processes this worker keeps. One pool per process rather than one per engine: the
#: three verbs run the same programs the same way, and a step holds a process, not a verb.
_PROCESSES = _Processes()

atexit.register(_PROCESSES.shutdown)

#: The jq process the step running on this task talks to. A program is evaluated from inside
#: the thread offload() hands the step's work to, which is where the engine reads it.
_RUNNING: ContextVar[_Process] = ContextVar("dirigent_jq_process")


def _running() -> _Process:
    """The jq process this step holds, which only a step running through offload() has."""
    try:
        return _RUNNING.get()
    except LookupError as error:
        missing = "a jq engine is called through offload(), which takes the process its program runs in"
        raise RuntimeError(missing) from error


class JqEngine(Engine):
    """Where the three jq engines' programs run: in a jq process, never on the worker's loop."""

    async def offload[T](self, work: Callable[[], T]) -> T:
        """Hold a jq process for the step, and kill it if the step is cancelled or times out."""
        process = await _PROCESSES.take()
        token = _RUNNING.set(process)
        try:
            return await asyncio.to_thread(work)
        except asyncio.CancelledError:
            # Cancelling the await does not stop the thread: it is inside a blocking read,
            # and killing the process is both what ends the program and what lets that read
            # return, so nothing is left running behind a step that has already failed.
            process.kill()
            raise
        finally:
            _RUNNING.reset(token)
            _PROCESSES.give_back(process)


class JqProgramConfig(ProgramConfig):
    """The program-shaped config of a jq engine, whichever verb is running it.

    All three verbs take the same program in the same language, so all three publish the
    same config: the frame's fields, with ``program`` narrowed to jq source.
    """

    program: Annotated[str, Field(min_length=1, json_schema_extra={"contentMediaType": JQ_MEDIA_TYPE})]
    """The jq program this step runs."""


class JqTransformer(JqEngine, Transformer):
    """Reshapes one whole value by running a jq program over it.

    A jq program opens no file, no socket, and starts nothing: it is handed a value and
    returns values, which is why this engine executes no code on the worker and needs no
    allowlist entry. Its two ways of reading an environment, ``env`` and ``$ENV``, are
    shadowed, so a program sees an empty object rather than the process it runs in -- which
    is a jq process of dirigent's own, so that a step's timeout can end it.

    A jq program is a stream: it can emit zero, one, or many outputs. One output is the
    step's value, many outputs are that list of values, and none is a refusal, because a
    step that produced nothing has no output for the next step to read.
    """

    kind = "jq"
    summary = "Reshape a value with a jq program."
    config_model: ClassVar[type[BaseModel]] = JqProgramConfig

    def compile(self, program: str) -> object:
        """Compile a jq program, refusing a bad one with jq's own message about it."""
        return _compile(program)

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run the program over one value, and read its stream of outputs as one result."""
        produced = _outputs(compiled, value)
        if not produced:
            raise TransformError(NO_OUTPUT)
        return produced[0] if len(produced) == 1 else produced


class JqMapper(JqEngine, Mapper):
    """Replaces every element of a list with what a jq program makes of that element.

    The program is run once per element, with the element as its input, and is sandboxed
    exactly as ``transform.jq`` is: ``env`` and ``$ENV`` read an empty object.

    A map replaces each element with one thing, so the stream a program emits for an element
    has to be exactly one output. Zero of them and several of them are both refusals rather
    than a shorter or longer list, because dropping elements is what ``filter.jq`` is for and
    changing their number is what ``transform.jq`` is for.
    """

    kind = "jq"
    summary = "Replace every element of a list with what a jq program makes of it."
    config_model: ClassVar[type[BaseModel]] = JqProgramConfig

    def compile(self, program: str) -> object:
        """Compile a jq program, refusing a bad one with jq's own message about it."""
        return _compile(program)

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run the program over one element, and take its single output as the replacement."""
        produced = _outputs(compiled, value)
        if len(produced) != 1:
            raise TransformError(
                f"the program produced {len(produced)} outputs, and a map replaces an element with "
                f"exactly one; a program that drops elements is a filter.jq step, and one that "
                f"changes how many there are is a transform.jq step"
            )
        return produced[0]


class JqFilterer(JqEngine, Filterer):
    """Keeps the elements of a list a jq program answers true for.

    The program is run once per element, with the element as its input, and is sandboxed
    exactly as ``transform.jq`` is: ``env`` and ``$ENV`` read an empty object.

    The answer has to be exactly one output, and that output has to be ``true`` or ``false``.
    jq's own truthiness is not applied: a program emitting ``0`` or ``""`` is a mistake
    surfaced rather than an element quietly dropped, and an author who means "has readings"
    writes ``.count > 0``.
    """

    kind = "jq"
    summary = "Keep the elements of a list a jq program answers true for."
    config_model: ClassVar[type[BaseModel]] = JqProgramConfig

    def compile(self, program: str) -> object:
        """Compile a jq program, refusing a bad one with jq's own message about it."""
        return _compile(program)

    def keep(self, compiled: object, value: JsonValue) -> bool:
        """Run the program over one element, and read its single boolean output as the verdict."""
        produced = _outputs(compiled, value)
        if len(produced) != 1:
            raise TransformError(
                f"the program produced {len(produced)} outputs, and a filter answers one true or false "
                f"per element; a program that reshapes an element is a map.jq or transform.jq step"
            )
        answer = produced[0]
        if not isinstance(answer, bool):
            raise TransformError(
                f"the program answered {json.dumps(answer)}, and a filter answers true or false; jq's "
                f"truthiness is not applied, so a program meaning 'has readings' writes '.count > 0'"
            )
        return answer
