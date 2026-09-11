"""``dg run --local``: apply and run a document with no server, and say what happened."""

import asyncio
import re
import shutil
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typer.testing import CliRunner

from clisupport import (
    LINE,
    asking_for_the_rendering,
    closing,
    messages,
    of_kind,
    plain,
    records,
    refusal,
)
from dirigent_cli import local
from dirigent_cli.commands import GUARD_EXIT, split_unsafe
from dirigent_cli.local import (
    LOCAL_LOG_PAGE,
    POLL_CEILING,
    POLL_SECONDS,
    POLL_WIDEN,
    ConnectionSpec,
    LocalError,
    SchemaSpec,
    _drive,  # pyright: ignore[reportPrivateUsage] - the poll this suite measures
    _new_logs,  # pyright: ignore[reportPrivateUsage] - the read this suite measures
    connections_for,
    load_connection_specs,
    load_schema_specs,
    schemas_for,
)
from dirigent_cli.main import app, hoist_globals
from dirigent_client.enums import LogLevel
from dirigent_core.config import CONFIG_FILE_ENV, Settings, reset_settings_cache
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.documents import load_pipeline_text as load_text
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Base, LogEntry
from dirigent_core.plugins import load_plugin_host
from dirigent_core.protocol import parse

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"

HELLO = """
format: dirigent/v1
kind: pipeline
code: local-hello
description: One shell step, run with no server anywhere.
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, "hello from a local run"]
"""

FAILING = """
format: dirigent/v1
kind: pipeline
code: local-failure
description: One step that cannot possibly work.
steps:
  copy_nothing:
    block: storage.copy
    config:
      source: "${run.scratch}/missing.json"
      target: "${run.scratch}/copy.json"
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Give every local run its own configuration, with no ambient allowlist."""
    config = tmp_path / "settings.yaml"
    config.write_text("enabled_unsafe_blocks: []\n")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    monkeypatch.delenv("DG_URL", raising=False)
    monkeypatch.delenv("DG_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    yield
    reset_settings_cache()


def invoke(*argv: str) -> Any:
    """Run one command and return its result, hoisting global options as the entry point does."""
    return runner.invoke(app, hoist_globals(list(argv)))


def rendering(*argv: str) -> Any:
    """Run one command asking for the console rendering, for a test that reads the drawing."""
    return runner.invoke(app, asking_for_the_rendering(hoist_globals(list(argv))))


def write(tmp_path: Path, text: str, name: str = "document.yaml") -> Path:
    """Write a document to run."""
    path = tmp_path / name
    path.write_text(text)
    return path


def test_a_document_is_applied_and_run_with_no_server(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 0, result.output
    end = closing(result.stdout)
    assert end["kind"] == "run"
    assert end["message"] == "succeeded"
    assert [step["step"] for step in end["steps"]] == ["greet"]


def test_step_transitions_are_streamed_not_only_the_outcome(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert messages(result.stdout, "step") == ["queued", "succeeded"]


def test_a_failure_carries_the_diagnosis_before_the_database_is_discarded(tmp_path: Path) -> None:
    """The database is deleted on the way out, so the closing record is the only diagnosis."""
    result = invoke("run", "--local", str(write(tmp_path, FAILING)))
    assert result.exit_code == 1
    end = closing(result.stdout)
    assert end["kind"] == "run"
    assert end["message"] == "failed"
    failure = end["failures"][0]
    assert failure["step"] == "copy_nothing"
    assert failure["block"] == "storage.copy"
    assert failure["attempt"] == 1
    assert "missing.json" in (failure["error"] or ""), "the error must name what could not be found"


def test_an_unsafe_block_is_refused_cleanly(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)))
    assert result.exit_code == GUARD_EXIT
    refused = refusal(result.stdout)
    assert refused["status"] == GUARD_EXIT
    assert "executes code on the worker" in refused["message"]
    assert "Traceback" not in result.output


def test_the_remedy_for_an_unsafe_block_is_offered_to_a_person(tmp_path: Path) -> None:
    """The flag that unblocks the run is an affordance of the console rendering."""
    result = rendering("run", "--local", str(write(tmp_path, HELLO)))
    assert result.exit_code == GUARD_EXIT
    assert "--enable-unsafe shell.run" in plain(result.output)


def test_the_allowlist_is_added_to_rather_than_turned_off(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "docker.run")
    assert result.exit_code == GUARD_EXIT, "allowing a different block must not allow this one"


def test_the_unsafe_flag_takes_a_comma_separated_list_as_well_as_a_repeat() -> None:
    """--enable-unsafe accepts both repetition and a comma-separated list."""
    assert split_unsafe(["shell.run,docker.run"]) == ["shell.run", "docker.run"]
    assert split_unsafe(["shell.run", "docker.run"]) == ["shell.run", "docker.run"]
    assert split_unsafe([" shell.run , ", ""]) == ["shell.run"]
    assert split_unsafe([]) == []


def test_a_comma_separated_allowlist_reaches_the_run(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "docker.run,shell.run")
    assert result.exit_code == 0, result.output


def test_an_invalid_document_is_refused_with_its_issues(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO.replace("shell.run", "nope.gone"))))
    assert result.exit_code == GUARD_EXIT
    assert "no block" in refusal(result.stdout)["message"]


def test_parameters_reach_the_run(tmp_path: Path) -> None:
    document = HELLO.replace(
        "steps:",
        "params:\n  type: object\n  properties:\n    who: {type: string, default: nobody}\nsteps:",
    ).replace('"hello from a local run"', '"hello ${params.who}"')
    result = invoke(
        "run", "--local", str(write(tmp_path, document)), "-p", "who=morten", "--enable-unsafe", "shell.run"
    )
    assert result.exit_code == 0, result.output


def test_local_refuses_to_be_combined_with_a_server(tmp_path: Path) -> None:
    path = str(write(tmp_path, HELLO))
    with_url = invoke("--url", "http://x.example.org", "run", "--local", path)
    with_token = invoke("--token", "x", "run", "--local", path)
    assert "cannot be combined" in refusal(with_url.stdout)["message"]
    assert "cannot be combined" in refusal(with_token.stdout)["message"]


