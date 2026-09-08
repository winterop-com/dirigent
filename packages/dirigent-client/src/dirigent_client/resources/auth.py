"""Logging in, logging out, asking who you are, and the accounts and tokens an admin manages."""

from pydantic import SecretStr

from dirigent_client.enums import UserRole
from dirigent_client.resources.base import Resource, query, request_body
from dirigent_client.schemas import (
    Identity,
    IssuedTokenOut,
    LoginRequest,
    Page,
    PasswordChangeRequest,
    PasswordResetRequest,
    TokenOut,
    TokenRequest,
    UserIn,
    UserOut,
    UserUpdate,
)
from dirigent_client.transport import Transport


class Auth(Resource):
    """Exchange a password for a session, end one, and describe the caller."""

    #: What the instance names the session cookie it sets.
    SESSION_COOKIE = "dirigent_session"

    async def login(self, username: str, password: str) -> Identity:
        """Verify a username and password, and hold the session the instance answers with.

        The session is presented as a bearer token from here on, so the rest of this
        connection is authenticated whether or not a cookie could be sent back.
        """
        payload = LoginRequest(username=username, password=SecretStr(password))
        identity = await self._one(Identity, "POST", "/auth/login", json=request_body(payload))
        session = self._transport.session_cookie(self.SESSION_COOKIE)
        if session is not None:
            self._transport.present(session)
        return identity

    async def logout(self) -> None:
        """Revoke the presented session."""
        await self._transport.request("POST", "/auth/logout")

    async def whoami(self) -> Identity:
        """Report who this connection is acting as, and which credential said so."""
        return await self._one(Identity, "GET", "/auth/me")

    async def change_password(self, current: str, new: str) -> None:
        """Replace this account's own password, ending every other session it holds."""
        payload = PasswordChangeRequest(current_password=SecretStr(current), new_password=SecretStr(new))
        await self._transport.request("POST", "/auth/password", json=request_body(payload))


class Users(Resource):
    """The local accounts an instance holds."""

    async def list(self, *, after: str | None = None, limit: int | None = None) -> Page[UserOut]:
        """List every account."""
        return await self._many(UserOut, "GET", "/users", params=query(after=after, limit=limit))

    async def create(
        self,
        username: str,
        password: str,
        *,
        role: UserRole,
        name: str | None = None,
        email: str | None = None,
    ) -> UserOut:
        """Create an account with an Argon2id password hash."""
        declared = UserIn(
            username=username,
            password=SecretStr(password),
            role=role,
            name=name,
            email=email,
        )
        return await self._one(UserOut, "POST", "/users", json=request_body(declared))

    async def update(
        self,
        username: str,
        *,
        name: str | None = None,
        role: UserRole | None = None,
        email: str | None = None,
    ) -> UserOut:
        """Change an account's display name, email or role, leaving out whatever was not named.

        A field this call was not given is absent from the body, which is how the endpoint
        tells "leave it alone" from "clear it".
        """
        named: dict[str, object] = {}
        if name is not None:
            named["name"] = name
        if email is not None:
            named["email"] = email
        if role is not None:
            named["role"] = role
        body = UserUpdate.model_validate(named).model_dump(mode="json", exclude_unset=True)
        return await self._one(UserOut, "PATCH", f"/users/{username}", json=body)

    async def deactivate(self, username: str) -> UserOut:
        """Bar an account from logging in and revoke the sessions it already holds."""
        return await self._one(UserOut, "POST", f"/users/{username}/$deactivate")

    async def activate(self, username: str) -> UserOut:
        """Let an account log in again; the sessions it lost are not restored."""
        return await self._one(UserOut, "POST", f"/users/{username}/$activate")

    async def reset_password(self, username: str, password: str) -> None:
        """Set an account's password without its old one, ending every session it holds."""
        payload = PasswordResetRequest(password=SecretStr(password))
        await self._transport.request("POST", f"/users/{username}/$reset-password", json=request_body(payload))

    async def tokens(self, username: str, *, after: str | None = None, limit: int | None = None) -> Page[TokenOut]:
        """List the API tokens one account holds, without their secrets."""
        return await self._many(TokenOut, "GET", f"/users/{username}/tokens", params=query(after=after, limit=limit))

    async def create_token(self, username: str, name: str) -> IssuedTokenOut:
        """Mint a bearer token for another account; its secret is returned exactly once."""
        payload = TokenRequest(name=name)
        return await self._one(IssuedTokenOut, "POST", f"/users/{username}/tokens", json=request_body(payload))

    async def revoke_token(self, username: str, name: str) -> None:
        """Revoke that account's live tokens of the given name."""
        await self._transport.request("DELETE", f"/users/{username}/tokens/{name}")


class Tokens(Resource):
    """The bearer tokens automation authenticates with."""

    async def list(self, *, after: str | None = None, limit: int | None = None) -> Page[TokenOut]:
        """List every account's API tokens, without their secrets; sessions are not listed."""
        return await self._many(TokenOut, "GET", "/tokens", params=query(after=after, limit=limit))

    async def create(self, name: str) -> IssuedTokenOut:
        """Mint a bearer token for this account; its secret is returned exactly once."""
        payload = TokenRequest(name=name)
        return await self._one(IssuedTokenOut, "POST", "/tokens", json=request_body(payload))

    async def revoke(self, name: str) -> None:
        """Revoke this account's own live tokens of the given name."""
        await self._transport.request("DELETE", f"/tokens/{name}")


class Admin:
    """The account and token surfaces, which only an admin principal may call."""

    def __init__(self, transport: Transport) -> None:
        """Bind both admin surfaces to the instance their calls go to."""
        self.users = Users(transport)
        self.tokens = Tokens(transport)
