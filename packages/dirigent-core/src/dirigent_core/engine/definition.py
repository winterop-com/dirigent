"""The pipeline definition model: one immutable document per version, shared by everything."""

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from dirigent_client.enums import RunPriority
from dirigent_common import TEMPLATE_MEDIA_TYPE, EntityName, JsonMap, StepName, TemplateError, compile_template
from dirigent_common.durations import Duration
from dirigent_plugin import BLOCK_ID_PATTERN

FORMAT_V1: Final = "dirigent/v1"

KIND_PIPELINE: Final = "pipeline"

KIND_TRIGGERS: Final = "triggers"

EMPTY_PARAMS_SCHEMA: JsonMap = {"type": "object", "properties": {}}

#: A tag as it is stored and compared: the entity-name family, loosened -- a tag is a label
#: somebody types into a filter, not a key anything is addressed by, so a trailing or doubled
#: hyphen is nobody's ambiguity to resolve.
TAG_PATTERN: Final = r"^[a-z0-9][a-z0-9-]*$"

#: A tag as a document may write it. Case is normalised away at validation, so the schema an
#: editor squiggles against accepts a spelling the validator will lowercase.
TAG_WRITTEN_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9-]*$"

TAG_MAX_LENGTH: Final = 32

#: How many tags one document may declare. A vocabulary is a handful of words; a document
#: wearing twenty of them has stopped saying anything.
MAX_TAGS: Final = 16

_TAG = re.compile(TAG_PATTERN)


class ParameterError(ValueError):
    """Supplied run parameters did not satisfy the pipeline's parameter schema."""


class TriggerRule(StrEnum):
    """Edge condition for step readiness, using Airflow's vocabulary and values."""

    ALL_SUCCESS = "all_success"
    ALL_DONE = "all_done"
    ONE_FAILED = "one_failed"
    ALWAYS = "always"


class ConcurrencyPolicy(StrEnum):
    """What a pipeline does when a run starts while another is still going."""

    ALLOW = "allow"
    SKIP = "skip"
    QUEUE = "queue"
    REPLACE = "replace"


class ItemPolicy(StrEnum):
    """Whether one bad item sinks a fan-out batch."""

    FAIL_FAST = "fail_fast"

    CONTINUE = "continue"
    """Other items carry on; the run reports completed_with_errors."""


class TimeoutAction(StrEnum):
    """What a sensor's expired deadline means."""

    FAIL = "fail"
    """The step failed, and dependents behind all_success are skipped."""

    SKIP = "skip"
    """The step is skipped, which downstream trigger rules can see."""


class RetryPolicy(BaseModel):
    """Per-step retry: how many tries, how long between them, and how far apart they spread."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=100)
    """Total automatic attempts, including the first one."""

    backoff: Duration = timedelta(seconds=30)
    """The delay after the first failure; later ones multiply from it."""

    max_backoff: Duration = timedelta(hours=1)

    multiplier: float = Field(default=2.0, ge=1.0, le=10.0)

    jitter: float = Field(default=0.2, ge=0.0, le=1.0)
    """Fraction of the delay to spread randomly, so retries do not synchronise."""


class StepDefinition(BaseModel):
    """One node in the DAG: a block reference plus the engine semantics around it.

    The field order here is the canonical export order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    """A human title for this step; the map key stays the only thing that references it."""

    block: str = Field(pattern=BLOCK_ID_PATTERN)
    """The catalog id of the operator or sensor this step runs."""

    depends_on: list[StepName] = Field(default_factory=list[str])
    """Prerequisite step names; edges point from prerequisite to dependent."""

    rule: TriggerRule = TriggerRule.ALL_SUCCESS

    for_each: str | list[JsonValue] | None = None
    """A reference to a list, or a literal list: one run item per element."""

    items: ItemPolicy = ItemPolicy.FAIL_FAST

    config: JsonMap = Field(default_factory=dict)
    """Block config, opaque to the document format and validated against the block's model."""

    retry: RetryPolicy = RetryPolicy()

    timeout: Duration | None = None
    """How long one block call may take before it is abandoned as a transient failure."""

    poll: Duration | None = None
    """Sensor cadence; defaults to the sensor's own declared default."""

    deadline: Duration | None = None
    """How long a step may wait on a sensor or a remote job before the timeout applies."""

    on_timeout: TimeoutAction = TimeoutAction.FAIL

    continue_on_failure: bool = False
    """Treat a failure as tolerated: dependents still run, the run completes with errors."""

    @property
    def is_fan_out(self) -> bool:
        """Report whether this step maps over a list rather than running once."""
        return self.for_each is not None


