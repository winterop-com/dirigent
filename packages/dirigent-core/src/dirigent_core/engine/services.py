"""The services every engine path shares, gathered once per process."""

from functools import cached_property

from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import BlockKind
from dirigent_common import format_checker_with
from dirigent_core.config import Settings
from dirigent_core.engine.context import load_connections
from dirigent_core.engine.failure import Failure
from dirigent_core.messages import UNSAFE_BLOCK
from dirigent_core.plugins import PluginHost
from dirigent_core.secrets import SecretBox
from dirigent_core.storage import AttemptStorage, Storage, UnknownStorageConnection, build_storage, connection_binder
from dirigent_plugin import AnyOperator, AnySensor


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

    async def bound_storage(self, session: AsyncSession) -> AttemptStorage:
        """Return storage with every scheme configured from the connection this instance names for it.

        The configuration a step's context binds, for the paths that address artifacts outside
        a step. ``self.storage`` configures nothing: a scheme reached through it is opened with
        no endpoint and no credentials.

        The facade caches the credentials its binder opened, so it belongs to the call that
        asked for it, and a connection edited in the database is read by the next call.
        """
        records = await load_connections(session) if self.settings.storage_connections else {}

        def open_connection(scheme: str, ref: str, model: type[BaseModel]) -> BaseModel:
            record = records.get(ref)
            if record is None:
                raise UnknownStorageConnection(scheme, ref, records)
            return self.secrets.decrypt_config(model, record.config, record.envelope, key_id=record.key_id)

        return self.storage.bound_by(connection_binder(self.settings.storage_connections, open_connection))

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
        return Failure.rejected(UNSAFE_BLOCK, block=repr(block_id))
