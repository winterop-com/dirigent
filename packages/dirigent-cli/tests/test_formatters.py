"""The formatter registry: what is built in, what a plugin may add, and the contract."""

import io
from pathlib import Path
from typing import Any

import pytest
from pluginkit import PluginManager
from rich.console import Console as RichConsole
from rich.console import Group
from typer.testing import CliRunner

from clisupport import plain
from dirigent_cli import formatters
from dirigent_cli.formatters import (
    DEFAULT,
    Compact,
    Console,
    looks_like_a_template,
    names,
    registry,
    rendered,
)
from dirigent_cli.main import app
from dirigent_common import Formatter
from dirigent_core.protocol import as_json, make
from dirigent_plugin import extension

AT = "2026-01-01T18:22:23.069+00:00"


def record(**fields: Any) -> dict[str, Any]:
    """One record to render."""
    return make("step", at=AT, step="fetch", message="succeeded", **fields)


def printed(item: object) -> str:
    """Read a rendered record as the text it says, with colour named rather than detected.

    A formatter answers with an ``object``; printing one is what narrows it, here as in the
    command.
    """
    written = io.StringIO()
    console = RichConsole(file=written, force_terminal=False, no_color=True, width=400)
    parts: list[object] = list(item.renderables) if isinstance(item, Group) else [item]
    for part in parts:
        if isinstance(part, str):
            console.print(part, soft_wrap=True, highlight=False)
        else:
            console.print(part)
    return plain(written.getvalue().rstrip("\n"))


def test_the_built_ins_are_registered_under_their_own_names() -> None:
    registered = registry()
    assert isinstance(registered["console"], Console)
    assert isinstance(registered["compact"], Compact)


def test_the_default_is_the_first_name_offered() -> None:
    """A person reading the help should see the one they get for free first."""
    assert names()[0] == DEFAULT
    assert DEFAULT in registry()


def test_every_formatter_carries_a_name_and_a_version() -> None:
    """The contract is a name, a version and one method turning records into lines."""
    for name, formatter in registry().items():
        assert isinstance(formatter, Formatter)
        assert formatter.name == name
        assert formatter.version, f"{name} carries no version"


def test_a_formatter_renders_a_kind_it_has_never_heard_of() -> None:
    """A record from a newer dirigent, or from a plugin's own event, still has to read."""
    invented = make("weather", at=AT, message="raining", millimetres=4)
    for formatter in registry().values():
        line = printed(formatter.render(invented))
        assert "raining" in line
        assert "millimetres=4" in line


def test_compact_keeps_every_field_and_spends_no_columns() -> None:
    """Compact trades the padding a wide terminal can afford, not the record's content."""
    written = record(block="http.request", attempt=1)
    line = printed(Compact().render(written))
    padded = printed(Console().render(written))
    assert "block=http.request" in line and "attempt=1" in line
    assert "  " not in line, "nothing is padded"
    assert "  " in padded, "and the console rendering still is"
    assert line.split()[0] == padded.split()[0], "the same instant, spelled the same way"
    assert line.split()[1] == "[info]", "the level spends no column"


def test_a_line_that_is_not_a_record_passes_through_whichever_formatter_reads_it() -> None:
    lines = ["not ours at all", as_json(record())]
    for formatter in registry().values():
        out = list(rendered(lines, formatter))
        assert out[0] == "not ours at all"
        assert "succeeded" in printed(out[1])


class Shouty:
    """A formatter that exists only in this test."""

    name = "shouty"
    version = "9"

    def render(self, record: dict[str, Any]) -> str:
        """Render the message, loudly."""
        return str(record.get("message", "")).upper()


class ShoutyPack:
    """A plugin contributing the formatter above, as an installed package would."""

    @extension
    def formatters(self) -> list[Formatter]:
        """Contribute one formatter."""
        return [Shouty()]


def test_only_the_built_ins_are_registered_when_no_plugin_contributes_one() -> None:
    registered = registry(group="dirigent.formatters.none-installed")
    assert sorted(registered) == ["compact", "console"]


