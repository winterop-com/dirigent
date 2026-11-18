"""Checking a pack's own examples against its own contribution, without the engine.

An out-of-repo pack cannot import dirigent-core to reuse ``validate_against_catalog``: the
plugin contract stops at dirigent-plugin, and a pack must not reach past it. So the pack-side
conformance check re-derives the structural half here, over the pack's own ``Contribution``
and its own example documents. It is deliberately lighter than the engine's preflight: it
proves an example is a well-formed ``dirigent/v1`` pipeline coded after its file, that every
block and source kind it names is one the pack contributes, that each config fits the published
schema, and that a connection a step names is one the document accounts for -- carried, so
the document runs alone, or named under ``requires``. It does not resolve references, run
blocks, or reach for an instance.
"""

import re
from pathlib import Path
from typing import Any, Final, cast

import yaml
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError
from jsonschema.validators import extend as extend_validator  # pyright: ignore[reportUnknownVariableType]
from pydantic import BaseModel, JsonValue

from dirigent_common import LOCAL_REFERENCES, BlockModel, HumaneJsonSchema, JsonMap
from dirigent_common.bounds import BOUNDS_KEYWORD, bounds_keyword
from dirigent_plugin import AnyOperator, AnySensor, Contribution, mark_refusal, reference_fields
from dirigent_plugin.sources import AnySource

#: A ``${...}`` reference behind its run of dollars, matched the way the engine matches one: an
#: even run is the ``$${...}`` escape and names no reference.
_REFERENCE: Final = re.compile(r"(\$+)\{[^{}]+\}")

#: What a connection field publishes itself as a reference to.
_CONNECTION: Final = "connection"


def _has_reference(value: str) -> bool:
    """Whether a string names at least one reference, ignoring every escaped ``$${...}``."""
    return any(len(match.group(1)) % 2 for match in _REFERENCE.finditer(value))


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
    {
        name: _skip_deferred(keyword)
        for name, keyword in {**Draft202012Validator.VALIDATORS, BOUNDS_KEYWORD: bounds_keyword}.items()
    },
)


def _defer_references(value: JsonValue) -> object:
    """Replace every value that is a ``${...}`` reference with the deferred sentinel."""
    match value:
        case str():
            return _DEFERRED if _has_reference(value) else value
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
    step names and every source kind a ``source`` node names is one ``contribution`` provides,
    that each config fits its block's or kind's published schema (a ``${...}`` value is left for
    the run), and that a connection a config field publishes as one is either carried by the
    document's own ``connections`` block or named under its ``requires.connections``. A
    ``reply`` node is the engine's own and is not checked here. Every issue is a human-readable
    line prefixed with the file it was found in; an empty list means the examples conform.
    """
    contributed = _Contributed(
        _blocks_by_id(contribution), {source.spec.kind: source for source in contribution.sources}
    )
    issues: list[str] = []
    for path in sorted(examples_dir.rglob("*.yaml")):
        issues.extend(_check_document(path, path.relative_to(examples_dir), contributed))
    return issues


class _Contributed:
    """What a pack contributes that a step may name: its blocks by id and its source kinds by kind."""

    def __init__(self, blocks: dict[str, AnyOperator | AnySensor], sources: dict[str, AnySource]) -> None:
        """Hold both indexes."""
        self.blocks = blocks
        self.sources = sources


def _every_block(contribution: Contribution) -> list[AnyOperator | AnySensor]:
    """List every operator and then every sensor a contribution provides."""
    blocks: list[AnyOperator | AnySensor] = [*contribution.operators, *contribution.sensors]
    return blocks


def _blocks_by_id(contribution: Contribution) -> dict[str, AnyOperator | AnySensor]:
    """Index every operator and sensor a contribution provides by its block id."""
    return {block.spec.id: block for block in _every_block(contribution)}


def _check_document(path: Path, label: Path, contributed: _Contributed) -> list[str]:
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

    steps = document.get("steps")
    if isinstance(steps, dict):
        known = _known_connections(document)
        for name, step in cast("JsonMap", steps).items():
            issues.extend(_check_step(label, str(name), step, contributed, known))
    return issues


def _known_connections(document: JsonMap) -> set[str]:
    """Every connection code a document accounts for: the ones it carries and the ones it names."""
    carried = document.get("connections")
    known = set(cast("JsonMap", carried)) if isinstance(carried, dict) else set[str]()
    requires = document.get("requires")
    named = cast("JsonMap", requires).get("connections") if isinstance(requires, dict) else None
    if isinstance(named, list):
        known |= {one for one in cast("list[object]", named) if isinstance(one, str)}
    return known


def _check_step(
    label: Path,
    name: str,
    step: Any,
    contributed: _Contributed,
    connections: set[str],
) -> list[str]:
    """Check one step: the block or source kind it names, the config it carries, the connections it references.

    ``connections`` is every code the document accounts for, carried or required.
    """
    if not isinstance(step, dict):
        return [f"{label}: step {name!r} is not a mapping"]
    step_map = cast("JsonMap", step)
    if "reply" in step_map:
        return []
    source = step_map.get("source")
    if source is not None:
        return _check_source(label, name, source, contributed.sources, connections)
    block_id = step_map.get("block")
    raw_config = step_map.get("config")
    config = cast("JsonMap", raw_config) if isinstance(raw_config, dict) else cast("JsonMap", {})
    block = contributed.blocks.get(block_id) if isinstance(block_id, str) else None
    if block is None:
        return [f"{label}: step {name!r} names block {block_id!r}, which this pack does not contribute"]
    schema = block.config_model.model_json_schema(schema_generator=HumaneJsonSchema)
    return [*_config_issues(label, name, config, schema), *_connection_issues(label, name, config, schema, connections)]


def _check_source(label: Path, name: str, source: Any, kinds: dict[str, AnySource], connections: set[str]) -> list[str]:
    """Check one source node: the kind it names, and its own fields against that kind's schema."""
    if not isinstance(source, dict):
        return [f"{label}: step {name!r} source is not a mapping"]
    fields = dict(cast("JsonMap", source))
    kind_name = fields.pop("kind", None)
    kind = kinds.get(kind_name) if isinstance(kind_name, str) else None
    if kind is None:
        return [f"{label}: step {name!r} names source kind {kind_name!r}, which this pack does not contribute"]
    schema = kind.config_model.model_json_schema(schema_generator=HumaneJsonSchema)
    issues = [issue.replace(" config", " source", 1) for issue in _config_issues(label, name, fields, schema)]
    return [*issues, *_connection_issues(label, name, fields, schema, connections)]