def anchor_naive_moment(moment: datetime | None, timezone: str) -> datetime | None:
    """Read a one-time schedule's ``at`` in the zone the schedule itself declares.

    A naive moment left as it is would make every later comparison against an aware "now"
    raise ``TypeError`` inside the scheduler tick.
    """
    if moment is None or moment.tzinfo is not None:
        return moment
    from dirigent_core.triggers.schedules import resolve_zone

    return moment.replace(tzinfo=resolve_zone(timezone))


class ScheduleSpec(BaseModel):
    """A pipeline's own clock, carried in the document: cron, interval, or a one-time firing.

    Only the declaration travels: operational state stays in the instance, which is why there
    is no ``paused`` field here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: EntityName
    name: str | None = None
    description: str | None = None
    cron: str | None = None
    interval: Duration | None = None
    at: datetime | None = None
    timezone: str = "UTC"
    params: JsonMap = Field(default_factory=dict)
    priority: RunPriority | None = None
    """The priority every fired run carries, or null to take the pipeline's own."""

    @model_validator(mode="after")
    def _exactly_one_clock(self) -> Self:
        """Reject a schedule that names no clock, or more than one, and anchor a naive moment."""
        declared = [field for field in ("cron", "interval", "at") if getattr(self, field) is not None]
        if len(declared) != 1:
            named = ", ".join(declared) or "none"
            raise ValueError(f"schedule {self.code!r} must declare exactly one of cron, interval, or at ({named})")
        anchored = anchor_naive_moment(self.at, self.timezone)
        return self if anchored is self.at else self.model_copy(update={"at": anchored})


class WebhookSpec(BaseModel):
    """An inbound endpoint declared by the document; its token is minted by the instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: EntityName
    name: str | None = None
    description: str | None = None
    params_from_payload: dict[str, str] = Field(default_factory=dict[str, str])
    """Strict payload-to-parameter mapping; anything unmapped is rejected at intake."""

    priority: RunPriority | None = None
    """The priority every accepted delivery's run carries, or null to take the pipeline's own."""


class TriggerSpecs(BaseModel):
    """The triggers a document declares, which travel with it but stay optional."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedules: list[ScheduleSpec] = Field(default_factory=list[ScheduleSpec])
    webhooks: list[WebhookSpec] = Field(default_factory=list[WebhookSpec])

    @property
    def empty(self) -> bool:
        """Report whether this document declares no triggers at all."""
        return not self.schedules and not self.webhooks


class Requirements(BaseModel):
    """What a shared document needs from the instance before it can be applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    blocks: list[str] = Field(default_factory=list[str])
    connections: list[EntityName] = Field(default_factory=list[str])
    pipelines: list[EntityName] = Field(default_factory=list[str])
    """Pipelines this one starts with ``pipeline.run``, and therefore cannot run without."""

    storage: list[str] = Field(default_factory=list[str])
    """Storage this document writes through, named by scheme, such as ``s3``; some backend
    on the instance must claim each one."""

    schemas: list[EntityName] = Field(default_factory=list[str])
    """Named JSON Schemas this document references, by code; the instance must hold each one."""

    workers: list[EntityName] = Field(default_factory=list[str])
    """Capability tags a worker must carry to claim this pipeline's work, such as ``docker``.
    A run pins the list at creation, and only a worker carrying every tag claims it."""

    @property
    def empty(self) -> bool:
        """Report whether this document requires nothing in particular."""
        return not (self.blocks or self.connections or self.pipelines or self.storage or self.schemas or self.workers)


class ReportSpec(BaseModel):
    """The report document a run renders when it settles; no template means the built-in one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    template: Annotated[str | None, Field(json_schema_extra={"contentMediaType": TEMPLATE_MEDIA_TYPE})] = None

    @field_validator("template")
    @classmethod
    def _check_template(cls, template: str | None) -> str | None:
        """Refuse a template that does not compile, at apply rather than at settlement."""
        if template is not None:
            try:
                compile_template(template)
            except TemplateError as error:
                raise ValueError(str(error)) from error
        return template


