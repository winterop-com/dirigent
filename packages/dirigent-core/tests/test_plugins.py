"""Tests for the plugin host: discovery, indexing, collisions, and the catalog."""

from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, SecretStr

from dirigent_common import API_VERSION, BlockModel, Duration, HealthReport, base_format_checker
from dirigent_core.config import Settings
from dirigent_core.engine.services import EngineServices
from dirigent_core.plugins import (
    BlockKind,
    DuplicateContribution,
    PluginHost,
    UnknownBlock,
    UnsupportedApiVersion,
    json_schema,
    load_plugin_host,
)
from dirigent_core.storage import FileStorageBackend
from dirigent_plugin import (
    AlertMessage,
    ConnectionKind,
    Contribution,
    Notifier,
    NotYet,
    Operator,
    OperatorSpec,
    RemoteHandle,
    Sensor,
    SensorSpec,
    StepContext,
    extension,
)


class EchoConfig(BlockModel):
    """What the echo operator is told."""

    value: str


class EchoOutput(BaseModel):
    """What the echo operator reports."""

    value: str


class EchoOperator(Operator[EchoConfig, EchoOutput]):
    """A synchronous operator with nothing to say for itself."""

    spec = OperatorSpec(id="test.echo", summary="Echo a value.", idempotent=True)
    config_model = EchoConfig
    output_model = EchoOutput

    async def execute(self, config: EchoConfig, ctx: StepContext) -> EchoOutput | RemoteHandle:
        """Return the configured value."""
        return EchoOutput(value=config.value)


class UnsafeOperator(Operator[EchoConfig, EchoOutput]):
    """An operator that declares it runs code on the worker."""

    spec = OperatorSpec(id="test.unsafe", summary="Run code locally.", local_execution=True)
    config_model = EchoConfig
    output_model = EchoOutput

    async def execute(self, config: EchoConfig, ctx: StepContext) -> EchoOutput | RemoteHandle:
        """Return the configured value."""
        return EchoOutput(value=config.value)


class WaitConfig(BaseModel):
    """What the wait sensor is told."""

    ready: bool = False


class WaitOutput(BaseModel):
    """What the wait sensor observed."""

    ready: bool


class WaitSensor(Sensor[WaitConfig, WaitOutput]):
    """A sensor with a custom cadence, so the catalog has something to publish."""

    spec = SensorSpec(
        id="test.wait",
        summary="Wait for readiness.",
        default_poll=timedelta(seconds=15),
        default_deadline=timedelta(minutes=30),
    )
    config_model = WaitConfig
    output_model = WaitOutput

    async def poke(self, config: WaitConfig, ctx: StepContext) -> WaitOutput | NotYet:
        """Observe once."""
        return WaitOutput(ready=True) if config.ready else NotYet()


class NoteConfig(BaseModel):
    """What the note notifier is told."""

    channel: str = "log"


class NoteNotifier(Notifier):
    """A notifier that drops everything."""

    id = "note"
    config_model = NoteConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Drop the message."""


class DeskConfig(BaseModel):
    """What the desk connection kind is told."""

    base_url: str = "http://localhost"


class DeskConnectionKind(ConnectionKind):
    """A connection kind that always reports health."""

    id = "desk"
    config_model = DeskConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Report healthy."""
        return HealthReport(healthy=True)


def _even_digits(value: object) -> bool:
    """A stand-in contributed format: a string of an even number of characters."""
    return isinstance(value, str) and len(value) % 2 == 0


class FullPlugin:
    """A plugin contributing something on every surface."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute one of each."""
        return Contribution(
            operators=[EchoOperator(), UnsafeOperator()],
            sensors=[WaitSensor()],
            storage_backends=[FileStorageBackend("./artifacts")],
            notifiers=[NoteNotifier()],
            connection_kinds=[DeskConnectionKind()],
            formats={"even-digits": _even_digits},
        )


class CollidingPlugin:
    """A second plugin claiming a block id the first one already has."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute a colliding block id."""
        return Contribution(operators=[EchoOperator()])


