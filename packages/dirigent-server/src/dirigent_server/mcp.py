"""MCP over Streamable HTTP at ``/mcp``, authenticated as the API is and calling the API as its caller.

A request presents an API token as a bearer token; the session cookie is never read here. Each
tool is a request to this application's own API, made in process with that token, so the routes
the API already has decide what the caller's role may do.
"""

from contextlib import AbstractAsyncContextManager, nullcontext

import httpx2
from fastapi import FastAPI, status
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from dirigent_client import Dirigent
from dirigent_core.auth import resolve_token
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_mcp.http import MCP_PATH, METHODS, Caller, McpEndpoint
from dirigent_mcp.server import Offers
from dirigent_server.errors import answer, render
from dirigent_server.messages import MCP_CROSS_ORIGIN, UNAUTHENTICATED
from dirigent_server.security import initiated_elsewhere


def install_mcp(app: FastAPI, settings: Settings) -> None:
    """Mount ``/mcp`` when the instance serves it. Registered before the UI shell, which would otherwise claim it."""
    if not settings.mcp_enabled:
        return

    async def authenticate(secret: str) -> Caller | None:
        async with session_scope(app.state.session_factory) as session:
            principal = await resolve_token(session, secret)
        if principal is None:
            return None
        offers = (
            Offers.ADMINISTERING
            if principal.is_admin
            else Offers.OPERATING
            if principal.may_operate
            else Offers.READING
        )
        return Caller(key=str(principal.token_id), offers=offers)

    def open_client(secret: str, request: Request) -> Dirigent:
        return Dirigent(
            url=f"{request.url.scheme}://{request.url.netloc}",
            token=secret,
            http_transport=httpx2.ASGITransport(app),
            api_prefix=settings.api_prefix,
        )

    endpoint = McpEndpoint(
        authenticate=authenticate,
        open_client=open_client,
        unauthenticated=_unauthenticated,
        cross_origin=_cross_origin,
        initiated_elsewhere=initiated_elsewhere,
        max_body=settings.mcp_max_body,
        session_idle=settings.mcp_session_idle,
        max_sessions=settings.mcp_max_sessions,
    )
    app.state.mcp = endpoint
    app.router.routes.append(Route(MCP_PATH, endpoint, methods=list(METHODS), include_in_schema=False))


def mcp_running(app: FastAPI) -> AbstractAsyncContextManager[None]:
    """Serve MCP sessions for as long as the application runs, when ``/mcp`` is mounted."""
    endpoint: McpEndpoint | None = getattr(app.state, "mcp", None)
    return endpoint.run() if endpoint is not None else nullcontext()


def _unauthenticated(request: Request) -> Response:
    """Answer a request with no bearer token, or one that does not resolve, as the API does."""
    problem = render(
        status.HTTP_401_UNAUTHORIZED, UNAUTHENTICATED.render(), code=UNAUTHENTICATED.code, instance=request.url.path
    )
    response = answer(problem)
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


def _cross_origin(request: Request) -> Response:
    """Answer a request a page on another origin caused."""
    problem = render(
        status.HTTP_403_FORBIDDEN, MCP_CROSS_ORIGIN.render(), code=MCP_CROSS_ORIGIN.code, instance=request.url.path
    )
    return answer(problem)
