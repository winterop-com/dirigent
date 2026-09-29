"""Print every word the UI says, from the catalogue it says it out of.

The inventory a copy review reads: every label, under its code, in the order
``packages/dirigent-server/frontend/src/lib/labels.ts`` declares it. A sweep is reading this list
end to end, not grepping for the patterns somebody remembered -- and because the catalogue is the
only place a user-visible string may live (``scripts/check_ui_labels.py`` holds that), the list is
complete by construction rather than by however many regexes it occurred to somebody to write.

It ends with what reading a list cannot show: the places the product says one thing in two ways.
Two codes holding the same words are one vocabulary drawn in two places, which is usually right
and occasionally a merge. Two codes whose words differ only in case, in punctuation or in
which form a word is in are drift, and drift is the defect this catalogue exists to make
visible. The grouping is crude and says so: read it as a prompt, not as a finding.

    uv run python scripts/ui_copy.py
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# It reads the catalogue the same way, so there is one parser rather than two that drift.
from check_ui_labels import entries  # noqa: E402  # isort: skip


#: The endings a word is said in when the same concept is drawn as a noun, a verb and a count:
#: fires, firings, fired.
ENDINGS = ("ings", "ing", "ies", "ed", "es", "s")


def stem(word: str) -> str:
    """Cut a word back to the concept it is a form of.

    It is crude on purpose: this reports, so a word it cuts too far costs a line somebody reads
    and dismisses, while a word it leaves whole costs the drift nobody notices.

    Args:
        word: One lower-case word.

    Returns:
        What is left after the ending that made it a form.
    """
    for ending in ENDINGS:
        if len(word) > len(ending) + 2 and word.endswith(ending):
            return word.removesuffix(ending)
    return word


def concept(text: str) -> str:
    """Reduce a label to the concept it names, so two spellings of it collide.

    Args:
        text: The label as written.

    Returns:
        Its words, stemmed, deduplicated and in order, with the punctuation and case gone.
    """
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    return " ".join(sorted({stem(word) for word in words}))


def plainly(text: str) -> str:
    """Reduce a label to its words, with case and a plural's ``s`` folded away.

    Args:
        text: The label as written.

    Returns:
        The same words, in the same order, in one form.
    """
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    return " ".join(word.removesuffix("s") if len(word) > 3 else word for word in words)


def main() -> int:
    """Print the catalogue, then what is said twice and what is nearly said twice.

    Returns:
        A process exit code, always 0: this reports, it does not refuse.
    """
    found = entries()
    if not found:
        print("no catalogue to read", file=sys.stderr)
        return 0
    section = ""
    for code, text in found:
        head = code.split(".")[0]
        if head != section:
            print(f"\n## {head}\n")
            section = head
        print(f"{code}: {text}")

    same: dict[str, list[str]] = defaultdict(list)
    near: dict[str, set[str]] = defaultdict(set)
    for code, text in found:
        same[text].append(code)
        near[concept(text)].add(text)

    twice = {text: codes for text, codes in same.items() if len(codes) > 1}
    if twice:
        print("\n## said twice\n")
        for text, codes in sorted(twice.items()):
            print(f"{text!r}: {', '.join(codes)}")

    # A word beside its plural, or a chip's lower case beside a tile's capital, is this product's
    # own convention rather than drift. What is left after folding both away is a concept the
    # product writes two ways.
    drifted = {key: texts for key, texts in near.items() if len({plainly(text) for text in texts}) > 1}
    if drifted:
        print("\n## nearly the same\n")
        for _, texts in sorted(drifted.items()):
            for text in sorted(texts):
                print(f"{text!r}: {', '.join(same[text])}")
            print()

    print(f"\n{len(found)} labels.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
