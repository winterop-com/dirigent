"""Checking a pack's own examples against its own contribution, without the engine.

An out-of-repo pack cannot import dirigent-core to reuse ``validate_against_catalog``: the
plugin contract stops at dirigent-plugin, and a pack must not reach past it. So the pack-side
conformance check re-derives the structural half here, over the pack's own ``Contribution``
and its own example documents. It is deliberately lighter than the engine's preflight: it
proves an example is a well-formed ``dirigent/v1`` pipeline coded after its file, that every
block it names is one the pack contributes, that each config fits that block's published
schema, and that a named connection is carried by the document. It does not resolve
references, run blocks, or reach for an instance.
"""

import re
from pathlib import Path
from typing import Any, Final, cast

import yaml
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError
from jsonschema.validators import extend as extend_validator  # pyright: ignore[reportUnknownVariableType]
from pydantic import JsonValue

from dirigent_common import BlockModel, HumaneJsonSchema, JsonMap
from dirigent_plugin import AnyOperator, AnySensor, Contribution

#: A ``${...}`` reference, matched the way the engine matches one.
_REFERENCE: Final = re.compile(r"\$\{[^{}]+\}")


class _Deferred:
    """A config value that is only a ``${...}`` reference, opaque until a run resolves it."""

    def __repr__(self) -> str:
        """Render the sentinel for an error message."""
        return "${...}"


_DEFERRED: Final = _Deferred()


def _skip_deferred(keyword: Any) -> Any:
    """Wrap one jsonschema keyword so it passes over a value that is only known at run time."""

    def validate(validator: Any, value: Any, instance: Any, schema: Any) -> Any:
        if instance is _DEFERRED:
            return
        yield from keyword(validator, value, instance, schema)

    return validate


#: A validator that checks everything an example states literally and defers a reference.
_ConfigValidator: Any = extend_validator(  # pyright: ignore[reportUnknownVariableType]
    Draft202012Validator,
    {name: _skip_deferred(keyword) for name, keyword in Draft202012Validator.VALIDATORS.items()},
)


def _defer_references(value: JsonValue) -> object:
    """Replace every value that is a ``${...}`` reference with the deferred sentinel."""
    match value:
        case str():
            return _DEFERRED if _REFERENCE.search(value) else value
        case list():
            return [_defer_references(item) for item in value]
        case dict():
            return {key: _defer_references(item) for key, item in value.items()}
        case _:
            return value


def check_pack_examples(contribution: Contribution, examples_dir: Path) -> list[str]:
    """List everything wrong with a pack's example documents, checked against its own catalog.

    Reads every ``*.yaml`` under ``examples_dir`` (recursively) and, for each, checks that it
    is a ``dirigent/v1`` pipeline coded after its file with a description, that every block a
    step names is one ``contribution`` provides, that each step's config fits that block's
    published ``config_schema`` (a ``${...}`` value is left for the run), and that a connection
    a step names is carried by the document's own ``connections`` block. Every issue is a
    human-readable line prefixed with the file it was found in; an empty list means the
    examples conform.
    """
    blocks = _blocks_by_id(contribution)
    issues: list[str] = []
    for path in sorted(examples_dir.rglob("*.yaml")):
        issues.extend(_check_document(path, path.relative_to(examples_dir), blocks))
    return issues


def _every_block(contribution: Contribution) -> list[AnyOperator | AnySensor]:
    """List every operator and then every sensor a contribution provides."""
    blocks: list[AnyOperator | AnySensor] = [*contribution.operators, *contribution.sensors]
    return blocks


def _blocks_by_id(contribution: Contribution) -> dict[str, AnyOperator | AnySensor]:
    """Index every operator and sensor a contribution provides by its block id."""
    return {block.spec.id: block for block in _every_block(contribution)}


