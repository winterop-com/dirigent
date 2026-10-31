"""The validator a run's values are checked with, whose cost stays in step with the value's size.

The library's ``uniqueItems`` compares every pair of elements of an array it cannot sort, and one
string among integers is enough to stop it sorting. This one compares each element's canonical
text through a set, under JSON Schema's rule of equality: ``1`` and ``1.0`` are equal, ``true``
and ``1`` are not, and an object's keys have no order.
"""

import json
from collections.abc import Iterator
from typing import Any, Final

from jsonschema import Draft202012Validator, ValidationError
from jsonschema.validators import extend as extend_validator  # pyright: ignore[reportUnknownVariableType]
from pydantic import JsonValue


def canonical_json(value: JsonValue) -> str:
    """Write a JSON value so two values have the same text exactly when JSON Schema calls them equal."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(element) for element in value) + "]"
    if isinstance(value, dict):
        members = sorted(f"{json.dumps(key)}:{canonical_json(element)}" for key, element in value.items())
        return "{" + ",".join(members) + "}"
    return json.dumps(value)


def _unique_items(validator: Any, wanted: Any, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Say what the library's ``uniqueItems`` says, comparing through a set of canonical text."""
    if not wanted or not validator.is_type(instance, "array"):
        return
    seen: set[str] = set()
    for element in instance:
        text = canonical_json(element)
        if text in seen:
            yield ValidationError(f"{instance!r} has non-unique elements")
            return
        seen.add(text)


#: Draft 2020-12 with that one keyword replaced. Naming the version also makes this the class a
#: subschema naming that ``$schema`` resolves to, which a ``$ref`` back to the root would be.
ValueValidator: Final[Any] = extend_validator(  # pyright: ignore[reportUnknownVariableType]
    Draft202012Validator, {"uniqueItems": _unique_items}, version="draft2020-12"
)

__all__ = ["ValueValidator", "canonical_json"]
