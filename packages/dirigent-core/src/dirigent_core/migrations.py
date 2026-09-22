"""Programmatic Alembic access, so the CLI, the server, and the tests drive one migration history."""

import asyncio
import io
from collections.abc import Iterable, Iterator
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from dirigent_core.config import Settings, get_settings
from dirigent_core.database import create_engine
from dirigent_core.models import Base

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


class DifferenceKind(StrEnum):
    """What one difference between a live database and the models is."""

    MISSING_TABLE = "missing_table"
    """The models declare a table the database has not got."""

    MISSING_COLUMN = "missing_column"
    """A declared table is there, without a column the models give it."""

    EXTRA_COLUMN = "extra_column"
    """A declared table carries a column the models do not declare."""

    CHANGED = "changed"
    """A declared table differs some other way: a column's type, an index, a constraint."""


#: How each kind reads after the table or column it is about.
_WORDING: Final[dict[DifferenceKind, str]] = {
    DifferenceKind.MISSING_TABLE: "missing",
    DifferenceKind.MISSING_COLUMN: "missing",
    DifferenceKind.EXTRA_COLUMN: "unexpected",
    DifferenceKind.CHANGED: "changed",
}


class SchemaDifference(BaseModel):
    """One way a live database differs from the models, named where it is."""

    model_config = ConfigDict(frozen=True)

    kind: DifferenceKind
    """What the difference is."""

    table: str
    """The table it is in."""

    column: str | None = None
    """The column it is in, when the difference is about one."""

    def __str__(self) -> str:
        """Render the difference as the phrase a refusal names it by."""
        where = f"{self.table}.{self.column}" if self.column else f"table {self.table}"
        return f"{where} {_WORDING[self.kind]}"


def _flattened(differences: Iterable[Any]) -> Iterator[tuple[Any, ...]]:
    """Walk Alembic's diff list, which groups several changes to one column in a nested list."""
    for entry in differences:
        if isinstance(entry, list):
            yield from entry
        else:
            yield entry


def _named(difference: tuple[Any, ...]) -> SchemaDifference | None:
    """Name the table and column one Alembic difference is about.

    A table the models do not declare is not a difference: the database may be shared, and
    nothing dirigent runs reads it.
    """
    what = difference[0]
    if what == "add_table":
        return SchemaDifference(kind=DifferenceKind.MISSING_TABLE, table=difference[1].name)
    if what == "remove_table":
        return None
    if what == "add_column":
        return SchemaDifference(kind=DifferenceKind.MISSING_COLUMN, table=difference[2], column=difference[3].name)
    if what == "remove_column":
        return SchemaDifference(kind=DifferenceKind.EXTRA_COLUMN, table=difference[2], column=difference[3].name)
    if what.startswith("modify_"):
        return SchemaDifference(kind=DifferenceKind.CHANGED, table=difference[2], column=difference[3])
    element = difference[1]
    table = element if isinstance(element, sa.Table) else getattr(element, "table", None)
    return None if table is None else SchemaDifference(kind=DifferenceKind.CHANGED, table=table.name)


def _compare(connection: Connection) -> list[SchemaDifference]:
    """Diff one live connection's schema against the ORM metadata."""
    context = MigrationContext.configure(connection, opts={"compare_type": True, "include_schemas": False})
    found = [_named(difference) for difference in _flattened(compare_metadata(context, Base.metadata))]
    differences = [one for one in found if one is not None]
    absent = {one.table for one in differences if one.kind is DifferenceKind.MISSING_TABLE}
    # Every index and constraint of a table that is not there restates the missing table.
    return [one for one in differences if one.kind is DifferenceKind.MISSING_TABLE or one.table not in absent]


async def schema_differences(engine: AsyncEngine) -> list[SchemaDifference]:
    """Say how the live database differs from the models, in one reflection.

    Empty means the database holds the schema this code was built against. Before 1.0 the
    baseline migration is edited in place, so a database an older dirigent wrote is stamped
    at the same revision and the stamp cannot answer this; reflection can.
    """
    async with engine.connect() as connection:
        return await connection.run_sync(_compare)