def _check_document(path: Path, label: Path, blocks: dict[str, AnyOperator | AnySensor]) -> list[str]:
    """Check one example document, prefixing every issue with the file it was found in."""
    try:
        loaded: object = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        return [f"{label}: is not valid YAML ({error})"]
    if not isinstance(loaded, dict):
        return [f"{label}: is not a mapping"]
    document = cast("JsonMap", loaded)

    issues: list[str] = []
    if document.get("format") != "dirigent/v1":
        issues.append(f"{label}: format is {document.get('format')!r}, not 'dirigent/v1'")
    if document.get("kind") != "pipeline":
        issues.append(f"{label}: kind is {document.get('kind')!r}, not 'pipeline'")
    if document.get("code") != path.stem:
        issues.append(f"{label}: code is {document.get('code')!r}, but the file is named {path.stem!r}")
    if not document.get("description"):
        issues.append(f"{label}: has no description")

    connections = document.get("connections")
    known = set(cast("JsonMap", connections)) if isinstance(connections, dict) else set[str]()
    steps = document.get("steps")
    if isinstance(steps, dict):
        for name, step in cast("JsonMap", steps).items():
            issues.extend(_check_step(label, str(name), step, blocks, known))
    return issues


def _check_step(
    label: Path,
    name: str,
    step: Any,
    blocks: dict[str, AnyOperator | AnySensor],
    connections: set[str],
) -> list[str]:
    """Check one step: the block it names, the config it carries, the connection it references."""
    if not isinstance(step, dict):
        return [f"{label}: step {name!r} is not a mapping"]
    step_map = cast("JsonMap", step)
    issues: list[str] = []
    block_id = step_map.get("block")
    raw_config = step_map.get("config")
    config = cast("JsonMap", raw_config) if isinstance(raw_config, dict) else cast("JsonMap", {})

    block = blocks.get(block_id) if isinstance(block_id, str) else None
    if block is None:
        issues.append(f"{label}: step {name!r} names block {block_id!r}, which this pack does not contribute")
    else:
        schema = block.config_model.model_json_schema(schema_generator=HumaneJsonSchema)
        issues.extend(_config_issues(label, name, config, schema))

    named = config.get("connection")
    if isinstance(named, str) and not _REFERENCE.search(named) and named not in connections:
        issues.append(f"{label}: step {name!r} names connection {named!r}, which the document does not carry")
    return issues


def _config_issues(label: Path, name: str, config: JsonMap, schema: JsonMap) -> list[str]:
    """List the ways a step's config violates its block's schema, deferring every reference."""
    deferred = _defer_references(config)
    raised: Any = _ConfigValidator(schema).iter_errors(deferred)  # pyright: ignore[reportUnknownMemberType]
    found = cast("list[SchemaValidationError]", list(raised))
    issues: list[str] = []
    for error in sorted(found, key=lambda item: [str(part) for part in item.absolute_path]):
        location = ".".join(str(part) for part in error.absolute_path)
        where = f"config.{location}" if location else "config"
        issues.append(f"{label}: step {name!r} {where}: {error.message}")
    return issues


def assert_contribution_conforms(contribution: Contribution) -> list[str]:
    """List the ways a contribution's blocks are malformed, beyond what constructing it enforces.

    A ``Contribution`` already rejects colliding ids when it is built, and a block id is a
    pattern that forbids an empty one, so a valid contribution passes those. This adds the
    check the contract cannot make on its own: that every operator's and sensor's
    ``config_model`` and ``output_model`` is a :class:`BlockModel`. An empty list means the
    contribution's blocks are well-formed.
    """
    issues: list[str] = []
    seen: set[str] = set()
    for block in _every_block(contribution):
        label = type(block).__name__
        block_id = block.spec.id
        if not block_id:
            issues.append(f"{label} has an empty spec.id")
        elif block_id in seen:
            issues.append(f"duplicate block id {block_id!r}")
        seen.add(block_id)
        for role in ("config_model", "output_model"):
            model = getattr(block, role)
            if not (isinstance(model, type) and issubclass(model, BlockModel)):
                issues.append(f"{block_id or label} {role} is not a BlockModel")
    return issues
