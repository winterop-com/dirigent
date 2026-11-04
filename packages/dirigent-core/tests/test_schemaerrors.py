"""A schema's refusal of a value says what to write instead, where it can tell."""

from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, ValidationError

from dirigent_core.schemaerrors import describe

PERIODS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "period": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
        "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "shape": {"anyOf": [{"type": "object", "required": ["id"]}, {"type": "null"}]},
    },
}


def refused(schema: dict[str, Any], value: object) -> ValidationError:
    validator: Any = Draft202012Validator(schema)
    [error] = list(validator.iter_errors(value))
    return cast("ValidationError", error)


def said(value: dict[str, Any]) -> str:
    return describe(refused(PERIODS, value))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"period": 202501}, "202501 is a number; write it quoted, '202501'"),
        ({"period": [202501, 202502]}, "202501 and 202502 are numbers; write each quoted, as '202501'"),
        ({"period": ["202501", 202502]}, "202502 is a number; write it quoted, '202502'"),
        ({"period": [1, 2, 3, 4, 5]}, "1, 2, 3 and 2 more are numbers; write each quoted, as '1'"),
        ({"period": [1, True]}, "1 and true are not text; write each quoted, as '1'"),
        ({"period": {"a": 1}}, "{'a': 1} is none of what this field takes: a string, a list or null"),
        ({"period": [{"a": 1}]}, "{'a': 1} is not of type 'string' (at 0)"),
        ({"limit": "x"}, "'x' is none of what this field takes: an integer or null"),
        ({"shape": {}}, "'id' is a required property"),
    ],
)
def test_a_refusal_names_what_to_write(value: dict[str, Any], expected: str) -> None:
    assert said(value) == expected


def test_a_plain_type_refusal_of_a_bare_number_is_told_to_quote_it() -> None:
    assert describe(refused({"type": "string"}, 7)) == "7 is a number; write it quoted, '7'"


def test_a_refusal_quoting_cannot_fix_keeps_jsonschema_s_sentence() -> None:
    error = refused({"type": "string", "minLength": 3}, "ab")
    assert describe(error) == error.message
