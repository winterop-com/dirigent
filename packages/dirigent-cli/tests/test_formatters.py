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
from dirigent_cli import formatters, summaries
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


def test_the_effective_configuration_names_what_the_working_directory_could_not_set() -> None:
    drawn = printed(
        Console().render(
            make(
                "config",
                at=AT,
                message="effective configuration",
                settings={"host": "127.0.0.1"},
                ignored=["database_url", "host"],
            )
        )
    )
    assert "database_url, host" in drawn


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
                problems=[
                    {
                        "code": "document.step_config_invalid",
                        "message": "'Not A Name' is not a code",
                        "params": {},
                        "location": "code",
                    }
                ],
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


def test_a_documents_shape_is_drawn_as_the_rows_and_the_totals_its_record_carries() -> None:
    """The command counts; the table, the totals and the warnings are the formatter's."""
    drawn = printed(
        Console().render(
            make(
                "validation.shape",
                at=AT,
                message="shape",
                code="demo",
                document="demo.yaml",
                checked="document and catalog",
                attempts_max=13,
                attempts_at_least=True,
                deadline_longest="1d",
                steps=[
                    {
                        "name": "shape",
                        "block": "transform.jq",
                        "cardinality": 3,
                        "elements": 3,
                        "items": "continue",
                        "max_attempts": 3,
                        "retry_wait": "1m30s",
                    },
                    {
                        "name": "wait",
                        "block": "time.sleep",
                        "depends_on": ["shape"],
                        "cardinality": "adopts shape",
                        "elements": 3,
                        "item_wise_parent": "shape",
                        "poll": "1s",
                        "deadline": "1d",
                        "on_timeout": "skip",
                        "from_block": ["poll"],
                    },
                ],
                warnings=[{"step": "shape", "cause": "retry-outlasts-deadline", "message": "shape retries for ages"}],
            )
        )
    )
    assert "what demo will cost" in drawn
    assert "transform.jq" in drawn and "1m30s" in drawn
    assert "adopts shape" in drawn
    assert "item by item" in drawn, "a step whose items each wait for their own match says so beside its width"
    assert "continue" in drawn, "a fan-out that does not fail fast says so where the width is"
    assert "then skip" in drawn, "what an expired deadline makes of the step belongs beside it"
    assert "1s  block" in drawn, "a wait the catalog filled in is marked as the block's own"
    assert "at least 13" in drawn, "a total counted over an unknown width is a floor"
    assert "shape retries for ages" in drawn
    assert "steps=" not in drawn and "warnings=" not in drawn, "the rows are drawn, not spelled out on the line"


def test_a_shape_with_nothing_to_warn_about_is_the_table_and_the_totals_alone() -> None:
    """A document nothing is wrong with draws no list of nothing, and a shape with no steps draws nothing."""
    drawn = printed(
        Console().render(
            make(
                "validation.shape",
                at=AT,
                message="shape",
                code="demo",
                attempts_max=1,
                steps=[{"name": "greet", "block": "shell.run"}],
            )
        )
    )
    assert "at most 1" in drawn
    assert drawn.splitlines()[-1].startswith("deadline chain"), "a document with no warnings draws no list of them"
    assert summaries.beneath(make("validation.shape", at=AT, message="shape", code="demo", steps=[])) is None


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


def test_a_found_attempt_renders_what_it_belongs_to_and_where_to_open_it() -> None:
    found = make(
        "run.attempt",
        at=AT,
        message="failed",
        attempt_id="an-attempt",
        run_id="a-run",
        pipeline="demo",
        step="load",
        item="oslo",
        attempt=2,
        address="http://127.0.0.1:8080/runs/a-run/load?attempt=an-attempt",
    )
    text = printed(Console().render(found))
    assert "attempt an-attempt" in text
    assert "oslo" in text
    assert "http://127.0.0.1:8080/runs/a-run/load?attempt=an-attempt" in text


