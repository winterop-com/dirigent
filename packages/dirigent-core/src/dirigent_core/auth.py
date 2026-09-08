"""Accounts, passwords, and bearer credentials.

No secret is stored: passwords are Argon2id hashes and tokens are stored as a SHA-256 of the
presented value.
"""

import hashlib
import secrets as secrets_module
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import UUID

import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import TokenKind, TriggerKind, UserRole
from dirigent_core.logging import get_logger
from dirigent_core.models import ApiToken, User, utcnow

SESSION_LIFETIME = timedelta(days=14)

TOKEN_BYTES = 32

#: How much of a token is stored in the clear beside its hash.
PREFIX_LENGTH = 8

MIN_PASSWORD_LENGTH = 8

BOOTSTRAP_PASSWORD_ENV = "DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD"

DEFAULT_ADMIN = "admin"

#: Names the advisory lock every account change that could lock this instance out takes.
ACCOUNT_LOCK_KEY = 0x64_69_72_67_61_63_63_74

#: How stale a token's ``last_used_at`` may be before the next resolution rewrites it.
LAST_USED_RESOLUTION = timedelta(seconds=60)

_hasher = PasswordHasher()
_logger = get_logger("auth")


class AuthError(Exception):
    """Any refusal from the authentication layer."""


class WeakPassword(AuthError):
    """A password was too short to be worth hashing."""

    def __init__(self) -> None:
        """Build a message stating the minimum length."""
        super().__init__(f"a password must be at least {MIN_PASSWORD_LENGTH} characters")


class DuplicateUser(AuthError):
    """An account already holds the requested username."""

    def __init__(self, username: str) -> None:
        """Name the account already holding the username."""
        super().__init__(f"a user named {username!r} already exists")
        self.username = username


class DuplicateEmail(AuthError):
    """An account already holds the requested email address."""

    def __init__(self, email: str) -> None:
        """Name the address already taken."""
        super().__init__(f"a user with the email {email!r} already exists")
        self.email = email


class LastAdmin(AuthError):
    """A change would have left the instance with no active admin."""

    def __init__(self, username: str) -> None:
        """Name the account that would have been the last one able to manage this instance."""
        super().__init__(f"{username!r} is the only active admin; promote another account before changing this one")
        self.username = username


class WrongPassword(AuthError):
    """A self-service password change presented the wrong current password."""

    def __init__(self) -> None:
        """State what did not match, without naming the account."""
        super().__init__("the current password is not correct")


class Principal(BaseModel):
    """Who a request is acting as, and which credential said so."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    username: str
    role: UserRole
    token_id: UUID | None = None
    token_name: str | None = None
    via: TokenKind | None = None

    @property
    def is_admin(self) -> bool:
        """Report whether this principal may manage accounts and definitions."""
        return self.role is UserRole.ADMIN

    @property
    def may_operate(self) -> bool:
        """Report whether this principal may change anything: define, apply, run, and schedule."""
        return self.role in {UserRole.ADMIN, UserRole.OPERATOR}

    @property
    def label(self) -> str:
        """Render who this is for a log line or a run's attribution label."""
        if self.token_name and self.via is TokenKind.API:
            return f"{self.username} (token {self.token_name})"
        return self.username

    @property
    def trigger_kind(self) -> TriggerKind:
        """Say whether a run this principal starts was started by a person or by automation."""
        return TriggerKind.API_TOKEN if self.via is TokenKind.API else TriggerKind.USER


class IssuedToken(BaseModel):
    """A freshly minted credential, carrying the only copy of its secret."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    username: str
    kind: TokenKind
    secret: SecretStr
    prefix: str
    expires_at: datetime | None = None


class TokenRow(BaseModel):
    """An API token beside the account that holds it, as a listing renders it."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    username: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


def hash_password(password: str) -> str:
    """Hash a password with Argon2id, refusing one too short to be worth hashing."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against its stored hash, returning rather than raising on mismatch."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def mint_secret() -> str:
    """Generate an unguessable token; this value is never stored, only its hash."""
    return secrets_module.token_urlsafe(TOKEN_BYTES)


def hash_token(secret: str) -> str:
    """Hash a presented token the one way the lookup compares it.

    A plain SHA-256 rather than a password hash: the token carries full entropy, so there is
    nothing to brute-force.
    """
    return hashlib.sha256(secret.encode()).hexdigest()


async def find_user(session: AsyncSession, username: str) -> User | None:
    """Find an account by name."""
    found = await session.execute(sa.select(User).where(User.username == username))
    return found.scalar_one_or_none()


async def find_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Find an account by email address."""
    found = await session.execute(sa.select(User).where(User.email == email))
    return found.scalar_one_or_none()