def test_local_needs_a_document_not_a_pipeline_name() -> None:
    result = invoke("run", "--local", "some-pipeline")
    assert result.exit_code == 1
    assert "not a file" in refusal(result.stdout)["message"]


def test_a_connections_file_is_read_in_either_shape(tmp_path: Path) -> None:
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("connections:\n  echo:\n    kind: http\n    config: {base_url: https://x.example.org}\n")
    assert [spec.code for spec in load_connection_specs(mapping)] == ["echo"]

    listed = tmp_path / "list.yaml"
    listed.write_text("- code: echo\n  kind: http\n  config: {base_url: https://x.example.org}\n")
    assert [spec.code for spec in load_connection_specs(listed)] == ["echo"]

    broken = tmp_path / "broken.yaml"
    broken.write_text("just a string\n")
    with pytest.raises(LocalError, match="mapping or a list"):
        load_connection_specs(broken)


def test_the_bundled_connections_file_is_readable() -> None:
    specs = load_connection_specs(EXAMPLES / "connections.yaml")
    by_code = {spec.code: spec for spec in specs}
    assert "postman-echo" in by_code, "the corpus's own HTTP endpoint, which most examples name"
    assert by_code["postman-echo"].config["base_url"] == "https://postman-echo.com"


def test_a_connection_of_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    connections = tmp_path / "c.yaml"
    connections.write_text("nope:\n  kind: not-a-kind\n  config: {}\n")
    result = invoke(
        "run", "--local", str(write(tmp_path, HELLO)), "--connections", str(connections), "--enable-unsafe", "shell.run"
    )
    assert result.exit_code == GUARD_EXIT
    assert "no connection kind" in refusal(result.stdout)["message"]


