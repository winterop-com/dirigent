"""The example corpus: every document the installed plugins ship, and its source."""

from collections.abc import Sequence

from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import ExampleDetail, ExampleOut, Page


class Examples(Resource):
    """Read the documents every installed plugin contributes, and the text of one."""

    async def list(
        self,
        *,
        tags: Sequence[str] = (),
        shelf: str | None = None,
        plugin: str | None = None,
        starter: bool | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> Page[ExampleOut]:
        """List the installed corpus, narrowed to the tags, shelf, plugin or starters named."""
        params = query(tag=list(tags) or None, shelf=shelf, plugin=plugin, starter=starter, after=after, limit=limit)
        return await self._many(ExampleOut, "GET", "/examples", params=params)

    async def get(self, code: str) -> ExampleDetail:
        """Read one example by its code, with the text a copy of it copies."""
        return await self._one(ExampleDetail, "GET", f"/examples/{code}")
