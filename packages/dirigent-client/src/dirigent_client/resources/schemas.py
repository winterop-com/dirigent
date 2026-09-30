"""Schemas: named JSON Schemas an instance holds, addressable by code and referenced by name."""

from dirigent_client.resources.base import CLEAR, Clear, Resource, edit_body, query, request_body
from dirigent_client.schemas import Page, SchemaIn, SchemaOut, SchemaUpdate
from dirigent_common import JsonMap


def declared_label(body: JsonMap, keyword: str) -> str | Clear:
    """One of a schema's own label keywords, or a clear where the schema declares none.

    Storing a schema reads ``title`` and ``description`` off the schema itself and editing one
    reads nothing, so a caller replacing a stored body sends the identity the new schema
    declares alongside it -- or the instance keeps labels belonging to a shape it no longer
    holds. An empty keyword is the absence of a label rather than a label, so it clears too.
    """
    said = body.get(keyword)
    if isinstance(said, str) and said.strip():
        return said.strip()
    return CLEAR


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
        name: str | Clear | None = None,
        description: str | Clear | None = None,
    ) -> SchemaOut:
        """Replace a schema's body or its labels; the code is fixed.

        An argument left out is a field the request says nothing about, so what the instance
        holds under it stays: a body stored on its own keeps the name and the description the
        schema was stored with. `CLEAR` in place of a label sends it as null, which removes
        the one that is stored.
        """
        sent = edit_body(SchemaUpdate, name=name, description=description, body=body)
        return await self._one(SchemaOut, "PATCH", f"/schemas/{code}", json=sent)

    async def delete(self, code: str) -> None:
        """Remove a schema."""
        await self._transport.request("DELETE", f"/schemas/{code}")
