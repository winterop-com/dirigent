"""Logging in, logging out, and asking who you are."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from dirigent_client.enums import TokenKind
from dirigent_client.schemas import (
    Identity,
    IssuedTokenOut,
    LoginRequest,
    Page,
    PasswordChangeRequest,
    TokenOut,
    TokenRequest,
)
from dirigent_core.auth import (
    SESSION_LIFETIME,
    Principal,
    WeakPassword,
    WrongPassword,
    authenticate,
    change_password,
    issue_token,
    list_tokens,
    revoke_session,
    revoke_token,
)
from dirigent_core.auth import find_user as find_user_row
from dirigent_core.models import User
from dirigent_core.ratelimit import TokenBucket
from dirigent_server.dependencies import SessionDep, SettingsDep
from dirigent_server.logging import get_logger
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, uuid_cursor
from dirigent_server.security import (
    AdminDep,
    PrincipalDep,
    clear_session_cookie,
    presented_secret,
    set_session_cookie,
)
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["auth"])

_logger = get_logger("auth")

#: Mounted outside the principal dependency; login is the only unauthenticated route.
public_router = APIRouter(route_class=Transactional, tags=["auth"])


LOGIN_BUCKETS = TokenBucket()


@public_router.post(
    "/auth/login",
    operation_id="login",
    summary="Log in and receive a session cookie",
    response_model=Identity,
    responses={429: {"description": "Too many login attempts from this address or for this account."}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> Identity:
    """Verify a username and password, and set an http-only session cookie."""
    _limit_login(request, payload.username, per_minute=settings.login_rate_per_minute)
    user = await authenticate(session, payload.username, payload.password.get_secret_value())
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
    issued = await issue_token(session, user, name="session", kind=TokenKind.SESSION, lifetime=SESSION_LIFETIME)
    set_session_cookie(
        response,
        issued.secret.get_secret_value(),
        max_age=int(SESSION_LIFETIME.total_seconds()),
        secure=settings.environment != "local",
    )
    return Identity(user_id=user.id, username=user.username, role=user.role, via=TokenKind.SESSION)


def _limit_login(request: Request, username: str, *, per_minute: int) -> None:
    """Refuse a caller attempting logins faster than the instance is willing to hash.

    Login is unauthenticated and runs Argon2id, so an unlimited caller can spend the whole
    process's memory and CPU. Both keys have to pass: the address bound stops one machine
    from flooding the process, and the username bound stops a stuffing run spread across
    many addresses from concentrating on one account. Refusal must stay ahead of the hash.
    """
    address = request.client.host if request.client else "unknown"
    for scope, key in (("address", f"address:{address}"), ("account", f"user:{username}")):
        if not LOGIN_BUCKETS.allow(key, per_minute=per_minute):
            _logger.warning("login rate limited", scope=scope, address=address, limit=per_minute)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"too many login attempts; this instance accepts {per_minute} a minute",
                headers={"Retry-After": "60"},
            )


@router.post("/auth/logout", operation_id="logout", summary="Log out", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep, principal: PrincipalDep) -> Response:
    """Revoke the presented session and clear its cookie.

    The cookie is cleared on the response this returns. Clearing it on the injected one and
    returning another discards the header, because a route that returns a Response returns
    that Response and nothing is merged into it.
    """
    secret = presented_secret(request)
    if secret is not None and principal.via is TokenKind.SESSION:
        await revoke_session(session, secret)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.post(
    "/auth/password",
    operation_id="changePassword",
    summary="Change your own password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def change_own_password(
    payload: PasswordChangeRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> Response:
    """Replace the caller's own password, ending every other session the account holds.

    The credential this request arrived on survives, so the change does not log the person
    out of the page they made it from. An API token is not a session and is untouched.
    """
    user = await _require_user(session, principal.username)
    try:
        await change_password(
            session,
            user,
            payload.current_password.get_secret_value(),
            payload.new_password.get_secret_value(),
            keep=principal.token_id,
        )
    except WrongPassword as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except WeakPassword as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", operation_id="whoami", summary="Describe the authenticated caller", response_model=Identity)
async def whoami(principal: PrincipalDep) -> Identity:
    """Report who this request is acting as, and which credential said so."""
    return identity_of(principal)


def identity_of(principal: Principal) -> Identity:
    """Render a principal for the API, which never exposes the credential itself."""
    return Identity(
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
        via=principal.via,
        token_name=principal.token_name,
    )


@router.get("/tokens", operation_id="listTokens", summary="List API tokens", response_model=Page[TokenOut])
async def list_api_tokens(
    session: SessionDep,
    principal: AdminDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[TokenOut]:
    """List every API token, without its secret; sessions are not listed."""
    rows = await list_tokens(session, after=uuid_cursor(after), limit=limit + 1)
    found = [TokenOut.model_validate(token, from_attributes=True) for token in rows]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


@router.post(
    "/tokens",
    operation_id="createToken",
    summary="Create an API token",
    response_model=IssuedTokenOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_token(payload: TokenRequest, session: SessionDep, principal: AdminDep) -> IssuedTokenOut:
    """Mint a bearer token for automation and return its secret exactly once."""
    user = await _require_user(session, principal.username)
    issued = await issue_token(session, user, name=payload.name)
    return IssuedTokenOut(
        id=issued.id,
        name=issued.name,
        username=issued.username,
        prefix=issued.prefix,
        token=issued.secret.get_secret_value(),
    )


@router.delete(
    "/tokens/{name}",
    operation_id="revokeToken",
    summary="Revoke one of your own API tokens",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_token(name: str, session: SessionDep, principal: AdminDep) -> Response:
    """Revoke the caller's live tokens of the given name."""
    if not await revoke_token(session, user_id=principal.user_id, name=name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no live token named {name!r}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _require_user(session: SessionDep, username: str) -> User:
    """Read the account a principal names."""
    user = await find_user_row(session, username)
    if user is None:  # pragma: no cover - a resolved principal always has its row
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="the authenticated account is gone")
    return user
