"""Tests for ``dg blocks new`` and ``dg init``'s templates."""

import base64
import py_compile
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from clisupport import of_kind, records, refusal
from dirigent_cli.main import app, hoist_globals
from dirigent_cli.project import project_name, scaffold, write_token_env

runner = CliRunner()


def invoke(*argv: str) -> Any:
    """Run one command in the default record mode, which is what these tests read."""
    return runner.invoke(app, hoist_globals(list(argv)))


def test_the_scaffold_writes_a_working_pack(tmp_path: Path) -> None:
    result = invoke("blocks", "new", "acme", "--directory", str(tmp_path))
    assert result.exit_code == 0, result.output

    root = tmp_path / "dirigent-acme"
    written = records(result.output)
    assert [record["path"] for record in of_kind(written, "scaffold")]
    closing = of_kind(written, "scaffolded")[0]
    assert closing["directory"] == str(root)
    assert closing["next"] == ["uv sync", "uv run pytest"]

    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["name"] == "dirigent-acme"
    assert project["project"]["entry-points"]["dirigent.plugins.v1"]["acme"] == "dirigent_acme:plugin"
    assert (root / "src" / "dirigent_acme" / "py.typed").is_file()
    for module in ("src/dirigent_acme/__init__.py", "src/dirigent_acme/acme.py", "tests/test_plugin.py"):
        py_compile.compile(str(root / module), doraise=True)


def test_an_existing_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "dirigent-acme").mkdir()
    result = invoke("blocks", "new", "acme", "--directory", str(tmp_path))
    assert result.exit_code != 0
    assert "already exists" in refusal(result.stdout)["message"]


@pytest.mark.parametrize("name", ["Acme", "9lives", "acme-pack", ""])
def test_a_name_that_cannot_become_a_module_is_refused(tmp_path: Path, name: str) -> None:
    result = invoke("blocks", "new", name, "--directory", str(tmp_path))
    assert result.exit_code != 0
    assert not (tmp_path / f"dirigent-{name}").exists()


REPO_ROOT = Path(__file__).resolve().parents[3]


