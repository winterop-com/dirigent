"""The services every engine path shares, gathered once per process."""

from functools import cached_property

from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict

from dirigent_client.schemas import BlockKind
from dirigent_common import format_checker_with
from dirigent_core.config import Settings
from dirigent_core.engine.failure import Failure
from dirigent_core.plugins import PluginHost
from dirigent_core.secrets import SecretBox
from dirigent_core.storage import Storage, build_storage
from dirigent_plugin import AnyOperator, AnySensor, ErrorClass


class EngineServices(BaseModel):
    """Everything the engine reaches outside the database."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, ignored_types=(cached_property,))

    settings: Settings
    host: PluginHost
    storage: Storage
    secrets: SecretBox

    @classmethod
    def build(cls, settings: Settings, host: PluginHost) -> "EngineServices":
        """Assemble the services from settings and an already-loaded plugin host."""
        key = settings.secret_key.get_secret_value() if settings.secret_key else None
        return cls(
            settings=settings,
            host=host,
            storage=build_storage(settings.artifact_root, host.storage_backends.values()),
            secrets=SecretBox(key),
        )

    @cached_property
    def connection_models(self) -> dict[str, type[BaseModel]]:
        """Index the contributed connection kinds by id."""
        return {name: connection.config_model for name, connection in self.host.connection_kinds.items()}

    @cached_property
    def format_checker(self) -> FormatChecker:
        """The one checker every instance validation asserts against: base plus contributed formats."""
        return format_checker_with(self.host.formats)

    def block(self, block_id: str) -> AnyOperator | AnySensor:
        """Resolve a block id to the instance the engine calls."""
        return self.host.block(block_id)

    def kind_of(self, block_id: str) -> BlockKind:
        """Report whether a block id names an operator or a sensor."""
        return self.host.kind_of(block_id)

    def local_execution_refusal(self, block_id: str) -> Failure | None:
        """Refuse a block that runs code on the worker unless the instance allowlists it.

        The gate is enforced on the execution path, so "can edit pipelines" never silently
        means "can run code on workers".
        """
        block = self.host.operators.get(block_id) or self.host.sensors.get(block_id)
        if block is None or not getattr(block.spec, "local_execution", False):
            return None
        if block_id in self.settings.enabled_unsafe_blocks:
            return None
        return Failure(
            message=(
                f"block {block_id!r} executes code on the worker and is disabled; "
                f"add it to DIRIGENT_ENABLED_UNSAFE_BLOCKS to allow it"
            ),
            error_class=ErrorClass.REJECTED,
        )
