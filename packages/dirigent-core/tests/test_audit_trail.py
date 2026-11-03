"""The audit trail in core: who a change is attributed to, what a reading narrows to, and how long it is kept."""

import logging
from collections.abc import AsyncIterator, Generator, MutableMapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from dirigent_client.enums import AuditAction, AuditSubject, TokenKind, UserRole
from dirigent_core import audit, retention
from dirigent_core.auth import Principal, create_user, issue_token, revoke_token
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.models import AuditEntry


@contextmanager
def capture_info() -> Generator[list[MutableMapping[str, Any]]]:
    """Capture structured log events at INFO and up, whatever level an earlier test configured."""
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
    try:
        with capture_logs() as logged:
            yield logged
    finally:
        structlog.configure(**saved)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_scope(sessions) as opened:
        yield opened


async def trail(session: AsyncSession) -> list[AuditEntry]:
    return list((await session.execute(sa.select(AuditEntry).order_by(AuditEntry.id))).scalars())


async def test_a_change_with_no_actor_named_is_the_systems(session: AsyncSession) -> None:
    await create_user(session, "ola", "a long enough password", role=UserRole.VIEWER)
    [entry] = await trail(session)
    assert (entry.action, entry.subject_kind, entry.subject_code) == (AuditAction.CREATED, AuditSubject.USER, "ola")
    assert (entry.actor_label, entry.actor_username) == ("system", None)


async def test_a_host_command_names_itself_and_a_session_actor_beats_it(session: AsyncSession) -> None:
    with audit.acting_as(audit.host("dg admin user create")):
        user = await create_user(session, "ola", "a long enough password", role=UserRole.ADMIN)
        principal = Principal(
            user_id=user.id,
            username="ola",
            role=UserRole.ADMIN,
            token_name="mcp-trial",
            token_prefix="abcd1234",
            via=TokenKind.API,
        )
        audit.act_as(session, principal.actor)
        issued = await issue_token(session, user, name="ci")
    created_user, created_token = await trail(session)
    assert created_user.actor_label == "dg admin user create"
    assert created_token.actor_label == "ola (token mcp-trial)"
    assert (created_token.actor_token, created_token.actor_token_prefix) == ("mcp-trial", "abcd1234")
    assert (created_token.subject_code, created_token.parent_code, created_token.subject_id) == ("ci", "ola", issued.id)


async def test_a_revoke_is_journalled_and_logged_with_the_same_fields(session: AsyncSession) -> None:
    user = await create_user(session, "ola", "a long enough password", role=UserRole.ADMIN)
    issued = await issue_token(session, user, name="ci")
    with capture_info() as logged:
        assert await revoke_token(session, issued.id)
    [line] = [line for line in logged if line.get("action") == "revoked"]
    assert line["log_level"] == "info"
    assert (line["subject_kind"], line["subject"], line["parent"], line["actor"]) == ("token", "ci", "ola", "system")
    assert (await trail(session))[-1].action is AuditAction.REVOKED


async def test_a_session_token_is_never_journalled(session: AsyncSession) -> None:
    user = await create_user(session, "ola", "a long enough password", role=UserRole.ADMIN)
    await issue_token(session, user, name="browser", kind=TokenKind.SESSION)
    assert [entry.subject_kind for entry in await trail(session)] == [AuditSubject.USER]


async def test_the_trail_is_kept_a_year_unless_told_otherwise(session: AsyncSession) -> None:
    assert Settings().retention_audit == timedelta(days=365)
    await create_user(session, "old", "a long enough password", role=UserRole.VIEWER)
    await create_user(session, "new", "a long enough password", role=UserRole.VIEWER)
    await session.execute(
        sa.update(AuditEntry).where(AuditEntry.subject_code == "old").values(created_at=NOW - timedelta(days=400))
    )
    policy = retention.Policy(audit=timedelta(days=365))
    assert retention.configured(policy)
    assert await retention.counted(session, policy, now=NOW) == {"audit": 1}
    swept = await retention.sweep(session, policy, now=NOW)
    assert swept.counts == {"audit": 1}
    assert [entry.subject_code for entry in await trail(session)] == ["new"]


async def test_a_reading_narrows_by_actor_and_window(session: AsyncSession) -> None:
    with audit.acting_as(audit.host("dg dev")):
        await create_user(session, "ola", "a long enough password", role=UserRole.VIEWER)
    await create_user(session, "kari", "a long enough password", role=UserRole.VIEWER)
    by_dev = await audit.list_entries(session, audit.AuditQuery(actor="dg dev"))
    assert [entry.subject_code for entry in by_dev] == ["ola"]
    future = await audit.list_entries(session, audit.AuditQuery(since=datetime.now(UTC) + timedelta(hours=1)))
    assert future == []
    newest_first = await audit.list_entries(session, audit.AuditQuery(), limit=1)
    assert [entry.subject_code for entry in newest_first] == ["kari"]
