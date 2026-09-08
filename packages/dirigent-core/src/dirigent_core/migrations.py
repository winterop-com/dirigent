"""Programmatic Alembic access, so the CLI, the server, and the tests drive one migration history."""

import asyncio
import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

from dirigent_core.config import Settings, get_settings
from dirigent_core.database import create_engine

#: The migration scripts ship inside the package, so no working directory is assumed.
ALEMBIC_DIRECTORY = Path(__file__).resolve().parent / "alembic"


def alembic_config(settings: Settings | None = None) -> Config:
    """Build an Alembic config pointing at the packaged migrations and the configured database."""
    resolved = settings or get_settings()
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIRECTORY))
    config.set_main_option("sqlalchemy.url", resolved.database_url)
    config.set_main_option("timezone", "UTC")
    return config


def _run_command(connection: Connection, name: str, revision: str, settings: Settings | None) -> None:
    """Run one Alembic command on an established synchronous connection."""
    config = alembic_config(settings)
    config.attributes["connection"] = connection
    getattr(command, name)(config, revision)


async def _with_connection(name: str, revision: str, settings: Settings | None) -> None:
    """Open the async engine and hand a synchronous connection to Alembic."""
    engine = create_engine(settings or get_settings())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_run_command, name, revision, settings)
    finally:
        await engine.dispose()


async def upgrade_async(revision: str = "head", settings: Settings | None = None) -> None:
    """Bring the database up to a revision, creating the schema on an empty database."""
    await _with_connection("upgrade", revision, settings)


async def downgrade_async(revision: str, settings: Settings | None = None) -> None:
    """Take the database back to a revision."""
    await _with_connection("downgrade", revision, settings)


def _read_revision(connection: Connection) -> str | None:
    """Read the alembic_version stamp from an established connection."""
    return MigrationContext.configure(connection).get_current_revision()


async def current_revision_async(settings: Settings | None = None) -> str | None:
    """Read the revision the database is stamped with, or None when it has never been migrated."""
    engine = create_engine(settings or get_settings())
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_read_revision)
    finally:
        await engine.dispose()


def upgrade(revision: str = "head", settings: Settings | None = None) -> None:
    """Run an upgrade from synchronous code, such as the CLI."""
    asyncio.run(upgrade_async(revision, settings))


def downgrade(revision: str, settings: Settings | None = None) -> None:
    """Run a downgrade from synchronous code, such as the CLI."""
    asyncio.run(downgrade_async(revision, settings))


def current_revision(settings: Settings | None = None) -> str | None:
    """Read the current revision from synchronous code, such as the CLI."""
    return asyncio.run(current_revision_async(settings))


def head_revision(settings: Settings | None = None) -> str | None:
    """Read the newest revision the packaged migrations define."""
    return ScriptDirectory.from_config(alembic_config(settings)).get_current_head()


def history(settings: Settings | None = None) -> str:
    """Render the migration history as Alembic prints it, without touching the database."""
    config = alembic_config(settings)
    buffer = io.StringIO()
    config.stdout = buffer
    command.history(config, verbose=False)
    return buffer.getvalue()
