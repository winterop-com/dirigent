#!/usr/bin/env python3
"""Check that every version the documentation names as the current one is the workspace's version.

It reads the version from ``packages/dirigent-cli/pyproject.toml`` and scans ``README.md``,
``ROADMAP.md``, every package's ``README.md`` and every page under ``docs/`` except
``docs/releases.md``, whose versions are history. A mention is one of:

* a pinned package, ``dirigent-cli==0.30.0`` or ``dirigent-dhis2==0.30.0``;
* the image, ``ghcr.io/winterop-com/dirigent:0.30.0``;
* the version a ``dg`` command prints, ``dg 0.30.0``;
* the ``version=`` of an ``instance.initialised`` or ``project.scaffolded`` record in a
  captured ``dg init``.

Each one that differs is printed as ``path:line: found X, the workspace is at Y`` and the exit
status is 1. Run it with ``uv run python scripts/check_docs_version.py``; ``make static`` calls it.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

#: The package whose version every package in the workspace carries.
VERSION_SOURCE: Final = REPO_ROOT / "packages" / "dirigent-cli" / "pyproject.toml"

#: The release notes, where an older version is a fact about that release.
HISTORY: Final = {REPO_ROOT / "docs" / "releases.md"}

_V: Final = r"(\d+\.\d+\.\d+)"

#: Each pattern's first group is the version it names.
MENTIONS: Final = (
    re.compile(rf"\bdirigent(?:-[a-z0-9]+)*=={_V}"),
    re.compile(rf"ghcr\.io/winterop-com/dirigent:v?{_V}"),
    re.compile(rf"\bdg {_V}\b"),
    re.compile(rf"\[(?:instance\.initialised|project\.scaffolded)\].*?\bversion={_V}"),
)


def workspace_version() -> str:
    """The version the CLI package declares."""
    with VERSION_SOURCE.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def pages() -> list[Path]:
    """Every documentation file the check scans, release notes left out."""
    found = [REPO_ROOT / "README.md", REPO_ROOT / "ROADMAP.md"]
    found += sorted((REPO_ROOT / "packages").glob("*/README.md"))
    found += sorted((REPO_ROOT / "docs").rglob("*.md"))
    return [path for path in found if path.is_file() and path not in HISTORY]


def stale(path: Path, version: str) -> list[str]:
    """One fault line for each mention in the file that names another version."""
    faults: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern in MENTIONS:
            for match in pattern.finditer(line):
                if match.group(1) != version:
                    where = path.relative_to(REPO_ROOT)
                    faults.append(f"{where}:{number}: found {match.group(1)}, the workspace is at {version}")
    return faults


def main() -> int:
    """Print every stale mention and fail when there is one."""
    version = workspace_version()
    faults = [fault for path in pages() for fault in stale(path, version)]
    for fault in faults:
        print(fault)
    if faults:
        print(f"{len(faults)} version mention(s) in the documentation are not {version}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
