"""What a document's report and its templates are checked for before anything runs.

A template renders an unknown name as nothing, by design, so a typo in one is silent at the
run. These checks read the names a template reaches for and compare them with what the
template will be given, and say so as a warning: a refusal would turn a lenient renderer into
a strict one by the back door.
"""

from collections.abc import Iterator, Mapping
from typing import Any, Final, cast

import jinja2.meta
from jinja2 import nodes

from dirigent_client.schemas import Catalog, ValidationIssue
from dirigent_common import JsonMap, Message
from dirigent_common.templating import ENVIRONMENT
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.messages import (
    REPORT_NO_SUCH_STEP,
    REPORT_RENDER_UNSEEN,
    REPORT_STEP_NO_TEXT,
    REPORT_STEP_NOT_A_BLOCK,
    TEMPLATE_NAME_UNKNOWN,
)

#: The block whose text a document most often means as its report.
RENDER_BLOCK: Final = "report.render"

#: The fields of the ``run`` namespace a run's facts carry.
RUN_FIELDS: Final = frozenset(
    {
        "id",
        "status",
        "pipeline",
        "error",
        "error_code",
        "error_params",
        "failed_step",
        "params",
        "trigger",
        "started_at",
        "finished_at",
        "duration_ms",
        "url",
        "report_url",
        "window_start",
        "window_end",
        "trace_id",
    }
)

#: The fields of one step's facts.
STEP_FIELDS: Final = frozenset(
    {
        "step",
        "block",
        "outcome",
        "attempts",
        "depends_on",
        "warnings",
        "duration_ms",
        "error",
        "error_code",
        "error_params",
        "output",
        "output_uri",
        "output_bytes",
    }
)

#: What a mapping answers to in a template beside its keys: ``step.items()`` is a loop.
MAPPING_METHODS: Final = frozenset({"items", "keys", "values", "get"})

#: Every name a report template is given, and the fields of the ones that are objects.
REPORT_CONTEXT: Final[Mapping[str, frozenset[str] | None]] = {
    "run": RUN_FIELDS,
    "pipeline": frozenset({"code", "name", "version"}),
    "params": None,
    "steps": None,
    "step": None,
    "items": None,
    "items_total": None,
    "items_failed": None,
    "url": None,
    "rendered_at": None,
}


def report_issues(definition: PipelineDefinition, catalog: Catalog | None) -> list[ValidationIssue]:
    """Refuse a ``report.from`` naming no step, a source or a reply, or a block that hands on no text."""
    report = definition.report
    if report is None or report.step is None:
        return []
    name = report.step
    step = definition.steps.get(name)
    if step is None:
        return [ValidationIssue.of(REPORT_NO_SUCH_STEP, location="report.from", step=repr(name))]
    if step.block is None:
        form = "source" if step.source is not None else "reply"
        return [ValidationIssue.of(REPORT_STEP_NOT_A_BLOCK, location="report.from", step=repr(name), form=form)]
    entry = catalog.block(step.block) if catalog is not None else None
    if entry is None or _hands_on_text(entry.output_schema):
        return []
    return [ValidationIssue.of(REPORT_STEP_NO_TEXT, location="report.from", step=repr(name), block=step.block)]


def _hands_on_text(schema: JsonMap) -> bool:
    """Say whether an output schema declares a ``text`` that can be a string."""
    if not schema:
        return True
    field = cast("Mapping[str, Any]", schema.get("properties", {})).get("text")
    if not isinstance(field, dict):
        return False
    described = cast("Mapping[str, Any]", field)
    branches = [described, *cast("list[Mapping[str, Any]]", described.get("anyOf", []))]
    return any(branch.get("type") == "string" for branch in branches)


def report_warnings(definition: PipelineDefinition) -> list[ValidationIssue]:
    """Say what is worth knowing about a document's report that refuses nothing."""
    warnings: list[ValidationIssue] = []
    if definition.report is None:
        warnings.extend(
            ValidationIssue.of(REPORT_RENDER_UNSEEN, location=f"steps.{name}", step=repr(name), bare=name)
            for name, step in definition.steps.items()
            if step.block == RENDER_BLOCK
        )
    elif definition.report.template is not None:
        warnings.extend(unknown_names(definition.report.template, "report.template", _report_context(definition)))
    for name, step in definition.steps.items():
        template = step.config.get("template") if step.block == RENDER_BLOCK else None
        values = step.config.get("values", {})
        if isinstance(template, str) and isinstance(values, dict):
            given: dict[str, frozenset[str] | None] = {key: None for key in cast("dict[str, Any]", values)}
            warnings.extend(unknown_names(template, f"steps.{name}.config.template", given))
    return warnings


def _report_context(definition: PipelineDefinition) -> dict[str, frozenset[str] | None]:
    """The names a run's report template is given, with the steps and params this document declares."""
    return {
        **REPORT_CONTEXT,
        "step": frozenset(definition.steps),
        "params": _declared_params(definition.params),
    }


def _declared_params(schema: JsonMap) -> frozenset[str] | None:
    """The parameters a run of the document can have, or None when the schema names none it leaves open."""
    if not schema:
        return frozenset()
    properties = schema.get("properties")
    return frozenset(cast("dict[str, Any]", properties)) if isinstance(properties, dict) else None


def unknown_names(
    source: str,
    location: str,
    given: Mapping[str, frozenset[str] | None],
    message: Message = TEMPLATE_NAME_UNKNOWN,
) -> list[ValidationIssue]:
    """Warn on each name and first field a template reads that its context does not have."""
    try:
        tree = ENVIRONMENT.parse(source)
    except jinja2.TemplateSyntaxError:
        return []
    free = jinja2.meta.find_undeclared_variables(tree)
    unknown: dict[str, str] = {}
    names = f"; it is given {', '.join(sorted(given))}" if given else ""
    for name in sorted(free):
        if name not in given:
            unknown.setdefault(name, names)
    for root, field in _reads(tree):
        if root not in free or root not in given:
            continue
        fields = given[root]
        if fields is None or field in fields or field in MAPPING_METHODS:
            continue
        hint = f"; {root} has {', '.join(sorted(fields))}" if fields else f"; {root} has nothing"
        unknown.setdefault(f"{root}.{field}", hint)
    return [ValidationIssue.of(message, location=location, name=name, hint=hint) for name, hint in unknown.items()]


def _reads(tree: nodes.Template) -> Iterator[tuple[str, str]]:
    """Every ``name.field`` and ``name['field']`` a template reads, by its root name and first field."""
    for read in tree.find_all(nodes.Getattr):
        target = read.node
        if isinstance(target, nodes.Name) and target.ctx == "load":
            yield target.name, read.attr
    for item in tree.find_all(nodes.Getitem):
        target, key = item.node, item.arg
        if (
            isinstance(target, nodes.Name)
            and target.ctx == "load"
            and isinstance(key, nodes.Const)
            and isinstance(key.value, str)
        ):
            yield target.name, key.value
