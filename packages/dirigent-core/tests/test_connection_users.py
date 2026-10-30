"""What uses a connection: the document walk behind the refusal to remove one."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AlertEvent, NotificationStatus
from dirigent_client.schemas import BlockEntry, BlockKind, Catalog, ConnectionUsers, PipelineUse, SourceEntry
from dirigent_core.connections import ConnectionInUse, connection_users, remove_connection, said
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import connections_named
from dirigent_core.models import Connection, Notification, Pipeline, PipelineVersion
from dirigent_plugin import REFERENCE_KEYWORD

SIGNED = {"properties": {"sign_with": {"type": "string", REFERENCE_KEYWORD: "connection"}, "note": {"type": "string"}}}

CATALOG = Catalog(
    blocks=[
        BlockEntry(id="test.signed", kind=BlockKind.OPERATOR, summary="", group="", plugin="", config_schema=SIGNED),
    ],
    sources=[SourceEntry(kind="test.listen", plugin="", summary="", hosting="held", config_schema=SIGNED)],
)


def test_a_document_names_a_connection_under_connection_and_under_a_published_reference() -> None:
    document = {
        "requires": {"connections": ["asked"]},
        "steps": {
            "plain": {"block": "test.signed", "config": {"connection": "by-key", "note": "not-a-reference"}},
            "signed": {"block": "test.signed", "config": {"sign_with": "by-marker"}},
            "gone": {"block": "nobody.installed", "config": {"connection": "by-key", "sign_with": "unknowable"}},
        },
    }
    named = connections_named(document, CATALOG)
    assert set(named) == {"asked", "by-key", "by-marker"}
    assert named["asked"].steps == [], "a requirement has no step behind it"
    assert named["by-key"].steps == ["plain", "gone"], "a block no longer installed still answers for the key"
    assert named["by-marker"].steps == ["signed"]


def test_a_source_node_names_a_connection_beside_its_kind() -> None:
    document = {
        "steps": {
            "listen": {"source": {"kind": "test.listen", "connection": "held"}},
            "signed": {"source": {"kind": "test.listen", "sign_with": "marked"}},
        }
    }
    named = connections_named(document, CATALOG)
    assert named["held"].sources == ["listen"]
    assert named["held"].steps == []
    assert named["marked"].sources == ["signed"]


def test_a_connection_written_as_a_reference_is_not_one_a_document_can_be_said_to_name() -> None:
    document = {
        "requires": {"connections": ["${params.asked}"]},
        "steps": {"fetch": {"block": "test.signed", "config": {"connection": "${params.where}"}}},
    }
    assert connections_named(document, CATALOG) == {}


def test_a_refusal_names_each_family() -> None:
    users = ConnectionUsers(
        pipelines=[PipelineUse(pipeline="a"), PipelineUse(pipeline="b")],
        alert_rules=["page"],
        storage_schemes=["s3"],
    )
    assert said(users) == "pipelines a, b and alert rule page and storage scheme s3"
    assert said(ConnectionUsers()) == ""


async def _stored(sessions: async_sessionmaker[AsyncSession], code: str = "ops-api") -> Connection:
    async with session_scope(sessions) as session:
        row = Connection(code=code, kind="http", config={"base_url": "https://ops.example.org"})
        session.add(row)
    return row


async def test_only_each_pipelines_current_version_counts(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with session_scope(sessions) as session:
        holder = Pipeline(code="nightly", current_version=2)
        session.add(holder)
        await session.flush()
        naming = {"steps": {"fetch": {"block": "test.signed", "config": {"connection": "ops-api"}}}}
        session.add(PipelineVersion(pipeline_id=holder.id, version=1, document=naming, digest="sha256:1"))
        session.add(PipelineVersion(pipeline_id=holder.id, version=2, document={"steps": {}}, digest="sha256:2"))
    async with sessions() as session:
        assert (await connection_users(session, CATALOG, {}, "ops-api")).empty


async def test_a_storage_scheme_configured_from_a_connection_holds_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _stored(sessions)
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Connection))).scalar_one()
        with pytest.raises(ConnectionInUse) as refused:
            await remove_connection(session, CATALOG, {"s3": "ops-api", "gcs": "other"}, row)
    assert refused.value.users.storage_schemes == ["s3"]
    assert "storage scheme s3" in str(refused.value)


async def test_a_settled_test_message_lets_go_of_the_connection(sessions: async_sessionmaker[AsyncSession]) -> None:
    """A test message has no rule to delete, so nothing else would ever free the connection."""
    await _stored(sessions)
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Connection))).scalar_one()
        session.add(
            Notification(
                event=AlertEvent.RUN_SUCCEEDED,
                notifier="webhook",
                connection_id=row.id,
                subject="test",
                status=NotificationStatus.SENT,
            )
        )
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Connection))).scalar_one()
        await remove_connection(session, CATALOG, {}, row)
    async with sessions() as session:
        assert (await session.execute(sa.select(Connection))).first() is None
        kept = (await session.execute(sa.select(Notification))).scalar_one()
        assert kept.connection_id is None, "the delivery record stays, without the connection"
