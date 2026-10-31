"""What a pipeline with sources and replies must satisfy before it is stored.

Every rule here reads the document and the kinds alone. That two pipelines do not claim one
route is a question for the instance, and is asked where the instance is read.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from dirigent_client.schemas import ValidationIssue
from dirigent_common import JsonMap, format_duration, validation_issue
from dirigent_core.engine.definition import (
    LONGEST_CADENCE,
    ConcurrencyPolicy,
    PipelineDefinition,
    TriggerRule,
    TriggerSpecs,
)
from dirigent_core.messages import (
    JOIN_OF_SOURCES,
    REPLACE_ON_HELD,
    REPLY_NO_SOURCE,
    REPLY_NOT_A_LEAF,
    REQUIRED_PARAM_ON_SOURCES,
    ROOT_BESIDE_SOURCES,
    ROUTE_CLAIMED,
    SAMPLE_INVALID,
    SAMPLE_NOT_AN_OBJECT,
    SCHEDULE_ON_SOURCES,
    SOURCE_POLL_TOO_LONG,
    UNKNOWN_KIND,
)
from dirigent_plugin.sources import AnySource, PolledSource, ReceivedSource, SourceHosting

#: The moment a sample is made whole at, which only its ``received_at`` default reads.
SAMPLE_MOMENT = datetime(2026, 1, 1, tzinfo=UTC)


def source_issues(definition: PipelineDefinition, kinds: Mapping[str, AnySource]) -> list[ValidationIssue]:
    """Check a document's sources and replies against the rules of the node model."""
    issues: list[ValidationIssue] = []
    issues.extend(_kind_issues(definition, kinds))
    issues.extend(_reply_issues(definition, kinds))
    sources = definition.sources
    if not sources:
        return issues
    issues.extend(
        ValidationIssue.of(ROOT_BESIDE_SOURCES, location=f"steps.{name}", step=repr(name))
        for name in definition.roots
        if name not in sources
    )
    issues.extend(_join_issues(definition))
    issues.extend(triggers_issues(definition.code, definition.triggers))
    issues.extend(_param_issues(definition))
    issues.extend(_concurrency_issues(definition, kinds))
    issues.extend(_route_issues_within(definition, kinds))
    return issues


def triggers_issues(code: str, triggers: TriggerSpecs, *, prefix: str = "triggers") -> list[ValidationIssue]:
    """Refuse a schedule on a pipeline with sources: whatever it started would enter no source."""
    return [
        ValidationIssue.of(SCHEDULE_ON_SOURCES, location=f"{prefix}.schedules[{index}]", code=repr(code))
        for index, _ in enumerate(triggers.schedules)
    ]


def source_config(kind: AnySource, config: JsonMap) -> BaseModel:
    """Validate a source's own fields into its kind's config model."""
    return kind.config_model.model_validate(config)


