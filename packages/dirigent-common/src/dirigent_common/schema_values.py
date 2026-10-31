"""The validator a run's values are checked with, and the bound every evaluation runs under.

Draft 2020-12, saying what the library says, with these differences in how:

* ``uniqueItems`` compares each element's canonical text through a set, under JSON Schema's rule
  of equality: ``1`` and ``1.0`` are equal, ``true`` and ``1`` are not, and an object's keys have
  no order.
* ``unevaluatedItems`` and ``unevaluatedProperties`` look up what was evaluated in a set.
* ``pattern``, ``patternProperties``, and the patterns ``additionalProperties`` and
  ``unevaluatedProperties`` read match with the ``regex`` package in its ``re``-compatible mode,
  which releases the interpreter's lock while it matches and stops at the evaluation's deadline.
* Every keyword checks the bound :func:`bounded_evaluation` sets before it runs, and raises
  :class:`EvaluationOverrun` once the deadline has passed or the caller has stopped waiting.

Outside :func:`bounded_evaluation` nothing is bounded.
"""

import json
import threading
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from functools import lru_cache
from typing import Any, Final

import regex
from jsonschema import Draft202012Validator, ValidationError
from jsonschema.validators import extend as extend_validator  # pyright: ignore[reportUnknownVariableType]
from pydantic import JsonValue

from dirigent_common.durations import format_duration

#: The keyword signature the library calls: validator, the keyword's value, instance, schema.
type Keyword = Callable[[Any, Any, Any, Any], Any]


class EvaluationOverrun(Exception):
    """An evaluation that passed its deadline, or whose caller stopped waiting for it."""

    def __init__(self, within: timedelta) -> None:
        """Name the bound the evaluation passed."""
        super().__init__(f"the evaluation did not finish within {format_duration(within)}")
        self.within = within


class _Bound:
    """When the current evaluation must stop, and the event that stops it sooner."""

    __slots__ = ("deadline", "stopped", "within")

    def __init__(self, within: timedelta, stopped: threading.Event | None) -> None:
        self.within = within
        self.deadline = time.monotonic() + within.total_seconds()
        self.stopped = stopped


_BOUND: ContextVar[_Bound | None] = ContextVar("dirigent_schema_value_bound", default=None)


@contextmanager
def bounded_evaluation(within: timedelta, stopped: threading.Event | None = None) -> Generator[None]:
    """Bound every evaluation inside the block to ``within``, and to ``stopped`` staying unset.

    The bound is held in a context variable, so it covers the thread or task that entered the
    block and nothing else.
    """
    token = _BOUND.set(_Bound(within, stopped))
    try:
        yield
    finally:
        _BOUND.reset(token)


def _remaining(bound: _Bound | None) -> float | None:
    """Seconds an evaluation under ``bound`` has left, or None when it is unbounded.

    Raises:
        EvaluationOverrun: The deadline has passed, or the caller has stopped waiting.
    """
    if bound is None:
        return None
    left = bound.deadline - time.monotonic()
    if left <= 0 or (bound.stopped is not None and bound.stopped.is_set()):
        raise EvaluationOverrun(bound.within)
    return left


@lru_cache(maxsize=512)
def _compiled(pattern: str) -> "regex.Pattern[str]":
    """Compile a schema's pattern with ``re``'s syntax and meaning."""
    return regex.compile(pattern, regex.VERSION0)


def _found(pattern: str, text: str) -> bool:
    """Whether ``pattern`` matches anywhere in ``text``, within what the evaluation has left.

    The match releases the interpreter's lock while it runs.
    """
    bound = _BOUND.get()
    left = _remaining(bound)
    try:
        return _compiled(pattern).search(text, concurrent=True, timeout=left) is not None
    except TimeoutError as error:
        raise EvaluationOverrun(bound.within if bound is not None else timedelta(0)) from error


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


def _extras(extras: list[Any]) -> tuple[str, str]:
    """The library's wording for the items or properties a keyword did not expect."""
    return ", ".join(repr(extra) for extra in extras), "was" if len(extras) == 1 else "were"


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


