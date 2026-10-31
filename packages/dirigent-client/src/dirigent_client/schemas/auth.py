"""Who the caller is, the accounts an instance holds, and the tokens automation uses."""

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr

from dirigent_client.enums import TokenKind, UserRole
from dirigent_client.schemas.common import RequestModel, WireModel
from dirigent_common import Duration, Email, EntityName

#: How long a token may live: above zero and under a century, so its expiry is always a real date.
TokenLifetime = Annotated[Duration, Field(gt=timedelta(0), le=timedelta(days=36500))]


class LoginRequest(BaseModel):
    """What a login presents."""

    username: str = Field(min_length=1)
    password: SecretStr


class Identity(WireModel):
    """Who the caller is."""

    user_id: UUID
    username: str
    role: UserRole
    via: TokenKind | None = None
    token_name: str | None = None


class TokenOut(WireModel):
    """An API token as a listing shows it: everything except the secret."""

    id: UUID
    name: str
    username: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class TokenRequest(RequestModel):
    """What creating an API token asks for."""

    name: EntityName
    """What a person calls the token, and how it reads in an audit trail; two may share one.

    An entity name like every other named thing an instance holds."""

    expires_in: TokenLifetime | None = None
    """How long the token lives from now, such as ``90d``; unset, it lives until it is revoked."""


class IssuedTokenOut(WireModel):
    """A freshly minted token: the one and only time its secret is returned."""

    id: UUID
    name: str
    username: str
    prefix: str
    token: str
    """The secret. It is not stored and cannot be shown again."""

    expires_at: datetime | None = None
    """When the token stops resolving, or null for one that lives until it is revoked."""


class UserOut(WireModel):
    """An account as a listing shows it; the password hash is never rendered."""

    id: UUID
    username: str
    name: str | None = None
    email: str | None = None
    role: UserRole
    active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserIn(RequestModel):
    """What creating an account asks for."""

    username: str = Field(min_length=1, max_length=200)
    password: SecretStr
    name: str | None = None
    email: Email | None = None
    role: UserRole


class UserUpdate(RequestModel):
    """What editing an account may change; the username and the password are not among them.

    A field left out is left alone, and ``name`` or ``email`` sent as null is cleared. Those
    are different requests, so they are told apart by what the body contained rather than by
    the value landing as ``None`` either way. A role is never cleared, only replaced.
    """

    name: str | None = None
    email: Email | None = None
    role: UserRole | None = None

    def changing(self, field: str) -> bool:
        """Report whether the request said anything about this field at all."""
        return field in self.model_fields_set


class PasswordChangeRequest(BaseModel):
    """What a person changing their own password presents."""

    current_password: SecretStr
    new_password: SecretStr


class PasswordResetRequest(BaseModel):
    """What an admin resetting another account's password presents."""

    password: SecretStr
