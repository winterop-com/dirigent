"""``${...}`` reference resolution: the whole reference language, and nothing more.

There are no expressions, loops, or conditionals, and four namespaces: ``params.*``,
``steps.<name>.output.*``, ``item``, and ``run.scratch`` / ``run.id`` /
``run.window.start`` / ``run.window.end``.

A reference that stands alone resolves to the typed value, so ``"${params.count}"`` is an
integer downstream; one inside a larger string interpolates. An unknown reference raises
rather than resolving to empty, and the engine fails the attempt as ``rejected``.

``$${...}`` is the escape: it yields the literal ``${...}`` and is never resolved, which is
how a compose file, a shell command or a template reaches a tool with its own braces intact.
"""

import re
import shlex
from collections.abc import Callable, Container
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from dirigent_common import JsonMap

REFERENCE_PATTERN: Final = re.compile(r"(\$+)\{([^{}]+)\}")
"""A run of dollars before a braced name.

The dollars collapse in pairs: each ``$$`` is one literal dollar, and a single dollar left
over makes what follows a reference. So ``${x}`` resolves, ``$${x}`` is the literal ``${x}``,
and ``$$${x}`` is a dollar followed by the resolved ``${x}``. A ``$$`` that no brace follows
is not matched at all and passes through untouched.
"""

#: A reference that is the entire value, which resolves to the typed value rather than text.
WHOLE_REFERENCE: Final = re.compile(r"^\$\{([^{}]+)\}$")


class UnknownReference(Exception):
    """A document named something the run does not have."""

    def __init__(self, reference: str, detail: str) -> None:
        """Name the reference and what was actually available."""
        super().__init__(f"${{{reference}}} cannot be resolved: {detail}")
        self.reference = reference


class ReferenceScope(BaseModel):
    """Everything a reference may read, gathered once per attempt at claim time."""

    model_config = ConfigDict(frozen=True)

    params: JsonMap = Field(default_factory=dict)

    outputs: dict[str, JsonValue] = Field(default_factory=dict)
    """Stored outputs of upstream steps, keyed by step name."""

    item: JsonValue = None
    """The element this run item maps, when the step fans out."""

    has_item: bool = False
    """Whether ``item`` is meaningful, so a null item is distinguishable from no item."""

    scratch: str = ""
    run_id: UUID | None = None

    window_start: datetime | None = None
    """The start of the run's logical data interval, when it carries one."""

    window_end: datetime | None = None
    """The end of the run's logical data interval, exclusive, when it carries one."""


def resolve(value: JsonValue, scope: ReferenceScope, *, quote: bool = False) -> JsonValue:
    """Resolve every reference in a config value, recursively, preserving structure."""
    match value:
        case str():
            return _resolve_string(value, scope, quote=quote)
        case list():
            return [resolve(element, scope, quote=quote) for element in value]
        case dict():
            return {key: resolve(element, scope, quote=quote) for key, element in value.items()}
        case _:
            return value


def resolve_config(config: JsonMap, scope: ReferenceScope, *, shell_fields: Container[str] = frozenset()) -> JsonMap:
    """Resolve a step's whole config map, which is what the engine hands a block.

    ``shell_fields`` names the config keys the block marked with
    :class:`~dirigent_plugin.ShellString`, whose value is handed to ``sh -c``. In those, every
    substituted value is shell-quoted, so a parameter that arrived in a webhook payload
    becomes exactly one word; the metacharacters the pipeline author typed keep their meaning.
    """
    return {key: resolve(value, scope, quote=key in shell_fields) for key, value in config.items()}


def has_reference(value: str) -> bool:
    """Whether a string names at least one reference, ignoring every escaped ``$${...}``."""
    return any(len(match.group(1)) % 2 for match in REFERENCE_PATTERN.finditer(value))


