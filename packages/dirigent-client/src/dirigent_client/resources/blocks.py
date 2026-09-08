"""The block catalog: what this instance can run, and the schemas a form is built from."""

from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import BlockEntry, BlockKind, Catalog


class Blocks(Resource):
    """Read the merged catalog every installed plugin contributes to."""

    async def catalog(self, *, kind: BlockKind | None = None) -> Catalog:
        """Read every contributed operator, sensor, storage scheme, notifier, and connection kind."""
        return await self._one(Catalog, "GET", "/blocks", params=query(kind=kind.value if kind else None))

    async def get(self, block_id: str) -> BlockEntry:
        """Read one catalog entry, which is what a step's configuration form is built from."""
        return await self._one(BlockEntry, "GET", f"/blocks/{block_id}")