def _kind_issues(definition: PipelineDefinition, kinds: Mapping[str, AnySource]) -> list[ValidationIssue]:
    """Check each source's kind exists, its fields fit the kind, and its sample can be made whole."""
    issues: list[ValidationIssue] = []
    for name in definition.sources:
        node = definition.steps[name].source
        if node is None:  # pragma: no cover - sources lists only steps that are
            continue
        kind = kinds.get(node.kind)
        if kind is None:
            known = ", ".join(sorted(kinds)) or "none are installed"
            issues.append(
                ValidationIssue.of(
                    UNKNOWN_KIND, location=f"steps.{name}.source.kind", kind=repr(node.kind), known=known
                )
            )
            continue
        try:
            config = source_config(kind, node.config)
        except ValidationError as error:
            issues.extend(_located(f"steps.{name}.source", error))
            continue
        issues.extend(
            ValidationIssue(
                location=f"steps.{name}.source" + (f".{issue.location}" if issue.location else ""),
                message=issue.message,
                code=issue.code,
                params=issue.params,
            )
            for issue in kind.check_config(config)
        )
        if isinstance(kind, PolledSource) and kind.poll_every(config) > LONGEST_CADENCE:
            issues.append(
                ValidationIssue.of(
                    SOURCE_POLL_TOO_LONG,
                    location=f"steps.{name}.source.poll",
                    poll=format_duration(kind.poll_every(config)),
                    limit=format_duration(LONGEST_CADENCE),
                )
            )
        sample = definition.steps[name].sample
        if sample is None:
            continue
        try:
            if not isinstance(sample, dict):
                raise ValueError(SAMPLE_NOT_AN_OBJECT.render(kind=type(sample).__name__))
            kind.complete(config, cast("JsonMap", sample), received_at=SAMPLE_MOMENT)
        except (ValueError, ValidationError) as error:
            issues.append(
                ValidationIssue.of(
                    SAMPLE_INVALID,
                    location=f"steps.{name}.sample",
                    step=repr(name),
                    kind=repr(node.kind),
                    detail=_first_line(error),
                )
            )
    return issues


def _reply_issues(definition: PipelineDefinition, kinds: Mapping[str, AnySource]) -> list[ValidationIssue]:
    """Refuse a reply something depends on, and a reply no replying source reaches."""
    issues: list[ValidationIssue] = []
    for name in definition.replies:
        for dependent in definition.dependents_of(name):
            issues.append(
                ValidationIssue.of(
                    REPLY_NOT_A_LEAF,
                    location=f"steps.{dependent}.depends_on",
                    dependent=repr(dependent),
                    step=repr(name),
                )
            )
        replying = [
            source
            for source in definition.ancestors_of(name)
            if (node := definition.steps[source].source) is not None
            and (kind := kinds.get(node.kind)) is not None
            and kind.spec.replies
        ]
        if not replying:
            issues.append(ValidationIssue.of(REPLY_NO_SOURCE, location=f"steps.{name}", step=repr(name)))
    return issues


def entries(definition: PipelineDefinition) -> dict[str, frozenset[str]]:
    """Say, for every step, which sources a run can enter at and still have it run.

    A source runs when it is entered. ``all_success`` needs every prerequisite, so it keeps
    only the entries they share; ``one_failed`` needs one of them to have run; ``all_done``
    and ``always`` run once their prerequisites settle, which they do whatever was entered.
    """
    every = frozenset(definition.sources)
    reached: dict[str, frozenset[str]] = {}
    for name in definition.topological_order():
        step = definition.steps[name]
        if step.source is not None:
            reached[name] = frozenset({name})
            continue
        upstream = [reached[dependency] for dependency in step.depends_on]
        match step.rule:
            case TriggerRule.ALL_SUCCESS:
                shared = every
                for one in upstream:
                    shared &= one
                reached[name] = shared if upstream else every
            case TriggerRule.ONE_FAILED:
                either: set[str] = set()
                for one in upstream:
                    either |= one
                reached[name] = frozenset(either)
            case _:
                reached[name] = every
    return reached


