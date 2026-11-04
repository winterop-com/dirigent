"""Reads of a step's output field that the step's block says its output never has.

A block whose output schema is closed names every field its output can carry, so a reference
or a template reading another one is a typo: a reference fails at run time, and a template
renders it empty. Each is a warning at plan, never a refusal, and only where the schema says
so for certain: a path through an open object, a list, a union or anything untyped is not
judged.
"""

from collections.abc import Iterator, Mapping
from typing import Any, Final, cast

import jinja2
import jinja2.meta
from jinja2 import nodes
from pydantic import JsonValue

from dirigent_client.schemas import Catalog, ValidationIssue
from dirigent_common import JsonMap
from dirigent_common.templating import ENVIRONMENT
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.references import references_in
from dirigent_core.messages import OUTPUT_FIELD_UNKNOWN

#: What a mapping answers to in a template beside its keys: ``output.items()`` is a loop.
MAPPING_METHODS: Final = frozenset({"items", "keys", "values", "get"})

#: Where in a schema its ``$ref`` targets live.
DEFINITIONS: Final = "#/$defs/"

#: How many ``$ref`` and nullable unions one field is followed through before it is not judged.
MAX_HOPS: Final = 8


def output_field_warnings(definition: PipelineDefinition, catalog: Catalog | None) -> list[ValidationIssue]:
    """Warn on every reference and report template read of an output field its step's block does not declare."""
    if catalog is None:
        return []
    schemas = _output_schemas(definition, catalog)
    warnings: list[ValidationIssue] = []
    for name in sorted(definition.steps):
        step = definition.steps[name]
        places: list[tuple[str, JsonValue]] = [
            (f"steps.{name}.config", cast("JsonValue", step.config)),
            (f"steps.{name}.for_each", cast("JsonValue", step.for_each)),
        ]
        if step.reply is not None:
            places.append((f"steps.{name}.reply", cast("JsonValue", step.reply.model_dump(mode="json"))))
        for location, value in places:
            for reference in sorted({reference.strip() for reference in references_in(value)}):
                found = _referenced(reference, definition)
                if found is not None:
                    target, path = found
                    warnings.extend(_unknown(f"${{{reference}}}", location, target, path, schemas, definition))
    report = definition.report
    if report is not None and report.template is not None:
        warnings.extend(_template_warnings(report.template, "report.template", schemas, definition))
    return _once(warnings)


def _output_schemas(definition: PipelineDefinition, catalog: Catalog) -> dict[str, JsonMap]:
    """The published output schema of each step's block or source kind, where the catalog holds one."""
    schemas: dict[str, JsonMap] = {}
    for name, step in definition.steps.items():
        if step.block is not None:
            block = catalog.block(step.block)
            if block is not None and block.output_schema:
                schemas[name] = block.output_schema
        elif step.source is not None:
            source = catalog.source(step.source.kind)
            if source is not None and source.output_schema:
                schemas[name] = source.output_schema
    return schemas


def _referenced(reference: str, definition: PipelineDefinition) -> tuple[str, list[str]] | None:
    """The step a reference reads one output of, and the path into that output, or None for any other reference."""
    parts = [part for part in reference.split(".") if part]
    match parts:
        case ["steps", target, "output", *path] if (
            target in definition.steps and not definition.steps[target].is_fan_out
        ):
            return target, path
        case ["steps", target, "item", "output", *path] if target in definition.steps:
            return target, path
        case _:
            return None


def _template_warnings(
    source: str, location: str, schemas: Mapping[str, JsonMap], definition: PipelineDefinition
) -> list[ValidationIssue]:
    """Warn on each ``step.<name>.output.<field>`` a report template reads that the step's output does not have."""
    try:
        tree = ENVIRONMENT.parse(source)
    except jinja2.TemplateSyntaxError:
        return []
    if "step" not in jinja2.meta.find_undeclared_variables(tree):
        return []
    warnings: list[ValidationIssue] = []
    for chain in sorted(set(_chains(tree))):
        match chain:
            case ("step", target, "output", *path) if path:
                warnings.extend(
                    _unknown(".".join(chain), location, target, path, schemas, definition, methods=MAPPING_METHODS)
                )
            case _:
                continue
    return warnings


def _chains(tree: nodes.Template) -> Iterator[tuple[str, ...]]:
    """Every dotted read a template makes from a name, as the name followed by each key it reads."""
    for read in tree.find_all((nodes.Getattr, nodes.Getitem)):
        keys: list[str] = []
        current: nodes.Node = read
        while True:
            if isinstance(current, nodes.Getattr):
                keys.append(current.attr)
                current = current.node
            elif (
                isinstance(current, nodes.Getitem)
                and isinstance(current.arg, nodes.Const)
                and isinstance(current.arg.value, str | int)
            ):
                keys.append(str(current.arg.value))
                current = current.node
            else:
                break
        if isinstance(current, nodes.Name) and current.ctx == "load":
            yield (current.name, *reversed(keys))


def _unknown(
    reference: str,
    location: str,
    target: str,
    path: list[str],
    schemas: Mapping[str, JsonMap],
    definition: PipelineDefinition,
    *,
    methods: frozenset[str] = frozenset(),
) -> list[ValidationIssue]:
    """Warn when a path into a step's output leaves the fields its closed schema declares."""
    schema = schemas.get(target)
    if schema is None:
        return []
    node: JsonMap | None = schema
    for index, field in enumerate(path):
        node = _closed_object(node, schema)
        if node is None:
            return []
        properties = cast("dict[str, Any]", node["properties"])
        if field not in properties:
            if field in methods:
                return []
            step = definition.steps[target]
            return [
                ValidationIssue.of(
                    OUTPUT_FIELD_UNKNOWN,
                    location=location,
                    reference=reference,
                    field=repr(".".join(path[: index + 1])),
                    step=repr(target),
                    block=step.block or (step.source.kind if step.source is not None else ""),
                    fields=", ".join(sorted(properties)) or "nothing",
                )
            ]
        child = properties[field]
        node = cast("JsonMap", child) if isinstance(child, dict) else None
    return []


def _closed_object(node: JsonMap | None, root: JsonMap) -> JsonMap | None:
    """The object schema a node stands for when it names every field it may have, or None when it does not."""
    for _ in range(MAX_HOPS):
        if node is None:
            return None
        ref = node.get("$ref")
        if isinstance(ref, str):
            node = _definition(ref, root)
            continue
        branches = node.get("anyOf")
        if isinstance(branches, list):
            kept = [branch for branch in cast("list[object]", branches) if branch != {"type": "null"}]
            node = cast("JsonMap", kept[0]) if len(kept) == 1 and isinstance(kept[0], dict) else None
            continue
        break
    if node is None or node.get("type") != "object" or node.get("additionalProperties") is not False:
        return None
    return node if isinstance(node.get("properties"), dict) else None


def _definition(ref: str, root: JsonMap) -> JsonMap | None:
    """The schema a local ``$ref`` names, or None for one this check does not follow."""
    if not ref.startswith(DEFINITIONS):
        return None
    found = cast("dict[str, Any]", root.get("$defs", {})).get(ref.removeprefix(DEFINITIONS))
    return cast("JsonMap", found) if isinstance(found, dict) else None


def _once(warnings: list[ValidationIssue]) -> list[ValidationIssue]:
    """Keep one warning per field a template misreads, however many longer reads pass through it."""
    kept: dict[tuple[str, object, object], ValidationIssue] = {}
    for warning in warnings:
        kept.setdefault((warning.location, warning.params.get("step"), warning.params.get("field")), warning)
    return list(kept.values())
