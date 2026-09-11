"""Reading, writing, and validating a ``dirigent/v1`` document."""

import difflib
import hashlib
from collections.abc import Iterable, Mapping
from typing import Any, Final, cast, get_args, get_origin

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError
from jsonschema.exceptions import SchemaError
from jsonschema.validators import extend as extend_validator  # pyright: ignore[reportUnknownVariableType]
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from dirigent_client.schemas import Catalog, ValidationIssue
from dirigent_common import STORAGE_URI_FORMAT, JsonMap, base_format_checker
from dirigent_core.engine.definition import (
    FORMAT_V1,
    KIND_PIPELINE,
    KIND_TRIGGERS,
    Document,
    PipelineDefinition,
    TriggerRule,
    TriggersDefinition,
    canonical_document,
)
from dirigent_core.engine.references import has_reference, references_in

#: High enough that the canonical dump never folds a line, which would shift the digest.
YAML_WIDTH: Final = 10_000


class PlainLoader(yaml.SafeLoader):
    """A safe loader that leaves a date written as a date alone.

    YAML resolves ``2026-01-01`` to a ``datetime.date``, which is not a JSON value, so the
    timestamp resolver is removed and such a value stays the string it was written as.
    """


PlainLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def safe_load(text: str) -> object:
    """Read YAML (or JSON) the one way dirigent reads it, with dates left as strings."""
    return yaml.load(text, Loader=PlainLoader)  # noqa: S506 - PlainLoader is SafeLoader minus a resolver


class CanonicalDumper(yaml.SafeDumper):
    """The one YAML dumper an export uses: block style, and sequences indented under their key."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        """Indent block sequences under their key rather than beside it."""
        super().increase_indent(flow=flow, indentless=False)


class DocumentError(Exception):
    """A document could not be read at all, or did not satisfy the format."""

    def __init__(self, message: str, problems: Iterable[str] = ()) -> None:
        """Carry the whole list of problems a document has."""
        self.problems = list(problems) or [message]
        detail = "; ".join(self.problems)
        super().__init__(message if detail == message else f"{message}: {detail}")


def parse_text(text: str) -> JsonMap:
    """Read a document's text as YAML, which accepts its JSON form verbatim."""
    try:
        loaded = safe_load(text)
    except yaml.YAMLError as error:
        raise DocumentError(f"the document is not valid YAML or JSON: {error}") from error
    if loaded is None:
        raise DocumentError("the document is empty")
    if not isinstance(loaded, dict):
        raise DocumentError(f"a document is a mapping, not {type(loaded).__name__}")
    return cast("JsonMap", loaded)


#: The model each document kind is read into.
MODELS: Final[dict[str, type[PipelineDefinition] | type[TriggersDefinition]]] = {
    KIND_PIPELINE: PipelineDefinition,
    KIND_TRIGGERS: TriggersDefinition,
}


def load_document(raw: JsonMap) -> Document:
    """Validate a parsed document against the format, reporting every problem at once."""
    kind = _check_envelope(raw)
    try:
        return MODELS[kind].model_validate(raw)
    except ValidationError as error:
        raise DocumentError("the document does not satisfy dirigent/v1", _readable(error, kind)) from error


def load_text(text: str) -> Document:
    """Read a document from its YAML or JSON text, in one call."""
    return load_document(parse_text(text))


def carried_refusal(definition: Document) -> str | None:
    """Why an instance will not store this document, or ``None`` when it will.

    A document may carry its own connections and its own schemas so that it runs alone under
    ``dg run --local``. An applied document is stored, versioned and exported, so a carried
    credential would be in all three, and a carried schema would be a copy of a resource an
    instance holds once and names. Every door that stores a document refuses one the same way.
    """
    if not isinstance(definition, PipelineDefinition):
        return None
    if definition.connections:
        named = ", ".join(sorted(definition.connections))
        return (
            f"this document carries its own connections ({named}), which an instance will not store: "
            "create them with `dg connection create` and let the document name them"
        )
    if definition.schemas:
        named = ", ".join(sorted(definition.schemas))
        return (
            f"this document carries its own schemas ({named}), which an instance will not store: "
            "create them with `dg schema create` and let the document name them in requires.schemas"
        )
    return None


