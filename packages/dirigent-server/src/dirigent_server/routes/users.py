"""Local accounts: the listing, creation, edits, activation, password resets, and their tokens."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import (
    IssuedTokenOut,
    Page,
    PasswordResetRequest,
    TokenOut,
    TokenRequest,
    UserIn,
    UserOut,
    UserUpdate,
)
from dirigent_core.auth import (
    DuplicateEmail,
    DuplicateUser,
    LastAdmin,
    WeakPassword,
    activate_user,
    create_user,
    deactivate_user,
    find_user,
    issue_token,
    list_tokens,
    list_users,
    reset_password,
    revoke_token,
    set_email,
    set_role,
)
from dirigent_core.models import User
from dirigent_server.dependencies import SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, uuid_cursor
from dirigent_server.security import AdminDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["users"])


def render(row: User) -> UserOut:
    """Render an account row for the API."""
    return UserOut.model_validate(row, from_attributes=True)


async def find(session: AsyncSession, username: str) -> User:
    """Read one account by name, or say this instance has no such account."""
    row = await find_user(session, username)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no user named {username!r}")
    return row


@router.get("/users", operation_id="listUsers", summary="List accounts", response_model=Page[UserOut])
async def list_accounts(
    session: SessionDep,
    principal: AdminDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[UserOut]:
    """List every account."""
    found = [render(row) for row in await list_users(session, after=after, limit=limit + 1)]
    items, following = clip(found, limit, lambda row: row.username)
    return Page(items=items, next=following)


@router.post(
    "/users",
    operation_id="createUser",
    summary="Create an account",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(payload: UserIn, session: SessionDep, principal: AdminDep) -> UserOut:
    """Create an account with an Argon2id password hash."""
    try:
        user = await create_user(
            session,
            payload.username,
            payload.password.get_secret_value(),
            role=payload.role,
            name=payload.name,
            email=payload.email,
        )
    except (DuplicateEmail, DuplicateUser) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except WeakPassword as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return render(user)


@router.patch("/users/{username}", operation_id="updateUser", summary="Update an account", response_model=UserOut)
async def update_account(
    username: str,
    payload: UserUpdate,
    session: SessionDep,
    principal: AdminDep,
) -> UserOut:
    """Change an account's display name, email or role; the username and the password are not editable."""
    row = await find(session, username)
    if payload.changing("name"):
        row.name = payload.name
    if payload.changing("email"):
        try:
            await set_email(session, row, payload.email)
        except DuplicateEmail as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if payload.role is not None:
        try:
            await set_role(session, row, payload.role)
        except LastAdmin as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await session.flush()
    return render(row)


@router.post(
    "/users/{username}/$deactivate",
    operation_id="deactivateUser",
    summary="Deactivate an account",
    response_model=UserOut,
)
async def deactivate_account(username: str, session: SessionDep, principal: AdminDep) -> UserOut:
    """Bar an account from logging in and revoke the sessions it already holds."""
    row = await find(session, username)
    try:
        await deactivate_user(session, row)
    except LastAdmin as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return render(row)


@router.post(
    "/users/{username}/$activate",
    operation_id="activateUser",
    summary="Activate an account",
    response_model=UserOut,
)
async def activate_account(username: str, session: SessionDep, principal: AdminDep) -> UserOut:
    """Let an account log in again; the sessions it lost are not restored."""
    return render(await activate_user(session, await find(session, username)))


@router.post(
    "/users/{username}/$reset-password",
    operation_id="resetPassword",
    summary="Reset an account's password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_account_password(
    username: str,
    payload: PasswordResetRequest,
    session: SessionDep,
    principal: AdminDep,
) -> Response:
    """Set an account's password without presenting the old one, ending every session it holds and no API token."""
    row = await find(session, username)
    try:
        await reset_password(session, row, payload.password.get_secret_value())
    except WeakPassword as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/users/{username}/tokens",
    operation_id="listUserTokens",
    summary="List an account's API tokens",
    response_model=Page[TokenOut],
)
async def list_account_tokens(
    username: str,
    session: SessionDep,
    principal: AdminDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[TokenOut]:
    """List the API tokens one account holds, without their secrets; sessions are not listed."""
    row = await find(session, username)
    rows = await list_tokens(session, user_id=row.id, after=uuid_cursor(after), limit=limit + 1)
    found = [TokenOut.model_validate(token, from_attributes=True) for token in rows]
    items, following = clip(found, limit, lambda token: token.id)
    return Page(items=items, next=following)


@router.post(
    "/users/{username}/tokens",
    operation_id="createUserToken",
    summary="Create an API token for an account",
    response_model=IssuedTokenOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_account_token(
    username: str,
    payload: TokenRequest,
    session: SessionDep,
    principal: AdminDep,
) -> IssuedTokenOut:
    """Mint a bearer token for another account and return its secret exactly once."""
    row = await find(session, username)
    issued = await issue_token(session, row, name=payload.name)
    return IssuedTokenOut(
        id=issued.id,
        name=issued.name,
        username=issued.username,
        prefix=issued.prefix,
        token=issued.secret.get_secret_value(),
    )


@router.delete(
    "/users/{username}/tokens/{name}",
    operation_id="revokeUserToken",
    summary="Revoke an account's API token",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_account_token(username: str, name: str, session: SessionDep, principal: AdminDep) -> Response:
    """Revoke that account's live tokens of the given name."""
    row = await find(session, username)
    if not await revoke_token(session, user_id=row.id, name=name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no live token named {name!r} for {username!r}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