def test_run_stats_render_the_days_the_durations_and_what_failed_most() -> None:
    """Every table is drawn from the record, and the line keeps none of what is drawn beneath it."""
    stats = make(
        "runs.stats",
        at=AT,
        message="3 settled, 1 failed",
        window_start="2026-01-01T00:00:00+00:00",
        window_end="2026-01-02T00:00:00+00:00",
        settled=3,
        failed=1,
        trend=[{"day": "2026-01-01", "total": 3, "succeeded": 2, "failed": 1}],
        durations=[{"pipeline": "demo", "runs": 3, "p50_ms": 2000, "p95_ms": 9000, "max_ms": 9000}],
        top_errors=[{"code": "shell.exit", "message": "exit 1 [sic]", "count": 1, "pipeline": "demo"}],
        failing_steps=[{"pipeline": "demo", "step": "load", "failures": 1}],
    )
    text = printed(Console().render(stats))
    assert "settled per day" in text and "2026-01-01" in text
    assert "9.0s" in text, "the p95 is drawn as a duration"
    assert "shell.exit" in text and "exit 1 [sic]" in text, "a message is printed as it was said, not as markup"
    assert "failing steps" in text and "load" in text
    assert "trend" not in summaries.line(stats)
    assert summaries.beneath(make("runs.stats", at=AT, message="0 settled, 0 failed", trend=[])) is None


def test_a_runs_summary_renders_a_row_per_pipeline_and_leaves_out_empty_states() -> None:
    summary = make(
        "runs.summary",
        at=AT,
        message="1 pipelines ran",
        window_start="2026-01-01T00:00:00+00:00",
        window_end="2026-01-02T00:00:00+00:00",
        pipelines=[
            {
                "pipeline": "every-ten",
                "name": None,
                "latest": {"id": "a", "status": "failed", "created_at": "2026-01-01T23:50:00+00:00"},
                "counts": {"succeeded": 140, "failed": 3},
                "recent": [{"id": "b", "status": "succeeded"}, {"id": "a", "status": "failed"}],
                "median_duration_ms": 4000,
            }
        ],
    )
    text = printed(Console().render(summary))
    assert "every-ten" in text
    assert "140 succeeded, 3 failed" in text
    assert "4.0s" in text
    assert "cancelled" not in text, "a state with no runs is not drawn"
    assert "pipelines" not in summaries.line(summary)
    assert summaries.beneath(make("runs.summary", at=AT, message="0 pipelines ran", pipelines=[])) is None


def test_a_process_that_minted_a_token_hands_it_over_beneath_its_line() -> None:
    """Dg dev's starting record carries the fixture token once; the rendering must not drop it."""
    drawn = printed(
        Console().render(make("process", at=AT, message="starting", process="dev", token="a-dev-token", admin="dev"))
    )
    assert "export DG_TOKEN=a-dev-token" in drawn
    assert "starting" in drawn
    quiet = printed(Console().render(make("process", at=AT, message="ready", process="dev")))
    assert "DG_TOKEN" not in quiet


BASE = "http://127.0.0.1:8123"


def announced(message: str, **fields: Any) -> dict[str, Any]:
    """One record a serving process announces itself with, carrying what the banner reads."""
    said: dict[str, Any] = {
        "process": "dev",
        "version": "0.32.0",
        "api": BASE,
        "ui": BASE,
        "docs": f"{BASE}/docs",
        "mcp": f"{BASE}/mcp",
        "admin": "admin",
        "password": "admin",
        "state": "/work/.dirigent/state",
        "log": "/work/.dirigent/state/dev.log",
        "packs": [
            {"name": "dirigent-block-base", "version": "0.32.0"},
            {"name": "dirigent-blocks", "version": "0.32.0"},
            {"name": "dirigent-dhis2", "version": "0.31.4"},
        ],
        "blocks": 33,
        "connection_kinds": 10,
        "source_kinds": 1,
    }
    return make("process", at=AT, message=message, **{**said, **fields})


