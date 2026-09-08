"""What a block author gets: one block, a config, a context, and something to assert on."""

from datetime import timedelta

import pytest
from pydantic import BaseModel, Field, ValidationError

from dirigent_plugin import NotYet, Operator, OperatorSpec, Sensor, SensorSpec, StepContext
from dirigent_testing import FakeContext, call_block


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
