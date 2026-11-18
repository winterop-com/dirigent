"""The lists of packages the configuration keeps by hand name every package the workspace holds."""

import ast
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
PACKAGES: Final = ROOT / "packages"


def _config() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def _sources() -> set[str]:
    return {f"packages/{path.parent.name}/src" for path in PACKAGES.glob("*/src")}


def _modules() -> set[str]:
    return {path.name for path in PACKAGES.glob("*/src/*") if (path / "__init__.py").is_file()}


def test_mypy_reads_every_package() -> None:
    paths = set(_config()["tool"]["mypy"]["mypy_path"]) - {"scripts"}
    assert paths == _sources()


def test_pyright_reads_every_package() -> None:
    paths = set(_config()["tool"]["pyright"]["extraPaths"]) - {"scripts"}
    assert paths == _sources()


def test_isort_takes_every_package_as_first_party() -> None:
    assert set(_config()["tool"]["ruff"]["lint"]["isort"]["known-first-party"]) == _modules()


@pytest.mark.parametrize(
    "path",
    [
        PACKAGES / "dirigent-common" / "tests" / "test_messages.py",
        PACKAGES / "dirigent-testing" / "tests" / "test_wording.py",
    ],
    ids=lambda path: path.name,
)
def test_a_walk_over_every_catalogue_imports_every_messages_module(path: Path) -> None:
    holders = {found.parent.name for found in PACKAGES.glob("*/src/*/messages.py")}
    (listing,) = [
        node.value
        for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MODULES"
    ]
    listed = ast.literal_eval(listing) if listing is not None else ()
    assert {str(name).removesuffix(".messages") for name in listed} == holders