def _join_issues(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Refuse an ``all_success`` step whose prerequisites can only run under different entries."""
    reached = entries(definition)
    issues: list[ValidationIssue] = []
    for name in definition.topological_order():
        step = definition.steps[name]
        if step.source is not None or step.rule is not TriggerRule.ALL_SUCCESS or reached[name]:
            continue
        upstream = [(dependency, reached[dependency]) for dependency in step.depends_on]
        if any(not one for _, one in upstream):
            continue
        first, second = _disjoint_pair(upstream)
        issues.append(
            ValidationIssue.of(
                JOIN_OF_SOURCES,
                location=f"steps.{name}.rule",
                step=repr(name),
                first=repr(first),
                second=repr(second),
            )
        )
    return issues


def _disjoint_pair(upstream: list[tuple[str, frozenset[str]]]) -> tuple[str, str]:
    """Name one source from each of two prerequisites that share no entry."""
    for index, (_, left) in enumerate(upstream):
        for _, right in upstream[index + 1 :]:
            if not left & right:
                return sorted(left)[0], sorted(right)[0]
    names: set[str] = set()
    for _, one in upstream:
        names |= one
    ordered = sorted(names)
    return ordered[0], ordered[-1]


def _param_issues(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Refuse a required parameter with no default, which a run a source creates cannot give."""
    properties = definition.params.get("properties")
    declared = cast("dict[str, Any]", properties) if isinstance(properties, dict) else {}
    required = definition.params.get("required")
    listed = (
        [name for name in cast("list[object]", required) if isinstance(name, str)] if isinstance(required, list) else []
    )
    return [
        ValidationIssue.of(REQUIRED_PARAM_ON_SOURCES, location=f"params.properties.{name}", name=repr(name))
        for name in listed
        if not (isinstance(declared.get(name), dict) and "default" in cast("dict[str, Any]", declared[name]))
    ]


def _concurrency_issues(definition: PipelineDefinition, kinds: Mapping[str, AnySource]) -> list[ValidationIssue]:
    """Refuse ``replace`` and ``skip`` beside a source a worker polls or holds: either drops an input it took."""
    if definition.concurrency not in {ConcurrencyPolicy.REPLACE, ConcurrencyPolicy.SKIP}:
        return []
    for name in definition.sources:
        node = definition.steps[name].source
        kind = kinds.get(node.kind) if node is not None else None
        if kind is not None and kind.spec.hosting is not SourceHosting.RECEIVED:
            return [
                ValidationIssue.of(
                    REPLACE_ON_HELD,
                    location="concurrency",
                    code=repr(definition.code),
                    hosting=kind.spec.hosting.value,
                    policy=definition.concurrency.value,
                )
            ]
    return []


def declared_routes(definition: PipelineDefinition, kinds: Mapping[str, AnySource]) -> list[tuple[str, str, str, str]]:
    """List every method and template the document's received sources answer, as step, method, template, normalised."""
    routes: list[tuple[str, str, str, str]] = []
    for name in definition.sources:
        node = definition.steps[name].source
        kind = kinds.get(node.kind) if node is not None else None
        if node is None or not isinstance(kind, ReceivedSource):
            continue
        try:
            route = kind.route(source_config(kind, node.config))
        except ValidationError:
            continue
        routes.extend((name, method, route.template, route.normalised) for method in route.methods)
    return routes


def _route_issues_within(definition: PipelineDefinition, kinds: Mapping[str, AnySource]) -> list[ValidationIssue]:
    """Refuse two sources of one document answering the same method at the same template."""
    seen: dict[tuple[str, str], str] = {}
    issues: list[ValidationIssue] = []
    for step, method, template, normalised in declared_routes(definition, kinds):
        other = seen.get((method, normalised))
        if other is not None and other != step:
            issues.append(
                ValidationIssue.of(
                    ROUTE_CLAIMED,
                    location=f"steps.{step}.source.path",
                    method=method,
                    template=template,
                    step=repr(other),
                    pipeline=repr(definition.code),
                )
            )
            continue
        seen[(method, normalised)] = step
    return issues


def _located(prefix: str, error: ValidationError) -> list[ValidationIssue]:
    """Render a kind config's validation errors at the place in the document they belong to."""
    issues: list[ValidationIssue] = []
    for detail in error.errors():
        issue = validation_issue(cast("dict[str, Any]", detail))
        where = f"{prefix}.{issue.location}" if issue.location else prefix
        issues.append(ValidationIssue(location=where, message=issue.message, code=issue.code, params=issue.params))
    return issues


def _first_line(error: Exception) -> str:
    """Reduce a refusal to the part a person reads: its first problem, or its first line."""
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return f"{where}: {first['msg']}" if where else str(first["msg"])
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__
