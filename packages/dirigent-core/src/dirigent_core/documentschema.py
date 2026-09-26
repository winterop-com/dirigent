"""The JSON Schema an editor checks a ``dirigent/v1`` document against.

The document format is a pydantic model and every block's config is another one, so a document
is only half-describable without the catalog: ``steps.push.config`` is whatever the block named
in ``steps.push.block`` accepts. This module composes the two into one Draft 2020-12 schema, so
an editor squiggles an unknown key in the place an apply would refuse it.

A CONFIG VALUE MAY BE A REFERENCE, and this schema has to say so. An apply defers every value
carrying a ``${...}``, so a config schema published as written would squiggle ``delay:
"${params.pace}"`` in a document the server accepts. Every place a value goes in a block's
config gains the reference as an alternative; the keywords around them do not, so an unknown
key and a missing required key are still refused exactly where they were.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from dirigent_client.schemas import Catalog
from dirigent_common import HumaneJsonSchema, JsonMap
from dirigent_core.engine.definition import PipelineDefinition, TriggersDefinition
from dirigent_core.engine.references import JSON_REFERENCE_PATTERN

#: The dialect the composed schema declares, which is the one the engine validates parameters in.
DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"

TITLE: Final = "dirigent/v1 document"

#: What a value the run resolves looks like, offered beside every config field's own type.
REFERENCE: Final[JsonMap] = {"type": "string", "pattern": JSON_REFERENCE_PATTERN}

#: Keywords that say what a value is rather than what it may be, which stay outside the pair.
ANNOTATIONS: Final = ("title", "description", "default", "examples", "deprecated")


def document_schema(catalog: Catalog) -> JsonMap:
    """Compose both document kinds with this instance's own block config schemas.

    The two branches share ``$defs``, and ``kind`` is what an editor picks between them by.
    """
    pipeline = _pipeline_schema(catalog)
    triggers = TriggersDefinition.model_json_schema(ref_template="#/$defs/{model}", schema_generator=HumaneJsonSchema)
    definitions = cast("dict[str, Any]", pipeline.pop("$defs", {}))
    definitions.update(cast("dict[str, Any]", triggers.pop("$defs", {})))
    return {
        "$schema": DIALECT,
        "title": TITLE,
        "$defs": definitions,
        "oneOf": [pipeline, triggers],
    }


def _pipeline_schema(catalog: Catalog) -> JsonMap:
    """The pipeline branch: the document format with every block's config grafted onto its step."""
    schema = PipelineDefinition.model_json_schema(schema_generator=HumaneJsonSchema)
    definitions = cast("dict[str, Any]", schema.setdefault("$defs", {}))
    step = cast("dict[str, Any]", definitions["StepDefinition"])
    blocks = sorted(catalog.blocks, key=lambda entry: entry.id)

    if blocks:
        cast("dict[str, Any]", step["properties"])["block"]["enum"] = [entry.id for entry in blocks]

    cases: list[JsonMap] = []
    for entry in blocks:
        config, lifted = _lift(entry.config_schema, entry.id)
        definitions.update(lifted)
        # The config itself is the object the step declares and is never a reference; every
        # value inside it may be one.
        config = cast("JsonMap", _within(config))
        cases.append(
            {
                "if": {"properties": {"block": {"const": entry.id}}, "required": ["block"]},
                "then": {"properties": {"config": config}},
            }
        )
    if cases:
        step["allOf"] = cases
    return schema


def _lift(config_schema: JsonMap, block_id: str) -> tuple[JsonMap, dict[str, Any]]:
    """Move one block's ``$defs`` into the document's, under names only that block uses.

    Two blocks contribute a ``Size`` each and a shared ``$defs`` has room for one, so every
    definition is renamed for the block it came from and every ``$ref`` to it follows.
    """
    own = cast("dict[str, Any]", config_schema.get("$defs", {}))
    body = {key: value for key, value in config_schema.items() if key != "$defs"}
    lifted = {f"{block_id}.{name}": _within(_repoint(value, block_id)) for name, value in own.items()}
    return cast("JsonMap", _repoint(body, block_id)), lifted


#: Keywords whose value is one subschema describing a value of its own.
_ONE: Final = ("items", "additionalProperties", "contains", "propertyNames", "not")

#: Keywords whose value is a map of subschemas, each describing a value of its own.
_MAPPED: Final = ("properties", "patternProperties")

#: Keywords whose value is a list of subschemas describing the value their parent describes.
_BRANCHED: Final = ("anyOf", "oneOf", "allOf")


def _deferrable(schema: object) -> Any:
    """One value position, written so a reference may stand in it.

    The annotations stay outside the pair, because an editor reads the label and the help off
    the node it is completing and would find neither inside a branch.
    """
    if not isinstance(schema, dict):
        return schema
    inner = cast("dict[str, Any]", _within(cast("Mapping[str, Any]", schema)))
    notes = {key: inner.pop(key) for key in tuple(inner) if key in ANNOTATIONS}
    return {**notes, "anyOf": [inner, REFERENCE]}


def _within(schema: object) -> Any:
    """The same subschema with every value position inside it written as deferrable."""
    if not isinstance(schema, dict):
        return schema
    mapping = cast("Mapping[str, Any]", schema)
    rewritten: dict[str, Any] = {}
    for key, value in mapping.items():
        if key in _MAPPED and isinstance(value, dict):
            rewritten[key] = {name: _deferrable(one) for name, one in cast("Mapping[str, Any]", value).items()}
        elif key in _ONE and isinstance(value, dict):
            rewritten[key] = _deferrable(cast("Mapping[str, Any]", value))
        elif key == "prefixItems" and isinstance(value, list):
            rewritten[key] = [_deferrable(one) for one in cast("Sequence[Any]", value)]
        elif key in _BRANCHED and isinstance(value, list):
            rewritten[key] = [_within(one) for one in cast("Sequence[Any]", value)]
        else:
            rewritten[key] = value
    return rewritten


def _repoint(value: object, block_id: str) -> Any:
    """Point every local ``$ref`` at the name its definition was lifted under."""
    if isinstance(value, dict):
        mapping = cast("Mapping[str, object]", value)
        return {key: _repoint_member(key, item, block_id) for key, item in mapping.items()}
    if isinstance(value, list):
        items = cast("Sequence[object]", value)
        return [_repoint(item, block_id) for item in items]
    return value


def _repoint_member(key: str, value: object, block_id: str) -> Any:
    """Rewrite one member, which is a rename only when it is the ``$ref`` itself."""
    prefix = "#/$defs/"
    if key == "$ref" and isinstance(value, str) and value.startswith(prefix):
        return f"{prefix}{block_id}.{value.removeprefix(prefix)}"
    return _repoint(value, block_id)