def test_a_plugin_contributes_a_formatter_and_dg_format_dispatches_on_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third party ships a formatter, and the command renders with it by name."""

    def register_the_pack(self: PluginManager, group: str, *, ignore_errors: bool = False) -> int:
        """Stand in for the installed distributions of the formatter group."""
        if group != formatters.ENTRY_POINT_GROUP:
            return 0
        self.register(ShoutyPack(), name="shouty-pack")
        return 1

    monkeypatch.setattr(PluginManager, "load_entrypoints", register_the_pack)
    assert isinstance(registry()["shouty"], Shouty)
    assert "console" in registry(), "the built-ins are still there beside it"
    assert names()[0] == DEFAULT

    stored = tmp_path / "run.ndjson"
    stored.write_text(as_json(record()) + "\n")
    shown = CliRunner().invoke(app, ["format", "shouty", "--file", str(stored)])
    assert shown.exit_code == 0, shown.output
    assert "SUCCEEDED" in plain(shown.output)


def test_two_plugins_claiming_one_formatter_name_are_refused() -> None:
    """A formatter name is what the command dispatches on, so it has one owner."""
    with pytest.raises(formatters.DuplicateFormatter) as refusal:
        registry(extra={"first-pack": ShoutyPack(), "second-pack": ShoutyPack()})
    said = str(refusal.value)
    assert "shouty" in said
    assert "first-pack" in said and "second-pack" in said


def test_a_plugin_may_not_claim_a_built_in_name() -> None:
    class ConsolePack:
        """A plugin contributing a formatter under a name the CLI already owns."""

        @extension
        def formatters(self) -> list[Formatter]:
            """Contribute a formatter called console."""
            shadow = Shouty()
            shadow.name = "console"
            return [shadow]

    with pytest.raises(formatters.DuplicateFormatter) as refusal:
        registry(extra={"shadow-pack": ConsolePack()})
    assert formatters.BUILT_IN in str(refusal.value)


def test_a_template_is_told_apart_from_a_formatter_name() -> None:
    """Not to render it: to answer the habit docker teaches with the tool that does the job."""
    assert looks_like_a_template("{{.step}}")
    assert looks_like_a_template("{{ .step }}")
    assert not looks_like_a_template("console")
    assert not looks_like_a_template("compact")


def closing_run(**fields: Any) -> dict[str, Any]:
    """A watched run's closing record, which is the one carrying a header to mark."""
    carried: dict[str, Any] = {
        "message": "succeeded",
        "run_id": "01a00000-0000-7000-8000-000000000000",
        "pipeline": "demo",
        "pipeline_version": 3,
        "duration_ms": 4200,
        "steps": [{"step": "fetch", "block": "http.request", "status": "succeeded"}],
        "failures": [],
        **fields,
    }
    return make("run", at=AT, **carried)


def test_the_ordinary_priority_puts_nothing_in_the_run_header() -> None:
    """Almost every run is normal, so marking every one of them would say nothing."""
    header = printed(Console().render(closing_run(priority="normal")))
    assert "priority=normal" in header, "the record still carries the word it was created with"
    assert "!" not in header
    assert " low" not in header


def test_an_urgent_run_is_marked_in_its_header() -> None:
    """A red bang beside the run id, read here with the colour named rather than detected."""
    header = printed(Console().render(closing_run(priority="high")))
    assert "!" in header


def test_a_low_run_is_marked_in_its_header() -> None:
    header = printed(Console().render(closing_run(priority="low")))
    assert "low" in header
    assert "!" not in header


def step_summary(step: str, **fields: Any) -> dict[str, Any]:
    """One row of the closing record's own step list."""
    return {
        "step": step,
        "item": None,
        "block": "shell.run",
        "status": "succeeded",
        "depends_on": [],
        "warnings": 0,
        "attempts": 1,
        "duration_ms": 12,
        "output": None,
        "error": None,
        "artifact_uri": None,
        "artifact_bytes": None,
        **fields,
    }


def test_a_failed_run_is_drawn_with_the_diagnosis_its_record_carries() -> None:
    """A local run's database is gone by then, so the drawing has to say all of it."""
    drawn = printed(
        Console().render(
            closing_run(
                message="failed",
                steps=[step_summary("copy_nothing", block="storage.copy", status="failed")],
                failures=[
                    {
                        "step": "copy_nothing",
                        "item": None,
                        "block": "storage.copy",
                        "attempt": 1,
                        "error": "missing.json could not be read",
                    }
                ],
            )
        )
    )
    assert "copy_nothing failed" in drawn
    assert "storage.copy" in drawn
    assert "attempt 1" in drawn
    assert "missing.json" in drawn


