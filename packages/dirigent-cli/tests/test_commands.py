"""The command tree, driven against a real server running in this process."""

import asyncio
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from clisupport import asking_for_the_rendering, closing, of_kind, only, plain, records, refusal, rows
from dirigent_cli.commands import instance_settings
from dirigent_cli.main import app, dev_admin, hoist_globals
from dirigent_cli.profiles import resolve_endpoint
from dirigent_cli.project import ProjectError, find_project, scaffold
from dirigent_core.config import CONFIG_FILE_ENV, Settings, reset_settings_cache

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: cli-demo
description: Two shell steps the CLI can drive.
params:
  type: object
  properties:
    greeting:
      type: string
      default: hello from the cli
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, "${params.greeting}"]
  farewell:
    block: shell.run
    depends_on: [greet]
    config:
      argv: [echo, goodbye]
"""


#: A daily clock on the demo pipeline, for the commands that read a cadence rather than fire it.
SCHEDULE = """
triggers:
  schedules:
    - code: nightly
      cron: "0 5 * * *"
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Give every command a throwaway instance and a working directory of its own."""
    config = tmp_path / "settings.yaml"
    config.write_text(
        f'database_url: "sqlite+aiosqlite:///{tmp_path / "dirigent.db"}"\n'
        f'artifact_root: "file://{tmp_path / "artifacts"}"\n'
        "enabled_unsafe_blocks: [shell.run]\n"
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Run the real API on a real port, and point the CLI at it through DG_URL and DG_TOKEN."""
    import asyncio
    import socket
    import threading
    import time

    import uvicorn
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from dirigent_client.enums import UserRole
    from dirigent_core.auth import create_user, issue_token
    from dirigent_core.database import create_engine, create_session_factory, session_scope
    from dirigent_core.logging import configure_logging
    from dirigent_core.models import Base
    from dirigent_server import create_app

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        enabled_unsafe_blocks=["shell.run"],
    )

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with session_scope(create_session_factory(engine)) as session:
                user = await create_user(session, "tester", "a test password", role=UserRole.ADMIN)
                issued = await issue_token(session, user, name="cli")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    # The server shares this process, so its logs would land in the CLI's captured output
    # and a --json assertion would try to parse a log line as JSON.
    configure_logging("ERROR", "console")
    token = asyncio.run(prepare())
    # The socket stays bound and is handed to uvicorn. Reading the port and closing it first
    # leaves a window in which another test's server takes it, and this one's CLI then talks
    # to that instance's database.
    holder = socket.socket()
    # No SO_REUSEADDR. It lets a bind succeed on a port another socket has not finished with,
    # so a test whose server outlived its teardown could go on serving the port the next test
    # was handed -- and a CLI would then write to one instance's database and read from
    # another's. Without it, that clash is a loud bind error instead of a silent one.
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = int(holder.getsockname()[1])

    running = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_config=None))
    thread = threading.Thread(target=lambda: running.run(sockets=[holder]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not running.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert running.started, "the test server did not start"
    monkeypatch.setenv("DG_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("DG_TOKEN", token)
    try:
        yield token
    finally:
        running.should_exit = True
        thread.join(timeout=20)
        # The socket is released only once the server that was using it has stopped. Closing
        # first hands the port back while a live server may still answer on it, which is how
        # one test's CLI ends up reading another test's database.
        stopped = not thread.is_alive()
        holder.close()
        assert stopped, "the test server did not stop"


def invoke(*argv: str) -> Any:
    """Run one command and return its result, hoisting global options as the entry point does."""
    return runner.invoke(app, asking_for_the_rendering(hoist_globals(list(argv))))


def machine(*argv: str) -> Any:
    """Run one command in the record spelling, which is what a command writes unasked."""
    return runner.invoke(app, hoist_globals(list(argv)))


def apply_document(tmp_path: Path, text: str = DOCUMENT) -> Path:
    """Write a document and apply it."""
    path = tmp_path / "demo.yaml"
    path.write_text(text)
    result = invoke("apply", str(path))
    assert result.exit_code == 0, result.output
    # An apply that reported success and stored nothing is the shape of a flake that only
    # shows up in whatever ran next. Fail here, where the evidence still is.
    listed = invoke("pipeline", "list", "--json")
    if "cli-demo" not in listed.output:
        # Reading again separates the two explanations: a row that appears on the second look
        # was committed and briefly invisible, and one that never appears was written
        # somewhere else.
        first_instance = only(invoke("system", "info", "--json").output, "system.info")["fields"]
        time.sleep(1.0)
        again = invoke("pipeline", "list", "--json")
        second_instance = only(invoke("system", "info", "--json").output, "system.info")["fields"]
        raise AssertionError(
            f"apply said it worked and the instance has nothing.\n"
            f"apply said: {result.output}\n"
            f"first list: {listed.output!r}\n"
            f"list a second later: {again.output!r}\n"
            f"DG_URL={os.environ.get('DG_URL')} expected database {tmp_path / 'dirigent.db'}\n"
            f"instance answering the first list: {first_instance!r}\n"
            f"instance answering the second: {second_instance!r}\n"
        )
    return path


def latest_run() -> str:
    """Read the newest run's id from the API."""
    listed = rows(invoke("runs", "list", "--json").stdout)
    assert listed, "no run was created"
    return str(listed[0]["id"])


def test_init_scaffolds_a_project_that_finds_itself(tmp_path: Path) -> None:
    result = invoke("init", str(tmp_path / "project"), "--documents-only")
    assert result.exit_code == 0
    assert "dirigent.yaml" in result.output
    project = find_project(tmp_path / "project")
    assert project is not None
    assert [path.name for path in project.documents()] == ["hello-world.yaml"]
    assert (tmp_path / "project" / ".dirigent" / "profiles.yaml").is_file()


def test_init_writes_a_uv_project_pinning_the_running_runtime(tmp_path: Path) -> None:
    import tomllib

    from dirigent_cli.commands import cli_version

    result = machine("init", str(tmp_path / "project"), "--documents-only", "--json")
    assert result.exit_code == 0, result.output
    scaffolded = of_kind(records(result.stdout), "project.scaffolded")[0]
    assert "pyproject.toml" in scaffolded["files"]
    assert "README.md" in scaffolded["files"]
    assert "skipped" not in scaffolded
    project = tomllib.loads((tmp_path / "project" / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == [f"dirigent-cli=={cli_version()}"]
    assert "tool" not in project, "dirigent-cli resolves from PyPI"


def test_init_leaves_an_existing_pyproject_alone_and_says_so(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "theirs"\n')
    result = machine("init", str(root), "--documents-only", "--json")
    assert result.exit_code == 0, result.output
    scaffolded = of_kind(records(result.stdout), "project.scaffolded")[0]
    assert scaffolded["skipped"] == ["pyproject.toml"]
    assert "pyproject.toml" not in scaffolded["files"]
    assert '"theirs"' in (root / "pyproject.toml").read_text()


def test_init_writes_a_working_config_and_a_reference_beside_it(tmp_path: Path) -> None:
    """The file someone edits stays short; the whole surface is one file away, and read-only."""
    assert invoke("init", str(tmp_path / "project"), "--documents-only").exit_code == 0
    working = (tmp_path / "project" / "dirigent.yaml").read_text()
    example = (tmp_path / "project" / "dirigent.example.yaml").read_text()
    assert "worker_concurrency: 8" in working
    assert "project:" in working, "the project block and the settings share one file"
    assert yaml.safe_load(example) is None, "every line of the reference is a comment"
    assert "# DIRIGENT_WORKER_CONCURRENCY" in example
    assert example.count("# DIRIGENT_") == len(Settings.model_fields)


def test_init_ignores_instance_state_and_leaves_the_profiles_committable(tmp_path: Path) -> None:
    assert invoke("init", str(tmp_path / "project"), "--documents-only").exit_code == 0
    ignore = tmp_path / "project" / ".dirigent" / ".gitignore"
    assert ignore.read_text().splitlines()[-1] == "state/"


def test_the_ci_template_adds_a_workflow(tmp_path: Path) -> None:
    result = invoke("init", str(tmp_path / "ci"), "--template", "ci", "--documents-only")
    assert result.exit_code == 0
    workflow = tmp_path / "ci" / ".github" / "workflows" / "dirigent.yml"
    assert workflow.is_file()
    assert "dg apply --dry-run" in workflow.read_text()


def test_init_refuses_a_short_password_before_writing_anything(tmp_path: Path) -> None:
    project = tmp_path / "short"
    result = machine("init", str(project), "--password", "short", "--json")
    assert result.exit_code == 1
    assert "at least 8" in only(result.stdout, "error")["message"]
    assert not project.exists(), "nothing is written for a password that would have been refused"


def test_init_never_overwrites(tmp_path: Path) -> None:
    scaffold(tmp_path / "twice")
    with pytest.raises(ProjectError, match="never overwrites"):
        scaffold(tmp_path / "twice")
    assert invoke("init", str(tmp_path / "twice"), "--documents-only").exit_code == 1


def test_an_unknown_template_is_refused(tmp_path: Path) -> None:
    result = invoke("init", str(tmp_path / "x"), "--template", "kubernetes")
    assert result.exit_code == 1
    assert "basic, ci and compose" in result.output


def test_the_scaffolded_example_validates_offline(tmp_path: Path) -> None:
    scaffold(tmp_path / "project")
    result = machine("validate", str(tmp_path / "project" / "pipelines" / "hello-world.yaml"))
    assert result.exit_code == 0
    assert only(result.stdout, "validation")["message"] == "valid"
    closed = closing(result.stdout)
    assert closed["kind"] == "validated"
    assert (closed["documents"], closed["invalid"]) == (1, 0)


def test_validate_reports_a_broken_document_with_its_problems(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("format: dirigent/v1\ncode: 'Not A Name'\nsteps: {}\n")
    result = machine("validate", str(path))
    assert result.exit_code == 1
    reported = only(result.stdout, "validation")
    assert reported["message"] == "invalid"
    assert reported["problems"], "a document that did not parse says what was wrong with it"
    assert closing(result.stdout)["invalid"] == 1


def test_validate_refuses_a_reference_that_will_never_resolve(tmp_path: Path, server: str) -> None:
    path = tmp_path / "refs.yaml"
    path.write_text(
        "format: dirigent/v1\ncode: refs\nsteps:\n"
        "  a: { block: shell.run, config: {argv: ['echo', '${params.nope}']} }\n"
    )
    result = machine("validate", str(path), "--server")
    assert result.exit_code == 1
    assert any("undeclared parameter" in one for one in only(result.stdout, "validation")["problems"])


def test_validate_with_a_server_checks_the_catalog(tmp_path: Path, server: str) -> None:
    path = tmp_path / "missing.yaml"
    path.write_text("format: dirigent/v1\ncode: missing\nsteps:\n  a: { block: nope.gone }\n")
    assert machine("validate", str(path)).exit_code == 0, "offline validation cannot see the catalog"
    result = machine("validate", str(path), "--server")
    assert result.exit_code == 1
    assert any("no block" in one for one in only(result.stdout, "validation")["problems"])
    assert only(result.stdout, "validation")["code"] == "missing"


def test_validate_outside_a_project_and_with_no_argument_says_so() -> None:
    result = machine("validate")
    assert result.exit_code == 1
    assert "dg init" in refusal(result.stdout)["message"]


def test_apply_creates_then_reports_unchanged(tmp_path: Path, server: str) -> None:
    path = apply_document(tmp_path)
    again = invoke("apply", str(path))
    assert again.exit_code == 0
    assert "unchanged" in again.output


def _project(tmp_path: Path, *codes: str) -> Path:
    """A project whose pipelines directory holds one document per code."""
    (tmp_path / "dirigent.yaml").write_text("project:\n  pipelines: pipelines\n")
    directory = tmp_path / "pipelines"
    directory.mkdir(exist_ok=True)
    for code in codes:
        (directory / f"{code}.yaml").write_text(DOCUMENT.replace("code: cli-demo", f"code: {code}"))
    return directory


def test_apply_prune_deactivates_what_the_project_no_longer_holds(tmp_path: Path, server: str) -> None:
    directory = _project(tmp_path, "keep-me", "drop-me")
    first = invoke("apply", "--prune")
    assert first.exit_code == 0, first.output
    (directory / "drop-me.yaml").unlink()

    second = invoke("apply", "--prune")

    assert second.exit_code == 0, second.output
    assert "deactivated" in second.output
    assert "drop-me" in second.output
    listed = invoke("--json", "pipeline", "list")
    active = {row["code"]: row["active"] for row in rows(listed.stdout)}
    assert active == {"keep-me": True, "drop-me": False}


def test_a_dry_run_prune_reports_and_writes_nothing(tmp_path: Path, server: str) -> None:
    directory = _project(tmp_path, "keep-me", "drop-me")
    assert invoke("apply", "--prune").exit_code == 0
    (directory / "drop-me.yaml").unlink()

    planned = invoke("apply", "--dry-run", "--prune")

    assert planned.exit_code == 0, planned.output
    assert "drop-me" in planned.output
    assert "dry run" in planned.output
    listed = invoke("--json", "pipeline", "list")
    active = {row["code"]: row["active"] for row in rows(listed.stdout)}
    assert active["drop-me"] is True


def test_prune_refuses_a_single_document(tmp_path: Path, server: str) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    result = machine("apply", str(path), "--prune")
    assert result.exit_code == 1
    assert "whole project" in refusal(result.stdout)["message"]


def test_apply_shows_a_diff_when_the_document_changed(tmp_path: Path, server: str) -> None:
    path = apply_document(tmp_path)
    path.write_text(DOCUMENT.replace("argv: [echo, goodbye]", "argv: [echo, so long]"))
    result = machine("apply", str(path))
    assert result.exit_code == 0
    plan = rows(result.stdout, "apply")[0]["plan"]
    assert plan["action"] == "update"
    assert plan["diff"]["steps_changed"] == ["farewell"]


def test_a_dry_run_writes_nothing(tmp_path: Path, server: str) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    result = machine("apply", str(path), "--dry-run")
    assert result.exit_code == 0
    assert rows(result.stdout, "apply")[0]["dry_run"] is True
    assert rows(machine("pipeline", "list").stdout) == [], "nothing was written"


def test_a_dry_run_draws_the_shape_it_would_install(tmp_path: Path, server: str) -> None:
    """A plan that says what changes is half of it; the other half is what the graph looks like."""
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    lines = [line.strip() for line in invoke("apply", str(path), "--dry-run").output.splitlines()]
    assert "greet  (shell.run)" in lines
    assert "farewell  (shell.run)" in lines
    assert lines.index("greet  (shell.run)") < lines.index("farewell  (shell.run)")


def test_validate_carries_the_shape_of_a_document_no_instance_has_seen(tmp_path: Path) -> None:
    """The record carries the graph, so the drawing is the formatter's and not the command's."""
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    reported = only(machine("validate", str(path)).stdout, "validation")
    assert [step["name"] for step in reported["steps"]] == ["greet", "farewell"]
    assert reported["steps"][0]["block"] == "shell.run"
    assert reported["steps"][1]["depends_on"] == ["greet"]


def test_apply_refuses_an_invalid_document_and_exits_non_zero(tmp_path: Path, server: str) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT.replace("shell.run", "nope.gone"))
    result = machine("apply", str(path))
    assert result.exit_code == 1
    assert rows(result.stdout, "apply")[0]["plan"]["action"] == "invalid"


def test_apply_can_rename_a_document(tmp_path: Path, server: str) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    result = machine("apply", str(path), "--as", "renamed")
    assert result.exit_code == 0
    assert rows(result.stdout, "apply")[0]["plan"]["code"] == "renamed"


def test_apply_reads_standard_input(tmp_path: Path, server: str) -> None:
    result = runner.invoke(app, ["apply", "-"], input=DOCUMENT)
    assert result.exit_code == 0
    assert rows(result.stdout, "apply")[0]["plan"]["code"] == "cli-demo"


def test_schema_stores_from_a_file_taking_its_code_from_the_id(tmp_path: Path, server: str) -> None:
    path = tmp_path / "org-unit.json"
    path.write_text('{"$id": "org-unit", "title": "Org unit", "type": "object"}')
    stored = invoke("schema", "create", str(path))
    assert stored.exit_code == 0, stored.output
    assert "org-unit" in stored.output
    listed = invoke("schema", "list", "--json")
    assert "org-unit" in listed.output
    shown = invoke("schema", "show", "org-unit")
    assert shown.exit_code == 0
    deleted = machine("schema", "delete", "org-unit")
    assert deleted.exit_code == 0, deleted.output
    assert only(deleted.stdout, "schema.deleted")["code"] == "org-unit"


def test_schema_takes_its_code_from_the_filename_when_there_is_no_id(tmp_path: Path, server: str) -> None:
    path = tmp_path / "reading.json"
    path.write_text('{"type": "object", "required": ["celsius"]}')
    stored = invoke("schema", "create", str(path))
    assert stored.exit_code == 0, stored.output
    assert "reading" in stored.output


def test_schema_create_refuses_a_body_that_is_not_a_schema(tmp_path: Path, server: str) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"$id": "broken", "type": "not-a-type"}')
    refused = invoke("schema", "create", str(path))
    assert refused.exit_code != 0


def test_apply_in_a_project_applies_every_document(tmp_path: Path, server: str) -> None:
    scaffold(tmp_path)
    (tmp_path / "pipelines" / "second.yaml").write_text(DOCUMENT)
    result = machine("apply")
    assert result.exit_code == 0
    assert {applied["plan"]["code"] for applied in rows(result.stdout, "apply")} == {"hello-world", "cli-demo"}


def test_apply_in_a_project_applies_pipelines_before_the_documents_that_schedule_them(
    tmp_path: Path, server: str
) -> None:
    """A triggers document naming an absent pipeline is refused, so ordering is the whole test."""
    scaffold(tmp_path)
    (tmp_path / "pipelines" / "second.yaml").write_text(DOCUMENT)
    # Sorts first by path, so only the ordering rule can make this converge in one apply.
    (tmp_path / "pipelines" / "a-clocks.yaml").write_text(
        "format: dirigent/v1\nkind: triggers\ncode: cli-clocks\npipeline: cli-demo\n"
        "triggers:\n  schedules:\n    - { code: ops-nightly, cron: '0 2 * * *' }\n"
    )

    result = invoke("apply")

    assert result.exit_code == 0, result.output
    assert "triggers for cli-demo" in plain(result.output)


def test_renaming_a_whole_project_is_refused(tmp_path: Path, server: str) -> None:
    scaffold(tmp_path)
    result = machine("apply", "--as", "everything")
    assert result.exit_code == 1
    assert "--as recodes one document" in refusal(result.stdout)["message"]


def test_apply_json_prints_the_servers_own_response(tmp_path: Path, server: str) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    result = invoke("apply", str(path), "--json")
    assert result.exit_code == 0
    assert rows(result.stdout)[0]["plan"]["action"] == "create"


def test_export_round_trips_back_through_apply(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    exported = invoke("export", "cli-demo", "-f", str(tmp_path / "out.yaml"))
    assert exported.exit_code == 0
    text = (tmp_path / "out.yaml").read_text()
    assert text.startswith("format: dirigent/v1\n")
    again = machine("apply", str(tmp_path / "out.yaml"))
    assert rows(again.stdout, "apply")[0]["plan"]["action"] == "unchanged"


def test_export_refuses_a_pipeline_that_does_not_exist(server: str) -> None:
    result = machine("export", "nobody-home")
    assert result.exit_code == 1
    assert "no pipeline" in refusal(result.stdout)["message"]


def test_the_pipeline_group_lists_shows_and_versions(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    listing = invoke("pipeline", "list")
    assert "cli-demo" in listing.output
    shown = invoke("pipeline", "show", "cli-demo")
    assert "greet  (shell.run)" in shown.output
    assert "  farewell  (shell.run)" in shown.output, "the dependent is drawn under what it waits for"
    versions = invoke("pipeline", "versions", "cli-demo")
    assert "tester" in versions.output


def test_the_pipeline_listing_shows_tags_and_narrows_by_them(tmp_path: Path, server: str) -> None:
    """`--tag` is the server's own filter, so the rows it leaves out never reach the CLI."""
    apply_document(tmp_path)
    labelled = tmp_path / "labelled.yaml"
    labelled.write_text(
        "format: dirigent/v1\ncode: cli-labelled\ndescription: A tagged pipeline.\n"
        "tags: [climate, http]\nsteps:\n  greet:\n    block: shell.run\n    config: { argv: [echo, hi] }\n"
    )
    assert invoke("apply", str(labelled)).exit_code == 0

    listing = invoke("pipeline", "list")
    assert "climate" in listing.output and "cli-demo" in listing.output

    listed = rows(invoke("pipeline", "list", "--json").stdout)
    assert {row["code"]: row["tags"] for row in listed} == {"cli-demo": [], "cli-labelled": ["climate", "http"]}

    narrowed = rows(invoke("pipeline", "list", "--tag", "climate", "--json").stdout)
    assert [row["code"] for row in narrowed] == ["cli-labelled"]
    assert rows(invoke("pipeline", "list", "--tag", "climate", "--tag", "acme", "--json").stdout) == []


def test_the_runs_listing_narrows_by_the_tags_the_runs_pipeline_wears(tmp_path: Path, server: str) -> None:
    """`dg runs --tag nightly --status failed` is one question, and this is its tag half."""
    apply_document(tmp_path)
    labelled = tmp_path / "labelled.yaml"
    labelled.write_text(
        "format: dirigent/v1\ncode: cli-labelled\ndescription: A tagged pipeline.\n"
        "tags: [climate, http]\nsteps:\n  greet:\n    block: shell.run\n    config: { argv: [echo, hi] }\n"
    )
    assert invoke("apply", str(labelled)).exit_code == 0
    assert invoke("run", "cli-demo").exit_code == 0
    assert invoke("run", "cli-labelled").exit_code == 0

    def pipelines_of(*tags: str) -> list[str]:
        named = [word for tag in tags for word in ("--tag", tag)]
        listed = rows(invoke("runs", "list", *named, "--json").stdout)
        return [row["pipeline"] for row in listed]

    assert sorted(pipelines_of()) == ["cli-demo", "cli-labelled"]
    assert pipelines_of("climate") == ["cli-labelled"]
    assert pipelines_of("climate", "http") == ["cli-labelled"], "a repeated tag narrows rather than widens"
    assert pipelines_of("climate", "acme") == []


def test_a_stored_pipeline_is_re_checked_against_the_instance(tmp_path: Path, server: str) -> None:
    """A pipeline that applied cleanly is checked again, on demand, against what is here now."""
    apply_document(tmp_path)
    valid = invoke("pipeline", "validate", "cli-demo")
    assert valid.exit_code == 0, valid.output
    assert "valid" in plain(valid.output)

    every = invoke("pipeline", "validate", "--all")
    assert every.exit_code == 0, every.output
    assert "cli-demo" in plain(every.output)

    named = invoke("pipeline", "validate", "cli-demo", "--version", "1")
    assert named.exit_code == 0, named.output


def test_validating_every_pipeline_takes_no_name(tmp_path: Path, server: str) -> None:
    """--all is a sweep, so a name or a version alongside it is a contradiction."""
    apply_document(tmp_path)
    refused = invoke("pipeline", "validate", "cli-demo", "--all")
    assert refused.exit_code != 0
    assert "neither a code nor a version" in plain(refused.output)
    assert "name a pipeline" in plain(invoke("pipeline", "validate").output)


def test_a_stored_pipeline_that_names_a_deleted_connection_is_reported(tmp_path: Path, server: str) -> None:
    """This is the drift it exists for: it applied cleanly, and now it could not run."""
    document = DOCUMENT.replace(
        "  greet:\n    block: shell.run",
        "  greet:\n    block: http.request\n    config: {connection: gone, path: /}\n  unused:\n    block: shell.run",
    )
    path = tmp_path / "drifted.yaml"
    path.write_text(document)
    invoke("connection", "create", "http", "gone", "--set", "base_url=https://example.org")
    assert invoke("apply", str(path)).exit_code == 0, "it applies while the connection exists"

    assert invoke("connection", "delete", "gone").exit_code == 0
    checked = invoke("pipeline", "validate", "cli-demo")
    assert checked.exit_code == 1, checked.output
    printed = plain(checked.output)
    assert "invalid" in printed
    assert "gone" in printed, "it names the connection that went missing"


def test_a_pipeline_can_be_deactivated_activated_and_deleted(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    off = machine("pipeline", "deactivate", "cli-demo")
    assert only(off.stdout, "pipeline.deactivated")["code"] == "cli-demo"
    assert invoke("run", "cli-demo").exit_code == 1
    on = machine("pipeline", "activate", "cli-demo")
    assert only(on.stdout, "pipeline.activated")["code"] == "cli-demo"
    gone = machine("pipeline", "delete", "cli-demo")
    assert only(gone.stdout, "pipeline.deleted")["code"] == "cli-demo"


def test_deleting_a_pipeline_takes_its_run_history_with_it(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    # A run still in flight refuses the delete, and nothing here claims work, so settle it.
    assert machine("runs", "cancel", latest_run()).exit_code == 0
    assert only(machine("pipeline", "delete", "cli-demo").stdout, "pipeline.deleted")["runs"] == "deleted"
    gone = invoke("pipeline", "delete", "cli-demo")
    assert gone.exit_code == 1, "the pipeline and its runs are gone, so a second delete finds nothing"


def test_a_run_is_started_and_shown(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    started = invoke("run", "cli-demo", "-p", 'greeting="hi"')
    assert started.exit_code == 0
    shown = invoke("runs", "show", latest_run())
    assert "cli-demo" in shown.output
    assert "greet" in shown.output
    assert "farewell" in shown.output


def test_showing_a_run_composes_one_document_out_of_the_paged_sub_resources(tmp_path: Path, server: str) -> None:
    """The wire pages the grids; what a script reads off ``runs show --json`` is still whole."""
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    document = only(invoke("runs", "show", latest_run(), "--json").output, "run.detail")["fields"]

    assert set(document) == {
        "run",
        "dag",
        "items",
        "attempts",
        "items_total",
        "attempts_total",
        "waiting_for_workers",
    }
    assert document["run"]["pipeline"] == "cli-demo"
    assert [node["code"] for node in document["dag"]["nodes"]] == ["greet", "farewell"]
    assert [row["step_name"] for row in document["attempts"]] == ["greet", "farewell"]
    assert document["items"] == []
    assert (document["attempts_total"], document["items_total"]) == (2, 0)


def test_showing_a_run_says_where_each_steps_time_went(tmp_path: Path, server: str) -> None:
    """A reader can tell queued time from running time without doing the subtraction."""
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    document = only(invoke("runs", "show", latest_run(), "--json").output, "run.detail")["fields"]

    split = {"queued_ms", "running_ms", "waiting_ms"}
    assert all(split <= set(node) for node in document["dag"]["nodes"])
    assert all(split <= set(attempt) for attempt in document["attempts"])
    first = document["attempts"][0]
    assert first["created_at"] is not None and first["running_ms"] >= 0
    assert first["queued_ms"] + first["running_ms"] + first["waiting_ms"] >= 0


def test_profiling_a_run_records_the_critical_path_and_the_split_along_it(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    stream = records(invoke("runs", "profile", latest_run(), "--json").stdout)

    [measured] = of_kind(stream, "run.profile")
    assert measured["critical_path"] == ["greet", "farewell"], "farewell waited for greet, so both decided the run"
    assert measured["pipeline"] == "cli-demo"
    steps = of_kind(stream, "run.profile.step")
    assert [row["step"] for row in steps] == ["greet", "farewell"]
    assert all(row["attempts"] == 1 for row in steps)
    assert all({"queued_ms", "running_ms", "waiting_ms"} <= set(row) for row in steps)
    assert of_kind(stream, "run.profile.warning") == [], "two shell steps prove nothing worth warning about"


def test_log_levels_read_bare_and_patterned_forms_with_the_later_repeat_winning() -> None:
    from dirigent_cli.commands import parse_log_levels
    from dirigent_client.enums import LogLevel

    assert parse_log_levels(None) is None
    assert parse_log_levels([]) is None
    assert parse_log_levels(["debug"]) == {"*": LogLevel.DEBUG}
    assert parse_log_levels(["acme.*=debug"]) == {"acme.*": LogLevel.DEBUG}
    assert parse_log_levels(["warning", "acme.*=DEBUG"]) == {"*": LogLevel.WARNING, "acme.*": LogLevel.DEBUG}
    assert parse_log_levels(["*=info", "*=debug"]) == {"*": LogLevel.DEBUG}


def test_a_log_level_that_is_not_one_is_refused_naming_the_piece() -> None:
    import click
    import typer

    from dirigent_cli.commands import parse_log_levels

    for value in (["loud"], ["acme.*=loud"], ["=debug"]):
        try:
            parse_log_levels(value)
        except (typer.Exit, click.exceptions.Exit, SystemExit):
            continue
        raise AssertionError(f"{value!r} was not refused")


def test_a_window_is_read_off_one_flag_as_two_instants() -> None:
    from dirigent_cli.commands import read_window

    assert read_window("2026-06-01T00:00:00Z..2026-06-02T00:00:00Z") == (
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    assert read_window("2026-06-01..2026-06-02") == (
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 2, tzinfo=UTC),
    ), "an instant with no offset is read as UTC, because the flag names no zone"
    assert read_window("2026-06-01T00:00:00+02:00..2026-06-02T00:00:00+02:00")[0].utcoffset() == timedelta(hours=2)


def test_a_window_that_is_not_two_instants_separated_by_two_dots_is_refused() -> None:
    from dirigent_cli.commands import ParamError, read_window

    for value in ("2026-06-01", "2026-06-01,2026-06-02", "yesterday..today", "..2026-06-02"):
        with pytest.raises(ParamError, match="ISO 8601"):
            read_window(value)


def test_a_window_that_runs_backwards_or_covers_nothing_is_refused() -> None:
    from dirigent_cli.commands import ParamError, read_window

    for value in ("2026-06-02..2026-06-01", "2026-06-01..2026-06-01"):
        with pytest.raises(ParamError, match="runs forwards and covers something"):
            read_window(value)


def test_dg_run_carries_the_window_it_was_given_onto_the_run(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)

    started = invoke("run", "cli-demo", "--window", "2026-06-01..2026-06-02")

    assert started.exit_code == 0, started.output
    run = only(invoke("runs", "show", latest_run(), "--json").output, "run.detail")["fields"]["run"]
    assert run["window_start"] == "2026-06-01T00:00:00Z"
    assert run["window_end"] == "2026-06-02T00:00:00Z"


def test_dg_run_refuses_a_backwards_window_before_it_calls_the_server(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)

    refused = invoke("run", "cli-demo", "--window", "2026-06-02..2026-06-01")

    assert refused.exit_code == 1
    assert "runs forwards and covers something" in plain(refused.output)
    assert rows(invoke("runs", "list", "--json").stdout) == []


def test_dg_backfill_writes_one_record_carrying_every_window_it_filled(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path, DOCUMENT + SCHEDULE)

    result = invoke(
        "backfill",
        "cli-demo",
        "--schedule",
        "nightly",
        "--from",
        "2026-06-01T05:00:00Z",
        "--to",
        "2026-06-04T05:00:00Z",
        "--json",
    )

    assert result.exit_code == 0, result.output
    filled = of_kind(records(result.output), "backfill")
    assert len(filled) == 1, "one record for the whole backfill, carrying the windows"
    assert filled[0]["message"] == "created"
    assert (filled[0]["windows_total"], filled[0]["runs_created"]) == (3, 3)
    assert [one["window_end"] for one in filled[0]["windows"]] == [
        "2026-06-01T05:00:00Z",
        "2026-06-02T05:00:00Z",
        "2026-06-03T05:00:00Z",
    ]
    assert all(one["run_id"] for one in filled[0]["windows"])


def test_dg_backfill_dry_run_plans_the_same_windows_and_creates_no_run(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path, DOCUMENT + SCHEDULE)

    result = invoke(
        "backfill",
        "cli-demo",
        "--schedule",
        "nightly",
        "--from",
        "2026-06-01T05:00:00Z",
        "--to",
        "2026-06-04T05:00:00Z",
        "--dry-run",
        "--json",
    )

    assert result.exit_code == 0, result.output
    planned = of_kind(records(result.output), "backfill")[0]
    assert planned["message"] == "planned"
    assert planned["dry_run"] is True
    assert (planned["windows_total"], planned["runs_created"]) == (3, 0)
    assert rows(invoke("runs", "list", "--json").stdout) == []


def test_dg_backfill_renders_its_windows_as_a_table_for_a_person(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path, DOCUMENT + SCHEDULE)

    result = invoke(
        "backfill",
        "cli-demo",
        "--schedule",
        "nightly",
        "--from",
        "2026-06-01T05:00:00Z",
        "--to",
        "2026-06-03T05:00:00Z",
        "--dry-run",
    )

    printed = plain(result.output)
    assert "window start" in printed and "window end" in printed
    assert "2026-06-01T05:00:00Z" in printed


def test_dg_backfill_refuses_an_interval_that_covers_nothing(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path, DOCUMENT + SCHEDULE)

    refused = invoke(
        "backfill",
        "cli-demo",
        "--schedule",
        "nightly",
        "--from",
        "2026-06-04T05:00:00Z",
        "--to",
        "2026-06-01T05:00:00Z",
    )

    assert refused.exit_code == 1
    assert "runs forwards and covers something" in plain(refused.output)


def test_parameters_are_coerced_by_the_schema_they_are_going_to() -> None:
    from dirigent_cli.commands import parse_params

    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "code": {"type": "string"},
            "regions": {"type": "array", "items": {"type": "string"}},
        },
    }
    assert parse_params(["count=3"], schema=schema) == {"count": 3}
    assert parse_params(["code=3"], schema=schema) == {"code": "3"}
    assert parse_params(["regions=[east, west]"], schema=schema) == {"regions": ["east", "west"]}


def test_a_malformed_parameter_is_refused(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    result = invoke("run", "cli-demo", "-p", "nonsense")
    assert result.exit_code == 1
    assert "key=value" in plain(result.output)


def test_a_run_can_be_listed_cancelled_and_reported(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    run_id = latest_run()
    assert "cli-demo" in invoke("runs", "list").output
    cancelled = only(machine("runs", "cancel", run_id).stdout, "run.cancelled")
    assert cancelled["run_id"] == run_id
    assert cancelled["status"] == "cancelled"
    report = invoke("runs", "report", run_id)
    assert "cli-demo" in report.output
    assert invoke("runs", "logs", run_id).exit_code == 0


def test_a_listing_follows_its_cursor_without_the_caller_seeing_one() -> None:
    """``paged`` is what makes paging invisible: it walks until the total limit or the end."""
    from dirigent_cli.commands import MAX_PAGE, paged
    from dirigent_client import Page

    pages = {
        None: Page[str](items=["a", "b"], next="b"),
        "b": Page[str](items=["c"], next=None),
    }
    asked: list[tuple[str | None, int]] = []

    def fetch(after: str | None, size: int) -> Page[str]:
        asked.append((after, size))
        return pages[after]

    assert list(paged(fetch, None)) == ["a", "b", "c"]
    assert asked == [(None, MAX_PAGE), ("b", MAX_PAGE)], "the cursor is passed back verbatim"

    asked.clear()
    assert list(paged(fetch, 2)) == ["a", "b"], "the caller's limit bounds the total"
    assert asked == [(None, 2)], "and a bounded walk asks for no more than it needs"


def test_retrying_a_step_that_never_failed_is_refused(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    result = machine("runs", "retry", latest_run(), "--step", "greet")
    assert result.exit_code == 1
    assert "no settled failure" in refusal(result.stdout)["message"]


def test_a_retried_step_says_which_attempt_it_queued(tmp_path: Path, server: str) -> None:
    """A retry is read by whoever asked for it, so the attempt it minted is a record."""
    import sqlite3
    from contextlib import closing

    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    # No worker runs here, so the attempt is settled as failed the way one would have.
    with closing(sqlite3.connect(tmp_path / "dirigent.db")) as database:
        database.execute("update step_attempts set status = 'failed' where step_name = 'greet'")
        database.commit()

    result = machine("runs", "retry", latest_run(), "--step", "greet")

    assert result.exit_code == 0, result.output
    retried = only(result.stdout, "run.retried")
    assert retried["message"] == "queued"
    assert retried["step"] == "greet"
    assert retried["attempt"] == 2


def test_the_catalog_is_listed_and_described(server: str) -> None:
    listed = invoke("blocks", "list")
    assert "http.request" in listed.output
    assert "storage.copy" in listed.output
    shown = invoke("blocks", "show", "storage.copy")
    assert "source" in shown.output and "target" in shown.output
    assert invoke("blocks", "show", "nope.gone").exit_code == 1


def test_blocks_can_be_filtered_to_sensors(server: str) -> None:
    sensors = invoke("blocks", "list", "--kind", "sensor")
    assert "storage.exists" in sensors.output
    assert "storage.copy" not in sensors.output


def test_a_connection_is_created_shown_checked_and_deleted(server: str) -> None:
    created = invoke(
        "connection",
        "create",
        "http",
        "ops-api",
        "--set",
        "base_url=https://ops.example.org",
        "--set",
        "bearer_token=hunter2",
    )
    assert created.exit_code == 0
    listed = invoke("connection", "list")
    assert "ops-api" in listed.output
    shown = invoke("connection", "show", "ops-api")
    assert "https://ops.example.org" in shown.output
    assert "hunter2" not in shown.output, "a secret must never be printed"
    assert "***" in shown.output
    deleted = machine("connection", "delete", "ops-api")
    assert deleted.exit_code == 0
    assert only(deleted.stdout, "connection.deleted")["code"] == "ops-api"


def test_creating_a_connection_states_what_it_made_with_the_secret_redacted(server: str) -> None:
    """The fact a create writes carries the row it made, and never the credential in it."""
    created = machine(
        "connection",
        "create",
        "s3",
        "archive",
        "--set",
        "endpoint_url=http://s3.example.org",
        "--set",
        "bucket=archive",
        "--set",
        "secret_access_key=a-secret-key",
    )
    assert created.exit_code == 0, created.output
    assert "a-secret-key" not in created.output, "a secret is never emitted"
    made = only(created.stdout, "connection.created")
    assert (made["code"], made["connection_kind"], made["message"]) == ("archive", "s3", "created")
    assert made["config"]["bucket"] == "archive"
    assert made["config"]["secret_access_key"] == "***"


def test_creating_a_connection_of_an_unknown_kind_is_refused(server: str) -> None:
    result = machine("connection", "create", "nope", "x", "--set", "base_url=https://x")
    assert result.exit_code == 1
    assert "no connection kind" in refusal(result.stdout)["message"]


def test_system_info_and_the_worker_registry(server: str) -> None:
    info = invoke("system", "info")
    assert "sqlite" in info.output
    assert "shell.run" in info.output
    assert invoke("system", "workers").exit_code == 0


def test_a_minted_bearer_token_survives_the_json_output(server: str) -> None:
    """It is shown once, so the spelling a script asked for must not swallow it."""
    result = invoke("--json", "admin", "token", "create", "scripted")
    assert result.exit_code == 0, result.output
    minted = only(result.stdout, "token.issued")
    assert minted["token"], "a script that minted a token can read it"
    assert minted["name"] == "scripted"


def test_tokens_and_users_and_auth_status(server: str) -> None:
    created = invoke("admin", "token", "create", "ci")
    assert created.exit_code == 0
    assert "only time" in created.output
    assert "ci" in invoke("admin", "token", "list").output
    assert only(machine("admin", "token", "revoke", "ci").stdout, "token.revoked")["code"] == "ci"
    assert "tester" in invoke("admin", "user", "list").output
    status = machine("auth", "status")
    assert status.exit_code == 0, status.output
    said = only(status.stdout, "auth")
    assert said["message"] == "authenticated"
    assert said["username"] == "tester"
    assert said["role"] == "admin"
    assert said["url"] and said["source"] and said["via"]


def test_creating_an_account_without_a_role_is_refused(server: str) -> None:
    """There is no default, so nothing becomes an admin by leaving the option out."""
    result = invoke("admin", "user", "create", "second", "--password", "another password")
    assert result.exit_code != 0


def test_a_token_is_minted_and_revoked_for_another_account(server: str) -> None:
    """--user is what makes a token belong to someone other than the caller."""
    assert (
        invoke("admin", "user", "create", "second", "--role", "operator", "--password", "another password").exit_code
        == 0
    )
    minted = only(machine("admin", "token", "create", "ci", "--user", "second").stdout, "token.issued")
    assert minted["username"] == "second"
    assert minted["name"] == "ci"
    listed = {(row["username"], row["name"]) for row in rows(machine("admin", "token", "list").stdout)}
    assert ("second", "ci") in listed
    revoked = only(machine("admin", "token", "revoke", "ci", "--user", "second").stdout, "token.revoked")
    assert revoked["code"] == "ci"
    assert revoked["username"] == "second"


def test_an_admin_resets_another_accounts_password(server: str) -> None:
    assert (
        invoke("admin", "user", "create", "second", "--role", "operator", "--password", "another password").exit_code
        == 0
    )
    reset = only(
        machine("admin", "user", "password", "second", "--password", "a third password").stdout, "password.reset"
    )
    assert reset["message"] == "reset"
    assert reset["username"] == "second"
    assert reset["sessions"] == "revoked"


def test_auth_status_without_a_token_refuses_rather_than_saying_nothing(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scripted status with no token has to say so on the stream it is read on."""
    monkeypatch.delenv("DG_TOKEN", raising=False)

    result = machine("auth", "status")

    assert result.exit_code == 1
    assert "no token" in refusal(result.stdout)["message"]


def test_logging_in_needs_no_token_even_where_a_profile_names_one(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scaffolded profile reads DG_TOKEN, and login is how that token comes to exist."""
    project = tmp_path / "stack"
    assert invoke("init", str(project), "--template", "compose", "--password", "a test password").exit_code == 0
    monkeypatch.chdir(project)
    monkeypatch.delenv("DG_TOKEN")
    result = machine("auth", "login", "--username", "tester", "--password", "a test password")
    assert result.exit_code == 0, result.output
    assert only(result.stdout, "token.issued")["token"]


def test_logging_in_hands_over_the_token_it_minted(server: str) -> None:
    """A scripted login exits 0 and shows nothing unless the token is on the stream."""
    result = machine("auth", "login", "--username", "tester", "--password", "a test password")

    assert result.exit_code == 0, result.output
    issued = only(result.stdout, "token.issued")
    assert issued["message"] == "logged in"
    assert issued["username"] == "tester"
    assert issued["token"], "the token the login minted is lost unless the record carries it"
    assert issued["url"]


def test_the_rendered_login_shows_the_token_once(server: str) -> None:
    """The console spells it as the export a person pastes, and never twice."""
    result = invoke("auth", "login", "--username", "tester", "--password", "a test password")

    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "export DG_TOKEN=" in text
    assert "only time" in text
    assert text.count("token=") == 0, "the line does not carry the secret the rendering hands over"


def test_an_account_is_switched_off_and_back_on_from_the_cli(server: str) -> None:
    """The two commands an admin screen needs are the two the CLI has parity for."""
    assert (
        invoke("admin", "user", "create", "second", "--role", "operator", "--password", "another password").exit_code
        == 0
    )
    off = invoke("--json", "admin", "user", "deactivate", "second")
    assert off.exit_code == 0, off.output
    assert [row["active"] for row in rows(off.stdout)] == [False]
    on = invoke("--json", "admin", "user", "activate", "second")
    assert [row["active"] for row in rows(on.stdout)] == [True]


def test_the_last_active_admin_is_not_switched_off_from_the_cli(server: str) -> None:
    refused = invoke("admin", "user", "deactivate", "tester")
    assert refused.exit_code == 1
    assert "only active admin" in refused.output


def test_a_person_changes_their_own_password_from_the_cli(server: str) -> None:
    changed = machine("auth", "password", "--current", "a test password", "--new", "a longer new password")
    assert changed.exit_code == 0, changed.output
    assert only(changed.stdout, "password.changed")["other_sessions"] == "revoked"
    assert invoke("admin", "user", "list").exit_code == 0, "the api token this ran on still works"


def test_a_listing_is_one_record_per_row_rather_than_a_table(server: str) -> None:
    listed = invoke("blocks", "list", "--json")
    stream = records(listed.stdout)
    assert {record["kind"] for record in stream} == {"block", "storage_scheme", "connection_kind"}
    assert {block["id"] for block in rows(listed.stdout, "block")} >= {"shell.run"}
    assert rows(invoke("system", "workers", "--json").stdout) == []


def test_an_unreachable_server_says_so_rather_than_traces_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DG_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DG_TOKEN", "irrelevant")
    result = machine("pipeline", "list")
    assert result.exit_code == 1
    refused = refusal(result.stdout)
    assert "cannot reach" in refused["message"]
    assert any("dg dev" in problem for problem in refused["problems"]), (
        "a refused loopback connection does not say the local instance is not running"
    )


def test_an_unreachable_remote_server_gets_no_local_advice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DG_URL", "http://198.51.100.9:9")
    monkeypatch.setenv("DG_TOKEN", "irrelevant")
    result = machine("pipeline", "list")
    assert result.exit_code == 1
    assert refusal(result.stdout).get("problems", []) == []


def test_an_unauthenticated_cli_is_told_to_get_a_token(server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DG_TOKEN")
    result = machine("pipeline", "list")
    assert result.exit_code == 1
    assert "authentication required" in refusal(result.stdout)["message"]


def test_init_initialises_an_instance_that_dg_dev_can_run(tmp_path: Path) -> None:
    """The default is an instance: a migrated database with an admin, beside the documents."""
    root = tmp_path / "instance"

    result = invoke("init", str(root), "--password", "a test password")

    assert result.exit_code == 0, result.output
    state = root / ".dirigent" / "state"
    assert (state / "dirigent.db").is_file(), "no database was created"
    assert (root / "pipelines" / "hello-world.yaml").is_file(), "the documents were not written"
    assert "admin" in result.output and "token" in result.output


def test_init_puts_the_token_where_the_local_profile_reads_it(tmp_path: Path) -> None:
    """The token lands in the project's .env, so no shell has to export it."""
    root = tmp_path / "instance"

    result = machine("init", str(root), "--password", "a test password", "--json")

    assert result.exit_code == 0, result.output
    initialised = only(result.stdout, "instance.initialised")
    assert ".env" in initialised["files"]
    assert f"DG_TOKEN={initialised['token']}" in (root / ".env").read_text().splitlines()
    assert ".env" in (root / ".gitignore").read_text().splitlines()
    endpoint = resolve_endpoint(start=root, environ={})
    assert endpoint.token == initialised["token"]
    assert endpoint.profile == "local"


def test_a_plain_dev_start_keeps_the_instance_init_made(tmp_path: Path) -> None:
    """A plain dg dev after dg init runs that instance: its admin stays, no development admin is made."""
    root = tmp_path / "instance"
    result = machine("init", str(root), "--password", "a test password", "--json")
    assert result.exit_code == 0, result.output
    settings = instance_settings(root)

    admin, token = asyncio.run(dev_admin(settings))

    assert admin == "admin", "the admin dg init made is the one dg dev names"
    assert token is None, "the token was handed over by dg init, so dg dev mints none"
    assert (root / ".dirigent" / "state" / "dirigent.db").is_file()


def test_init_shows_the_token_once_and_says_where_it_lives(tmp_path: Path) -> None:
    """The rendering hands the token over, names .env, and spells the two terminals apart."""
    result = invoke("init", str(tmp_path / "instance"), "--password", "a test password")

    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert ".env" in text
    assert "second terminal" in text
    assert "http://127.0.0.1:3333" in text


def test_init_says_what_this_instance_is_not(tmp_path: Path) -> None:
    """It is one person's SQLite instance, and somebody has to be told a real server is not."""
    result = invoke("init", str(tmp_path / "instance"), "--password", "a test password")

    assert "compose" in plain(result.output)


def test_init_refuses_to_clobber_an_instance_that_is_already_there(tmp_path: Path) -> None:
    """Migrating and re-admining a live database is not what running init twice means.

    The documents are removed first, so scaffolding would succeed and only the instance
    stands in the way: without the guard this migrates and re-admins a live database.
    """
    root = tmp_path / "instance"
    assert invoke("init", str(root), "--password", "a test password").exit_code == 0
    for path in (root / "dirigent.yaml", root / "dirigent.example.yaml", root / "pipelines" / "hello-world.yaml"):
        path.unlink()
    (root / ".dirigent" / "profiles.yaml").unlink()
    (root / ".dirigent" / ".gitignore").unlink()

    again = invoke("init", str(root), "--password", "another password")

    assert again.exit_code == 1
    assert "dirigent.db" in plain(again.output), "the refusal names the instance, not a document"


def test_documents_only_writes_no_database(tmp_path: Path) -> None:
    """The old behaviour is still available, and it is what the flag now names."""
    root = tmp_path / "documents"

    result = invoke("init", str(root), "--documents-only")

    assert result.exit_code == 0, result.output
    assert not (root / ".dirigent" / "state" / "dirigent.db").exists()
    assert (root / "pipelines" / "hello-world.yaml").is_file()


def test_init_refuses_when_it_has_no_password_and_cannot_ask(tmp_path: Path) -> None:
    """A prompt in a pipe blocks forever, so say how to give one instead."""
    result = invoke("init", str(tmp_path / "instance"))

    assert result.exit_code == 1
    assert "DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD" in plain(result.output)


def test_every_single_read_answers_with_a_record_naming_its_kind(tmp_path: Path, server: str) -> None:
    """A command that answers with one thing is still a record stream a reader dispatches on."""
    apply_document(tmp_path)
    assert invoke("run", "cli-demo").exit_code == 0
    run_id = latest_run()
    schema = tmp_path / "org-unit.json"
    schema.write_text('{"$id": "org-unit", "title": "Org unit", "type": "object"}')
    assert machine("schema", "create", str(schema)).exit_code == 0
    assert (
        machine("connection", "create", "http", "ops-api", "--set", "base_url=https://ops.example.org").exit_code == 0
    )

    reads = [
        ("pipeline", "show", "cli-demo"),
        ("export", "cli-demo"),
        ("runs", "show", run_id),
        ("runs", "report", run_id),
        ("blocks", "show", "storage.copy"),
        ("connection", "show", "ops-api"),
        ("schema", "show", "org-unit"),
        ("system", "info"),
        ("admin", "token", "create", "scripted"),
    ]
    for argv in reads:
        result = machine(*argv)
        assert result.exit_code == 0, f"{argv}: {result.output}"
        written = records(result.stdout)
        assert written, f"{argv} wrote nothing"
        for record in written:
            assert isinstance(record, dict), f"{argv} wrote a line that is not an object"
            assert record.get("kind"), f"{argv} wrote a record with no kind: {record}"
