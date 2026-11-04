"""``POST /schemas/$check``: a value against a stored schema or an unsaved body, writing nothing."""

from typing import Any

from fastapi.testclient import TestClient

PREFIX = "/api/v1"

READING: dict[str, Any] = {
    "$id": "reading",
    "type": "object",
    "required": ["id"],
    "properties": {
        "id": {"type": "string"},
        "age": {"type": "integer", "minimum": 0},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


def stored(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post(f"{PREFIX}/schemas", json={"body": body}).status_code == 201


def checked(client: TestClient, **payload: Any) -> Any:
    response = client.post(f"{PREFIX}/schemas/$check", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def refused(client: TestClient, status: int, **payload: Any) -> str:
    response = client.post(f"{PREFIX}/schemas/$check", json=payload)
    assert response.status_code == status, response.text
    return str(response.json()["code"])


def test_a_value_that_fits_a_stored_schema_is_valid(client: TestClient) -> None:
    stored(client, READING)
    assert checked(client, code="reading", value={"id": "a", "age": 3}) == {"valid": True, "errors": [], "omitted": 0}


def test_every_failure_is_named_by_where_it_is_in_the_value_and_in_the_schema(client: TestClient) -> None:
    stored(client, READING)
    answer = checked(client, code="reading", value={"age": -1, "tags": ["a", 3]})
    assert answer["valid"] is False
    assert [(one["at"], one["keyword"], one["schema_at"]) for one in answer["errors"]] == [
        ("", "required", "/required"),
        ("/age", "minimum", "/properties/age/minimum"),
        ("/tags/1", "type", "/properties/tags/items/type"),
    ]
    assert all(one["message"] for one in answer["errors"])


def test_a_pointer_escapes_the_characters_a_pointer_reserves(client: TestClient) -> None:
    body = {"type": "object", "properties": {"a/b~c": {"type": "string"}}}
    answer = checked(client, body=body, value={"a/b~c": 1})
    assert [one["at"] for one in answer["errors"]] == ["/a~1b~0c"]


def test_an_unsaved_body_is_checked_rather_than_what_is_stored(client: TestClient) -> None:
    stored(client, READING)
    loosened: dict[str, Any] = {**READING, "required": []}
    assert checked(client, body=loosened, value={})["valid"] is True
    assert checked(client, code="reading", value={})["valid"] is False
    assert client.get(f"{PREFIX}/schemas/reading").json()["body"]["required"] == ["id"], "nothing was written"


def test_null_is_a_value_like_any_other(client: TestClient) -> None:
    answer = checked(client, body={"type": "object"}, value=None)
    assert [(one["at"], one["keyword"]) for one in answer["errors"]] == [("", "type")]


def test_a_reference_inside_the_schema_is_followed(client: TestClient) -> None:
    body = {"$defs": {"id": {"type": "string"}}, "properties": {"id": {"$ref": "#/$defs/id"}}}
    answer = checked(client, body=body, value={"id": 7})
    assert [(one["at"], one["schema_at"]) for one in answer["errors"]] == [("/id", "/properties/id/type")]


def test_a_reference_to_another_stored_schema_is_followed_by_its_code(client: TestClient) -> None:
    """A ``$ref`` naming a held code reaches that schema, as a run's reaches the ones it pinned."""
    stored(client, READING)
    body = {"type": "object", "properties": {"reading": {"$ref": "reading"}}}
    assert checked(client, body=body, value={"reading": {"id": "a"}})["valid"] is True
    answer = checked(client, body=body, value={"reading": {}})
    assert [(one["at"], one["keyword"]) for one in answer["errors"]] == [("/reading", "required")]


def test_an_address_reaches_a_held_schema_only_through_its_exact_id(client: TestClient) -> None:
    """A link to some outside schema that ends in a held code is not quietly checked against it."""
    stored(client, READING)
    stored(client, {"$id": "https://example.org/schemas/unit.json", "type": "object", "required": ["id"]})
    sibling = {"$id": "https://example.org/schemas/wrapper.json", "properties": {"unit": {"$ref": "unit.json"}}}
    assert checked(client, body=sibling, value={"unit": {}})["valid"] is False
    outside = {"properties": {"reading": {"$ref": "https://other.example/schemas/reading.json"}}}
    assert refused(client, 422, body=outside, value={"reading": {}}) == "schema.reference_unresolved"


def test_a_reference_to_a_code_nothing_holds_is_refused(client: TestClient) -> None:
    body = {"type": "object", "properties": {"reading": {"$ref": "no-such-shape"}}}
    assert refused(client, 422, body=body, value={"reading": {}}) == "schema.reference_unresolved"


def test_a_schema_another_references_cannot_be_deleted(client: TestClient) -> None:
    stored(client, READING)
    stored(client, {"$id": "wrapper", "properties": {"reading": {"$ref": "reading"}}})
    answer = client.delete(f"{PREFIX}/schemas/reading")
    assert answer.status_code == 409
    assert answer.json()["code"] == "schema.referenced"
    assert client.delete(f"{PREFIX}/schemas/wrapper").status_code == 204
    assert client.delete(f"{PREFIX}/schemas/reading").status_code == 204


def test_a_body_that_is_not_a_schema_is_refused_before_the_value_is_read(client: TestClient) -> None:
    assert refused(client, 422, body={"type": "not-a-type"}, value={}) == "schema.invalid"


def test_one_schema_is_named(client: TestClient) -> None:
    stored(client, READING)
    assert refused(client, 422, value={}) == "schema.check_names_one"
    assert refused(client, 422, code="reading", body={}, value={}) == "schema.check_names_one"


def test_a_code_nothing_holds_is_not_found(client: TestClient) -> None:
    assert refused(client, 404, code="nothing-here", value={}) == "server.no_schema"


def test_failures_past_a_hundred_are_counted(client: TestClient) -> None:
    answer = checked(client, body={"items": {"type": "string"}}, value=list(range(150)))
    assert (len(answer["errors"]), answer["omitted"]) == (100, 50)


def test_a_viewer_may_check(client: TestClient, viewer: TestClient) -> None:
    stored(client, READING)
    assert checked(viewer, code="reading", value={"id": "a"})["valid"] is True


def test_a_pipeline_naming_a_schema_uses_the_ones_it_references(client: TestClient) -> None:
    stored(client, READING)
    stored(client, {"$id": "wrapper", "properties": {"reading": {"$ref": "reading"}}})
    document = {
        "format": "dirigent/v1",
        "code": "wrapped-gate",
        "requires": {"schemas": ["wrapper"]},
        "steps": {
            "gate": {"block": "validate.schema", "config": {"input": {"reading": {"id": "a"}}, "schema": "wrapper"}}
        },
    }
    applied = client.post(f"{PREFIX}/pipelines/$apply", json={"document": document})
    assert applied.status_code in (200, 201), applied.text
    assert client.get(f"{PREFIX}/schemas/reading").json()["used_by"] == ["wrapped-gate"]
    assert client.get(f"{PREFIX}/schemas/wrapper").json()["used_by"] == ["wrapped-gate"]
