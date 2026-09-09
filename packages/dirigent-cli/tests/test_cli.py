"""Tests for the dirigent command line."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import click
import pytest
import typer
from typer.testing import CliRunner

from clisupport import of_kind, only, plain, records, refusal
from dirigent_cli import main, triggers
from dirigent_cli.commands import GUARD_EXIT
from dirigent_cli.context import CliState
from dirigent_cli.main import (
    LIST_ALIASES,
    PANEL_ORDER,
    app,
    build_app,
    build_worker,
    distribution_version,
)
from dirigent_core.config import CONFIG_FILE_ENV, Settings, get_settings, redacted_url, reset_settings_cache
from dirigent_core.protocol import make

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every command a throwaway database and a clean settings cache."""
    config_file = tmp_path / "dirigent.yaml"
    config_file.write_text(f'database_url: "sqlite+aiosqlite:///{tmp_path / "dirigent.db"}"\n')
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config_file))
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_the_version_flag_answers_with_one_plain_line() -> None:
    """`dg --version` is the one output that is not a record: a line a person or a script reads as is."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"dg {distribution_version('dirigent-cli')}"


def test_config_show_writes_the_effective_settings_as_a_record() -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    settings = only(result.stdout, "config")["settings"]
    assert "database_url" in settings
    assert "worker_concurrency" in settings


def test_db_current_refuses_before_the_first_upgrade() -> None:
    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 1
    problem = refusal(result.stdout)
    assert "never been migrated" in problem["message"]
    assert any("dg db upgrade" in one for one in problem["problems"])


def test_db_upgrade_then_current_reports_the_head(tmp_path: Path) -> None:
    upgraded = runner.invoke(app, ["db", "upgrade"])
    assert upgraded.exit_code == 0
    assert only(upgraded.stdout, "db.upgraded")["target"] == "head"
    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 0
    current = only(result.stdout, "db.revision")
    assert current["at_head"] is True
    assert current["revision"] == current["head"]
    assert (tmp_path / "dirigent.db").exists()


def test_db_history_lists_the_baseline() -> None:
    result = runner.invoke(app, ["db", "history"])
    assert result.exit_code == 0
    assert "0001_baseline" in only(result.stdout, "db.history")["history"]


@pytest.fixture
def keyed_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """A migrated instance with a secret key, which is what sealing a credential needs."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    config_file = tmp_path / "keyed.yaml"
    config_file.write_text(
        f'database_url: "sqlite+aiosqlite:///{tmp_path / "keyed.db"}"\nsecret_key: "{key}"\n',
    )
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config_file))
    reset_settings_cache()
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0
    yield get_settings()
    reset_settings_cache()


#: One whole s3 credential, as the compose stack's bootstrap writes it.
ARTIFACT_CONNECTION = [
    "--set",
    "endpoint_url=http://s3:9000",
    "--set",
    "bucket=dirigent",
    "--set",
    "access_key_id=an-access-key",
    "--set",
    "secret_access_key=a-secret-key",
    "--set",
    "path_style=true",
]


def stored_connection(settings: Settings, code: str) -> Any:
    """Read one connection row back the way the engine reads it: straight from the database."""
    import asyncio

    import sqlalchemy as sa

    from dirigent_core.database import create_engine, create_session_factory, session_scope
    from dirigent_core.models import Connection

    async def read() -> Any:
        engine = create_engine(settings)
        try:
            async with session_scope(create_session_factory(engine)) as session:
                found = await session.execute(sa.select(Connection).where(Connection.code == code))
                row = found.scalar_one()
                # The row is detached when the session closes, so what the test reads is taken now.
                return (row.kind, dict(row.config), row.secret_envelope, row.secret_key_id, row.name)
        finally:
            await engine.dispose()

    return asyncio.run(read())


def test_connection_ensure_creates_a_row_and_then_updates_it(keyed_instance: Settings) -> None:
    created = runner.invoke(app, ["--json", "connection", "ensure", "s3", "artifacts", *ARTIFACT_CONNECTION])
    assert created.exit_code == 0, created.output
    made = only(created.output, "connection.created")
    assert made["message"] == "created"
    assert made["code"] == "artifacts"
    assert made["connection_kind"] == "s3"
    assert made["config"]["bucket"] == "dirigent"
    assert made["config"]["path_style"] is True, "--set is coerced against the kind's schema"

    again = runner.invoke(
        app,
        ["--json", "connection", "ensure", "s3", "artifacts", "--name", "Artifacts", *ARTIFACT_CONNECTION],
    )
    assert again.exit_code == 0, again.output
    assert only(again.output, "connection.updated")["message"] == "updated", "the second brings the row to this config"
    kind, config, envelope, key_id, name = stored_connection(keyed_instance, "artifacts")
    assert (kind, config["bucket"], name) == ("s3", "dirigent", "Artifacts")
    assert envelope is not None and key_id is not None


