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

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response, Security, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from dirigent_core.auth import Principal, resolve_token
from dirigent_core.config import Settings
from dirigent_core.logging import redact_path
from dirigent_server.dependencies import SessionDep
from dirigent_server.errors import answer, render

SESSION_COOKIE = "dirigent_session"

BEARER_PREFIX = "Bearer "

#: Must not hint at which credential would have worked.
UNAUTHENTICATED = "authentication required: present a bearer token or log in"

#: One detail for both role refusals, saying neither which role would have sufficed nor what
#: any role may do: a refusal is not the place to teach the permission model.
FORBIDDEN = "not permitted for your role"

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

CROSS_SITE = (
    "this write was initiated by another site, and a session cookie may not be spent across "
    "origins; automation authenticating with a bearer token is unaffected"
)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UNAUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def require_operator(principal: Annotated[Principal, Security(require_principal)]) -> Principal:
    """Refuse a request from an account that may only read."""
    if not principal.may_operate:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN)
    return principal


async def require_admin(principal: Annotated[Principal, Security(require_principal)]) -> Principal:
    """Refuse a request from an account that may not manage accounts, tokens, or connections."""
    if not principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN)
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
            return answer(render(status.HTTP_403_FORBIDDEN, CROSS_SITE, instance=redact_path(request.url.path)))
        return await call_next(request)


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
