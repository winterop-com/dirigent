"""What a document will cost before it runs: how wide, how many tries, how long it may wait.

Everything here is read off the document, and off the catalog where a server hands one over.
Nothing executes, so the numbers are the ones the engine fixes when it creates a run: a
fan-out's cardinality, the attempts a retry policy allows, and the waits a step may spend
under a deadline. What only the run can decide -- a parameter supplied at the command line,
a window's bounds -- is reported as unknown rather than guessed at, and a total that counted
one of those says so.

The cardinality rules are :func:`dirigent_core.engine.runs.resolve_fan_out`'s: a literal list
is its own length, ``${steps.<name>.items}`` adopts another fan-out's grid, a reference that
resolves to a list is that list, and anything else is only the run's to answer.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from dirigent_cli.schemas import ShapeWarning, StepShape
from dirigent_client.schemas import BlockEntry, BlockKind, Catalog
from dirigent_common import Duration, JsonMap, base_format_checker, format_duration
from dirigent_core.engine.definition import ParameterError, PipelineDefinition, RetryPolicy, StepDefinition
from dirigent_core.engine.failure import backoff_delay
from dirigent_core.engine.references import ReferenceScope, UnknownReference, resolve

#: What a cardinality says when the document alone cannot fix it.
UNKNOWN: Final = "unknown"

#: How a cardinality names the fan-out whose grid a step maps over instead of its own.
ADOPTS: Final = "adopts {step}"


class DocumentShape(BaseModel):
    """What a whole document will cost: the steps, the totals over them, and the warnings."""

    model_config = ConfigDict(frozen=True)

    attempts_max: int = 0
    """Every attempt the document allows: each step's tries times the items it maps over."""

    attempts_at_least: bool = False
    """Whether that total is a floor, a cardinality only the run can fix having counted once."""

    deadline_longest: Duration | None = None
    """The longest chain of deadlines through the DAG, which is the wait the document allows."""

    steps: list[StepShape] = Field(default_factory=list[StepShape])
    warnings: list[ShapeWarning] = Field(default_factory=list[ShapeWarning])


def explain(definition: PipelineDefinition, catalog: Catalog | None = None) -> DocumentShape:
    """Read a document as the work it will become, in the order the steps will run.

    ``catalog`` is a server's, where one was asked for: a sensor that declares no cadence and
    no deadline of its own takes the block's, and the row says which of the two came from
    there. With no catalog the document's own values are all there is.
    """
    params = _param_defaults(definition)
    order = definition.topological_order()
    shapes: dict[str, StepShape] = {}
    for name in order:
        shapes[name] = _step_shape(name, definition.steps[name], params, shapes, catalog)
    rows = [shapes[name] for name in order]
    return DocumentShape(
        attempts_max=sum(row.max_attempts * (1 if row.elements is None else row.elements) for row in rows),
        attempts_at_least=any(row.elements is None for row in rows),
        deadline_longest=_deadline_longest(definition, shapes, order),
        steps=rows,
        warnings=_warnings(rows, catalog),
    )


def _param_defaults(definition: PipelineDefinition) -> JsonMap:
    """Fill the parameters a run would be given with the defaults the document declares.

    A parameter with no default is one only the run supplies, and every cardinality that
    reads one is unknown here rather than wrong.
    """
    try:
        return definition.validate_params({}, base_format_checker())
    except ParameterError:
        return {}


def _step_shape(
    name: str,
    step: StepDefinition,
    params: JsonMap,
    done: Mapping[str, StepShape],
    catalog: Catalog | None,
) -> StepShape:
    """Read one step as the work it will become, against the steps already read."""
    cardinality, elements = _cardinality(step, params, done)
    poll, deadline, from_block = _waits(step, _entry(step, catalog))
    return StepShape(
        name=name,
        block=step.block,
        depends_on=list(step.depends_on),
        cardinality=cardinality,
        elements=elements,
        reference=step.for_each if isinstance(step.for_each, str) else None,
        items=step.items.value,
        max_attempts=step.retry.max_attempts,
        retry_wait=_retry_wait(step.retry),
        timeout=step.timeout,
        poll=poll,
        deadline=deadline,
        on_timeout=step.on_timeout.value,
        from_block=from_block,
    )


