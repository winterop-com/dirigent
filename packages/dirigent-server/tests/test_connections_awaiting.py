"""A connection created awaiting its secrets holds its settings alone, and nothing uses it until it is completed."""

from collections.abc import AsyncIterator
from typing import Any, ClassVar, Final

import httpx2
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from pydantic import BaseModel, SecretStr, model_validator

from dirigent_common import BlockModel, HealthReport
from dirigent_core.config import Settings
from dirigent_core.engine.executor import Engine
from dirigent_core.models import Connection
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


class EitherConfig(BlockModel):
    """A kind taking exactly one of two secrets, as a DHIS2 connection takes a token or a password."""

    endpoint: str
    api_token: SecretStr | None = None
    password: SecretStr | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "EitherConfig":
        if (self.api_token is None) == (self.password is None):
            raise ValueError("an either connection takes an api_token or a password, and not both")
        return self


class EitherKind(ConnectionKind):
    id: ClassVar[str] = "either"
    config_model: ClassVar[type[BaseModel]] = EitherConfig

    async def check(self, config: BaseModel) -> HealthReport:
        return HealthReport(healthy=True)


class PlainConfig(BlockModel):
    """A kind that declares no secret at all."""

    endpoint: str


class PlainKind(ConnectionKind):
    id: ClassVar[str] = "plain"
    config_model: ClassVar[type[BaseModel]] = PlainConfig

    async def check(self, config: BaseModel) -> HealthReport:
        return HealthReport(healthy=True)


class VaultPlugin:
    @extension
    def contribute(self) -> Contribution:
        return Contribution(connection_kinds=[VaultKind(), EitherKind(), PlainKind()])


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


def _client(app: FastAPI, token: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://testserver", headers={"Authorization": f"Bearer {token}"}
    )


@pytest.fixture
async def operator(app: FastAPI, operator_token: str) -> AsyncIterator[httpx2.AsyncClient]:
    async with _client(app, operator_token) as client:
        yield client


@pytest.fixture
async def viewer(app: FastAPI, viewer_token: str) -> AsyncIterator[httpx2.AsyncClient]:
    async with _client(app, viewer_token) as client:
        yield client


async def _create(client: httpx2.AsyncClient, code: str, kind: str, config: dict[str, Any]) -> httpx2.Response:
    return await client.post(f"{PREFIX}/connections", json={"code": code, "kind": kind, "config": config})


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


async def test_a_setting_the_model_refuses_whatever_the_secrets_is_refused_by_the_kinds_own_hint(
    admin: httpx2.AsyncClient, operator: httpx2.AsyncClient
) -> None:
    for client in (admin, operator):
        refused = await _awaiting(client, "local-db", "sql", {"url": "sqlite:////tmp/x.db"})
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "server.connection_config_invalid"
        assert "names no driver" in refused.json()["detail"]
        assert "sqlite+aiosqlite" in refused.json()["detail"]
    assert (await admin.get(f"{PREFIX}/connections")).json()["items"] == []


async def test_a_kind_taking_one_secret_of_several_awaits_it_though_all_together_are_refused(
    admin: httpx2.AsyncClient,
) -> None:
    created = await _awaiting(admin, "either", "either", {"endpoint": "https://either.invalid"})
    assert created.status_code == 201, created.text
    assert created.json()["awaiting_secrets"] is True


async def test_a_secret_the_settings_do_not_need_is_not_awaited(operator: httpx2.AsyncClient) -> None:
    created = await _create(operator, "local-db", "sql", {"url": "sqlite+aiosqlite:////tmp/x.db"})
    assert created.status_code == 201, created.text
    assert created.json()["awaiting_secrets"] is False, "sqlite opens with no password"


async def test_a_check_is_refused_until_a_person_completes_it(admin: httpx2.AsyncClient) -> None:
    await _awaiting(admin, "vault", "vault", {"endpoint": "https://vault.invalid"})
    refused = await admin.post(f"{PREFIX}/connections/vault/$check")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "secret.connection_awaiting_secrets"
    assert "vault holds its settings and awaits its secrets (password, api_token)" in refused.json()["detail"]
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
    assert (await _create(admin, "svc", "http", {"base_url": "http://127.0.0.1:9"})).status_code == 201
    async with app.state.session_factory() as session:
        await session.execute(sa.update(Connection).values(awaiting_secrets=True))
        await session.commit()
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


async def test_an_operator_creates_a_connection_awaiting_its_secrets_whatever_it_asked(
    operator: httpx2.AsyncClient,
) -> None:
    vault = await _create(operator, "vault", "vault", {"endpoint": "https://vault.invalid", "username": "ops"})
    assert vault.status_code == 201, vault.text
    assert vault.json()["awaiting_secrets"] is True

    slack = await _create(operator, "ops-slack", "slack", {"channel": "#ops"})
    assert slack.status_code == 201, slack.text
    assert slack.json()["awaiting_secrets"] is True, "slack requires a credential and was given none"


async def test_an_operator_creates_a_plain_http_connection_complete(operator: httpx2.AsyncClient) -> None:
    """A kind whose credential is optional, given none, is whole and usable at once."""
    web = await _create(operator, "web", "http", {"base_url": "https://svc.invalid", "bearer_token": None})
    assert web.status_code == 201, web.text
    assert web.json()["awaiting_secrets"] is False


async def test_an_operator_creates_a_kind_with_no_secret_complete(
    operator: httpx2.AsyncClient, admin: httpx2.AsyncClient
) -> None:
    plain = await _create(operator, "plain", "plain", {"endpoint": "https://plain.invalid"})
    assert plain.status_code == 201, plain.text
    assert plain.json()["awaiting_secrets"] is False
    assert (await admin.post(f"{PREFIX}/connections/plain/$check")).json()["healthy"] is True


async def test_an_operator_sending_a_secret_is_refused_by_name_and_nothing_is_stored(
    operator: httpx2.AsyncClient,
) -> None:
    refused = await _create(operator, "vault", "vault", {"endpoint": "https://vault.invalid", "api_token": TOKEN})
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "server.secrets_need_admin"
    assert "api_token" in refused.json()["detail"]
    assert TOKEN not in refused.text
    assert (await operator.get(f"{PREFIX}/connections")).json()["items"] == []


async def test_an_operator_cannot_supply_a_secret_through_an_update_and_a_viewer_creates_nothing(
    operator: httpx2.AsyncClient, viewer: httpx2.AsyncClient
) -> None:
    assert (await _create(operator, "vault", "vault", {"endpoint": "https://vault.invalid"})).status_code == 201
    patched = await operator.patch(
        f"{PREFIX}/connections/vault", json={"config": {"endpoint": "https://vault.invalid", "api_token": TOKEN}}
    )
    assert patched.status_code == 403, patched.text
    assert TOKEN not in patched.text
    assert (await operator.delete(f"{PREFIX}/connections/vault")).status_code == 403
    assert (await operator.post(f"{PREFIX}/connections/vault/$check")).status_code == 403
    assert (await _create(viewer, "plain", "plain", {"endpoint": "https://plain.invalid"})).status_code == 403


async def test_an_admin_still_creates_a_whole_connection_with_its_secret(admin: httpx2.AsyncClient) -> None:
    made = await _create(admin, "vault", "vault", {"endpoint": "https://vault.invalid", "api_token": TOKEN})
    assert made.status_code == 201, made.text
    assert (made.json()["awaiting_secrets"], made.json()["config"]["api_token"]) == (False, "***")