def _connection_issues(label: Path, name: str, config: JsonMap, schema: JsonMap, connections: set[str]) -> list[str]:
    """List each connection a config names in a field published as one, that the document does not account for."""
    issues: list[str] = []
    for field in sorted(reference_fields(schema, _CONNECTION)):
        named = config.get(field)
        if isinstance(named, str) and not _has_reference(named) and named not in connections:
            issues.append(
                f"{label}: step {name!r} names connection {named!r}, which the document neither carries nor requires"
            )
    return issues


def _config_issues(label: Path, name: str, config: JsonMap, schema: JsonMap) -> list[str]:
    """List the ways a step's config violates its block's schema, deferring every reference."""
    deferred = _defer_references(config)
    raised: Any = _ConfigValidator(schema, registry=LOCAL_REFERENCES).iter_errors(deferred)  # pyright: ignore[reportUnknownMemberType]
    found = cast("list[SchemaValidationError]", list(raised))
    issues: list[str] = []
    for error in sorted(found, key=lambda item: [str(part) for part in item.absolute_path]):
        location = ".".join(str(part) for part in error.absolute_path)
        where = f"config.{location}" if location else "config"
        issues.append(f"{label}: step {name!r} {where}: {error.message}")
    return issues


def assert_contribution_conforms(contribution: Contribution) -> list[str]:
    """List the ways a contribution is malformed, beyond what constructing it enforces.

    A ``Contribution`` already rejects colliding ids when it is built, and a block id is a
    pattern that forbids an empty one, so a valid contribution passes those. This adds the
    check the contract cannot make on its own: that every operator's and sensor's
    ``config_model`` and ``output_model`` is a :class:`BlockModel`, and every source kind's is a
    pydantic model. A connection or source kind's ``mark`` is checked through
    :func:`dirigent_plugin.mark_refusal`, which is what registration holds it to, so a pack
    reads the same refusal here as it would at startup; a kind that declares none passes. An
    empty list means the contribution conforms.
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
    for connection in contribution.connection_kinds:
        refusal = mark_refusal(connection.id, connection.mark)
        if refusal is not None:
            issues.append(refusal)
        known = set(connection.config_model.model_fields)
        for form in connection.credential_forms:
            unknown = [field for field in form.fields if field not in known]
            label = f"connection kind {connection.id} credential form {form.code!r}"
            if not form.fields:
                issues.append(f"{label} names no field")
            elif unknown:
                issues.append(f"{label} names {', '.join(unknown)}, which its config model does not declare")
    for source in contribution.sources:
        kind = source.spec.kind
        for role in ("config_model", "output_model"):
            model = getattr(source, role, None)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                issues.append(f"source kind {kind} {role} is not a pydantic model")
        refusal = mark_refusal(kind, source.mark)
        if refusal is not None:
            issues.append(refusal)
    return issues