class ConnectionDefinition(BaseModel):
    """A connection a document carries with it, rather than naming one the instance holds.

    For a document that has to run on its own -- a published example, a reproduction -- with
    no instance to create a connection on first. A server refuses a document that embeds one,
    because applying it would store the credential in every version of the pipeline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = "http"
    config: JsonMap = Field(default_factory=dict)


class PipelineDefinition(BaseModel):
    """A ``dirigent/v1`` pipeline document: steps, edges, parameter schema, triggers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["dirigent/v1"] = FORMAT_V1
    kind: Literal["pipeline"] = KIND_PIPELINE
    code: EntityName
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(
        default_factory=list[str],
        json_schema_extra={
            "items": {"type": "string", "pattern": TAG_WRITTEN_PATTERN},
            "maxItems": MAX_TAGS,
            "uniqueItems": True,
        },
    )
    """What this pipeline is for, in the words a corpus is filtered by."""

    concurrency: ConcurrencyPolicy = ConcurrencyPolicy.ALLOW
    priority: RunPriority = RunPriority.NORMAL
    """How far ahead of other runs the claim takes this pipeline's attempts.

    A trigger may override it for what it fires, and an ad hoc run may override it again."""

    params: JsonMap = Field(default_factory=lambda: dict(EMPTY_PARAMS_SCHEMA))
    steps: dict[StepName, StepDefinition] = Field(min_length=1)
    triggers: TriggerSpecs = Field(default_factory=TriggerSpecs)
    requires: Requirements = Field(default_factory=Requirements)
    report: ReportSpec | None = None
    """The document a settled run renders from its own facts; absent renders nothing."""

    connections: dict[EntityName, ConnectionDefinition] = Field(default_factory=dict[str, "ConnectionDefinition"])
    """Connections the document brings, for a run with no instance to name them on."""
    schemas: dict[EntityName, JsonMap] = Field(default_factory=dict[str, "JsonMap"])
    """JSON Schemas the document brings, keyed by code, for a run with no instance to hold them."""

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, tags: list[str]) -> list[str]:
        """Lowercase each tag, then refuse one that is not a tag, a repetition, and a crowd.

        Normalising here is what lets every comparison after it be exact: the instance stores
        what this returns, so a listing narrows with ``=`` rather than a rule each caller has
        to reapply.
        """
        if len(tags) > MAX_TAGS:
            raise ValueError(f"a document declares at most {MAX_TAGS} tags, and this one declares {len(tags)}")
        normalised: list[str] = []
        seen: set[str] = set()
        for index, written in enumerate(tags):
            tag = written.lower()
            if _TAG.fullmatch(tag) is None or len(tag) > TAG_MAX_LENGTH:
                raise ValueError(
                    f"tags[{index}] {written!r} is not a valid tag: a tag is lowercased, and what is left "
                    f"must be letters, digits and hyphens, start with a letter or digit, and be at most "
                    f"{TAG_MAX_LENGTH} characters"
                )
            if tag in seen:
                raise ValueError(f"tags[{index}] {tag!r} is declared twice; a tag says one thing once")
            seen.add(tag)
            normalised.append(tag)
        return normalised

    @model_validator(mode="after")
    def _check_graph(self) -> Self:
        """Reject unknown step names, self-edges, and any cycle."""
        for name, step in self.steps.items():
            for dependency in step.depends_on:
                if dependency == name:
                    raise ValueError(f"step {name!r} depends on itself")
                if dependency not in self.steps:
                    raise ValueError(f"step {name!r} depends on unknown step {dependency!r}")
        _require_acyclic(self.steps)
        _require_unique_trigger_codes(self.triggers)
        return self

    @property
    def roots(self) -> list[str]:
        """List the steps with no prerequisites."""
        return [name for name, step in self.steps.items() if not step.depends_on]

    def dependents_of(self, name: str) -> list[str]:
        """List the steps that name a step as a prerequisite."""
        return [other for other, step in self.steps.items() if name in step.depends_on]

    def descendants_of(self, name: str) -> list[str]:
        """List every step reachable downstream of a step, transitively."""
        seen: set[str] = set()
        frontier = list(self.dependents_of(name))
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(self.dependents_of(current))
        return sorted(seen)

    def topological_order(self) -> list[str]:
        """Order the steps so every prerequisite precedes its dependents."""
        remaining = {name: set(step.depends_on) for name, step in self.steps.items()}
        ordered: list[str] = []
        while remaining:
            ready = sorted(name for name, pending in remaining.items() if not pending)
            for name in ready:
                ordered.append(name)
                del remaining[name]
            for pending in remaining.values():
                pending.difference_update(ready)
        return ordered

    def validate_params(self, params: JsonMap, format_checker: FormatChecker) -> JsonMap:
        """Validate supplied parameters against the pipeline's own schema, filling defaults.

        ``format_checker`` is the instance's assembled checker, so a ``format`` a parameter
        declares asserts here exactly as it does at a ``validate.schema`` gate.

        The schema is checked before it is used, because a version stored before that check
        existed can hold a schema that is not one, and jsonschema then raises something no
        caller of this method catches.
        """
        resolved = _with_defaults(self.params, params)
        try:
            Draft202012Validator.check_schema(self.params)
            Draft202012Validator(self.params, format_checker=format_checker).validate(resolved)  # pyright: ignore[reportUnknownMemberType]
        except SchemaValidationError as error:
            location = "/".join(str(part) for part in error.absolute_path) or "(root)"
            raise ParameterError(f"parameter {location} is invalid: {error.message}") from error
        except Exception as error:
            # Anything but a validation error here is the pipeline's schema failing, not the
            # supplied parameters: an unknown type, an unresolvable $ref, a subschema that is
            # not a schema. Each raises a different jsonschema type, several of them private.
            raise ParameterError(
                f"the pipeline's parameter schema is not itself valid JSON Schema ({_schema_problem(error)}); "
                "apply a corrected document to fix it"
            ) from error
        return resolved


