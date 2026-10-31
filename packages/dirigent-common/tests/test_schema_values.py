"""Tests for the validator a run's values are checked with, and the bound it runs under."""

import threading
from datetime import timedelta
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dirigent_common import LOCAL_REFERENCES, EvaluationOverrun, ValueValidator, bounded_evaluation


def _said(validator: Any, value: Any) -> list[tuple[str, str]]:
    """Every error a validator raises over a value, as where and what, in a stable order."""
    return sorted((error.json_path, error.message) for error in validator.iter_errors(value))


#: Schemas over each keyword the validator replaces, with a value each refuses or passes.
REPLACED: list[tuple[Any, Any]] = [
    ({"pattern": "^a+$"}, "ab"),
    ({"pattern": "^a+$"}, "a\n"),
    ({"pattern": r"^\d+$"}, "\u0663"),
    ({"patternProperties": {"^x": {"type": "string"}}}, {"xa": 1, "b": 2}),
    ({"propertyNames": {"pattern": "^[a-z]+$"}}, {"aB": 1, "ok": 2}),
    ({"additionalProperties": False, "patternProperties": {"^x": {}}}, {"xa": 1, "b": 2, "c": 3}),
    ({"additionalProperties": False, "properties": {"a": {}}}, {"a": 1, "b": 2}),
    ({"additionalProperties": {"type": "string"}, "patternProperties": {"^x": {}}}, {"xa": 1, "b": 2}),
    ({"prefixItems": [{}], "unevaluatedItems": False}, [1, 2, 3]),
    ({"prefixItems": [{}], "unevaluatedItems": {"type": "string"}}, [1, 2, "x"]),
    ({"contains": {"type": "string"}, "unevaluatedItems": False}, [1, "x"]),
    ({"items": {"type": "integer"}, "unevaluatedItems": False}, [1, 2]),
    (
        {
            "if": {"minItems": 2},
            "then": {"prefixItems": [{}, {}]},
            "else": {"prefixItems": [{}]},
            "unevaluatedItems": False,
        },
        [1, 2, 3],
    ),
    ({"anyOf": [{"prefixItems": [{}, {}]}], "unevaluatedItems": False}, [1, 2, 3]),
    ({"$defs": {"p": {"prefixItems": [{}]}}, "$ref": "#/$defs/p", "unevaluatedItems": False}, [1, 2]),
    ({"properties": {"a": {}}, "unevaluatedProperties": False}, {"a": 1, "b": 2, "c": 3}),
    ({"properties": {"a": {}}, "unevaluatedProperties": {"type": "string"}}, {"a": 1, "b": 2, "c": "x"}),
    ({"patternProperties": {"^x": {}}, "unevaluatedProperties": False}, {"xa": 1, "b": 2}),
    ({"additionalProperties": {"type": "integer"}, "unevaluatedProperties": False}, {"a": 1, "b": "x"}),
    (
        {
            "if": {"required": ["a"]},
            "then": {"properties": {"b": {}}},
            "else": {"properties": {"c": {}}},
            "unevaluatedProperties": False,
        },
        {"a": 1, "b": 2, "c": 3},
    ),
    ({"dependentSchemas": {"a": {"properties": {"b": {}}}}, "unevaluatedProperties": False}, {"a": 1, "b": 2}),
    (
        {
            "allOf": [{"properties": {"a": {}}}],
            "oneOf": [{"properties": {"b": {}}}],
            "unevaluatedProperties": False,
        },
        {"a": 1, "b": 2, "c": 3},
    ),
    (
        {"$defs": {"p": {"properties": {"a": {}}}}, "$ref": "#/$defs/p", "unevaluatedProperties": False},
        {"a": 1, "z": 2},
    ),
    ({"properties": {"n": {"properties": {"a": {}}, "unevaluatedProperties": False}}}, {"n": {"a": 1, "b": 2}}),
]


@pytest.mark.parametrize(("schema", "value"), REPLACED)
def test_the_keywords_it_replaces_say_what_the_library_says(schema: Any, value: Any) -> None:
    ours = _said(ValueValidator(schema, registry=LOCAL_REFERENCES), value)
    assert ours == _said(Draft202012Validator(schema, registry=LOCAL_REFERENCES), value)


def test_a_match_past_the_deadline_raises_rather_than_answering() -> None:
    validator = ValueValidator({"pattern": "^(a|aa)+$"}, registry=LOCAL_REFERENCES)
    with pytest.raises(EvaluationOverrun) as raised, bounded_evaluation(timedelta(milliseconds=100)):
        list(validator.iter_errors("a" * 60 + "!"))
    assert raised.value.within == timedelta(milliseconds=100)


def test_an_evaluation_whose_caller_stopped_raises_at_its_next_keyword() -> None:
    stopped = threading.Event()
    stopped.set()
    validator = ValueValidator({"type": "string"}, registry=LOCAL_REFERENCES)
    with pytest.raises(EvaluationOverrun), bounded_evaluation(timedelta(minutes=1), stopped):
        list(validator.iter_errors("value"))


def test_outside_a_bound_an_evaluation_runs_to_its_end() -> None:
    validator = ValueValidator({"pattern": "^a+$"}, registry=LOCAL_REFERENCES)
    assert validator.is_valid("aaa")
    assert not validator.is_valid("aab")
