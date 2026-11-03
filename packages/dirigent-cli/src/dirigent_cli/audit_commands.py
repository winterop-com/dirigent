"""``dg audit``: who changed what on an instance, newest first. Admin only."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from dirigent_cli.commands import fail, paged
from dirigent_cli.context import client_for, state_of
from dirigent_cli.messages import NOT_A_MOMENT
from dirigent_cli.output import emit_records
from dirigent_client.enums import AuditAction, AuditSubject
from dirigent_common.durations import DurationError, parse_duration

#: How many changes a listing shows when no limit is given.
AUDIT_PAGE = 50


def moment_of(value: str | None, *, option: str, now: datetime | None = None) -> datetime | None:
    """Read an option naming an instant: an ISO timestamp, or a duration back from now such as 24h."""
    if value is None:
        return None
    try:
        back = parse_duration(value)
    except DurationError:
        back = None
    if isinstance(back, timedelta):
        return (now or datetime.now(UTC)) - back
    try:
        named = datetime.fromisoformat(value)
    except ValueError:
        fail(NOT_A_MOMENT, option=option, value=repr(value))
    return named if named.tzinfo is not None else named.replace(tzinfo=UTC)


def audit(
    ctx: typer.Context,
    subject_kind: Annotated[
        AuditSubject | None, typer.Option("--kind", help="Only changes to this kind of thing, such as connection.")
    ] = None,
    subject: Annotated[
        str | None, typer.Option("--subject", help="Only changes to the subject with this code.")
    ] = None,
    actor: Annotated[
        str | None, typer.Option(help="Only changes by this username, or by this host command, such as dg dev.")
    ] = None,
    action: Annotated[AuditAction | None, typer.Option(help="Only changes of this action, such as deleted.")] = None,
    since: Annotated[
        str | None, typer.Option(help="Only changes after this: a timestamp, or a span back such as 24h.")
    ] = None,
    until: Annotated[
        str | None, typer.Option(help="Only changes before this: a timestamp, or a span back such as 1h.")
    ] = None,
    limit: Annotated[int, typer.Option(help=f"How many changes at most; {AUDIT_PAGE} when omitted.")] = AUDIT_PAGE,
) -> None:
    """List administrative changes, newest first: who, when, what, and which fields; never a value."""
    after_moment = moment_of(since, option="--since")
    before_moment = moment_of(until, option="--until")
    with client_for(state_of(ctx)) as dg:
        rows = list(
            paged(
                lambda after, size: dg.call(
                    dg.audit.list(
                        subject_kind=subject_kind,
                        subject=subject,
                        actor=actor,
                        action=action,
                        since=after_moment,
                        until=before_moment,
                        after=after,
                        limit=size,
                    )
                ),
                limit,
            )
        )
    emit_records("audit", rows)
