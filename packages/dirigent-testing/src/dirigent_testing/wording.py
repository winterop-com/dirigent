"""Checking that no refusal a package makes reaches a person under no code at all.

WHY THIS EXISTS. ``dirigent_common.Catalogue`` is the one place a refusal's wording lives,
under a code that identifies it wherever it appears. That is only true while it stays true:
one sentence written at a raise site is one phrase nobody reviewing the catalogue will ever
see, and one phrase a second language cannot reach. The frontend holds the same rule with
``scripts/check_ui_labels.py``, which lives in the engine's repository and so cannot be run
by a pack. This ships from ``dirigent-testing``, which every pack already installs, so a pack
holds its own wording to the rule its blocks are held to.

Nothing here is autouse. A distributed pytest plugin does not mutate a consumer's run unasked,
so this is one call from a test a pack writes:

.. code-block:: python

    def test_every_refusal_the_pack_makes_carries_a_code():
        assert check_pack_messages(Path(dirigent_acme.__file__).parent) == []

WHAT IT REFUSES.

* **A refusal raised under no code inside a pydantic validator.** ``raise ValueError("...")``
  in a ``@field_validator`` or ``@model_validator`` is not a private exception: pydantic wraps
  it, and the sentence reaches the wire as the ``msg`` param of a ``validation.*`` issue,
  rendered whole. It is a refusal a person reads, so it is minted and rendered:
  ``raise ValueError(NO_CREDENTIAL.render())``. Inside a validator there is no ambiguity to
  resolve -- the argument of a raise is always a message, never a wire value -- so this is
  judged by *where* the literal is written rather than by what it looks like.
* **A coded constructor handed a literal.** ``BlockFailure``, ``Failure.rejected``,
  ``Issue.of`` and the CLI's ``refuse`` all take a ``Message`` positionally, so a type checker
  already refuses a string there. This repeats the rule for a pack whose CI runs no type
  checker, and it is what makes the failure say *why* rather than say ``str``.
* **A catalogue entry nothing reads.** A message minted and never named is a phrase the
  product no longer says: a reviewer reads it and a translator translates it for nothing.
* **A code two catalogues both define.** A code is stable API, so a prefix has exactly one
  owner. This walks ``Catalogue.all``, which is every catalogue the process has imported --
  for a pack's suite, the engine's and its own -- so a pack learns at once that its prefix
  collides with something installed beside it.

WHAT IT DELIBERATELY DOES NOT JUDGE, each for a reason somebody could argue with.

* **A block's ``summary`` and its docstring.** ``OperatorSpec(summary=...)`` and a config
  field's docstring are English a person reads on the Blocks screen, and they are not in a
  catalogue anywhere -- by convention, not by oversight. ``docs/conventions.md`` puts
  documentation beside the value it documents, so that one sentence travels to the block
  catalog, the generated reference and the generated config form from one place. Whether a
  pack should instead *contribute* those as labels is an open question about a second
  extension point, not a fault in a raise site, and guessing at it here would make this check
  something people argue with rather than something they fix.
* **A connection's ``HealthReport.detail``.** A sentence a person reads on the Connections
  screen, and the same open question -- but its sites are a mix of prose, ``str(error)`` and
  a scrubbed process tail, and the ones that are not prose cannot be coded at all.
* **An exception a package raises for itself and catches before it answers.** The CLI's
  ``ParamError`` and ``SourceError``, a transform engine's ``TransformError``: by
  ``docs/conventions.md`` those are not refusals until something catches them and refuses
  under a code, and telling the one that escapes from the one that is caught needs a walk of
  the whole program. Review covers that.
* **Log lines.** ``ctx.log.info``, a heartbeat, a ``process`` record: events, not refusals.
  They carry no code and nothing here applies to them.
"""

import ast
import re
from pathlib import Path
from typing import Final

from dirigent_common import Catalogue

#: Directory names never descended into.
PRUNE: Final = frozenset({"__pycache__", ".venv", "node_modules", "site", "build", "dist"})