def test_shell_output_reaches_the_stream_not_only_an_artifact(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    said = messages(result.stdout, "log")
    assert "hello from a local run" in said, "what the command printed is the point of the step"


def test_the_stream_reads_as_cause_then_effect(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    stream = records(result.stdout)
    announced = next(index for index, event in enumerate(stream) if event["message"] == "queued")
    printed = next(index for index, event in enumerate(stream) if event["message"] == "hello from a local run")
    settled = next(
        index for index, event in enumerate(stream) if event["kind"] == "step" and event["message"] == "succeeded"
    )
    assert announced < printed < settled, "the step is announced, then what it printed, then how it settled"
    assert stream[-1]["kind"] == "run" and stream[-1]["message"] == "succeeded"


def test_every_record_of_the_stream_reads_the_same_way(tmp_path: Path) -> None:
    """The default output is the protocol: one shape, whatever the record is about."""
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    stream = records(result.stdout)
    assert len(stream) >= 4, result.output
    assert all({"v", "at", "level", "kind", "step", "item", "message"} <= set(event) for event in stream)
    kinds = [event["kind"] for event in stream]
    assert kinds[0] == "run" and kinds[-1] == "run"
    assert "step" in kinds and "log" in kinds


def test_the_default_stream_carries_no_process_logs(tmp_path: Path) -> None:
    """Process logging is a diagnostic on stderr, and the quiet default asks for none of it."""
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert "dirigent.engine" not in result.stderr
    assert "attempt settled" not in result.stderr


def test_one_v_interleaves_the_engines_own_events(tmp_path: Path) -> None:
    result = invoke("-v", "run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert "attempt settled" in result.stderr
    assert "aiosqlite" not in result.stderr


def test_two_v_gives_debug_without_the_library_firehose(tmp_path: Path) -> None:
    result = invoke("-vv", "run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert "aiosqlite" not in result.stderr, "the noisy libraries stay capped so -vv is readable"


def test_debug_all_lifts_even_the_library_cap() -> None:
    import logging

    from dirigent_cli.context import CliState

    assert CliState(verbose=2).floors["aiosqlite"] == logging.WARNING
    assert CliState(verbose=2, debug_all=True).floors == {}
    CliState(verbose=2, debug_all=True).configure_output()
    assert logging.getLogger("aiosqlite").level in (logging.DEBUG, logging.NOTSET)


def test_the_environment_sets_the_level_when_no_flag_does(monkeypatch: pytest.MonkeyPatch) -> None:
    from dirigent_cli.context import CliState

    assert CliState().level == "WARNING"
    monkeypatch.setenv("DIRIGENT_LOG_LEVEL", "INFO")
    assert CliState().level == "INFO"
    assert CliState(verbose=2).level == "DEBUG", "the flag wins over the environment"


NAMED_SCHEMA = """
format: dirigent/v1
kind: pipeline
code: local-named-schema
description: One gate that checks a value against a schema the instance holds by name.
requires:
  schemas: [ou-shape]
steps:
  check:
    block: validate.schema
    config:
      input: {id: OU1, level: 2}
      schema: ou-shape
"""

CARRIED_SCHEMA = """
format: dirigent/v1
kind: pipeline
code: local-carried-schema
description: One gate that checks a value against a schema the document carries.
schemas:
  ou-shape:
    type: object
    required: [id, level]
    properties:
      id: {type: string}
      level: {type: integer}
steps:
  check:
    block: validate.schema
    config:
      input: {id: OU1, level: 2}
      schema: ou-shape
"""

OU_SHAPE = (
    '{"$id": "ou-shape", "type": "object", "required": ["id", "level"],'
    ' "properties": {"id": {"type": "string"}, "level": {"type": "integer"}}}'
)


def test_load_schema_specs_reads_a_body_and_takes_its_fallback_from_the_filename(tmp_path: Path) -> None:
    path = tmp_path / "ou-shape.json"
    path.write_text(OU_SHAPE)
    spec = load_schema_specs(path)
    assert spec.fallback_code == "ou-shape"
    assert spec.body["required"] == ["id", "level"]

    broken = tmp_path / "broken.json"
    broken.write_text('"just a string"\n')
    with pytest.raises(LocalError, match="is not a JSON Schema"):
        load_schema_specs(broken)


def test_a_named_schema_is_held_by_a_local_run_and_gates_the_value(tmp_path: Path) -> None:
    """A --schema file is stored by code, and a gate that names it checks against it."""
    schema = tmp_path / "ou-shape.json"
    schema.write_text(OU_SHAPE)
    result = invoke("run", "--local", str(write(tmp_path, NAMED_SCHEMA)), "--schema", str(schema))
    assert result.exit_code == 0, result.output
    assert closing(result.stdout)["message"] == "succeeded"


def test_a_carried_schema_is_seeded_and_gates_the_value(tmp_path: Path) -> None:
    """A schema the document carries is stored into the local instance, so the gate resolves it."""
    result = invoke("run", "--local", str(write(tmp_path, CARRIED_SCHEMA)))
    assert result.exit_code == 0, result.output
    assert closing(result.stdout)["message"] == "succeeded"


COMPOSING_PARENT = """
format: dirigent/v1
kind: pipeline
code: local-composition
description: One step that starts the carried-schema document as a child and waits for it.
requires:
  pipelines: [local-carried-schema]
steps:
  child:
    block: pipeline.run
    config:
      pipeline: local-carried-schema
      wait: true
      strict: true
"""


def test_a_child_applied_with_also_apply_keeps_the_schemas_it_carries(tmp_path: Path) -> None:
    """A supporting document's carried schemas are seeded too, so its gate resolves as a child."""
    child = write(tmp_path, CARRIED_SCHEMA, name="child.yaml")
    parent = write(tmp_path, COMPOSING_PARENT, name="parent.yaml")
    result = invoke("run", "--local", str(parent), "--also-apply", str(child))
    assert result.exit_code == 0, result.output
    assert closing(result.stdout)["message"] == "succeeded"


def test_a_document_requiring_a_schema_no_local_run_holds_is_refused(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, NAMED_SCHEMA)))
    assert result.exit_code != 0
    assert "ou-shape" in refusal(result.stdout)["message"]


def test_a_named_schema_the_instance_lacks_fails_the_step_at_the_gate(tmp_path: Path) -> None:
    """With no requires to catch it at apply, an unheld code fails the run where it is read."""
    document = NAMED_SCHEMA.replace("requires:\n  schemas: [ou-shape]\n", "")
    result = invoke("run", "--local", str(write(tmp_path, document)))
    assert result.exit_code != 0
    said = [event["message"] for event in records(result.stdout)]
    assert any("no schema coded 'ou-shape'" in message for message in said), said


def test_a_document_brings_its_own_schemas_and_a_file_replaces_one(tmp_path: Path) -> None:
    """A published document carries the shapes it needs; --schema is how somebody redirects one."""
    document = load_text(
        "format: dirigent/v1\ncode: carried\n"
        "schemas:\n"
        "  ou-shape: {type: object, required: [id]}\n"
        "  other-shape: {type: object}\n"
        "steps:\n  a: {block: validate.schema, config: {input: {id: x}, schema: ou-shape}}\n"
    )
    carried = {spec.code: spec for spec in schemas_for([document], ())}
    assert set(carried) == {"ou-shape", "other-shape"}, "a carried schema is keyed by its map code"
    assert carried["ou-shape"].body["required"] == ["id"]

    override = SchemaSpec(body={"type": "object", "required": ["id", "extra"]}, code="ou-shape")
    merged = {spec.code: spec for spec in schemas_for([document], [override])}
    assert merged["ou-shape"].body["required"] == ["id", "extra"], "the file wins for that code"
    assert merged["other-shape"].body == {"type": "object"}, "and leaves the rest alone"


def test_a_local_run_seals_and_opens_its_own_connections(tmp_path: Path) -> None:
    """A local run seals its connections with an ephemeral key and opens them like any other."""
    connections = tmp_path / "c.yaml"
    connections.write_text(
        "warehouse:\n  kind: http\n  config:\n    base_url: https://warehouse.example.org\n    bearer_token: a-secret\n"
    )
    document = HELLO.replace("block: shell.run", "block: http.ready").replace(
        'config:\n      argv: [echo, "hello from a local run"]',
        "config:\n      connection: warehouse\n      path: /health\n    poll: 1s\n    deadline: 2s\n"
        "    on_timeout: skip\n",
    )
    result = invoke("run", "--local", str(write(tmp_path, document)), "--connections", str(connections))
    assert result.exit_code == 0, result.output
    assert "a-secret" not in result.output, "a stored credential is never printed"


@pytest.mark.e2e
def test_the_hello_world_example_runs_end_to_end() -> None:
    """The example a new project is scaffolded with must actually run."""
    result = invoke("run", "--local", str(EXAMPLES / "hello-world.yaml"))
    assert result.exit_code == 0, result.output
    assert closing(result.stdout)["message"] == "succeeded"


CHAIN = """
format: dirigent/v1
kind: pipeline
code: local-chain
description: A chain whose alphabetical order is the reverse of the order it runs in.
steps:
  zebra:
    block: shell.run
    config:
      argv: [echo, "first"]
  middle:
    block: shell.run
    depends_on: [zebra]
    config:
      argv: [echo, "second"]
  apple:
    block: shell.run
    depends_on: [middle]
    config:
      argv: [echo, "third"]
"""


def test_the_parallel_sleep_example_waits_three_times_at_once(tmp_path: Path) -> None:
    """Steps with no edges between them are all roots, so nine seconds of waiting takes five."""
    started = time.monotonic()
    result = invoke(
        "--json",
        "-v",
        "run",
        "--local",
        str(EXAMPLES / "graph" / "parallel-sleep.yaml"),
        "--enable-unsafe",
        "shell.run",
    )
    elapsed = time.monotonic() - started
    assert result.exit_code == 0, result.stdout
    assert elapsed < 8, f"the waits ran one after another: {elapsed:.1f}s for a five second run"
    produced = {event["step"]: event for event in records(result.stdout) if event["kind"] == "output"}
    assert produced.keys() == {"slow", "medium", "quick", "report"}
    for step, configured in (("slow", 5000), ("medium", 3000), ("quick", 1000)):
        waited = produced[step]["waited_ms"]
        assert waited >= configured, f"{step} reported waiting less than it was configured to"
    reported = produced["report"]["stdout"]
    for step in ("slow", "medium", "quick"):
        assert f"{produced[step]['waited_ms']}ms" in reported, f"the join did not read {step}"
        assert step in reported, f"the join read {step} without saying which wait it was"
    events = records(result.stdout)
    queued = [event["step"] for event in events if event["kind"] == "step" and event["message"] == "queued"]
    assert queued[:3] == ["slow", "medium", "quick"], "the roots are announced in the order they were written"
    assert [step["step"] for step in events[-1]["steps"]][-1] == "report", "the join settles last, and lists last"


def test_a_fan_out_labels_every_item_it_streams(tmp_path: Path) -> None:
    """Four attempts of one step are four different things, and the stream has to say which."""
    document = """
format: dirigent/v1
kind: pipeline
code: local-fan-out
description: One step mapped over three elements.
params:
  type: object
  properties:
    regions:
      type: array
      default: [east, west, north]
      items:
        type: string
steps:
  greet:
    block: shell.run
    for_each: "${params.regions}"
    config:
      argv: [echo, "${item}"]
"""
    result = invoke("run", "--local", str(write(tmp_path, document)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 0, result.output
    settled = {
        (event["step"], event["item"])
        for event in of_kind(records(result.stdout), "step")
        if event["message"] == "succeeded"
    }
    assert settled == {("greet", "east"), ("greet", "west"), ("greet", "north")}


def test_the_stream_shows_what_a_block_reported_rather_than_only_that_it_reported(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    reported = next(
        record
        for record in records(result.stdout)
        if record["kind"] == "log" and record["message"] == "command finished"
    )
    assert reported["step"] == "greet"
    assert reported["fields"]["exit_code"] == 0, "a log line's fields are the half that says what happened"


def test_a_local_run_reports_what_each_step_produced(tmp_path: Path) -> None:
    """The database is deleted on the way out, so an output not carried here is gone."""
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    produced = closing(result.stdout)["steps"][0]
    assert produced["step"] == "greet"
    assert produced["output"]["exit_code"] == 0
    assert produced["output"]["stdout"] == "hello from a local run\n", "the value is carried whole"


def test_two_artifacts_from_one_run_are_two_different_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each step spills to its own object, so no two steps report the same artifact."""
    monkeypatch.setenv("COLUMNS", "200")
    (tmp_path / "settings.yaml").write_text("enabled_unsafe_blocks: []\ninline_artifact_max: 16\n")
    reset_settings_cache()
    document = """
format: dirigent/v1
kind: pipeline
code: local-two-artifacts
description: Two steps, each spilling its output to the run's own scratch space.
steps:
  first:
    block: shell.run
    config:
      argv: [echo, "the first"]
  second:
    block: shell.run
    depends_on: [first]
    config:
      argv: [echo, "the second"]
"""
    result = invoke("run", "--local", str(write(tmp_path, document)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 0, result.output
    spilled = [step["artifact_uri"] for step in closing(result.stdout)["steps"]]
    assert len(spilled) == 2 and all(spilled), result.output
    assert len(set(spilled)) == 2, "two different objects must not be one URI"


def test_keep_leaves_the_instance_behind_and_says_where(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run", "--keep")
    assert result.exit_code == 0, result.output
    kept = closing(result.stdout)["kept_at"]
    assert kept, "the run that keeps its instance says where it left it"
    directory = Path(kept)
    try:
        assert (directory / "dirigent.db").is_file()
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_keep_without_local_is_refused(tmp_path: Path) -> None:
    result = invoke("run", "some-pipeline", "--keep")
    assert result.exit_code == 1
    assert "--keep" in refusal(result.stdout)["message"]


WRITER = """
format: dirigent/v1
kind: pipeline
code: local-writer
description: One file written at a path that outlives the run.
steps:
  mark:
    block: storage.write
    config:
      target: "file://MARKER"
      value: {seen: [alpha]}
"""

READER = """
format: dirigent/v1
kind: pipeline
code: local-reader
description: The file the writer left, read back.
steps:
  seen:
    block: storage.exists
    poll: 1s
    deadline: 5s
    on_timeout: skip
    config:
      uri: "file://MARKER"
  read:
    block: storage.read
    depends_on: [seen]
    config:
      source: "file://MARKER"
  previous:
    block: transform.jq
    depends_on: [read]
    config:
      input: "${steps.read.output.value}"
      program: .seen
"""


def at(document: str, marker: Path) -> str:
    """Point a document's stable path at one file, which two runs then share."""
    return document.replace("MARKER", str(marker))


def test_a_second_run_under_the_same_root_reads_what_the_first_wrote(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    marker = root / "artifacts" / "marker.json"
    first = invoke("run", "--local", "--root", str(root), str(write(tmp_path, at(WRITER, marker))))
    assert first.exit_code == 0, first.output
    assert marker.is_file(), "the root outlives the run that wrote into it"
    second = invoke(
        "run",
        "--local",
        "--root",
        str(root),
        str(write(tmp_path, at(READER, marker), name="reader.yaml")),
    )
    assert second.exit_code == 0, second.output
    steps = {step["step"]: step for step in closing(second.stdout)["steps"]}
    assert steps["seen"]["status"] == "succeeded"
    assert steps["previous"]["output"]["value"] == ["alpha"]


def test_the_started_record_says_which_root_the_run_is_held_in(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    result = invoke(
        "run",
        "--local",
        "--root",
        str(root),
        str(write(tmp_path, at(WRITER, root / "artifacts" / "m.json"))),
    )
    assert result.exit_code == 0, result.output
    started = of_kind(records(result.stdout), "run")[0]
    assert started["root"] == str(root)
    assert started["scratch"].startswith(f"file://{root / 'artifacts'}/runs/")


def test_root_without_local_is_refused(tmp_path: Path) -> None:
    result = invoke("run", "some-pipeline", "--root", str(tmp_path / "instance"))
    assert result.exit_code == 1
    assert "--root" in refusal(result.stdout)["message"]


def test_a_root_that_is_a_file_is_refused(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory\n")
    result = invoke(
        "run", "--local", "--root", str(occupied), str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run"
    )
    assert result.exit_code == GUARD_EXIT
    assert "is not a directory" in refusal(result.stdout)["message"]


FAN_OUT_THEN_FAILURE = """
format: dirigent/v1
kind: pipeline
code: local-stream
description: A fan-out that works, and then a step that cannot.
params:
  type: object
  properties:
    regions:
      type: array
      default: [east, west]
      items:
        type: string
steps:
  greet:
    block: shell.run
    for_each: "${params.regions}"
    config:
      argv: [echo, "${item}"]
  copy_nothing:
    block: storage.copy
    depends_on: [greet]
    config:
      source: "${run.scratch}/missing.json"
      target: "${run.scratch}/copy.json"
"""


def test_one_v_adds_the_output_record_rather_than_changing_a_line(tmp_path: Path) -> None:
    """Verbosity decides which records are written; what a record carries never moves."""
    document = str(write(tmp_path, HELLO))
    default = invoke("run", "--local", document, "--enable-unsafe", "shell.run")
    verbose = invoke("-v", "run", "--local", document, "--enable-unsafe", "shell.run")
    assert of_kind(records(default.stdout), "output") == [], "the quiet default leaves the value to the summary"
    produced = of_kind(records(verbose.stdout), "output")
    assert produced, verbose.output
    assert produced[0]["exit_code"] == 0
    assert produced[0]["stdout"] == "hello from a local run\n", "the value is whole, at the level that shows it"


def test_a_debug_line_from_a_block_waits_for_a_run_that_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The run keeps info and up unless --log-level asks, and the terminal renders at -d."""
    monkeypatch.setenv("COLUMNS", "300")
    document = str(write(tmp_path, SLEEPS))
    assert not _waited(invoke("run", "--local", document))
    assert not _waited(invoke("-d", "run", "--local", document)), (
        "process verbosity shows what the run kept, and this run kept info and up"
    )
    assert _waited(invoke("-d", "run", "--local", document, "--log-level", "debug"))


def _waited(result: Any) -> bool:
    """Whether the block's own debug line reached the stream."""
    return any("still waiting" in said for said in messages(result.stdout, "log"))


SLEEPS = """
format: dirigent/v1
kind: pipeline
code: local-sleep
description: One short wait, which logs its remainder at debug.
steps:
  wait:
    block: time.sleep
    config:
      for: 1s
"""


def test_json_puts_nothing_but_json_objects_on_stdout(tmp_path: Path) -> None:
    result = invoke("--json", "run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 0, result.output
    assert records(result.stdout), "the stream is not empty"
    assert "succeeded  run" not in result.stdout, "no rich rendering survives --json"
    assert "┏" not in result.stdout, "no table is drawn under --json"


def test_a_runs_stream_carries_the_stable_discriminators(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    events = records(result.stdout)
    kinds = [event["kind"] for event in events]
    assert kinds[0] == "run" and kinds[-1] == "run"
    assert set(kinds) <= {"run", "step", "log", "output"}
    assert all(event["v"] == 1 for event in events), "every record says which protocol it is"


def test_the_stream_survives_a_fan_out_and_a_failure(tmp_path: Path) -> None:
    """Two items and a failed step still come out as one object per line, in order."""
    document = write(tmp_path, FAN_OUT_THEN_FAILURE)
    result = invoke("run", "--local", str(document), "--enable-unsafe", "shell.run")
    assert result.exit_code == 1, result.output
    events = records(result.stdout)
    settled = {
        (event["step"], event["item"])
        for event in events
        if event["kind"] == "step" and event["message"] == "succeeded"
    }
    assert ("greet", "east") in settled
    assert ("greet", "west") in settled
    closing = events[-1]
    assert closing["kind"] == "run"
    assert closing["message"] == "failed", "the run's own status is the message its closing event carries"
    assert closing["exit_code"] == 1
    assert [failure["step"] for failure in closing["failures"]] == ["copy_nothing"]
    assert {step["step"] for step in closing["steps"]} == {"greet", "copy_nothing"}


def test_every_fan_out_element_reaches_the_stream_without_a_readable_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two elements are both attempt 1 of one step, so the stream must not key on the name.

    A label is read from a row the run writes; when it is not readable, a key built from the
    step name leaves both elements sharing one, and one of them is announced while the rest
    are swallowed.
    """

    async def unlabelled(session: object, run_id: object) -> dict[object, str]:
        return {}

    monkeypatch.setattr(local, "_item_labels", unlabelled)
    result = invoke("run", "--local", str(write(tmp_path, FAN_OUT_THEN_FAILURE)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 1, result.output
    settled = [
        event
        for event in records(result.stdout)
        if event["kind"] == "step" and event["step"] == "greet" and event["message"] == "succeeded"
    ]
    assert len(settled) == 2, "both elements settled, so both belong in the stream"


def test_a_finished_step_carries_the_output_the_table_would_have_shown(tmp_path: Path) -> None:
    result = invoke("-v", "run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    events = records(result.stdout)
    settled = next(event for event in events if event["kind"] == "step" and event["message"] == "succeeded")
    assert settled["step"] == "greet"
    assert settled["duration_ms"] is not None
    produced = next(event for event in events if event["kind"] == "output")
    assert produced["stdout"] == "hello from a local run\n", "the output event carries the value whole"


def test_a_local_run_that_cannot_be_set_up_refuses_as_a_problem_object(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)))
    assert result.exit_code == GUARD_EXIT
    problem = refusal(result.stdout)
    assert problem["kind"] == "error"
    assert problem["status"] == GUARD_EXIT
    assert "shell.run" in problem["message"]


def test_verbosity_raises_dirigents_own_loggers_and_nobody_elses(tmp_path: Path) -> None:
    """-v is a request for the engine's reasoning, not for alembic's migration history."""
    document = str(write(tmp_path, HELLO))
    verbose = invoke("-v", "run", "--local", document, "--enable-unsafe", "shell.run")
    assert verbose.exit_code == 0, verbose.output
    assert "dirigent.engine" in verbose.stderr, "the engine's own events are what -v asked for"
    assert "alembic" not in verbose.stderr
    assert "sqlalchemy" not in verbose.stderr


def test_debug_all_lifts_every_cap(tmp_path: Path) -> None:
    result = invoke("--debug-all", "run", "--local", str(write(tmp_path, HELLO)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 0, result.output
    assert "alembic" in result.stderr, "--debug-all is the flag that asks for everybody's logging"


def test_every_record_says_when_at_every_level(tmp_path: Path) -> None:
    """One shape means one shape: no field comes and goes with the flags."""
    document = str(write(tmp_path, HELLO))
    for argv in (("run",), ("-v", "run"), ("-d", "run")):
        result = invoke(*argv, "--local", document, "--enable-unsafe", "shell.run")
        stream = records(result.stdout)
        assert stream, result.output
        assert all(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$", event["at"]) for event in stream)


WARNS = """
format: dirigent/v1
kind: pipeline
code: local-warned
description: A step that succeeds and warns on the way.
steps:
  noisy:
    block: shell.run
    config:
      command: "echo careful >&2; echo fine"
"""


def test_a_warning_is_recorded_at_its_own_level(tmp_path: Path) -> None:
    """A step can succeed and still have said something worth reading."""
    result = invoke("run", "--local", str(write(tmp_path, WARNS)), "--enable-unsafe", "shell.run")
    assert result.exit_code == 0, result.stdout
    levels = {record["message"]: record["level"] for record in of_kind(records(result.stdout), "log")}
    assert levels["careful"] == "warning", "a line that is not routine says so"
    assert levels["fine"] == "info", "and a routine one says that"


def test_the_console_and_json_outputs_carry_the_same_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One protocol: rendering it does not change the events or their field names.

    One execution, spelled twice: the run goes out as records, and ``dg format`` renders
    that same stream through the formatter a rendered invocation uses live. A second
    execution would order its events on its own clock, which no rendering promises to
    reproduce.
    """
    monkeypatch.setenv("COLUMNS", "300")
    document = str(write(tmp_path, HELLO))
    machine = invoke("-v", "run", "--local", document, "--enable-unsafe", "shell.run")
    assert machine.exit_code == 0, machine.output
    shown = runner.invoke(app, ["format"], input=machine.stdout)
    assert shown.exit_code == 0, shown.output

    def kinds(lines: list[str]) -> list[str]:
        records = [parse(line) for line in lines]
        return [record["kind"] for record in records if record is not None]

    lines = plain(shown.stdout).splitlines()
    rendered = [found.group("kind") for found in (LINE.match(line) for line in lines) if found]
    assert rendered == kinds(machine.stdout.splitlines()), "the same events, whether encoded or rendered"


def test_a_commands_diagnostics_read_in_the_same_grammar_as_its_story(tmp_path: Path) -> None:
    """One grammar covers both streams, so -v does not read as a second program starting."""
    document = str(write(tmp_path, HELLO))
    result = invoke("-v", "run", "--local", document, "--enable-unsafe", "shell.run")
    diagnostics = [line for line in plain(result.stderr).splitlines() if line.strip()]
    assert diagnostics, result.output
    for line in diagnostics:
        assert LINE.match(line), f"a diagnostic does not read as a line: {line}"
    assert any("dirigent." in line for line in diagnostics), "and says which logger wrote it"


def test_ndjson_carries_no_decoration(tmp_path: Path) -> None:
    """Under JSON, nothing reaches stdout that is not one record per line."""
    document = str(write(tmp_path, HELLO))
    result = invoke("run", "--local", document, "--enable-unsafe", "shell.run")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines
    assert all(parse(line) is not None for line in lines), "JSON printed something that is not a record"
    assert "\u250f" not in result.stdout and "succeeded  run" not in result.stdout


def test_a_document_brings_its_own_connections_and_a_file_replaces_one(tmp_path: Path) -> None:
    """A published document runs as it is; --connections is how somebody redirects it."""
    document = load_text(
        "format: dirigent/v1\ncode: carried\n"
        "connections:\n"
        "  demo: {kind: http, config: {base_url: 'https://example.org'}}\n"
        "  other: {kind: http, config: {base_url: 'https://second.example'}}\n"
        "steps:\n  a: { block: shell.run, config: {argv: [echo, hi]} }\n"
    )
    carried = {spec.code: spec for spec in connections_for([document], ())}
    assert set(carried) == {"demo", "other"}
    assert carried["demo"].config == {"base_url": "https://example.org"}

    override = ConnectionSpec(code="demo", kind="http", config={"base_url": "https://mine.internal"})
    merged = {spec.code: spec for spec in connections_for([document], [override])}
    assert merged["demo"].config == {"base_url": "https://mine.internal"}, "the file wins for that name"
    assert merged["other"].config == {"base_url": "https://second.example"}, "and leaves the rest alone"
    assert len(connections_for([document], [override])) == 2, "the replaced one is not seeded twice"


def stored_stream(tmp_path: Path) -> Path:
    """Run a document under NDJSON and keep the stream in a file."""
    document = str(write(tmp_path, HELLO))
    machine = invoke("-v", "run", "--local", document, "--enable-unsafe", "shell.run")
    stored = tmp_path / "run.ndjson"
    stored.write_text(machine.stdout)
    return stored


def test_a_stored_stream_renders_back_as_the_console_rendering(tmp_path: Path) -> None:
    rendered = invoke("format", "console", "--file", str(stored_stream(tmp_path)))
    assert rendered.exit_code == 0, rendered.output
    printed = plain(rendered.output)
    assert "hello from a local run" in printed, "the message is back in the console rendering"
    assert "pipeline=local-hello" in printed, "and the fields with it"


def test_the_formatter_is_optional_and_the_stream_can_arrive_on_stdin(tmp_path: Path) -> None:
    """``dg dev | dg format`` is the shape: no formatter named, nothing but a pipe."""
    stored = stored_stream(tmp_path)
    piped = runner.invoke(app, ["format"], input=stored.read_text())
    assert piped.exit_code == 0, piped.output
    assert plain(piped.output) == plain(invoke("format", "console", "--file", str(stored)).output)


def test_a_line_that_is_not_a_record_passes_through_untouched(tmp_path: Path) -> None:
    """A real log interleaves; formatting one must not eat the rest of it."""
    stored = tmp_path / "mixed.ndjson"
    stored.write_text('a line from somebody else\n{"v":1,"kind":"log","message":"ours"}\n')
    rendered = invoke("format", "--file", str(stored))
    assert rendered.exit_code == 0, rendered.output
    printed = plain(rendered.output)
    assert "a line from somebody else" in printed
    assert "ours" in printed


def test_a_template_is_answered_with_the_tool_that_does_that_job(tmp_path: Path) -> None:
    """Docker and kubectl take a template here; refusing without saying where to go is unkind."""
    result = invoke("format", "{{.step}}", "--file", str(stored_stream(tmp_path)))
    assert result.exit_code == 2
    printed = plain(result.output)
    assert "takes no template" in printed
    assert "jq" in printed, "it names the tool that picks fields out of this stream"


def test_an_unknown_formatter_is_refused_by_name(tmp_path: Path) -> None:
    result = invoke("format", "yaml", "--file", str(stored_stream(tmp_path)))
    assert result.exit_code == 2
    assert "yaml" in result.output and "console" in result.output


def test_a_registered_formatter_renders_the_same_records_differently(tmp_path: Path) -> None:
    """A formatter changes how a record reads, never which records there are or what they hold."""
    stored = stored_stream(tmp_path)
    padded = plain(invoke("format", "console", "--file", str(stored)).output)
    unpadded = plain(invoke("format", "compact", "--file", str(stored)).output)
    assert padded != unpadded, "the two formatters do not render alike"
    for line in unpadded.splitlines():
        assert "  " not in line.strip(), "compact pads no columns"
    assert "pipeline=local-hello" in unpadded, "and drops none of the record's fields"


def test_compact_makes_one_line_of_every_record_a_run_carries(tmp_path: Path) -> None:
    """Compact spends no columns, so what console draws as a table stays on the line."""
    stored = stored_stream(tmp_path)
    written = [line for line in stored.read_text().splitlines() if line.strip()]
    unpadded = plain(invoke("format", "compact", "--file", str(stored)).output)
    assert len(unpadded.splitlines()) == len(written), "one record, one line"
    assert "steps=" in unpadded, "including what the closing record carries for its table"


def test_console_draws_the_closing_record_rather_than_spelling_it_out(tmp_path: Path) -> None:
    """The table is a rendering of the run record, keyed by its kind, not a second reading."""
    stored = stored_stream(tmp_path)
    padded = plain(invoke("format", "console", "--file", str(stored)).output)
    assert "steps=" not in padded, "the closing record's own line does not spell out every step"
    assert "greet" in padded and "shell.run" in padded, "the table says what the step was"


def test_an_unknown_spelling_is_refused_by_name(tmp_path: Path) -> None:
    result = invoke("-o", "yaml", "run", "--local", str(write(tmp_path, HELLO)))
    assert result.exit_code == 2
    assert "console" in result.output and "json" in result.output


def test_the_environment_names_the_spelling_when_no_flag_does(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A container sets it once; a flag on the command still wins."""
    monkeypatch.setenv("DIRIGENT_LOG_FORMAT", "json")
    document = str(write(tmp_path, HELLO))
    named = invoke("run", "--local", document, "--enable-unsafe", "shell.run")
    assert all(parse(line) is not None for line in named.stdout.splitlines() if line.strip())
    monkeypatch.setenv("DIRIGENT_LOG_FORMAT", "console")
    shown = invoke("run", "--local", document, "--enable-unsafe", "shell.run")
    assert LINE.match(plain(shown.output).splitlines()[0]), shown.output


def test_a_command_asked_for_nothing_writes_records(tmp_path: Path) -> None:
    """Off a terminal, NDJSON is what a command writes when neither a flag nor the environment says.

    The test runner's stdout is a pipe, which is what an agent's shell, CI and a container's
    log are: records without asking.
    """
    document = str(write(tmp_path, HELLO))
    result = invoke("run", "--local", document, "--enable-unsafe", "shell.run")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.output
    assert all(parse(line) is not None for line in lines), "a rendering reached stdout unasked"


def test_a_refusal_is_a_record_a_formatter_can_render(tmp_path: Path) -> None:
    """`dg runs list | dg format` should say why it failed, not pass a line of JSON through."""
    result = invoke("run", "--local", str(write(tmp_path, HELLO)))
    refused = parse(result.stdout.splitlines()[0])

    assert refused is not None, "a refusal that does not parse is somebody else's text to a formatter"
    assert refused["kind"] == "error"
    assert refused["level"] == "error"
    assert refused["at"] is not None, "and it says when, like every other record"


def test_the_closing_record_carries_the_steps_in_execution_order(tmp_path: Path) -> None:
    """The order is a fact about the run, so it is asserted on the record that carries it.

    The table beside this is a rendering of the same order; that test reads the drawing
    because the drawing is what it is about.
    """
    result = invoke("run", "--local", str(write(tmp_path, CHAIN)), "--enable-unsafe", "shell.run")

    assert result.exit_code == 0, result.output
    assert [step["step"] for step in closing(result.stdout)["steps"]] == ["zebra", "middle", "apple"]


def test_the_closing_record_counts_a_warning_against_the_step_that_logged_it(tmp_path: Path) -> None:
    """How many warnings a step logged is a fact, and the summary is a rendering of it."""
    result = invoke("run", "--local", str(write(tmp_path, WARNS)), "--enable-unsafe", "shell.run")

    assert result.exit_code == 0, result.output
    warned = {step["step"]: step["warnings"] for step in closing(result.stdout)["steps"]}
    assert sum(warned.values()) == 1, f"the warning was not counted against a step: {warned}"


def test_priority_is_refused_where_there_is_nothing_to_be_ahead_of(tmp_path: Path) -> None:
    """A --local run is alone in a throwaway instance, so ordering it against others says nothing."""
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--priority", "high")
    assert result.exit_code == 1
    assert "orders a run against the others queued" in refusal(result.stdout)["message"]


def test_a_priority_that_is_not_one_is_refused_before_anything_is_applied(tmp_path: Path) -> None:
    result = invoke("run", "--local", str(write(tmp_path, HELLO)), "--priority", "urgent")
    assert result.exit_code == 1
    refused = refusal(result.stdout)["message"]
    assert "is not a priority" in refused
    assert "low, normal, high" in refused


#: A run that logged more than one page holds, which is what makes the paging visible.
LONG_LOG_LINES = 1_200

#: How many quiet polls the widening test watches, enough for the interval to reach its ceiling.
QUIET_TICKS = 8


async def _seeded_run(root: Path) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], EngineServices, UUID]:
    """Build a local run's database and create one queued run in it, claiming nothing."""
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{root / 'local.db'}",
        artifact_root=f"file://{root / 'artifacts'}",
    )
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    services = EngineServices.build(settings, load_plugin_host())
    definition = PipelineDefinition(
        code="paged",
        steps={"one": StepDefinition(block="storage.copy", config={"source": "a", "target": "b"})},
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return engine, sessions, services, run.id


async def _log_lines(sessions: async_sessionmaker[AsyncSession], run_id: UUID, messages: list[str]) -> None:
    """Write log entries straight into the run, the way a worker's flush does."""
    async with session_scope(sessions) as session:
        await session.execute(
            sa.insert(LogEntry),
            [
                {
                    "run_id": run_id,
                    "run_item_id": None,
                    "step_attempt_id": None,
                    "step_name": "one",
                    "level": LogLevel.INFO,
                    "message": message,
                    "fields": None,
                    "created_at": datetime.now(UTC),
                }
                for message in messages
            ],
        )


async def test_the_local_driver_reads_a_long_log_in_pages(tmp_path: Path) -> None:
    """Every line is delivered once, in id order, however many pages it takes."""
    engine, sessions, _services, run_id = await _seeded_run(tmp_path / "long")
    await _log_lines(sessions, run_id, [f"line {index}" for index in range(LONG_LOG_LINES)])
    delivered: list[str] = []
    widths: list[int] = []
    cursor, more = 0, True
    while more:
        lines, cursor, more = await _new_logs(sessions, run_id, cursor, {})
        widths.append(len(lines))
        delivered.extend(line.message for line in lines)
    assert delivered == [f"line {index}" for index in range(LONG_LOG_LINES)]
    assert max(widths) <= LOCAL_LOG_PAGE + 1
    await engine.dispose()


class _StopDriving(Exception):
    """Raised from the stubbed sleep to end a poll loop that would otherwise run to a deadline."""


class _IdleWorker:
    """A worker that claims nothing, so the run under the driver never moves on its own."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        """Take whatever the driver passes, and wait to be stopped."""
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        """Do nothing until the driver asks to stop."""
        await self._stopped.wait()

    def request_stop(self) -> None:
        """Let the run loop finish."""
        self._stopped.set()


async def test_the_local_driver_widens_its_poll_when_nothing_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quiet run is asked about less and less often, and a line puts the poll back to the floor."""
    engine, sessions, services, run_id = await _seeded_run(tmp_path / "quiet")
    monkeypatch.setattr(local, "Worker", _IdleWorker)
    intervals: list[float] = []
    slept = asyncio.sleep

    async def recording(seconds: float) -> None:
        """Record what the driver asked to wait, wait for none of it, and write a line partway."""
        intervals.append(seconds)
        if len(intervals) == QUIET_TICKS:
            await _log_lines(sessions, run_id, ["something happened"])
        if len(intervals) == QUIET_TICKS + 2:
            raise _StopDriving
        await slept(0)

    monkeypatch.setattr(asyncio, "sleep", recording)
    with pytest.raises(_StopDriving):
        async for _event in _drive(sessions, services, run_id, "paged", {}, [], 600.0):
            pass
    widening = [POLL_SECONDS * POLL_WIDEN**step for step in range(QUIET_TICKS)]
    assert intervals[:QUIET_TICKS] == pytest.approx([min(seconds, POLL_CEILING) for seconds in widening])
    assert intervals[QUIET_TICKS - 1] == POLL_CEILING, "the widening stops at the ceiling"
    assert intervals[QUIET_TICKS] == pytest.approx(POLL_SECONDS), "the line that landed put the poll back"
    assert intervals[QUIET_TICKS + 1] == pytest.approx(POLL_SECONDS * POLL_WIDEN)
    await engine.dispose()


def test_a_terminal_gets_the_rendering_unasked_and_records_when_it_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one thing the terminal decides: unasked, a person reads lines and a pipe reads records."""
    from dirigent_cli.main import resolve_output

    monkeypatch.delenv("DIRIGENT_LOG_FORMAT", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert resolve_output(None, json_output=False) == "console"
    assert resolve_output(None, json_output=True) == "json"
    assert resolve_output("json", json_output=False) == "json"
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert resolve_output(None, json_output=False) == "json"
    assert resolve_output("console", json_output=False) == "console"
    monkeypatch.setenv("DIRIGENT_LOG_FORMAT", "console")
    assert resolve_output(None, json_output=False) == "console"


def test_a_process_record_follows_the_output_it_was_asked_for(capsys: pytest.CaptureFixture[str]) -> None:
    """Dg dev's own lines go through the same sink as every record, so -o console renders them."""
    from dirigent_cli import main
    from dirigent_cli.output import configure
    from dirigent_core.protocol import make

    record = make("process", at=datetime.now(UTC), message="starting", process="dev", api="http://127.0.0.1:1")
    configure(output="json")
    main.emit(record)
    assert parse(capsys.readouterr().out.strip()) is not None
    configure(output="console")
    main.emit(record)
    assert LINE.match(plain(capsys.readouterr().out).splitlines()[0])
    configure(output="json")
