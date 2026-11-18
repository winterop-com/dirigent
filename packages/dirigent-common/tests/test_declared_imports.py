"""Every library a package's source imports is one the package declares.

A library that arrives only through another package's requirement disappears from an install
the day that package stops needing it, and nothing says so until an import fails.
"""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
PACKAGES: Final = ROOT / "packages"

#: Where an import name is not the distribution's own name.
DISTRIBUTIONS: Final = packages_distributions()


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared(directory: Path) -> set[str]:
    project = tomllib.loads((directory / "pyproject.toml").read_text())["project"]
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    return {_canonical(re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0]) for requirement in requirements}


def _imported(directory: Path) -> set[str]:
    names: set[str] = set()
    for path in (directory / "src").rglob("*.py"):
        if "shelves" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return {name for name in names if name not in sys.stdlib_module_names and not name.startswith("dirigent_")}


@pytest.mark.parametrize("directory", sorted(PACKAGES.glob("dirigent-*")), ids=lambda directory: directory.name)
def test_a_package_declares_every_library_its_source_imports(directory: Path) -> None:
    declared = _declared(directory)
    missing = {
        name: sorted(_canonical(distribution) for distribution in DISTRIBUTIONS.get(name, [name]))
        for name in _imported(directory)
        if not any(_canonical(distribution) in declared for distribution in DISTRIBUTIONS.get(name, [name]))
    }
    assert missing == {}