#: A decorator that makes a function pydantic's, so what it raises reaches the wire.
VALIDATORS: Final = frozenset({"field_validator", "model_validator", "validator", "root_validator"})

#: The constructors that take a ``Message`` and render it, named so a literal given to one
#: fails saying which rule it broke rather than saying ``str``.
CODED: Final = frozenset({"BlockFailure", "Failure.rejected", "Issue.of", "refuse"})

#: A word of prose: letters, and the apostrophes and hyphens that hold one together.
PROSE_WORD: Final = re.compile(r"^[A-Za-z][A-Za-z'’-]*$")


def _named(name: str) -> re.Pattern[str]:
    """Build the pattern that finds one name read as a name.

    Whole-word, so ``NO_PROGRAM`` is not found inside ``NO_PROGRAM_CODE``.

    Args:
        name: The constant to look for.

    Returns:
        The pattern that matches it and nothing longer.
    """
    return re.compile(rf"\b{re.escape(name)}\b")


UNCODED_FIX: Final = (
    "a refusal a person reads is minted in a Catalogue and rendered from it, so it carries a "
    "code a reader selects by and a translation can replace. See docs/plugins.md."
)

DEAD_FIX: Final = (
    "no source reads this message. A phrase the product no longer says is a phrase a reviewer "
    "reads and a translator translates for nothing: take it out of the catalogue."
)


def is_prose(text: str) -> bool:
    """Say whether a literal is a sentence somebody reads rather than a value.

    Args:
        text: The literal's text, with each interpolation already written as a hole.

    Returns:
        Whether it holds at least two words of prose.
    """
    stripped = text.strip()
    if " " not in stripped:
        return False
    words = (word.strip(".,;:!?()[]{}\"'") for word in stripped.split())
    return sum(1 for word in words if PROSE_WORD.match(word)) >= 2


