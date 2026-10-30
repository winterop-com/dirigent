"""Authentication and the three roles: a session cookie for the UI, a bearer token for automation.

Every route under the versioned API requires a principal. The only exemptions are the
health probes, the OpenAPI document and its viewers, and the login endpoint.

A viewer may read: every GET, the event streams, exports and reports, and whatever acts on
the caller's own credential. An operator may in addition define, apply, run, cancel, retry
and schedule. Anything that hands out authority -- accounts, API tokens, connections,
schemas -- and deleting a pipeline require admin.

The session cookie is an ambient credential: a browser attaches it to a request another
site's page caused. So a write that spends it has to say it came from this instance, which
is what the cross-site guard below requires. A bearer token is not ambient and is exempt.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Final

from fastapi import FastAPI, Request, Response, Security, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dirigent_common.hosts import is_loopback_host
from dirigent_core.auth import Principal, resolve_token
from dirigent_core.config import Settings
from dirigent_server.dependencies import SessionDep
from dirigent_server.errors import Refusal, answer, render
from dirigent_server.messages import (
    CROSS_SITE as CROSS_SITE_MESSAGE,
)
from dirigent_server.messages import (
    FORBIDDEN as FORBIDDEN_MESSAGE,
)
from dirigent_server.messages import (
    HOST_NOT_LOOPBACK,
)
from dirigent_server.messages import (
    UNAUTHENTICATED as UNAUTHENTICATED_MESSAGE,
)

SESSION_COOKIE = "dirigent_session"

BEARER_PREFIX = "Bearer "

#: Must not hint at which credential would have worked.
UNAUTHENTICATED = UNAUTHENTICATED_MESSAGE.render()

#: One detail for both role refusals, saying neither which role would have sufficed nor what
#: any role may do: a refusal is not the place to teach the permission model.
FORBIDDEN = FORBIDDEN_MESSAGE.render()

#: Declared so the schemes reach the OpenAPI document; without them every operation renders
#: as open and a generated client has no place to put a token. ``auto_error=False`` on both,
#: so that :func:`require_principal` remains the one place a request is refused.
bearer_scheme = HTTPBearer(
    scheme_name="bearerAuth",
    description="An API token from `dg admin token create`, presented as `Authorization: Bearer <token>`.",
    auto_error=False,
)
cookie_scheme = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="sessionCookie",
    description="The http-only session cookie `POST /auth/login` sets, which the UI uses.",
    auto_error=False,
)


#: Methods that change state, and so may not be caused by another site's page.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: What a browser reports for a request that no other site initiated: a same-origin fetch,
#: or a typed URL, bookmark or redirect, which is ``none``.
SAME_SITE_FETCH = frozenset({"same-origin", "none"})

#: Login is guarded although it carries no session yet: a cross-site login POST logs a
#: person into an account the attacker controls, and every later action is attributed there.
LOGIN_PATH = "/auth/login"

CROSS_SITE = CROSS_SITE_MESSAGE.render()


def presented_secret(request: Request) -> str | None:
    """Read the credential from the request: an Authorization header, or the session cookie."""
    header = request.headers.get("authorization")
    if header and header.startswith(BEARER_PREFIX):
        return header[len(BEARER_PREFIX) :].strip() or None
    return request.cookies.get(SESSION_COOKIE)


async def optional_principal(
    request: Request,
    session: SessionDep,
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    _cookie: Annotated[str | None, Security(cookie_scheme)] = None,
) -> Principal | None:
    """Resolve who is asking, or nothing when no usable credential was presented.

    The two unused scheme parameters are what put the security schemes in the OpenAPI
    document; the credential itself is read from the request.
    """
    secret = presented_secret(request)
    if secret is None:
        return None
    return await resolve_token(session, secret)


async def require_principal(principal: Annotated[Principal | None, Security(optional_principal)]) -> Principal:
    """Refuse a request that carries no valid credential."""
    if principal is None:
        raise Refusal(
            UNAUTHENTICATED_MESSAGE,
            status=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def require_operator(principal: Annotated[Principal, Security(require_principal)]) -> Principal:
    """Refuse a request from an account that may only read."""
    if not principal.may_operate:
        raise Refusal(FORBIDDEN_MESSAGE, status=status.HTTP_403_FORBIDDEN)
    return principal


async def require_admin(principal: Annotated[Principal, Security(require_principal)]) -> Principal:
    """Refuse a request from an account that may not manage accounts, tokens, or connections."""
    if not principal.is_admin:
        raise Refusal(FORBIDDEN_MESSAGE, status=status.HTTP_403_FORBIDDEN)
    return principal


def initiated_elsewhere(request: Request) -> bool:
    """Whether a browser says another site caused this request.

    Fetch metadata is the answer when the browser sends it; ``Origin`` is the fallback, and
    a request carrying neither is not from a browser at all.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in SAME_SITE_FETCH
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return origin.rstrip("/").lower() != f"{request.url.scheme}://{request.url.netloc}".lower()


