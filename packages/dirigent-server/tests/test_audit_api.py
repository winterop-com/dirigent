"""The audit trail: every administrative change is journalled and logged, by whom, and never with a value."""

import asyncio
import json
import logging
from collections.abc import Generator, MutableMapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import AuditEntry
from tests_support import DOCUMENT, apply_document


@contextmanager
def capture_info() -> Generator[list[MutableMapping[str, Any]]]:
    """Capture structured log events at INFO and up, whatever level an earlier test configured."""
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
    try:
        with capture_logs() as logged:
            yield logged
    finally:
        structlog.configure(**saved)


PREFIX = "/api/v1"

SECRET = "super-secret-value"

ROTATED = "another-secret-value"


def entries(client: TestClient, **params: str | int) -> list[dict[str, Any]]:
    """Read the trail through the API, newest first."""
    response = client.get(f"{PREFIX}/audit", params=params)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def stored(settings: Settings) -> list[AuditEntry]:
    """Read every journal row straight from the database, oldest first."""

    async def read() -> list[AuditEntry]:
        engine = create_engine(settings)
        try:
            async with session_scope(create_session_factory(engine)) as session:
                return list((await session.execute(sa.select(AuditEntry).order_by(AuditEntry.id))).scalars())
        finally:
            await engine.dispose()

    return asyncio.run(read())


def create_connection(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/connections",
        json={
            "code": "ops-api",
            "kind": "http",
            "config": {"base_url": "https://ops.example.org", "bearer_token": SECRET},
        },
    )
    assert created.status_code == 201, created.text


def test_a_secret_update_records_the_field_name_and_nothing_of_the_value(
    client: TestClient, settings: Settings
) -> None:
    create_connection(client)
    with capture_info() as logged:
        updated = client.patch(
            f"{PREFIX}/connections/ops-api",
            json={"config": {"base_url": "https://ops.example.org", "bearer_token": ROTATED}},
        )
    assert updated.status_code == 200, updated.text

    newest = entries(client, subject_kind="connection")[0]
    assert newest["action"] == "updated"
    assert newest["subject_code"] == "ops-api"
    assert newest["fields"] == ["bearer_token"]

    rows = stored(settings)
    journal = json.dumps(
        [{column.name: str(getattr(row, column.name)) for column in AuditEntry.__table__.columns} for row in rows]
    )
    assert SECRET not in journal and ROTATED not in journal
    lines = [line for line in logged if line.get("subject_kind") == "connection"]
    assert [line["action"] for line in lines] == ["updated"]
    assert lines[0]["fields"] == ["bearer_token"]
    assert SECRET not in json.dumps(logged, default=str) and ROTATED not in json.dumps(logged, default=str)


def test_an_update_that_keeps_the_secret_by_its_marker_names_only_what_changed(client: TestClient) -> None:
    create_connection(client)
    kept = client.patch(
        f"{PREFIX}/connections/ops-api",
        json={"name": "Ops", "config": {"base_url": "https://ops2.example.org", "bearer_token": "***"}},
    )
    assert kept.status_code == 200, kept.text
    assert entries(client, subject_kind="connection", action="updated")[0]["fields"] == ["base_url", "name"]


def test_a_token_names_itself_and_its_prefix_on_what_it_changed(client: TestClient, admin_token: str) -> None:
    create_connection(client)
    entry = entries(client, subject="ops-api")[0]
    assert entry["action"] == "created"
    assert entry["actor_username"] == "tester"
    assert entry["actor_token"] == "tests"
    assert entry["actor_token_prefix"] == admin_token[:8]
    assert entry["actor_label"] == "tester (token tests)"


def test_a_change_that_is_refused_leaves_no_entry(client: TestClient) -> None:
    refused = client.post(f"{PREFIX}/connections", json={"code": "broken", "kind": "http", "config": {}})
    assert refused.status_code == 422
    assert entries(client, subject="broken") == []


def test_a_connection_delete_is_recorded(client: TestClient) -> None:
    create_connection(client)
    assert client.delete(f"{PREFIX}/connections/ops-api").status_code == 204
    assert [entry["action"] for entry in entries(client, subject="ops-api")] == ["deleted", "created"]


def test_token_creation_and_revocation_are_recorded_against_the_account(client: TestClient) -> None:
    created = client.post(f"{PREFIX}/tokens", json={"name": "mcp-trial"}).json()
    with capture_info() as logged:
        assert client.delete(f"{PREFIX}/tokens/{created['id']}").status_code == 204
    trail = entries(client, subject_kind="token", subject="mcp-trial")
    assert [entry["action"] for entry in trail] == ["revoked", "created"]
    assert {entry["parent_code"] for entry in trail} == {"tester"}
    assert any(line.get("action") == "revoked" and line.get("subject") == "mcp-trial" for line in logged)