async def list_users(session: AsyncSession, *, after: str | None = None, limit: int | None = None) -> list[User]:
    """List accounts in name order."""
    statement = sa.select(User).order_by(User.username)
    if after is not None:
        statement = statement.where(User.username > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def count_users(session: AsyncSession) -> int:
    """Count accounts."""
    found = await session.execute(sa.select(sa.func.count()).select_from(User))
    return int(found.scalar_one())


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    role: UserRole,
    name: str | None = None,
    email: str | None = None,
) -> User:
    """Create an account, refusing a duplicate name or address before hashing anything."""
    if await find_user(session, username) is not None:
        raise DuplicateUser(username)
    if email is not None and await find_user_by_email(session, email) is not None:
        raise DuplicateEmail(email)
    user = User(
        username=username,
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    await session.flush()
    _logger.info("user created", username=username, role=role.value)
    return user


async def reset_password(session: AsyncSession, user: User, password: str) -> User:
    """Replace an account's password without its old one, ending every session it holds and no API token."""
    user.password_hash = hash_password(password)
    await revoke_sessions(session, user.id)
    await session.flush()
    _logger.info("password reset", username=user.username)
    return user


async def set_email(session: AsyncSession, user: User, email: str | None) -> User:
    """Set or clear an account's email address, refusing one another account already holds."""
    if email is not None:
        existing = await find_user_by_email(session, email)
        if existing is not None and existing.id != user.id:
            raise DuplicateEmail(email)
    user.email = email
    await session.flush()
    return user


async def count_active_admins(session: AsyncSession, *, excluding: UUID | None = None) -> int:
    """Count the accounts that can still manage this instance, optionally ignoring one row."""
    statement = sa.select(sa.func.count()).select_from(User).where(User.role == UserRole.ADMIN, User.active.is_(True))
    if excluding is not None:
        statement = statement.where(User.id != excluding)
    found = await session.execute(statement)
    return int(found.scalar_one())


async def lock_accounts(session: AsyncSession) -> None:
    """Serialise the account changes that are guarded against locking everyone out.

    The guard counts the other admins and then writes, and two of those running at once each
    see the other account as the one that keeps the instance manageable. The lock is held
    until the transaction ends. PostgreSQL only; SQLite serialises its writers itself.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(sa.select(sa.func.pg_advisory_xact_lock(ACCOUNT_LOCK_KEY)))


async def _refuse_lockout(session: AsyncSession, user: User) -> None:
    """Refuse a change to this row that would leave the instance with no active admin."""
    await lock_accounts(session)
    if user.role is not UserRole.ADMIN or not user.active:
        return
    if await count_active_admins(session, excluding=user.id) == 0:
        raise LastAdmin(user.username)


async def set_role(session: AsyncSession, user: User, role: UserRole) -> User:
    """Change what an account may do, refusing the change that locks everyone out."""
    if role is not UserRole.ADMIN:
        await _refuse_lockout(session, user)
    user.role = role
    await session.flush()
    _logger.info("user role changed", username=user.username, role=role.value)
    return user


async def revoke_sessions(session: AsyncSession, user_id: UUID, *, keep: UUID | None = None) -> int:
    """Revoke every live browser session of an account, reporting how many were ended."""
    statement = sa.select(ApiToken).where(
        ApiToken.user_id == user_id,
        ApiToken.kind == TokenKind.SESSION,
        ApiToken.revoked_at.is_(None),
    )
    if keep is not None:
        statement = statement.where(ApiToken.id != keep)
    rows = await session.execute(statement)
    moment = utcnow()
    revoked = 0
    for row in rows.scalars():
        row.revoked_at = moment
        revoked += 1
    await session.flush()
    return revoked


async def deactivate_user(session: AsyncSession, user: User) -> User:
    """Bar an account from logging in and end the sessions it already holds.

    The flag and the revocations land in one flush, so no window exists in which the account
    is barred from logging in while a session it already had still resolves.
    """
    await _refuse_lockout(session, user)
    user.active = False
    await revoke_sessions(session, user.id)
    _logger.info("user deactivated", username=user.username)
    return user


async def activate_user(session: AsyncSession, user: User) -> User:
    """Let an account log in again; the sessions it lost are not restored."""
    user.active = True
    await session.flush()
    _logger.info("user activated", username=user.username)
    return user


async def change_password(
    session: AsyncSession,
    user: User,
    current: str,
    new: str,
    *,
    keep: UUID | None = None,
) -> User:
    """Replace an account's own password, ending every session it holds except ``keep``.

    Verifying the current password here is what makes this self-service rather than a reset:
    holding the credential is not enough, the person has to know the password it stands for.
    """
    if not verify_password(user.password_hash, current):
        raise WrongPassword
    user.password_hash = hash_password(new)
    await revoke_sessions(session, user.id, keep=keep)
    _logger.info("password changed", username=user.username)
    return user


@lru_cache(maxsize=1)
def absent_password_hash() -> str:
    """A real Argon2id hash of a value nothing can present, verified against on a miss.

    The point is the *time*, not the result. Short-circuiting on a missing account would let
    a login against an unknown username return in well under a millisecond while a real one
    takes the ~28ms Argon2id costs, answering "does this account exist?" to anyone with a
    stopwatch -- exactly what the identical error message is there to prevent. Hashing a
    random secret costs one call, once per process.
    """
    return _hasher.hash(secrets_module.token_urlsafe(TOKEN_BYTES))


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    """Verify a username and password, returning the account or nothing at all.

    A missing account and a wrong password are the same answer on purpose, so the endpoint
    above cannot become a way to enumerate who exists -- and they take the same time, which
    is the half that a short-circuit would give away.
    """
    user = await find_user(session, username)
    if user is None or not user.active:
        verify_password(absent_password_hash(), password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    user.last_login_at = utcnow()
    await session.flush()
    return user


async def issue_token(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    kind: TokenKind = TokenKind.API,
    lifetime: timedelta | None = None,
) -> IssuedToken:
    """Mint a credential for an account and store only its hash."""
    secret = mint_secret()
    expires_at = utcnow() + lifetime if lifetime else None
    row = ApiToken(
        user_id=user.id,
        name=name,
        kind=kind,
        token_hash=hash_token(secret),
        prefix=secret[:PREFIX_LENGTH],
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    _logger.info("token issued", username=user.username, name=name, kind=kind.value)
    return IssuedToken(
        id=row.id,
        name=name,
        username=user.username,
        kind=kind,
        secret=SecretStr(secret),
        prefix=row.prefix,
        expires_at=expires_at,
    )


def _should_record_use(token: ApiToken, moment: datetime) -> bool:
    """Say whether this resolution is the one that writes ``last_used_at``."""
    if token.last_used_at is None:
        return True
    return moment - token.last_used_at >= LAST_USED_RESOLUTION


async def resolve_token(session: AsyncSession, secret: str, *, now: datetime | None = None) -> Principal | None:
    """Turn a presented secret into the principal it authenticates, or nothing."""
    moment = now or utcnow()
    found = await session.execute(sa.select(ApiToken).where(ApiToken.token_hash == hash_token(secret)))
    token = found.scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None
    user = await session.get(User, token.user_id)
    if user is None or not user.active:
        return None
    if token.expires_at is not None and token.expires_at <= moment:
        return None
    if _should_record_use(token, moment):
        token.last_used_at = moment
    return Principal(
        user_id=user.id,
        username=user.username,
        role=user.role,
        token_id=token.id,
        token_name=token.name,
        via=token.kind,
    )


async def list_tokens(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
    after: UUID | None = None,
    limit: int | None = None,
) -> list[TokenRow]:
    """List API tokens beside the account that holds each, in id order, which is oldest first."""
    statement = (
        sa.select(ApiToken, User.username)
        .join(User, User.id == ApiToken.user_id)
        .where(ApiToken.kind == TokenKind.API)
        .order_by(ApiToken.id)
    )
    if user_id is not None:
        statement = statement.where(ApiToken.user_id == user_id)
    if after is not None:
        statement = statement.where(ApiToken.id > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return [
        TokenRow(
            id=token.id,
            username=username,
            name=token.name,
            prefix=token.prefix,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
            expires_at=token.expires_at,
            revoked_at=token.revoked_at,
        )
        for token, username in rows
    ]


async def revoke_token(session: AsyncSession, *, user_id: UUID, name: str) -> bool:
    """Revoke one account's live tokens of a given name, reporting whether anything was revoked.

    A name is unique only within an account, so the owner is part of what is revoked.
    """
    statement = sa.select(ApiToken).where(
        ApiToken.revoked_at.is_(None),
        ApiToken.user_id == user_id,
        ApiToken.name == name,
    )
    rows = await session.execute(statement)
    revoked = 0
    for token in rows.scalars():
        token.revoked_at = utcnow()
        revoked += 1
    await session.flush()
    return revoked > 0


async def revoke_session(session: AsyncSession, secret: str) -> None:
    """Revoke the session a cookie carries."""
    found = await session.execute(sa.select(ApiToken).where(ApiToken.token_hash == hash_token(secret)))
    row = found.scalar_one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()


async def bootstrap_admin(session: AsyncSession, password: str, *, username: str = DEFAULT_ADMIN) -> User | None:
    """Create the first admin if this instance has none.

    Returns None when accounts already exist, so setting the environment variable on every
    deploy cannot reset the password of a live instance.
    """
    if await count_users(session) > 0:
        return None
    return await create_user(session, username, password, role=UserRole.ADMIN, name="Bootstrap admin")