def substitute(value: str, render: Callable[[str], str]) -> str:
    """Replace every reference in a string with ``render`` of its text, honouring the escape.

    ``render`` is handed the reference exactly as written, braces stripped and nothing else.
    """

    def one(match: re.Match[str]) -> str:
        dollars, reference = match.group(1), match.group(2)
        literal = "$" * (len(dollars) // 2)
        if len(dollars) % 2 == 0:
            return f"{literal}{{{reference}}}"
        return literal + render(reference)

    return REFERENCE_PATTERN.sub(one, value)


def references_in(value: JsonValue) -> list[str]:
    """List every reference a value names, skipping the escaped ones."""
    match value:
        case str():
            return [match.group(2) for match in REFERENCE_PATTERN.finditer(value) if len(match.group(1)) % 2]
        case list():
            return [reference for element in value for reference in references_in(element)]
        case dict():
            return [reference for element in value.values() for reference in references_in(element)]
        case _:
            return []


def _resolve_string(value: str, scope: ReferenceScope, *, quote: bool = False) -> JsonValue:
    """Resolve a string, typed when it is one whole reference and textual when embedded.

    Under ``quote`` the whole-reference shortcut is dropped too: handing a command that is
    entirely one reference to a shell unquoted would let a parameter be an arbitrary program.
    """
    whole = WHOLE_REFERENCE.match(value)
    if whole is not None and not quote:
        return lookup(whole.group(1).strip(), scope)
    render = _as_shell_word if quote else _as_text
    return substitute(value, lambda reference: render(lookup(reference.strip(), scope)))


def _as_shell_word(value: JsonValue) -> str:
    """Render a resolved value as exactly one word for a shell, whatever it contains."""
    return shlex.quote(_as_text(value))


def _as_text(value: JsonValue) -> str:
    """Render a resolved value for interpolation into a larger string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def lookup(reference: str, scope: ReferenceScope) -> JsonValue:
    """Resolve one reference path against the scope, or say precisely what is missing."""
    parts = [part for part in reference.split(".") if part]
    if not parts:
        raise UnknownReference(reference, "it names nothing")
    match parts[0]:
        case "params":
            return _walk(reference, scope.params, parts[1:], "params")
        case "item":
            if not scope.has_item:
                raise UnknownReference(reference, "this step does not fan out, so there is no item")
            return _walk(reference, scope.item, parts[1:], "item")
        case "steps":
            return _step_output(reference, parts, scope)
        case "run":
            return _run_value(reference, parts, scope)
        case unknown:
            raise UnknownReference(
                reference,
                f"{unknown!r} is not a namespace; the reference language has params, steps, item, and run",
            )


def _step_output(reference: str, parts: list[str], scope: ReferenceScope) -> JsonValue:
    """Resolve ``steps.<name>.output.<path>`` against the stored upstream outputs."""
    if len(parts) < 3 or parts[2] != "output":
        raise UnknownReference(reference, "a step reference reads steps.<name>.output.<field>")
    name = parts[1]
    if name not in scope.outputs:
        available = ", ".join(sorted(scope.outputs)) or "no step has produced output yet"
        raise UnknownReference(reference, f"step {name!r} has no stored output ({available})")
    return _walk(reference, scope.outputs[name], parts[3:], f"steps.{name}.output")


def _run_value(reference: str, parts: list[str], scope: ReferenceScope) -> JsonValue:
    """Resolve the run-level values a document may read."""
    match parts[1:]:
        case ["scratch"]:
            return scope.scratch
        case ["id"]:
            return str(scope.run_id) if scope.run_id is not None else None
        case ["window", "start"]:
            return _window_edge(reference, scope.window_start)
        case ["window", "end"]:
            return _window_edge(reference, scope.window_end)
        case _:
            raise UnknownReference(
                reference,
                "run exposes only run.scratch, run.id, run.window.start and run.window.end",
            )


def _window_edge(reference: str, edge: datetime | None) -> JsonValue:
    """Render one edge of the run's window, or refuse because this run has no window.

    Resolving to empty would silently widen whatever the step was going to fetch, so a run
    with no window refuses the reference the way an unknown one is refused.
    """
    if edge is None:
        raise UnknownReference(
            reference,
            "this run carries no window; a schedule-fired or backfilled run has one, "
            "and an ad hoc run only if it was started with one",
        )
    return edge.isoformat()


def _walk(reference: str, value: JsonValue, path: list[str], namespace: str) -> JsonValue:
    """Walk a dotted path into a resolved value, naming the level that was missing."""
    current = value
    walked = namespace
    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            available = ", ".join(sorted(current)) if isinstance(current, dict) else "it is not an object"
            raise UnknownReference(reference, f"{walked} has no {part!r} ({available})")
        walked = f"{walked}.{part}"
    return current
