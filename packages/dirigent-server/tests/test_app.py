"""Tests for the application factory and the health probes."""

from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dirigent_core.config import Settings
from dirigent_server import create_app
from dirigent_server.logging import PACKAGE_LOGGER, get_logger


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"]


def test_the_probes_need_no_credential(anonymous: TestClient) -> None:
    assert anonymous.get("/health").status_code == 200
    assert anonymous.get("/health/ready").status_code == 200
    assert anonymous.get("/openapi.json").status_code == 200


def test_readiness_runs_the_registered_checks(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "checks": {"database": {"status": "healthy", "detail": None}}}


def test_readiness_fails_when_the_database_is_unreachable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    settings = Settings(database_url=f"sqlite+aiosqlite:///{blocker / 'dirigent.db'}")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"] == {"status": "unhealthy", "detail": "database is unreachable"}


def test_the_versioned_router_is_mounted(client: TestClient) -> None:
    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["name"] == "dirigent"
    assert response.json()["database"] == "sqlite"


def test_the_api_prefix_is_configurable(tmp_path: Path, admin_token: str, settings: Settings) -> None:
    moved = settings.model_copy(update={"api_prefix": "/api/v2"})
    headers = {"Authorization": f"Bearer {admin_token}"}
    with TestClient(create_app(moved), headers=headers) as client:
        assert client.get("/api/v2/system/info").status_code == 200
        assert client.get("/api/v1/system/info").status_code == 404


def test_the_openapi_document_is_generated(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    assert document["info"]["title"] == "dirigent"
    assert "/health" in document["paths"]


def test_the_bootstrap_admin_is_created_from_the_environment(tmp_path: Path, monkeypatch: object) -> None:
    from dirigent_core.auth import BOOTSTRAP_PASSWORD_ENV

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'boot.db'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )
    import asyncio

    from dirigent_core.database import create_engine
    from dirigent_core.models import Base

    async def schema() -> None:
        engine = create_engine(settings)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(schema())
    monkeypatch.setenv(BOOTSTRAP_PASSWORD_ENV, "a bootstrap password")  # type: ignore[attr-defined]
    with TestClient(create_app(settings)) as client:
        login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "a bootstrap password"})
    assert login.status_code == 200
    assert login.json()["username"] == "admin"


def test_the_server_re_exports_the_shared_logging_configuration() -> None:
    from dirigent_core.logging import get_logger as core_get_logger

    assert PACKAGE_LOGGER == "dirigent"
    assert get_logger is core_get_logger


def test_the_startup_directory_is_applied_and_a_broken_document_does_not_stop_the_boot(
    tmp_path: Path, admin_token: str, settings: Settings
) -> None:
    """A mounted directory seeds the instance at boot, one bad file loudly refused."""
    directory = tmp_path / "pipelines"
    directory.mkdir()
    (directory / "good.yaml").write_text(
        "format: dirigent/v1\ncode: seeded-at-boot\nsteps:\n  only:\n    block: value.const\n"
        "    config: { value: booted }\n"
    )
    (directory / "broken.yaml").write_text("{ not a document")
    booted = settings.model_copy(update={"apply_dir": directory})

    with TestClient(create_app(booted), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        listed = client.get("/api/v1/pipelines")
        assert listed.status_code == 200
        codes = [row["code"] for row in listed.json()["items"]]
        assert codes == ["seeded-at-boot"]
        version = client.get("/api/v1/pipelines/seeded-at-boot/versions").json()["items"][0]
        assert version["provenance_source"] == "directory"
