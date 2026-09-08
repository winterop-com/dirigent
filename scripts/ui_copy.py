"""Print every sentence the UI renders, one per line, with where it lives.

The inventory a copy review reads: descriptions, empty states, status notes, placeholders,
dialog and card prose, and bare paragraphs. A sweep is reading this list end to end, not
grepping for the patterns somebody remembered.

    uv run python scripts/ui_copy.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "dirigent-server" / "frontend" / "src"

PATTERNS = (
    re.compile(r"""(?:description|emptyMessage|placeholder|title|aria-label)=["']([^"']{12,})["']"""),
    re.compile(r"""(?:description|emptyMessage|note|hint|help|placeholder):\s*["']([^"']{12,})["']"""),
    re.compile(r"<(?:Dialog|Card)Description>\s*([^<{][^<]{11,}?)\s*</"),
    re.compile(r"<p[^>]*>\s*([A-Z][^<{]{11,}?)\s*</p>"),
    re.compile(r"""=\s*["']([A-Z][^"']{11,}[.!?])["']"""),
)


def main() -> int:
    """Print every rendered sentence as file:line, deduplicated, in path order."""
    seen: set[tuple[str, str]] = set()
    for path in sorted(ROOT.rglob("*.tsx")) + sorted(ROOT.rglob("*.ts")):
        if "test" in path.name or "/ui/" in str(path):
            continue
        text = path.read_text()
        for pattern in PATTERNS:
            for match in pattern.finditer(text):
                sentence = re.sub(r"\s+", " ", match.group(1)).strip()
                key = (path.name, sentence)
                if key in seen:
                    continue
                seen.add(key)
                line = text[: match.start()].count("\n") + 1
                rel = path.relative_to(ROOT.parents[1])
                print(f"{rel}:{line}: {sentence}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
