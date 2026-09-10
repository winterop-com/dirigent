"""The REST surface: what it lets through, what it refuses, and what it never reveals."""

import asyncio
import json
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import httpx2
import pytest
import sqlalchemy as sa
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from dirigent_client.enums import AttemptStatus, LogLevel, RunItemStatus, RunStatus, WorkerStatus
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import (
    Connection,
    LogEntry,
    PipelineVersion,
    Run,
    RunItem,
    StepAttempt,
    Worker,
    uuid7,
)
from dirigent_server.routes.auth import LOGIN_BUCKETS
from tests_support import DOCUMENT, apply_document

PREFIX = "/api/v1"

#: A second account, named once so every test that needs one says the same thing.
SECOND = {"username": "second", "password": "another password"}


def test_every_business_route_refuses_an_anonymous_request(anonymous: TestClient) -> None:
    for method, path in [
        ("get", "/pipelines"),
        ("post", "/pipelines/$apply"),
        ("get", "/runs"),
        ("get", "/connections"),
        ("get", "/schemas"),
        ("get", "/blocks"),
        ("get", "/workers"),
        ("get", "/users"),
        ("get", "/system/info"),
        ("get", "/auth/me"),
    ]:
        response = anonymous.request(method, f"{PREFIX}{path}", json={})
        assert response.status_code == 401, f"{method} {path} let an anonymous request through"
        assert "authentication required" in response.json()["detail"]


