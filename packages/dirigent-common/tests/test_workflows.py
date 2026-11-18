"""What the workflows promise about secrets, caches and publishing, read without running them."""

from pathlib import Path
from typing import Any, Final

import yaml

ROOT: Final = Path(__file__).resolve().parents[3]
WORKFLOWS: Final = ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    return loaded


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """The ``on:`` block, which YAML 1.1 reads as the key ``True``."""
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    return triggers


def test_a_docker_hub_token_reaches_only_the_step_that_signs_in() -> None:
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for name, job in _workflow(path.name)["jobs"].items():
            assert "DOCKERHUB_TOKEN" not in job.get("env", {}), f"{path.name} {name} hands the token to every step"
            for step in job.get("steps", []):
                if "DOCKERHUB_TOKEN" in step.get("env", {}):
                    assert "docker login" in step["run"], f"{path.name} {name} {step.get('name')}"


def test_the_release_build_restores_no_cache() -> None:
    steps = _workflow("release.yaml")["jobs"]["build"]["steps"]
    (setup,) = [step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")]
    assert setup["with"]["enable-cache"] is False


def test_the_site_is_published_only_after_ci_passed_on_main() -> None:
    workflow = _workflow("pages.yaml")
    triggers = _triggers(workflow)
    assert "push" not in triggers
    assert triggers["workflow_run"] == {"workflows": ["ci"], "types": ["completed"], "branches": ["main"]}
    condition = workflow["jobs"]["deploy"]["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in condition
