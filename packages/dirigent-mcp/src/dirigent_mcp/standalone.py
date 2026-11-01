"""A standalone MCP server over Streamable HTTP, in front of a remote instance.

Each request presents the caller's own API token for the instance, which this server asks the
instance about and forwards on every call; it holds no token of its own. Bound to loopback, it
answers only to a loopback ``Host``.
"""

import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Final

from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from dirigent_client import Dirigent, Forbidden, Unauthorized, UserRole
from dirigent_common import Message
from dirigent_common.hosts import is_loopback_host
from dirigent_mcp.http import MCP_PATH, METHODS, Caller, McpEndpoint
from dirigent_mcp.messages import CROSS_ORIGIN, HOST_NOT_LOOPBACK, UNAUTHENTICATED

#: The roles whose tokens are offered the tools that write.
OPERATING_ROLES: Final = frozenset({UserRole.ADMIN, UserRole.OPERATOR})

SESSION_IDLE: Final = timedelta(minutes=30)
MAX_SESSIONS: Final = 256


def refusal(status: int, message: Message, headers: dict[str, str] | None = None, **params: str) -> Response:
    """Answer a refusal as one JSON record carrying its code and its sentence."""
    return JSONResponse(
        {"status": status, "code": message.code, "detail": message.render(**params), "params": params},
        status_code=status,
        headers=headers,
    )


def _host_name(authority: str) -> str:
    """The name or address a ``Host`` value names, without its port or brackets."""
    if authority.startswith("["):
        return authority[1:].partition("]")[0]
    return authority.rpartition(":")[0] if authority.count(":") == 1 else authority


class LoopbackHostsOnly:
    """Refuse a request whose ``Host`` is not a loopback name, so a page on a rebound name cannot reach it."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass one request through, or answer 421 without reading any of it."""
        hosts = Headers(scope=scope).getlist("host") if scope["type"] == "http" else []
        stranger = next((host for host in hosts if not is_loopback_host(_host_name(host.lower()))), None)
        if stranger is None:
            await self.app(scope, receive, send)
            return
        await refusal(421, HOST_NOT_LOOPBACK, host=stranger)(scope, receive, send)


def standalone_app(
    url: str,
    *,
    loopback: bool,
    read_only: bool = False,
    max_body: int = DEFAULT_MAX_REQUEST_BODY_SIZE,
    session_idle: timedelta = SESSION_IDLE,
    max_sessions: int = MAX_SESSIONS,
) -> ASGIApp:
    """Serve MCP at ``/mcp`` for the instance at ``url``, every call made with the caller's own token."""

    async def authenticate(secret: str) -> Caller | None:
        async with Dirigent(url=url, token=secret) as dg:
            try:
                identity = await dg.auth.whoami()
            except (Unauthorized, Forbidden):
                return None
        key = hashlib.sha256(secret.encode()).hexdigest()
        return Caller(key=key, may_operate=not read_only and identity.role in OPERATING_ROLES)

    endpoint = McpEndpoint(
        authenticate=authenticate,
        open_client=lambda secret: Dirigent(url=url, token=secret),
        unauthenticated=_unauthenticated,
        cross_origin=_cross_origin,
        max_body=max_body,
        session_idle=session_idle,
        max_sessions=max_sessions,
    )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None]:
        async with endpoint.run():
            yield

    app: ASGIApp = Starlette(routes=[Route(MCP_PATH, endpoint, methods=list(METHODS))], lifespan=lifespan)
    return LoopbackHostsOnly(app) if loopback else app


def _unauthenticated(request: Request) -> Response:
    """Answer a request whose bearer token the instance does not accept."""
    return refusal(401, UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"})


def _cross_origin(request: Request) -> Response:
    """Answer a request a page on another origin caused."""
    return refusal(403, CROSS_ORIGIN)