def _cardinality(step: StepDefinition, params: JsonMap, done: Mapping[str, StepShape]) -> tuple[int | str, int | None]:
    """Say how many run items a step becomes, and the count behind that where there is one."""
    expression = step.for_each
    if expression is None:
        return 1, 1
    if isinstance(expression, list):
        return len(expression), len(expression)
    adopted = step.adopted_grid
    if adopted is not None:
        upstream = done[adopted].elements if adopted in done else None
        return ADOPTS.format(step=adopted), upstream
    if "steps." in expression:
        # resolve_fan_out refuses a step's output here, because cardinality is fixed when the
        # run is created and no step has run by then.
        return UNKNOWN, None
    try:
        resolved = resolve(expression, ReferenceScope(params=params))
    except UnknownReference:
        return UNKNOWN, None
    if not isinstance(resolved, list):
        return UNKNOWN, None
    return len(resolved), len(resolved)


def _entry(step: StepDefinition, catalog: Catalog | None) -> BlockEntry | None:
    """Find what the catalog says about this step's block, where there is a catalog."""
    return None if catalog is None else catalog.block(step.block)


def _waits(step: StepDefinition, entry: BlockEntry | None) -> tuple[timedelta | None, timedelta | None, list[str]]:
    """Take the cadence and the deadline from the document, then from the block's own defaults."""
    poll, deadline = step.poll, step.deadline
    from_block: list[str] = []
    if entry is None:
        return poll, deadline, from_block
    if poll is None and entry.default_poll_seconds is not None:
        poll = timedelta(seconds=entry.default_poll_seconds)
        from_block.append("poll")
    if deadline is None and entry.default_deadline_seconds is not None:
        deadline = timedelta(seconds=entry.default_deadline_seconds)
        from_block.append("deadline")
    return poll, deadline, from_block


def _retry_wait(policy: RetryPolicy) -> timedelta | None:
    """Add up every backoff the policy allows, at the top of the jitter it spreads them over.

    ``max_attempts`` tries have one delay fewer between them, and each delay is the engine's
    own: exponential, clamped at ``max_backoff``, and then spread by the jitter.
    """
    if policy.max_attempts <= 1:
        return None
    steady = policy.model_copy(update={"jitter": 0.0})
    total = sum((backoff_delay(steady, attempt) for attempt in range(1, policy.max_attempts)), timedelta(0))
    return total * (1 + policy.jitter)


def _deadline_longest(
    definition: PipelineDefinition, shapes: Mapping[str, StepShape], order: Sequence[str]
) -> timedelta | None:
    """Add the deadlines along each path through the DAG and take the longest of them.

    A step cannot start before its dependencies settled, so the chain is what the document
    allows end to end; a step with no deadline lengthens no chain.
    """
    chains: dict[str, timedelta] = {}
    for name in order:
        upstream = max((chains[one] for one in definition.steps[name].depends_on), default=timedelta(0))
        chains[name] = upstream + (shapes[name].deadline or timedelta(0))
    longest = max(chains.values(), default=timedelta(0))
    return longest or None


def _warnings(rows: Sequence[StepShape], catalog: Catalog | None) -> list[ShapeWarning]:
    """Name what the document leaves unbounded or unresolved, one sentence each."""
    found: list[ShapeWarning] = []
    for row in rows:
        # The step that named the reference is warned about; one that adopts its grid has the
        # same unknown width and no second cause.
        if row.cardinality == UNKNOWN:
            found.append(
                ShapeWarning(
                    step=row.name,
                    cause="unknown-cardinality",
                    message=(
                        f"{row.name} fans out over {row.reference}, which only the run can resolve, "
                        f"so it is counted as one item here."
                    ),
                )
            )
        if row.retry_wait is not None and row.deadline is not None and row.retry_wait > row.deadline:
            found.append(
                ShapeWarning(
                    step=row.name,
                    cause="retry-outlasts-deadline",
                    message=(
                        f"{row.name} may spend {format_duration(row.retry_wait)} in backoff between its "
                        f"{row.max_attempts} attempts, which is longer than the {format_duration(row.deadline)} "
                        f"deadline each one waits under."
                    ),
                )
            )
        if row.deadline is None and _is_sensor(row, catalog):
            found.append(ShapeWarning(step=row.name, cause="unbounded-sensor", message=_unbounded(row, catalog)))
    return found


def _unbounded(row: StepShape, catalog: Catalog | None) -> str:
    """Say that nothing bounds a sensor's wait, and where a catalog would still fill one in."""
    if catalog is None:
        return f"{row.name} polls with no deadline, so nothing here bounds its wait: --server reads the block's."
    return f"{row.name} waits on a sensor that neither the document nor {row.block} gives a deadline."


def _is_sensor(row: StepShape, catalog: Catalog | None) -> bool:
    """Report whether a step waits on a sensor, by the catalog where there is one.

    Offline there is nothing to ask, and a cadence is the one thing only a sensor carries.
    """
    if catalog is None:
        return row.poll is not None
    entry = catalog.block(row.block)
    return entry is not None and entry.kind is BlockKind.SENSOR
