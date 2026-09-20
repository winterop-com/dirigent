"""Tests for the runner protocol, driven by a runner whose whole language is five words."""

import asyncio
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import JsonValue

from dirigent_plugin import (
    BlockFailure,
    ErrorClass,
    Mapper,
    ProgramRunner,
    RunnerEngine,
    TransformConfig,
    Transformer,
    TransformError,
    runners,
)
from dirigent_testing import FakeContext, call_block
from echo_runner import PROGRAMS

#: The runner the engines here start, which speaks the protocol and knows five programs.
RUNNER = Path(__file__).with_name("echo_runner.py")

#: What starts one, and the key a runner is pooled under.
COMMAND = (sys.executable, str(RUNNER))

READINGS: list[JsonValue] = [1, 2, 3, 4, 5]


class EchoTransformer(RunnerEngine, Transformer):
    """A transform engine that reads none of its own language: a bad program is the step's to find."""

    kind = "echo"
    summary = "Run one program in a runner process."
    command: ClassVar[Sequence[str]] = COMMAND

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Run the program over the value and read its stream of outputs as one result."""
        produced = self.outputs(compiled, value)
        if not produced:
            raise TransformError("the program produced no output")
        return produced[0] if len(produced) == 1 else produced


class SpareTransformer(EchoTransformer):
    """The same engine started by a different command, which is a runner of its own."""

    kind = "spare"
    summary = "Run one program in a runner started differently."
    command: ClassVar[Sequence[str]] = (*COMMAND, "--spare")


class EchoMapper(RunnerEngine, Mapper):
    """A map engine that reads its own language well enough to refuse a bad program at apply."""

    kind = "echo"
    summary = "Replace every element with what one program makes of it."
    command: ClassVar[Sequence[str]] = COMMAND

    def check_program(self, program: str) -> None:
        """Refuse a word this runner's language does not have, without starting a runner."""
        if program not in PROGRAMS:
            raise TransformError(f"{program} is not a program this engine knows")

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Take the program's single output as the element's replacement."""
        produced = self.outputs(compiled, value)
        if len(produced) != 1:
            raise TransformError(f"the program produced {len(produced)} outputs, and a map replaces one with one")
        return produced[0]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every request line the parent sends, in the order it sent them."""
    recorded: list[dict[str, Any]] = []
    exchange = ProgramRunner._exchange  # pyright: ignore[reportPrivateUsage] - the wire under test

    def watched(self: ProgramRunner, request: dict[str, Any]) -> dict[str, Any]:
        recorded.append(request)
        return exchange(self, request)

    monkeypatch.setattr(ProgramRunner, "_exchange", watched)
    return recorded


@pytest.fixture
def taken(monkeypatch: pytest.MonkeyPatch) -> list[ProgramRunner]:
    """Every runner the pool hands a step, in the order it handed them out."""
    pool = runners._RUNNERS  # pyright: ignore[reportPrivateUsage] - the pool under test
    handed: list[ProgramRunner] = []
    take = pool.take

    async def watched(command: Sequence[str]) -> ProgramRunner:
        runner = await take(command)
        handed.append(runner)
        return runner

    monkeypatch.setattr(pool, "take", watched)
    return handed


@pytest.fixture
def runner() -> Iterator[ProgramRunner]:
    """One runner of this test's own, spoken to directly rather than through a step."""
    started = ProgramRunner(COMMAND)
    yield started
    started.kill()


def kinds(sent: list[dict[str, Any]]) -> list[str]:
    """The kind of every request sent, which is the shape of the conversation."""
    return [request["kind"] for request in sent]


async def test_a_step_sends_its_program_once_however_many_elements_it_runs(
    block_ctx: FakeContext, sent: list[dict[str, Any]]
) -> None:
    output = await call_block(EchoMapper(), {"input": READINGS, "program": "double"}, block_ctx)

    assert output.model_dump()["value"] == [2, 4, 6, 8, 10]
    assert kinds(sent) == ["compile", "run", "run", "run", "run", "run", "forget"]
    assert [request["program"] for request in sent if request["kind"] == "compile"] == ["double"]


