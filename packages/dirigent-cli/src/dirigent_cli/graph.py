"""A pipeline's shape as an indented tree: what runs first, and what waits for what."""

from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple, cast

#: The rule a step has unless it says otherwise, and so the one not worth printing.
DEFAULT_RULE = "all_success"

INDENT = "  "


class GraphStep(NamedTuple):
    """One step as the tree draws it."""

    name: str
    block: str
    depends_on: tuple[str, ...] = ()
    rule: str = DEFAULT_RULE


def steps_of_document(document: Mapping[str, Any]) -> list[GraphStep]:
    """Read the steps out of a ``dirigent/v1`` document, in the order it wrote them."""
    steps = document.get("steps")
    if not isinstance(steps, dict):
        return []
    read: list[GraphStep] = []
    for name, body in cast("dict[str, Any]", steps).items():
        held = cast("dict[str, Any]", body) if isinstance(body, dict) else {}
        depends = held.get("depends_on")
        read.append(
            GraphStep(
                name=str(name),
                block=str(held.get("block", "-")),
                depends_on=tuple(str(item) for item in cast("list[Any]", depends or ())),
                rule=str(held.get("rule", DEFAULT_RULE)),
            )
        )
    return read


def render_graph(steps: Sequence[GraphStep]) -> list[str]:
    """Draw the graph as indented lines, each step under the last step it waits for.

    A step with several dependencies is drawn once, under the last of them, and names the
    others rather than appearing twice: one step is one line, whatever its in-degree.
    """
    ordered = _in_order(steps)
    position = {step.name: index for index, step in enumerate(ordered)}
    known = set(position)
    parents = {step.name: _parent(step, position) for step in ordered}
    children: dict[str | None, list[GraphStep]] = {}
    for step in ordered:
        children.setdefault(parents[step.name], []).append(step)

    lines: list[str] = []
    drawn: set[str] = set()

    def draw(step: GraphStep, depth: int) -> None:
        """Write one step's line, then the steps that wait on it."""
        if step.name in drawn:
            return
        drawn.add(step.name)
        lines.append(INDENT * depth + _line(step, parents[step.name], known))
        for child in children.get(step.name, []):
            draw(child, depth + 1)

    for root in children.get(None, []):
        draw(root, 0)
    # A cycle has no root to reach it from, and a step left undrawn is worse than one drawn
    # at the margin.
    for step in ordered:
        draw(step, 0)
    return lines


def _line(step: GraphStep, parent: str | None, known: set[str]) -> str:
    """Render one step: its name, its block, and whatever the tree cannot show."""
    rendered = f"{step.name}  ({step.block})"
    others = [name for name in step.depends_on if name != parent and name in known]
    if others:
        rendered += f"  also after {', '.join(others)}"
    if step.rule != DEFAULT_RULE:
        rendered += f"  when {step.rule}"
    return rendered


def _parent(step: GraphStep, position: Mapping[str, int]) -> str | None:
    """The dependency a step is drawn under: the last one to run, or nothing for a root."""
    known = [name for name in step.depends_on if name in position]
    return max(known, key=lambda name: position[name]) if known else None


def _in_order(steps: Sequence[GraphStep]) -> list[GraphStep]:
    """Sort the steps so nothing precedes what it waits for, keeping the written order otherwise."""
    known = {step.name for step in steps}
    waiting = list(steps)
    placed: list[GraphStep] = []
    settled: set[str] = set()
    while waiting:
        ready = [step for step in waiting if all(name in settled or name not in known for name in step.depends_on)]
        if not ready:
            # A cycle, which validation refuses: draw the rest as written rather than hiding it.
            placed.extend(waiting)
            break
        placed.extend(ready)
        settled.update(step.name for step in ready)
        names = {step.name for step in ready}
        waiting = [step for step in waiting if step.name not in names]
    return placed