def compose_files(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scaffold the stack and load it beside the base stack it is cut from."""
    scaffold(tmp_path / "stack", template="compose", version="1.2.3", password="a-long-enough-password")
    scaffolded = yaml.safe_load((tmp_path / "stack" / "compose.yaml").read_text())
    base = yaml.safe_load((REPO_ROOT / "infra" / "compose.yaml").read_text())
    return scaffolded, base


def test_the_scaffolded_stack_matches_the_base_stack(tmp_path: Path) -> None:
    """Only what the instance is built from, and which documents it applies, may differ."""
    scaffolded, base = compose_files(tmp_path)
    assert sorted(scaffolded["services"]) == sorted(base["services"])
    assert sorted(scaffolded["volumes"]) == sorted(base["volumes"])
    for name, service in base["services"].items():
        theirs = scaffolded["services"][name]
        assert sorted(theirs.get("environment", {})) == sorted(service.get("environment", {})), name
        assert theirs.get("healthcheck") == service.get("healthcheck"), name
        assert theirs.get("depends_on") == service.get("depends_on"), name
        mounts = [mount.split(":", 1)[1] for mount in theirs.get("volumes", [])]
        assert mounts == [mount.split(":", 1)[1] for mount in service.get("volumes", [])], name
        # environment is compared by key above: the scaffold's DIRIGENT_SECRET_KEY message
        # points at the .env it writes rather than at the repository's .env.example.
        skipped = {"build", "image", "volumes", "environment"}
        rest = {key: value for key, value in service.items() if key not in skipped}
        assert {key: theirs[key] for key in rest} == rest, name


def test_the_scaffolded_stack_builds_on_the_published_image(tmp_path: Path) -> None:
    scaffolded, _ = compose_files(tmp_path)
    for name in ("server", "worker"):
        service = scaffolded["services"][name]
        assert service["image"] == "dirigent-instance:local"
        assert service["build"]["dockerfile"] == "Dockerfile"
        assert service["build"]["args"] == {"DIRIGENT_IMAGE": "${DIRIGENT_IMAGE:-ghcr.io/winterop-com/dirigent:1.2.3}"}


def test_the_scaffolded_dockerfile_builds_on_the_running_version(tmp_path: Path) -> None:
    scaffold(tmp_path / "stack", template="compose", version="1.2.3", password="a-long-enough-password")
    instructions = [
        line for line in (tmp_path / "stack" / "Dockerfile").read_text().splitlines() if line and line[0] != "#"
    ]
    assert instructions[0] == "ARG DIRIGENT_IMAGE=ghcr.io/winterop-com/dirigent:1.2.3"
    assert instructions[1] == "FROM ${DIRIGENT_IMAGE}"
    recipe = (tmp_path / "stack" / "Dockerfile").read_text()
    assert "# RUN uv pip install dirigent-dhis2==1.2.3" in recipe


def test_the_scaffolded_stack_carries_no_build_secret(tmp_path: Path) -> None:
    """Every package the recipe installs is public, so the build needs nothing handed to it."""
    scaffold(tmp_path / "stack", template="compose", version="1.2.3", password="pw")
    compose = yaml.safe_load((tmp_path / "stack" / "compose.yaml").read_text())
    assert "secrets" not in compose
    assert "secrets" not in compose["services"]["server"]["build"]
    assert "secrets" not in compose["services"]["worker"]["build"]


def test_the_stack_applies_the_project_documents(tmp_path: Path) -> None:
    scaffolded, _ = compose_files(tmp_path)
    mount = "./pipelines:/etc/dirigent/pipelines:ro"
    assert mount in scaffolded["services"]["server"]["volumes"]
    assert mount in scaffolded["services"]["worker"]["volumes"]


def test_the_environment_file_is_private_and_carries_a_key_and_the_password(tmp_path: Path) -> None:
    scaffold(tmp_path / "stack", template="compose", version="1.2.3", password="a-long-enough-password")
    environment = tmp_path / "stack" / ".env"
    assert environment.stat().st_mode & 0o777 == 0o600
    values = dict(
        line.split("=", 1) for line in environment.read_text().splitlines() if line and not line.startswith("#")
    )
    assert values["DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD"] == "a-long-enough-password"
    assert values["DIRIGENT_IMAGE"] == "ghcr.io/winterop-com/dirigent:1.2.3"
    key = values["DIRIGENT_SECRET_KEY"]
    assert len(key) == 44
    assert len(base64.urlsafe_b64decode(key)) == 32
    assert (tmp_path / "stack" / ".gitignore").read_text().splitlines()[-1] == ".env"


def test_the_compose_template_initialises_no_local_instance(tmp_path: Path) -> None:
    result = invoke(
        "init", str(tmp_path / "stack"), "--template", "compose", "--password", "a-long-enough-password", "--json"
    )
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "stack" / ".dirigent" / "state").exists()
    closing = of_kind(records(result.stdout), "project.scaffolded")[0]
    assert closing["template"] == "compose"
    assert closing["next"] == [
        "uv sync",
        "docker compose up -d",
        "uv run dg auth login --username admin",
    ]
    assert {"compose.yaml", "Dockerfile", ".env", ".gitignore", "pyproject.toml", "README.md"} <= set(closing["files"])


def test_the_compose_template_refuses_an_admin_name_and_documents_only(tmp_path: Path) -> None:
    named = invoke(
        "init", str(tmp_path / "a"), "--template", "compose", "--admin", "root", "--password", "x" * 20, "--json"
    )
    assert named.exit_code != 0
    assert "first admin is named admin" in refusal(named.stdout)["message"]

    skipped = invoke("init", str(tmp_path / "b"), "--template", "compose", "--documents-only", "--json")
    assert skipped.exit_code != 0
    assert "no instance to skip" in refusal(skipped.stdout)["message"]


def test_every_install_page_names_the_one_install_line() -> None:
    """One page drifting to another install form sends a reader down a path nobody tests."""
    for page in ("docs/getting-started.md", "docs/index.md", "docs/tutorial.md", "README.md"):
        assert "uv tool install dirigent-cli" in (REPO_ROOT / page).read_text(), page


@pytest.mark.parametrize("template", ["basic", "ci", "compose"])
def test_every_template_pins_the_running_runtime(tmp_path: Path, template: str) -> None:
    scaffold(tmp_path / "pinned", template=template, version="1.2.3", password="a-long-enough-password")
    project = tomllib.loads((tmp_path / "pinned" / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == ["dirigent-cli==1.2.3"]
    assert project["project"]["requires-python"] == ">=3.13"
    assert "sources" not in project.get("tool", {}).get("uv", {}), "dirigent-cli resolves from PyPI"


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        ("hello-world", "hello-world"),
        ("Hello World!", "hello-world"),
        ("My Project", "my-project"),
        ("...", "dirigent-project"),
    ],
)
def test_a_directory_name_becomes_a_project_name(tmp_path: Path, directory: str, expected: str) -> None:
    assert project_name(tmp_path / directory) == expected


def test_a_relative_directory_is_named_for_what_it_resolves_to(tmp_path: Path, monkeypatch: Any) -> None:
    home = tmp_path / "My Project"
    home.mkdir()
    monkeypatch.chdir(home)
    assert project_name(Path(".")) == "my-project"


def test_an_existing_pyproject_is_left_alone_and_reported(tmp_path: Path) -> None:
    root = tmp_path / "already"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "theirs"\n')
    made = scaffold(root, version="1.2.3")
    assert made.skipped == [root / "pyproject.toml"]
    assert root / "pyproject.toml" not in made.files
    assert tomllib.loads((root / "pyproject.toml").read_text())["project"]["name"] == "theirs"


def test_an_existing_root_ignore_gains_the_missing_lines(tmp_path: Path) -> None:
    root = tmp_path / "already"
    root.mkdir()
    (root / ".gitignore").write_text(".venv/\n")
    made = scaffold(root, version="1.2.3")
    assert (root / ".gitignore").read_text().splitlines() == [".venv/", "__pycache__/", ".env"]
    assert root / ".gitignore" in made.files
    assert made.skipped == []


@pytest.mark.parametrize(
    ("template", "first"),
    [("basic", "uv sync"), ("ci", "uv sync"), ("compose", "uv sync")],
)
def test_the_readme_names_the_pinned_runtime_and_the_first_command(tmp_path: Path, template: str, first: str) -> None:
    scaffold(tmp_path / "read", template=template, version="1.2.3", password="a-long-enough-password")
    readme = (tmp_path / "read" / "README.md").read_text()
    assert "uv run dg" in readme
    assert first in readme
    assert readme.splitlines()[0] == "# read"


def test_the_root_ignore_covers_the_environment_uv_builds_and_the_env_file(tmp_path: Path) -> None:
    scaffold(tmp_path / "plain", version="1.2.3")
    lines = (tmp_path / "plain" / ".gitignore").read_text().splitlines()
    assert ".venv/" in lines
    assert "__pycache__/" in lines
    assert ".env" in lines, "the token dg init writes to .env would be committed"


def test_the_token_env_file_is_readable_by_its_owner_alone(tmp_path: Path) -> None:
    scaffold(tmp_path / "plain", version="1.2.3")
    path = write_token_env(tmp_path / "plain", "a-minted-token")
    assert path == tmp_path / "plain" / ".env"
    assert "DG_TOKEN=a-minted-token" in path.read_text().splitlines()
    assert path.stat().st_mode & 0o777 == 0o600