def load_pipeline_text(text: str) -> PipelineDefinition:
    """Read a document that must be a pipeline, naming the kind it turned out to be."""
    definition = load_text(text)
    if not isinstance(definition, PipelineDefinition):
        raise DocumentError(f"this is a `kind: {definition.kind}` document, and a pipeline document was wanted")
    return definition


def _check_envelope(raw: JsonMap) -> str:
    """Refuse a document whose format tag is missing, or whose kind is neither of the two."""
    declared = raw.get("format")
    if declared is None:
        raise DocumentError(f"the document declares no format; add `format: {FORMAT_V1}`")
    if declared != FORMAT_V1:
        raise DocumentError(f"this instance reads {FORMAT_V1} documents, and this one declares {declared!r}")
    kind = raw.get("kind", KIND_PIPELINE)
    if kind not in MODELS:
        known = " and ".join(f"`kind: {name}`" for name in MODELS)
        raise DocumentError(f"{FORMAT_V1} defines {known}, and this document declares {kind!r}")
    return str(kind)


def _readable(error: ValidationError, kind: str = KIND_PIPELINE) -> list[str]:
    """Render pydantic's errors as document paths."""
    problems: list[str] = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"]) or "(document)"
        if detail["type"] == "extra_forbidden":
            problems.append(f"{location}: unknown key{_did_you_mean(detail['loc'], kind)}")
            continue
        problems.append(f"{location}: {detail['msg']}")
    return problems


def _did_you_mean(location: tuple[int | str, ...], kind: str) -> str:
    """Name the document field an unknown key is closest to, when one is close enough."""
    model = _model_at(location[:-1], kind)
    if model is None:
        return ""
    known = [field.alias or name for name, field in model.model_fields.items()]
    close = difflib.get_close_matches(str(location[-1]), known, n=1)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _model_at(location: tuple[int | str, ...], kind: str = KIND_PIPELINE) -> type[BaseModel] | None:
    """Walk a validation error's location down the models the format itself defines.

    Block config is opaque to the format, so the walk stops at ``steps.<name>.config``: an
    unknown key inside one is refused against the block's published schema instead, and gets
    that check's message rather than a suggestion from here.
    """
    current: Any = MODELS.get(kind, PipelineDefinition)
    for part in location:
        if isinstance(current, type) and issubclass(current, BaseModel):
            field = current.model_fields.get(str(part))
            current = None if field is None else field.annotation
        else:
            current = _element_of(current)
        if current is None:
            return None
    return current if isinstance(current, type) and issubclass(current, BaseModel) else None


def _element_of(annotation: Any) -> Any:
    """Read what one entry of a list or map annotation holds, or nothing if it holds neither."""
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    return args[-1] if get_origin(annotation) in (list, dict) and args else None


def to_yaml(definition: Document) -> str:
    """Render a definition as the canonical YAML an export writes and a digest covers."""
    return yaml.dump(
        canonical_document(definition),
        Dumper=CanonicalDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=YAML_WIDTH,
        indent=2,
    )


def digest_of(definition: Document) -> str:
    """Hash the canonical form of a definition."""
    return f"sha256:{hashlib.sha256(to_yaml(definition).encode()).hexdigest()}"


def digest_of_document(document: JsonMap) -> str:
    """Hash a stored document by re-canonicalizing it, so storage order never shifts a digest."""
    return digest_of(MODELS[str(document.get("kind", KIND_PIPELINE))].model_validate(document))


class _Deferred:
    """A ``${...}`` reference, opaque until a run resolves it."""

    def __repr__(self) -> str:
        """Render the sentinel for an error message."""
        return "${...}"


DEFERRED: Final = _Deferred()


def _skip_deferred(keyword: Any) -> Any:
    """Wrap one jsonschema keyword so it passes over a value that is only known at run time."""

    def validate(validator: Any, value: Any, instance: Any, schema: Any) -> Any:
        if instance is DEFERRED:
            return
        yield from keyword(validator, value, instance, schema)

    return validate