async def test_a_program_the_runner_refuses_is_refused_before_an_element_is_sent(
    block_ctx: FakeContext, sent: list[dict[str, Any]]
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(EchoMapper(), {"input": READINGS, "program": "quadruple"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "quadruple is not a program" in raised.value.message
    assert kinds(sent) == ["compile"]


async def test_a_value_the_program_cannot_work_on_is_rejected_naming_the_element(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(EchoMapper(), {"input": [1, "two"], "program": "double"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message.startswith("element 1: ")
    assert 'cannot double "two"' in raised.value.message


async def test_a_step_gives_its_runner_back_holding_nothing_of_its_own(
    block_ctx: FakeContext, sent: list[dict[str, Any]], taken: list[ProgramRunner]
) -> None:
    await call_block(EchoTransformer(), {"input": "ada", "program": "echo"}, block_ctx)
    compiled = next(request["id"] for request in sent if request["kind"] == "compile")

    assert kinds(sent)[-1] == "forget"
    with pytest.raises(TransformError) as raised:
        taken[0].run(compiled, "ada")
    assert compiled in str(raised.value)


def test_an_id_no_program_was_compiled_under_is_an_error_naming_it(runner: ProgramRunner) -> None:
    with pytest.raises(TransformError) as raised:
        runner.run("nothing_was_compiled_here", 1)

    assert "nothing_was_compiled_here" in str(raised.value)


def test_a_forgotten_program_is_released_and_the_source_compiles_again_under_a_new_id(
    runner: ProgramRunner,
) -> None:
    first = runner.compile("echo")
    runner.forget(first)

    with pytest.raises(TransformError):
        runner.run(first, 1)
    second = runner.compile("echo")
    assert second != first
    assert runner.run(second, 1) == [1]


def test_two_programs_in_one_runner_are_compiled_once_each_rather_than_over_each_other(
    runner: ProgramRunner, sent: list[dict[str, Any]]
) -> None:
    echo = runner.compile("echo")
    twice = runner.compile("twice")

    answered = [runner.run(echo, 1), runner.run(twice, 2), runner.run(echo, 3), runner.run(twice, 4)]

    assert answered == [[1], [2, 2], [3], [4, 4]]
    assert kinds(sent).count("compile") == 2


async def test_a_cancelled_step_kills_the_runner_its_program_was_running_in(
    block_ctx: FakeContext, taken: list[ProgramRunner]
) -> None:
    """A program cannot be interrupted, so one that outlived its step would run on unwatched."""
    running = asyncio.create_task(call_block(EchoTransformer(), {"input": 1, "program": "forever"}, block_ctx))
    await asyncio.sleep(0.1)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert len(taken) == 1
    assert not taken[0].alive, "the program was left running"
    idle = runners._RUNNERS._idle  # pyright: ignore[reportPrivateUsage] - nothing killed is reused
    assert all(taken[0] not in kept for kept in idle.values())


async def test_a_runner_is_kept_per_command_so_two_engines_do_not_share_one_process(
    block_ctx: FakeContext, taken: list[ProgramRunner]
) -> None:
    await call_block(EchoTransformer(), {"input": "ada", "program": "echo"}, block_ctx)
    await call_block(SpareTransformer(), {"input": "ada", "program": "echo"}, block_ctx)

    assert taken[0] is not taken[1]
    assert [runner.command for runner in taken] == [COMMAND, (*COMMAND, "--spare")]


async def test_a_runner_that_ran_a_step_is_handed_to_the_next_one(
    block_ctx: FakeContext, taken: list[ProgramRunner]
) -> None:
    """Starting a process costs more than every program a step runs through it."""
    await call_block(EchoTransformer(), {"input": "ada", "program": "echo"}, block_ctx)
    await call_block(EchoTransformer(), {"input": "grace", "program": "twice"}, block_ctx)

    assert taken[0] is taken[1]


def test_an_engine_that_reads_its_own_language_refuses_a_bad_program_at_apply() -> None:
    config = EchoMapper.config_model.model_validate({"input": READINGS, "program": "quadruple"})

    assert EchoMapper().check_config(config) == ["quadruple is not a program this engine knows"]


def test_an_engine_that_reads_no_program_leaves_a_bad_one_to_the_step() -> None:
    """There is no runner at apply, so an engine that cannot parse its language checks nothing."""
    config = EchoTransformer.config_model.model_validate({"input": 1, "program": "quadruple"})

    assert EchoTransformer().check_config(config) == []


def test_a_config_carrying_no_program_has_nothing_to_check() -> None:
    assert EchoMapper().check_config(TransformConfig(input=1)) == []


def test_an_engine_called_outside_a_step_says_where_its_programs_run() -> None:
    with pytest.raises(RuntimeError, match="offload"):
        EchoTransformer().compile("echo")
