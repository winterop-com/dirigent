"""The plugin host: discovery at startup, then direct dispatch forever after.

A block id is public API, referenced by stored pipelines as a string forever, so two packages
claiming the same one is a startup error rather than last-one-wins.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from pluginkit import PluginManager
from pydantic import BaseModel

from dirigent_client.schemas import BlockEntry, BlockKind, Catalog, SurfaceEntry
from dirigent_common import API_VERSION, HumaneJsonSchema, JsonMap, as_markdown
from dirigent_core.secrets import secret_fields
from dirigent_plugin import (
    ENTRY_POINT_GROUP,
    PROJECT_NAME,
    AnyOperator,
    AnySensor,
    ConnectionKind,
    Contribution,
    FormatCheck,
    Notifier,
    StorageBackend,
    markers,
)
from dirigent_plugin.markers import contribute


class PluginError(Exception):
    """A plugin made the host unable to start."""


class UnsupportedApiVersion(PluginError):
    """A plugin was written against a different revision of the block contract."""

    def __init__(self, plugin: str, api_version: int) -> None:
        """Name the plugin and both API versions."""
        super().__init__(
            f"plugin {plugin!r} contributes api_version {api_version}; this host speaks {API_VERSION}. "
            f"Upgrade the plugin, or the host, so both agree."
        )
        self.plugin = plugin
        self.api_version = api_version


class DuplicateContribution(PluginError):
    """Two plugins claimed the same public identifier."""

    def __init__(self, surface: str, identifier: str, first: str, second: str) -> None:
        """Name the identifier and both plugins."""
        super().__init__(
            f"{surface} {identifier!r} is contributed by both {first!r} and {second!r}. "
            f"{surface.capitalize()}s are public API, so one of the two packages must be uninstalled or renamed."
        )
        self.surface = surface
        self.identifier = identifier
        self.plugins = (first, second)


class UnknownBlock(PluginError):
    """A stored pipeline referenced a block no installed plugin contributes."""

    def __init__(self, block_id: str, known: Iterable[str]) -> None:
        """Name the block and the size of the catalog."""
        super().__init__(
            f"no block {block_id!r} is installed; the catalog has {len(list(known))} blocks. "
            f"Install the plugin package that contributes it."
        )
        self.block_id = block_id


def _described_in_markdown(node: Any) -> Any:
    """Walk a schema, reading every description the way the readers of it render one."""
    if isinstance(node, dict):
        return {
            key: as_markdown(value)
            if key == "description" and isinstance(value, str)
            else _described_in_markdown(value)
            for key, value in cast("dict[str, Any]", node).items()
        }
    if isinstance(node, list):
        return [_described_in_markdown(item) for item in cast("list[object]", node)]
    return node


def json_schema(model: type[BaseModel]) -> JsonMap:
    """Render a contributed Pydantic model as the JSON Schema the catalog publishes.

    A description arrives here from a docstring and leaves as markdown, because that is what
    every reader of the catalog renders: the UI's block panel and step form, `dg blocks show`,
    and the generated reference.
    """
    published = model.model_json_schema(mode="serialization", schema_generator=HumaneJsonSchema)
    return cast("JsonMap", _described_in_markdown(published))


class PluginHost:
    """The startup-built indexes every runtime call dispatches through."""

    def __init__(self, contributions: Mapping[str, Contribution]) -> None:
        """Build and validate the indexes, failing on any cross-plugin collision."""
        self.contributions = dict(contributions)
        self.operators: dict[str, AnyOperator] = {}
        self.sensors: dict[str, AnySensor] = {}
        self.storage_backends: dict[str, StorageBackend] = {}
        self.notifiers: dict[str, Notifier] = {}
        self.connection_kinds: dict[str, ConnectionKind] = {}
        self.formats: dict[str, FormatCheck] = {}
        self.origins: dict[str, str] = {}
        for plugin, contribution in self.contributions.items():
            self._index(plugin, contribution)

    def _index(self, plugin: str, contribution: Contribution) -> None:
        """Fold one plugin's contribution into the host's indexes."""
        if contribution.api_version != API_VERSION:
            raise UnsupportedApiVersion(plugin, contribution.api_version)
        for operator in contribution.operators:
            self._claim("block id", operator.spec.id, plugin)
            self.operators[operator.spec.id] = operator
        for sensor in contribution.sensors:
            self._claim("block id", sensor.spec.id, plugin)
            self.sensors[sensor.spec.id] = sensor
        for backend in contribution.storage_backends:
            self._claim("storage scheme", backend.scheme, plugin)
            self.storage_backends[backend.scheme] = backend
        for notifier in contribution.notifiers:
            self._claim("notifier", notifier.id, plugin)
            self.notifiers[notifier.id] = notifier
        for connection_kind in contribution.connection_kinds:
            self._claim("connection kind", connection_kind.id, plugin)
            self.connection_kinds[connection_kind.id] = connection_kind
        for format_name, check in contribution.formats.items():
            self._claim("format", format_name, plugin)
            self.formats[format_name] = check

    def _claim(self, surface: str, identifier: str, plugin: str) -> None:
        """Record who owns an identifier, refusing a second claimant."""
        key = f"{surface}:{identifier}"
        owner = self.origins.get(key)
        if owner is not None:
            raise DuplicateContribution(surface, identifier, owner, plugin)
        self.origins[key] = plugin

    def owner_of(self, surface: str, identifier: str) -> str:
        """Name the plugin that contributed an identifier."""
        return self.origins.get(f"{surface}:{identifier}", "unknown")

    @property
    def block_ids(self) -> list[str]:
        """List every operator and sensor id this host can run."""
        return sorted([*self.operators, *self.sensors])

    @property
    def blocks(self) -> dict[str, AnyOperator | AnySensor]:
        """Index every operator and sensor by id, which is what an apply-time check dispatches on."""
        return {**self.operators, **self.sensors}

    def block(self, block_id: str) -> AnyOperator | AnySensor:
        """Resolve a block id to the instance the engine calls."""
        found = self.operators.get(block_id) or self.sensors.get(block_id)
        if found is None:
            raise UnknownBlock(block_id, self.block_ids)
        return found

    def kind_of(self, block_id: str) -> BlockKind:
        """Report whether a block id names an operator or a sensor."""
        if block_id in self.operators:
            return BlockKind.OPERATOR
        if block_id in self.sensors:
            return BlockKind.SENSOR
        raise UnknownBlock(block_id, self.block_ids)

    def catalog(self) -> Catalog:
        """Build the served catalog: every contribution, with its published schemas."""
        blocks: list[BlockEntry] = []
        for block_id, operator in self.operators.items():
            blocks.append(
                BlockEntry(
                    id=block_id,
                    kind=BlockKind.OPERATOR,
                    summary=as_markdown(operator.spec.summary),
                    group=operator.spec.group,
                    plugin=self.owner_of("block id", block_id),
                    idempotent=operator.spec.idempotent,
                    local_execution=operator.spec.local_execution,
                    default_poll_seconds=(
                        operator.spec.default_poll.total_seconds() if operator.spec.default_poll else None
                    ),
                    config_schema=json_schema(operator.config_model),
                    output_schema=json_schema(operator.output_model),
                )
            )
        for block_id, sensor in self.sensors.items():
            blocks.append(
                BlockEntry(
                    id=block_id,
                    kind=BlockKind.SENSOR,
                    summary=as_markdown(sensor.spec.summary),
                    group=sensor.spec.group,
                    plugin=self.owner_of("block id", block_id),
                    default_poll_seconds=sensor.spec.default_poll.total_seconds(),
                    default_deadline_seconds=sensor.spec.default_deadline.total_seconds(),
                    config_schema=json_schema(sensor.config_model),
                    output_schema=json_schema(sensor.output_model),
                )
            )
        return Catalog(
            plugins=sorted(self.contributions),
            blocks=sorted(blocks, key=lambda entry: entry.id),
            storage_schemes=self._surfaces("storage scheme", self.storage_backends, lambda item: item.config_model),
            notifiers=self._surfaces("notifier", self.notifiers, lambda item: item.config_model),
            connection_kinds=self._surfaces("connection kind", self.connection_kinds, lambda item: item.config_model),
        )

    def _surfaces[T](
        self, surface: str, index: Mapping[str, T], config_model: Callable[[T], type[BaseModel]]
    ) -> list[SurfaceEntry]:
        """Render one non-block surface's index as catalog entries."""
        return [
            SurfaceEntry(
                id=identifier,
                plugin=self.owner_of(surface, identifier),
                config_schema=json_schema(config_model(item)),
                secret_fields=secret_fields(config_model(item)),
            )
            for identifier, item in sorted(index.items())
        ]


def load_plugin_host(
    *,
    group: str = ENTRY_POINT_GROUP,
    extra: Mapping[str, object] | None = None,
) -> PluginHost:
    """Discover installed plugins, call ``contribute()`` once each, and index the result.

    ``extra`` registers plugin objects that are not installed as distributions.
    """
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.load_entrypoints(group)
    for name, plugin in (extra or {}).items():
        manager.register(plugin, name=name)
    # The hook's return annotation is a declaration, not an enforcement: a plugin may answer
    # with anything, and anything that is not a Contribution is not indexed.
    collected = manager.caller(contribute).collect_with_plugins()
    return PluginHost(
        {
            name: value
            for name, value in collected
            if isinstance(value, Contribution)  # pyright: ignore[reportUnnecessaryIsInstance]
        }
    )