class SilentPlugin:
    """A plugin that implements nothing, which the host must tolerate."""


class RenamedPlugin:
    """A plugin whose implementation is named for itself and targets the hook."""

    @extension(target="contribute")
    def surfaces(self) -> Contribution:
        """Contribute one operator through a renamed implementation."""
        return Contribution(operators=[EchoOperator()])


class WrongTypePlugin:
    """A plugin whose implementation answers with something that is not a contribution."""

    @extension
    def contribute(self) -> object:
        """Answer with the wrong thing, which the host must ignore."""
        return {"operators": []}


@pytest.fixture
def host() -> PluginHost:
    """A host built from one plugin contributing on every surface."""
    return PluginHost({"full": FullPlugin().contribute()})


def test_the_host_indexes_every_surface(host: PluginHost) -> None:
    assert sorted(host.operators) == ["test.echo", "test.unsafe"]
    assert sorted(host.sensors) == ["test.wait"]
    assert sorted(host.storage_backends) == ["file"]
    assert sorted(host.notifiers) == ["note"]
    assert sorted(host.connection_kinds) == ["desk"]
    assert sorted(host.formats) == ["even-digits"]
    assert host.block_ids == ["test.echo", "test.unsafe", "test.wait"]


def test_a_block_id_resolves_to_the_instance_the_engine_calls(host: PluginHost) -> None:
    assert isinstance(host.block("test.echo"), EchoOperator)
    assert isinstance(host.block("test.wait"), WaitSensor)
    assert host.kind_of("test.echo") is BlockKind.OPERATOR
    assert host.kind_of("test.wait") is BlockKind.SENSOR


def test_an_unknown_block_names_itself(host: PluginHost) -> None:
    with pytest.raises(UnknownBlock, match="no block 'nope.missing' is installed"):
        host.block("nope.missing")
    with pytest.raises(UnknownBlock):
        host.kind_of("nope.missing")


def test_a_duplicate_block_id_names_both_plugins() -> None:
    with pytest.raises(DuplicateContribution) as raised:
        PluginHost({"first": FullPlugin().contribute(), "second": CollidingPlugin().contribute()})
    assert raised.value.identifier == "test.echo"
    assert raised.value.plugins == ("first", "second")
    assert "'first'" in str(raised.value)
    assert "'second'" in str(raised.value)


def test_a_duplicate_scheme_names_both_plugins() -> None:
    contribution = Contribution(storage_backends=[FileStorageBackend("./a")])
    with pytest.raises(DuplicateContribution, match="storage scheme 'file'"):
        PluginHost({"one": contribution, "two": Contribution(storage_backends=[FileStorageBackend("./b")])})


def test_a_duplicate_notifier_names_both_plugins() -> None:
    with pytest.raises(DuplicateContribution, match="notifier 'note'"):
        PluginHost({"one": Contribution(notifiers=[NoteNotifier()]), "two": Contribution(notifiers=[NoteNotifier()])})


def test_a_duplicate_connection_kind_names_both_plugins() -> None:
    contribution = Contribution(connection_kinds=[DeskConnectionKind()])
    with pytest.raises(DuplicateContribution, match="connection kind 'desk'"):
        PluginHost({"one": contribution, "two": Contribution(connection_kinds=[DeskConnectionKind()])})


def test_a_duplicate_format_names_both_plugins() -> None:
    with pytest.raises(DuplicateContribution, match="format 'even-digits'"):
        PluginHost(
            {
                "one": Contribution(formats={"even-digits": _even_digits}),
                "two": Contribution(formats={"even-digits": _even_digits}),
            }
        )


def test_the_services_assemble_one_checker_of_base_plus_contributed_formats(tmp_path: Path) -> None:
    """The host's formats become one instance checker the whole engine validates against."""
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )
    services = EngineServices.build(settings, PluginHost({"full": FullPlugin().contribute()}))
    checker = services.format_checker
    assert checker.conforms("abcd", "even-digits")  # the contributed format asserts
    assert not checker.conforms("abc", "even-digits")
    assert checker.conforms("01920000-0000-7000-8000-000000000000", "uuid7")  # a base format still asserts
    assert "even-digits" not in set(base_format_checker().checkers)  # the base was left untouched


