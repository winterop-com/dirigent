"""``${...}`` reference resolution: the whole reference language, and nothing more.

There are no expressions, loops, or conditionals, and four namespaces: ``params.*``,
``steps.*``, ``item``, and ``run.scratch`` / ``run.id`` / ``run.window.start`` /
``run.window.end``.

``steps`` has three forms: ``steps.<name>.output.*`` is a step's stored output,
``steps.<name>.items`` is the list a fan-out maps over and only ``for_each`` reads it, and
``steps.<name>.item.output.*`` is the matching item's output in a step this one shares a
grid with.

A reference that stands alone resolves to the typed value, so ``"${params.count}"`` is an
integer downstream; one inside a larger string interpolates. An unknown reference raises
rather than resolving to empty, and the engine fails the attempt as ``rejected``.

``$${...}`` is the escape: it yields the literal ``${...}`` and is never resolved, which is
how a compose file, a shell command or a template reaches a tool with its own braces intact.
"""

import re
from collections.abc import Callable, Collection
from datetime import datetime
from typing import Final, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from dirigent_common import JsonMap
from dirigent_plugin import SHELL_VARIABLE_PREFIX, SHELL_VARIABLES_FIELD

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

    item_index: int | None = None
    """This run item's position in the grid, which is what pairs it with another fan-out's."""

    grids: dict[str, list[JsonValue]] = Field(default_factory=dict)
    """The lists fan-out steps map over, keyed by step name, as ``for_each`` expands them."""

    item_outputs: dict[str, JsonValue] = Field(default_factory=dict)
    """Outputs of the matching item in each step this one shares a grid with, by step name."""

    paired: frozenset[str] = frozenset()
    """The steps whose grid this one shares, and whose matching item it may therefore read."""

    scratch: str = ""
    run_id: UUID | None = None

    window_start: datetime | None = None
    """The start of the run's logical data interval, when it carries one."""

    window_end: datetime | None = None
    """The end of the run's logical data interval, exclusive, when it carries one."""


def resolve(value: JsonValue, scope: ReferenceScope) -> JsonValue:
    """Resolve every reference in a config value, recursively, preserving structure."""
    match value:
        case str():
            return _resolve_string(value, scope)
        case list():
            return [resolve(element, scope) for element in value]
        case dict():
            return {key: resolve(element, scope) for key, element in value.items()}
        case _:
            return value


def resolve_config(config: JsonMap, scope: ReferenceScope, *, shell_fields: Collection[str] = ()) -> JsonMap:
    """Resolve a step's whole config map, which is what the engine hands a block.

    ``shell_fields`` names the config keys the block marked with
    :class:`~dirigent_plugin.ShellString`, whose value is handed to ``sh -c``. There a
    substituted value never reaches the shell's parser: each reference is rewritten to a
    variable of the engine's own, and the values are collected in ``shell_variables`` for the
    block to set in the command's environment. The metacharacters the pipeline author typed
    keep their meaning, and a parameter that arrived in a webhook payload is never shell
    source, however the author quoted the reference.
    """
    variables: dict[str, str] = {}
    resolved = {
        key: (_resolve_shell(value, scope, variables) if key in shell_fields else resolve(value, scope))
        for key, value in config.items()
    }
    if shell_fields:
        resolved[SHELL_VARIABLES_FIELD] = cast("JsonValue", variables)
    return resolved


def has_reference(value: str) -> bool:
    """Whether a string names at least one reference, ignoring every escaped ``$${...}``."""
    return any(len(match.group(1)) % 2 for match in REFERENCE_PATTERN.finditer(value))


def substitute(value: str, render: Callable[[str], str]) -> str:
    """Replace every reference in a string with ``render`` of its text, honouring the escape.

    ``render`` is handed the reference exactly as written, braces stripped and nothing else.
    """

    def one(match: re.Match[str]) -> str:
        literal, resolves = _collapse(match.group(1), match.group(2))
        return literal + render(match.group(2)) if resolves else literal

    return REFERENCE_PATTERN.sub(one, value)


