"""Tests for the baseline schema and the migration that creates it."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from dirigent_client.enums import AttemptStatus, RunStatus, TriggerKind
from dirigent_core import migrations
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, ping, session_scope
from dirigent_core.ids import uuid7
from dirigent_core.models import (
    ALL_TABLES,
    Base,
    Entity,
    Journal,
    Pipeline,
    PipelineVersion,
    Run,
    StepAttempt,
)
from dirigent_core.types import UtcDateTime


@pytest.fixture
def sqlite_settings(tmp_path: Path) -> Settings:
    """Point the settings at a throwaway file-backed SQLite database."""
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}")


@pytest.fixture
async def engine(sqlite_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Provide an engine on a database created from the ORM metadata, disposed when the test ends."""
    engine = create_engine(sqlite_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def test_every_table_is_registered_in_the_metadata() -> None:
    declared = {model.__tablename__ for model in ALL_TABLES}
    assert declared == set(Base.metadata.tables)
    assert len(declared) == 19


def test_every_entity_is_identified_and_stamped_the_same_way() -> None:
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not issubclass(model, Entity):
            continue
        table, where = mapper.local_table, model.__tablename__
        columns = list(table.columns)
        names = [column.name for column in columns]
        assert names[0] == "id", f"{where}.id is not the first column"
        assert names[names.index("created_at") + 1] == "updated_at", f"{where} splits its stamps"
        trailing = columns[names.index("updated_at") + 1 :]
        assert all(isinstance(column.type, UtcDateTime) for column in trailing), f"{where} sorts a plain column last"
        assert isinstance(table.c.id.type, sa.Uuid) and table.c.id.primary_key, f"{where}.id is not a uuid key"
        assert table.c.id.default.arg(None).version == 7, f"{where}.id is not minted as a uuid7"
        for name in ("created_at", "updated_at"):
            column = table.c[name]
            assert not column.nullable, f"{where}.{name} is nullable"
            assert column.default is not None and column.server_default is not None, f"{where}.{name} has no default"
        assert table.c.created_at.onupdate is None, f"{where}.created_at moves on update"
        assert table.c.updated_at.onupdate is not None, f"{where}.updated_at does not move on update"


def test_no_journal_row_carries_a_last_modified_stamp() -> None:
    """A journal row is written once, so there is nothing for an update stamp to say."""
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not issubclass(model, Journal):
            continue
        table, where = mapper.local_table, model.__tablename__
        assert "updated_at" not in table.columns, f"{where} carries an updated_at"
        assert not hasattr(model, "updated_at"), f"{model.__name__} exposes an updated_at"
        assert table.c.id.primary_key and table.c.id.autoincrement, f"{where}.id is not an autoincrement key"
        assert isinstance(table.c.id.type, sa.BigInteger), f"{where}.id is not the wide integer a cursor needs"
        assert "created_at" in table.columns, f"{where} has no created_at"


def test_every_timestamp_column_is_timezone_aware() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, sa.DateTime):
                assert column.type.timezone is True, f"{table.name}.{column.name} is not timestamptz"


def test_the_claim_query_indexes_exist() -> None:
    indexes = {index.name for index in Base.metadata.tables["step_attempts"].indexes}
    assert "ix_step_attempts_status_available_at" in indexes
    assert "ix_step_attempts_status_next_poll_at" in indexes
    assert "ix_step_attempts_lease_expires_at" in indexes


def test_json_columns_use_jsonb_on_postgres_and_json_elsewhere() -> None:
    column = Base.metadata.tables["pipeline_versions"].columns["document"]
    postgres_impl = column.type.dialect_impl(postgresql.dialect())
    sqlite_impl = column.type.dialect_impl(sqlite.dialect())
    assert isinstance(postgres_impl, postgresql.JSONB)
    assert isinstance(sqlite_impl, sa.JSON)


def test_uuid7_is_time_ordered_and_correctly_versioned() -> None:
    first, second = uuid7(), uuid7()
    assert first.version == 7
    assert first.variant == "specified in RFC 4122"
    assert first.bytes < second.bytes


def test_uuid7_stays_ordered_inside_a_millisecond() -> None:
    """A millisecond is the resolution at which this system actually does things."""
    minted = [uuid7() for _ in range(2000)]
    assert minted == sorted(minted)
    assert len(set(minted)) == len(minted)


