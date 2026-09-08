"""Turning a connection's configuration into the client that talks to it.

This lives beside the configuration rather than in the standard library of blocks, so an
adapter pack can use the shared HTTP connection without depending on that library.
"""

import httpx2

from dirigent_common.schemas import HttpConnectionConfig


def build_client(config: HttpConnectionConfig) -> httpx2.AsyncClient:
    """Build a client carrying a connection's base URL, auth, TLS setting, and timeout."""
    headers: dict[str, str] = {}
    if config.bearer_token is not None:
        headers["Authorization"] = f"Bearer {config.bearer_token.get_secret_value()}"
    auth: httpx2.Auth | None = None
    if config.basic_username:
        password = config.basic_password.get_secret_value() if config.basic_password else ""
        auth = httpx2.BasicAuth(config.basic_username, password)
    return httpx2.AsyncClient(
        base_url=config.base_url,
        headers=headers,
        auth=auth,
        verify=config.verify_tls,
        timeout=config.timeout.total_seconds(),
    )
