"""MCP over Streamable HTTP: every request authenticated as its caller, and every call made as them.

One endpoint serves two MCP servers built from the same tools: the whole set for a caller who may
operate, and the reading tools alone for one who may only read. A request is checked for the page
that caused it, then for its bearer token, before either server sees it, and a session answers
only the credential that opened it. A tool calls the instance with the bearer token of the request
it arrived on, never with one the server holds.
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Final

from mcp.server import MCPServer
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict
from starlette.authentication import AuthCredentials
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from dirigent_client import Dirigent
from dirigent_mcp.messages import NO_CREDENTIAL
from dirigent_mcp.server import ARRIVED_ON, Connect, build

#: Where the endpoint is served.
MCP_PATH: Final = "/mcp"

#: The methods Streamable HTTP uses: a message, the stream a client listens on, and a session's end.
METHODS: Final = ("GET", "POST", "DELETE")

BEARER_PREFIX: Final = "bearer "

#: What a browser reports for a request no other site caused.
SAME_SITE_FETCH: Final = frozenset({"same-origin", "none"})


class Caller(BaseModel):
    """Who presented a bearer token: the credential's own key, and whether its role may change anything."""

    model_config = ConfigDict(frozen=True)

    key: str
    may_operate: bool


#: Turns a presented bearer token into its caller, or nothing when it does not authenticate.
Authenticate = Callable[[str], Awaitable[Caller | None]]

#: Answers a request that is refused, given the request.
Refuse = Callable[[Request], Response]


def bearer(request: Request) -> str | None:
    """The bearer token a request presents in its ``Authorization`` header; a cookie is never read."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER_PREFIX):
        return None
    return header[len(BEARER_PREFIX) :].strip() or None


def foreign_origin(request: Request) -> bool:
    """Whether a browser says a page on another origin caused this request.

    Fetch metadata decides when the browser sends it; ``Origin`` otherwise has to be this request's
    own scheme, host and port. A request with neither is not from a browser.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in SAME_SITE_FETCH
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return origin.rstrip("/").lower() != f"{request.url.scheme}://{request.url.netloc}".lower()


def per_caller(open_client: Callable[[str], Dirigent]) -> Connect:
    """A client of each call's own, carrying the bearer token of the request the call arrived on."""

    @asynccontextmanager
    async def connect() -> AsyncGenerator[Dirigent]:
        request = ARRIVED_ON.get()
        secret = bearer(request) if request is not None else None
        if secret is None:
            raise ToolError(NO_CREDENTIAL.render())
        async with open_client(secret) as client:
            yield client

    return connect


class McpEndpoint:
    """The ASGI application that answers MCP at one path, for whoever each request authenticates as."""

    def __init__(
        self,
        *,
        authenticate: Authenticate,
        open_client: Callable[[str], Dirigent],
        unauthenticated: Refuse,
        cross_origin: Refuse,
        initiated_elsewhere: Callable[[Request], bool] = foreign_origin,
        max_body: int,
        session_idle: timedelta,
        max_sessions: int,
    ) -> None:
        """Hold how a caller is authenticated, how a call reaches the instance, and how a refusal is answered."""
        self._authenticate = authenticate
        self._connect = per_caller(open_client)
        self._unauthenticated = unauthenticated
        self._cross_origin = cross_origin
        self._initiated_elsewhere = initiated_elsewhere
        self._max_body = max_body
        self._session_idle = session_idle
        self._max_sessions = max_sessions
        self._operating: StreamableHTTPSessionManager | None = None
        self._reading: StreamableHTTPSessionManager | None = None

    def _manager(self, server: MCPServer) -> StreamableHTTPSessionManager:
        """Give a server its session manager, with the checks this endpoint makes itself left out of it."""
        server.streamable_http_app(
            max_request_body_size=self._max_body,
            session_idle_timeout=self._session_idle.total_seconds(),
            max_sessions=self._max_sessions,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        return server.session_manager

    @asynccontextmanager
    async def run(self) -> AsyncGenerator[None]:
        """Serve sessions while this is open, on a fresh pair of servers each time it is entered.

        The sessions live in a task of their own, so this may be entered in one task and left in another.
        """
        started = asyncio.Event()
        stopping = asyncio.Event()

        async def serve() -> None:
            operating = self._manager(build(self._connect))
            reading = self._manager(build(self._connect, read_only=True))
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(operating.run())
                await stack.enter_async_context(reading.run())
                self._operating, self._reading = operating, reading
                started.set()
                try:
                    await stopping.wait()
                finally:
                    self._operating = self._reading = None

        sessions = asyncio.create_task(serve())
        waiting = asyncio.create_task(started.wait())
        await asyncio.wait({sessions, waiting}, return_when=asyncio.FIRST_COMPLETED)
        if sessions.done():
            waiting.cancel()
            await sessions
        try:
            yield
        finally:
            stopping.set()
            await sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Refuse a request another origin caused or nobody authenticated, else hand it to its caller's server."""
        request = Request(scope)
        if self._initiated_elsewhere(request):
            await self._cross_origin(request)(scope, receive, send)
            return
        secret = bearer(request)
        caller = await self._authenticate(secret) if secret is not None else None
        if secret is None or caller is None:
            await self._unauthenticated(request)(scope, receive, send)
            return
        manager = self._operating if caller.may_operate else self._reading
        if manager is None:
            raise RuntimeError("the MCP endpoint is not running: enter McpEndpoint.run() first")
        user = AuthenticatedUser(AccessToken(token=secret, client_id=caller.key, scopes=[]))
        scope["user"], scope["auth"] = user, AuthCredentials([])
        await manager.handle_request(scope, receive, send)