async def test_the_baseline_migration_creates_the_whole_schema(sqlite_settings: Settings) -> None:
    await migrations.upgrade_async(settings=sqlite_settings)
    assert await migrations.current_revision_async(sqlite_settings) == migrations.head_revision(sqlite_settings)

    engine = create_engine(sqlite_settings)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
    finally:
        await engine.dispose()

    assert {model.__tablename__ for model in ALL_TABLES} <= tables


async def test_the_baseline_migration_is_reversible(sqlite_settings: Settings) -> None:
    await migrations.upgrade_async(settings=sqlite_settings)
    await migrations.downgrade_async("base", settings=sqlite_settings)
    assert await migrations.current_revision_async(sqlite_settings) is None


def test_the_migration_history_names_every_revision() -> None:
    settings = Settings()
    assert migrations.head_revision(settings) == "0001_baseline"
    history = migrations.history(settings)
    assert "0001_baseline (head)" in history
    assert history.strip().count("\n") == 0, "one revision, because nothing has shipped that needs a second"


async def test_an_engine_creates_the_directory_its_sqlite_file_needs(tmp_path: Path) -> None:
    """The driver opens a file and never a path, so nobody should have to mkdir first."""
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / '.dirigent' / 'state' / 'dirigent.db'}")
    engine = create_engine(settings)
    try:
        assert (tmp_path / ".dirigent" / "state").is_dir()
        assert await ping(engine) is True
    finally:
        await engine.dispose()


async def test_ping_reports_a_reachable_database(engine: AsyncEngine) -> None:
    assert await ping(engine) is True


async def test_ping_reports_an_unreachable_database(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{blocker / 'dirigent.db'}"))
    try:
        assert await ping(engine) is False
    finally:
        await engine.dispose()


async def test_a_run_pins_the_pipeline_version_it_started_from(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    pipeline = Pipeline(code="daily-climate-load", description="A pipeline.")
    async with session_scope(factory) as session:
        session.add(pipeline)
        await session.flush()
        version = PipelineVersion(
            pipeline_id=pipeline.id,
            version=1,
            document={"format": "dirigent/v1", "kind": "pipeline", "steps": {}},
            digest="sha256:" + "0" * 64,
        )
        session.add(version)
        await session.flush()
        run = Run(
            pipeline_id=pipeline.id,
            pipeline_version_id=version.id,
            params={"day": "2026-08-28"},
            triggered_by_kind=TriggerKind.SCHEDULE,
        )
        session.add(run)
        await session.flush()
        session.add(
            StepAttempt(
                run_id=run.id,
                step_name="wait_for_drop",
                block_id="storage.exists",
                status=AttemptStatus.WAITING,
                available_at=datetime.now(UTC),
                next_poll_at=datetime.now(UTC) + timedelta(minutes=5),
                remote_handle={"block_id": "storage.exists", "ref": "job-1"},
            )
        )

    async with session_scope(factory) as session:
        stored = (await session.execute(sa.select(Run))).scalar_one()
        assert stored.status is RunStatus.QUEUED
        assert stored.pipeline_version_id == version.id
        assert stored.params == {"day": "2026-08-28"}
        attempt = (await session.execute(sa.select(StepAttempt))).scalar_one()
        assert attempt.status is AttemptStatus.WAITING
        assert attempt.remote_handle == {"block_id": "storage.exists", "ref": "job-1"}
        assert attempt.gone_probes == 0


async def test_a_pipeline_name_is_unique(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    async with session_scope(factory) as session:
        session.add(Pipeline(code="only-once"))
    with pytest.raises(IntegrityError):
        async with session_scope(factory) as session:
            session.add(Pipeline(code="only-once"))


def _compare(connection: sa.Connection) -> list[object]:
    """Diff one live connection's schema against the ORM metadata."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    context = MigrationContext.configure(connection, opts={"compare_type": True, "include_schemas": False})
    return list(compare_metadata(context, Base.metadata))


async def metadata_drift(engine: AsyncEngine) -> list[object]:
    """Compare a migrated database against the ORM metadata, and say what differs."""
    async with engine.connect() as connection:
        return await connection.run_sync(_compare)


async def test_the_migrations_leave_no_drift_against_the_models_on_sqlite(sqlite_settings: Settings) -> None:
    await migrations.upgrade_async(settings=sqlite_settings)
    engine = create_engine(sqlite_settings)
    try:
        assert await metadata_drift(engine) == []
    finally:
        await engine.dispose()
