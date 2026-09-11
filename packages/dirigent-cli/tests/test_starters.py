"""Copying a starter: the text rewrite, `dg examples`, and `dg pipeline new`."""

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from clisupport import of_kind, only, records, refusal, rows
from dirigent_cli.main import app, hoist_globals
from dirigent_cli.starters import instantiate, preflight, summary
from dirigent_client import Requirements

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

FLOW = """\
# A comment that has to survive.
format: dirigent/v1
kind: pipeline
code: a-starter
tags: [open-data, http, starter]

steps: {}
"""

BLOCK = """\
format: dirigent/v1
kind: pipeline
code: a-starter
tags:
  - open-data
  - starter
  - http

steps: {}
"""


def machine(*argv: str) -> Any:
    """Run one command in the record spelling, which is what a command writes unasked."""
    return runner.invoke(app, hoist_globals(list(argv)))


def test_a_flow_list_loses_only_the_starter_tag() -> None:
    copied = instantiate(FLOW, "mine")
    assert "code: mine" in copied
    assert "tags: [open-data, http]" in copied
    assert copied.startswith("# A comment that has to survive.\n")


def test_a_block_list_loses_only_the_starter_tag() -> None:
    copied = instantiate(BLOCK, "mine")
    assert "code: mine" in copied
    assert "  - open-data\n  - http\n" in copied
    assert "starter" not in copied


def test_the_tag_goes_wherever_it_sits_in_the_list() -> None:
    for tags in ("[starter, a, b]", "[a, starter, b]", "[a, b, starter]"):
        copied = instantiate(FLOW.replace("[open-data, http, starter]", tags), "mine")
        assert "tags: [a, b]" in copied
    for block in ("  - starter\n  - a\n", "  - a\n  - starter\n"):
        copied = instantiate(BLOCK.replace("  - open-data\n  - starter\n  - http\n", block), "mine")
        assert "  - a\n" in copied and "starter" not in copied


def test_a_document_whose_only_tag_was_starter_loses_the_whole_entry() -> None:
    assert "tags" not in instantiate(FLOW.replace("[open-data, http, starter]", "[starter]"), "mine")
    only_one = BLOCK.replace("  - open-data\n  - starter\n  - http\n", "  - starter\n")
    copied = instantiate(only_one, "mine")
    assert "tags" not in copied
    assert copied.endswith("steps: {}\n")


def test_a_step_named_code_is_never_rewritten() -> None:
    source = FLOW.replace("steps: {}", "steps:\n  one:\n    config:\n      code: keep-me\n")
    copied = instantiate(source, "mine")
    assert "      code: keep-me" in copied
    assert "code: mine" in copied


def test_a_requirements_summary_counts_what_a_document_needs() -> None:
    assert summary(Requirements()) == "-"
    assert summary(Requirements(connections=["a", "b"], schemas=["c"])) == "2 connections, 1 schema"


def test_the_preflight_names_the_commands_that_create_what_is_missing() -> None:
    lines = preflight(Requirements(connections=["warehouse"], schemas=["reading"], workers=["docker"]))
    assert lines[0] == "dg connection create KIND warehouse"
    assert lines[1] == "dg schema create reading.json --code reading"
    assert lines[-1] == "a worker carrying the docker tag"


def test_examples_list_emits_one_record_per_row() -> None:
    result = machine("examples", "list", "--local", "--starter")
    assert result.exit_code == 0, result.output
    listed = rows(result.stdout, "example")
    assert listed
    assert all(row["starter"] for row in listed)
    assert {"code", "name", "tags", "plugin", "shelf", "requires"} <= set(listed[0])


def test_examples_list_narrows_by_shelf_and_tag() -> None:
    result = machine("examples", "list", "--local", "--shelf", "recipes", "--tag", "starter")
    assert {row["shelf"] for row in rows(result.stdout, "example")} == {"recipes"}


def test_examples_show_carries_the_source() -> None:
    result = machine("examples", "show", "report-to-file", "--local")
    assert result.exit_code == 0, result.output
    shown = only(result.stdout, "example.source")
    assert shown["code"] == "report-to-file"
    assert "format: dirigent/v1" in shown["source"]


def test_examples_show_prints_the_document_verbatim_at_a_terminal() -> None:
    result = runner.invoke(app, hoist_globals(["-o", "console", "examples", "show", "report-to-file", "--local"]))
    assert result.exit_code == 0, result.output
    assert "format: dirigent/v1" in result.stdout
    assert not result.stdout.lstrip().startswith("{"), "a document is not a record stream"


def test_examples_show_refuses_a_code_nobody_ships() -> None:
    result = machine("examples", "show", "no-such-example", "--local")
    assert result.exit_code == 1
    assert "no example 'no-such-example' is installed" in refusal(result.stdout)["message"]


def test_pipeline_new_writes_the_copy_and_says_what_it_needs(tmp_path: Path) -> None:
    result = machine("pipeline", "new", "report-to-file", "--local", "--code", "mine", "--dir", str(tmp_path / "p"))
    assert result.exit_code == 0, result.output
    created = only(result.stdout, "pipeline.created")
    assert created["code"] == "mine"
    assert created["starter"] == "report-to-file"
    written = tmp_path / "p" / "mine.yaml"
    assert created["path"] == str(written)
    text = written.read_text()
    assert "code: mine" in text
    assert "starter" not in text.split("steps:")[0]
    assert created["requires"]["blocks"]


def test_pipeline_new_takes_the_starters_own_code_when_none_is_named(tmp_path: Path) -> None:
    result = machine("pipeline", "new", "report-to-file", "--local", "--dir", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert (tmp_path / "report-to-file.yaml").is_file()


def test_pipeline_new_refuses_an_example_that_is_not_a_starter(tmp_path: Path) -> None:
    result = machine("pipeline", "new", "hello-world", "--local", "--dir", str(tmp_path))
    assert result.exit_code == 1
    refused = refusal(result.stdout)
    assert "not a starter" in refused["message"]
    assert any("'starter' tag" in problem for problem in refused["problems"])
    assert not list(tmp_path.glob("*.yaml"))


def test_pipeline_new_refuses_to_overwrite_a_file_that_is_there(tmp_path: Path) -> None:
    (tmp_path / "report-to-file.yaml").write_text("mine\n")
    result = machine("pipeline", "new", "report-to-file", "--local", "--dir", str(tmp_path))
    assert result.exit_code == 1
    assert "already there" in refusal(result.stdout)["message"]
    assert (tmp_path / "report-to-file.yaml").read_text() == "mine\n"


def test_pipeline_new_renders_the_preflight_at_a_terminal(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        hoist_globals(
            ["-o", "console", "pipeline", "new", "kafka-consume-then-transform", "--local", "--dir", str(tmp_path)]
        ),
    )
    assert result.exit_code == 0, result.output
    assert "dg connection create KIND orders-topic" in result.stdout


def test_a_copied_starter_carries_no_record_of_its_own_beyond_the_one(tmp_path: Path) -> None:
    result = machine("pipeline", "new", "report-to-file", "--local", "--dir", str(tmp_path))
    assert [record["kind"] for record in records(result.stdout)] == ["pipeline.created"]
    assert len(of_kind(records(result.stdout), "pipeline.created")) == 1