#: A validator that checks everything a document states literally and defers the rest.
ConfigValidator: Any = extend_validator(  # pyright: ignore[reportUnknownVariableType]
    Draft202012Validator,
    {name: _skip_deferred(keyword) for name, keyword in Draft202012Validator.VALIDATORS.items()},
)


def defer_references(value: JsonValue) -> object:
    """Replace every value containing a ``${...}`` reference with the deferred sentinel.

    A config is checked against its block's schema at apply time, when a referenced value has
    no type yet; deferring exactly those values keeps the rest of the check strict.
    """
    match value:
        case str():
            return DEFERRED if has_reference(value) else value
        case list():
            return [defer_references(item) for item in value]
        case dict():
            return {key: defer_references(item) for key, item in value.items()}
        case _:
            return value


class TriggerTarget(BaseModel):
    """The pipeline a triggers document names, as the instance currently holds it."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    code: str
    active: bool = True
    definition: PipelineDefinition | None = None
    """Its current version, or None when it has none and therefore declares no parameters."""


def validate_against_catalog(
    definition: Document,
    catalog: Catalog,
    *,
    connections: Iterable[str] = (),
    pipelines: Iterable[str] = (),
    check_blocks: bool = True,
    unsafe_allowed: Iterable[str] | None = None,
    storage_schemes: Iterable[str] | None = None,
    schemas: Iterable[str] | None = None,
    blocks: Mapping[str, Any] | None = None,
    format_checker: FormatChecker | None = None,
    target: TriggerTarget | None = None,
) -> list[ValidationIssue]:
    """Check a document against what this instance actually has, reporting everything at once.

    ``check_blocks`` is off on the offline path, where no catalog is available to check against.
    ``unsafe_allowed`` and ``storage_schemes`` are what the instance permits and what its
    backends claim; left unset, neither is checked, because a caller that does not know them
    would otherwise refuse a document the instance would have run. ``blocks`` is the live
    contributed blocks keyed by id, which is what lets each one make its own extra refusals;
    a caller holding no host passes none and the check is the schema alone. ``format_checker``
    is the instance's assembled checker, which the pinned parameters of a schedule are checked
    against; unset, they are checked against the base formats alone, which is all a caller
    holding no host can know. ``target`` is the pipeline a triggers document names, as the
    instance holds it now; on the offline path there is none to read, and only the clocks and
    the codes are checked.
    """
    checker = format_checker if format_checker is not None else base_format_checker()
    if isinstance(definition, TriggersDefinition):
        return _triggers_document_issues(definition, checker, target, check_target=check_blocks)
    # A document that brings its own connections or schemas satisfies its own references to them.
    known = {name for name in connections} | set(definition.connections)
    known_schemas = None if schemas is None else {name for name in schemas} | set(definition.schemas)
    held = {name for name in pipelines}
    issues: list[ValidationIssue] = []
    if check_blocks:
        issues.extend(
            _requirement_issues(
                definition,
                catalog,
                known,
                held,
                None if storage_schemes is None else set(storage_schemes),
                known_schemas,
            )
        )
    malformed_params = _params_schema_issues(definition)
    issues.extend(malformed_params)
    issues.extend(_carried_schema_issues(definition))
    issues.extend(_reference_issues(definition))
    issues.extend(_trigger_issues(definition, checker, check_params=not malformed_params))
    if check_blocks:
        issues.extend(
            _step_block_issues(
                definition,
                catalog,
                known,
                None if unsafe_allowed is None else set(unsafe_allowed),
                None if storage_schemes is None else set(storage_schemes),
                blocks,
                known_schemas,
            )
        )
    return issues


def worker_routing_issues(definition: PipelineDefinition, carried: set[str]) -> list[ValidationIssue]:
    """Report the tags a document requires of a worker that no live worker carries.

    Never a refusal: workers come and go, and a run of the pipeline simply queues until one
    carrying the tags registers.
    """
    missing = [tag for tag in definition.requires.workers if tag not in carried]
    if not missing:
        return []
    return [
        ValidationIssue(
            location="requires.workers",
            message=(f"no live worker carries {', '.join(missing)}; a run of this pipeline would wait until one does"),
        )
    ]


def _params_schema_issues(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Check that the parameter schema a document declares is itself a JSON Schema.

    Nothing else ever checks it, and a schema that is not one only fails when the first run
    is created, from inside jsonschema, long after the document was stored.
    """
    if not definition.params:
        return []
    try:
        Draft202012Validator.check_schema(definition.params)
    except SchemaError as error:
        where = "/".join(str(part) for part in error.absolute_path)
        return [
            ValidationIssue(
                location="params",
                message=(
                    "the parameter schema is not itself valid JSON Schema"
                    + (f" at {where}" if where else "")
                    + f": {error.message}"
                ),
            )
        ]
    return []


