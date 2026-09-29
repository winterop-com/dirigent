#!/usr/bin/env python
"""Hold every refusal a browser can be shown to a sentence the browser itself can say.

WHY THIS EXISTS. A refusal carries a dotted code, the params its sentence was written out of, and
that sentence already rendered into ``detail`` by whichever Python process minted it.
``lib/refusal`` draws this interface's own sentence for the code and falls back to ``detail`` only
where it has none -- so a code with no label still *works*, in English, silently. Without this
check the fallback is where the fault this change removed quietly comes back.

WHAT IT HOLDS. Every message the workspace mints lands in exactly one of six buckets, and a code
that lands in none of them fails:

* **Served.** Its catalogue is contributed through ``Contribution.labels``, so the instance serves
  its template from ``GET /labels`` and the browser renders from that. A pack owns its own words.
* **A command's own.** ``cli.*`` and ``health.*`` are said by ``dg`` at a terminal and reach no
  browser.
* **A test double's.** ``testing.*``.
* **Wordless.** The whole template is one param -- the server's ``{detail}``, pydantic's ``{msg}``
  -- so there is nothing to translate and the fallback already renders the only words there are.
  Giving one of these words means first giving the refusal inside it a code of its own.
* **Labelled.** ``refused.<code>`` in ``labels.ts`` says it in this interface's words.
* **Recorded as unsaid.** In ``unlabelled_refusals.txt``, which is a ratchet and not a list of
  wishes: a new code may not join it, and a code that has been given words must leave it.

It also fails a label that has drifted from the refusal it draws -- a code no catalogue mints any
more, a sentence naming a param the refusal does not carry (which would make the renderer fall
back to English for a reason nobody could see), and a code owned by both this table and a pack.

WHAT IT CANNOT SEE. Which codes a browser is *actually* shown. A route raising a refusal is
reachable or not by argument, not by reading, so the buckets above are drawn by ownership instead:
everything a browser could be shown is held, and the recorded file says how much of that has words
so far. The eight ``validation.*`` codes pydantic mints on first sight are not in any catalogue
until that error type has been seen once, so they are wordless by construction rather than by
declaration -- their template is ``{msg}``, which is pydantic's English in a param.
"""

import importlib
import pkgutil
import re
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_ui_labels import entries  # noqa: E402  # isort: skip

#: Where a code with no words yet is recorded, one per line.
RECORD: Final = REPO_ROOT / "scripts" / "unlabelled_refusals.txt"

#: The section of `labels.ts` that holds one sentence per server code.
SECTION: Final = "refused."

#: A template that is one param and nothing else has no words of its own.
WORDLESS: Final = re.compile(r"^\{[a-z_][a-z0-9_]*\}$")

#: A named hole, as both catalogues write one.
HOLE: Final = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

#: Catalogues only a terminal reads, and the one a test double refuses out of.
NOT_A_BROWSERS: Final = frozenset({"cli", "health", "testing"})

#: Every package whose import registers a catalogue.
PACKAGES: Final = (
    "dirigent_common",
    "dirigent_plugin",
    "dirigent_core",
    "dirigent_client",
    "dirigent_server",
    "dirigent_cli",
    "dirigent_testing",
)


def minted() -> dict[str, tuple[str, str]]:
    """Every message the workspace mints, as code -> (prefix, template).

    Returns:
        One entry per catalogued message, with test-only catalogues left out.
    """
    from dirigent_common.messages import Catalogue

    for name in PACKAGES:
        package = importlib.import_module(name)
        for found in pkgutil.walk_packages(package.__path__, f"{name}."):
            try:
                importlib.import_module(found.name)
            except Exception:  # noqa: BLE001  # a module that will not import mints nothing
                continue
    return {
        message.code: (catalogue.prefix, message.text)
        for catalogue in Catalogue.all
        if not catalogue.prefix.startswith("test_")
        for message in catalogue.messages.values()
    }


def served() -> set[str]:
    """Every code an installed pack contributes, which the instance serves rather than this table.

    Returns:
        The codes ``GET /labels`` answers with on this checkout.
    """
    from dirigent_core.plugins import load_plugin_host

    return set(load_plugin_host().labels)