def test_a_bad_token_is_refused_like_no_token(anonymous: TestClient) -> None:
    response = anonymous.get(f"{PREFIX}/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


def test_logging_in_sets_a_session_cookie_that_authenticates(anonymous: TestClient) -> None:
    from tests_support import PASSWORD, USERNAME

    login = anonymous.post(f"{PREFIX}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["username"] == USERNAME
    assert "dirigent_session" in login.cookies
    assert anonymous.get(f"{PREFIX}/auth/me").status_code == 200
    assert anonymous.post(f"{PREFIX}/auth/logout").status_code == 204
    assert anonymous.get(f"{PREFIX}/auth/me").status_code == 401


def test_a_wrong_password_is_refused_without_saying_which_half_was_wrong(anonymous: TestClient) -> None:
    response = anonymous.post(f"{PREFIX}/auth/login", json={"username": "tester", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_whoami_says_which_credential_was_used(client: TestClient) -> None:
    body = client.get(f"{PREFIX}/auth/me").json()
    assert body["username"] == "tester"
    assert body["via"] == "api"
    assert body["token_name"] == "tests"


def test_a_token_can_be_created_listed_and_revoked(client: TestClient) -> None:
    created = client.post(f"{PREFIX}/tokens", json={"name": "ci"})
    assert created.status_code == 201
    secret = created.json()["token"]
    assert created.json()["prefix"] == secret[:8]
    listed = client.get(f"{PREFIX}/tokens").json()["items"]
    assert {token["name"] for token in listed} == {"tests", "ci"}
    assert all("token" not in token for token in listed)
    assert {token["username"] for token in listed} == {"tester"}
    assert client.delete(f"{PREFIX}/tokens/ci").status_code == 204
    assert client.delete(f"{PREFIX}/tokens/ci").status_code == 404


def test_the_catalog_is_served_and_filterable(client: TestClient) -> None:
    catalog = client.get(f"{PREFIX}/blocks").json()
    ids = {block["id"] for block in catalog["blocks"]}
    assert {"http.request", "http.ready", "storage.copy", "storage.exists", "shell.run"} <= ids
    assert "http" in {kind["id"] for kind in catalog["connection_kinds"]}
    sensors = client.get(f"{PREFIX}/blocks", params={"kind": "sensor"}).json()
    assert {block["id"] for block in sensors["blocks"]} == {
        "http.ready",
        "kafka.consume",
        "rabbitmq.consume",
        "storage.exists",
        "time.sleep",
        "time.window",
    }


def test_the_catalog_names_the_secret_fields_of_a_connection_kind(client: TestClient) -> None:
    kinds = {kind["id"]: kind for kind in client.get(f"{PREFIX}/blocks").json()["connection_kinds"]}
    assert kinds["http"]["secret_fields"] == ["bearer_token", "basic_password", "hmac_secret"]
    assert kinds["slack"]["secret_fields"] == ["webhook_url", "bot_token"]
    assert kinds["email"]["secret_fields"] == ["password"]
    assert kinds["kafka"]["secret_fields"] == ["password"]
    assert kinds["rabbitmq"]["secret_fields"] == ["password"]


def test_the_catalog_carries_the_group_each_block_declares(client: TestClient) -> None:
    catalog = client.get(f"{PREFIX}/blocks").json()
    groups = {block["id"]: block["group"] for block in catalog["blocks"]}
    assert groups == {
        "convert.arrow": "transform",
        "convert.std": "transform",
        "docker.build": "execute",
        "docker.compose.down": "execute",
        "docker.compose.up": "execute",
        "docker.run": "execute",
        "filter.jq": "transform",
        "git.checkout": "git",
        "http.ready": "http",
        "http.request": "http",
        "kafka.consume": "kafka",
        "kafka.produce": "kafka",
        "map.jq": "transform",
        "pipeline.run": "execute",
        "rabbitmq.consume": "rabbitmq",
        "shell.run": "execute",
        "sql.execute": "sql",
        "sql.query": "sql",
        "storage.copy": "storage",
        "storage.exists": "storage",
        "time.sleep": "time",
        "time.window": "time",
        "transform.jq": "transform",
        "validate.schema": "validate",
        "value.const": "value",
        "webhook.post": "webhook",
    }
    assert client.get(f"{PREFIX}/blocks/map.jq").json()["group"] == "transform"


def test_one_block_carries_the_schemas_a_form_is_built_from(client: TestClient) -> None:
    entry = client.get(f"{PREFIX}/blocks/storage.copy").json()
    assert entry["kind"] == "operator"
    assert entry["config_schema"]["required"] == ["source", "target"]
    assert client.get(f"{PREFIX}/blocks/nope.gone").status_code == 404


def test_a_connection_round_trips_with_its_secret_redacted(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/connections",
        json={
            "code": "ops-api",
            "kind": "http",
            "config": {"base_url": "https://ops.example.org", "bearer_token": "super-secret"},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["config"]["base_url"] == "https://ops.example.org"
    assert body["config"]["bearer_token"] == "***"
    assert body["secret_fields"] == ["bearer_token", "basic_password", "hmac_secret"]
    assert "super-secret" not in created.text

    listed = client.get(f"{PREFIX}/connections").json()["items"]
    assert [row["code"] for row in listed] == ["ops-api"]
    assert "super-secret" not in client.get(f"{PREFIX}/connections/ops-api").text


def test_a_slack_channel_is_minted_and_sealed_like_any_other_connection(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/connections",
        json={"code": "ops-slack", "kind": "slack", "config": {"bot_token": "xoxb-super-secret", "channel": "#ops"}},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["config"]["channel"] == "#ops"
    assert body["config"]["bot_token"] == "***"
    assert body["config"]["webhook_url"] is None
    assert body["secret_fields"] == ["webhook_url", "bot_token"]
    assert "xoxb-super-secret" not in created.text
    assert "xoxb-super-secret" not in client.get(f"{PREFIX}/connections/ops-slack").text


def test_an_incoming_webhook_is_sealed_because_it_is_the_credential(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/connections",
        json={"code": "ops-hook", "kind": "slack", "config": {"webhook_url": "https://hooks.slack.test/T/B/xxx"}},
    )
    assert created.status_code == 201
    assert created.json()["config"]["webhook_url"] == "***"
    assert "hooks.slack.test" not in created.text


def test_an_email_channel_seals_its_submission_password(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/connections",
        json={
            "code": "ops-mail",
            "kind": "email",
            "config": {
                "host": "smtp.example.org",
                "username": "postmaster",
                "password": "super-secret",
                "from_address": "dirigent@example.org",
                "to": ["oncall@example.org"],
            },
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["config"]["host"] == "smtp.example.org"
    assert body["config"]["to"] == ["oncall@example.org"]
    assert body["config"]["password"] == "***"
    assert body["secret_fields"] == ["password"]
    assert "super-secret" not in created.text


def test_a_channel_config_the_kind_refuses_never_becomes_a_connection(client: TestClient) -> None:
    both = {"webhook_url": "https://hooks.slack.test/T/B/xxx", "bot_token": "xoxb-x", "channel": "#ops"}
    refused = client.post(f"{PREFIX}/connections", json={"code": "x", "kind": "slack", "config": both})
    assert refused.status_code == 422
    assert client.get(f"{PREFIX}/connections").json()["items"] == []


def test_a_connection_is_validated_against_its_kind(client: TestClient) -> None:
    assert client.post(f"{PREFIX}/connections", json={"code": "x", "kind": "http", "config": {}}).status_code == 422
    assert client.post(f"{PREFIX}/connections", json={"code": "x", "kind": "nope", "config": {}}).status_code == 422


def test_a_schema_reads_its_identity_from_its_own_keywords(client: TestClient) -> None:
    body = {
        "$id": "org-unit",
        "title": "Organisation unit",
        "description": "An org unit read.",
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}},
    }
    created = client.post(f"{PREFIX}/schemas", json={"body": body})
    assert created.status_code == 201
    assert created.json()["code"] == "org-unit"
    assert created.json()["name"] == "Organisation unit"
    assert client.get(f"{PREFIX}/schemas/org-unit").json()["body"]["type"] == "object"
    assert "org-unit" in {row["code"] for row in client.get(f"{PREFIX}/schemas").json()["items"]}
    assert client.delete(f"{PREFIX}/schemas/org-unit").status_code == 204
    assert client.get(f"{PREFIX}/schemas/org-unit").status_code == 404


def test_a_body_that_is_not_a_valid_schema_is_refused(client: TestClient) -> None:
    refused = client.post(f"{PREFIX}/schemas", json={"code": "bad", "body": {"type": "not-a-type"}})
    assert refused.status_code == 422
    assert "valid JSON Schema" in refused.json()["detail"]


def test_a_schema_naming_no_code_any_way_is_refused(client: TestClient) -> None:
    refused = client.post(f"{PREFIX}/schemas", json={"body": {"type": "object"}})
    assert refused.status_code == 422


def test_two_connections_may_not_share_a_name(client: TestClient) -> None:
    payload: dict[str, Any] = {"code": "ops-api", "kind": "http", "config": {"base_url": "https://ops.example.org"}}
    assert client.post(f"{PREFIX}/connections", json=payload).status_code == 201
    assert client.post(f"{PREFIX}/connections", json=payload).status_code == 409


def test_a_connection_can_be_updated_and_deleted(client: TestClient) -> None:
    payload: dict[str, Any] = {"code": "ops-api", "kind": "http", "config": {"base_url": "https://ops.example.org"}}
    client.post(f"{PREFIX}/connections", json=payload)
    updated = client.patch(
        f"{PREFIX}/connections/ops-api",
        json={"description": "operations", "config": {"base_url": "https://ops2.example.org"}},
    )
    assert updated.status_code == 200
    assert updated.json()["config"]["base_url"] == "https://ops2.example.org"
    assert updated.json()["description"] == "operations"
    assert client.delete(f"{PREFIX}/connections/ops-api").status_code == 204
    assert client.get(f"{PREFIX}/connections/ops-api").status_code == 404


def test_a_connection_a_rule_delivers_through_may_not_be_deleted(client: TestClient) -> None:
    client.post(
        f"{PREFIX}/connections",
        json={"code": "ops-webhook", "kind": "webhook", "config": {"url": "https://ops.example.org/hooks"}},
    )
    declared = client.post(
        f"{PREFIX}/alert-rules",
        json={"code": "page-ops", "event": "run_failed", "notifier": "webhook", "connection": "ops-webhook"},
    )
    assert declared.status_code == 201
    refused = client.delete(f"{PREFIX}/connections/ops-webhook")
    assert refused.status_code == 409
    assert "still referenced" in refused.json()["detail"]
    assert client.get(f"{PREFIX}/connections/ops-webhook").status_code == 200


def test_a_rule_carries_the_connection_it_delivers_through(client: TestClient) -> None:
    client.post(
        f"{PREFIX}/connections",
        json={"code": "ops-webhook", "kind": "webhook", "config": {"url": "https://ops.example.org/hooks"}},
    )
    client.post(
        f"{PREFIX}/alert-rules",
        json={"code": "page-ops", "event": "run_failed", "notifier": "webhook", "connection": "ops-webhook"},
    )
    listed = client.get(f"{PREFIX}/alert-rules").json()["items"]
    assert listed[0]["connection"] == "ops-webhook"
    assert listed[0]["paused"] is False


def test_a_rule_is_paused_and_resumed_on_the_row(client: TestClient) -> None:
    client.post(f"{PREFIX}/alert-rules", json={"code": "page-ops", "event": "run_failed", "notifier": "log"})
    paused = client.patch(f"{PREFIX}/alert-rules/page-ops", json={"paused": True})
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert client.get(f"{PREFIX}/alert-rules").json()["items"][0]["paused"] is True
    resumed = client.patch(f"{PREFIX}/alert-rules/page-ops", json={"paused": False})
    assert resumed.json()["paused"] is False


def test_pausing_a_rule_that_is_not_there_is_a_404(client: TestClient) -> None:
    assert client.patch(f"{PREFIX}/alert-rules/nothing", json={"paused": True}).status_code == 404


def test_a_notification_is_read_on_its_own_and_put_back_on_the_queue(client: TestClient) -> None:
    queued = client.post(f"{PREFIX}/alert-rules/$test", json={"notifier": "log", "subject": "a test"})
    assert queued.status_code == 202
    notification_id = queued.json()["notification_id"]
    read = client.get(f"{PREFIX}/notifications/{notification_id}")
    assert read.status_code == 200
    assert read.json()["subject"] == "a test"
    assert read.json()["max_attempts"] >= 1
    assert read.json()["rule"] is None, "a test message is raised by no rule"
    again = client.post(f"{PREFIX}/notifications/{notification_id}/$retry")
    assert again.status_code == 200
    assert again.json()["status"] == "pending"
    assert again.json()["attempt"] == 0


def test_the_queue_narrows_by_status_and_by_notifier(client: TestClient) -> None:
    client.post(f"{PREFIX}/alert-rules/$test", json={"notifier": "log", "subject": "a test"})
    assert len(client.get(f"{PREFIX}/notifications", params={"status": "pending"}).json()["items"]) == 1
    assert client.get(f"{PREFIX}/notifications", params={"status": "sent"}).json()["items"] == []
    assert len(client.get(f"{PREFIX}/notifications", params={"notifier": "log"}).json()["items"]) == 1
    assert client.get(f"{PREFIX}/notifications", params={"notifier": "slack"}).json()["items"] == []


def test_checking_a_connection_reports_rather_than_raises(client: TestClient) -> None:
    client.post(
        f"{PREFIX}/connections",
        json={
            "code": "unreachable",
            "kind": "http",
            "config": {"base_url": "http://127.0.0.1:9", "timeout": "50ms"},
        },
    )
    report = client.post(f"{PREFIX}/connections/unreachable/$check")
    assert report.status_code == 200
    assert report.json()["healthy"] is False
    assert report.json()["detail"]
    assert client.get(f"{PREFIX}/connections/unreachable").json()["last_check_healthy"] is False


def test_applying_a_document_creates_a_pipeline(client: TestClient) -> None:
    result = apply_document(client, DOCUMENT)
    assert result["plan"]["action"] == "create"
    assert result["version"] == 1
    listed = client.get(f"{PREFIX}/pipelines").json()["items"]
    assert [row["code"] for row in listed] == ["api-demo"]
    assert listed[0]["current_version"] == 1


def test_a_document_carrying_its_own_connections_is_refused_and_writes_nothing(client: TestClient) -> None:
    """An applied document is stored, versioned and exported; a credential must not ride along."""
    carried = yaml.safe_load(DOCUMENT)
    carried["connections"] = {"demo": {"kind": "http", "config": {"base_url": "https://example.org"}}}
    response = client.post(f"{PREFIX}/pipelines/$apply", json={"document": carried})
    assert response.status_code == 422, response.text
    detail = str(response.json()["detail"])
    assert "demo" in detail and "dg connection create" in detail

    assert client.get(f"{PREFIX}/pipelines").json()["items"] == [], "nothing was written"
    assert client.get(f"{PREFIX}/connections").json()["items"] == [], "and no connection was created"


def test_a_document_carrying_its_own_schemas_is_refused_and_writes_nothing(client: TestClient) -> None:
    """A carried schema would land in every version of the pipeline; a shared instance holds its own."""
    carried = yaml.safe_load(DOCUMENT)
    carried["schemas"] = {"ou-shape": {"type": "object", "required": ["id"]}}
    response = client.post(f"{PREFIX}/pipelines/$apply", json={"document": carried})
    assert response.status_code == 422, response.text
    detail = str(response.json()["detail"])
    assert "ou-shape" in detail and "dg schema create" in detail

    assert client.get(f"{PREFIX}/pipelines").json()["items"] == [], "nothing was written"


def test_prune_deactivates_directory_absentees_and_nothing_else(client: TestClient) -> None:
    """The reconcile half of a directory apply, over the wire."""
    gone = yaml.safe_load(DOCUMENT)
    gone["code"] = "gone-from-directory"
    kept = yaml.safe_load(DOCUMENT)
    kept["code"] = "kept-in-directory"
    authored = yaml.safe_load(DOCUMENT)
    authored["code"] = "authored-elsewhere"
    for document in (gone, kept):
        applied = client.post(f"{PREFIX}/pipelines/$apply", json={"document": document, "source": "directory"})
        assert applied.status_code == 200, applied.text
    assert client.post(f"{PREFIX}/pipelines/$apply", json={"document": authored}).status_code == 200

    pruned = client.post(f"{PREFIX}/pipelines/$prune", json={"keep": ["kept-in-directory"]})

    assert pruned.status_code == 200, pruned.text
    assert pruned.json() == {
        "pruned": ["gone-from-directory"],
        "trigger_documents_removed": [],
        "dry_run": False,
    }
    rows = {row["code"]: row["active"] for row in client.get(f"{PREFIX}/pipelines").json()["items"]}
    assert rows == {"gone-from-directory": False, "kept-in-directory": True, "authored-elsewhere": True}


def test_prune_with_an_empty_keep_is_refused_outside_a_dry_run(client: TestClient) -> None:
    applied = yaml.safe_load(DOCUMENT)
    applied["code"] = "the-only-one"
    client.post(f"{PREFIX}/pipelines/$apply", json={"document": applied, "source": "directory"})

    refused = client.post(f"{PREFIX}/pipelines/$prune", json={"keep": []})
    assert refused.status_code == 422
    assert "empty" in str(refused.json()["detail"])

    planned = client.post(f"{PREFIX}/pipelines/$prune", json={"keep": []}, params={"dry_run": True})
    assert planned.status_code == 200
    assert planned.json() == {"pruned": ["the-only-one"], "trigger_documents_removed": [], "dry_run": True}
    assert client.get(f"{PREFIX}/pipelines").json()["items"][0]["active"] is True


def test_a_dry_run_reports_a_plan_and_writes_nothing(client: TestClient) -> None:
    result = apply_document(client, DOCUMENT, dry_run=True)
    assert result["dry_run"] is True
    assert result["plan"]["action"] == "create"
    assert client.get(f"{PREFIX}/pipelines").json()["items"] == []


def test_re_applying_the_same_document_is_a_reported_no_op(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    again = apply_document(client, DOCUMENT)
    assert again["plan"]["action"] == "unchanged"
    assert again["version"] == 1


def test_a_changed_document_writes_a_version_with_a_diff(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    changed = DOCUMENT.replace("argv: [echo, goodbye]", "argv: [echo, so long]")
    result = apply_document(client, changed)
    assert result["plan"]["action"] == "update"
    assert result["plan"]["diff"]["steps_changed"] == ["farewell"]
    assert result["plan"]["diff"]["steps_added"] == []
    versions = client.get(f"{PREFIX}/pipelines/api-demo/versions").json()["items"]
    assert [row["version"] for row in versions] == [2, 1]
    assert versions[0]["applied_by"] == "tester (token tests)"
    assert versions[0]["provenance_source"] == "api"


def test_an_invalid_document_is_refused_with_its_issues(client: TestClient) -> None:
    result = apply_document(client, DOCUMENT.replace("shell.run", "nope.gone"))
    assert result["plan"]["action"] == "invalid"
    assert [issue["location"] for issue in result["plan"]["issues"]] == [
        "steps.farewell.block",
        "steps.greet.block",
    ]


def test_a_document_that_is_not_dirigent_v1_is_refused_before_anything_else(client: TestClient) -> None:
    response = client.post(f"{PREFIX}/pipelines/$apply", json={"document": {"code": "x", "steps": {}}})
    assert response.status_code == 422
    body = response.json()
    assert "declares no format" in body["problems"][0]
    assert "declares no format" in body["detail"]


def test_a_document_can_be_registered_under_a_different_name(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/pipelines/$apply",
        json={"document": yaml.safe_load(DOCUMENT), "code": "recoded"},
    )
    assert response.status_code == 200
    assert response.json()["plan"]["code"] == "recoded"


def test_export_returns_canonical_yaml(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    exported = client.get(f"{PREFIX}/pipelines/api-demo/$export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/yaml")
    assert exported.text.startswith("format: dirigent/v1\n")
    reapplied = apply_document(client, exported.text)
    assert reapplied["plan"]["action"] == "unchanged"


def test_export_can_name_a_version_and_refuses_an_unknown_one(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    assert client.get(f"{PREFIX}/pipelines/api-demo/$export", params={"version": 1}).status_code == 200
    assert client.get(f"{PREFIX}/pipelines/api-demo/$export", params={"version": 9}).status_code == 404
    assert client.get(f"{PREFIX}/pipelines/nobody/$export").status_code == 404


def test_a_pipeline_can_be_deactivated_and_activated(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    assert client.post(f"{PREFIX}/pipelines/api-demo/$deactivate").json()["active"] is False
    assert client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).status_code == 409
    assert client.post(f"{PREFIX}/pipelines/api-demo/$activate").json()["active"] is True


def test_reading_a_pipeline_includes_its_current_document(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    body = client.get(f"{PREFIX}/pipelines/api-demo").json()
    assert body["document"]["format"] == "dirigent/v1"
    assert client.get(f"{PREFIX}/pipelines/nobody").status_code == 404


#: Three documents wearing overlapping vocabularies, so a repeated tag has something to narrow.
TAGGED = {"climate-load": ["climate", "http"], "climate-shape": ["climate"], "org-units": ["nightly", "http"]}


def apply_tagged(client: TestClient) -> None:
    """Apply one small document per entry in TAGGED, wearing the tags it names."""
    for code, tags in TAGGED.items():
        rendered = ", ".join(tags)
        apply_document(
            client,
            f"format: dirigent/v1\ncode: {code}\ndescription: A tagged pipeline.\ntags: [{rendered}]\n"
            f"steps:\n  greet:\n    block: shell.run\n    config: {{ argv: [echo, hi] }}\n",
        )


def test_a_listing_row_carries_the_tags_its_document_declared(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    apply_tagged(client)
    rows = {row["code"]: row["tags"] for row in client.get(f"{PREFIX}/pipelines").json()["items"]}
    assert rows["climate-load"] == ["climate", "http"]
    assert rows["api-demo"] == [], "a document that declared none wears none"
    assert client.get(f"{PREFIX}/pipelines/climate-load").json()["tags"] == ["climate", "http"]


def test_the_tag_parameter_narrows_the_listing_and_repeats_to_say_and(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    apply_tagged(client)

    def codes(*tags: str) -> list[str]:
        answer = client.get(f"{PREFIX}/pipelines", params=[("tag", tag) for tag in tags])
        assert answer.status_code == 200, answer.text
        return [row["code"] for row in answer.json()["items"]]

    assert codes() == ["api-demo", "climate-load", "climate-shape", "org-units"]
    assert codes("climate") == ["climate-load", "climate-shape"]
    assert codes("climate", "http") == ["climate-load"]
    assert codes("climate", "nightly") == []
    assert codes("nobody-uses-this") == []


def test_a_shouted_tag_is_applied_lowercased_and_answers_to_that_spelling_alone(client: TestClient) -> None:
    apply_document(
        client,
        "format: dirigent/v1\ncode: shouted\ndescription: A shouting pipeline.\ntags: [Climate, Nightly]\n"
        "steps:\n  greet:\n    block: shell.run\n    config: { argv: [echo, hi] }\n",
    )
    assert client.get(f"{PREFIX}/pipelines/shouted").json()["tags"] == ["climate", "nightly"]
    assert [row["code"] for row in client.get(f"{PREFIX}/pipelines", params=[("tag", "climate")]).json()["items"]] == [
        "shouted"
    ]
    assert client.get(f"{PREFIX}/pipelines", params=[("tag", "Climate")]).json()["items"] == []


def test_a_document_whose_tag_cannot_be_normalised_is_refused_with_the_rule_stated(client: TestClient) -> None:
    refused = client.post(
        f"{PREFIX}/pipelines/$apply",
        json={
            "document": {
                "format": "dirigent/v1",
                "code": "bad-tags",
                "tags": ["climate", "nightly import"],
                "steps": {"greet": {"block": "shell.run", "config": {"argv": ["echo", "hi"]}}},
            }
        },
    )
    assert refused.status_code == 422, refused.text
    assert "tags[1]" in refused.text
    assert "'nightly import' is not a valid tag" in refused.text


def test_the_runs_listing_narrows_by_the_tags_the_runs_pipeline_wears(client: TestClient) -> None:
    """A run does not pin tags: the filter is a join to what its pipeline wears now."""
    apply_tagged(client)
    started = {code: client.post(f"{PREFIX}/pipelines/{code}/$run", json={"params": {}}) for code in TAGGED}
    for code, accepted in started.items():
        assert accepted.status_code in {200, 202}, f"{code}: {accepted.text}"
    runs = {code: accepted.json()["run_id"] for code, accepted in started.items()}

    def pipelines_of(*tags: str) -> set[str]:
        answer = client.get(f"{PREFIX}/runs", params=[("tag", tag) for tag in tags])
        assert answer.status_code == 200, answer.text
        return {row["pipeline"] for row in answer.json()["items"]}

    assert pipelines_of() == set(TAGGED)
    assert pipelines_of("climate") == {"climate-load", "climate-shape"}
    assert pipelines_of("climate", "http") == {"climate-load"}, "a repeated tag narrows rather than widens"
    assert pipelines_of("climate", "nightly") == set()
    assert pipelines_of("nobody-uses-this") == set()

    ids = {row["id"] for row in client.get(f"{PREFIX}/runs", params=[("tag", "nightly")]).json()["items"]}
    assert ids == {runs["org-units"]}


def test_a_run_filtered_by_tag_and_status_answers_both(client: TestClient) -> None:
    apply_tagged(client)
    run_id = UUID(client.post(f"{PREFIX}/pipelines/climate-load/$run", json={"params": {}}).json()["run_id"])
    client.post(f"{PREFIX}/pipelines/org-units/$run", json={"params": {}})
    rows_written(client, sa.update(Run).where(Run.id == run_id).values(status=RunStatus.FAILED))
    answer = client.get(f"{PREFIX}/runs", params=[("tag", "climate"), ("status", RunStatus.FAILED.value)])
    assert [row["id"] for row in answer.json()["items"]] == [str(run_id)]


def test_retagging_a_pipeline_moves_its_runs_under_the_new_tag(client: TestClient) -> None:
    apply_tagged(client)
    run_id = client.post(f"{PREFIX}/pipelines/climate-shape/$run", json={"params": {}}).json()["run_id"]
    apply_document(
        client,
        "format: dirigent/v1\ncode: climate-shape\ndescription: A tagged pipeline.\ntags: [nightly]\n"
        "steps:\n  greet:\n    block: shell.run\n    config: { argv: [echo, hi] }\n",
    )

    def ids(tag: str) -> set[str]:
        return {row["id"] for row in client.get(f"{PREFIX}/runs", params=[("tag", tag)]).json()["items"]}

    assert run_id not in ids("climate")
    assert run_id in ids("nightly")


def test_a_document_declaring_a_tag_that_is_not_one_is_refused_at_the_index(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/pipelines/$apply",
        json={"document": yaml.safe_load(DOCUMENT.replace("code: api-demo", "code: api-demo\ntags: [ok, 'Bad Tag']"))},
    )
    assert response.status_code == 422, response.text
    assert "tags[1]" in str(response.json()["problems"])
    assert client.get(f"{PREFIX}/pipelines").json()["items"] == [], "nothing was written"


def test_a_pipeline_that_has_never_run_carries_no_last_run(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    row = client.get(f"{PREFIX}/pipelines").json()["items"][0]
    assert row["last_run"] is None
    assert (row["schedules"], row["webhooks"], row["active_runs"]) == (0, 0, 0)


def test_a_pipeline_listing_counts_what_fires_it_and_what_is_in_flight(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    triggers = f"{PREFIX}/pipelines/api-demo/triggers"
    assert client.post(f"{triggers}/schedules", json={"code": "nightly", "cron": "0 3 * * *"}).status_code == 201
    assert client.post(f"{triggers}/schedules", json={"code": "hourly", "interval": "1h"}).status_code == 201
    assert client.post(f"{triggers}/webhooks", json={"code": "inbound"}).status_code == 201
    client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})

    row = client.get(f"{PREFIX}/pipelines").json()["items"][0]
    assert row["schedules"] == 2
    assert row["webhooks"] == 1
    assert row["active_runs"] == 1


def test_a_pipeline_listing_carries_its_newest_run_and_the_step_that_run_failed_at(client: TestClient) -> None:
    """The last run is the newest one, and the step named is the one that run failed at."""
    apply_document(client, DOCUMENT)

    older = UUID(client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"])
    rows_written(
        client,
        sa.update(StepAttempt).where(StepAttempt.run_id == older).values(status=AttemptStatus.FAILED),
        sa.update(Run).where(Run.id == older).values(status=RunStatus.FAILED, finished_at=datetime.now(UTC)),
    )

    newer = UUID(client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"])
    rows_written(
        client,
        sa.update(StepAttempt).where(StepAttempt.run_id == newer).values(status=AttemptStatus.SUCCEEDED),
        sa.insert(StepAttempt).values(
            run_id=newer,
            step_name="farewell",
            block_id="shell.run",
            attempt=1,
            status=AttemptStatus.FAILED,
        ),
        sa.update(Run).where(Run.id == newer).values(status=RunStatus.FAILED, finished_at=datetime.now(UTC)),
    )

    row = client.get(f"{PREFIX}/pipelines").json()["items"][0]
    assert row["last_run"]["id"] == str(newer), "the newest run, not the first"
    assert row["last_run"]["status"] == "failed"
    assert row["last_run"]["failed_step"] == "farewell", "the step that run failed at, not another run's"
    assert row["last_run"]["finished_at"] is not None
    assert row["active_runs"] == 0


def test_a_pipeline_that_ended_well_names_no_failed_step(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    rows_written(
        client,
        sa.update(StepAttempt).where(StepAttempt.run_id == UUID(run_id)).values(status=AttemptStatus.SUCCEEDED),
        sa.update(Run).where(Run.id == UUID(run_id)).values(status=RunStatus.SUCCEEDED),
    )
    row = client.get(f"{PREFIX}/pipelines").json()["items"][0]
    assert row["last_run"]["status"] == "succeeded"
    assert row["last_run"]["failed_step"] is None


def test_the_runs_listing_names_the_step_a_run_failed_at(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = UUID(client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"])
    rows_written(
        client,
        sa.update(StepAttempt).where(StepAttempt.run_id == run_id).values(status=AttemptStatus.FAILED),
        sa.update(Run).where(Run.id == run_id).values(status=RunStatus.FAILED, finished_at=datetime.now(UTC)),
    )
    rows = client.get(f"{PREFIX}/runs").json()["items"]
    failed = next(row for row in rows if row["id"] == str(run_id))
    assert failed["failed_step"] == "greet"
    healthy = client.get(f"{PREFIX}/runs/{run_id}").json()["run"]
    assert healthy["failed_step"] is None, "the detail renders the DAG; the row is the listing's own"


def test_one_pipelines_runs_and_triggers_are_never_counted_against_another(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    apply_document(client, DOCUMENT.replace("code: api-demo", "code: api-quiet"))
    client.post(f"{PREFIX}/pipelines/api-demo/triggers/webhooks", json={"code": "inbound"})
    client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})

    rows = {row["code"]: row for row in client.get(f"{PREFIX}/pipelines").json()["items"]}
    assert rows["api-demo"]["webhooks"] == 1
    assert rows["api-demo"]["active_runs"] == 1
    assert rows["api-demo"]["last_run"] is not None
    assert rows["api-quiet"]["webhooks"] == 0
    assert rows["api-quiet"]["active_runs"] == 0
    assert rows["api-quiet"]["last_run"] is None


def test_a_stored_parameter_schema_that_is_not_a_schema_is_answered_with_a_readable_refusal(
    client: TestClient,
) -> None:
    """Apply refuses such a document now, so the row is written directly: a version stored before."""
    apply_document(client, DOCUMENT)
    broken = yaml.safe_load(DOCUMENT)
    broken["params"] = {"type": "objcet"}
    rows_written(client, sa.update(PipelineVersion).values(document=broken))

    refused = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {"greeting": "hei"}})

    assert refused.status_code == 422, refused.text
    assert "parameter schema is not itself valid JSON Schema" in refused.json()["detail"]
    assert "apply a corrected document" in refused.json()["detail"]


def test_an_ad_hoc_run_may_declare_the_window_it_covers(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    accepted = client.post(
        f"{PREFIX}/pipelines/api-demo/$run",
        json={"params": {}, "window_start": "2026-06-01T00:00:00Z", "window_end": "2026-06-02T00:00:00Z"},
    )

    assert accepted.status_code == 202, accepted.text
    run = client.get(f"{PREFIX}/runs/{accepted.json()['run_id']}").json()["run"]
    assert datetime.fromisoformat(run["window_start"]) == datetime(2026, 6, 1, tzinfo=UTC)
    assert datetime.fromisoformat(run["window_end"]) == datetime(2026, 6, 2, tzinfo=UTC)


def test_an_ad_hoc_run_that_declares_no_window_carries_none(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    accepted = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})

    run = client.get(f"{PREFIX}/runs/{accepted.json()['run_id']}").json()["run"]
    assert run["window_start"] is None
    assert run["window_end"] is None


def test_an_ad_hoc_run_may_ask_for_debug_and_the_row_says_so(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    accepted = client.post(
        f"{PREFIX}/pipelines/api-demo/$run",
        json={"params": {}, "log_levels": {"*": "debug"}},
    )

    assert accepted.status_code == 202, accepted.text
    run = client.get(f"{PREFIX}/runs/{accepted.json()['run_id']}").json()["run"]
    assert run["log_levels"] == {"*": "debug"}


def test_a_run_carries_the_priority_it_was_created_with(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    accepted = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}, "priority": "high"})

    assert accepted.status_code == 202, accepted.text
    run = client.get(f"{PREFIX}/runs/{accepted.json()['run_id']}").json()["run"]
    assert run["priority"] == "high"


def test_a_run_takes_the_ordinary_priority_when_the_body_names_none(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    accepted = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})

    run = client.get(f"{PREFIX}/runs/{accepted.json()['run_id']}").json()["run"]
    assert run["priority"] == "normal"


def test_the_runs_listing_carries_the_priority(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}, "priority": "low"})

    listed = client.get(f"{PREFIX}/runs").json()["items"]

    assert [row["priority"] for row in listed] == ["low"]


def test_a_priority_that_is_not_one_is_refused(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    refused = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}, "priority": "urgent"})

    assert refused.status_code == 422, refused.text


def test_an_empty_log_level_pattern_is_refused(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    refused = client.post(
        f"{PREFIX}/pipelines/api-demo/$run",
        json={"params": {}, "log_levels": {"": "debug"}},
    )

    assert refused.status_code == 422, refused.text
    assert "a pattern may not be empty" in refused.text


def test_a_level_that_is_not_one_is_refused(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    refused = client.post(
        f"{PREFIX}/pipelines/api-demo/$run",
        json={"params": {}, "log_levels": {"*": "loud"}},
    )

    assert refused.status_code == 422, refused.text


def test_a_half_declared_window_is_refused_with_the_grammar(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    for half in ({"window_start": "2026-06-01T00:00:00Z"}, {"window_end": "2026-06-02T00:00:00Z"}):
        refused = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}, **half})
        assert refused.status_code == 422, refused.text
        assert "a window has two ends" in refused.text


def test_a_backwards_window_is_refused_before_any_run_is_created(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    refused = client.post(
        f"{PREFIX}/pipelines/api-demo/$run",
        json={"params": {}, "window_start": "2026-06-02T00:00:00Z", "window_end": "2026-06-01T00:00:00Z"},
    )

    assert refused.status_code == 422, refused.text
    assert "runs forwards and covers something" in refused.text
    assert client.get(f"{PREFIX}/runs").json()["items"] == []


def test_a_run_is_started_and_its_parameters_are_validated(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    refused = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {"greeting": 7}})
    assert refused.status_code == 422
    accepted = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    assert run_id

    detail = client.get(f"{PREFIX}/runs/{run_id}").json()
    assert detail["run"]["pipeline"] == "api-demo"
    assert detail["run"]["triggered_by_kind"] == "api_token"
    assert detail["run"]["triggered_by_label"] == "tester (token tests)"
    assert [node["code"] for node in detail["dag"]["nodes"]] == ["greet", "farewell"]
    assert detail["dag"]["edges"] == [["greet", "farewell"]]
    assert (detail["attempts_total"], detail["items_total"]) == (2, 0)
    assert "attempts" not in detail and "items" not in detail, "the grids are their own sub-resources"

    attempts = client.get(f"{PREFIX}/runs/{run_id}/attempts").json()
    assert {attempt["step_name"] for attempt in attempts["items"]} == {"greet", "farewell"}
    assert attempts["next"] is None
    assert client.get(f"{PREFIX}/runs/{run_id}/items").json() == {"items": [], "next": None}


FAN_OUT = """
format: dirigent/v1
kind: pipeline
code: fanned
description: One step over three elements, so a grid exists to count.
steps:
  seed:
    block: shell.run
    config:
      argv: [echo, seed]
  spread:
    block: shell.run
    depends_on: [seed]
    for_each: [oslo, bergen, tromso]
    items: continue
    config:
      argv: [echo, spread]
  gather:
    block: shell.run
    depends_on: [spread]
    config:
      argv: [echo, gather]
"""

#: The instants the fan-out run is settled at, which fix the order its steps are read in.
SEEDED = datetime(2026, 2, 1, tzinfo=UTC)


def fanned_run(client: TestClient) -> str:
    """Start a run of the fan-out document, which expands its literal list on creation."""
    apply_document(client, FAN_OUT)
    return str(client.post(f"{PREFIX}/pipelines/fanned/$run", json={"params": {}}).json()["run_id"])


def settled_fan_out(client: TestClient) -> str:
    """Start a fan-out run and write the outcomes a worker would have written.

    One element fails twice and one step never starts, so every count the DAG carries --
    attempts against newest attempts, items against failed items -- differs from the others.
    """
    run_id = fanned_run(client)
    items = {row["item_index"]: row["id"] for row in client.get(f"{PREFIX}/runs/{run_id}/items").json()["items"]}
    attempts = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"step": "spread"}).json()["items"]
    by_item = {row["run_item_id"]: row["id"] for row in attempts}
    seed = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"step": "seed"}).json()["items"][0]["id"]
    rows_written(
        client,
        sa.update(StepAttempt)
        .where(StepAttempt.id == UUID(seed))
        .values(
            status=AttemptStatus.SUCCEEDED,
            started_at=SEEDED,
            finished_at=SEEDED + timedelta(seconds=1),
        ),
        *[
            sa.update(StepAttempt)
            .where(StepAttempt.id == UUID(by_item[items[index]]))
            .values(
                status=status,
                started_at=SEEDED + timedelta(seconds=2),
                finished_at=SEEDED + timedelta(seconds=3),
            )
            for index, status in ((0, AttemptStatus.SUCCEEDED), (1, AttemptStatus.FAILED), (2, AttemptStatus.SUCCEEDED))
        ],
        # A time-ordered id like every real row gets: the attempts listing orders by id, and
        # a random uuid can sort before the first try and flip the order it asserts.
        sa.insert(StepAttempt).values(
            id=uuid7(),
            run_id=UUID(run_id),
            run_item_id=UUID(items[1]),
            step_name="spread",
            block_id="shell.run",
            attempt=2,
            kind="manual",
            status=AttemptStatus.FAILED,
            error="it refused twice",
            started_at=SEEDED + timedelta(seconds=4),
            finished_at=SEEDED + timedelta(seconds=5),
        ),
        *[
            sa.update(RunItem).where(RunItem.id == UUID(items[index])).values(status=status)
            for index, status in ((0, RunItemStatus.SUCCEEDED), (1, RunItemStatus.FAILED), (2, RunItemStatus.SUCCEEDED))
        ],
    )
    return run_id


def test_the_dag_is_the_same_story_the_grid_told(client: TestClient) -> None:
    """Every node field the inlined grid was folded from is folded from counts instead."""
    run_id = settled_fan_out(client)
    dag = client.get(f"{PREFIX}/runs/{run_id}").json()["dag"]
    assert dag["nodes"] == [
        {
            "code": "seed",
            "name": None,
            "block": "shell.run",
            "outcome": "succeeded",
            "depends_on": [],
            "rule": "all_success",
            "fan_out": False,
            "items_total": 0,
            "items_failed": 0,
            "attempts": 1,
        },
        {
            "code": "spread",
            "name": None,
            "block": "shell.run",
            "outcome": "succeeded",
            "depends_on": ["seed"],
            "rule": "all_success",
            "fan_out": True,
            "items_total": 3,
            "items_failed": 1,
            "attempts": 4,
        },
        {
            "code": "gather",
            "name": None,
            "block": "shell.run",
            "outcome": "pending",
            "depends_on": ["spread"],
            "rule": "all_success",
            "fan_out": False,
            "items_total": 0,
            "items_failed": 0,
            "attempts": 1,
        },
    ], "the steps in the order they were written, each folded from its own counts"
    assert dag["edges"] == [["seed", "spread"], ["spread", "gather"]]


#: A document where one step carries a human title and the other carries none.
TITLED_STEPS = """
format: dirigent/v1
kind: pipeline
code: titled-steps
description: One step is named, the other is known by its key alone.
steps:
  quick:
    name: The quick one
    block: shell.run
    config:
      argv: [echo, quick]
  plain:
    block: shell.run
    depends_on: [quick]
    config:
      argv: [echo, plain]
"""


def test_the_dag_carries_the_title_the_document_gave_a_step(client: TestClient) -> None:
    """A node carries the step's key and its optional name, so the graph heads it the way the editor does."""
    apply_document(client, TITLED_STEPS)
    run_id = str(client.post(f"{PREFIX}/pipelines/titled-steps/$run", json={"params": {}}).json()["run_id"])
    nodes = client.get(f"{PREFIX}/runs/{run_id}").json()["dag"]["nodes"]
    assert [(node["code"], node["name"]) for node in nodes] == [("quick", "The quick one"), ("plain", None)]


#: A document whose steps run in the opposite order to the one they are written in.
WRITTEN_ORDER = """
format: dirigent/v1
kind: pipeline
code: written-order
description: The step written first is the one that runs last.
steps:
  later:
    block: shell.run
    depends_on: [earlier]
    config:
      argv: [echo, later]
  earlier:
    block: shell.run
    config:
      argv: [echo, earlier]
"""


def test_the_dag_draws_the_steps_in_the_order_they_were_written(client: TestClient) -> None:
    """A run in flight and the same run settled are one shape.

    The order the nodes arrive in is the order they are laid out in, so an order that followed
    the run -- which step started first, which finished first -- would move every box on the
    canvas the moment the page was opened again.
    """
    apply_document(client, WRITTEN_ORDER)
    run_id = str(client.post(f"{PREFIX}/pipelines/written-order/$run", json={"params": {}}).json()["run_id"])

    def drawn() -> list[str]:
        return [node["code"] for node in client.get(f"{PREFIX}/runs/{run_id}").json()["dag"]["nodes"]]

    assert drawn() == ["later", "earlier"], "nothing has run yet"

    attempts = {row["step_name"]: row["id"] for row in client.get(f"{PREFIX}/runs/{run_id}/attempts").json()["items"]}
    rows_written(
        client,
        sa.update(StepAttempt)
        .where(StepAttempt.id == UUID(attempts["earlier"]))
        .values(status=AttemptStatus.SUCCEEDED, started_at=SEEDED, finished_at=SEEDED + timedelta(seconds=1)),
        sa.update(StepAttempt)
        .where(StepAttempt.id == UUID(attempts["later"]))
        .values(
            status=AttemptStatus.RUNNING,
            started_at=SEEDED + timedelta(seconds=2),
        ),
    )

    assert drawn() == ["later", "earlier"], "the step that ran first is still the step written second"
    assert client.get(f"{PREFIX}/runs/{run_id}").json()["dag"]["edges"] == [["earlier", "later"]]


def test_the_detail_counts_the_grids_it_no_longer_carries(client: TestClient) -> None:
    run_id = settled_fan_out(client)
    detail = client.get(f"{PREFIX}/runs/{run_id}").json()
    assert (detail["items_total"], detail["attempts_total"]) == (3, 6)
    assert "items" not in detail and "attempts" not in detail
    assert len(client.get(f"{PREFIX}/runs/{run_id}/items", params={"limit": 500}).json()["items"]) == 3
    assert len(client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"limit": 500}).json()["items"]) == 6


def test_a_runs_attempts_walk_in_pages(client: TestClient) -> None:
    run_id = settled_fan_out(client)

    first = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"limit": 4}).json()
    assert len(first["items"]) == 4
    assert first["next"] == first["items"][-1]["id"]

    second = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"after": first["next"], "limit": 4}).json()
    assert len(second["items"]) == 2
    assert second["next"] is None

    walked = [row["id"] for row in first["items"] + second["items"]]
    assert walked == sorted(walked), "creation order, every attempt once"
    assert len(set(walked)) == 6

    items = client.get(f"{PREFIX}/runs/{run_id}/items", params={"limit": 2}).json()
    assert [row["item_key"] for row in items["items"]] == ["oslo", "bergen"]
    following = client.get(f"{PREFIX}/runs/{run_id}/items", params={"after": items["next"], "limit": 2}).json()
    assert [row["item_key"] for row in following["items"]] == ["tromso"]
    assert following["next"] is None
    assert client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"after": "half-past"}).status_code == 422