def test_the_summary_table_is_in_execution_order_not_alphabetical() -> None:
    """The record lists the steps in the order they ran, and the table must not reorder them."""
    drawn = printed(
        Console().render(closing_run(steps=[step_summary("zebra"), step_summary("middle"), step_summary("apple")]))
    )
    assert drawn.index("zebra") < drawn.index("middle") < drawn.index("apple")


def test_the_summary_table_shows_what_each_step_produced() -> None:
    """The value is in the closing record, and the table is where a person reads it."""
    produced = {"exit_code": 0, "stdout": "hello from a local run\n"}
    drawn = " ".join(printed(Console().render(closing_run(steps=[step_summary("greet", output=produced)]))).split())
    assert "exit_code=0" in drawn
    assert "stdout=hello from a" in drawn


def test_a_step_that_warned_is_marked_in_the_summary_table() -> None:
    drawn = printed(Console().render(closing_run(steps=[step_summary("noisy", warnings=1)])))
    assert "1 warn" in drawn


def test_a_settled_step_leaves_its_output_to_the_table() -> None:
    """A step's line says how it settled; the value it produced is drawn once, in the table."""
    line = printed(Console().render(record(block="shell.run", attempt=1, duration_ms=12)))
    assert "exit_code=0" not in line


def test_the_effective_configuration_is_drawn_as_a_setting_per_row() -> None:
    drawn = printed(
        Console().render(
            make(
                "config",
                at=AT,
                message="effective configuration",
                settings={"database_url": "sqlite+aiosqlite:///dirigent.db", "secret_key": "***"},
            )
        )
    )
    assert "database_url" in drawn
    assert "sqlite+aiosqlite:///dirigent.db" in drawn
    assert "secret_key" in drawn and "***" in drawn


def test_the_migration_history_is_drawn_as_alembic_wrote_it() -> None:
    drawn = printed(Console().render(make("db.history", at=AT, message="migration history", history="0001_baseline")))
    assert "0001_baseline" in drawn


def test_an_invalid_document_is_drawn_with_the_problems_its_record_carries() -> None:
    drawn = printed(
        Console().render(
            make(
                "validation",
                at=AT,
                level="error",
                message="invalid",
                code="demo",
                problems=["code: 'Not A Name' is not a code"],
            )
        )
    )
    assert "invalid" in drawn
    assert "Not A Name" in drawn


def test_a_valid_pipeline_is_drawn_as_the_graph_its_record_carries() -> None:
    """The command carries the steps; drawing them under what they wait for is the formatter's."""
    drawn = printed(
        Console().render(
            make(
                "validation",
                at=AT,
                message="valid",
                code="demo",
                steps=[
                    {"name": "greet", "block": "shell.run", "depends_on": [], "rule": "all_success"},
                    {"name": "farewell", "block": "shell.run", "depends_on": ["greet"], "rule": "all_success"},
                ],
            )
        )
    )
    assert "greet  (shell.run)" in drawn
    assert "farewell  (shell.run)" in drawn
    assert drawn.index("greet") < drawn.index("farewell")
    assert "steps=" not in drawn, "the graph is drawn, not spelled out on the line"


def test_a_run_profile_renders_the_chain_and_the_split_along_it() -> None:
    """The table is the formatter's, built from the record and nothing read a second time."""
    profile = make(
        "run.profile",
        at=AT,
        message="succeeded in 10.0s",
        run_id="a-run",
        pipeline="demo",
        critical_path=["extract", "load"],
        duration_ms=10_000,
        queued_ms=1000,
        running_ms=7000,
        waiting_ms=2000,
    )
    text = printed(Console().render(profile))
    assert "critical path: extract -> load" in text
    assert "waiting" in text and "2.0s" in text
    assert "70%" in text, "the share of the run is what says which part is worth attention"


def test_a_process_that_minted_a_token_hands_it_over_beneath_its_line() -> None:
    """Dg dev's starting record carries the fixture token once; the rendering must not drop it."""
    drawn = printed(
        Console().render(make("process", at=AT, message="starting", process="dev", token="a-dev-token", admin="dev"))
    )
    assert "export DG_TOKEN=a-dev-token" in drawn
    assert "starting" in drawn
    quiet = printed(Console().render(make("process", at=AT, message="ready", process="dev")))
    assert "DG_TOKEN" not in quiet