def test_connection_ensure_seals_the_secret_half_with_the_instance_key(keyed_instance: Settings) -> None:
    from dirigent_core.secrets import SecretBox

    result = runner.invoke(app, ["--json", "connection", "ensure", "s3", "artifacts", *ARTIFACT_CONNECTION])
    assert result.exit_code == 0, result.output
    assert "a-secret-key" not in result.output, "a secret is never emitted"
    assert only(result.output, "connection.created")["config"]["secret_access_key"] == "***"

    _, config, envelope, _, _ = stored_connection(keyed_instance, "artifacts")
    assert "secret_access_key" not in config, "the secret half is not a column"
    key = keyed_instance.secret_key
    assert key is not None
    assert SecretBox(key.get_secret_value()).open(envelope) == {"secret_access_key": "a-secret-key"}


def test_connection_ensure_refuses_a_kind_no_plugin_contributes(keyed_instance: Settings) -> None:
    result = runner.invoke(app, ["--json", "connection", "ensure", "nope", "artifacts", "--set", "bucket=dirigent"])
    assert result.exit_code == 1
    assert "no connection kind" in refusal(result.output)["message"]


def test_the_scheduler_refuses_to_start_on_sqlite() -> None:
    result = runner.invoke(app, ["scheduler"])
    assert result.exit_code == GUARD_EXIT
    problem = refusal(result.stdout)
    assert "advisory" in problem["message"]
    assert any("dg dev" in one for one in problem["problems"])


def test_the_worker_refuses_to_start_on_sqlite() -> None:
    result = runner.invoke(app, ["worker"])
    assert result.exit_code == GUARD_EXIT
    problem = refusal(result.stdout)
    assert "refuses to start on SQLite" in problem["message"]
    assert problem["status"] == GUARD_EXIT


def test_the_server_refuses_to_embed_the_scheduler_on_sqlite() -> None:
    """`dg server` embeds the scheduler by default, and leadership is a PostgreSQL lock."""
    result = runner.invoke(app, ["server"])
    assert result.exit_code == GUARD_EXIT
    problem = refusal(result.stdout)
    assert "advisory lock" in problem["message"]
    assert any("--no-scheduler" in one for one in problem["problems"])


