"""Turning a connection's configuration into the client that talks to it.

This lives beside the configuration rather than in the standard library of blocks, so an
adapter pack can use the shared HTTP connection without depending on that library.
"""

from collections.abc import Callable
from typing import Any

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
    hooks: dict[str, list[Callable[..., Any]]] | None = (
        {"request": [BaseRedirect(config.base_url, verify=config.verify_tls)]}
        if config.follow_redirects_with_auth
        else None
    )
    return httpx2.AsyncClient(
        base_url=config.base_url,
        headers=headers,
        auth=auth,
        verify=config.verify_tls,
        timeout=config.timeout.total_seconds(),
        event_hooks=hooks,
    )


class BaseRedirect:
    """A request hook that sends every request under a base URL to where that base redirects.

    The base is resolved once, on the first request, by following its redirects without a
    credential. Each request is then rewritten onto the resolved base before it is sent, so its
    credential and its method reach the target rather than being dropped or turned into a GET
    by a redirect on the way.
    """

    def __init__(self, base_url: str, *, verify: bool) -> None:
        """Hold the configured base until the first request resolves it."""
        self._base = base_url.rstrip("/")
        self._verify = verify
        self._resolved: str | None = None

    async def __call__(self, request: httpx2.Request) -> None:
        """Rewrite a request under the configured base onto the resolved one."""
        url = str(request.url)
        if url != self._base and not url.startswith(f"{self._base}/"):
            return
        if self._resolved is None:
            self._resolved = await resolve_base(self._base, verify=self._verify)
        if self._resolved == self._base:
            return
        request.url = httpx2.URL(self._resolved + url[len(self._base) :])
        request.headers["Host"] = request.url.netloc.decode()


async def resolve_base(base_url: str, *, verify: bool) -> str:
    """Follow a base URL's redirects without a credential and answer where the base itself lands.

    The walk stops before a redirect that goes deeper under the base it has reached, on the same
    host: that one is the service sending an anonymous caller somewhere inside itself, such as
    its sign-in page, not the base moving. A base that does not answer is kept as it is.
    """
    base = base_url.rstrip("/")
    try:
        async with httpx2.AsyncClient(verify=verify, timeout=10.0, follow_redirects=True) as probe:
            response = await probe.get(f"{base}/")
    except httpx2.HTTPError:
        return base
    current = httpx2.URL(base)
    for hop in [*(earlier.url for earlier in response.history[1:]), response.url]:
        landed = httpx2.URL(str(hop).rstrip("/"))
        if landed.host == current.host and landed.path.startswith(f"{current.path.rstrip('/')}/"):
            break
        current = landed
    return str(current).rstrip("/")
