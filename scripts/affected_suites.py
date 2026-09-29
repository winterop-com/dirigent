#!/usr/bin/env python3
"""Name the test suites a change can reach, for a pull request that runs only those.

The graph is read from the workspace packages' own ``pyproject.toml`` files, so a package
added, removed or re-pointed changes the answer without this file being touched. Two edges no
manifest spells out are added here, because both are resolved at run time rather than
declared: the ``dirigent.*`` entry points the plugin host discovers, and the ``pytest11``
entry point every suite in the interpreter loads.

Anything outside ``packages/`` selects every suite: a document, an infra file or the root
manifest is read by tests that reach out of their own package, and a rule naming which ones
would be a second copy of that truth.

Reads paths on stdin, on the command line, or from ``--base``. Writes the pytest paths to
stdout, one per line, and the plan behind them to stderr.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGES: Final = ROOT / "packages"

#: The package whose plugin host discovers every ``dirigent.*`` entry point in the interpreter.
DISCOVERER: Final = "dirigent-core"

#: Where a requirement's name stops and its version, extras or markers begin.
SEPARATORS: Final = "=<>!~[ ;(@"

#: Paths no Python test reads. The browser lane and the UI type scale cover this subtree.
INERT: Final = ("packages/dirigent-server/frontend/",)


def _distribution(requirement: str) -> str:
    """The distribution a requirement names, without its version, extras or markers."""
    for index, character in enumerate(requirement):
        if character in SEPARATORS:
            return requirement[:index].strip()
    return requirement.strip()


def _requirements(manifest: dict[str, Any]) -> Iterator[str]:
    """Every requirement a manifest states, across dependencies, extras and groups."""
    project: dict[str, Any] = manifest.get("project", {})
    yield from project.get("dependencies", [])
    for extra in project.get("optional-dependencies", {}).values():
        yield from extra
    for group in manifest.get("dependency-groups", {}).values():
        yield from (item for item in group if isinstance(item, str))


class Workspace:
    """The workspace's packages, and which of them can reach which."""

    def __init__(self) -> None:
        """Read every manifest under ``packages/`` and build the graph from it."""
        manifests: dict[str, dict[str, Any]] = {}
        self.directories: dict[str, Path] = {}
        for path in sorted(PACKAGES.glob("*/pyproject.toml")):
            manifest: dict[str, Any] = tomllib.loads(path.read_text())
            name = str(manifest["project"]["name"])
            manifests[name] = manifest
            self.directories[name] = path.parent

        contributors: set[str] = set()
        loaded_by_every_suite: set[str] = set()
        self.requires: dict[str, set[str]] = {}
        for name, manifest in manifests.items():
            self.requires[name] = {
                distribution
                for distribution in map(_distribution, _requirements(manifest))
                if distribution in self.directories and distribution != name
            }
            groups: dict[str, Any] = manifest["project"].get("entry-points", {})
            if any(group.startswith("dirigent.") for group in groups):
                contributors.add(name)
            if "pytest11" in groups:
                loaded_by_every_suite.add(name)

        self.requires[DISCOVERER] |= contributors - {DISCOVERER}
        for name in self.requires:
            self.requires[name] |= loaded_by_every_suite - {name}

    def owner(self, path: str) -> str | None:
        """The package a repository path belongs to, or None when it belongs to none."""
        parts = Path(path).parts
        if len(parts) < 2 or parts[0] != PACKAGES.name:
            return None
        return next((name for name, at in self.directories.items() if at.name == parts[1]), None)

    def dependents(self, changed: Iterable[str]) -> set[str]:
        """The changed packages, and every package that reaches one of them."""
        reached = set(changed)
        growing = True
        while growing:
            growing = False
            for name, requires in self.requires.items():
                if name not in reached and requires & reached:
                    reached.add(name)
                    growing = True
        return reached

    def suites(self, packages: Iterable[str]) -> list[str]:
        """The pytest path of each of those packages that has a suite, in a stable order."""
        directories = (self.directories[name] / "tests" for name in sorted(packages))
        return [str(path.relative_to(ROOT)) for path in directories if path.is_dir()]


def changed_paths(base: str) -> list[str]:
    """Every path that differs from the merge base with ``base``, the working tree included."""

    def git(*arguments: str) -> list[str]:
        finished = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True)
        return [line for line in finished.stdout.splitlines() if line]

    merge_base = git("merge-base", base, "HEAD")[0]
    committed = git("diff", "--name-only", merge_base, "HEAD")
    # A porcelain line carries a two-column status, then the path, then `-> path` on a rename.
    uncommitted = [line[3:].split(" -> ")[-1].strip('"') for line in git("status", "--porcelain=1")]
    return sorted({*committed, *uncommitted})


def plan(paths: Iterable[str], workspace: Workspace) -> tuple[set[str], list[str]]:
    """The packages a change reaches, and the lines explaining why each one is in."""
    changed: set[str] = set()
    reasons: list[str] = []
    everything = False
    for path in paths:
        if path.startswith(INERT):
            continue
        package = workspace.owner(path)
        if package is None:
            if not everything:
                reasons.append(f"{path} is outside {PACKAGES.name}/, so every suite runs")
            everything = True
        elif package not in changed:
            changed.add(package)
            reasons.append(f"{package} changed")
    if everything:
        return set(workspace.directories), reasons
    reached = workspace.dependents(changed)
    reasons.extend(f"{name} depends on a changed package" for name in sorted(reached - changed))
    return reached, reasons


def main() -> int:
    """Print the pytest paths for the change described on stdin, on argv, or by ``--base``."""
    parser = argparse.ArgumentParser(description="Name the test suites a change can reach.")
    parser.add_argument("--base", help="a ref whose merge base with HEAD the change is measured from")
    parser.add_argument("paths", nargs="*", help="changed paths, when no base is given")
    arguments = parser.parse_args()

    if arguments.base:
        paths = changed_paths(arguments.base)
    elif arguments.paths:
        paths = [str(path) for path in arguments.paths]
    else:
        paths = [line.strip() for line in sys.stdin if line.strip()]

    workspace = Workspace()
    packages, reasons = plan(paths, workspace)
    suites = workspace.suites(packages)

    print(f"{len(paths)} path(s) changed, reaching {len(packages)} of {len(workspace.directories)}:", file=sys.stderr)
    for reason in reasons:
        print(f"  {reason}", file=sys.stderr)
    print("\n".join(suites))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
