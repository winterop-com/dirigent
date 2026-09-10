"""What this instance is, whether it is well, and which nodes are picking work up."""

from typing import Final

from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import Health, Page, Readiness, SystemInfo, WorkerOut

HTTP_SERVICE_UNAVAILABLE: Final = 503


class System(Resource):
    """Describe the instance, and read the two probes a load balancer reads."""

    async def info(self) -> SystemInfo:
        """Describe the instance, and repeat what each connection said when it was last checked."""
        return await self._one(SystemInfo, "GET", "/system/info")

    async def health(self) -> Health:
        """Ask whether the process is alive, without touching any dependency."""
        return await self._one(Health, "GET", "/health", prefixed=False)

    async def ready(self) -> Readiness:
        """Run every registered check and report the worst status.

        An unhealthy instance answers 503 with the same report, so a caller reads
        ``status`` rather than catching an exception.
        """
        return await self._one(Readiness, "GET", "/health/ready", prefixed=False, accept=(HTTP_SERVICE_UNAVAILABLE,))


class Workers(Resource):
    """Read the worker registry: who is alive, on what version, with which plugins."""

    async def list(self, *, after: str | None = None, limit: int | None = None) -> Page[WorkerOut]:
        """List the worker registry, flagging anything stale or running different code."""
        return await self._many(WorkerOut, "GET", "/workers", params=query(after=after, limit=limit))
