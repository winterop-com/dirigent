"""A pipeline's watches: the sensor each keeps a run waiting on, and how that is going."""

from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import Page, WatchOut


class Watches(Resource):
    """Read, pause, and resume the watches hanging from a pipeline."""

    async def list(self, pipeline: str, *, after: str | None = None, limit: int | None = None) -> Page[WatchOut]:
        """List every watch on a pipeline, with the run each one has waiting."""
        return await self._many(
            WatchOut,
            "GET",
            f"/pipelines/{pipeline}/triggers/watches",
            params=query(after=after, limit=limit),
        )

    async def get(self, pipeline: str, code: str) -> WatchOut:
        """Read one watch by code."""
        return await self._one(WatchOut, "GET", f"/pipelines/{pipeline}/triggers/watches/{code}")

    async def pause(self, pipeline: str, code: str) -> WatchOut:
        """Stop a watch, cancelling the run it has waiting, and keep where it left off."""
        return await self._one(WatchOut, "POST", f"/pipelines/{pipeline}/triggers/watches/{code}/$pause")

    async def resume(self, pipeline: str, code: str) -> WatchOut:
        """Start a watch again, arming a run from where its last success left off."""
        return await self._one(WatchOut, "POST", f"/pipelines/{pipeline}/triggers/watches/{code}/$resume")