def _collapse(dollars: str, reference: str) -> tuple[str, bool]:
    """The literal text a run of dollars leaves, and whether the reference after it resolves.

    The dollars collapse in pairs, so an even run leaves the braces as text and an odd one
    makes what follows a reference.
    """
    literal = "$" * (len(dollars) // 2)
    if len(dollars) % 2 == 0:
        return f"{literal}{{{reference}}}", False
    return literal, True


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


def _resolve_string(value: str, scope: ReferenceScope) -> JsonValue:
    """Resolve a string, typed when it is one whole reference and textual when embedded."""
    whole = WHOLE_REFERENCE.match(value)
    if whole is not None:
        return lookup(whole.group(1).strip(), scope)
    return substitute(value, lambda reference: _as_text(lookup(reference.strip(), scope)))


def _resolve_shell(value: JsonValue, scope: ReferenceScope, variables: dict[str, str]) -> JsonValue:
    """Rewrite a shell string so that nothing it substitutes is ever parsed by the shell.

    Each reference becomes a reference to a variable the engine invents, and its value is
    recorded in ``variables`` under that name for the block to set in the command's
    environment. A variable's value is text a shell expands and never re-reads, so what a
    webhook payload carries cannot become shell source however the author wrote the
    reference; what the quoting below decides is only whether that text stays one word.

    A shell string is always text, so the whole-reference shortcut does not apply: a command
    that is entirely one reference is one word, and therefore the name of a program to run
    and never a program.
    """
    if not isinstance(value, str):
        return value
    rewritten: list[str] = []
    context: tuple[str, ...] = ()
    read = 0
    for match in REFERENCE_PATTERN.finditer(value):
        before = value[read : match.start()]
        context = _shell_context(before, context)
        literal, resolves = _collapse(match.group(1), match.group(2))
        rewritten.append(before + literal)
        if resolves:
            name = f"{SHELL_VARIABLE_PREFIX}{len(variables)}"
            variables[name] = _as_text(lookup(match.group(2).strip(), scope))
            rewritten.append(_shell_word(name, context))
        read = match.end()
    rewritten.append(value[read:])
    return "".join(rewritten)


def _shell_word(name: str, context: tuple[str, ...]) -> str:
    """A reference to the variable that is one word where the author put it.

    Inside the author's quotes it takes none of its own: a second pair would end theirs and
    leave the value to be split into words. Anywhere else it takes a pair, or the shell would
    split the value and expand any glob in it -- bare, and inside a ``$( )`` or a backquoted
    command, which quote nothing they hold. Inside single quotes, which a shell keeps
    literal, this text is what the author gets rather than the value.
    """
    return f"${name}" if context and context[-1] in "'\"" else f'"${name}"'


def _shell_context(text: str, context: tuple[str, ...]) -> tuple[str, ...]:
    """Where in a shell's quoting this text leaves it, given where it began.

    The stack holds what the shell has opened and not yet closed: a quote, a ``$( )``
    substitution, or a backquoted one, each of which quotes what is inside it in its own
    right. Only the innermost decides how a reference there is written, and getting that
    wrong can only cost a value its word boundaries -- never make it shell source.
    """
    stack = list(context)
    escaped = skipped = False
    for index, character in enumerate(text):
        inner = stack[-1] if stack else ""
        if skipped or escaped:
            skipped = escaped = False
        elif inner == "'":
            if character == "'":
                stack.pop()
        elif character == "\\":
            escaped = True
        elif inner in '"`' and character == inner:
            stack.pop()
        elif character == "$" and text[index + 1 : index + 2] == "(":
            stack.append("(")
            skipped = True
        elif character == "`" or (character in "'\"" and inner != '"'):
            stack.append(character)
        elif character == ")" and inner == "(":
            stack.pop()
    return tuple(stack)


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
    """Resolve the ``steps`` namespace: a step's output, its grid, or its matching item."""
    match parts[1:]:
        case [name, "output", *path]:
            if name not in scope.outputs:
                available = ", ".join(sorted(scope.outputs)) or "no step has produced output yet"
                raise UnknownReference(reference, f"step {name!r} has no stored output ({available})")
            return _walk(reference, scope.outputs[name], path, f"steps.{name}.output")
        case [name, "items"]:
            if name not in scope.grids:
                raise UnknownReference(
                    reference,
                    f"step {name!r} has no grid here; steps.{name}.items is the list a fan-out maps over, "
                    "and only for_each reads it",
                )
            return cast("JsonValue", scope.grids[name])
        case [name, "item", "output", *path]:
            if name not in scope.paired:
                raise UnknownReference(
                    reference,
                    f"this step does not fan over step {name!r}'s items; "
                    f"write for_each: ${{steps.{name}.items}} to map over them",
                )
            if name not in scope.item_outputs:
                raise UnknownReference(reference, f"step {name!r}'s item {scope.item_index} did not succeed")
            return _walk(reference, scope.item_outputs[name], path, f"steps.{name}.item.output")
        case _:
            raise UnknownReference(
                reference,
                "a step reference reads steps.<name>.output.<field>, steps.<name>.items, "
                "or steps.<name>.item.output.<field>",
            )


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
