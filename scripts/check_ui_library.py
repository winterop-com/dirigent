#!/usr/bin/env python3
"""Check that no screen hand-builds what sokkel-ui or the icon vocabulary already draws.

Reads the frontend's sources as text, because a JS linter cannot see inside a ``className`` or a
JSX attribute's value. ``docs/ui-conventions.md``, "The component library".

Refused anywhere under ``src``, tests excepted:

* ``lucide-import``: an import from ``lucide-react`` outside ``lib/icons.ts`` and
  ``lib/glyphs.ts``, the two tables a mark is chosen in. A mark is ``ICONS.<concept>``, or a
  kind's glyph from ``lib/glyphs``.
* ``icon-button``: a ``<Button>`` sized ``icon``, ``icon-xs``, ``icon-sm`` or ``icon-lg``. An
  icon-only button is sokkel-ui's ``IconButton``, which cannot be drawn without a name and a
  tooltip.
* ``arbitrary-radius``: ``rounded-[...]``. A corner is a rung of the radius ladder.
* ``shut-title``: a ``<Button>`` carrying both ``disabled`` and ``title``. A disabled button takes
  no pointer and no focus, so its ``title`` is never read; a button that cannot act says why with
  ``reason``.

Run it with ``uv run python scripts/check_ui_library.py``; ``make static`` and ``make ui-lint``
both call it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parent.parent

SRC: Final = REPO_ROOT / "packages" / "dirigent-server" / "frontend" / "src"

#: The tables a mark is chosen in, which alone may import the glyph set.
GLYPH_TABLES: Final = frozenset({SRC / "lib" / "icons.ts", SRC / "lib" / "glyphs.ts"})

SUFFIXES: Final = {".ts", ".tsx"}

ICON_SIZE: Final = re.compile(
    r"""\bsize=(?:"icon(?:-[a-z]+)?"|'icon(?:-[a-z]+)?'|\{\s*['"]icon(?:-[a-z]+)?['"]\s*\})"""
)

LUCIDE: Final = re.compile(r"""from\s+['"]lucide-react['"]""")

RADIUS: Final = re.compile(r"\brounded(?:-[a-z]+)?-\[")

DISABLED: Final = re.compile(r"\sdisabled(?:=|\s|/?>)")

TITLE: Final = re.compile(r"\stitle=")

FIX: Final = {
    "lucide-import": "a mark is `ICONS.<concept>` from lib/icons; add the concept there if it has none.",
    "icon-button": "an icon-only button is sokkel-ui's `IconButton`, with a label and a tooltip.",
    "arbitrary-radius": "a corner is a rung of the radius ladder: rounded-sm, rounded-md or rounded-lg.",
    "shut-title": "a disabled button's `title` is never read; say why with the Button's `reason`.",
}


def source_files() -> list[Path]:
    """Every file the rules read, in a stable order.

    Returns:
        The .ts/.tsx files under ``src``, the tests excluded.
    """
    return sorted(path for path in SRC.rglob("*") if path.suffix in SUFFIXES and ".test." not in path.name)


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


def line_of(text: str, offset: int) -> int:
    """Say which line an offset falls on.

    Args:
        text: The source.
        offset: An offset into it.

    Returns:
        The 1-based line number.
    """
    return text.count("\n", 0, offset) + 1


def offences(path: Path) -> list[tuple[int, str]]:
    """Every offence in one file.

    Args:
        path: The file to read.

    Returns:
        ``(line, rule)`` for each offence, in the order they occur.
    """
    text = path.read_text(encoding="utf-8")
    found: list[tuple[int, str]] = []
    if path not in GLYPH_TABLES:
        found += [(line_of(text, match.start()), "lucide-import") for match in LUCIDE.finditer(text)]
    for match in re.finditer(r"<Button\b", text):
        tag = tag_at(text, match.start())
        if ICON_SIZE.search(tag):
            found.append((line_of(text, match.start()), "icon-button"))
        if DISABLED.search(tag) and TITLE.search(tag):
            found.append((line_of(text, match.start()), "shut-title"))
    found += [(line_of(text, match.start()), "arbitrary-radius") for match in RADIUS.finditer(text)]
    return sorted(found)


def main() -> int:
    """Refuse every offence.

    Returns:
        A process exit code: 0 when the sources hold none, 1 otherwise.
    """
    files = source_files()
    said = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: {rule}: {FIX[rule]}"
        for path in files
        for line, rule in offences(path)
    ]
    if said:
        for line in said:
            print(line)
        print(f"\n{len(said)} UI library fault(s).")
        return 1
    print(f"ui library ok ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