def test_a_contribution_from_another_contract_revision_is_refused() -> None:
    future = Contribution.model_construct(api_version=API_VERSION + 1, operators=[EchoOperator()])
    with pytest.raises(UnsupportedApiVersion, match=f"this host speaks {API_VERSION}") as raised:
        PluginHost({"future": future})
    assert raised.value.plugin == "future"
    assert raised.value.api_version == API_VERSION + 1


def test_the_contract_itself_refuses_a_foreign_api_version() -> None:
    with pytest.raises(ValueError, match="unsupported api_version"):
        Contribution(api_version=API_VERSION + 1)


def test_the_catalog_publishes_schemas_and_provenance(host: PluginHost) -> None:
    catalog = host.catalog()
    assert catalog.api_version == API_VERSION
    assert catalog.plugins == ["full"]
    assert [entry.id for entry in catalog.blocks] == ["test.echo", "test.unsafe", "test.wait"]

    echo = catalog.block("test.echo")
    assert echo is not None
    assert echo.kind is BlockKind.OPERATOR
    assert echo.group == "test"
    assert echo.plugin == "full"
    assert echo.idempotent is True
    assert echo.local_execution is False
    assert echo.config_schema["properties"]["value"]["type"] == "string"
    assert echo.config_schema["additionalProperties"] is False, "a stray config key is refusable at apply"
    assert echo.output_schema["properties"]["value"]["type"] == "string"

    unsafe = catalog.block("test.unsafe")
    assert unsafe is not None
    assert unsafe.local_execution is True

    wait = catalog.block("test.wait")
    assert wait is not None
    assert wait.kind is BlockKind.SENSOR
    assert wait.default_poll_seconds == 15.0
    assert wait.default_deadline_seconds == 1800.0

    assert [entry.id for entry in catalog.storage_schemes] == ["file"]
    assert [entry.id for entry in catalog.notifiers] == ["note"]
    assert [entry.id for entry in catalog.connection_kinds] == ["desk"]
    assert catalog.connection_kinds[0].config_schema["properties"]["base_url"]["default"] == "http://localhost"


class RstDocstrings(BlockModel):
    """Exactly one of ``file`` or ``content``, never both."""

    file: str = ""
    """The compose file to read, relative to ``scratch``."""

    content: str = ""
    """Two literals: ``a`` and ``b``."""

    already: str = ""
    """A `code` span written as markdown, and an unpaired `` opener."""

    plain: str = ""
    """Nothing to convert here."""


def test_a_docstring_reaches_the_catalog_as_markdown() -> None:
    """Every description a docstring supplied is markdown by the time it leaves the host.

    A description is authored as a Python docstring, so it is written in reStructuredText, and
    every reader of the catalog -- the UI, `dg blocks show`, the generated reference -- renders
    markdown. The conversion is at this one boundary rather than three times downstream.
    """
    schema = json_schema(RstDocstrings)
    assert schema["description"] == "Exactly one of `file` or `content`, never both."
    properties = schema["properties"]
    assert properties["file"]["description"] == "The compose file to read, relative to `scratch`."
    assert properties["content"]["description"] == "Two literals: `a` and `b`."
    assert properties["already"]["description"] == "A `code` span written as markdown, and an unpaired `` opener."
    assert properties["plain"]["description"] == "Nothing to convert here."


class Budgeted(BlockModel):
    """A config with a duration in each shape a block writes one."""

    timeout: Duration = Field(default=timedelta(minutes=5), gt=timedelta(0))
    """How long the work may take."""

    grace: Duration = timedelta(seconds=10)
    """How long a stop is waited for."""


