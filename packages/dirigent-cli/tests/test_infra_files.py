"""What the infrastructure files promise, checked without starting any of them."""

import re
import subprocess
from pathlib import Path
from typing import Any, Final, cast

import pytest
import yaml

from dirigent_cli.project import InitChoices, compose_document, scaffold

REPO_ROOT: Final = Path(__file__).resolve().parents[3]

#: The one service meant to be reached from elsewhere, which asks every caller to authenticate.
PUBLIC_PORTS: Final = {"${DIRIGENT_PORT:-3333}:3333"}


def _published(document: dict[str, Any]) -> list[str]:
    services = cast("dict[str, dict[str, Any]]", document["services"])
    return [str(port) for service in services.values() for port in service.get("ports", [])]


@pytest.mark.parametrize("path", sorted((REPO_ROOT / "infra").glob("compose*.yaml")), ids=lambda path: path.name)
def test_a_stack_publishes_on_loopback_alone(path: Path) -> None:
    for port in _published(yaml.safe_load(path.read_text())):
        assert port.startswith("127.0.0.1:") or port in PUBLIC_PORTS, f"{path.name} publishes {port} on every interface"


def test_the_scaffolded_stack_publishes_on_loopback_alone() -> None:
    choices = InitChoices(
        template="compose", services=("s3", "docker", "kafka", "rabbitmq"), password="a-long-enough-password"
    )
    for port in _published(yaml.safe_load(compose_document(choices, "1.2.3"))):
        assert port.startswith("127.0.0.1:") or port in PUBLIC_PORTS, f"the scaffold publishes {port}"


@pytest.mark.parametrize("variable", ["POSTGRES_PASSWORD", "S3_SECRET_KEY"])
def test_the_stack_has_no_default_for_a_credential(variable: str) -> None:
    choices = InitChoices(template="compose", services=("s3",), password="a-long-enough-password")
    for document in ((REPO_ROOT / "infra" / "compose.yaml").read_text(), compose_document(choices, "1.2.3")):
        assert f"${{{variable}:-" not in document
        assert f"${{{variable}:?" in document


def test_the_example_environment_names_no_credential() -> None:
    lines = dict(
        line.split("=", 1)
        for line in (REPO_ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert lines["POSTGRES_PASSWORD"] == ""
    assert lines["S3_SECRET_KEY"] == ""


def test_a_scaffolded_stack_generates_its_own_credentials(tmp_path: Path) -> None:
    choices = InitChoices(template="compose", services=("s3",), password="a-long-enough-password")
    seen: list[dict[str, str]] = []
    for name in ("one", "two"):
        scaffold(tmp_path / name, choices, version="1.2.3")
        text = (tmp_path / name / ".env").read_text()
        seen.append(dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")))
    for variable in ("POSTGRES_PASSWORD", "S3_SECRET_KEY"):
        assert re.fullmatch(r"[0-9a-f]{48}", seen[0][variable]), "hex goes into a URL as it stands"
        assert seen[0][variable] != seen[1][variable]
    assert seen[0]["POSTGRES_PASSWORD"] != seen[0]["S3_SECRET_KEY"]


def test_every_dockerignore_pattern_that_names_a_kind_of_file_matches_at_any_depth() -> None:
    """A pattern with no ``**/`` matches at the root alone, and ``COPY packages/`` takes what is below."""
    patterns = [
        line.lstrip("!")
        for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    at_the_root_on_purpose = {"docs", "site", "reports"}
    for pattern in patterns:
        assert pattern.startswith(("**/", "packages/")) or pattern in at_the_root_on_purpose, pattern
    for secret in ("**/.env", "**/.env.*", "**/.dirigent", "**/.git"):
        assert secret in patterns


def _packs_check() -> str:
    dockerfile = (REPO_ROOT / "infra" / "Dockerfile").read_text()
    found = re.search(r"^RUN (set -f;.*?^    done)$", dockerfile, re.MULTILINE | re.DOTALL)
    assert found is not None
    return found[1]


def _check_packs(packs: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - a fixed command, with the input in the environment
        ["/bin/sh", "-c", _packs_check()],
        env={"DIRIGENT_PACKS": packs, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "packs",
    [
        "",
        "dirigent-dhis2==1.2.3",
        "dirigent-dhis2==1.2.3 dirigent-block-parquet==1.2.3",
        "dirigent-dhis2==1.2.3rc1",
        "dirigent-dhis2==1!2.3.post1+local",
        "dirigent_dhis2[extra,other]==1.2.3",
    ],
)
def test_a_pinned_pack_is_built(packs: str) -> None:
    assert _check_packs(packs).returncode == 0


@pytest.mark.parametrize(
    "packs",
    [
        "dirigent-dhis2",
        "dirigent-dhis2==1.2.3 dirigent-block-parquet",
        "dirigent-dhis2>=1.2",
        "dirigent-dhis2~=1.2",
        "dirigent-dhis2==1.*",
        "dirigent-dhis2==",
        "git+https://example.test/pack.git",
        "https://example.test/pack.whl",
        "./local-pack",
        "--index-url=https://example.test/simple",
        "-r",
    ],
)
def test_anything_else_is_refused_by_name(packs: str) -> None:
    result = _check_packs(packs)
    assert result.returncode != 0
    assert "DIRIGENT_PACKS" in result.stderr
    assert "is not pinned" in result.stderr