def _carried_schema_issues(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Check that each schema a document carries is itself a valid JSON Schema.

    A carried schema is never stored on its own, so this apply-time check is the only thing
    that catches a body that is not a schema before a gate tries to validate against it.
    """
    issues: list[ValidationIssue] = []
    for code, body in definition.schemas.items():
        try:
            Draft202012Validator.check_schema(body)
        except SchemaError as error:
            where = "/".join(str(part) for part in error.absolute_path)
            issues.append(
                ValidationIssue(
                    location=f"schemas.{code}",
                    message=(
                        "the carried schema is not itself valid JSON Schema"
                        + (f" at {where}" if where else "")
                        + f": {error.message}"
                    ),
                )
            )
    return issues


def _trigger_issues(
    definition: Document,
    format_checker: FormatChecker,
    *,
    check_params: bool = True,
    against: PipelineDefinition | None = None,
) -> list[ValidationIssue]:
    """Check the clocks a document declares, the parameters its schedules pin, and its mappings.

    ``check_params`` is off when the parameter schema is not itself a schema, which is already
    reported and would otherwise be reported again once per trigger. ``against`` is the
    definition whose parameter schema the pins and the mappings are checked against, which for
    a triggers document is another document's current version.
    """
    from dirigent_core.triggers.schedules import (
        ScheduleError,
        ScheduleRequest,
        check_schedule,
        check_schedule_params,
    )
    from dirigent_core.triggers.webhooks import WebhookError, check_webhook_mapping

    pins_against = against if against is not None else definition
    issues: list[ValidationIssue] = []
    for index, spec in enumerate(definition.triggers.schedules):
        try:
            check_schedule(ScheduleRequest.from_spec(spec))
        except (ScheduleError, ValidationError) as error:
            issues.append(
                ValidationIssue(location=f"triggers.schedules[{index}].{spec.code}", message=str(error).strip())
            )
        if not check_params or not isinstance(pins_against, PipelineDefinition):
            continue
        try:
            check_schedule_params(pins_against, spec.params, format_checker)
        except ScheduleError as error:
            issues.append(ValidationIssue(location=f"triggers.schedules[{index}].params", message=str(error).strip()))
    if not check_params or not isinstance(pins_against, PipelineDefinition):
        return issues
    for index, hook in enumerate(definition.triggers.webhooks):
        try:
            check_webhook_mapping(pins_against, hook.params_from_payload)
        except WebhookError as error:
            issues.append(
                ValidationIssue(location=f"triggers.webhooks[{index}].params_from_payload", message=str(error).strip())
            )
    return issues


def _triggers_document_issues(
    definition: TriggersDefinition,
    format_checker: FormatChecker,
    target: TriggerTarget | None,
    *,
    check_target: bool,
) -> list[ValidationIssue]:
    """Check a triggers document: the pipeline it names, its clocks, and the pins they carry."""
    if not check_target:
        return _trigger_issues(definition, format_checker, check_params=False)
    if target is None:
        return [
            ValidationIssue(
                location="pipeline",
                message=(
                    f"no pipeline coded {definition.pipeline!r} exists on this instance; "
                    "apply it before the document that schedules it"
                ),
            )
        ]
    if not target.active:
        return [
            ValidationIssue(
                location="pipeline",
                message=(
                    f"the pipeline coded {definition.pipeline!r} is inactive; "
                    "activate it before the document that schedules it"
                ),
            )
        ]
    return _trigger_issues(definition, format_checker, against=target.definition)


def _requirement_issues(
    definition: PipelineDefinition,
    catalog: Catalog,
    connections: set[str],
    pipelines: set[str],
    schemes: set[str] | None,
    schemas: set[str] | None,
) -> list[ValidationIssue]:
    """Check the ``requires`` preflight first, with one complete list of what is missing."""
    installed = {entry.id for entry in catalog.blocks}
    issues = [
        ValidationIssue(
            location=f"requires.blocks.{index}",
            message=f"block {block!r} is not installed on this instance",
        )
        for index, block in enumerate(definition.requires.blocks)
        if block not in installed
    ]
    issues.extend(
        ValidationIssue(
            location=f"requires.connections.{index}",
            message=f"no connection coded {name!r} exists on this instance",
        )
        for index, name in enumerate(definition.requires.connections)
        if name not in connections
    )
    issues.extend(
        ValidationIssue(
            location=f"requires.pipelines.{index}",
            message=(f"no pipeline coded {name!r} exists on this instance; apply it before the document that runs it"),
        )
        for index, name in enumerate(definition.requires.pipelines)
        if name not in pipelines and name != definition.code
    )
    if schemes is not None:
        registered = ", ".join(sorted(schemes)) or "none are registered"
        issues.extend(
            ValidationIssue(
                location=f"requires.storage.{index}",
                message=f"no storage backend claims {scheme!r} ({registered})",
            )
            for index, scheme in enumerate(definition.requires.storage)
            if scheme not in schemes
        )
    if schemas is not None:
        held = ", ".join(sorted(schemas)) or "none are held"
        issues.extend(
            ValidationIssue(
                location=f"requires.schemas.{index}",
                message=f"no schema coded {name!r} exists on this instance ({held})",
            )
            for index, name in enumerate(definition.requires.schemas)
            if name not in schemas
        )
    return issues


def _step_block_issues(
    definition: PipelineDefinition,
    catalog: Catalog,
    connections: set[str],
    allowed: set[str] | None = None,
    schemes: set[str] | None = None,
    blocks: Mapping[str, Any] | None = None,
    schemas: set[str] | None = None,
) -> list[ValidationIssue]:
    """Check every step against the catalog: the block exists, and its config fits the schema."""
    issues: list[ValidationIssue] = []
    for name in sorted(definition.steps):
        step = definition.steps[name]
        entry = catalog.block(step.block)
        if entry is None:
            issues.append(
                ValidationIssue(
                    location=f"steps.{name}.block",
                    message=f"no block {step.block!r} is installed; install the plugin package that contributes it",
                )
            )
            continue
        malformed = _config_issues(name, step.config, entry.config_schema)
        issues.extend(malformed)
        issues.extend(_connection_issues(name, step.config, connections))
        issues.extend(_schema_issues(name, step.config, schemas))
        issues.extend(_allowlist_issues(name, step.block, entry, allowed))
        issues.extend(_scheme_issues(name, step.config, entry.config_schema, schemes))
        if not malformed:
            issues.extend(_block_refusals(name, step.block, step.config, blocks))
    return issues


def _block_refusals(
    step: str, block_id: str, config: JsonMap, blocks: Mapping[str, Any] | None
) -> list[ValidationIssue]:
    """Ask the live block what else it refuses, once its config is known to fit the schema.

    A config still carrying a ``${...}`` is not known yet, so it is left to the run: a block
    asked to compile a program that is a reference would refuse the reference rather than
    the program.
    """
    block = None if blocks is None else blocks.get(block_id)
    if block is None or references_in(cast("JsonValue", config)):
        return []
    try:
        validated = block.config_model.model_validate(config)
    except ValidationError:
        return []
    return [
        ValidationIssue(location=f"steps.{step}.config", message=message)
        for message in cast("list[str]", block.check_config(validated))
    ]


def _allowlist_issues(step: str, block: str, entry: Any, allowed: set[str] | None) -> list[ValidationIssue]:
    """Refuse a step whose block runs code on the worker where the instance does not allow it.

    The execution path refuses it too. Saying so at apply is what stops a document being
    stored, scheduled, and only then found to be unrunnable.
    """
    if allowed is None or not getattr(entry, "local_execution", False) or block in allowed:
        return []
    permitted = ", ".join(sorted(allowed)) or "none"
    return [
        ValidationIssue(
            location=f"steps.{step}.block",
            message=(
                f"block {block!r} executes code on the worker and DIRIGENT_ENABLED_UNSAFE_BLOCKS "
                f"does not name it (currently allowed: {permitted})"
            ),
        )
    ]


def _storage_fields(schema: JsonMap) -> set[str]:
    """Name the config fields a block publishes as storage URIs, and nothing else.

    A block says which of its strings address storage. Guessing from the value instead would
    refuse an ``http.request`` whose ``url`` is perfectly good: nothing tells the two apart
    by looking.
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return set()
    named: set[str] = set()
    for field, declared in cast("dict[str, Any]", properties).items():
        if not isinstance(declared, dict):
            continue
        shape = cast("dict[str, Any]", declared)
        options = cast("list[dict[str, Any]]", shape.get("anyOf") or [])
        shapes: list[dict[str, Any]] = [shape, *options]
        if any(one.get("format") == STORAGE_URI_FORMAT for one in shapes):
            named.add(str(field))
    return named


def _scheme_issues(step: str, config: JsonMap, schema: JsonMap, schemes: set[str] | None) -> list[ValidationIssue]:
    """Refuse a step addressing a storage scheme no backend claims."""
    if schemes is None:
        return []
    issues: list[ValidationIssue] = []
    for key in sorted(_storage_fields(schema) & set(config)):
        value = config[key]
        if not isinstance(value, str) or has_reference(value) or "://" not in value:
            continue
        scheme = value.split("://", 1)[0]
        if scheme in schemes:
            continue
        registered = ", ".join(sorted(schemes)) or "none are registered"
        issues.append(
            ValidationIssue(
                location=f"steps.{step}.config.{key}",
                message=f"no storage backend claims {scheme!r} ({registered})",
            )
        )
    return issues


def _config_issues(step: str, config: JsonMap, schema: JsonMap) -> list[ValidationIssue]:
    """Validate one step's config against its block's published schema."""
    if not schema:
        return []
    deferred = defer_references(config)
    validator: Any = ConfigValidator(schema)
    raised: Any = validator.iter_errors(deferred)  # pyright: ignore[reportUnknownMemberType]
    found = cast("list[SchemaValidationError]", list(raised))
    issues: list[ValidationIssue] = []
    for error in sorted(found, key=lambda item: [str(part) for part in item.absolute_path]):
        path = ".".join(str(part) for part in error.absolute_path)
        issues.append(
            ValidationIssue(
                location=f"steps.{step}.config" + (f".{path}" if path else ""),
                message=error.message,
            )
        )
    return issues


def _connection_issues(step: str, config: JsonMap, connections: set[str]) -> list[ValidationIssue]:
    """Refuse a step naming a connection this instance does not hold."""
    named = config.get("connection")
    if not isinstance(named, str) or has_reference(named) or named in connections:
        return []
    available = ", ".join(sorted(connections)) or "this instance has no connections"
    return [
        ValidationIssue(
            location=f"steps.{step}.config.connection",
            message=f"no connection coded {named!r} exists ({available})",
        )
    ]


def _schema_issues(step: str, config: JsonMap, schemas: set[str] | None) -> list[ValidationIssue]:
    """Refuse a step naming a schema no instance holds and the document does not carry."""
    if schemas is None:
        return []
    named = config.get("schema")
    if not isinstance(named, str) or has_reference(named) or named in schemas:
        return []
    available = ", ".join(sorted(schemas)) or "this instance holds no schemas"
    return [
        ValidationIssue(
            location=f"steps.{step}.config.schema",
            message=f"no schema coded {named!r} exists ({available})",
        )
    ]


def _reference_issues(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Check every ``${...}`` a document writes against what a run will actually have."""
    declared = _declared_params(definition.params)
    issues: list[ValidationIssue] = []
    for name in sorted(definition.steps):
        step = definition.steps[name]
        upstream = _ancestors(definition, name)
        family = set(definition.grid_family(name))
        for reference in sorted(set(references_in(cast("JsonValue", step.config)))):
            problem = _reference_problem(reference.strip(), definition, name, upstream, declared, family)
            if problem is not None:
                issues.append(ValidationIssue(location=f"steps.{name}.config", message=problem))
        issues.extend(_fan_out_literal_issues(name, step.for_each))
        issues.extend(_adoption_issues(definition, name))
        # for_each carries one extra rule: cardinality is fixed when the run is created, so
        # it cannot read a step's output.
        for reference in sorted(set(references_in(cast("JsonValue", step.for_each)))):
            problem = _for_each_problem(reference.strip(), definition, name, declared)
            if problem is not None:
                issues.append(ValidationIssue(location=f"steps.{name}.for_each", message=problem))
    return issues


def _fan_out_literal_issues(step: str, for_each: str | list[JsonValue] | None) -> list[ValidationIssue]:
    """Refuse a ``for_each`` string that interpolates nothing, since it stays a string at run time."""
    if not isinstance(for_each, str) or has_reference(for_each):
        return []
    return [
        ValidationIssue(
            location=f"steps.{step}.for_each",
            message=(
                f"for_each is a literal string, not a list: {for_each!r} maps over nothing. "
                "Write a list, or an interpolation such as ${params.regions}"
            ),
        )
    ]


def _adoption_issues(definition: PipelineDefinition, step: str) -> list[ValidationIssue]:
    """Refuse ``rule: one_failed`` on a step that maps over another fan-out's grid.

    That rule fires as soon as one prerequisite has failed, while the rest are still running,
    so the step it belongs to would be claimed before the grid it pairs with has settled.
    """
    if definition.steps[step].adopted_grid is None or definition.steps[step].rule is not TriggerRule.ONE_FAILED:
        return []
    return [
        ValidationIssue(
            location=f"steps.{step}.rule",
            message=(
                "a step that maps over another fan-out's items cannot use one_failed, which is ready "
                "before that fan-out has finished producing them"
            ),
        )
    ]


def _for_each_problem(
    reference: str,
    definition: PipelineDefinition,
    step: str,
    declared: set[str] | None,
) -> str | None:
    """Say what is wrong with a reference inside ``for_each``, or nothing when it will resolve."""
    parts = [part for part in reference.split(".") if part]
    match parts:
        case ["steps", target, "items"] if definition.steps[step].adopted_grid == target:
            return _adopted_grid_problem(reference, definition, step, target)
        case ["steps", *_]:
            return (
                f"${{{reference}}} reads a step's output, and fan-out is expanded when the run is created: "
                "for_each may read params, run, and an upstream fan-out's grid as ${steps.<name>.items}, "
                "but not a step's output"
            )
        case ["item", *_]:
            return f"${{{reference}}} reads the fan-out item, which does not exist yet inside for_each itself"
        case _:
            return _reference_problem(reference, definition, step, set(), declared, set())


def _adopted_grid_problem(reference: str, definition: PipelineDefinition, step: str, target: str) -> str | None:
    """Say why a step cannot map over the grid it named, or nothing when it may."""
    if target not in definition.steps:
        return f"${{{reference}}} names step {target!r}, which this pipeline does not have"
    if not definition.steps[target].is_fan_out:
        return f"${{{reference}}} maps over step {target!r}'s items, but {target!r} has no for_each"
    if target not in definition.steps[step].depends_on:
        return (
            f"${{{reference}}} maps over step {target!r}'s items, so {target!r} must be a direct "
            f"prerequisite of {step!r}; add it to depends_on"
        )
    return None


def _reference_problem(
    reference: str,
    definition: PipelineDefinition,
    step: str,
    upstream: set[str],
    declared: set[str] | None,
    family: set[str],
) -> str | None:
    """Say what is wrong with one reference, or nothing when it will resolve.

    ``family`` names the fan-outs this step shares a grid with, which are the only steps whose
    matching item it may read.
    """
    parts = [part for part in reference.split(".") if part]
    match parts:
        case []:
            return "${} names nothing"
        case ["params", parameter, *_] if declared is not None and parameter not in declared:
            available = ", ".join(sorted(declared)) or "the pipeline declares no parameters"
            return f"${{{reference}}} reads an undeclared parameter ({available})"
        case ["params", *_]:
            return None
        case ["item", *_]:
            if not definition.steps[step].is_fan_out:
                return f"${{{reference}}} reads the fan-out item, but step {step!r} has no for_each"
            return None
        case ["steps", target, "output", *_]:
            if target not in definition.steps:
                return f"${{{reference}}} names step {target!r}, which this pipeline does not have"
            if target not in upstream:
                return (
                    f"${{{reference}}} reads step {target!r}, which is not a prerequisite of {step!r}; "
                    f"add it to depends_on"
                )
            return None
        case ["steps", target, "items"]:
            return (
                f"${{{reference}}} names the list step {target!r} maps over, which only for_each reads; "
                f"inside config, read the matching item with ${{steps.{target}.item.output.<field>}}"
            )
        case ["steps", target, "item", "output", *_]:
            if target not in definition.steps:
                return f"${{{reference}}} names step {target!r}, which this pipeline does not have"
            if target not in family:
                return (
                    f"${{{reference}}} reads step {target!r}'s matching item, but {step!r} does not fan over "
                    f"{target!r}'s items; write for_each: ${{steps.{target}.items}}"
                )
            return None
        case ["steps", _, "item", *_]:
            return f"${{{reference}}} is malformed: a matching item reads steps.<name>.item.output.<field>"
        case ["steps", *_]:
            return (
                f"${{{reference}}} is malformed: a step reference reads steps.<name>.output.<field>, "
                "steps.<name>.items, or steps.<name>.item.output.<field>"
            )
        case ["run", "scratch"] | ["run", "id"] | ["run", "window", "start"] | ["run", "window", "end"]:
            return None
        case ["run", *_]:
            return (
                f"${{{reference}}} is malformed: run exposes only run.scratch, run.id, "
                "run.window.start and run.window.end"
            )
        case [namespace, *_]:
            return f"${{{reference}}} names {namespace!r}, which is not one of params, steps, item, run"
        case _:  # pragma: no cover - every shape above is total over a list of strings
            return None


def _declared_params(schema: JsonMap) -> set[str] | None:
    """List the parameter names a schema declares, or None when it accepts anything."""
    if schema.get("additionalProperties") is True:
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    return set(cast("Mapping[str, object]", properties))


def _ancestors(definition: PipelineDefinition, name: str) -> set[str]:
    """List every step a step transitively depends on."""
    seen: set[str] = set()
    frontier = list(definition.steps[name].depends_on)
    while frontier:
        current = frontier.pop()
        if current in seen or current not in definition.steps:
            continue
        seen.add(current)
        frontier.extend(definition.steps[current].depends_on)
    return seen


class DocumentSummary(BaseModel):
    """What a document says about itself, for a plan, a listing, or a diff."""

    model_config = ConfigDict(frozen=True)

    kind: str = KIND_PIPELINE
    code: str
    name: str | None = None
    description: str | None = None
    pipeline: str | None = None
    """The pipeline a triggers document fires; a pipeline document names none but itself."""

    steps: list[str] = Field(default_factory=list[str])
    blocks: list[str] = Field(default_factory=list[str])
    schedules: list[str] = Field(default_factory=list[str])
    webhooks: list[str] = Field(default_factory=list[str])
    digest: str


def summarize(definition: Document) -> DocumentSummary:
    """Reduce a definition to the handful of facts a plan or a listing shows."""
    pipeline = definition.pipeline if isinstance(definition, TriggersDefinition) else None
    steps = sorted(definition.steps) if isinstance(definition, PipelineDefinition) else []
    blocks = (
        sorted({step.block for step in definition.steps.values()}) if isinstance(definition, PipelineDefinition) else []
    )
    return DocumentSummary(
        kind=definition.kind,
        code=definition.code,
        name=definition.name,
        description=definition.description,
        pipeline=pipeline,
        steps=steps,
        blocks=blocks,
        schedules=[spec.code for spec in definition.triggers.schedules],
        webhooks=[spec.code for spec in definition.triggers.webhooks],
        digest=digest_of(definition),
    )