def labelled() -> dict[str, str]:
    """Every sentence this interface holds for a server code, as code -> the sentence.

    Returns:
        One entry per ``refused.*`` label, keyed by the code it draws.
    """
    return {code.removeprefix(SECTION): said for code, said in entries() if code.startswith(SECTION)}


def recorded() -> list[str]:
    """Every code recorded as having no words here yet, in the order the file lists them.

    Returns:
        The codes the record holds, comments and blank lines dropped.
    """
    if not RECORD.is_file():
        return []
    lines = RECORD.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def faults(
    catalogue: dict[str, tuple[str, str]], contributed: set[str], here: dict[str, str], listed: list[str]
) -> tuple[list[str], list[str]]:
    """Weigh every code against the six buckets, and every label against the code it draws.

    Args:
        catalogue: Every message the workspace mints.
        contributed: The codes an installed pack serves.
        here: The sentences this interface holds, by code.
        listed: The codes recorded as having no words yet.

    Returns:
        What is wrong, and the codes that would be written to the record.
    """
    said: list[str] = []
    unsaid: list[str] = []
    on_record = set(listed)
    for code, (prefix, template) in sorted(catalogue.items()):
        if code in contributed:
            if code in here:
                said.append(
                    f"{code} is both contributed by a pack and given words in labels.ts: "
                    "one code has one owner, so take the label out and let the pack's travel."
                )
            continue
        if prefix in NOT_A_BROWSERS or WORDLESS.match(template):
            continue
        if code in here:
            wanted = set(HOLE.findall(here[code]))
            carried = set(HOLE.findall(template))
            stray = sorted(wanted - carried)
            if stray:
                said.append(
                    f"{code} is drawn from {stray}, which the refusal does not carry "
                    f"(it carries {sorted(carried)}): the renderer would fall back to English "
                    "and nothing on screen would say why."
                )
            if code in on_record:
                said.append(f"{code} has words now, so take it out of {RECORD.name}.")
            continue
        unsaid.append(code)
        if code not in on_record:
            said.append(
                f"{code} can reach a browser and nothing here says it: give it a sentence under "
                f"`refused.{code}` in labels.ts, or add it to {RECORD.name} if it is not yours to write."
            )
    for code in listed:
        if code not in catalogue:
            said.append(f"{RECORD.name} lists {code}, which no catalogue mints any more: take it out.")
    for code in sorted(set(here) - set(catalogue)):
        said.append(f"labels.ts says `refused.{code}`, which no catalogue mints: a stale sentence, take it out.")
    return said, unsaid


def main() -> int:
    """Print what is wrong, or what each bucket holds, and say whether the gate passes."""
    catalogue = minted()
    contributed = served()
    here = labelled()
    write = "--write" in sys.argv
    said, unsaid = faults(catalogue, contributed, here, [] if write else recorded())
    if write:
        RECORD.write_text(
            "# Every refusal a browser can be shown that this interface has no words for yet.\n"
            "#\n"
            "# A ratchet, not a backlog: `scripts/check_refusal_labels.py` refuses a new entry, and\n"
            "# refuses to keep one that has been given a sentence under `refused.<code>` in\n"
            "# labels.ts. Written by that script's --write; shrink it by writing sentences.\n"
            + "".join(f"{code}\n" for code in unsaid),
            encoding="utf-8",
        )
        print(f"recorded {len(unsaid)} refusals with no words yet in {RECORD.name}")
        return 0
    if said:
        for fault in said:
            print(fault)
        print(f"\n{len(said)} refusal(s) to answer for.")
        return 1
    wordless = sum(1 for prefix, text in catalogue.values() if WORDLESS.match(text) and prefix not in NOT_A_BROWSERS)
    terminal = sum(1 for prefix, _ in catalogue.values() if prefix in NOT_A_BROWSERS)
    print(
        f"refusal labels ok ({len(catalogue)} codes: {len(here)} said here, {len(contributed)} served by packs, "
        f"{terminal} a terminal's, {wordless} wordless, {len(unsaid)} recorded as unsaid)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
