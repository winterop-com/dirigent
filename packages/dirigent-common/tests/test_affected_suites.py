"""The suites a pull request runs include every suite its change can break."""

import re
import sys
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
HERE: Final = Path(__file__).resolve()

sys.path.insert(0, str(ROOT / "scripts"))

from affected_suites import ALSO_READ_BY, READ_AS_FILES, Workspace, plan  # noqa: E402  # isort: skip


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return Workspace()


def selected(workspace: Workspace, *paths: str) -> set[str]:
    packages, _ = plan(paths, workspace)
    return packages


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "packages/dirigent-server/src/dirigent_server/app.py",
            {"dirigent-client", "dirigent-mcp", "dirigent-cli", "dirigent-server"},
        ),
        (
            "packages/dirigent-core/src/dirigent_core/engine/references.py",
            {"dirigent-block-execute", "dirigent-block-jq", "dirigent-client", "dirigent-common", "dirigent-mcp"},
        ),
        ("packages/dirigent-server/frontend/src/lib/labels.ts", {"dirigent-cli", "dirigent-server"}),
        ("packages/dirigent-server/frontend/index.html", {"dirigent-server"}),
        ("packages/dirigent-examples/src/dirigent_examples/shelves/python/README.md", {"dirigent-client"}),
        ("packages/dirigent-block-http/src/dirigent_block_http/__init__.py", {"dirigent-common", "dirigent-testing"}),
    ],
)
def test_a_change_selects_the_suites_that_can_break_on_it(workspace: Workspace, path: str, expected: set[str]) -> None:
    assert expected <= selected(workspace, path)


def test_a_path_outside_the_packages_selects_every_suite(workspace: Workspace) -> None:
    assert selected(workspace, "docs/conventions.md") == set(workspace.directories)


def test_every_suite_is_selected_by_a_change_to_a_package_its_tests_import(workspace: Workspace) -> None:
    for name, directory in workspace.directories.items():
        for path in (directory / "tests").rglob("*.py"):
            for module in set(re.findall(r"^\s*(?:from|import)\s+(dirigent_\w+)", path.read_text(), re.MULTILINE)):
                imported = module.replace("_", "-")
                if imported not in workspace.directories:
                    continue
                source = str(workspace.directories[imported].relative_to(ROOT) / "src" / module / "x.py")
                assert name in selected(workspace, source), f"{path.relative_to(ROOT)} imports {module}"


def test_every_suite_that_reads_the_examples_as_files_is_named(workspace: Workspace) -> None:
    (readers,) = ALSO_READ_BY.values()
    for name, directory in workspace.directories.items():
        for path in (directory / "tests").rglob("*.py"):
            if path.resolve() != HERE and re.search(r'/ "examples"', path.read_text()):
                assert name in readers, f"{path.relative_to(ROOT)} reads examples/ and is not named"


def test_every_suite_that_reads_the_frontend_as_files_is_named(workspace: Workspace) -> None:
    (readers,) = READ_AS_FILES.values()
    for name, directory in workspace.directories.items():
        for path in (directory / "tests").rglob("*.py"):
            text = "" if path.resolve() == HERE else path.read_text()
            if '/ "frontend"' in text or "check_ui_" in text:
                assert name in readers, f"{path.relative_to(ROOT)} reads the frontend and is not named"
