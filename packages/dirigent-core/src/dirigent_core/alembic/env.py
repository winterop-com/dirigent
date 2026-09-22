"""Alembic environment: one migration history that runs on both PostgreSQL and SQLite."""

import asyncio

from alembic import context
from sqlalchemy import Connection

from dirigent_core.config import get_settings
from dirigent_core.database import create_engine
from dirigent_core.models import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    """Resolve the URL to migrate: the Alembic config wins, then the instance settings."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL for the configured URL without connecting to a database."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an established synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open the engine on the URL to migrate and drive the migrations through it.

    The engine is the instance's own, so this path opens SQLite with the pragmas every other
    connection in the process is configured with.
    """
    engine = create_engine(get_settings().model_copy(update={"database_url": database_url()}))
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run the migrations against a live database."""
    connectable = config.attributes.get("connection", None)
    if isinstance(connectable, Connection):
        do_run_migrations(connectable)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
