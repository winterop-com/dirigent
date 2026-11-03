"""The generic HTTP connection kind, and the client one is turned into.

The configuration it registers is :class:`dirigent_common.HttpConnectionConfig`, so an adapter
pack presents the same HTTP connection as this one rather than redefining base URL, auth, TLS
and timeouts into a fourth slightly different form.
"""

from typing import ClassVar

import httpx2
from pydantic import BaseModel

from dirigent_common import CredentialForm, HealthReport, HttpConnectionConfig, build_client, raised_detail, secrets_of
from dirigent_plugin import ConnectionKind


class HttpConnectionKind(ConnectionKind):
    """The connection kind every generic HTTP block resolves its credentials through."""

    id: ClassVar[str] = "http"
    config_model: ClassVar[type[BaseModel]] = HttpConnectionConfig
    credential_forms: ClassVar[tuple[CredentialForm, ...]] = (
        CredentialForm(code="bearer", name="Bearer token", fields=("bearer_token",)),
        CredentialForm(code="basic", name="Basic username and password", fields=("basic_username", "basic_password")),
        CredentialForm(code="credential", name="A credential in a header or query parameter", fields=("credential",)),
    )

    async def check(self, config: BaseModel) -> HealthReport:
        """Request the health path: healthy on a 2xx or a 3xx, and unhealthy on anything else, saying why."""
        settings = HttpConnectionConfig.model_validate(config.model_dump())
        secrets = secrets_of(settings)
        try:
            async with build_client(settings) as client:
                response = await client.get(settings.health_path)
        except httpx2.HTTPError as error:
            return HealthReport(healthy=False, detail=raised_detail(error, redact=secrets))
        return HealthReport(
            healthy=response.status_code < CLIENT_ERROR,
            detail=answered(response.status_code, settings.health_path, credentialed=bool(secrets)),
            version=response.headers.get("server"),
        )


#: The first status that is not an answer a reachable, correctly addressed service gives.
CLIENT_ERROR = 400

#: The statuses that mean a credential was wanted, or presented and refused.
CREDENTIAL_REFUSED = frozenset({401, 403})


def answered(status: int, path: str, *, credentialed: bool) -> str:
    """Say what the health path answered, and for a refusal what it most likely means."""
    said = f"HTTP {status} at {path}"
    if status in CREDENTIAL_REFUSED:
        if credentialed:
            return f"{said}: the service refused the credential this connection holds"
        return f"{said}: the service wants a credential, and this connection holds none"
    if CLIENT_ERROR <= status < 500:  # noqa: PLR2004
        return f"{said}: the service is reachable, and this is not an address it answers; set health_path to one"
    return said