def test_an_account_lifecycle_is_recorded_without_its_password(client: TestClient) -> None:
    password = "a long enough password"
    assert (
        client.post(f"{PREFIX}/users", json={"username": "ola", "password": password, "role": "viewer"}).status_code
        == 201
    )
    assert client.patch(f"{PREFIX}/users/ola", json={"role": "operator", "name": "Ola"}).status_code == 200
    assert client.post(f"{PREFIX}/users/ola/$deactivate").status_code == 200
    assert client.post(f"{PREFIX}/users/ola/$activate").status_code == 200
    reset = client.post(f"{PREFIX}/users/ola/$reset-password", json={"password": "yet another password"})
    assert reset.status_code == 204
    trail = entries(client, subject_kind="user", subject="ola")
    assert [entry["action"] for entry in reversed(trail)] == [
        "created",
        "role_changed",
        "updated",
        "deactivated",
        "activated",
        "password_reset",
    ]
    assert password not in json.dumps(trail)


def test_pipeline_and_schedule_changes_are_recorded(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    apply_document(client, DOCUMENT)
    apply_document(client, DOCUMENT.replace("goodbye", "farewell"))
    assert client.post(f"{PREFIX}/pipelines/api-demo/$deactivate").status_code == 200
    client.post(f"{PREFIX}/pipelines/api-demo/triggers/schedules", json={"code": "nightly", "cron": "0 3 * * *"})
    assert client.post(f"{PREFIX}/pipelines/api-demo/triggers/schedules/nightly/$pause").status_code == 200
    pipeline = entries(client, subject_kind="pipeline")
    assert [entry["action"] for entry in reversed(pipeline)] == ["created", "updated", "deactivated"]
    assert pipeline[1]["fields"] == ["steps"]
    schedule = entries(client, subject_kind="schedule")
    assert [entry["action"] for entry in reversed(schedule)] == ["created", "paused"]
    assert {entry["parent_code"] for entry in schedule} == {"api-demo"}
    assert client.delete(f"{PREFIX}/pipelines/api-demo").status_code == 204
    assert entries(client, subject_kind="pipeline", action="deleted")[0]["subject_code"] == "api-demo"


def test_alert_rules_and_schemas_are_recorded(client: TestClient) -> None:
    client.post(f"{PREFIX}/alert-rules", json={"code": "page-ops", "event": "run_failed"})
    client.patch(f"{PREFIX}/alert-rules/page-ops", json={"paused": True, "template": "failed: {{ pipeline }}"})
    client.delete(f"{PREFIX}/alert-rules/page-ops")
    rules = entries(client, subject_kind="alert_rule")
    assert [(entry["action"], entry["fields"]) for entry in reversed(rules)] == [
        ("created", []),
        ("updated", ["template"]),
        ("paused", []),
        ("deleted", []),
    ]
    client.post(f"{PREFIX}/schemas", json={"code": "person", "body": {"type": "object"}})
    client.patch(f"{PREFIX}/schemas/person", json={"name": "Person"})
    client.delete(f"{PREFIX}/schemas/person")
    schemas = entries(client, subject_kind="schema")
    assert [(entry["action"], entry["fields"]) for entry in reversed(schemas)] == [
        ("created", []),
        ("updated", ["name"]),
        ("deleted", []),
    ]


def test_the_trail_filters_and_pages(client: TestClient) -> None:
    for name in ("one", "two", "three"):
        client.post(f"{PREFIX}/tokens", json={"name": name})
    first = client.get(f"{PREFIX}/audit", params={"subject_kind": "token", "limit": 2}).json()
    assert [entry["subject_code"] for entry in first["items"]] == ["three", "two"]
    rest = client.get(f"{PREFIX}/audit", params={"subject_kind": "token", "limit": 2, "after": first["next"]}).json()
    assert [entry["subject_code"] for entry in rest["items"]] == ["one", "tests"]
    assert rest["next"] is None
    assert entries(client, actor="tester", subject_kind="token")
    assert entries(client, actor="nobody") == []
    later = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    assert entries(client, since=later) == []
    assert len(entries(client, until=later, subject_kind="token")) == 4


def test_only_an_admin_reads_the_trail(operator: TestClient, viewer: TestClient, anonymous: TestClient) -> None:
    assert operator.get(f"{PREFIX}/audit").status_code == 403
    assert viewer.get(f"{PREFIX}/audit").status_code == 403
    assert anonymous.get(f"{PREFIX}/audit").status_code == 401


def test_an_operator_change_names_the_operator(operator: TestClient, client: TestClient) -> None:
    apply_document(operator, DOCUMENT)
    entry = entries(client, subject_kind="pipeline")[0]
    assert entry["actor_username"] == "an-operator"
    assert entry["actor_label"] == "an-operator (token operator-tests)"


def test_supplying_the_secrets_a_connection_awaits_is_its_own_action(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/connections",
        json={"code": "ops-slack", "kind": "slack", "config": {"channel": "#ops"}, "awaiting_secrets": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["awaiting_secrets"] is True
    supplied = client.patch(
        f"{PREFIX}/connections/ops-slack", json={"config": {"channel": "#ops", "bot_token": SECRET}}
    )
    assert supplied.status_code == 200, supplied.text
    newest = entries(client, subject="ops-slack")[0]
    assert (newest["action"], newest["fields"]) == ("secrets_supplied", ["bot_token"])
    assert SECRET not in json.dumps(newest)
