"""What uses a connection, and the refusal to remove one while anything does.

A pipeline names a connection from inside its document's JSON, so no foreign key can hold the
row back. The delete reads the documents under a row lock, and an apply holds a shared lock on
every connection its document names from before it checks them until it commits: whichever gets
there second waits, then sees what the first one did. SQLite takes the write lock at ``BEGIN
IMMEDIATE`` and renders neither lock.
"""

from collections.abc import Iterable, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import NotificationStatus
from dirigent_client.schemas import Catalog, ConnectionUsers, PipelineUse
from dirigent_core.engine.definition import connections_named
from dirigent_core.errors import DomainError
from dirigent_core.messages import CONNECTION_IN_USE
from dirigent_core.models import AlertRule, Connection, Notification, Pipeline, PipelineVersion


class ConnectionInUse(DomainError):
    """A connection was asked to be removed while something still reads it."""

    status = 409
    message = CONNECTION_IN_USE

    def __init__(self, code: str, users: ConnectionUsers) -> None:
        """Say what uses it, as a sentence and as what the read answers under ``used_by``."""
        super().__init__(code=repr(code), users=said(users), used_by=users.model_dump(mode="json"))
        self.users = users


def said(users: ConnectionUsers) -> str:
    """Name what uses a connection, one clause per family."""
    families: Sequence[tuple[str, str, list[str]]] = (
        ("pipeline", "pipelines", [one.pipeline for one in users.pipelines]),
        ("alert rule", "alert rules", users.alert_rules),
        ("storage scheme", "storage schemes", users.storage_schemes),
    )
    clauses = [f"{one if len(codes) == 1 else many} {', '.join(codes)}" for one, many, codes in families if codes]
    return " and ".join(clauses)


async def connection_users(
    session: AsyncSession, catalog: Catalog, storage_connections: Mapping[str, str], code: str
) -> ConnectionUsers:
    """Read what uses one connection now: current documents, alert rules and storage schemes.

    Only each pipeline's current version is asked. A past version is history, and a code held
    back by one nobody applies any more could never be removed. The documents are walked here
    rather than queried into, so SQLite and PostgreSQL answer the same thing.
    """
    statement = (
        sa.select(Pipeline.code, PipelineVersion.document)
        .join(PipelineVersion, PipelineVersion.pipeline_id == Pipeline.id)
        .where(PipelineVersion.version == Pipeline.current_version)
        .order_by(Pipeline.code)
    )
    pipelines: list[PipelineUse] = []
    for pipeline, document in (await session.execute(statement)).all():
        naming = connections_named(document, catalog).get(code)
        if naming is not None:
            pipelines.append(PipelineUse(pipeline=pipeline, steps=naming.steps, sources=naming.sources))
    rules = await session.execute(
        sa.select(AlertRule.code)
        .join(Connection, AlertRule.connection_id == Connection.id)
        .where(Connection.code == code)
        .order_by(AlertRule.code)
    )
    return ConnectionUsers(
        pipelines=pipelines,
        alert_rules=list(rules.scalars()),
        storage_schemes=sorted(scheme for scheme, named in storage_connections.items() if named == code),
    )


async def hold_connections(session: AsyncSession, codes: Iterable[str]) -> None:
    """Keep these connections from being deleted until this transaction ends."""
    await session.execute(
        sa.select(Connection.id).where(Connection.code.in_(sorted(set(codes)))).with_for_update(read=True)
    )


async def remove_connection(
    session: AsyncSession, catalog: Catalog, storage_connections: Mapping[str, str], row: Connection
) -> None:
    """Delete a connection, or refuse with what uses it.

    A test message with no rule behind it is the one delivery that outlives what it was sent for,
    so a settled one lets go of the connection. One still queued keeps it, through the foreign
    key the caller answers for.
    """
    await session.execute(sa.select(Connection.id).where(Connection.id == row.id).with_for_update())
    users = await connection_users(session, catalog, storage_connections, row.code)
    if not users.empty:
        raise ConnectionInUse(row.code, users)
    await session.execute(
        sa.update(Notification)
        .where(
            Notification.connection_id == row.id,
            Notification.alert_rule_id.is_(None),
            Notification.status.in_((NotificationStatus.SENT, NotificationStatus.FAILED)),
        )
        .values(connection_id=None)
    )
    await session.delete(row)
    await session.flush()