def test_the_server_flag_switches_the_ui_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--no-ui` lands in the settings, through the environment, before anything reads them."""
    from dirigent_cli.main import UI_ENV

    monkeypatch.setenv(UI_ENV, "true")
    reset_settings_cache()
    result = runner.invoke(app, ["server", "--no-ui"])
    assert result.exit_code == GUARD_EXIT, result.output
    assert get_settings().ui_enabled is False
    reset_settings_cache()


def test_the_server_flag_switches_the_ui_on_over_a_setting_that_said_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from dirigent_cli.main import UI_ENV

    monkeypatch.setenv(UI_ENV, "false")
    reset_settings_cache()
    result = runner.invoke(app, ["server", "--ui"])
    assert result.exit_code == GUARD_EXIT, result.output
    assert get_settings().ui_enabled is True
    reset_settings_cache()


def test_dev_takes_the_same_ui_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from dirigent_cli.main import UI_ENV

    monkeypatch.setenv(UI_ENV, "true")
    monkeypatch.setenv("DIRIGENT_DATABASE_URL", "postgresql+asyncpg://dirigent@localhost/dirigent")
    reset_settings_cache()
    result = runner.invoke(app, ["dev", "--no-ui"])
    assert result.exit_code == GUARD_EXIT, result.output
    assert get_settings().ui_enabled is False
    reset_settings_cache()


def test_dev_refuses_to_start_on_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIRIGENT_DATABASE_URL", "postgresql+asyncpg://dirigent@localhost/dirigent")
    reset_settings_cache()
    result = runner.invoke(app, ["dev"])
    assert result.exit_code == GUARD_EXIT
    assert "SQLite standalone mode" in refusal(result.stdout)["message"]


def test_dev_help_says_its_state_belongs_to_the_working_directory() -> None:
    result = runner.invoke(app, ["dev", "--help"])
    assert result.exit_code == 0
    assert ".dirigent/state" in result.output
    assert "different instance" in result.output


def test_dev_help_offers_wiping_the_state_it_otherwise_keeps() -> None:
    """The default runs the instance that is there, and the destructive flag is visible in the help."""
    result = runner.invoke(app, ["dev", "--help"])
    assert result.exit_code == 0
    assert "--wipe-state" in plain(result.output)


def test_dev_clears_the_state_directory_it_owns(tmp_path: Path) -> None:
    """--wipe-state: a state directory dirigent named is emptied, database and artifacts both."""
    state = tmp_path / ".dirigent" / "state"
    (state / "artifacts").mkdir(parents=True)
    (state / "dirigent.db").write_text("an older schema")
    settings = Settings(database_url=f"sqlite+aiosqlite:///{state / 'dirigent.db'}")

    cleared = main.clear_state(settings)

    assert cleared == state.resolve(), "the directory that went is named, so the record can carry it"
    assert not state.exists(), "the artifacts go with the database: both live under the state directory"


def test_dev_refuses_to_clear_a_directory_it_did_not_name(tmp_path: Path) -> None:
    """A database configured somewhere else keeps the files beside it.

    A test fixture and the UI's end-to-end harness both put their database next to files they
    still need, so only a directory spelled .dirigent/state is ever removed.
    """
    beside = tmp_path / "fixtures.yaml"
    beside.write_text("a file the wipe must not take")
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}")

    assert main.clear_state(settings) is None, "nothing was cleared, so nothing is reported"
    assert beside.exists()


def test_dev_clears_nothing_on_a_first_start(tmp_path: Path) -> None:
    """A state directory that was never there is not a wipe, so the run stays quiet."""
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / '.dirigent' / 'state' / 'dirigent.db'}")
    assert main.clear_state(settings) is None


def test_dev_says_what_it_cleared(tmp_path: Path) -> None:
    """One record naming the directory, so a wiped database is never a surprise."""
    record = main.state_cleared(tmp_path / ".dirigent" / "state")
    assert record["kind"] == "process"
    assert record["message"] == "state cleared"
    assert record["process"] == "dev"
    assert record["state"] == str(tmp_path / ".dirigent" / "state")


def test_a_worker_can_be_assembled_from_the_installed_plugins() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///./dirigent-cli-test.db")
    worker, engine = build_worker(settings, concurrency=3, tags=["docker"], name="test-worker")
    assert worker.name == "test-worker"
    assert worker.concurrency == 3
    assert worker.tags == ["docker"]
    assert worker.engine.tags == ["docker"], "the tags a worker advertises are the ones its claim routes on"
    assert "http.request" in worker.services.host.operators
    assert engine.dialect.name == "sqlite"


def test_the_server_command_builds_an_importable_app() -> None:
    application = build_app()
    assert application.title == "dirigent"
    assert {"/health", "/health/ready", "/api/v1/system/info"} <= set(application.openapi()["paths"])


def test_help_lists_the_command_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("config", "db", "server", "dev", "worker", "scheduler"):
        assert command in result.output


def test_distribution_version_reports_missing_packages() -> None:
    assert distribution_version("no-such-distribution-anywhere") == "not installed"


def test_the_database_password_is_never_printed() -> None:
    settings = Settings(database_url="postgresql+asyncpg://dirigent:hunter2@db.example.org/dirigent")
    assert redacted_url(settings) == "postgresql+asyncpg://dirigent:***@db.example.org/dirigent"
    assert redacted_url(Settings(database_url="sqlite+aiosqlite:///./dirigent.db")).endswith("dirigent.db")


class TestHoistGlobals:
    """An option declared on dg may appear anywhere; hoisting must never steal a value."""

    def test_trailing_flag_is_hoisted(self) -> None:
        assert main.hoist_globals(["run", "--local", "p.yaml", "-v"]) == ["-v", "run", "--local", "p.yaml"]

    def test_bundled_count_is_hoisted(self) -> None:
        assert main.hoist_globals(["runs", "list", "-vv"]) == ["-vv", "runs", "list"]

    def test_debug_all_is_hoisted(self) -> None:
        assert main.hoist_globals(["run", "p.yaml", "--debug-all"]) == ["--debug-all", "run", "p.yaml"]

    def test_leading_flag_keeps_its_place(self) -> None:
        assert main.hoist_globals(["-v", "run", "p.yaml"]) == ["-v", "run", "p.yaml"]

    def test_value_of_an_option_is_not_stolen(self) -> None:
        argv = ["--token", "-v", "run", "p.yaml"]
        assert main.hoist_globals(argv) == argv

    def test_param_value_is_not_stolen(self) -> None:
        argv = ["run", "p.yaml", "-p", "-v"]
        assert main.hoist_globals(argv) == argv

    def test_tokens_after_double_dash_are_untouched(self) -> None:
        argv = ["run", "p.yaml", "--", "-v"]
        assert main.hoist_globals(argv) == argv

    def test_flag_after_boolean_flag_is_hoisted(self) -> None:
        assert main.hoist_globals(["runs", "logs", "abc", "--follow", "-v"]) == [
            "-v",
            "runs",
            "logs",
            "abc",
            "--follow",
        ]

    def test_an_output_written_after_the_command_carries_its_value_forward(self) -> None:
        """`dg run --local doc.yaml -o json` is what the help says is valid in any position."""
        assert main.hoist_globals(["run", "--local", "doc.yaml", "-o", "json"]) == [
            "-o",
            "json",
            "run",
            "--local",
            "doc.yaml",
        ]

    def test_a_server_is_named_after_the_command_and_still_reaches_the_group(self) -> None:
        assert main.hoist_globals(["runs", "list", "--url", "https://dg.example.org"]) == [
            "--url",
            "https://dg.example.org",
            "runs",
            "list",
        ]

    def test_an_option_joined_to_its_value_takes_no_second_token(self) -> None:
        """`--output=json` is one token, so the token after it belongs to the command."""
        assert main.hoist_globals(["runs", "list", "--output=json", "--limit", "5"]) == [
            "--output=json",
            "runs",
            "list",
            "--limit",
            "5",
        ]

    def test_an_output_that_is_another_options_value_is_left_alone(self) -> None:
        argv = ["run", "p.yaml", "-p", "-o"]
        assert main.hoist_globals(argv) == argv

    def test_a_commands_own_short_option_is_not_a_global_one(self) -> None:
        """`dg export NAME -f out.yaml` writes a file; -f belongs to the command."""
        argv = ["export", "nightly", "-f", "out.yaml"]
        assert main.hoist_globals(argv) == argv


def test_every_list_command_answers_to_a_hidden_ls() -> None:
    """Every group holding a `list` gains exactly one `ls` alias."""
    assert LIST_ALIASES == [
        "runs ls",
        "pipeline ls",
        "blocks ls",
        "connection ls",
        "schedule ls",
        "webhook ls",
        "trigger-document ls",
        "alerts rules ls",
        "admin user ls",
        "admin token ls",
    ]


def test_runs_ls_is_the_same_command_as_runs_list() -> None:
    aliased = runner.invoke(app, ["runs", "ls", "--help"])
    canonical = runner.invoke(app, ["runs", "list", "--help"])
    assert aliased.exit_code == 0
    assert "List runs, newest first" in aliased.output
    assert "List runs, newest first" in canonical.output


def test_the_alias_stays_out_of_the_help_that_teaches_the_names() -> None:
    listed = runner.invoke(app, ["runs", "--help"])
    assert listed.exit_code == 0
    assert "list" in listed.output
    assert " ls " not in listed.output, "the alias is for fingers, not for the help text"


def test_the_help_is_grouped_into_panels_in_the_order_of_a_working_day() -> None:
    """The six panels appear in PANEL_ORDER, whichever entries happen to be groups."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    positions = [result.output.index(panel) for panel in PANEL_ORDER]
    assert positions == sorted(positions), result.output


def test_accounts_and_tokens_moved_under_admin_and_workers_under_system() -> None:
    """Accounts and tokens answer under `dg admin`, the worker registry under `dg system`."""
    assert runner.invoke(app, ["admin", "user", "--help"]).exit_code == 0
    assert runner.invoke(app, ["admin", "token", "--help"]).exit_code == 0
    assert runner.invoke(app, ["system", "workers", "--help"]).exit_code == 0
    assert runner.invoke(app, ["user", "--help"]).exit_code != 0
    assert runner.invoke(app, ["token", "--help"]).exit_code != 0
    assert runner.invoke(app, ["workers", "--help"]).exit_code != 0


def test_a_schedule_takes_the_same_parameter_flags_as_a_run() -> None:
    """A schedule's overrides accept the same -p and -P flags as `dg run`."""
    # The declared parameters, not the rendered help, which a narrow terminal truncates.
    group = cast("click.Group", typer.main.get_command(triggers.schedule_app))
    command = group.commands["create"]
    flags = {name for parameter in command.params for name in parameter.opts}
    assert {"-p", "--param", "-P", "--params-file"} <= flags


def test_each_verbosity_level_names_what_it_adds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flag whose help does not say what it gives is a flag nobody reaches for."""
    monkeypatch.setenv("TERMINAL_WIDTH", "200")
    result = runner.invoke(app, ["--help"])
    # Help wraps to the terminal, so compare against the text with its wrapping removed.
    rendered = " ".join(result.output.split())
    assert "dirigent's own only" in rendered, "-v says whose logs it raises"
    assert "Engine internals" in rendered
    assert "every library's own logging" in rendered


def test_debug_all_sets_the_level_rather_than_only_lifting_the_caps() -> None:
    """A flag that only uncapped the libraries printed nothing when used on its own."""
    assert CliState(debug_all=True).level == "DEBUG"
    assert CliState(debug_all=True).floors == {}
    assert CliState(debug=True).level == "DEBUG"
    assert CliState(debug=True).floors != {}
    assert CliState(verbose=1).level == "INFO"
    assert CliState().level == "WARNING"


def test_the_named_debug_flag_is_hoisted_like_the_counted_one() -> None:
    assert main.hoist_globals(["run", "--local", "x.yaml", "-d"]) == ["-d", "run", "--local", "x.yaml"]
    assert main.hoist_globals(["run", "x", "--debug-all"]) == ["--debug-all", "run", "x"]


def test_serve_is_a_hidden_alias_for_the_server_command() -> None:
    """Muscle memory from mkdocs and jekyll lands somewhere, without a second name in the help."""
    aliased = runner.invoke(app, ["serve", "--help"])
    assert aliased.exit_code == 0
    assert aliased.output.count("scheduler") == runner.invoke(app, ["server", "--help"]).output.count("scheduler")
    listing = runner.invoke(app, ["--help"]).output
    assert " serve " not in listing, "the alias is hidden; server is the name"


def test_a_dev_instance_announces_itself_as_one_record(tmp_path: Path) -> None:
    """The banner is gone: what a person needs to start working is fields on a record."""
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'state' / 'dirigent.db'}")
    record = main.dev_started(settings, bound="http://127.0.0.1:3333", admin="dev", token="secret", migrated="0007")
    assert record["kind"] == "process"
    assert record["message"] == "starting"
    assert record["at"], "a record carries the moment it happened, or its time column reads absent"
    assert record["api"] == "http://127.0.0.1:3333"
    assert record["docs"] == "http://127.0.0.1:3333/docs"
    assert record["token"] == "secret", "the token is minted once, so the record is what carries it"
    assert record["migrated"] == "0007"


def test_a_dev_instance_that_minted_nothing_carries_no_token(tmp_path: Path) -> None:
    """An absent field is absent, rather than present and null."""
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'state' / 'dirigent.db'}")
    record = main.dev_started(settings, bound="http://127.0.0.1:3333", admin="dev", token=None, migrated=None)
    assert "token" not in record
    assert "migrated" not in record


def test_a_reader_that_goes_away_ends_the_stream_rather_than_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dg dev | dg format`` ends with ctrl-c reaching both, and the formatter exits first."""
    silenced: list[bool] = []

    class Closed:
        """A stdout whose reader has gone."""

        def write(self, text: str) -> int:
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self) -> None:  # pragma: no cover - never reached, write raises first
            raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(main.sys, "stdout", Closed())
    monkeypatch.setattr(main, "silence_stdout", lambda: silenced.append(True))
    main.emit(make("process", at=datetime.now(UTC), message="ready", process="dev"))
    assert silenced == [True], "the write is abandoned quietly and stdout is pointed at the void"


def test_dev_names_the_admin_that_exists_rather_than_the_one_it_would_have_made(tmp_path: Path) -> None:
    """After dg init the instance has its own admin, and dev must not name one that is absent."""
    import asyncio

    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from dirigent_cli import commands
    from dirigent_core import migrations

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'state' / 'dirigent.db'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    migrations.upgrade("head", settings)
    asyncio.run(commands.first_admin(settings, "morten", "a test password"))

    admin, token = asyncio.run(main.dev_admin(settings))

    assert admin == "morten", "dev named an account that does not exist"
    assert token is None, "the instance's own admin already had its token handed over"


@pytest.fixture
def nothing_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the server check at a port nothing on this machine is serving."""
    monkeypatch.setenv("DIRIGENT_PORT", "9")
    reset_settings_cache()


@pytest.fixture
def a_migrated_host(nothing_listening: None) -> None:
    """An instance whose schema exists, on a host running nothing else."""
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0


def test_health_says_a_database_with_no_schema_is_not_ready(tmp_path: Path, nothing_listening: None) -> None:
    """Reachable is not usable, and it is the first thing a new deployment gets wrong."""
    (tmp_path / "dirigent.db").touch()  # a zero-byte file is a valid, empty SQLite database

    result = runner.invoke(app, ["health"])

    assert result.exit_code == 1
    checks = of_kind(records(result.output), "check")
    database = next(check for check in checks if check["check"] == "database")
    assert database["status"] == "unhealthy"
    assert "dg db upgrade" in database["message"], "the one thing the operator has to do is not said"
    assert [check["check"] for check in checks] == ["database", "server"], (
        "a database with no schema cannot be asked about workers or schedules, so it is not"
    )


def test_health_reports_one_record_for_every_check_this_host_can_answer(a_migrated_host: None) -> None:
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0, result.output
    checks = of_kind(records(result.output), "check")
    assert [check["check"] for check in checks] == ["database", "worker", "scheduler", "server"]
    assert {check["status"] for check in checks} == {"healthy", "absent"}


def test_health_does_not_fail_on_what_this_host_simply_does_not_run(a_migrated_host: None) -> None:
    """No worker and no server here is a report, not a fault."""
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0, result.output
    absent = {check["check"]: check["status"] for check in of_kind(records(result.output), "check")}
    assert absent["worker"] == "absent"
    assert absent["server"] == "absent"


def test_naming_a_component_that_is_not_here_fails(a_migrated_host: None) -> None:
    """Naming it is the assertion that this host runs one, so finding none is a failure."""
    for component in ("worker", "server"):
        result = runner.invoke(app, ["health", component])
        assert result.exit_code == 1, f"{component}: {result.output}"
        [check] = of_kind(records(result.output), "check")
        assert (check["check"], check["status"], check["level"]) == (component, "absent", "error")


def test_asking_a_server_for_liveness_says_which_question_it_asked(a_migrated_host: None) -> None:
    result = runner.invoke(app, ["health", "server", "--liveness"])

    [check] = of_kind(records(result.output), "check")
    assert check["probe"] == "liveness"


def test_health_ends_with_the_verdict(a_migrated_host: None) -> None:
    """The last line is the answer, so a person does not have to add the lines up."""
    result = runner.invoke(app, ["health"])

    [summary] = of_kind(records(result.output), "health")
    assert (summary["checked"], summary["healthy"], summary["absent"], summary["unhealthy"]) == (4, 2, 2, 0)
    assert summary["message"] == "an instance's database is here, and nothing is running against it"


def test_a_machine_with_no_instance_says_so_in_one_line(nothing_listening: None) -> None:
    """Five lines about the absence of everything is noise; the answer is one sentence.

    Looking must also not leave an empty instance behind: opening a SQLite URL creates the
    file, so the check looks before it opens.
    """
    settings = Settings()
    assert settings.sqlite_path is not None

    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0, result.output
    [database] = of_kind(records(result.output), "check")
    assert (database["check"], database["status"]) == ("database", "absent")
    [summary] = of_kind(records(result.output), "health")
    assert summary["message"].startswith("there is no instance here")
    assert not settings.sqlite_path.exists(), "the health check created the database it came to look at"


def test_a_named_server_is_checked_even_where_no_instance_is(nothing_listening: None) -> None:
    """DG_URL or --url names the server this shell talks to, wherever its database lives."""
    result = runner.invoke(app, ["--url", "http://127.0.0.1:9", "health"])

    assert result.exit_code == 0, result.output
    [server] = [check for check in of_kind(records(result.output), "check") if check["check"] == "server"]
    assert server["status"] == "absent"
    assert "nothing is answering at 127.0.0.1:9" in server["message"]


def test_an_instance_with_no_schedules_is_a_healthy_scheduler(a_migrated_host: None) -> None:
    result = runner.invoke(app, ["health", "scheduler"])

    assert result.exit_code == 0, result.output
    [check] = of_kind(records(result.output), "check")
    assert (check["check"], check["status"]) == ("scheduler", "healthy")


# -- dg docker reap --------------------------------------------------------------


def a_daemon() -> bool:
    """Stand in for the reaper's PATH probe on a host that has the docker CLI."""
    return True


def no_daemon() -> bool:
    """Stand in for the reaper's PATH probe on a host that has none."""
    return False


def test_docker_reap_refuses_a_host_with_no_docker_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dirigent_cli.reaper.reachable", no_daemon)
    result = runner.invoke(app, ["docker", "reap"])
    assert result.exit_code == GUARD_EXIT
    assert "not on this host's PATH" in refusal(result.stdout)["message"]


def test_docker_reap_writes_one_record_per_project_it_took_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import UUID

    from dirigent_blocks.reap import Reaped

    run_id = UUID("0123456789abcdef0123456789abcdef")
    reaped = [Reaped(f"dirigent-{run_id.hex}", run_id, "failed", torn_down=True)]
    monkeypatch.setattr("dirigent_cli.reaper.reachable", a_daemon)

    async def one_pass(settings: object, sessions: object, *, dry_run: bool = False) -> list[Reaped]:
        return reaped

    monkeypatch.setattr("dirigent_cli.reaper.pass_once", one_pass)
    result = runner.invoke(app, ["docker", "reap"])
    assert result.exit_code == 0
    written = of_kind(records(result.stdout), "docker_reaped")
    assert [item["project"] for item in written] == [f"dirigent-{run_id.hex}"]
    assert written[0]["run_status"] == "failed"
    assert written[0]["torn_down"] is True
    assert written[0]["message"] == "reaped"


def test_a_dry_run_says_it_would_reap_and_takes_nothing_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import UUID

    from dirigent_blocks.reap import Reaped

    run_id = UUID("0123456789abcdef0123456789abcdef")
    seen: list[bool] = []
    monkeypatch.setattr("dirigent_cli.reaper.reachable", a_daemon)

    async def one_pass(settings: object, sessions: object, *, dry_run: bool = False) -> list[Reaped]:
        seen.append(dry_run)
        return [Reaped(f"dirigent-{run_id.hex}", run_id, "unknown", torn_down=False)]

    monkeypatch.setattr("dirigent_cli.reaper.pass_once", one_pass)
    result = runner.invoke(app, ["docker", "reap", "--dry-run"])
    assert result.exit_code == 0
    assert seen == [True]
    written = of_kind(records(result.stdout), "docker_reaped")
    assert written[0]["message"] == "would reap"
    assert written[0]["torn_down"] is False


def test_a_worker_on_a_host_with_no_daemon_runs_no_reaping_chore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dirigent_cli.reaper.reachable", no_daemon)
    worker, engine = build_worker(get_settings())
    assert worker.chores == []
    del engine


def test_a_docker_capable_worker_runs_the_reaping_chore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dirigent_cli.reaper.reachable", a_daemon)
    worker, engine = build_worker(get_settings())
    assert [chore.name for chore in worker.chores] == ["docker-reap"]
    assert worker.chores[0].interval == get_settings().docker_reap_interval
    del engine


def test_a_teardown_the_daemon_refused_is_reported_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import UUID

    from dirigent_blocks.reap import Reaped

    run_id = UUID("0123456789abcdef0123456789abcdef")
    monkeypatch.setattr("dirigent_cli.reaper.reachable", a_daemon)

    async def one_pass(settings: object, sessions: object, *, dry_run: bool = False) -> list[Reaped]:
        return [Reaped(f"dirigent-{run_id.hex}", run_id, "failed", torn_down=False, detail="network in use")]

    monkeypatch.setattr("dirigent_cli.reaper.pass_once", one_pass)
    result = runner.invoke(app, ["docker", "reap"])
    assert result.exit_code == 0
    written = of_kind(records(result.stdout), "docker_reaped")
    assert written[0]["message"] == "could not reap"
    assert written[0]["detail"] == "network in use"


def test_a_reaping_pass_keeps_the_workers_own_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dirigent_cli import reaper

    monkeypatch.setenv("HOME", "/home/worker")
    built = reaper.environment(tmp_path)
    assert built["HOME"] == "/home/worker"
