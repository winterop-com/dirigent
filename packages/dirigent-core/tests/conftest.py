"""Fixtures the engine tests share: a throwaway database, a plugin host, and an engine."""

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_core import telemetry
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory
from dirigent_core.engine import EngineServices
from dirigent_core.engine.executor import Engine
from dirigent_core.models import Base
from dirigent_core.plugins import PluginHost
from engineblocks import EngineTestPlugin, reset_blocks


@pytest.fixture(autouse=True)
def _forget_block_history() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Leave the shared test blocks with no memory of the previous test."""
    reset_blocks()
    yield
    reset_blocks()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Instance settings pointed at a throwaway database and artifact root."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        lease=timedelta(seconds=30),
        lost_job_max_gone=3,
    )


@pytest.fixture
def host() -> PluginHost:
    """A plugin host carrying only the blocks the engine tests drive."""
    return PluginHost({"engine-tests": EngineTestPlugin().contribute()})


@pytest.fixture
def services(settings: Settings, host: PluginHost) -> EngineServices:
    """The services every engine path shares."""
    return EngineServices.build(settings, host)


@pytest.fixture
async def db_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A database created from the ORM metadata, disposed when the test ends."""
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory the engine and the tests share."""
    return create_session_factory(db_engine)


@pytest.fixture
def engine(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> Engine:
    """An engine bound to the throwaway database, leasing as a named test worker."""
    return Engine(sessions, services, owner="worker-under-test")


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """Give the module a real tracer that keeps its spans in memory, and hand them over.

    A test reads the trace itself rather than a collector's view of it, so what it asserts
    is the parentage the exporter would have sent.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    yield exporter
