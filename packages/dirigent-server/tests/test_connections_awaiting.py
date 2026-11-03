"""A connection created awaiting its secrets holds its settings alone, and nothing uses it until it is completed."""

from collections.abc import AsyncIterator
from typing import Any, ClassVar, Final

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, SecretStr, model_validator

from dirigent_common import BlockModel, HealthReport
from dirigent_core.config import Settings
from dirigent_core.engine.executor import Engine
from dirigent_core.plugins import load_plugin_host
from dirigent_plugin import ConnectionKind, Contribution, extension
from dirigent_server import create_app

PREFIX: Final = "/api/v1"

TOKEN: Final = "DUMMY-vault-token-canary-0003"


class VaultConfig(BlockModel):
    """A kind the model refuses without a credential, as a DHIS2 connection is."""

    endpoint: str
    username: str | None = None
    password: SecretStr | None = None
    api_token: SecretStr | None = None

    @model_validator(mode="after")
    def _one_credential(self) -> "VaultConfig":
        if self.api_token is None and self.password is None:
            raise ValueError("a vault connection needs an api_token or a password")
        return self


class VaultKind(ConnectionKind):
    id: ClassVar[str] = "vault"
    config_model: ClassVar[type[BaseModel]] = VaultConfig

    async def check(self, config: BaseModel) -> HealthReport:
        return HealthReport(healthy=True, detail="answered")


class VaultPlugin:
    @extension
    def contribute(self) -> Contribution:
        return Contribution(connection_kinds=[VaultKind()])


@pytest.fixture
async def app(settings: Settings, admin_token: str) -> AsyncIterator[FastAPI]:
    built = create_app(settings, scheduler=False, host=load_plugin_host(extra={"vault": VaultPlugin()}))
    async with built.router.lifespan_context(built):
        yield built


@pytest.fixture
async def admin(app: FastAPI, admin_token: str) -> AsyncIterator[httpx2.AsyncClient]:
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://testserver", headers=headers
    ) as client:
        yield client


async def _awaiting(client: httpx2.AsyncClient, code: str, kind: str, config: dict[str, Any]) -> httpx2.Response:
    body = {"code": code, "kind": kind, "config": config, "awaiting_secrets": True}
    return await client.post(f"{PREFIX}/connections", json=body)


async def test_the_settings_are_stored_alone_and_every_read_says_it_awaits_its_secrets(
    admin: httpx2.AsyncClient,
) -> None:
    created = await _awaiting(admin, "vault", "vault", {"endpoint": "https://vault.invalid", "username": "ops"})
    assert created.status_code == 201, created.text
    made = created.json()
    assert made["awaiting_secrets"] is True
    assert made["config"] == {
        "endpoint": "https://vault.invalid",
        "username": "ops",
        "password": None,
        "api_token": None,
    }
    [listed] = (await admin.get(f"{PREFIX}/connections")).json()["items"]
    read = (await admin.get(f"{PREFIX}/connections/vault")).json()
    assert listed["awaiting_secrets"] is read["awaiting_secrets"] is True


async def test_a_secret_given_is_refused_by_name_without_its_value_and_nothing_is_stored(
    admin: httpx2.AsyncClient,
) -> None:
    refused = await _awaiting(admin, "vault", "vault", {"endpoint": "https://vault.invalid", "api_token": TOKEN})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "server.secrets_withheld"
    assert "api_token" in refused.json()["detail"]
    assert TOKEN not in refused.text
    assert (await admin.get(f"{PREFIX}/connections")).json()["items"] == []


async def test_a_setting_the_model_refuses_is_still_refused(admin: httpx2.AsyncClient) -> None:
    refused = await _awaiting(admin, "vault", "vault", {"username": "ops"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "server.connection_config_invalid"
    assert "endpoint" in refused.json()["detail"]


async def test_a_check_is_refused_until_a_person_completes_it(admin: httpx2.AsyncClient) -> None:
    await _awaiting(admin, "vault", "vault", {"endpoint": "https://vault.invalid"})
    refused = await admin.post(f"{PREFIX}/connections/vault/$check")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "secret.connection_awaiting_secrets"
    assert "dg connection set-secret vault" in refused.json()["detail"]
    assert (await admin.get(f"{PREFIX}/connections/vault")).json()["last_check_at"] is None

    still = await admin.patch(f"{PREFIX}/connections/vault", json={"config": {"endpoint": "https://vault.invalid"}})
    assert still.status_code == 422, "an update is validated whole"
    assert (await admin.get(f"{PREFIX}/connections/vault")).json()["awaiting_secrets"] is True

    completed = await admin.patch(
        f"{PREFIX}/connections/vault", json={"config": {"endpoint": "https://vault.invalid", "api_token": TOKEN}}
    )
    assert completed.status_code == 200, completed.text
    assert (completed.json()["awaiting_secrets"], completed.json()["config"]["api_token"]) == (False, "***")
    assert (await admin.post(f"{PREFIX}/connections/vault/$check")).json()["healthy"] is True


async def test_a_step_naming_it_is_refused_before_anything_is_sent(app: FastAPI, admin: httpx2.AsyncClient) -> None:
    assert (await _awaiting(admin, "svc", "http", {"base_url": "http://127.0.0.1:9"})).status_code == 201
    document = {
        "format": "dirigent/v1",
        "code": "uses",
        "steps": {"call": {"block": "http.request", "config": {"connection": "svc", "path": "/"}}},
    }
    applied = await admin.post(f"{PREFIX}/pipelines/$apply", json={"document": document, "paused": False})
    assert applied.status_code == 200, applied.text
    run_id = (await admin.post(f"{PREFIX}/pipelines/uses/$run", json={"params": {}})).json()["run_id"]
    engine = Engine(app.state.session_factory, app.state.services, owner="worker")
    while unit := await engine.claim():
        await engine.run_unit(unit)
    [attempt] = (await admin.get(f"{PREFIX}/runs/{run_id}/attempts")).json()["items"]
    assert (attempt["status"], attempt["error_code"]) == ("failed", "secret.connection_awaiting_secrets")
    assert attempt["error_params"]["connection"] == "svc"