def test_a_duration_default_reaches_the_catalog_in_the_humane_spelling() -> None:
    """The published default is what a step may be written with, and a document writes ``5m``."""
    properties = json_schema(Budgeted)["properties"]
    assert properties["timeout"]["default"] == "5m"
    assert properties["grace"]["default"] == "10s"
    assert "gt" not in properties["timeout"], "JSON Schema has no keyword for a bound on a duration"
    assert json_schema(Budgeted)["$defs"]["Duration"]["format"] == "humane-duration"


class NestedDocstrings(BlockModel):
    """A model whose field is another model."""

    inner: RstDocstrings = RstDocstrings()
    """Carries a ``nested`` one."""


class LiteralSummaryOperator(Operator[EchoConfig, EchoOutput]):
    """An operator whose summary is written the way a docstring writes code."""

    spec = OperatorSpec(id="test.literal", summary="Echo a ``value`` and say so.")
    config_model = EchoConfig
    output_model = EchoOutput

    async def execute(self, config: EchoConfig, ctx: StepContext) -> EchoOutput | RemoteHandle:
        """Return the configured value."""
        return EchoOutput(value=config.value)


class LiteralSummarySensor(Sensor[WaitConfig, WaitOutput]):
    """A sensor whose summary is written the way a docstring writes code."""

    spec = SensorSpec(id="test.literal_wait", summary="Wait for ``ready`` to be true.")
    config_model = WaitConfig
    output_model = WaitOutput

    async def poke(self, config: WaitConfig, ctx: StepContext) -> WaitOutput | NotYet:
        """Observe once."""
        return WaitOutput(ready=True) if config.ready else NotYet()


def test_a_summary_reaches_the_catalog_as_markdown() -> None:
    """A summary crosses the same boundary a description does, and in the same spelling."""
    catalog = PluginHost(
        {
            "literal": Contribution(
                operators=[LiteralSummaryOperator()],
                sensors=[LiteralSummarySensor()],
            )
        }
    ).catalog()
    operator = catalog.block("test.literal")
    assert operator is not None
    assert operator.summary == "Echo a `value` and say so."
    sensor = catalog.block("test.literal_wait")
    assert sensor is not None
    assert sensor.summary == "Wait for `ready` to be true."


def test_the_conversion_reaches_a_description_nested_in_a_def() -> None:
    """A field's own model is published under `$defs`, and its docstrings are descriptions too."""
    schema = json_schema(NestedDocstrings)
    assert schema["properties"]["inner"]["description"] == "Carries a `nested` one."
    assert schema["$defs"]["RstDocstrings"]["description"] == "Exactly one of `file` or `content`, never both."


def test_the_catalog_digest_is_stable_and_content_addressed(host: PluginHost) -> None:
    assert host.catalog().digest == host.catalog().digest
    smaller = PluginHost({"full": Contribution(operators=[EchoOperator()])})
    assert smaller.catalog().digest != host.catalog().digest


def test_loading_attributes_each_contribution_to_the_name_it_was_registered_under() -> None:
    host = load_plugin_host(extra={"first": FullPlugin(), "quiet": SilentPlugin()})
    assert host.contributions["first"].block_ids() == ["test.echo", "test.unsafe", "test.wait"]
    assert "quiet" not in host.contributions
    assert host.owner_of("block id", "test.echo") == "first"


def test_loading_skips_a_plugin_answering_with_something_that_is_not_a_contribution() -> None:
    host = load_plugin_host(extra={"wrong": WrongTypePlugin()})
    assert "wrong" not in host.contributions


def test_loading_collects_a_renamed_implementation_of_the_hook() -> None:
    host = load_plugin_host(extra={"renamed": RenamedPlugin()})
    assert host.contributions["renamed"].block_ids() == ["test.echo"]


def test_loading_discovers_the_installed_pack_and_any_extra_plugin() -> None:
    host = load_plugin_host(extra={"tests": FullPlugin()})
    assert "builtin" in host.contributions
    assert "tests" in host.contributions
    assert "test.echo" in host.operators
