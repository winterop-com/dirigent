"""The JSON Schema an editor checks a ``dirigent/v1`` document against.

The document format is a pydantic model and every block's config is another one, so a document
is only half-describable without the catalog: ``steps.push.config`` is whatever the block named
in ``steps.push.block`` accepts. This module composes the two into one Draft 2020-12 schema, so
an editor squiggles an unknown key in the place an apply would refuse it.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from dirigent_client.schemas import Catalog
from dirigent_common import HumaneJsonSchema, JsonMap
from dirigent_core.engine.definition import PipelineDefinition, TriggersDefinition

#: The dialect the composed schema declares, which is the one the engine validates parameters in.
DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"

TITLE: Final = "dirigent/v1 document"


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
    lifted = {f"{block_id}.{name}": _repoint(value, block_id) for name, value in own.items()}
    return cast("JsonMap", _repoint(body, block_id)), lifted


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
