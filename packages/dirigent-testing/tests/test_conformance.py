"""A pack's conformance kit: its examples checked against its own contribution, without core."""

from pathlib import Path

from pydantic import Field

from dirigent_common import BlockModel
from dirigent_plugin import (
    Contribution,
    NotYet,
    Operator,
    OperatorSpec,
    Sensor,
    SensorSpec,
    StepContext,
)
from dirigent_testing import assert_contribution_conforms, check_pack_examples


class GreetConfig(BlockModel):
    name: str = Field(min_length=1)
    times: int = Field(default=1, ge=1)
    connection: str | None = None


class GreetOutput(BlockModel):
    greeting: str


class Greet(Operator[GreetConfig, GreetOutput]):
    """An operator with a config strict enough to refuse a bad example."""

    spec = OperatorSpec(id="demo.greet", summary="Greets whoever the config names")
    config_model = GreetConfig
    output_model = GreetOutput

    async def execute(self, config: GreetConfig, ctx: StepContext) -> GreetOutput:
        return GreetOutput(greeting=f"hello {config.name}")


class WaitConfig(BlockModel):
    ready: bool = False


class WaitOutput(BlockModel):
    observed: bool


class Wait(Sensor[WaitConfig, WaitOutput]):
    """A sensor, so the kit is exercised across both block surfaces."""

    spec = SensorSpec(id="demo.wait", summary="Waits for a flag in its own config")
    config_model = WaitConfig
    output_model = WaitOutput

    async def poke(self, config: WaitConfig, ctx: StepContext) -> WaitOutput | NotYet:
        return WaitOutput(observed=True) if config.ready else NotYet()


CONTRIBUTION = Contribution(operators=[Greet()], sensors=[Wait()])


def _write(directory: Path, name: str, body: str) -> Path:
    """Drop one example document on disk and return its path."""
    path = directory / name
    path.write_text(body)
    return path


def test_a_well_formed_example_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: Greets someone by name.
steps:
  hello:
    block: demo.greet
    config:
      name: ada
      times: 2
""",
    )

    assert check_pack_examples(CONTRIBUTION, tmp_path) == []


def test_a_step_naming_an_unknown_block_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-unknown.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-unknown
description: Names a block the pack does not contribute.
steps:
  hello:
    block: demo.absent
    config: {}
""",
    )

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 1
    assert "demo.absent" in issues[0]
    assert "does not contribute" in issues[0]


def test_a_config_violating_the_schema_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: Carries a config the block's schema refuses.
steps:
  hello:
    block: demo.greet
    config:
      name: ""
      times: 0
""",
    )

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert issues
    assert all(issue.startswith("demo-greet.yaml: step 'hello' config.") for issue in issues)


def test_code_that_does_not_match_the_filename_stem_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: not-the-filename
description: Coded after something other than its file.
steps:
  hello:
    block: demo.greet
    config:
      name: ada
""",
    )

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 1
    assert "not-the-filename" in issues[0]
    assert "demo-greet" in issues[0]


def test_a_reference_config_value_is_not_falsely_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: A reference stands in for a value only a run will know.
steps:
  hello:
    block: demo.greet
    config:
      name: ${params.who}
      times: ${params.count}
""",
    )

    assert check_pack_examples(CONTRIBUTION, tmp_path) == []


def test_a_connection_the_document_carries_satisfies_the_step(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: The step names a connection the document itself carries.
connections:
  demo-conn:
    kind: demo
steps:
  hello:
    block: demo.greet
    config:
      name: ada
      connection: demo-conn
""",
    )

    assert check_pack_examples(CONTRIBUTION, tmp_path) == []


def test_a_connection_the_document_does_not_carry_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: The step names a connection nothing carries.
steps:
  hello:
    block: demo.greet
    config:
      name: ada
      connection: absent-conn
""",
    )

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 1
    assert "absent-conn" in issues[0]
    assert "does not carry" in issues[0]


def test_a_well_formed_contribution_conforms() -> None:
    assert assert_contribution_conforms(CONTRIBUTION) == []


def test_a_block_whose_models_are_not_block_models_is_reported() -> None:
    from pydantic import BaseModel

    class LooseConfig(BaseModel):
        value: str = "x"

    class LooseOutput(BaseModel):
        done: bool = True

    class Loose(Operator[LooseConfig, LooseOutput]):
        spec = OperatorSpec(id="demo.loose", summary="Uses plain BaseModels, not BlockModels")
        config_model = LooseConfig
        output_model = LooseOutput

        async def execute(self, config: LooseConfig, ctx: StepContext) -> LooseOutput:
            return LooseOutput()

    issues = assert_contribution_conforms(Contribution(operators=[Loose()]))

    assert issues == [
        "demo.loose config_model is not a BlockModel",
        "demo.loose output_model is not a BlockModel",
    ]