def spends_the_cookie(request: Request, api_prefix: str) -> bool:
    """Whether this request is a write under the API that a session cookie would authenticate."""
    if request.method not in UNSAFE_METHODS or not request.url.path.startswith(api_prefix):
        return False
    if request.url.path == f"{api_prefix.rstrip('/')}{LOGIN_PATH}":
        return True
    header = request.headers.get("authorization")
    if header and header.startswith(BEARER_PREFIX):
        return False
    return SESSION_COOKIE in request.cookies


def install_cross_site_guard(app: FastAPI, settings: Settings) -> None:
    """Refuse a state-changing request that a cookie would authenticate and another site caused.

    Registered before the error handlers, so the version-header middleware they install wraps
    this refusal too.
    """
    prefix = settings.api_prefix

    @app.middleware("http")
    async def guard(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if spends_the_cookie(request, prefix) and initiated_elsewhere(request):
            return answer(
                render(
                    status.HTTP_403_FORBIDDEN,
                    CROSS_SITE,
                    code=CROSS_SITE_MESSAGE.code,
                    instance=request.url.path,
                )
            )
        return await call_next(request)


#: What the bundle needs: its own scripts and workers, Monaco's blob workers, and the inline
#: styles Monaco and the graph set on elements.
UI_POLICY: Final = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "worker-src 'self' blob:",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

#: What FastAPI's two API viewers load: the CDN's bundles and fonts, their own inline bootstrap,
#: and the blob worker ReDoc starts.
DOCS_POLICY: Final = "; ".join(
    (
        "default-src 'none'",
        "script-src https://cdn.jsdelivr.net 'unsafe-inline'",
        "worker-src blob:",
        "style-src https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'",
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)

#: The paths that serve those viewers.
DOCS_PATHS: Final = ("/docs", "/redoc")

#: Sent on every response. A route that set its own value keeps it.
DEFAULT_HEADERS: Final = (
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "same-origin"),
)


class SecurityHeaders:
    """Stamp every response this application sends with the default security headers."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass one request through, adding what its response did not set itself."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        policy = DOCS_POLICY if path.startswith(DOCS_PATHS) else UI_POLICY

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in DEFAULT_HEADERS:
                    headers.setdefault(name, value)
                headers.setdefault("content-security-policy", policy)
            await send(message)

        await self.app(scope, receive, stamped)


def install_security_headers(app: FastAPI) -> None:
    """Send the default security headers on every response, whichever layer answered it."""
    app.add_middleware(SecurityHeaders)


#: A ``Host`` value: a name or an address, or an address in brackets, then perhaps a port.
HOST_HEADER: Final = re.compile(r"(?:\[(?P<bracketed>[^\]]*)\]|(?P<name>[^:\[\]]*))(?::[0-9]*)?")


def _names_loopback(authority: str) -> bool:
    """Whether a ``Host`` value, with or without its port, is a loopback name or address."""
    parsed = HOST_HEADER.fullmatch(authority.lower())
    return parsed is not None and is_loopback_host(parsed["bracketed"] or parsed["name"] or "")


class LoopbackHostsOnly:
    """Refuse a request whose ``Host`` is not a loopback name.

    A page on a name that resolves to 127.0.0.1 is same-origin with itself, so a browser lets it
    read what this instance answers and send it the cookies this name earned. The ``Host`` it
    arrives with is that name.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass one request through, or answer 421 without reading any of it."""
        if scope["type"] != "http" or all(_names_loopback(host) for host in Headers(scope=scope).getlist("host")):
            await self.app(scope, receive, send)
            return
        problem = render(
            status.HTTP_421_MISDIRECTED_REQUEST,
            HOST_NOT_LOOPBACK.render(),
            code=HOST_NOT_LOOPBACK.code,
            instance=scope["path"],
        )
        await answer(problem)(scope, receive, send)


def install_loopback_hosts_only(app: FastAPI) -> None:
    """Keep a loopback bind to loopback names. Registered inside the security headers, which it answers under."""
    app.add_middleware(LoopbackHostsOnly)


def set_session_cookie(response: Response, secret: str, *, max_age: int, secure: bool) -> None:
    """Attach a session cookie that JavaScript cannot read and another site cannot send."""
    response.set_cookie(
        SESSION_COOKIE,
        secret,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie."""
    response.delete_cookie(SESSION_COOKIE, path="/")


PrincipalDep = Annotated[Principal, Security(require_principal)]
OperatorDep = Annotated[Principal, Security(require_operator)]
AdminDep = Annotated[Principal, Security(require_admin)]
