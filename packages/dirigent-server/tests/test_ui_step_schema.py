"""The web UI's step form, held to the step definition it draws.

The editor's step section draws its controls from ``frontend/src/lib/step-schema.json``: one
shape per engine member of a step and of its retry policy. Those shapes copy
``StepDefinition`` and ``RetryPolicy``, so these tests read the file against the schema the
definition publishes and fail on any member, bound, default or choice that parts from it.
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from dirigent_common.durations import HumaneJsonSchema
from dirigent_core.engine.definition import RetryPolicy, StepDefinition

SHAPES_PATH = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "step-schema.json"

#: Step members the editor reads and writes through its own controls rather than this form.
EDITED_ELSEWHERE = {"name", "description", "block", "source", "reply", "depends_on", "config", "retry", "sample"}

#: The keywords a shape may carry, each of which must say what the definition says.
COMPARED = ("type", "enum", "default", "minimum", "maximum", "format")

type Schema = dict[str, Any]


def shapes() -> dict[str, dict[str, Schema]]:
    """The form's shapes, under ``step`` and ``retry``."""
    return cast("dict[str, dict[str, Schema]]", json.loads(SHAPES_PATH.read_text(encoding="utf-8")))


def published(model: type[StepDefinition] | type[RetryPolicy]) -> Schema:
    """A model's schema, built the way every schema dirigent publishes is built."""
    return model.model_json_schema(schema_generator=HumaneJsonSchema)


def resolved(member: Schema, definitions: Schema) -> Schema:
    """One member's schema with its reference followed and the null branch dropped.

    A member that is optional on the definition is ``anyOf`` with ``null``, and a form shows an
    absent value as an empty control; what remains is the shape a value takes when it is there.
    A member whose value may take several shapes keeps them as ``anyOf``.
    """
    merged = dict(member)
    reference = merged.pop("$ref", None)
    if reference is not None:
        merged = {**definitions[reference.rsplit("/", 1)[-1]], **merged}
    branches = merged.pop("anyOf", None)
    if branches is None:
        return merged
    kept = [resolved(branch, definitions) for branch in branches if branch != {"type": "null"}]
    if len(kept) == 1:
        return {**kept[0], **merged}
    return {**merged, "anyOf": kept}


def members(model: type[StepDefinition] | type[RetryPolicy]) -> dict[str, Schema]:
    """Every member of a model, resolved, in the order the model declares them."""
    schema = published(model)
    definitions = cast("Schema", schema.get("$defs", {}))
    properties = cast("dict[str, Schema]", schema["properties"])
    return {name: resolved(member, definitions) for name, member in properties.items()}


def disagreements(form: dict[str, Schema], definition: dict[str, Schema]) -> list[str]:
    """Every keyword where a form shape says something its member does not."""
    found: list[str] = []
    for name, shape in form.items():
        member = definition[name]
        branches = cast("list[Schema]", member.get("anyOf", [member]))
        for keyword in COMPARED:
            if keyword not in shape:
                continue
            if keyword == "default":
                if member.get("default") != shape["default"]:
                    found.append(f"{name}.default: {shape['default']!r} != {member.get('default')!r}")
                continue
            said = [branch.get(keyword) for branch in branches]
            if shape[keyword] not in said:
                found.append(f"{name}.{keyword}: {shape[keyword]!r} is none of {said!r}")
    return found


@pytest.mark.parametrize(
    ("part", "model"),
    [("step", StepDefinition), ("retry", RetryPolicy)],
)
def test_every_shape_says_what_the_definition_says(part: str, model: type[StepDefinition] | type[RetryPolicy]) -> None:
    """A type, a choice, a bound or a default the form holds is the definition's own."""
    assert disagreements(shapes()[part], members(model)) == []


def test_the_step_form_draws_every_engine_member_in_order() -> None:
    """A member added to the definition is drawn by the form or edited elsewhere."""
    declared = [name for name in members(StepDefinition) if name not in EDITED_ELSEWHERE]
    assert list(shapes()["step"]) == declared


def test_the_retry_form_draws_every_policy_member_in_order() -> None:
    """The retry sub-form holds the policy's members, no more and no fewer."""
    assert list(shapes()["retry"]) == list(members(RetryPolicy))


def test_a_shape_that_parts_from_its_member_is_named() -> None:
    """The comparison names a bound the definition does not have."""
    form = {"max_attempts": {"type": "integer", "maximum": 99}}
    assert disagreements(form, members(RetryPolicy)) == ["max_attempts.maximum: 99 is none of [100]"]
