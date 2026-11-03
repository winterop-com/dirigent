"""The block catalog: what this instance can run, and the schemas a form is built from."""

from dirigent_client.resources.base import Resource, query, segment
from dirigent_client.schemas import BlockEntry, BlockKind, Catalog, ConnectionKindEntry
from dirigent_common import JsonMap


class Blocks(Resource):
    """Read the merged catalog every installed plugin contributes to."""

    async def catalog(self, *, kind: BlockKind | None = None) -> Catalog:
        """Read every contributed operator, sensor, storage scheme, notifier, and connection kind."""
        return await self._one(Catalog, "GET", "/blocks", params=query(kind=kind.value if kind else None))

    async def get(self, block_id: str) -> BlockEntry:
        """Read one catalog entry, which is what a step's configuration form is built from."""
        return await self._one(BlockEntry, "GET", f"/blocks/{segment(block_id)}")

    async def connection_kinds(self) -> list[ConnectionKindEntry]:
        """Read every installed connection kind with its fields, as a bare array: the kinds are few."""
        rows = await self._transport.json("GET", "/connection-kinds")
        return [ConnectionKindEntry.model_validate(row) for row in rows]

    async def connection_kind(self, kind_id: str) -> ConnectionKindEntry:
        """Read one connection kind's fields: which are secret, required, their defaults, its credential forms."""
        return await self._one(ConnectionKindEntry, "GET", f"/connection-kinds/{segment(kind_id)}")

    async def document_schema(self) -> JsonMap:
        """Read the JSON Schema a document is written against, with every installed block's config in it."""
        answered: JsonMap = await self._transport.json("GET", "/schema/document")
        return answered
