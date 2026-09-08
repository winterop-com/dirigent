"""The identity quartet across the wire: id, code, name, description.

``code`` is the addressable key: it is what a URL carries, what a document declares, and
what uniqueness is enforced on. ``name`` is display only, so nothing may reference by it and
two rows may share one. These tests hold that split at the boundary, where a rename would
otherwise pass every other test by moving the vocabulary and the assertions together.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests_support import DOCUMENT, apply_document

PREFIX = "/api/v1"

#: The route families whose path parameter addresses one of the five coded entities.
CODED_PREFIXES = (f"{PREFIX}/pipelines/", f"{PREFIX}/connections/", f"{PREFIX}/alert-rules/")


def schemas(client: TestClient) -> dict[str, Any]:
    """Read every component schema the OpenAPI document publishes."""
    document: dict[str, Any] = client.get("/openapi.json").json()
    components: dict[str, Any] = document["components"]["schemas"]
    return components


def properties_of(schema: dict[str, Any]) -> dict[str, Any]:
    """Read one component's properties, which a schema without any simply lacks."""
    found: dict[str, Any] = schema.get("properties") or {}
    return found


def test_no_wire_schema_exposes_display_name(client: TestClient) -> None:
    """``display_name`` was the old spelling of a user's human name, and is gone from the wire."""
    offenders = [
        f"{component}.{field}"
        for component, schema in schemas(client).items()
        for field in properties_of(schema)
        if field == "display_name"
    ]
    assert offenders == [], f"these wire schemas still publish display_name: {offenders}"


def test_no_path_addresses_a_coded_entity_by_name(client: TestClient) -> None:
    """A pipeline, connection or alert rule is addressed by ``{code}`` and never by ``{name}``."""
    document: dict[str, Any] = client.get("/openapi.json").json()
    offenders = [path for path in document["paths"] if path.startswith(CODED_PREFIXES) and "{name}" in path]
    assert offenders == [], f"these paths still address an entity by name: {offenders}"


@pytest.mark.parametrize("component", ["PipelineOut", "ConnectionOut", "ScheduleOut", "WebhookOut", "AlertRuleOut"])
def test_every_coded_entity_publishes_a_code_and_an_optional_name(client: TestClient, component: str) -> None:
    """The key is required; the human name is not, because most rows will never carry one."""
    schema = schemas(client)[component]
    fields = properties_of(schema)
    assert "code" in fields, f"{component} publishes no code"
    assert "name" in fields, f"{component} publishes no name"
    assert "code" in schema.get("required", []), f"{component} does not require its code"
    assert "name" not in schema.get("required", []), f"{component} requires a display name"


def test_two_pipelines_may_share_a_name_but_never_a_code(client: TestClient) -> None:
    """A name carries no identity, so two pipelines may wear the same one at once."""
    apply_document(client, DOCUMENT.replace("code: api-demo", "code: api-one\nname: The daily load"))
    apply_document(client, DOCUMENT.replace("code: api-demo", "code: api-two\nname: The daily load"))

    listed = client.get(f"{PREFIX}/pipelines").json()["items"]
    rows = {row["code"]: row for row in listed}

    assert set(rows) == {"api-one", "api-two"}
    assert rows["api-one"]["name"] == rows["api-two"]["name"] == "The daily load"


def test_reapplying_a_code_writes_a_version_rather_than_a_second_pipeline(client: TestClient) -> None:
    """The code is the identity an apply matches on, so the same code is the same pipeline."""
    first = apply_document(client, DOCUMENT.replace("code: api-demo", "code: api-one\nname: First"))
    second = apply_document(client, DOCUMENT.replace("code: api-demo", "code: api-one\nname: Second"))

    assert first["plan"]["action"] == "create"
    assert second["plan"]["action"] == "update"
    assert [row["code"] for row in client.get(f"{PREFIX}/pipelines").json()["items"]] == ["api-one"]
    assert client.get(f"{PREFIX}/pipelines/api-one").json()["name"] == "Second"


def test_two_connections_may_share_a_name_but_never_a_code(client: TestClient) -> None:
    """The same rule at the other end of the instance: the code is unique, the name is free."""
    body: dict[str, Any] = {
        "kind": "http",
        "name": "The warehouse",
        "config": {"base_url": "https://example.invalid"},
    }
    assert client.post(f"{PREFIX}/connections", json={**body, "code": "warehouse-eu"}).status_code == 201
    assert client.post(f"{PREFIX}/connections", json={**body, "code": "warehouse-us"}).status_code == 201
    assert client.post(f"{PREFIX}/connections", json={**body, "code": "warehouse-eu"}).status_code == 409

    listed = client.get(f"{PREFIX}/connections").json()["items"]
    assert [row["code"] for row in listed] == ["warehouse-eu", "warehouse-us"]
    assert {row["name"] for row in listed} == {"The warehouse"}
