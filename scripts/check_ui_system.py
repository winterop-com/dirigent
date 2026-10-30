#!/usr/bin/env python3
"""Check that no screen hand-builds what the design system already draws.

``src/components/ds`` holds one component per thing every screen draws -- a chip, a dot, an
icon button, a heading, a field -- and ``src/lib/icons.ts`` holds the one mark each concept
wears. That is only true while pages reach for them, so this reads the sources as text and
refuses the shapes a hand-built copy leaves behind. ``docs/ui-conventions.md``, "Design system".

Refused, under ``src/pages`` and ``src/components`` but not ``components/ui`` (the generated
primitives) or ``components/ds`` (the system itself):

* ``word-chip``: a hand-typed word chip, one class string holding ``rounded-sm``, ``border``,
  ``px-1.5`` and ``text-xs``. That shape is ``Chip``.
* ``icon-button``: a ``<Button>`` sized ``icon``, ``icon-xs``, ``icon-sm`` or ``icon-lg``. An
  icon-only button is ``IconButton``, which cannot be drawn without a name and a tooltip.
* ``lucide-import``: an import from ``lucide-react``. A mark is ``ICONS.<concept>`` from
  ``lib/icons``. This one holds under ``components/ds`` too.
* ``arbitrary-radius``: ``rounded-[...]``. A corner is a rung of the radius ladder.

THE RATCHET. Every offender that predates the check is recorded in
``scripts/ui_system_offenders.txt`` as ``rule<TAB>path<TAB>count``. A file may hold exactly as
many offences of a rule as recorded: one more is refused as new, one fewer is refused as stale,
so a migration shrinks the record in the same change. ``--write`` rewrites the record from what
the sources hold now.

Run it with ``uv run python scripts/check_ui_system.py``; ``make static`` and ``make ui-lint``
both call it.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parent.parent

SRC = REPO_ROOT / "packages" / "dirigent-server" / "frontend" / "src"

#: Where the rules apply.
ROOTS: Final = (SRC / "pages", SRC / "components")

#: The generated primitives, never checked.
PRIMITIVES: Final = SRC / "components" / "ui"

#: The design system itself, checked for the icon import alone.
SYSTEM: Final = SRC / "components" / "ds"

RECORD: Final = REPO_ROOT / "scripts" / "ui_system_offenders.txt"

SUFFIXES: Final = {".ts", ".tsx"}

#: A string literal, or the static text of a template literal.
LITERAL: Final = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|`([^`]*)`")

CHIP_CLASSES: Final = frozenset({"rounded-sm", "border", "px-1.5", "text-xs"})

ICON_SIZE: Final = re.compile(
    r"""\bsize=(?:"icon(?:-[a-z]+)?"|'icon(?:-[a-z]+)?'|\{\s*['"]icon(?:-[a-z]+)?['"]\s*\})"""
)

LUCIDE: Final = re.compile(r"""from\s+['"]lucide-react['"]""")

RADIUS: Final = re.compile(r"\brounded(?:-[a-z]+)?-\[")

FIX: Final = {
    "word-chip": "a word on a chip is `Chip` from components/ds/Chip.",
    "icon-button": "an icon-only button is `IconButton` from components/ds/IconButton, with a label and a tooltip.",
    "lucide-import": "a mark is `ICONS.<concept>` from lib/icons; add the concept there if it has none.",
    "arbitrary-radius": "a corner is a rung of the radius ladder: rounded-sm, rounded-md or rounded-lg.",
}

HEADER: Final = (
    "# Every place a screen still hand-builds what the design system draws.\n"
    "#\n"
    "# A ratchet, not a backlog: `scripts/check_ui_system.py` refuses a new offence and refuses to\n"
    "# keep a count a migration has lowered. One line per rule and file: rule, path, count.\n"
    "# Written by that script's --write; shrink it by moving a screen onto components/ds.\n"
)


def source_files() -> list[Path]:
    """Every file the rules read, in a stable order.

    Returns:
        The .ts/.tsx files under the roots, the primitives and the tests excluded.
    """
    found: list[Path] = []
    for root in ROOTS:
        for path in root.rglob("*"):
            if path.suffix not in SUFFIXES or ".test." in path.name:
                continue
            if PRIMITIVES in path.parents:
                continue
            found.append(path)
    return sorted(found)


def tag_at(text: str, start: int) -> str:
    """Read one JSX opening tag, its attributes included, from where it opens.

    Args:
        text: The source.
        start: The offset of the ``<``.

    Returns:
        The tag's text up to and including its closing ``>``.
    """
    depth = 0
    quote = ""
    at = start + 1
    while at < len(text):
        char = text[at]
        if quote:
            if char == "\\":
                at += 2
                continue
            if char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth == 0:
            return text[start : at + 1]
        at += 1
    return text[start:]


def offences(path: Path) -> Counter[str]:
    """Count each rule's offences in one file.

    Args:
        path: The file to read.

    Returns:
        How many times each rule is broken there.
    """
    text = path.read_text(encoding="utf-8")
    found: Counter[str] = Counter()
    found["lucide-import"] += len(LUCIDE.findall(text))
    if SYSTEM in path.parents:
        return +found
    for match in LITERAL.finditer(text):
        held = next(group for group in match.groups() if group is not None)
        if set(held.split()) >= CHIP_CLASSES:
            found["word-chip"] += 1
    for match in re.finditer(r"<Button\b", text):
        if ICON_SIZE.search(tag_at(text, match.start())):
            found["icon-button"] += 1
    found["arbitrary-radius"] += len(RADIUS.findall(text))
    return +found


def measured() -> dict[tuple[str, str], int]:
    """Count every offence the sources hold now.

    Returns:
        ``(rule, path relative to the repo) -> count``, for every non-zero count.
    """
    counts: dict[tuple[str, str], int] = {}
    for path in source_files():
        for rule, count in offences(path).items():
            counts[(rule, path.relative_to(REPO_ROOT).as_posix())] = count
    return counts


def recorded() -> dict[tuple[str, str], int]:
    """Read the ratchet.

    Returns:
        ``(rule, path) -> count`` as the record holds them.
    """
    if not RECORD.is_file():
        return {}
    counts: dict[tuple[str, str], int] = {}
    for line in RECORD.read_text(encoding="utf-8").splitlines():
        if line.strip() == "" or line.startswith("#"):
            continue
        rule, path, count = line.split("\t")
        counts[(rule, path)] = int(count)
    return counts


def main() -> int:
    """Refuse what the record does not cover, or rewrite the record with ``--write``.

    Returns:
        A process exit code: 0 when the sources match the record, 1 otherwise.
    """
    now = measured()
    if "--write" in sys.argv:
        lines = [f"{rule}\t{path}\t{count}\n" for (rule, path), count in sorted(now.items())]
        RECORD.write_text(HEADER + "".join(lines), encoding="utf-8")
        print(f"recorded {sum(now.values())} offences across {len(now)} rule-file pairs in {RECORD.name}")
        return 0
    held = recorded()
    said: list[str] = []
    for key in sorted(set(now) | set(held)):
        rule, path = key
        have, allowed = now.get(key, 0), held.get(key, 0)
        if have > allowed:
            said.append(f"{path}: {rule}: {have} found, {allowed} recorded -- {FIX[rule]}")
        elif have < allowed:
            said.append(
                f"{path}: {rule}: {have} found, {allowed} recorded -- the ratchet is stale; "
                "run `uv run python scripts/check_ui_system.py --write` to shrink it."
            )
    if said:
        for line in said:
            print(line)
        print(f"\n{len(said)} design-system fault(s).", file=sys.stderr)
        return 1
    by_rule = Counter[str]()
    for (rule, _), count in now.items():
        by_rule[rule] += count
    summary = ", ".join(f"{rule} {by_rule[rule]}" for rule in FIX)
    print(f"ui system ok ({len(source_files())} files; recorded offenders: {summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
