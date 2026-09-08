"""Accounts, passwords, and bearer credentials: what authenticates and what does not."""

import time
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import TokenKind, TriggerKind, UserRole
from dirigent_core.auth import (
    LAST_USED_RESOLUTION,
    DuplicateEmail,
    DuplicateUser,
    LastAdmin,
    WeakPassword,
    WrongPassword,
    absent_password_hash,
    activate_user,
    authenticate,
    bootstrap_admin,
    change_password,
    count_active_admins,
    count_users,
    create_user,
    deactivate_user,
    find_user,
    hash_password,
    hash_token,
    issue_token,
    list_tokens,
    list_users,
    mint_secret,
    reset_password,
    resolve_token,
    revoke_session,
    revoke_sessions,
    revoke_token,
    set_email,
    set_role,
    verify_password,
)
from dirigent_core.database import session_scope
from dirigent_core.models import utcnow

PASSWORD = "correct horse battery"


async def test_a_password_is_hashed_and_never_stored_in_the_clear() -> None:
    hashed = hash_password(PASSWORD)
    assert PASSWORD not in hashed
    assert hashed.startswith("$argon2")
    assert verify_password(hashed, PASSWORD)
    assert not verify_password(hashed, "wrong")


def test_two_hashes_of_the_same_password_differ() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_a_short_password_is_refused_before_it_is_hashed() -> None:
    with pytest.raises(WeakPassword):
        hash_password("short")


def test_verifying_against_something_that_is_not_a_hash_is_false_not_an_error() -> None:
    assert not verify_password("not a hash at all", PASSWORD)


def test_a_token_is_unguessable_and_stored_only_as_a_hash() -> None:
    secret = mint_secret()
    assert len(secret) >= 32
    assert secret != mint_secret()
    assert hash_token(secret) == hash_token(secret)
    assert secret not in hash_token(secret)