def literal_of(node: ast.expr) -> str | None:
    """Read one string literal, eliding the holes an f-string interpolates.

    What matters about ``f"task {task} disappeared"`` is that the words beside the hole are
    words, so the value it interpolates is read as one hole rather than followed.

    Args:
        node: The expression to read.

    Returns:
        The literal's text, or ``None`` when the expression is not a string literal.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = (
            part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "{}"
            for part in node.values
        )
        return "".join(parts)
    return None


def source_files(source: Path) -> list[Path]:
    """Every checkable module under a package, in a stable order.

    Args:
        source: The package directory to walk.

    Returns:
        The ``.py`` files to read, the pruned directories and the test files excluded.
    """
    found = [
        path
        for path in source.rglob("*.py")
        if not (PRUNE & set(path.relative_to(source).parts)) and not path.name.startswith("test_")
    ]
    return sorted(found)


class Reading:
    """One module read for the refusals it makes and the messages it mints."""

    def __init__(self, path: Path, label: str) -> None:
        """Parse the module, holding what to prefix each finding with."""
        self.path = path
        self.label = label
        self.tree = ast.parse(path.read_text(encoding="utf-8"))

    def uncoded(self) -> list[str]:
        """List every refusal this module makes that carries no code."""
        found: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and self.validates(node):
                found.extend(self.raised_in(node))
            if isinstance(node, ast.Call) and ast.unparse(node.func) in CODED:
                text = literal_of(node.args[0]) if node.args else None
                if text is not None:
                    found.append(
                        f"{self.label}:{node.lineno}: {ast.unparse(node.func)} was given {text!r} -- {UNCODED_FIX}"
                    )
        return found

    def validates(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Say whether a function is one pydantic calls, so what it raises reaches the wire.

        Args:
            node: The function to judge.

        Returns:
            Whether any decorator on it is a pydantic validator.
        """
        return any(any(name in ast.unparse(decorator) for name in VALIDATORS) for decorator in node.decorator_list)

    def raised_in(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """List every prose literal this validator raises.

        Args:
            node: A function pydantic calls.

        Returns:
            One finding per raise whose argument is a sentence rather than a value.
        """
        found: list[str] = []
        for raised in ast.walk(node):
            if not isinstance(raised, ast.Raise) or not isinstance(raised.exc, ast.Call):
                continue
            for argument in raised.exc.args:
                text = literal_of(argument)
                if text is not None and is_prose(text):
                    where = f"{self.label}:{raised.lineno}"
                    found.append(f"{where}: validator {node.name} raises {text!r} -- {UNCODED_FIX}")
                    break
        return found

    def minted(self) -> dict[str, str]:
        """Name every message this module mints, as ``constant -> the name it was minted under``.

        A message minted into no constant cannot be named at a raise site, so it is not one
        this can tell is dead; ``dirigent_common``'s validation catalogue mints on first sight
        and has none.

        Returns:
            Each module-level constant that holds a message, against the message's own name.
        """
        found: dict[str, str] = {}
        for node in self.tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target, value = node.targets[0], node.value
            if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
                continue
            if not (isinstance(value.func, ast.Attribute) and value.func.attr == "define"):
                continue
            name = literal_of(value.args[0]) if value.args else None
            if name is not None:
                found[target.id] = name
        return found


def check_pack_messages(source: Path) -> list[str]:
    """List every way a package's refusals depart from the catalogue they are supposed to live in.

    Reads every module under ``source`` and reports a refusal raised under no code, a message
    minted and never read, and a code two imported catalogues both define. Every issue is a
    human-readable line prefixed by where it was found; an empty list means the package's
    wording conforms. The module docstring says what this deliberately does not judge, and
    why.

    Args:
        source: The package directory to hold to the rule -- a pack's own ``src/<package>``.

    Returns:
        Everything wrong, in a stable order. Empty when the package conforms.
    """
    if not source.is_dir():
        return [f"{source} is not a directory, so there is no package to check"]
    readings = [Reading(path, str(path.relative_to(source))) for path in source_files(source)]
    issues = [found for reading in readings for found in reading.uncoded()]
    issues.extend(dead(readings))
    issues.extend(colliding())
    return issues


def dead(readings: list["Reading"]) -> list[str]:
    """Find every message minted under a constant that nothing in the package reads.

    A constant is read when its name appears anywhere outside the module that minted it, or
    more than once inside it. Reading the sources as text is what keeps a message re-exported
    through an ``__init__`` or named in a table from reading as dead.

    Args:
        readings: Every module read, minting modules included.

    Returns:
        One finding per message nothing names, in the order the modules declare them.
    """
    texts = {reading.label: reading.path.read_text(encoding="utf-8") for reading in readings}
    issues: list[str] = []
    for reading in readings:
        for constant, name in reading.minted().items():
            pattern = _named(constant)
            if any(pattern.search(text) for label, text in texts.items() if label != reading.label):
                continue
            if len(pattern.findall(texts[reading.label])) > 1:
                continue
            issues.append(f"{reading.label}: {constant} mints {name!r} -- {DEAD_FIX}")
    return issues


def colliding() -> list[str]:
    """Find every code more than one imported catalogue defines.

    Walks ``Catalogue.all``, which holds every catalogue the process has imported: in a pack's
    suite that is the engine's catalogues and the pack's own, so a prefix a pack has taken
    from something installed beside it is named here rather than at a customer's.

    A catalogue registers itself when it is constructed and cannot be unregistered, so a test
    that mints one leaves it in the walk for every test after it. A ``test_`` prefix is the
    workspace's own spelling for a catalogue built inside a test, and is passed over here for
    that reason.

    Returns:
        One finding per colliding code, in the order the catalogues were imported.
    """
    seen: dict[str, Catalogue] = {}
    issues: list[str] = []
    for catalogue in Catalogue.all:
        if catalogue.prefix.startswith("test_"):
            continue
        for message in catalogue.messages.values():
            owner = seen.setdefault(message.code, catalogue)
            if owner is not catalogue:
                issues.append(f"{message.code} is defined by two catalogues: a code has exactly one owner")
    return issues