def _pattern(validator: Any, pattern: str, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Say what the library's ``pattern`` says."""
    if validator.is_type(instance, "string") and not _found(pattern, instance):
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


def _pattern_properties(validator: Any, patterns: Any, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Say what the library's ``patternProperties`` says."""
    if not validator.is_type(instance, "object"):
        return
    for pattern, subschema in patterns.items():
        for key, value in instance.items():
            if _found(pattern, key):
                yield from validator.descend(value, subschema, path=key, schema_path=pattern)


def _additional(instance: Any, schema: Any) -> list[str]:
    """The keys of ``instance`` neither ``properties`` nor ``patternProperties`` names, in order."""
    properties = schema.get("properties", {})
    patterns = list(schema.get("patternProperties", {}))
    return [key for key in instance if key not in properties and not any(_found(pattern, key) for pattern in patterns)]


def _additional_properties(validator: Any, extra: Any, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Say what the library's ``additionalProperties`` says."""
    if not validator.is_type(instance, "object"):
        return
    extras = set(_additional(instance, schema))
    if validator.is_type(extra, "object"):
        for key in extras:
            yield from validator.descend(instance[key], extra, path=key)
    elif not extra and extras:
        if "patternProperties" in schema:
            verb = "does" if len(extras) == 1 else "do"
            joined = ", ".join(repr(key) for key in sorted(extras))
            patterns = ", ".join(repr(pattern) for pattern in sorted(schema["patternProperties"]))
            yield ValidationError(f"{joined} {verb} not match any of the regexes: {patterns}")
        else:
            listed, verb = _extras(sorted(extras, key=str))
            yield ValidationError(f"Additional properties are not allowed ({listed} {verb} unexpected)")


def _referenced(validator: Any, schema: Any) -> Iterator[tuple[Any, Any]]:
    """The validator and schema each of ``$ref`` and ``$dynamicRef`` in ``schema`` leads to."""
    for keyword in ("$ref", "$dynamicRef"):
        reference = schema.get(keyword)
        if reference is not None:
            resolved = validator._resolver.lookup(reference)
            yield validator.evolve(schema=resolved.contents, _resolver=resolved.resolver), resolved.contents


def _is_valid(errors: Iterator[ValidationError]) -> bool:
    """Whether an iterator of errors yields none."""
    return next(errors, None) is None


def _evaluated_indexes(validator: Any, instance: Any, schema: Any) -> set[int]:
    """The indexes of ``instance`` that ``schema`` evaluates, as the library finds them."""
    if validator.is_type(schema, "boolean"):
        return set()
    if "items" in schema:
        return set(range(len(instance)))
    evaluated: set[int] = set()
    for referred, contents in _referenced(validator, schema):
        evaluated |= _evaluated_indexes(referred, instance, contents)
    if "prefixItems" in schema:
        evaluated.update(range(len(schema["prefixItems"])))
    if "if" in schema:
        if validator.evolve(schema=schema["if"]).is_valid(instance):
            evaluated |= _evaluated_indexes(validator, instance, schema["if"])
            if "then" in schema:
                evaluated |= _evaluated_indexes(validator, instance, schema["then"])
        elif "else" in schema:
            evaluated |= _evaluated_indexes(validator, instance, schema["else"])
    for keyword in ("contains", "unevaluatedItems"):
        if keyword in schema:
            checker = validator.evolve(schema=schema[keyword])
            evaluated.update(index for index, item in enumerate(instance) if checker.is_valid(item))
    for keyword in ("allOf", "oneOf", "anyOf"):
        for subschema in schema.get(keyword, ()):
            if _is_valid(validator.descend(instance, subschema)):
                evaluated |= _evaluated_indexes(validator, instance, subschema)
    return evaluated


def _evaluated_keys(validator: Any, instance: Any, schema: Any) -> set[str]:
    """The keys of ``instance`` that ``schema`` evaluates, as the library finds them."""
    if validator.is_type(schema, "boolean"):
        return set()
    evaluated: set[str] = set()
    for referred, contents in _referenced(validator, schema):
        evaluated |= _evaluated_keys(referred, instance, contents)
    properties = schema.get("properties")
    if validator.is_type(properties, "object"):
        evaluated |= properties.keys() & instance.keys()
    for keyword in ("additionalProperties", "unevaluatedProperties"):
        subschema = schema.get(keyword)
        if subschema is not None:
            evaluated.update(key for key, value in instance.items() if _is_valid(validator.descend(value, subschema)))
    if "patternProperties" in schema:
        patterns = list(schema["patternProperties"])
        evaluated.update(key for key in instance if any(_found(pattern, key) for pattern in patterns))
    for key, subschema in schema.get("dependentSchemas", {}).items():
        if key in instance:
            evaluated |= _evaluated_keys(validator, instance, subschema)
    for keyword in ("allOf", "oneOf", "anyOf"):
        for subschema in schema.get(keyword, ()):
            if _is_valid(validator.descend(instance, subschema)):
                evaluated |= _evaluated_keys(validator, instance, subschema)
    if "if" in schema:
        if validator.evolve(schema=schema["if"]).is_valid(instance):
            evaluated |= _evaluated_keys(validator, instance, schema["if"])
            if "then" in schema:
                evaluated |= _evaluated_keys(validator, instance, schema["then"])
        elif "else" in schema:
            evaluated |= _evaluated_keys(validator, instance, schema["else"])
    return evaluated


def _unevaluated_items(validator: Any, unevaluated: Any, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Say what the library's ``unevaluatedItems`` says."""
    if not validator.is_type(instance, "array"):
        return
    evaluated = _evaluated_indexes(validator, instance, schema)
    left = [item for index, item in enumerate(instance) if index not in evaluated]
    if left:
        listed, verb = _extras(left)
        yield ValidationError(f"Unevaluated items are not allowed ({listed} {verb} unexpected)")


def _unevaluated_properties(validator: Any, unevaluated: Any, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """Say what the library's ``unevaluatedProperties`` says."""
    if not validator.is_type(instance, "object"):
        return
    evaluated = _evaluated_keys(validator, instance, schema)
    refused: list[str] = []
    for key in instance:
        if key not in evaluated:
            refused.extend(key for _ in validator.descend(instance[key], unevaluated, path=key, schema_path=key))
    if not refused:
        return
    if unevaluated is False:
        listed, verb = _extras(sorted(refused, key=str))
        yield ValidationError(f"Unevaluated properties are not allowed ({listed} {verb} unexpected)")
    else:
        listed, verb = _extras(refused)
        yield ValidationError(
            f"Unevaluated properties are not valid under the given schema ({listed} {verb} unevaluated and invalid)"
        )


def _watched(keyword: Keyword) -> Keyword:
    """Run ``keyword`` only while the evaluation's bound holds."""

    def watched(validator: Any, value: Any, instance: Any, schema: Any) -> Any:
        _remaining(_BOUND.get())
        return keyword(validator, value, instance, schema)

    return watched


_KEYWORDS: Final[dict[str, Keyword]] = {
    **Draft202012Validator.VALIDATORS,
    "additionalProperties": _additional_properties,
    "pattern": _pattern,
    "patternProperties": _pattern_properties,
    "unevaluatedItems": _unevaluated_items,
    "unevaluatedProperties": _unevaluated_properties,
    "uniqueItems": _unique_items,
}

#: Draft 2020-12 with those keywords. Naming the version also makes this the class a subschema
#: naming that ``$schema`` resolves to, which a ``$ref`` back to the root would be.
ValueValidator: Final[Any] = extend_validator(  # pyright: ignore[reportUnknownVariableType]
    Draft202012Validator,
    {name: _watched(keyword) for name, keyword in _KEYWORDS.items()},
    version="draft2020-12",
)

__all__ = ["EvaluationOverrun", "ValueValidator", "bounded_evaluation", "canonical_json"]
