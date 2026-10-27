"""What a coding agent is handed: the notes a project carries, and the catalog it reads without a server."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from clisupport import only, refusal, rows
from dirigent_cli.main import app, hoist_globals
from dirigent_cli.project import AGENTS_TEMPLATE, InitChoices, scaffold

runner = CliRunner()

#: A command the notes name, up to its first placeholder, flag, path or quoted argument.
NAMED_COMMAND = re.compile(r"uv run dg ((?:[a-z][a-z-]*)(?: [a-z][a-z-]*)*)")


def invoke(*argv: str) -> Any:
    """Run one command in the record mode an agent's shell gets."""
    return runner.invoke(app, hoist_globals(list(argv)))


def test_a_project_carries_notes_every_agent_reads(tmp_path: Path) -> None:
    made = scaffold(tmp_path / "demo", InitChoices(), version="1.2.3")
    agents = (tmp_path / "demo" / "AGENTS.md").read_text()
    assert agents.splitlines()[0] == "# Working in demo"
    assert (tmp_path / "demo" / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert {tmp_path / "demo" / "AGENTS.md", tmp_path / "demo" / "CLAUDE.md"} <= set(made.files)
    assert "AGENTS.md" in (tmp_path / "demo" / "README.md").read_text()


def test_notes_a_project_already_has_are_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    (root / "AGENTS.md").write_text("ours\n")
    made = scaffold(root, InitChoices(), version="1.2.3")
    assert (root / "AGENTS.md").read_text() == "ours\n"
    assert root / "AGENTS.md" in made.skipped


@pytest.mark.parametrize("command", sorted(set(NAMED_COMMAND.findall(AGENTS_TEMPLATE))))
def test_every_command_the_notes_name_exists(command: str) -> None:
    result = invoke(*command.split(), "--help")
    assert result.exit_code == 0, f"`dg {command}` is not a command:\n{result.output}"


def test_the_document_schema_is_composed_without_a_server() -> None:
    result = invoke("pipeline", "schema")
    assert result.exit_code == 0, result.output
    record = only(result.stdout, "pipeline.schema")
    assert record["blocks"] > 0
    schema = record["schema"]
    Draft202012Validator.check_schema(schema)
    hello = {
        "format": "dirigent/v1",
        "kind": "pipeline",
        "code": "hello",
        "steps": {"greet": {"block": "value.const", "config": {"value": "hi"}}},
    }
    assert list(Draft202012Validator(schema).iter_errors(hello)) == []  # pyright: ignore[reportUnknownMemberType]


def test_the_document_schema_is_written_where_an_editor_reads_it(tmp_path: Path) -> None:
    target = tmp_path / ".dirigent" / "document.schema.json"
    result = invoke("pipeline", "schema", "-f", str(target))
    assert result.exit_code == 0, result.output
    record = only(result.stdout, "pipeline.schema")
    assert record["path"] == str(target)
    assert "schema" not in record
    assert json.loads(target.read_text())["title"] == "dirigent/v1 document"


def test_the_blocks_installed_beside_dg_are_listed_and_shown_without_a_server() -> None:
    listed = invoke("blocks", "list", "--local", "--kind", "operator")
    assert listed.exit_code == 0, listed.output
    blocks = rows(listed.stdout, "block")
    assert "value.const" in {row["id"] for row in blocks}
    assert {row["kind"] for row in blocks} == {"operator"}
    shown = invoke("blocks", "show", "value.const", "--local")
    assert shown.exit_code == 0, shown.output
    assert "value" in only(shown.stdout, "block")["fields"]["config_schema"]["properties"]


def test_a_block_nobody_installed_is_refused_by_name() -> None:
    result = invoke("blocks", "show", "no.such", "--local")
    assert result.exit_code == 1
    assert refusal(result.stdout)["code"] == "cli.no_such_block"


REPO_ROOT = Path(__file__).resolve().parents[3]

#: Where the site is published, which every link in llms.txt is under.
SITE = "https://winterop-com.github.io/dirigent/"


def _nav_pages() -> set[str]:
    """Read every page the site's navigation names, as the path it is published at."""
    named = re.findall(r":\s*([a-z-]+)\.md\s*$", (REPO_ROOT / "mkdocs.yml").read_text(), flags=re.MULTILINE)
    return {"" if page == "index" else f"{page}/" for page in named}


def test_llms_txt_names_every_page_the_site_does_and_no_other() -> None:
    linked = set(re.findall(rf"\]\({re.escape(SITE)}([a-z-]*/?)\)", (REPO_ROOT / "docs" / "llms.txt").read_text()))
    assert linked == _nav_pages()


def test_a_project_made_before_the_notes_gets_them_and_keeps_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "older"
    scaffold(root, InitChoices(template="documents"), version="1.2.3")
    (root / "AGENTS.md").unlink()
    (root / "CLAUDE.md").write_text("ours\n")
    monkeypatch.chdir(root)
    result = invoke("init", "--agents")
    assert result.exit_code == 0, result.output
    record = only(result.stdout, "project.scaffolded")
    assert record["files"] == ["AGENTS.md"]
    assert record["skipped"] == ["CLAUDE.md"]
    assert (root / "AGENTS.md").read_text().splitlines()[0] == "# Working in older"
    assert (root / "CLAUDE.md").read_text() == "ours\n"


@pytest.mark.parametrize("extra", [["--template", "local"], ["--workflow"], ["--pack", "dirigent-dhis2"]])
def test_the_notes_alone_take_no_other_option(tmp_path: Path, extra: list[str]) -> None:
    result = invoke("init", str(tmp_path), "--agents", *extra)
    assert result.exit_code == 1
    assert refusal(result.stdout)["code"] == "cli.init_refused"
    assert not (tmp_path / "AGENTS.md").exists()


def test_the_notes_are_not_written_where_there_is_no_project(tmp_path: Path) -> None:
    result = invoke("init", str(tmp_path / "missing"), "--agents")
    assert result.exit_code == 1
    assert refusal(result.stdout)["code"] == "cli.init_refused"
    assert not (tmp_path / "missing").exists()
