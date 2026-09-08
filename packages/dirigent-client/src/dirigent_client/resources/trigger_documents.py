"""Triggers documents: the clocks and webhooks one document declares for another's pipeline."""

from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import Page, TriggerDocumentDetail, TriggerDocumentOut


class TriggerDocuments(Resource):
    """Read and remove the ``kind: triggers`` documents this instance holds."""

    async def list(self, *, after: str | None = None, limit: int | None = None) -> Page[TriggerDocumentOut]:
        """List every triggers document, in code order."""
        return await self._many(TriggerDocumentOut, "GET", "/trigger-documents", params=query(after=after, limit=limit))

    async def get(self, code: str) -> TriggerDocumentDetail:
        """Read one triggers document, with the rows it owns."""
        return await self._one(TriggerDocumentDetail, "GET", f"/trigger-documents/{code}")

    async def delete(self, code: str) -> None:
        """Remove a triggers document and every schedule and webhook it owns."""
        await self._transport.request("DELETE", f"/trigger-documents/{code}")