def test_a_runs_attempts_can_be_filtered_by_step_and_state(client: TestClient) -> None:
    run_id = settled_fan_out(client)

    of_step = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"step": "spread"}).json()["items"]
    assert {row["step_name"] for row in of_step} == {"spread"}
    assert len(of_step) == 4

    failed = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"status": "failed"}).json()["items"]
    assert [row["attempt"] for row in failed] == [1, 2], "both tries of the one element that failed"
    assert {row["status"] for row in failed} == {"failed"}

    assert client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"step": "nobody"}).json()["items"] == []
    assert client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"status": "nonsense"}).status_code == 422


def test_runs_can_be_filtered(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})
    assert len(client.get(f"{PREFIX}/runs").json()["items"]) == 1
    assert len(client.get(f"{PREFIX}/runs", params={"pipeline": "api-demo"}).json()["items"]) == 1
    assert client.get(f"{PREFIX}/runs", params={"pipeline": "other"}).json()["items"] == []
    assert client.get(f"{PREFIX}/runs", params={"status": "failed"}).json()["items"] == []
    assert len(client.get(f"{PREFIX}/runs", params={"since": "24h"}).json()["items"]) == 1
    assert client.get(f"{PREFIX}/runs", params={"since": "yesterday"}).status_code == 422


def test_a_run_can_be_cancelled(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    cancelled = client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert "tester" in cancelled.json()["error"]


def test_an_unknown_run_is_a_404(client: TestClient) -> None:
    missing = "00000000-0000-7000-8000-000000000000"
    assert client.get(f"{PREFIX}/runs/{missing}").status_code == 404
    assert client.get(f"{PREFIX}/runs/{missing}/$logs").status_code == 404
    assert client.get(f"{PREFIX}/runs/{missing}/$report").status_code == 404
    assert client.get(f"{PREFIX}/runs/{missing}/items").status_code == 404
    assert client.get(f"{PREFIX}/runs/{missing}/attempts").status_code == 404


def test_a_retry_requires_an_idempotency_key(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    attempt = client.get(f"{PREFIX}/runs/{run_id}/attempts").json()["items"][0]
    assert client.post(f"{PREFIX}/attempts/{attempt['id']}/$retry").status_code == 400
    refused = client.post(f"{PREFIX}/attempts/{attempt['id']}/$retry", headers={"Idempotency-Key": "abc"})
    assert refused.status_code == 409, "a queued attempt has not settled and cannot be retried"


def test_logs_are_paged(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    page = client.get(f"{PREFIX}/runs/{run_id}/$logs").json()
    assert page == {"items": [], "next": None}


def test_a_report_summarises_every_step(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    report = client.get(f"{PREFIX}/runs/{run_id}/$report").json()
    assert report["pipeline"] == "api-demo"
    assert [step["step"] for step in report["steps"]] == ["greet", "farewell"]
    assert report["steps"][0]["block"] == "shell.run"


def test_deleting_refuses_while_a_run_is_in_flight(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})
    refused = client.delete(f"{PREFIX}/pipelines/api-demo")
    assert refused.status_code == 409
    assert "finish or cancel them first" in refused.json()["detail"]
    assert len(client.get(f"{PREFIX}/pipelines").json()["items"]) == 1


def test_deleting_a_pipeline_takes_its_settled_runs_with_it(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    assert client.post(f"{PREFIX}/runs/{run_id}/$cancel").status_code == 200
    assert client.delete(f"{PREFIX}/pipelines/api-demo").status_code == 204
    assert client.get(f"{PREFIX}/pipelines").json()["items"] == []
    assert client.get(f"{PREFIX}/runs/{run_id}").status_code == 404, "the run went with the pipeline"
    assert client.delete(f"{PREFIX}/pipelines/api-demo").status_code == 404


def test_a_pipeline_with_no_runs_is_deleted_outright(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    assert client.delete(f"{PREFIX}/pipelines/api-demo").status_code == 204


def test_system_info_repeats_each_connections_last_check_and_probes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The corner of every page reads this, so it must never run anyone's connect timeout."""
    from dirigent_blocks.connections import HttpConnectionKind

    original = HttpConnectionKind.check
    probes = 0

    async def counted(self: HttpConnectionKind, config: Any) -> Any:
        nonlocal probes
        probes += 1
        return await original(self, config)

    monkeypatch.setattr(HttpConnectionKind, "check", counted)
    client.post(
        f"{PREFIX}/connections",
        json={
            "code": "unreachable",
            "kind": "http",
            "config": {"base_url": "http://127.0.0.1:9", "timeout": "50ms"},
        },
    )
    body = client.get(f"{PREFIX}/system/info").json()
    assert body["blocks"] >= 5
    assert "file" in body["storage_schemes"]
    assert body["secrets_configured"] is True
    assert body["unsafe_blocks_enabled"] == ["shell.run"]
    assert body["connections"] == [
        {
            "code": "unreachable",
            "name": None,
            "kind": "http",
            "last_check_at": None,
            "last_check_healthy": None,
            "last_check_detail": None,
        }
    ]
    assert probes == 0

    report = client.post(f"{PREFIX}/connections/unreachable/$check").json()
    assert probes == 1
    row = client.get(f"{PREFIX}/system/info").json()["connections"][0]
    assert (row["last_check_healthy"], row["last_check_detail"]) == (False, report["detail"])
    assert row["last_check_at"] is not None
    assert probes == 1, "reading the info again repeated the stored check rather than making one"


def test_a_check_holds_no_transaction_while_its_probe_is_out(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every transaction takes the write lock as it opens, and a probe can last a connect timeout."""
    import sqlite3

    from dirigent_common import HealthReport
    from dirigent_server.routes import connections as routes

    path = settings.database_url.removeprefix("sqlite+aiosqlite:///")

    async def probe_that_needs_the_lock(row: Any, services: Any) -> HealthReport:
        # BEGIN IMMEDIATE from a second connection fails within the timeout if the request
        # still holds the write lock, which is exactly what the old fan-out did.
        other = sqlite3.connect(path, timeout=0.2)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
        finally:
            other.close()
        return HealthReport(healthy=True, detail="probed with the lock free")

    monkeypatch.setattr(routes, "check", probe_that_needs_the_lock)
    client.post(f"{PREFIX}/connections", json={"code": "demo", "kind": "http", "config": {"base_url": "http://x"}})
    response = client.post(f"{PREFIX}/connections/demo/$check")
    assert response.status_code == 200, response.text
    row = client.get(f"{PREFIX}/connections/demo").json()
    assert (row["last_check_healthy"], row["last_check_detail"]) == (True, "probed with the lock free")


def test_the_worker_registry_is_served(client: TestClient) -> None:
    assert client.get(f"{PREFIX}/workers").json()["items"] == []


#: A document whose runs may only be claimed by a worker carrying the tag.
ROUTED = DOCUMENT.replace("code: api-demo", "code: api-demo\nrequires:\n  workers: [docker]")


def test_the_worker_registry_carries_each_workers_tags(client: TestClient) -> None:
    """Routing is read off the listing, so the tags a worker advertises are on the wire."""
    rows_written(
        client,
        sa.insert(Worker).values(
            id=uuid7(),
            name="docker-host",
            hostname="somewhere",
            version="test",
            plugins={},
            tags=["docker", "gpu"],
            concurrency=1,
            status=WorkerStatus.RUNNING,
        ),
    )
    [row] = client.get(f"{PREFIX}/workers").json()["items"]
    assert row["tags"] == ["docker", "gpu"]


def test_applying_a_document_no_worker_can_run_warns_rather_than_refusing(client: TestClient) -> None:
    """Workers come and go, so the plan says so and applies anyway."""
    result = apply_document(client, ROUTED)
    assert result["plan"]["action"] == "create"
    assert [issue["location"] for issue in result["plan"]["warnings"]] == ["requires.workers"]
    assert "no live worker carries docker" in result["plan"]["warnings"][0]["message"]


def test_a_queued_run_says_which_worker_tag_it_is_waiting_for(client: TestClient) -> None:
    """The run detail names the tags no live worker carries, computed as the run is read."""
    apply_document(client, ROUTED)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    assert client.get(f"{PREFIX}/runs/{run_id}").json()["waiting_for_workers"] == ["docker"]

    rows_written(
        client,
        sa.insert(Worker).values(
            id=uuid7(),
            name="docker-host",
            hostname="somewhere",
            version="test",
            plugins={},
            tags=["docker"],
            concurrency=1,
            status=WorkerStatus.RUNNING,
        ),
    )
    assert client.get(f"{PREFIX}/runs/{run_id}").json()["waiting_for_workers"] is None


def test_a_run_no_tag_blocks_is_not_reported_as_waiting(client: TestClient) -> None:
    """A document requiring nothing of a worker never draws the waiting line."""
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    assert client.get(f"{PREFIX}/runs/{run_id}").json()["waiting_for_workers"] is None


def test_accounts_can_be_listed_and_created(client: TestClient) -> None:
    assert [row["username"] for row in client.get(f"{PREFIX}/users").json()["items"]] == ["tester"]
    created = client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin"})
    assert created.status_code == 201
    assert created.json()["role"] == "admin"
    assert "password" not in created.text
    assert client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin"}).status_code == 409
    assert (
        client.post(f"{PREFIX}/users", json={"username": "third", "password": "short", "role": "admin"}).status_code
        == 422
    )


def test_creating_an_account_without_a_role_is_refused(client: TestClient) -> None:
    """There is no default, so nothing becomes an admin by leaving a field out."""
    assert client.post(f"{PREFIX}/users", json=SECOND).status_code == 422


def test_an_account_can_be_edited_field_by_field(client: TestClient) -> None:
    """A field the body left out is left alone; name sent as null is cleared."""
    client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin"})
    named = client.patch(f"{PREFIX}/users/second", json={"name": "The Second"})
    assert named.status_code == 200
    assert named.json()["name"] == "The Second"
    assert named.json()["role"] == "admin", "a body that said nothing about the role changed nothing"
    demoted = client.patch(f"{PREFIX}/users/second", json={"role": "operator"})
    assert demoted.json() == {**named.json(), "role": "operator"}
    cleared = client.patch(f"{PREFIX}/users/second", json={"name": None})
    assert cleared.json()["name"] is None
    assert client.patch(f"{PREFIX}/users/nobody", json={"role": "viewer"}).status_code == 404


def test_the_last_active_admin_cannot_demote_itself(client: TestClient) -> None:
    """Refusing the change is what keeps an instance from ending up with nobody who can manage it."""
    refused = client.patch(f"{PREFIX}/users/tester", json={"role": "operator"})
    assert refused.status_code == 409
    assert "only active admin" in refused.json()["detail"]
    assert client.get(f"{PREFIX}/auth/me").json()["role"] == "admin"
    client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin"})
    assert client.patch(f"{PREFIX}/users/tester", json={"role": "operator"}).status_code == 200


def test_the_last_active_admin_cannot_be_deactivated(client: TestClient) -> None:
    refused = client.post(f"{PREFIX}/users/tester/$deactivate")
    assert refused.status_code == 409
    assert "only active admin" in refused.json()["detail"]
    assert client.get(f"{PREFIX}/auth/me").status_code == 200


def test_deactivating_an_account_ends_its_login_and_its_sessions(client: TestClient, anonymous: TestClient) -> None:
    """A deactivated account cannot log in, and the session it already held stops resolving."""
    client.post(f"{PREFIX}/users", json={**SECOND, "role": "operator"})
    login = anonymous.post(f"{PREFIX}/auth/login", json={"username": "second", "password": "another password"})
    assert login.status_code == 200
    assert anonymous.get(f"{PREFIX}/auth/me").status_code == 200

    off = client.post(f"{PREFIX}/users/second/$deactivate")
    assert off.status_code == 200
    assert off.json()["active"] is False
    assert anonymous.get(f"{PREFIX}/auth/me").status_code == 401, "the session it held was revoked with the flag"
    refused = anonymous.post(f"{PREFIX}/auth/login", json={"username": "second", "password": "another password"})
    assert refused.status_code == 401

    on = client.post(f"{PREFIX}/users/second/$activate")
    assert on.json()["active"] is True
    assert (
        anonymous.post(f"{PREFIX}/auth/login", json={"username": "second", "password": "another password"}).status_code
        == 200
    )


def test_an_admin_resets_a_password_and_ends_every_session_of_that_account(
    settings: Settings, admin_token: str
) -> None:
    """A reset presents no old password, ends every session, and leaves the API tokens alone."""
    from dirigent_server import create_app

    app = create_app(settings)
    with (
        TestClient(app, headers={"Authorization": f"Bearer {admin_token}"}) as admin,
        TestClient(app) as theirs,
    ):
        assert admin.post(f"{PREFIX}/users", json={**SECOND, "role": "operator"}).status_code == 201
        minted = admin.post(f"{PREFIX}/users/second/tokens", json={"name": "ci"})
        assert minted.status_code == 201
        assert theirs.post(f"{PREFIX}/auth/login", json=SECOND).status_code == 200
        assert theirs.get(f"{PREFIX}/auth/me").status_code == 200

        reset = admin.post(f"{PREFIX}/users/second/$reset-password", json={"password": "a third password"})
        assert reset.status_code == 204
        assert theirs.get(f"{PREFIX}/auth/me").status_code == 401, "the session minted before the reset is refused"
        assert theirs.post(f"{PREFIX}/auth/login", json=SECOND).status_code == 401, "the old password is gone"
        again = {"username": "second", "password": "a third password"}
        assert theirs.post(f"{PREFIX}/auth/login", json=again).status_code == 200

        with TestClient(app, headers={"Authorization": f"Bearer {minted.json()['token']}"}) as automation:
            assert automation.get(f"{PREFIX}/auth/me").status_code == 200, "an API token survives a reset"


def test_a_reset_refuses_a_short_password_and_an_unknown_account(client: TestClient) -> None:
    assert client.post(f"{PREFIX}/users", json={**SECOND, "role": "operator"}).status_code == 201
    assert client.post(f"{PREFIX}/users/second/$reset-password", json={"password": "short"}).status_code == 422
    assert (
        client.post(f"{PREFIX}/users/nobody/$reset-password", json={"password": "a good password"}).status_code == 404
    )


def test_an_admin_mints_lists_and_revokes_a_token_for_another_account(client: TestClient) -> None:
    assert client.post(f"{PREFIX}/users", json={**SECOND, "role": "operator"}).status_code == 201
    minted = client.post(f"{PREFIX}/users/second/tokens", json={"name": "ci"})
    assert minted.status_code == 201
    assert minted.json()["username"] == "second"
    listed = client.get(f"{PREFIX}/users/second/tokens").json()["items"]
    assert [(row["username"], row["name"]) for row in listed] == [("second", "ci")]
    assert client.delete(f"{PREFIX}/users/second/tokens/ci").status_code == 204
    gone = client.delete(f"{PREFIX}/users/second/tokens/ci")
    assert gone.status_code == 404
    assert "for 'second'" in gone.json()["detail"]
    assert client.get(f"{PREFIX}/users/nobody/tokens").status_code == 404
    assert client.post(f"{PREFIX}/users/nobody/tokens", json={"name": "ci"}).status_code == 404


def test_revoking_your_own_token_leaves_another_accounts_token_of_that_name_alone(client: TestClient) -> None:
    """A token name is unique only within an account, so the owner is part of what is revoked."""
    assert client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin"}).status_code == 201
    assert client.post(f"{PREFIX}/tokens", json={"name": "ci"}).status_code == 201
    theirs = client.post(f"{PREFIX}/users/second/tokens", json={"name": "ci"})
    assert theirs.status_code == 201
    assert client.delete(f"{PREFIX}/tokens/ci").status_code == 204
    live = {
        (row["username"], row["name"])
        for row in client.get(f"{PREFIX}/tokens").json()["items"]
        if not row["revoked_at"]
    }
    assert ("second", "ci") in live
    assert ("tester", "ci") not in live


def test_an_email_is_validated_unique_and_clearable(client: TestClient) -> None:
    assert client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin", "email": "not-an-email"}).status_code == 422
    assert (
        client.post(f"{PREFIX}/users", json={**SECOND, "role": "admin", "email": "one@example.com"}).status_code == 201
    )
    taken = client.post(
        f"{PREFIX}/users",
        json={"username": "third", "password": "another password", "role": "admin", "email": "one@example.com"},
    )
    assert taken.status_code == 409
    assert client.patch(f"{PREFIX}/users/tester", json={"email": "one@example.com"}).status_code == 409
    assert client.patch(f"{PREFIX}/users/tester", json={"email": "not-an-email"}).status_code == 422
    assert (
        client.patch(f"{PREFIX}/users/tester", json={"email": "mine@example.com"}).json()["email"] == "mine@example.com"
    )
    assert client.patch(f"{PREFIX}/users/tester", json={"name": "Tester"}).json()["email"] == "mine@example.com"
    assert client.patch(f"{PREFIX}/users/tester", json={"email": None}).json()["email"] is None


def test_managing_accounts_is_an_admins(operator: TestClient) -> None:
    assert operator.patch(f"{PREFIX}/users/tester", json={"role": "viewer"}).status_code == 403
    assert operator.post(f"{PREFIX}/users/tester/$deactivate").status_code == 403
    assert operator.post(f"{PREFIX}/users/tester/$activate").status_code == 403


def test_a_person_changes_their_own_password_and_keeps_the_session_they_did_it_from(
    settings: Settings, admin_token: str
) -> None:
    """Every other session goes; the one the change arrived on stays, so the page does not log out."""
    from dirigent_server import create_app
    from tests_support import PASSWORD, USERNAME

    app = create_app(settings)
    credentials = {"username": USERNAME, "password": PASSWORD}
    with TestClient(app) as here, TestClient(app) as elsewhere:
        assert here.post(f"{PREFIX}/auth/login", json=credentials).status_code == 200
        assert elsewhere.post(f"{PREFIX}/auth/login", json=credentials).status_code == 200

        changed = here.post(
            f"{PREFIX}/auth/password",
            json={"current_password": PASSWORD, "new_password": "a longer new password"},
        )
        assert changed.status_code == 204
        assert here.get(f"{PREFIX}/auth/me").status_code == 200, "the session it was made from survives"
        assert elsewhere.get(f"{PREFIX}/auth/me").status_code == 401, "every other session is revoked"
        again = {"username": USERNAME, "password": "a longer new password"}
        assert elsewhere.post(f"{PREFIX}/auth/login", json=again).status_code == 200


def test_a_password_change_is_refused_without_the_current_one(client: TestClient) -> None:
    from tests_support import PASSWORD

    wrong = client.post(
        f"{PREFIX}/auth/password",
        json={"current_password": "not the password", "new_password": "a longer new password"},
    )
    assert wrong.status_code == 403
    weak = client.post(f"{PREFIX}/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert weak.status_code == 422
    assert client.get(f"{PREFIX}/auth/me").status_code == 200


def test_an_operator_may_change_their_own_password(operator: TestClient) -> None:
    """Self-service is not an admin action; every authenticated principal has it."""
    from tests_support import PASSWORD

    changed = operator.post(
        f"{PREFIX}/auth/password",
        json={"current_password": PASSWORD, "new_password": "a longer new password"},
    )
    assert changed.status_code == 204


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("pipelines", "applyPipeline"), ("runs", "getRunLogs"), ("connections", "checkConnection")],
)
def test_the_openapi_document_names_every_operation(client: TestClient, tag: str, expected: str) -> None:
    document = client.get("/openapi.json").json()
    operations = [
        operation
        for path in document["paths"].values()
        for operation in path.values()
        if tag in operation.get("tags", [])
    ]
    assert expected in {operation["operationId"] for operation in operations}
    assert all(operation.get("summary") for operation in operations)


def test_no_operation_id_is_generated_by_accident(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    generated = [
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
        if "_" in operation["operationId"]
    ]
    assert generated == [], f"these operations have no explicit operation id: {generated}"


def test_the_log_tail_streams_over_server_sent_events(client: TestClient) -> None:
    """A run that has already settled ends the stream rather than holding it open."""
    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$logs", params={"follow": "sse"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "event: end" in body


def test_a_principal_cannot_hold_more_log_streams_than_the_cap(client: TestClient) -> None:
    """Each tail is a periodic query against a pool the whole instance shares."""
    from dirigent_server.routes import runs as runs_route

    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    watcher = client.get(f"{PREFIX}/auth/me").json()["user_id"]
    runs_route.OPEN_TAILS[watcher] = runs_route.MAX_TAILS_PER_PRINCIPAL
    try:
        refused = client.get(f"{PREFIX}/runs/{run_id}/$logs", params={"follow": "sse"})
    finally:
        runs_route.OPEN_TAILS.pop(watcher, None)
    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "5"
    assert client.get(f"{PREFIX}/runs/{run_id}/$logs").status_code == 200, "a page is never refused"


#: A stream is read whole, so what it saw change has to be written while it is open.
INTERVAL = 0.05
REPLAYED = 0.5


def rows_written(client: TestClient, *statements: sa.Executable) -> None:
    """Write rows the way the engine would, so a test can move a run with no worker running."""
    settings = cast("FastAPI", client.app).state.settings

    async def apply() -> None:
        engine = create_engine(settings)
        try:
            async with session_scope(create_session_factory(engine)) as session:
                for statement in statements:
                    await session.execute(statement)
        finally:
            await engine.dispose()

    asyncio.run(apply())


def sse_events(lines: Iterator[str]) -> list[tuple[str, dict[str, Any]]]:
    """Read every event off a server-sent-event stream, each as its name and its payload."""
    found: list[tuple[str, dict[str, Any]]] = []
    name = ""
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            found.append((name, json.loads(line.removeprefix("data: "))))
    return found


def sse_frames(lines: Iterator[str]) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Read every event off a stream as its name, the id it carried, and its payload."""
    found: list[tuple[str, str | None, dict[str, Any]]] = []
    name = ""
    ident: str | None = None
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("id: "):
            ident = line.removeprefix("id: ")
        elif line.startswith("data: "):
            found.append((name, ident, json.loads(line.removeprefix("data: "))))
            ident = None
    return found


def log_row(run_id: UUID, attempt: UUID, message: str, when: datetime) -> sa.Executable:
    """Write one log line the way a worker running the greet step would."""
    return sa.insert(LogEntry).values(
        run_id=run_id,
        step_attempt_id=attempt,
        step_name="greet",
        level=LogLevel.INFO,
        message=message,
        created_at=when,
    )


def attempt_id(client: TestClient, run_id: UUID, step: str) -> UUID:
    """Name the attempt of one step of a run."""
    attempts = client.get(f"{PREFIX}/runs/{run_id}/attempts", params={"step": step}).json()["items"]
    return UUID(attempts[0]["id"])


def started_run(client: TestClient) -> UUID:
    """Apply the shared document and start one run of it."""
    apply_document(client, DOCUMENT)
    return UUID(client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"])


def test_the_event_stream_tells_the_run_story_in_order(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """One stream carries the attempts as they move, the lines they wrote, and how it ended."""
    from dirigent_server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "FOLLOW_INTERVAL_SECONDS", INTERVAL)
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    began = datetime(2026, 1, 1, tzinfo=UTC)
    rows_written(
        client,
        sa.update(StepAttempt).where(StepAttempt.id == greet).values(status=AttemptStatus.RUNNING, started_at=began),
    )

    def finish() -> None:
        """Move the run on while the stream is open, which is the only way it sees a change."""
        time.sleep(REPLAYED)
        rows_written(
            client,
            sa.insert(LogEntry).values(
                run_id=run_id,
                step_attempt_id=greet,
                step_name="greet",
                level=LogLevel.INFO,
                message="hello from the api",
                created_at=began + timedelta(seconds=1),
            ),
            sa.update(StepAttempt)
            .where(StepAttempt.id == greet)
            .values(status=AttemptStatus.SUCCEEDED, finished_at=began + timedelta(seconds=2)),
            sa.update(Run)
            .where(Run.id == run_id)
            .values(status=RunStatus.SUCCEEDED, finished_at=began + timedelta(seconds=2)),
        )

    writer = threading.Thread(target=finish)
    writer.start()
    try:
        with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            story = sse_events(response.iter_lines())
    finally:
        writer.join()

    assert [name for name, _ in story] == ["run", "attempt", "attempt", "log", "attempt", "run", "end"]
    moved = [data["status"] for name, data in story if name == "attempt" and data["step_name"] == "greet"]
    assert moved == ["running", "succeeded"], "the state it was found in, then the state it moved to"
    assert story[0][1]["status"] == "queued", "the run it joined is reported before the lines it caused"
    assert story[3][1]["message"] == "hello from the api"
    assert story[5][1]["status"] == "succeeded"


def test_the_event_stream_reports_a_run_that_started_before_it_settles(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A watcher learns that a run is running when it starts, not when it ends."""
    from dirigent_server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "FOLLOW_INTERVAL_SECONDS", INTERVAL)
    run_id = started_run(client)
    began = datetime(2026, 1, 1, tzinfo=UTC)

    def move() -> None:
        """Claim the run, then settle it, both while the stream is open."""
        time.sleep(REPLAYED)
        rows_written(
            client,
            sa.update(Run).where(Run.id == run_id).values(status=RunStatus.RUNNING, started_at=began),
        )
        time.sleep(REPLAYED)
        rows_written(
            client,
            sa.update(Run)
            .where(Run.id == run_id)
            .values(status=RunStatus.SUCCEEDED, finished_at=began + timedelta(seconds=2)),
        )

    writer = threading.Thread(target=move)
    writer.start()
    try:
        with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
            story = sse_events(response.iter_lines())
    finally:
        writer.join()

    runs = [data for name, data in story if name == "run"]
    assert [data["status"] for data in runs] == ["queued", "running", "succeeded"]
    assert runs[1]["started_at"] is not None, "the header can show a start time as soon as it has one"
    assert [name for name, _ in story[-2:]] == ["run", "end"], "the settled frame still ends the story"


def test_an_unchanged_run_is_not_reported_twice(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stream reports a state, not a cycle: polls that found the same run say nothing."""
    from dirigent_server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "FOLLOW_INTERVAL_SECONDS", INTERVAL)
    run_id = started_run(client)

    def settle() -> None:
        """Leave the run alone for several polls, then end it so the stream closes."""
        time.sleep(REPLAYED)
        rows_written(
            client,
            sa.update(Run)
            .where(Run.id == run_id)
            .values(status=RunStatus.SUCCEEDED, finished_at=datetime(2026, 1, 1, tzinfo=UTC)),
        )

    writer = threading.Thread(target=settle)
    writer.start()
    try:
        with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
            story = sse_events(response.iter_lines())
    finally:
        writer.join()

    assert [data["status"] for name, data in story if name == "run"] == ["queued", "succeeded"]


def test_an_unchanged_attempt_is_not_reported_twice(client: TestClient) -> None:
    """The stream reports a state, not a cycle: a poll that found nothing new says nothing."""
    run_id = started_run(client)
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
        story = sse_events(response.iter_lines())
    reported = [data["id"] for name, data in story if name == "attempt"]
    assert len(reported) == len(set(reported)), "a settled run is polled twice, and reports once"
    assert len(reported) == client.get(f"{PREFIX}/runs/{run_id}").json()["attempts_total"]
    assert [name for name, _ in story[-2:]] == ["run", "end"]


def test_event_streams_share_the_log_tail_budget(client: TestClient) -> None:
    """What a principal costs is the poll loops it holds open, not what they carry."""
    from dirigent_server.routes import runs as runs_route

    run_id = started_run(client)
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    watcher = client.get(f"{PREFIX}/auth/me").json()["user_id"]
    assert runs_route.MAX_TAILS_PER_PRINCIPAL == 8, "one multiplexed stream per run, and several runs open at once"
    held = runs_route.MAX_TAILS_PER_PRINCIPAL - 1
    runs_route.OPEN_TAILS[watcher] = held
    try:
        with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
            assert response.status_code == 200
            list(response.iter_lines())
        assert runs_route.OPEN_TAILS[watcher] == held, "an event stream is counted against the same budget"
        runs_route.OPEN_TAILS[watcher] = runs_route.MAX_TAILS_PER_PRINCIPAL
        assert client.get(f"{PREFIX}/runs/{run_id}/$events").status_code == 429
        assert client.get(f"{PREFIX}/runs/{run_id}/$logs", params={"follow": "sse"}).status_code == 429
    finally:
        runs_route.OPEN_TAILS.pop(watcher, None)


def test_a_fan_out_event_names_the_item(client: TestClient) -> None:
    """An attempt of a fan-out element carries the label and the index of the element it ran for."""
    run_id = started_run(client)
    farewell = attempt_id(client, run_id, "farewell")
    element = uuid.uuid4()
    rows_written(
        client,
        sa.insert(RunItem).values(id=element, run_id=run_id, step_name="farewell", item_index=2, item_key="oslo"),
        sa.update(StepAttempt).where(StepAttempt.id == farewell).values(run_item_id=element),
    )
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
        story = sse_events(response.iter_lines())
    attempts = [data for name, data in story if name == "attempt"]
    farewells = [row for row in attempts if row["step_name"] == "farewell"]
    assert [(row["item"], row["item_index"]) for row in farewells] == [("oslo", 2)]
    greets = [row for row in attempts if row["step_name"] == "greet"]
    assert [(row["item"], row["item_index"]) for row in greets] == [(None, None)]


def test_log_entries_reach_the_event_stream_in_id_order(client: TestClient) -> None:
    """A client resumes past the highest id it was sent, so a lower one after it is lost.

    Lines are buffered per attempt and written on a flush and again when that attempt settles,
    so two attempts running at once commit theirs out of timestamp order.
    """
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    began = datetime(2026, 1, 1, tzinfo=UTC)
    rows_written(
        client,
        log_row(run_id, greet, "written late, logged early", began + timedelta(seconds=1)),
        log_row(run_id, greet, "written next, logged last", began + timedelta(seconds=9)),
        log_row(run_id, greet, "written last, logged in between", began + timedelta(seconds=5)),
    )
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
        story = sse_frames(response.iter_lines())
    logs = [(ident, data["message"]) for name, ident, data in story if name == "log"]
    assert [message for _, message in logs] == [
        "written late, logged early",
        "written next, logged last",
        "written last, logged in between",
    ]
    ids = [int(ident) for ident, _ in logs if ident is not None]
    assert len(ids) == 3
    assert ids == sorted(ids)


def test_a_line_flushed_while_a_step_runs_reaches_the_stream_before_its_outcome(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker flushes a running attempt's log, and a watcher reads it before the step ends."""
    from dirigent_server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "FOLLOW_INTERVAL_SECONDS", INTERVAL)
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    began = datetime(2026, 1, 1, tzinfo=UTC)
    rows_written(
        client,
        sa.update(StepAttempt).where(StepAttempt.id == greet).values(status=AttemptStatus.RUNNING, started_at=began),
    )

    def work() -> None:
        """Flush a line mid-attempt, and settle the step a poll later."""
        time.sleep(REPLAYED)
        rows_written(client, log_row(run_id, greet, "still working", began + timedelta(seconds=1)))
        time.sleep(REPLAYED)
        rows_written(
            client,
            sa.update(StepAttempt)
            .where(StepAttempt.id == greet)
            .values(status=AttemptStatus.SUCCEEDED, finished_at=began + timedelta(seconds=9)),
            sa.update(Run)
            .where(Run.id == run_id)
            .values(status=RunStatus.SUCCEEDED, finished_at=began + timedelta(seconds=9)),
        )

    worker = threading.Thread(target=work)
    worker.start()
    try:
        with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
            story = sse_events(response.iter_lines())
    finally:
        worker.join()

    logged = next(index for index, (name, _) in enumerate(story) if name == "log")
    settled = next(
        index
        for index, (name, data) in enumerate(story)
        if name == "attempt" and data["step_name"] == "greet" and data["status"] == "succeeded"
    )
    assert story[logged][1]["message"] == "still working"
    assert logged < settled, "the line went out while the step was still running"


def test_a_stream_that_reaches_the_wall_clock_limit_says_expired_rather_than_end(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``end`` means the run settled; a client that read it at the limit would stop following."""
    from dirigent_server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "FOLLOW_MAX_SECONDS", 0.0)
    run_id = started_run(client)
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
        story = sse_events(response.iter_lines())
    assert [name for name, _ in story] == ["expired"]
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$logs", params={"follow": "sse"}) as response:
        tail = sse_events(response.iter_lines())
    assert [name for name, _ in tail] == ["expired"]


def test_a_quiet_log_stream_widens_its_poll_interval_to_the_ceiling() -> None:
    from dirigent_server.routes.runs import FOLLOW_INTERVAL_SECONDS, FOLLOW_MAX_INTERVAL_SECONDS, next_interval

    interval = FOLLOW_INTERVAL_SECONDS
    for _ in range(50):
        interval = next_interval(interval)
    assert interval == FOLLOW_MAX_INTERVAL_SECONDS
    assert next_interval(FOLLOW_INTERVAL_SECONDS) > FOLLOW_INTERVAL_SECONDS


def test_a_settled_failure_can_be_retried_with_an_idempotency_key(client: TestClient) -> None:
    """A manual retry creates exactly one attempt, however many times it is asked for."""
    import asyncio
    import uuid

    import sqlalchemy as sa

    apply_document(client, DOCUMENT)
    run_id = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"]
    attempt = client.get(f"{PREFIX}/runs/{run_id}/attempts").json()["items"][0]

    # Settle the attempt as failed the way the engine would, so the retry has something to do.
    from dirigent_client.enums import AttemptStatus
    from dirigent_core.database import create_engine, create_session_factory, session_scope
    from dirigent_core.models import StepAttempt

    settings = cast("FastAPI", client.app).state.settings

    async def fail_it() -> None:
        engine = create_engine(settings)
        try:
            async with session_scope(create_session_factory(engine)) as session:
                await session.execute(
                    sa.update(StepAttempt)
                    .where(StepAttempt.id == uuid.UUID(attempt["id"]))
                    .values(status=AttemptStatus.FAILED, error="a deliberate failure", error_class="unknown")
                )
        finally:
            await engine.dispose()

    asyncio.run(fail_it())

    headers = {"Idempotency-Key": "the-same-key"}
    first = client.post(f"{PREFIX}/attempts/{attempt['id']}/$retry", headers=headers)
    assert first.status_code == 202
    assert first.json()["attempt"] == 2
    assert first.json()["kind"] == "manual"
    again = client.post(f"{PREFIX}/attempts/{attempt['id']}/$retry", headers=headers)
    assert again.json()["id"] == first.json()["id"], "the same key must not create a second attempt"
    third = client.post(f"{PREFIX}/attempts/{attempt['id']}/$retry", headers={"Idempotency-Key": "another"})
    assert third.status_code == 409, "the step is queued again, so there is nothing settled to retry"


def test_retrying_an_attempt_that_does_not_exist_is_a_404(client: TestClient) -> None:
    missing = "00000000-0000-7000-8000-000000000000"
    response = client.post(f"{PREFIX}/attempts/{missing}/$retry", headers={"Idempotency-Key": "k"})
    assert response.status_code == 404


def test_a_rejected_connection_config_does_not_echo_the_secret_back(client: TestClient) -> None:
    """Pydantic's default error payload includes the input that failed, and here that is a credential."""
    response = client.post(
        f"{PREFIX}/connections",
        json={"code": "leaky", "kind": "http", "config": {"base_url": 17, "token": "super-secret-value"}},
    )
    assert response.status_code == 422
    assert "super-secret-value" not in response.text


def test_a_check_that_raises_says_what_kind_of_failure_and_nothing_more(client: TestClient) -> None:
    """A driver's exception text carries the DSN it was trying, and every principal reads this row."""
    from dirigent_server.routes.connections import CHECK_FAILED_HINT, summarise_failure

    detail = summarise_failure(RuntimeError("could not connect to postgres://admin:hunter2@db:5432/prod"))
    assert "hunter2" not in detail
    assert detail == f"RuntimeError: {CHECK_FAILED_HINT}"


def test_login_is_rate_limited_before_it_hashes_anything(anonymous: TestClient) -> None:
    """Argon2id at 64 MiB on an unauthenticated route is a weapon unless it is bounded."""
    LOGIN_BUCKETS.buckets.clear()
    codes = [
        anonymous.post(f"{PREFIX}/auth/login", json={"username": "nobody", "password": "wrong-password"}).status_code
        for _ in range(20)
    ]
    assert 401 in codes
    assert codes[-1] == 429
    LOGIN_BUCKETS.buckets.clear()


OPERATOR_ALLOWED = [
    ("get", "/pipelines"),
    ("get", "/runs"),
    ("get", "/connections"),
    ("get", "/blocks"),
    ("get", "/workers"),
    ("get", "/system/info"),
    ("get", "/auth/me"),
]

OPERATOR_REFUSED = [
    ("get", "/users"),
    ("post", "/users"),
    ("post", "/users/whatever/$reset-password"),
    ("get", "/users/whatever/tokens"),
    ("post", "/users/whatever/tokens"),
    ("delete", "/users/whatever/tokens/whatever"),
    ("get", "/tokens"),
    ("post", "/tokens"),
    ("delete", "/tokens/whatever"),
    ("post", "/connections"),
    ("patch", "/connections/whatever"),
    ("delete", "/connections/whatever"),
    ("post", "/connections/whatever/$check"),
    ("delete", "/pipelines/api-demo"),
]


@pytest.mark.parametrize(("method", "path"), OPERATOR_ALLOWED)
def test_an_operator_may_define_run_and_observe(operator: TestClient, method: str, path: str) -> None:
    """An operator may reach every observation route."""
    response = operator.request(method, f"{PREFIX}{path}", json={})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("method", "path"), OPERATOR_REFUSED)
def test_an_operator_may_not_hand_out_authority(operator: TestClient, method: str, path: str) -> None:
    """Every route here either mints authority or takes custody of a credential."""
    response = operator.request(method, f"{PREFIX}{path}", json={})
    assert response.status_code == 403, f"{method} {path} let an operator through"
    assert "not permitted for your role" in response.json()["detail"]


def test_an_operator_can_still_apply_and_run_a_pipeline(operator: TestClient) -> None:
    """Apply and $run stay open to an operator."""
    applied = apply_document(operator, DOCUMENT)
    assert applied["plan"]["action"] == "create"
    started = operator.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {"greeting": "hei"}})
    assert started.status_code == 202, started.text


def test_the_openapi_document_declares_how_a_credential_is_presented(client: TestClient) -> None:
    """Without a declared scheme, 50-odd operations render as open in /docs and in clients."""
    document = client.get("/openapi.json").json()
    schemes = document["components"]["securitySchemes"]
    assert schemes["bearerAuth"]["type"] == "http"
    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert schemes["sessionCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "dirigent_session",
        "description": schemes["sessionCookie"]["description"],
    }
    listed = document["paths"][f"{PREFIX}/pipelines"]["get"]["security"]
    assert {"bearerAuth": []} in listed
    assert "security" not in document["paths"][f"{PREFIX}/auth/login"]["post"]


def test_logging_out_clears_the_cookie_it_set(anonymous: TestClient) -> None:
    """Revoking the session stops it working; the browser still holds the cookie until told."""
    from tests_support import PASSWORD, USERNAME

    anonymous.post(f"{PREFIX}/auth/login", json={"username": USERNAME, "password": PASSWORD})

    logout = anonymous.post(f"{PREFIX}/auth/logout")

    assert logout.status_code == 204
    assert "set-cookie" in {name.lower() for name in logout.headers}, "nothing told the browser to drop it"
    assert "dirigent_session" not in anonymous.cookies


def test_a_description_sent_as_null_is_cleared(client: TestClient) -> None:
    """Omitting a field and sending it as null are different requests, and mean different things."""
    client.post(
        f"{PREFIX}/connections",
        json={
            "code": "described",
            "kind": "http",
            "config": {"base_url": "https://x.example.org"},
            "description": "a note",
        },
    )

    kept = client.patch(f"{PREFIX}/connections/described", json={"config": {"base_url": "https://x.example.org"}})
    assert kept.json()["description"] == "a note", "leaving it out changed it"

    cleared = client.patch(f"{PREFIX}/connections/described", json={"description": None})

    assert cleared.status_code == 200
    assert cleared.json()["description"] is None, "sending null could not clear it"


def stored_secret(client: TestClient, name: str, field: str) -> Any:
    """Open a connection's envelope the way a worker does, since every read shows the marker."""
    app = cast("FastAPI", client.app)

    async def opened() -> Any:
        engine = create_engine(app.state.settings)
        try:
            async with session_scope(create_session_factory(engine)) as session:
                found = await session.execute(sa.select(Connection).where(Connection.code == name))
                row = found.scalar_one()
                return app.state.services.secrets.open(row.secret_envelope, key_id=row.secret_key_id).get(field)
        finally:
            await engine.dispose()

    return asyncio.run(opened())


def test_a_read_edited_and_sent_back_keeps_the_secret(client: TestClient) -> None:
    """A form shows *** for a secret and sends the whole document back to change something else."""
    client.post(
        f"{PREFIX}/connections",
        json={
            "code": "round-trip",
            "kind": "http",
            "config": {"base_url": "https://ops.example.org", "bearer_token": "super-secret"},
        },
    )
    read_back = client.get(f"{PREFIX}/connections/round-trip").json()["config"]
    assert read_back["bearer_token"] == "***"

    edited = {**read_back, "base_url": "https://ops2.example.org"}
    updated = client.patch(f"{PREFIX}/connections/round-trip", json={"config": edited})

    assert updated.status_code == 200
    assert updated.json()["config"]["base_url"] == "https://ops2.example.org", "the edit did not take"
    assert stored_secret(client, "round-trip", "bearer_token") == "super-secret", "the mask was stored as the secret"


def test_the_marker_with_nothing_behind_it_is_refused(client: TestClient) -> None:
    """Nothing tells *** for a secret that was never set apart from somebody choosing it as one."""
    client.post(
        f"{PREFIX}/connections",
        json={"code": "no-secret", "kind": "http", "config": {"base_url": "https://ops.example.org"}},
    )
    assert client.get(f"{PREFIX}/connections/no-secret").json()["config"]["bearer_token"] is None

    refused = client.patch(
        f"{PREFIX}/connections/no-secret",
        json={"config": {"base_url": "https://ops.example.org", "bearer_token": "***"}},
    )

    assert refused.status_code == 422
    assert "bearer_token" in refused.text
    assert stored_secret(client, "no-secret", "bearer_token") is None


def test_a_new_secret_replaces_the_old_one(client: TestClient) -> None:
    client.post(
        f"{PREFIX}/connections",
        json={
            "code": "rotated",
            "kind": "http",
            "config": {"base_url": "https://ops.example.org", "bearer_token": "the-old-one"},
        },
    )

    updated = client.patch(
        f"{PREFIX}/connections/rotated",
        json={"config": {"base_url": "https://ops.example.org", "bearer_token": "the-new-one"}},
    )

    assert updated.status_code == 200
    assert "the-new-one" not in updated.text
    assert stored_secret(client, "rotated", "bearer_token") == "the-new-one"


async def test_a_write_is_committed_before_its_response_is_sent() -> None:
    """A client told a write succeeded must be able to read it, and must not be told too early.

    FastAPI runs the exit of a yield dependency after the response has gone out, so committing
    there tells a client its write happened before it had: a read straight back can miss it,
    and a commit that fails does so after a 2xx.
    """
    from fastapi import APIRouter, FastAPI

    from dirigent_server.transactions import Transactional

    order: list[str] = []

    class Recording(Transactional):
        """The route under test, saying when its commit finished."""

        def get_route_handler(self) -> Any:
            inner = super().get_route_handler()

            async def handler(request: Any) -> Any:
                response = await inner(request)
                order.append("committed")
                return response

            return handler

    router = APIRouter(route_class=Recording)

    @router.post("/thing")
    async def make_thing() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"made": True}

    app = FastAPI()
    app.include_router(router)

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/thing")
        order.append("answered")

    assert response.status_code == 200
    assert order == ["committed", "answered"], f"the response went out before the commit: {order}"


def test_a_run_created_through_the_api_belongs_to_the_request_trace(
    client: TestClient, spans: InMemorySpanExporter
) -> None:
    """What a worker picks up hours later has to lead back to the call that asked for it."""
    apply_document(client, DOCUMENT)
    accepted = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}})
    run_id = accepted.json()["run_id"]

    trace_id = client.get(f"{PREFIX}/runs/{run_id}").json()["run"]["trace_id"]

    finished = spans.get_finished_spans()
    request_span = next(span for span in finished if span.name.endswith("/$run"))
    run_span = next(span for span in finished if span.name == "run api-demo")
    assert request_span.context is not None
    assert run_span.parent is not None
    assert run_span.parent.span_id == request_span.context.span_id, "the run hangs from nothing"
    assert trace_id == format(request_span.context.trace_id, "032x")


# -- the pagination envelope ------------------------------------------------------


def start_runs(client: TestClient, count: int) -> list[str]:
    """Start runs of the applied pipeline and name them oldest first."""
    return [
        client.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {}}).json()["run_id"] for _ in range(count)
    ]


