"""The audit trail: one journal row and one INFO log line per administrative change.

A change is recorded in the transaction that makes it, so a change that rolls back leaves no
row. Who made it is read from the session, where the API puts the request's principal, or
from the ambient actor a command running against the database names for itself; neither set
means the instance itself acted. An update names the fields it changed and never a value.
"""

from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AuditAction, AuditSubject
from dirigent_core.logging import get_logger
from dirigent_core.models import AuditEntry

#: Where the API puts the principal a request acts as, on the request's own session.
ACTOR_KEY: Final = "dirigent.actor"

_logger: Final = get_logger("audit")


class Actor(BaseModel):
    """Who made a change: an account, the token it acted through, or the host itself."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID | None = None
    username: str | None = None
    token: str | None = None
    token_prefix: str | None = None
    label: str


#: The instance acting on its own account, such as a directory applied at boot.
SYSTEM: Final = Actor(label="system")

_ambient: ContextVar[Actor | None] = ContextVar("dirigent_audit_actor", default=None)


def act_as(session: AsyncSession, actor: Actor) -> None:
    """Attribute every change this session records to an actor."""
    session.info[ACTOR_KEY] = actor


@contextmanager
def acting_as(actor: Actor) -> Generator[Actor]:
    """Attribute every change recorded in this context to an actor, whatever session records it."""
    token = _ambient.set(actor)
    try:
        yield actor
    finally:
        _ambient.reset(token)


def host(command: str) -> Actor:
    """The person at the host's shell, acting on the database directly through a command."""
    return Actor(label=command)


def actor_of(session: AsyncSession) -> Actor:
    """Who this session's changes are attributed to."""
    held = session.info.get(ACTOR_KEY)
    if isinstance(held, Actor):
        return held
    return _ambient.get() or SYSTEM


def changed(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    """Name the keys whose values differ between two mappings, in sorted order."""
    missing = object()
    return sorted(key for key in before.keys() | after.keys() if before.get(key, missing) != after.get(key, missing))


async def record(
    session: AsyncSession,
    action: AuditAction,
    subject_kind: AuditSubject,
    *,
    code: str | None,
    subject_id: UUID | None = None,
    parent: str | None = None,
    fields: Iterable[str] = (),
) -> AuditEntry:
    """Journal one change in the session's transaction and log it at INFO with the same fields."""
    actor = actor_of(session)
    names = sorted(set(fields))
    entry = AuditEntry(
        action=action,
        subject_kind=subject_kind,
        subject_id=subject_id,
        subject_code=code,
        parent_code=parent,
        fields=names,
        actor_id=actor.user_id,
        actor_username=actor.username,
        actor_token=actor.token,
        actor_token_prefix=actor.token_prefix,
        actor_label=actor.label,
    )
    session.add(entry)
    await session.flush()
    _logger.info(
        f"{subject_kind.value.replace('_', ' ')} {action.value.replace('_', ' ')}",
        action=action.value,
        subject_kind=subject_kind.value,
        subject=code,
        subject_id=str(subject_id) if subject_id else None,
        parent=parent,
        fields=names or None,
        actor=actor.label,
    )
    return entry


class AuditQuery(BaseModel):
    """What a reading of the trail narrows to; nothing set reads all of it."""

    model_config = ConfigDict(frozen=True)

    subject_kind: AuditSubject | None = None
    subject: str | None = None
    actor: str | None = None
    """An account's username, or a host command's label for changes no account made."""

    action: AuditAction | None = None
    since: datetime | None = None
    until: datetime | None = None


async def list_entries(
    session: AsyncSession, query: AuditQuery, *, after: int | None = None, limit: int | None = None
) -> list[AuditEntry]:
    """Read the trail newest first, narrowed by the query and continued below ``after``."""
    statement = sa.select(AuditEntry).order_by(AuditEntry.id.desc())
    if query.subject_kind is not None:
        statement = statement.where(AuditEntry.subject_kind == query.subject_kind)
    if query.subject is not None:
        statement = statement.where(AuditEntry.subject_code == query.subject)
    if query.actor is not None:
        statement = statement.where(
            sa.or_(
                AuditEntry.actor_username == query.actor,
                sa.and_(AuditEntry.actor_username.is_(None), AuditEntry.actor_label == query.actor),
            )
        )
    if query.action is not None:
        statement = statement.where(AuditEntry.action == query.action)
    if query.since is not None:
        statement = statement.where(AuditEntry.created_at >= query.since)
    if query.until is not None:
        statement = statement.where(AuditEntry.created_at < query.until)
    if after is not None:
        statement = statement.where(AuditEntry.id < after)
    if limit is not None:
        statement = statement.limit(limit)
    return list((await session.execute(statement)).scalars())
