"""Connections: coded credential records of a contributed kind, redacted in every response."""

from dirigent_client.resources.base import Resource, query, request_body
from dirigent_client.schemas import ConnectionIn, ConnectionOut, ConnectionUpdate, Page
from dirigent_common import HealthReport, JsonMap


class Connections(Resource):
    """Create, read, edit, check, and remove the credential records an instance holds."""

    async def list(self, *, after: str | None = None, limit: int | None = None) -> Page[ConnectionOut]:
        """List every stored credential record, with its secrets redacted."""
        return await self._many(ConnectionOut, "GET", "/connections", params=query(after=after, limit=limit))

    async def get(self, code: str) -> ConnectionOut:
        """Read one credential record, with its secrets redacted."""
        return await self._one(ConnectionOut, "GET", f"/connections/{code}")

    async def create(
        self,
        code: str,
        *,
        kind: str,
        config: JsonMap | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> ConnectionOut:
        """Validate a credential against its kind, seal its secret half, and store it."""
        payload = ConnectionIn(code=code, name=name, kind=kind, description=description, config=config or {})
        return await self._one(ConnectionOut, "POST", "/connections", json=request_body(payload))

    async def update(
        self,
        code: str,
        *,
        config: JsonMap | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> ConnectionOut:
        """Replace a connection's settings; the config is sent whole, not merged field by field."""
        payload = ConnectionUpdate(name=name, description=description, config=config)
        return await self._one(ConnectionOut, "PATCH", f"/connections/{code}", json=request_body(payload))

    async def delete(self, code: str) -> None:
        """Remove a credential record."""
        await self._transport.request("DELETE", f"/connections/{code}")

    async def check(self, code: str) -> HealthReport:
        """Open the credential and ask its kind whether the external system answers."""
        return await self._one(HealthReport, "POST", f"/connections/{code}/$check")
