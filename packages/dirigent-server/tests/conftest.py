"""Fixtures the API tests share: a throwaway instance, and a client that is logged in."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from dirigent_client.enums import UserRole
from dirigent_core import telemetry
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_server import create_app

USERNAME = "tester"
OPERATOR = "an-operator"
VIEWER = "a-viewer"
PASSWORD = "a test password"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance pointed at a throwaway database, artifact root, and secret key."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        enabled_unsafe_blocks=["shell.run"],
    )


@pytest.fixture
def admin_token(settings: Settings) -> str:
    """Create the schema and one admin account, and return a bearer token for it."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = create_session_factory(engine)
            async with session_scope(sessions) as session:
                user = await create_user(session, USERNAME, PASSWORD, role=UserRole.ADMIN)
                issued = await issue_token(session, user, name="tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
def anonymous(settings: Settings, admin_token: str) -> Iterator[TestClient]:
    """A client carrying no credential at all."""
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def client(settings: Settings, admin_token: str) -> Iterator[TestClient]:
    """A client authenticated as an admin through a bearer token."""
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        yield client


@pytest.fixture
def operator_token(settings: Settings, admin_token: str) -> str:
    """Create a second, non-admin account and return a bearer token for it."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            sessions = create_session_factory(engine)
            async with session_scope(sessions) as session:
                user = await create_user(session, OPERATOR, PASSWORD, role=UserRole.OPERATOR)
                issued = await issue_token(session, user, name="operator-tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
def operator(settings: Settings, operator_token: str) -> Iterator[TestClient]:
    """A client authenticated as an operator."""
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {operator_token}"}) as client:
        yield client


@pytest.fixture
def viewer_token(settings: Settings, admin_token: str) -> str:
    """Create a read-only account and return a bearer token for it."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            sessions = create_session_factory(engine)
            async with session_scope(sessions) as session:
                user = await create_user(session, VIEWER, PASSWORD, role=UserRole.VIEWER)
                issued = await issue_token(session, user, name="viewer-tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
def viewer(settings: Settings, viewer_token: str) -> Iterator[TestClient]:
    """A client authenticated as a viewer."""
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {viewer_token}"}) as client:
        yield client


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """Give the API a real tracer that keeps its spans in memory, and hand them over."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    yield exporter
