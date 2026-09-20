"""The generic HTTP connection kind, and the client one is turned into.

The configuration it registers is :class:`dirigent_common.HttpConnectionConfig`, so an adapter
pack presents the same HTTP connection as this one rather than redefining base URL, auth, TLS
and timeouts into a fourth slightly different form.
"""

from typing import ClassVar

import httpx2
from pydantic import BaseModel

from dirigent_common import HealthReport, HttpConnectionConfig, build_client
from dirigent_plugin import ConnectionKind


class HttpConnectionKind(ConnectionKind):
    """The connection kind every generic HTTP block resolves its credentials through."""

    id: ClassVar[str] = "http"
    config_model: ClassVar[type[BaseModel]] = HttpConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Request the health path and report whether the service answered."""
        settings = HttpConnectionConfig.model_validate(config.model_dump())
        try:
            async with build_client(settings) as client:
                response = await client.get(settings.health_path)
        except httpx2.HTTPError as error:
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        healthy = response.status_code < 500
        return HealthReport(
            healthy=healthy,
            detail=f"HTTP {response.status_code}",
            version=response.headers.get("server"),
        )
