#!/usr/bin/env python3
"""Check that every UI label the documentation quotes is still a label the UI says.

WHY THIS EXISTS. ``docs/releases.md`` once quoted a screen's heading by name, the heading was
renamed, and the released note went on saying a word the product had stopped saying. Nothing
caught it, because nothing could: prose is prose, and a phrase in backticks is a block kind, a
document key, a CLI flag, a column header or a label, with no way to tell which from the text.

SO THE AUTHOR SAYS WHICH. A phrase the documentation quotes *because the UI draws it* carries
``attr_list``'s ``{ .label }``::

    The dashboard's `in flight`{ .label } tile counts them.

That is the whole marker. It renders as the inline code it already was, so a marked phrase reads
on the page exactly as an unmarked one; what it buys is that this check can find it. Marking is
opt-in for a measured reason: ``docs/`` holds hundreds of backticked multi-word phrases and only a
handful are labels, so a check that guessed would be almost all false alarm and would be turned
off within a week.

WHAT IT REFUSES. A marked phrase that ``src/lib/labels.ts`` no longer holds, exactly as written.
Exactly, because a label is the string a person reads: ``Right Now`` is not ``Right now``, and a
note that has drifted in case has drifted. Where the catalogue holds something close, the fault
says so, since the usual cause is the rename this check exists to catch.

WHAT IT CANNOT SEE. A label quoted with no marker on it, which is the cost of not guessing, and a
sentence that paraphrases a label rather than quoting it. Neither is this check's business: it
holds what an author said was a label, and the marker is what makes that claim checkable.

Run it alone with ``uv run python scripts/check_docs_labels.py``; ``make static`` and
``make ui-lint`` both call it.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

# It reads the catalogue through the one parser that reads it, so the set of labels this holds
# documentation to cannot drift from the set `make static` holds the components to.
from check_ui_labels import entries  # noqa: E402  # isort: skip

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The prose this applies to. Every page the site is built from.
DOCS = REPO_ROOT / "docs"

#: The class an author writes to say "the UI draws this phrase".
MARKER: Final = "label"

#: A code span followed by an ``attr_list`` block: `` `Phrase`{ .label } ``. The attribute block
#: takes the forms attr_list accepts -- ``{.label}``, ``{ .label }``, ``{: .label }`` -- and may
#: carry more than the one class, so the classes are read out rather than matched whole.
QUOTED: Final = re.compile(r"`([^`\n]+)`\{:?([^}\n]*)\}")

#: The opening or closing line of a fenced block, in either of the two fences mkdocs takes.
FENCE: Final = re.compile(r"^\s*(```|~~~)")

#: How close a catalogue entry has to be before it is worth naming as the likely rename.
NEARNESS: Final = 0.7

FIX: Final = "no label says this; quote what the catalogue holds, or drop the marker"


def said() -> set[str]:
    """Read every label a page could quote verbatim.

    A label with a value in it is a function and a refusal's template names its holes, so neither
    is a phrase a page can quote and neither belongs in the set a quote is held against.

    Returns:
        What the catalogue says, as written, for every label that is a plain phrase.
    """
    plain = set()
    for _, text in entries():
        if "=>" in text or "${" in text or text.startswith("{"):
            continue
        plain.add(text)
    return plain


def pages() -> list[Path]:
    """Find every page the marker could appear on.

    Returns:
        Every markdown file under ``docs/``, in a stable order.
    """
    return sorted(DOCS.rglob("*.md")) if DOCS.is_dir() else []


def marked(text: str) -> list[tuple[int, str]]:
    """Find every phrase a page claims the UI draws.

    A fenced block is skipped: a marker inside one is teaching the syntax, not claiming that the
    product says the words in the example.

    Args:
        text: One page, whole.

    Returns:
        Each ``(line number, phrase)`` whose attribute block carries the marker class.
    """
    found = []
    fenced = False
    for at, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in QUOTED.finditer(line):
            classes = {word.removeprefix(".") for word in match.group(2).split() if word.startswith(".")}
            if MARKER in classes:
                found.append((at, match.group(1)))
    return found


def main() -> int:
    """Report every quoted label the UI no longer says, then fail if there were any.

    Returns:
        A process exit code: 0 when clean, 1 when anything was found.
    """
    every = said()
    if not every:
        print("no catalogue to check the documentation against", file=sys.stderr)
        return 0
    files = pages()
    faults = 0
    quoted = 0
    for path in files:
        for lineno, phrase in marked(path.read_text(encoding="utf-8")):
            quoted += 1
            if phrase in every:
                continue
            faults += 1
            near = difflib.get_close_matches(phrase, every, n=1, cutoff=NEARNESS)
            hint = f" -- did the catalogue rename it to {near[0]!r}?" if near else ""
            print(f"{path.relative_to(REPO_ROOT)}:{lineno}: {phrase!r} -- {FIX}{hint}")
    if faults:
        plural = "" if faults == 1 else "s"
        print(f"\n{faults} quoted label{plural} the UI no longer says.", file=sys.stderr)
        return 1
    print(f"docs labels ok ({quoted} quoted, {len(every)} quotable labels, {len(files)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
