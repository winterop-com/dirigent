"""A pack's conformance kit: its examples checked against its own contribution, without core."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from dirigent_common import BlockModel, CredentialForm, HealthReport, JsonMap
from dirigent_plugin import (
    ConnectionKind,
    ConnectionRef,
    Contribution,
    NotYet,
    Operator,
    OperatorSpec,
    Sensor,
    SensorSpec,
    StepContext,
)
from dirigent_plugin.sources import PollContext, Polled, PolledSource, SourceHosting, SourceSpec
from dirigent_testing import assert_contribution_conforms, check_pack_examples


class GreetConfig(BlockModel):
    name: str = Field(min_length=1)
    times: int = Field(default=1, ge=1)
    connection: ConnectionRef | None = None
    reply_to: ConnectionRef | None = None


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


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feed: ConnectionRef
    every: int = Field(default=60, ge=1)


class FeedEntry(BaseModel):
    seen_at: datetime


class Feed(PolledSource[FeedConfig, FeedEntry]):
    """A source kind the pack contributes, so its examples may start from it."""

    spec = SourceSpec(kind="demo.feed", summary="Polls a feed", hosting=SourceHosting.POLLED)
    config_model = FeedConfig
    output_model = FeedEntry

    def complete(self, config: FeedConfig, given: JsonMap, *, received_at: datetime) -> FeedEntry:
        return FeedEntry(seen_at=received_at)

    async def poll(self, config: FeedConfig, cursor: JsonMap | None, ctx: PollContext, limit: int) -> Polled[FeedEntry]:
        return Polled()


CONTRIBUTION = Contribution(operators=[Greet()], sensors=[Wait()], sources=[Feed()])


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


def test_a_connection_the_document_requires_satisfies_the_step(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: The step names a connection the document requires of the instance.
requires:
  connections:
    - demo-conn
steps:
  hello:
    block: demo.greet
    config:
      name: ada
      connection: demo-conn
""",
    )

    assert check_pack_examples(CONTRIBUTION, tmp_path) == []


def test_a_connection_the_document_does_not_account_for_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: The step names a connection nothing accounts for.
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
    assert "neither carries nor requires" in issues[0]


def test_a_well_formed_contribution_conforms() -> None:
    assert assert_contribution_conforms(CONTRIBUTION) == []


def test_a_block_whose_models_are_not_block_models_is_reported() -> None:
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


class DemoConnectionConfig(BlockModel):
    base_url: str = "https://demo.invalid"


class DemoConnectionKind(ConnectionKind):
    """A connection kind a pack's own tests run the kit over."""

    id = "demo"
    config_model = DemoConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Report the connection as healthy."""
        return HealthReport(healthy=True, detail="demo")


def test_a_connection_kind_that_declares_no_mark_conforms() -> None:
    assert assert_contribution_conforms(Contribution(connection_kinds=[DemoConnectionKind()])) == []


def test_a_credential_form_naming_a_field_the_config_lacks_is_reported() -> None:
    class Keyed(DemoConnectionKind):
        """A connection kind whose credential form names a field that is not there."""

        id = "keyed"
        credential_forms = (
            CredentialForm(code="url", fields=("base_url",)),
            CredentialForm(code="token", fields=("api_token",)),
        )

    assert assert_contribution_conforms(Contribution(connection_kinds=[Keyed()])) == [
        "connection kind keyed credential form 'token' names api_token, which its config model does not declare"
    ]


def test_a_connection_kind_that_declares_path_data_conforms() -> None:
    class Marked(DemoConnectionKind):
        """A connection kind wearing a mark of its own."""

        id = "marked"
        mark = "M12 2 L22 12 L12 22 L2 12 Z"

    assert assert_contribution_conforms(Contribution(connection_kinds=[Marked()])) == []


def test_a_mark_that_is_not_path_data_is_reported() -> None:
    class Injected(DemoConnectionKind):
        """A connection kind that goes on to claim something a browser must never be handed."""

        id = "injected"

    contribution = Contribution(connection_kinds=[Injected()])
    Injected.mark = '"/><script>alert(1)</script>'

    assert assert_contribution_conforms(contribution) == [
        "the mark that kind 'injected' declares is not SVG path data: it carries '\"()/<>ipr', which path data does not"
    ]


def _source_example(
    tmp_path: Path, source: str, *, connections: str = "requires:\n  connections: [the-feed]\n"
) -> None:
    """Write an example that starts from a source node and answers with a reply node."""
    _write(
        tmp_path,
        "demo-feed.yaml",
        f"""
format: dirigent/v1
kind: pipeline
code: demo-feed
description: Starts from the pack's own source kind.
{connections}
steps:
  arrived:
    source:
{source}
  hello:
    block: demo.greet
    depends_on: [arrived]
    config:
      name: ${{steps.arrived.output.seen_at}}
  answered:
    depends_on: [hello]
    reply:
      status: 200
      body: {{done: true}}
""",
    )


def test_a_source_node_of_a_contributed_kind_and_a_reply_node_pass(tmp_path: Path) -> None:
    _source_example(tmp_path, "      kind: demo.feed\n      feed: the-feed\n      every: 30")

    assert check_pack_examples(CONTRIBUTION, tmp_path) == []


def test_a_source_node_is_checked_against_its_kind(tmp_path: Path) -> None:
    _source_example(tmp_path, "      kind: demo.feed\n      feed: the-feed\n      every: 0\n      stray: 1")

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 2
    assert all("step 'arrived' source" in issue for issue in issues)


def test_a_source_kind_the_pack_does_not_contribute_is_reported(tmp_path: Path) -> None:
    _source_example(tmp_path, "      kind: endpoint\n      path: /in")

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert issues == [
        "demo-feed.yaml: step 'arrived' names source kind 'endpoint', which this pack does not contribute"
    ]


def test_a_source_node_naming_a_connection_nothing_accounts_for_is_reported(tmp_path: Path) -> None:
    _source_example(tmp_path, "      kind: demo.feed\n      feed: the-feed", connections="")

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 1
    assert "'the-feed'" in issues[0] and "neither carries nor requires" in issues[0]


def test_every_field_a_block_publishes_as_a_connection_is_checked(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: The step names a connection in a field not called connection.
steps:
  hello:
    block: demo.greet
    config:
      name: ada
      reply_to: absent-conn
""",
    )

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 1
    assert "'absent-conn'" in issues[0]


def test_an_escaped_reference_is_a_literal_and_is_checked_as_one(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo-greet.yaml",
        """
format: dirigent/v1
kind: pipeline
code: demo-greet
description: An escaped reference is a literal value, not one left for the run.
steps:
  hello:
    block: demo.greet
    config:
      name: ada
      times: $${params.times}
""",
    )

    issues = check_pack_examples(CONTRIBUTION, tmp_path)

    assert len(issues) == 1
    assert "config.times" in issues[0]