def drawn_at(item: object, *, width: int, colour: bool, encoding: str = "utf-8") -> str:
    """Print a rendering to a terminal of a fixed width and encoding, with colour named rather than detected."""

    class Terminal(io.StringIO):
        """A terminal's stream, saying which characters it can draw."""

        def __init__(self, drawable: str) -> None:
            super().__init__()
            self.drawable = drawable

        def __getattribute__(self, name: str) -> Any:
            if name == "encoding":
                return object.__getattribute__(self, "drawable")
            return super().__getattribute__(name)

    written = Terminal(encoding)
    console = RichConsole(
        file=written,
        force_terminal=colour,
        color_system="truecolor" if colour else None,
        no_color=not colour,
        width=width,
    )
    parts: list[object] = list(item.renderables) if isinstance(item, Group) else [item]
    for part in parts:
        console.print(part)
    return written.getvalue()


def test_a_ready_instance_is_drawn_as_one_banner_of_the_facts_its_record_carries() -> None:
    drawn = plain(drawn_at(Console().render(announced("ready")), width=100, colour=False))
    lines = [line.rstrip() for line in drawn.splitlines()]
    head = next(index for index, line in enumerate(lines) if "dirigent 0.32.0" in line)
    assert "●" in lines[head + 1], "the mark stands beside the head on a wide terminal"
    assert "dev instance ready, UI and API" in lines[head + 1]
    assert lines[head + 2].strip().endswith(BASE)
    labelled = {line.split()[0]: line for line in lines[head + 3 :] if line.strip()}
    assert set(labelled) == {"docs", "mcp", "sign", "state", "log", "loaded", "packs"}
    assert labelled["sign"].split()[-3:] == ["admin", "/", "admin"]
    assert labelled["loaded"].endswith("33 blocks, 10 connection kinds, 1 source kind")
    assert "2 at 0.32.0: dirigent-block-base, dirigent-blocks; dirigent-dhis2 0.31.4" in labelled["packs"]
    assert "[info" not in drawn, "the banner is not a line of the grammar"


def test_the_banner_carries_the_brand_in_colour_and_the_same_words_without_it() -> None:
    coloured = drawn_at(Console().render(announced("ready")), width=100, colour=True)
    assert "\x1b[38;2;210;154;42m" in coloured, "the mark is drawn in the brand's amber"
    bare = drawn_at(Console().render(announced("ready")), width=100, colour=False)
    assert "\x1b[" not in bare
    assert plain(coloured).split() == bare.split()


def test_a_narrow_terminal_gets_the_banner_without_its_mark_and_nothing_cut() -> None:
    drawn = drawn_at(Console().render(announced("ready")), width=40, colour=False)
    assert "●" not in drawn
    assert all(len(line.rstrip()) <= 40 for line in drawn.splitlines())
    assert "/work/.dirigent/state/dev.log" in drawn.replace("\n", "").replace(" ", "")


def test_a_terminal_without_box_characters_gets_the_mark_in_ascii() -> None:
    drawn = drawn_at(Console().render(announced("ready")), width=100, colour=False, encoding="ascii")
    assert "●" not in drawn
    assert "o--o--o" in drawn


def test_a_server_banner_says_nothing_of_signing_in_or_of_state() -> None:
    server = announced("ready", process="server", admin=None, password=None, state=None, log=None, ui=None, mcp=None)
    drawn = drawn_at(Console().render(server), width=100, colour=False)
    assert "server ready, API only" in drawn
    for absent in ("sign in", "state", "log", "mcp"):
        assert f"  {absent} " not in drawn


def test_the_starting_record_hands_over_its_token_and_leaves_the_rest_to_the_banner() -> None:
    minted = Console().render(announced("starting", token="a-dev-token"))
    drawn = printed(minted)
    assert "export DG_TOKEN=a-dev-token" in drawn
    assert "starting" not in drawn
    assert "dirigent 0.32.0" not in drawn
    assert printed(Console().render(announced("starting"))) == ""
    banner = drawn_at(Console().render(announced("ready", token="a-dev-token")), width=100, colour=False)
    assert "a-dev-token" not in banner, "the token is never drawn on the banner"


