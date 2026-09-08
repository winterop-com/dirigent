"""The edges each package may depend on, asserted rather than described.

An architecture page says where a new thing goes; this fails when somebody puts it somewhere
else. A tree that is only written down is one nothing enforces.
"""

import re
import tomllib
from pathlib import Path
from typing import Any, Final, cast

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
PACKAGES: Final = ROOT / "packages"

#: What each package may depend on, of dirigent's own. A package may depend on less.
ALLOWED: Final[dict[str, set[str]]] = {
    "dirigent-common": set(),
    "dirigent-plugin": {"dirigent-common"},
    "dirigent-client": {"dirigent-common"},
    "dirigent-core": {"dirigent-common", "dirigent-plugin", "dirigent-client"},
    "dirigent-server": {"dirigent-common", "dirigent-plugin", "dirigent-client", "dirigent-core"},
    "dirigent-cli": {
        "dirigent-common",
        "dirigent-plugin",
        "dirigent-client",
        "dirigent-core",
        "dirigent-server",
        "dirigent-blocks",
    },
    "dirigent-blocks": {"dirigent-common", "dirigent-plugin"},
    "dirigent-parquet": {"dirigent-common", "dirigent-plugin"},
    "dirigent-storage-s3": {"dirigent-common", "dirigent-plugin"},
    "dirigent-testing": {"dirigent-common", "dirigent-plugin"},
}

#: What a module under ``src`` may import, which is the same rule read off the code.
IMPORT = re.compile(r"^\s*(?:from|import)\s+(dirigent_[a-z0-9_]+)", re.MULTILINE)


def distributions() -> list[str]:
    """Every workspace package, so a new one has to be placed rather than silently allowed."""
    return sorted(path.name for path in PACKAGES.iterdir() if (path / "pyproject.toml").is_file())


def declared(package: str) -> set[str]:
    """The dirigent packages this one's metadata says it depends on."""
    manifest = tomllib.loads((PACKAGES / package / "pyproject.toml").read_text())
    project = cast("dict[str, Any]", manifest.get("project", {}))
    requirements = cast("list[str]", project.get("dependencies", []))
    names = [str(item).split(">")[0].split("=")[0].split("[")[0].strip() for item in requirements]
    return {name for name in names if name.startswith("dirigent-")}


def imported(package: str) -> set[str]:
    """The dirigent packages this one's source actually imports."""
    own = package.replace("-", "_")
    found: set[str] = set()
    for module in (PACKAGES / package / "src").rglob("*.py"):
        for name in IMPORT.findall(module.read_text()):
            if name != own:
                found.add(name.replace("_", "-"))
    return found


def test_every_package_is_placed_in_the_tree() -> None:
    """A new package is an architectural decision, so it does not get a default."""
    assert set(distributions()) == set(ALLOWED), "a package was added without saying what it may depend on"


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_a_package_declares_only_what_it_may_depend_on(package: str) -> None:
    assert declared(package) <= ALLOWED[package], f"{package} declares a dependency the tree does not allow"


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_a_package_imports_only_what_it_may_depend_on(package: str) -> None:
    """Metadata can be right while the code reaches past it."""
    assert imported(package) <= ALLOWED[package], f"{package} imports a package the tree does not allow"


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_a_package_declares_what_it_imports(package: str) -> None:
    """An import nothing declares is a dependency that happens to be installed."""
    assert imported(package) <= declared(package), f"{package} imports something its metadata does not require"


def sourced(package: str) -> set[str]:
    """The dirigent packages this one's metadata resolves from the workspace."""
    manifest = tomllib.loads((PACKAGES / package / "pyproject.toml").read_text())
    tool = cast("dict[str, Any]", manifest.get("tool", {}))
    uv = cast("dict[str, Any]", tool.get("uv", {}))
    sources = cast("dict[str, Any]", uv.get("sources", {}))
    return {name for name in sources if name.startswith("dirigent-")}


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_a_package_sources_only_what_it_declares(package: str) -> None:
    """A workspace source for a dependency nothing declares outlives the dependency itself.

    The declaration is what the other tests read, so a stale source says the old edge is
    still there to anyone reading the manifest, and nothing catches it.
    """
    assert sourced(package) <= declared(package), f"{package} sources a package it does not depend on"


def test_common_depends_on_nothing_of_dirigents() -> None:
    """It is the bottom of the tree; a dependency here would be a cycle waiting to happen."""
    assert declared("dirigent-common") == set()
    assert imported("dirigent-common") == set()


def test_the_client_does_not_depend_on_the_block_contract() -> None:
    """An SDK has no use for Operator, and saying so is half the reason common exists."""
    assert "dirigent-plugin" not in declared("dirigent-client")
    assert "dirigent-plugin" not in imported("dirigent-client")
