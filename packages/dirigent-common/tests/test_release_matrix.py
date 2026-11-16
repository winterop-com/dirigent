"""The release publishes every package the workspace builds."""

import tomllib
from pathlib import Path
from typing import Any, Final

import yaml

ROOT: Final = Path(__file__).resolve().parents[3]


def test_the_release_matrix_names_every_workspace_package() -> None:
    workflow: dict[str, Any] = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yaml").read_text())
    published = set(workflow["jobs"]["pypi"]["strategy"]["matrix"]["package"])
    built = {
        tomllib.loads(path.read_text())["project"]["name"] for path in (ROOT / "packages").glob("*/pyproject.toml")
    }
    assert published == built
