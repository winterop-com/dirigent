"""What a block author gets: one block, a config, a context, and something to assert on."""

from datetime import timedelta

import pytest
from pydantic import BaseModel, Field, ValidationError

from dirigent_common import JsonMap
from dirigent_plugin import NotYet, Operator, OperatorSpec, Sensor, SensorSpec, StepContext
from dirigent_testing import FakeContext, call_block, carry_cursor


class GreetConfig(BaseModel):
    name: str = Field(min_length=1)


class GreetOutput(BaseModel):
    greeting: str


class Greet(Operator[GreetConfig, GreetOutput]):
    """An operator small enough to be read in one go, and real enough to run."""

    spec = OperatorSpec(id="test.greet", summary="Greets whoever the config names")
    config_model = GreetConfig
    output_model = GreetOutput

    async def execute(self, config: GreetConfig, ctx: StepContext) -> GreetOutput:
        ctx.log.info("greeting", name=config.name)
        return GreetOutput(greeting=f"hello {config.name}")


class WaitConfig(BaseModel):
    ready: bool = False


class WaitOutput(BaseModel):
    observed: bool


class Wait(Sensor[WaitConfig, WaitOutput]):
    """A sensor that reports NotYet until the config says the world is ready."""

    spec = SensorSpec(id="test.wait", summary="Waits for a flag in its own config")
    config_model = WaitConfig
    output_model = WaitOutput

    async def poke(self, config: WaitConfig, ctx: StepContext) -> WaitOutput | NotYet:
        if not config.ready:
            return NotYet(next_poll_in=timedelta(seconds=30))
        return WaitOutput(observed=True)


async def test_an_operator_runs_from_a_plain_dict_and_logs_what_it_did(block_ctx: FakeContext) -> None:
    output = await call_block(Greet(), {"name": "ada"}, block_ctx)

    assert isinstance(output, GreetOutput)
    assert output.greeting == "hello ada"
    assert block_ctx.log.messages() == ["greeting"]
    assert block_ctx.log.entries == [("info", "greeting", {"name": "ada"})]


async def test_a_config_the_schema_refuses_fails_before_the_block_runs(block_ctx: FakeContext) -> None:
    with pytest.raises(ValidationError):
        await call_block(Greet(), {"name": ""}, block_ctx)

    assert block_ctx.log.entries == []


async def test_a_sensor_that_is_not_ready_passes_its_notyet_through(block_ctx: FakeContext) -> None:
    result = await call_block(Wait(), {}, block_ctx)

    assert isinstance(result, NotYet)
    assert result.next_poll_in == timedelta(seconds=30)


async def test_a_sensor_that_is_ready_returns_its_output(block_ctx: FakeContext) -> None:
    result = await call_block(Wait(), {"ready": True}, block_ctx)

    assert isinstance(result, WaitOutput)
    assert result.observed is True


class TailConfig(BaseModel):
    batch: int = 2


class TailOutput(BaseModel):
    offsets: list[int]
    next_offset: int


class Tail(Sensor[TailConfig, TailOutput]):
    """Reads a notional stream: parks once, then takes a batch from where the cursor stands."""

    spec = SensorSpec(id="test.tail", summary="Tails a stream it keeps its place in")
    config_model = TailConfig
    output_model = TailOutput

    async def poke(self, config: TailConfig, ctx: StepContext) -> TailOutput | NotYet:
        held = ctx.cursor or {}
        offset = held.get("offset", 0)
        start = offset if isinstance(offset, int) else 0
        if not held.get("parked"):
            return NotYet(cursor={"offset": start, "parked": True})
        return TailOutput(offsets=list(range(start, start + config.batch)), next_offset=start + config.batch)

    def resume_cursor(self, output: TailOutput) -> JsonMap | None:
        return {"offset": output.next_offset}


async def test_a_sensor_says_nothing_about_where_it_left_off_unless_it_chooses_to(block_ctx: FakeContext) -> None:
    output = await call_block(Wait(), {"ready": True}, block_ctx)

    assert isinstance(output, WaitOutput)
    assert Wait().resume_cursor(output) is None


async def test_a_success_hands_the_next_poke_where_it_left_off(block_ctx: FakeContext) -> None:
    """Carried as a watch carries it: each batch starts where the one before it ended."""
    sensor = Tail()
    seen: list[list[int]] = []
    for _ in range(6):
        answer = await call_block(sensor, {}, block_ctx)
        if isinstance(answer, TailOutput):
            seen.append(answer.offsets)
        carry_cursor(sensor, answer, block_ctx)

    assert seen == [[0, 1], [2, 3], [4, 5]]
    assert block_ctx.cursor == {"offset": 6}


async def test_a_park_that_returns_no_cursor_leaves_the_one_that_was_there(block_ctx: FakeContext) -> None:
    block_ctx.cursor = {"offset": 4}
    answer = await call_block(Wait(), {}, block_ctx)

    carry_cursor(Wait(), answer, block_ctx)

    assert block_ctx.cursor == {"offset": 4}


async def test_a_success_from_a_sensor_that_keeps_no_place_starts_the_next_poke_fresh(
    block_ctx: FakeContext,
) -> None:
    block_ctx.cursor = {"offset": 4}
    answer = await call_block(Wait(), {"ready": True}, block_ctx)

    carry_cursor(Wait(), answer, block_ctx)

    assert block_ctx.cursor is None