async def test_a_user_can_be_created_and_authenticated(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
    async with session_scope(sessions) as session:
        user = await authenticate(session, "morten", PASSWORD)
        assert user is not None and user.role is UserRole.ADMIN
        assert user.last_login_at is not None


async def test_a_wrong_password_and_a_missing_account_answer_the_same(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
    async with session_scope(sessions) as session:
        assert await authenticate(session, "morten", "wrong") is None
        assert await authenticate(session, "nobody", PASSWORD) is None


async def test_a_deactivated_account_cannot_log_in(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        user.active = False
    async with session_scope(sessions) as session:
        assert await authenticate(session, "morten", PASSWORD) is None


async def test_two_accounts_may_not_share_a_name(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
    async with session_scope(sessions) as session:
        with pytest.raises(DuplicateUser):
            await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)


async def test_a_reset_ends_every_session_and_keeps_the_api_tokens(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        api = await issue_token(session, user, name="ci")
        browser = await issue_token(session, user, name="web", kind=TokenKind.SESSION)
    async with session_scope(sessions) as session:
        row = await find_user(session, "morten")
        assert row is not None
        await reset_password(session, row, "a different password")
    async with session_scope(sessions) as session:
        assert await authenticate(session, "morten", "a different password") is not None
        assert await authenticate(session, "morten", PASSWORD) is None
        assert await resolve_token(session, browser.secret.get_secret_value()) is None
        assert await resolve_token(session, api.secret.get_secret_value()) is not None


async def test_two_accounts_may_not_share_an_email(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN, email="one@example.com")
    async with session_scope(sessions) as session:
        with pytest.raises(DuplicateEmail):
            await create_user(session, "second", PASSWORD, role=UserRole.ADMIN, email="one@example.com")
        await create_user(session, "second", PASSWORD, role=UserRole.ADMIN, email="two@example.com")
    async with session_scope(sessions) as session:
        taken = await find_user(session, "second")
        assert taken is not None
        with pytest.raises(DuplicateEmail):
            await set_email(session, taken, "one@example.com")
    async with session_scope(sessions) as session:
        held = await find_user(session, "second")
        assert held is not None
        await set_email(session, held, "two@example.com")
        assert held.email == "two@example.com"
        await set_email(session, held, None)
        assert held.email is None


async def test_a_token_resolves_to_the_principal_it_belongs_to(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        issued = await issue_token(session, user, name="ci")
    async with session_scope(sessions) as session:
        principal = await resolve_token(session, issued.secret.get_secret_value())
    assert principal is not None
    assert principal.username == "morten"
    assert principal.token_name == "ci"
    assert principal.via is TokenKind.API
    assert principal.is_admin
    assert "token ci" in principal.label
    assert principal.trigger_kind is TriggerKind.API_TOKEN


async def test_a_session_reads_as_a_person_not_as_automation(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        issued = await issue_token(session, user, name="web", kind=TokenKind.SESSION)
    async with session_scope(sessions) as session:
        principal = await resolve_token(session, issued.secret.get_secret_value())
    assert principal is not None
    assert principal.trigger_kind is TriggerKind.USER
    assert principal.label == "morten"


async def test_an_unknown_expired_or_revoked_token_resolves_to_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        live = await issue_token(session, user, name="ci")
        stale = await issue_token(session, user, name="old", lifetime=timedelta(seconds=1))
    async with session_scope(sessions) as session:
        assert await resolve_token(session, "not a token") is None
        assert await resolve_token(session, stale.secret.get_secret_value(), now=utcnow() + timedelta(hours=1)) is None
        assert await revoke_token(session, user_id=user.id, name="ci") is True
    async with session_scope(sessions) as session:
        assert await resolve_token(session, live.secret.get_secret_value()) is None
        assert await revoke_token(session, user_id=user.id, name="ci") is False


async def test_a_token_of_a_deactivated_user_stops_working(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        issued = await issue_token(session, user, name="ci")
        user.active = False
    async with session_scope(sessions) as session:
        assert await resolve_token(session, issued.secret.get_secret_value()) is None


async def test_using_a_token_records_when_it_was_last_used(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        issued = await issue_token(session, user, name="ci")
    async with session_scope(sessions) as session:
        await resolve_token(session, issued.secret.get_secret_value())
    async with session_scope(sessions) as session:
        tokens = await list_tokens(session)
        assert [token.name for token in tokens] == ["ci"]
        assert tokens[0].last_used_at is not None
        assert tokens[0].prefix == issued.secret.get_secret_value()[:8]


async def test_a_second_use_inside_the_window_does_not_write_the_timestamp_again(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Recording the use is throttled, because otherwise every read of the API is a write."""
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        issued = await issue_token(session, user, name="ci")
    secret = issued.secret.get_secret_value()

    first = utcnow()
    async with session_scope(sessions) as session:
        assert await resolve_token(session, secret, now=first) is not None

    inside = first + LAST_USED_RESOLUTION - timedelta(seconds=1)
    async with session_scope(sessions) as session:
        assert await resolve_token(session, secret, now=inside) is not None
        assert (await list_tokens(session))[0].last_used_at == first, (
            "a use inside the window must leave the stored value alone"
        )
        assert not session.dirty, "nothing was changed, so there is nothing for the commit to write"

    async with session_scope(sessions) as session:
        assert (await list_tokens(session))[0].last_used_at == first

    beyond = first + LAST_USED_RESOLUTION
    async with session_scope(sessions) as session:
        assert await resolve_token(session, secret, now=beyond) is not None
    async with session_scope(sessions) as session:
        assert (await list_tokens(session))[0].last_used_at == beyond, "past the window the field moves again"


async def test_a_listing_never_shows_sessions(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        await issue_token(session, user, name="ci")
        await issue_token(session, user, name="web", kind=TokenKind.SESSION)
    async with session_scope(sessions) as session:
        assert [token.name for token in await list_tokens(session)] == ["ci"]
        assert [token.name for token in await list_tokens(session, user_id=user.id)] == ["ci"]


async def test_revoking_by_name_reaches_only_the_named_account(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        one = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        other = await create_user(session, "second", PASSWORD, role=UserRole.ADMIN)
        mine = await issue_token(session, one, name="ci")
        theirs = await issue_token(session, other, name="ci")
    async with session_scope(sessions) as session:
        assert await revoke_token(session, user_id=one.id, name="ci") is True
    async with session_scope(sessions) as session:
        assert await resolve_token(session, mine.secret.get_secret_value()) is None
        assert await resolve_token(session, theirs.secret.get_secret_value()) is not None


async def test_a_listed_token_names_the_account_that_holds_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        await issue_token(session, user, name="ci")
    async with session_scope(sessions) as session:
        assert [(row.username, row.name) for row in await list_tokens(session)] == [("morten", "ci")]


async def test_logging_out_revokes_exactly_that_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        one = await issue_token(session, user, name="web", kind=TokenKind.SESSION)
        two = await issue_token(session, user, name="web", kind=TokenKind.SESSION)
    async with session_scope(sessions) as session:
        await revoke_session(session, one.secret.get_secret_value())
        await revoke_session(session, "not a session")
    async with session_scope(sessions) as session:
        assert await resolve_token(session, one.secret.get_secret_value()) is None
        assert await resolve_token(session, two.secret.get_secret_value()) is not None


async def test_the_bootstrap_admin_is_created_once_and_never_again(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        created = await bootstrap_admin(session, PASSWORD)
        assert created is not None and created.username == "admin"
    async with session_scope(sessions) as session:
        assert await bootstrap_admin(session, "another password entirely") is None
        assert await count_users(session) == 1
        assert [user.username for user in await list_users(session)] == ["admin"]


async def test_an_unknown_username_costs_the_same_as_a_wrong_password(sessions: Any) -> None:
    """The identical message is only half the answer; the other half is the identical time."""
    async with session_scope(sessions) as session:
        await create_user(session, "present", "a good enough password", role=UserRole.ADMIN)

    async with session_scope(sessions) as session:
        missing = time.perf_counter()
        assert await authenticate(session, "absent", "a good enough password") is None
        missing = time.perf_counter() - missing

        wrong = time.perf_counter()
        assert await authenticate(session, "present", "not the password") is None
        wrong = time.perf_counter() - wrong

    # Generous, because a timing assertion on a busy machine has to be; what it rules out is
    # a miss answering orders of magnitude faster than a hit.
    assert missing > wrong / 10, f"a missing account answered in {missing:.4f}s against {wrong:.4f}s"


def test_the_absent_password_hash_is_a_real_hash_nothing_can_match() -> None:
    assert absent_password_hash().startswith("$argon2")
    assert verify_password(absent_password_hash(), "anything at all") is False


async def test_the_only_active_admin_cannot_demote_itself(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The last admin giving up the role would leave nobody able to manage the instance."""
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
    async with session_scope(sessions) as session:
        only = await find_user(session, "morten")
        assert only is not None
        with pytest.raises(LastAdmin):
            await set_role(session, only, UserRole.OPERATOR)
    async with session_scope(sessions) as session:
        still = await find_user(session, "morten")
        assert still is not None and still.role is UserRole.ADMIN


async def test_an_admin_may_be_demoted_once_another_active_one_exists(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        await create_user(session, "second", PASSWORD, role=UserRole.ADMIN)
    async with session_scope(sessions) as session:
        one = await find_user(session, "morten")
        assert one is not None
        await set_role(session, one, UserRole.OPERATOR)
    async with session_scope(sessions) as session:
        assert await count_active_admins(session) == 1
        left = await find_user(session, "second")
        assert left is not None
        with pytest.raises(LastAdmin):
            await set_role(session, left, UserRole.VIEWER)


async def test_a_deactivated_admin_does_not_count_towards_the_lockout_guard(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """An account that cannot log in cannot rescue an instance from having no admin."""
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        asleep = await create_user(session, "asleep", PASSWORD, role=UserRole.ADMIN)
        asleep.active = False
    async with session_scope(sessions) as session:
        assert await count_active_admins(session) == 1
        only = await find_user(session, "morten")
        assert only is not None
        with pytest.raises(LastAdmin):
            await deactivate_user(session, only)


async def test_deactivating_an_account_revokes_the_sessions_it_holds(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The flag and the revocations land together, so no session outlives the account's access."""
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        operator = await create_user(session, "second", PASSWORD, role=UserRole.OPERATOR)
        web = await issue_token(session, operator, name="web", kind=TokenKind.SESSION)
        api = await issue_token(session, operator, name="ci")
    async with session_scope(sessions) as session:
        row = await find_user(session, "second")
        assert row is not None
        await deactivate_user(session, row)
    async with session_scope(sessions) as session:
        gone = await find_user(session, "second")
        assert gone is not None and gone.active is False
        assert await resolve_token(session, web.secret.get_secret_value()) is None
        assert await resolve_token(session, api.secret.get_secret_value()) is None, "the account is barred"
        held = await list_tokens(session, user_id=gone.id)
        assert [token.revoked_at is None for token in held] == [True], "the api token itself is not revoked"


async def test_an_account_can_be_activated_again(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        await create_user(session, "second", PASSWORD, role=UserRole.OPERATOR)
    async with session_scope(sessions) as session:
        row = await find_user(session, "second")
        assert row is not None
        await deactivate_user(session, row)
    async with session_scope(sessions) as session:
        row = await find_user(session, "second")
        assert row is not None
        await activate_user(session, row)
    async with session_scope(sessions) as session:
        assert await authenticate(session, "second", PASSWORD) is not None


async def test_changing_a_password_ends_every_other_session_but_this_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        here = await issue_token(session, user, name="web", kind=TokenKind.SESSION)
        elsewhere = await issue_token(session, user, name="web", kind=TokenKind.SESSION)
    async with session_scope(sessions) as session:
        row = await find_user(session, "morten")
        assert row is not None
        await change_password(session, row, PASSWORD, "a different password", keep=here.id)
    async with session_scope(sessions) as session:
        assert await authenticate(session, "morten", "a different password") is not None
        assert await resolve_token(session, here.secret.get_secret_value()) is not None
        assert await resolve_token(session, elsewhere.secret.get_secret_value()) is None


async def test_a_password_change_presenting_the_wrong_current_one_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
    async with session_scope(sessions) as session:
        row = await find_user(session, "morten")
        assert row is not None
        with pytest.raises(WrongPassword):
            await change_password(session, row, "not the password", "a different password")
        with pytest.raises(WeakPassword):
            await change_password(session, row, PASSWORD, "short")
    async with session_scope(sessions) as session:
        assert await authenticate(session, "morten", PASSWORD) is not None, "the stored hash is untouched"


async def test_revoking_sessions_leaves_api_tokens_alone(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        user = await create_user(session, "morten", PASSWORD, role=UserRole.ADMIN)
        api = await issue_token(session, user, name="ci")
        await issue_token(session, user, name="web", kind=TokenKind.SESSION)
    async with session_scope(sessions) as session:
        row = await find_user(session, "morten")
        assert row is not None
        assert await revoke_sessions(session, row.id) == 1
    async with session_scope(sessions) as session:
        assert await resolve_token(session, api.secret.get_secret_value()) is not None