def write_logs(settings: Settings, run_id: str, count: int) -> None:
    """Append log entries to a run, which no worker runs in these tests."""

    async def append() -> None:
        engine = create_engine(settings)
        try:
            sessions = create_session_factory(engine)
            async with session_scope(sessions) as session:
                for index in range(count):
                    session.add(LogEntry(run_id=UUID(run_id), message=f"line {index}"))
        finally:
            await engine.dispose()

    asyncio.run(append())


def test_a_listing_walks_in_pages(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    started = start_runs(client, 3)

    first = client.get(f"{PREFIX}/runs", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["next"] == first["items"][-1]["id"]

    second = client.get(f"{PREFIX}/runs", params={"after": first["next"], "limit": 2}).json()
    assert len(second["items"]) == 1
    assert second["next"] is None

    walked = [row["id"] for row in first["items"] + second["items"]]
    assert walked == list(reversed(started)), "newest first, every run once"


def test_a_name_cursor_walks_the_same_way(client: TestClient) -> None:
    for name in ("gamma", "alpha", "beta"):
        created = client.post(
            f"{PREFIX}/connections",
            json={"code": name, "kind": "http", "config": {"base_url": "https://example.invalid"}},
        )
        assert created.status_code == 201, created.text

    first = client.get(f"{PREFIX}/connections", params={"limit": 2}).json()
    assert [row["code"] for row in first["items"]] == ["alpha", "beta"]
    assert first["next"] == "beta"

    second = client.get(f"{PREFIX}/connections", params={"after": first["next"], "limit": 2}).json()
    assert [row["code"] for row in second["items"]] == ["gamma"]
    assert second["next"] is None


def test_a_row_created_between_pages_is_neither_skipped_nor_repeated(client: TestClient) -> None:
    """The keyset promise: a cursor names a row, so an insert cannot shift a page under it."""
    apply_document(client, DOCUMENT)
    started = start_runs(client, 2)

    first = client.get(f"{PREFIX}/runs", params={"limit": 1}).json()
    assert [row["id"] for row in first["items"]] == [started[-1]]

    inserted = start_runs(client, 1)[0]

    second = client.get(f"{PREFIX}/runs", params={"after": first["next"], "limit": 1}).json()
    assert [row["id"] for row in second["items"]] == [started[0]], "the second run, not the new one"
    assert inserted not in [row["id"] for row in second["items"]]


def test_the_limit_is_capped(client: TestClient) -> None:
    assert client.get(f"{PREFIX}/runs", params={"limit": 501}).status_code == 422
    assert client.get(f"{PREFIX}/runs", params={"limit": 0}).status_code == 422
    assert client.get(f"{PREFIX}/runs", params={"limit": 500}).status_code == 200


def test_a_cursor_that_is_not_one_is_refused(client: TestClient) -> None:
    refused = client.get(f"{PREFIX}/runs", params={"after": "not-a-uuid"})
    assert refused.status_code == 422
    assert "not a cursor" in refused.json()["detail"]


def test_the_log_page_walks_its_cursor(client: TestClient, settings: Settings) -> None:
    apply_document(client, DOCUMENT)
    run_id = start_runs(client, 1)[0]
    write_logs(settings, run_id, 3)

    first = client.get(f"{PREFIX}/runs/{run_id}/$logs", params={"limit": 2}).json()
    assert [row["message"] for row in first["items"]] == ["line 0", "line 1"]
    assert first["next"] == str(first["items"][-1]["id"])

    second = client.get(f"{PREFIX}/runs/{run_id}/$logs", params={"after": first["next"], "limit": 2}).json()
    assert [row["message"] for row in second["items"]] == ["line 2"]
    assert second["next"] is None

    assert client.get(f"{PREFIX}/runs/{run_id}/$logs", params={"after": "half-past"}).status_code == 422


def test_a_version_cursor_walks_a_pipelines_history(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    apply_document(client, DOCUMENT.replace("argv: [echo, goodbye]", "argv: [echo, so long]"))
    apply_document(client, DOCUMENT.replace("argv: [echo, goodbye]", "argv: [echo, farewell then]"))

    first = client.get(f"{PREFIX}/pipelines/api-demo/versions", params={"limit": 2}).json()
    assert [row["version"] for row in first["items"]] == [3, 2]
    assert first["next"] == "2"

    second = client.get(f"{PREFIX}/pipelines/api-demo/versions", params={"after": first["next"], "limit": 2}).json()
    assert [row["version"] for row in second["items"]] == [1]
    assert second["next"] is None


def test_a_reconnect_resumes_the_log_tail_from_the_last_event_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A browser resends the id it last saw; the tail continues past it rather than from the top."""
    from dirigent_server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "FOLLOW_INTERVAL_SECONDS", INTERVAL)
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    began = datetime(2026, 1, 1, tzinfo=UTC)
    rows_written(client, log_row(run_id, greet, "first", began), log_row(run_id, greet, "second", began))

    def settle() -> None:
        """Land one more line and end the run while the first stream is open."""
        time.sleep(REPLAYED)
        rows_written(
            client,
            log_row(run_id, greet, "third", began + timedelta(seconds=1)),
            sa.update(Run)
            .where(Run.id == run_id)
            .values(status=RunStatus.SUCCEEDED, finished_at=began + timedelta(seconds=2)),
        )

    writer = threading.Thread(target=settle)
    writer.start()
    try:
        with client.stream("GET", f"{PREFIX}/runs/{run_id}/$logs", params={"follow": "sse"}) as response:
            delivered = sse_frames(response.iter_lines())
    finally:
        writer.join()

    logs = [(ident, data["message"]) for name, ident, data in delivered if name == "log"]
    assert [message for _, message in logs] == ["first", "second", "third"]
    assert all(ident is not None for ident, _ in logs), "every log frame names the id a reconnect resumes at"

    with client.stream(
        "GET",
        f"{PREFIX}/runs/{run_id}/$logs",
        params={"follow": "sse"},
        headers={"Last-Event-ID": str(logs[0][0])},
    ) as response:
        resumed = sse_frames(response.iter_lines())
    assert [data["message"] for name, _, data in resumed if name == "log"] == ["second", "third"]

    with client.stream(
        "GET",
        f"{PREFIX}/runs/{run_id}/$logs",
        params={"follow": "sse"},
        headers={"Last-Event-ID": str(logs[-1][0])},
    ) as response:
        caught_up = sse_frames(response.iter_lines())
    assert [name for name, _, _ in caught_up if name == "log"] == [], "nothing delivered is sent a second time"


def test_an_explicit_cursor_wins_over_the_header_a_reconnect_resent(client: TestClient) -> None:
    """``after`` is what a caller asked for; the header is only the fallback."""
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    began = datetime(2026, 1, 1, tzinfo=UTC)
    rows_written(client, log_row(run_id, greet, "first", began), log_row(run_id, greet, "second", began))
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    entries = client.get(f"{PREFIX}/runs/{run_id}/$logs").json()["items"]

    with client.stream(
        "GET",
        f"{PREFIX}/runs/{run_id}/$logs",
        params={"follow": "sse", "after": "0"},
        headers={"Last-Event-ID": str(entries[-1]["id"])},
    ) as response:
        story = sse_frames(response.iter_lines())
    assert [data["message"] for name, _, data in story if name == "log"] == ["first", "second"]
    refused = client.get(
        f"{PREFIX}/runs/{run_id}/$logs",
        params={"follow": "sse"},
        headers={"Last-Event-ID": "not a cursor"},
    )
    assert refused.status_code == 422


def test_only_a_log_frame_of_the_event_stream_carries_an_id(client: TestClient) -> None:
    """Attempts and the run are replayed on connect, so an id on one would skip a state."""
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    rows_written(client, log_row(run_id, greet, "hello", datetime(2026, 1, 1, tzinfo=UTC)))
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
        story = sse_frames(response.iter_lines())
    assert {name for name, ident, _ in story if ident is not None} == {"log"}
    assert [ident for name, ident, _ in story if name in {"attempt", "run", "end"}] == [None] * len(
        [name for name, _, _ in story if name in {"attempt", "run", "end"}]
    )


def test_the_event_stream_resumes_its_logs_from_the_last_event_id(client: TestClient) -> None:
    """The log cursor is restored and the attempts replay, which the client dedupes by id."""
    run_id = started_run(client)
    greet = attempt_id(client, run_id, "greet")
    rows_written(client, log_row(run_id, greet, "hello", datetime(2026, 1, 1, tzinfo=UTC)))
    client.post(f"{PREFIX}/runs/{run_id}/$cancel")
    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events") as response:
        first = sse_frames(response.iter_lines())
    seen = [ident for name, ident, _ in first if name == "log"]
    assert seen and seen[-1] is not None

    with client.stream("GET", f"{PREFIX}/runs/{run_id}/$events", headers={"Last-Event-ID": str(seen[-1])}) as response:
        again = sse_frames(response.iter_lines())
    assert [name for name, _, _ in again if name == "log"] == [], "the line already delivered is not repeated"
    assert [name for name, _, _ in again if name == "attempt"] != [], "attempts replay, and the client dedupes them"