def test_a_process_record_without_a_version_keeps_its_line() -> None:
    """A stream an older dirigent wrote reads as it always did."""
    drawn = printed(Console().render(make("process", at=AT, message="ready", process="dev")))
    assert drawn.splitlines()[0].count("ready") == 1
    assert "dirigent" not in drawn


def test_the_compact_formatter_keeps_the_announcement_on_one_line() -> None:
    line = printed(Compact().render(announced("ready")))
    assert "\n" not in line
    assert " ready " in line
    assert "blocks=33" in line


def test_a_changed_schema_names_the_pipelines_it_was_changed_for() -> None:
    """The dependents ride off the line and are drawn beneath it, named rather than counted."""
    edited = make(
        "schema.updated",
        at=AT,
        message="updated",
        code="gate-shape",
        name="Gate shape",
        changed=["body"],
        used_by=["gated", "nightly"],
    )
    drawn = printed(Console().render(edited))
    line, beneath = drawn.splitlines()[0], drawn.splitlines()[1:]
    assert "code=gate-shape" in line
    assert 'changed=["body"]' in line
    # The dependents ride off the line, so a shape twenty pipelines name still reads as one.
    assert "used_by" not in line
    assert "gated" not in line
    drawn_beneath = "\n".join(beneath)
    assert summaries.SCHEMA_REACHES in drawn_beneath
    assert [one.strip() for one in beneath if one.strip().startswith("-")] == ["- gated", "- nightly"]
    # The exception reads after the names, because the colon above governs them and a run in
    # flight is not one of them.
    assert drawn_beneath.index(summaries.IN_FLIGHT_KEEPS_ITS_SHAPE) > drawn_beneath.index("nightly")


def test_a_changed_schema_nothing_depends_on_draws_nothing_beneath_its_line() -> None:
    edited = make(
        "schema.updated",
        at=AT,
        message="updated",
        code="lonely",
        name=None,
        changed=["name"],
        used_by=[],
    )
    assert summaries.beneath(edited) is None
    assert "lonely" in printed(Console().render(edited))


def test_a_source_reads_as_its_state_its_step_and_what_it_has_taken() -> None:
    listed = make(
        "source",
        at=AT,
        fields={
            "pipeline": "arrivals",
            "code": "poked",
            "kind": "sensor",
            "state": "listening",
            "summary": "playground.arrive",
            "methods": [],
            "in_flight": 1,
            "max_in_flight": 2,
            "accepted": 3,
            "refused": 0,
            "failed": 0,
            "poll_failures": 0,
            "last_error": None,
        },
    )
    drawn = printed(Console().render(listed))
    assert "listening" in drawn
    assert "[source poked]" in drawn
    assert "pipeline=arrivals" in drawn
    assert "source=sensor" in drawn
    assert "in_flight=1/2" in drawn
    assert "accepted=3" in drawn
    assert "fields.kind" not in drawn, "the source's own kind is not spelled as a namespaced collision"
    assert "poll_failures" not in drawn, "a source that has not failed says nothing of failures"
    assert "failed=" not in drawn, "nor of failed runs when it has none"


def test_a_refused_input_reads_as_a_warning_with_its_reason() -> None:
    taken = make(
        "source.input",
        at=AT,
        fields={
            "created_at": AT,
            "outcome": "refused",
            "status": 401,
            "code": "source.unauthorised",
            "reason": "bad token",
            "method": "POST",
            "path": "/ask",
            "duration_ms": 3,
        },
    )
    drawn = printed(Console().render(taken))
    assert "[warning" in drawn
    assert "refused" in drawn
    assert "[source.input]" in drawn
    assert "status=401" in drawn
    assert 'reason="bad token"' in drawn