def _schema_problem(error: Exception) -> str:
    """Reduce a jsonschema failure over a malformed schema to its first line."""
    message = getattr(error, "message", None)
    text = str(message) if isinstance(message, str) else str(error)
    return text.strip().splitlines()[0] if text.strip() else error.__class__.__name__


class TriggersDefinition(BaseModel):
    """A ``dirigent/v1`` triggers document: clocks and webhooks for a pipeline defined elsewhere."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["dirigent/v1"] = FORMAT_V1
    kind: Literal["triggers"] = KIND_TRIGGERS
    code: EntityName
    name: str | None = None
    description: str | None = None
    pipeline: EntityName
    """The code of the pipeline these triggers fire."""

    triggers: TriggerSpecs = Field(default_factory=TriggerSpecs)
    """What this document declares; empty retires everything it owned."""

    @model_validator(mode="after")
    def _check_trigger_codes(self) -> Self:
        """Reject two schedules or two webhooks sharing a code."""
        _require_unique_trigger_codes(self.triggers)
        return self


#: Either kind of ``dirigent/v1`` document.
type Document = PipelineDefinition | TriggersDefinition


def load_definition(document: JsonMap) -> PipelineDefinition:
    """Parse a stored pipeline version document into the model the engine walks."""
    return PipelineDefinition.model_validate(document)


def dump_definition(definition: PipelineDefinition) -> JsonMap:
    """Serialize a definition to the canonical JSON document a pipeline version row stores."""
    return canonical_document(definition)


def canonical_document(definition: "Document") -> JsonMap:
    """Render a definition in the one shape every export, digest, and stored row uses.

    The output is a function of the definition alone, never of the order an author typed:
    PostgreSQL's ``jsonb`` does not preserve key order, so a document stored and read back
    would otherwise export differently than it went in. Model fields keep their declaration
    order, steps are written in topological order, and maps the format does not interpret get
    the fixed key order in :data:`PREFERRED_KEYS`.
    """
    dumped = definition.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    tagged: JsonMap = {"format": definition.format, "kind": definition.kind}
    tagged.update({key: value for key, value in dumped.items() if key not in tagged})
    if isinstance(definition, PipelineDefinition):
        tagged["steps"] = {name: cast("JsonMap", tagged["steps"])[name] for name in definition.topological_order()}
    return cast("JsonMap", _canonicalize(tagged))


#: Keys whose values the format does not interpret, and which therefore get a fixed key order.
OPAQUE_KEYS = frozenset({"params", "config", "params_from_payload"})

#: The order the well-known schema keys are written in; everything else follows, sorted.
PREFERRED_KEYS: tuple[str, ...] = (
    "type",
    "title",
    "description",
    "format",
    "enum",
    "const",
    "default",
    "required",
    "properties",
    "items",
    "additionalProperties",
)


def _canonicalize(value: JsonValue) -> JsonValue:
    """Impose the canonical key order on a dumped document."""
    match value:
        case dict():
            return {
                key: (_ordered_opaque(item) if key in OPAQUE_KEYS else _canonicalize(item))
                for key, item in value.items()
            }
        case list():
            return [_canonicalize(item) for item in value]
        case _:
            return value


def _ordered_opaque(value: JsonValue) -> JsonValue:
    """Order the keys of an opaque map: the well-known ones first, then the rest sorted."""
    match value:
        case dict():
            preferred = [key for key in PREFERRED_KEYS if key in value]
            rest = sorted(key for key in value if key not in PREFERRED_KEYS)
            return {key: _ordered_opaque(value[key]) for key in [*preferred, *rest]}
        case list():
            return [_ordered_opaque(item) for item in value]
        case _:
            return value


def _require_unique_trigger_codes(triggers: TriggerSpecs) -> None:
    """Reject two schedules or two webhooks sharing a code."""
    for label, codes in (
        ("schedule", [schedule.code for schedule in triggers.schedules]),
        ("webhook", [webhook.code for webhook in triggers.webhooks]),
    ):
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if duplicates:
            raise ValueError(f"duplicate {label} codes: {', '.join(duplicates)}")


def _require_acyclic(steps: dict[str, StepDefinition]) -> None:
    """Reject a definition whose edges loop, naming the steps still tangled."""
    remaining = {name: set(step.depends_on) for name, step in steps.items()}
    while remaining:
        ready = {name for name, pending in remaining.items() if not pending}
        if not ready:
            raise ValueError(f"the steps {sorted(remaining)} form a cycle")
        for name in ready:
            del remaining[name]
        for pending in remaining.values():
            pending.difference_update(ready)


def _with_defaults(schema: JsonMap, params: JsonMap) -> JsonMap:
    """Fill in the defaults a parameter schema declares, without touching supplied values."""
    properties: object = schema.get("properties")
    if not isinstance(properties, dict):
        return dict(params)
    filled = dict(params)
    for name, declared in cast("dict[str, object]", properties).items():
        if name not in filled and isinstance(declared, dict) and "default" in declared:
            filled[name] = cast("dict[str, object]", declared)["default"]
    return filled
