from datetime import timedelta

import pytest
from jsonschema import FormatChecker

from dirigent_common import Unresolvable, outward_references, reference_targets, schema_code_of, value_errors


@pytest.mark.parametrize(
    ("uri", "code"),
    [
        ("org-unit", "org-unit"),
        ("org-unit#/properties/id", "org-unit"),
        ("https://example.org/schemas/org-unit.json", "org-unit"),
        ("https://example.org/schemas/Org_Unit", None),
        ("#/$defs/id", None),
    ],
)
def test_a_uri_names_the_code_in_its_last_segment(uri: str, code: str | None) -> None:
    assert schema_code_of(uri) == code


def test_a_schema_s_outward_references_are_resolved_against_its_id() -> None:
    schema = {
        "$id": "https://example.org/schemas/reading.json",
        "$defs": {"id": {"type": "string"}},
        "properties": {
            "id": {"$ref": "#/$defs/id"},
            "station": {"$ref": "station-code.json"},
            "self": {"$ref": "https://example.org/schemas/reading.json"},
            "items": {"type": "array", "items": [{"$ref": "unit#/properties/x"}]},
            "$ref": {"type": "string"},
        },
    }
    assert outward_references(schema) == {
        "https://example.org/schemas/station-code.json",
        "https://example.org/schemas/unit",
    }


def test_an_address_reaches_a_held_schema_only_through_its_exact_id() -> None:
    held = {
        "address": {"type": "object"},
        "station-code": {"$id": "https://example.org/schemas/station-code.json", "type": "string"},
    }
    bare = {"properties": {"a": {"$ref": "address"}}}
    assert reference_targets(bare, held.get) == ({"address"}, set())
    outside = {"properties": {"a": {"$ref": "https://other.example/schemas/address.json"}}}
    assert reference_targets(outside, held.get) == (set(), {"https://other.example/schemas/address.json"})
    sibling = {"$id": "https://example.org/schemas/reading.json", "properties": {"s": {"$ref": "station-code.json"}}}
    assert reference_targets(sibling, held.get) == ({"station-code"}, set())


def test_a_reference_reaches_only_what_is_held() -> None:
    held = {"station-code": {"type": "string", "pattern": "^[A-Z]{3}[0-9]{2}$"}}
    schema = {"properties": {"station": {"$ref": "station-code"}}}
    errors = value_errors(
        schema, {"station": "oslo"}, format_checker=FormatChecker(), within=timedelta(seconds=5), held=held.get
    )
    assert [error.json_path for error in errors] == ["$.station"]
    with pytest.raises(Unresolvable):
        value_errors(schema, {"station": "oslo"}, format_checker=FormatChecker(), within=timedelta(seconds=5))
    with pytest.raises(Unresolvable):
        value_errors(
            {"$ref": "https://other.example/schemas/station-code"},
            "OSL01",
            format_checker=FormatChecker(),
            within=timedelta(seconds=5),
            held=held.get,
        )
