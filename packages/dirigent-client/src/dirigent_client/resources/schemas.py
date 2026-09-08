"""Schemas: named JSON Schemas an instance holds, addressable by code and referenced by name."""

from dirigent_client.resources.base import Resource, query, request_body
from dirigent_client.schemas import Page, SchemaIn, SchemaOut, SchemaUpdate
from dirigent_common import JsonMap


class Schemas(Resource):
    """Create, read, edit, and remove the JSON Schemas an instance holds."""

    async def list(self, *, after: str | None = None, limit: int | None = None) -> Page[SchemaOut]:
        """List every stored schema."""
        return await self._many(SchemaOut, "GET", "/schemas", params=query(after=after, limit=limit))

    async def get(self, code: str) -> SchemaOut:
        """Read one schema by its code."""
        return await self._one(SchemaOut, "GET", f"/schemas/{code}")

    async def create(
        self,
        body: JsonMap,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> SchemaOut:
        """Store a JSON Schema, taking its identity from its own keywords when none is given."""
        payload = SchemaIn(code=code, name=name, description=description, body=body)
        return await self._one(SchemaOut, "POST", "/schemas", json=request_body(payload))

    async def update(
        self,
        code: str,
        *,
        body: JsonMap | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> SchemaOut:
        """Replace a schema's body or its labels; the code is fixed."""
        payload = SchemaUpdate(name=name, description=description, body=body)
        return await self._one(SchemaOut, "PATCH", f"/schemas/{code}", json=request_body(payload))

    async def delete(self, code: str) -> None:
        """Remove a schema."""
        await self._transport.request("DELETE", f"/schemas/{code}")
