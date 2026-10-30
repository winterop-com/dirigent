"""``dg schedule``, ``dg watch``, ``dg source`` and ``dg alerts``, driven against a real server."""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from clisupport import asking_for_the_rendering, only, plain, refusal, rows
from dirigent_cli.main import app, hoist_globals
from dirigent_cli.output import alert_event, throttle_note, watching
from dirigent_core.config import CONFIG_FILE_ENV, Settings, reset_settings_cache

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: cli-demo
description: A pipeline with a typed parameter, so an override has a schema to be read against.
params:
  type: object
  properties:
    greeting:
      type: string
      default: hello from the cli
    count:
      type: integer
      default: 1
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, "${params.greeting}"]
"""

# Far enough away that the embedded scheduler cannot fire it mid-test.
NIGHTLY = "0 3 * * *"

#: The same pipeline, declaring the clock in the document so an apply materialises it.
SCHEDULED_DOCUMENT = (
    DOCUMENT
    + f"""
triggers:
  schedules:
    - code: nightly
      cron: "{NIGHTLY}"
"""
)

# Wide enough that rich never folds a token or a table cell.
CONSOLE_WIDTH = "200"


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Give every command a throwaway instance and a working directory of its own."""
    monkeypatch.setenv("COLUMNS", CONSOLE_WIDTH)
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


def apply_document(tmp_path: Path, text: str = DOCUMENT) -> None:
    """Write the demo document and apply it."""
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


def rows_of(*argv: str) -> list[dict[str, Any]]:
    """Run a listing with --json and read the row each record it wrote carries."""
    result = invoke(*argv, "--json")
    assert result.exit_code == 0, result.output
    return rows(result.stdout)


def test_a_cron_schedule_is_created_in_the_zone_it_names(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    result = machine("schedule", "create", "cli-demo", "nightly", "--cron", NIGHTLY, "--tz", "Europe/Oslo")
    assert result.exit_code == 0, result.output
    created = only(result.stdout, "schedule.created")
    assert created["code"] == "nightly"
    assert created["pipeline"] == "cli-demo"
    assert created["clock"] == NIGHTLY
    assert created["timezone"] == "Europe/Oslo"
    assert created["next_fire_at"], "the record says when it next fires"
    row = rows_of("schedule", "list", "cli-demo")[0]
    assert row["kind"] == "cron"
    assert row["cron"] == NIGHTLY
    assert row["timezone"] == "Europe/Oslo"


def test_an_interval_and_a_one_time_schedule_are_created_too(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("schedule", "create", "cli-demo", "hourly", "--interval", "1h").exit_code == 0
    assert invoke("schedule", "create", "cli-demo", "once", "--at", "2999-01-01T00:00:00Z").exit_code == 0
    kinds = {row["code"]: row["kind"] for row in rows_of("schedule", "list", "cli-demo")}
    assert kinds == {"hourly": "interval", "once": "one_time"}


def test_a_schedule_takes_exactly_one_clock(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    none = invoke("schedule", "create", "cli-demo", "never")
    assert none.exit_code == 1
    assert "exactly one of --cron, --interval, or --at" in plain(none.output)
    assert "(none given)" in plain(none.output)

    both = invoke("schedule", "create", "cli-demo", "both", "--cron", NIGHTLY, "--interval", "1h")
    assert both.exit_code == 1
    assert "--cron, --interval" in plain(both.output), "the refusal names the flags that were given"
    assert rows_of("schedule", "list", "cli-demo") == []


def test_a_parameter_override_is_coerced_by_the_pipelines_schema(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = invoke("schedule", "create", "cli-demo", "nightly", "--cron", NIGHTLY, "-p", "count=3")
    assert created.exit_code == 0, created.output
    row = rows_of("schedule", "list", "cli-demo")[0]
    assert row["params"] == {"count": 3}
    assert isinstance(row["params"]["count"], int), "the schema says integer, so the override is one"


def test_a_schedule_carries_the_priority_it_was_given(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = invoke("schedule", "create", "cli-demo", "nightly", "--cron", NIGHTLY, "--priority", "high")
    assert created.exit_code == 0, created.output
    assert rows_of("schedule", "list", "cli-demo")[0]["priority"] == "high"

    plain_one = invoke("schedule", "create", "cli-demo", "hourly", "--interval", "1h")
    assert plain_one.exit_code == 0, plain_one.output
    by_code = {row["code"]: row["priority"] for row in rows_of("schedule", "list", "cli-demo")}
    assert by_code["hourly"] is None, "omitted takes the pipeline's own"


def test_a_priority_that_is_not_one_names_the_vocabulary(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    refused = invoke("schedule", "create", "cli-demo", "nightly", "--cron", NIGHTLY, "--priority", "urgent")
    assert refused.exit_code == 1
    assert "'urgent' is not a priority" in plain(refused.output)
    assert rows_of("schedule", "list", "cli-demo") == []


def test_a_parameter_the_pipeline_never_declared_is_refused(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    result = invoke("schedule", "create", "cli-demo", "nightly", "--cron", NIGHTLY, "-p", "dya=2026-01-01")
    assert result.exit_code == 1
    assert "declares no parameter 'dya'" in plain(result.output)
    assert "it declares count, greeting" in plain(result.output)
    assert rows_of("schedule", "list", "cli-demo") == []


def test_apply_paused_lands_the_documents_schedule_paused_and_a_resume_survives_the_next_apply(
    tmp_path: Path, server: str
) -> None:
    path = tmp_path / "scheduled.yaml"
    path.write_text(SCHEDULED_DOCUMENT)
    assert invoke("apply", str(path), "--paused").exit_code == 0
    assert rows_of("schedule", "list", "cli-demo")[0]["paused"] is True

    assert invoke("schedule", "resume", "cli-demo", "nightly").exit_code == 0
    path.write_text(SCHEDULED_DOCUMENT.replace(NIGHTLY, "0 4 * * *"))
    assert invoke("apply", str(path)).exit_code == 0

    row = rows_of("schedule", "list", "cli-demo")[0]
    assert row["cron"] == "0 4 * * *"
    assert row["paused"] is False


#: A pipeline whose root sensor is watched, parked for longer than any test runs.
WATCHED_DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: cli-demo
steps:
  arrive:
    block: playground.arrive
    config: { after_pokes: 1000, rows: 1 }
triggers:
  watches:
    - code: follow
      step: arrive
"""


def test_a_watch_is_listed_shown_paused_and_resumed_as_records(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path, WATCHED_DOCUMENT)

    listed = machine("watch", "list", "cli-demo")
    assert listed.exit_code == 0, listed.output
    [row] = rows(listed.stdout, "watch")
    assert (row["code"], row["step"], row["paused"], row["managed"]) == ("follow", "arrive", False, True)
    armed = row["waiting_run_id"]
    assert armed is not None

    shown = machine("watch", "show", "cli-demo", "follow")
    assert shown.exit_code == 0, shown.output
    assert only(shown.stdout, "watch")["fields"]["waiting_run_id"] == armed

    paused = machine("watch", "pause", "cli-demo", "follow")
    assert paused.exit_code == 0, paused.output
    assert only(paused.stdout, "watch.paused")["code"] == "follow"
    assert rows(machine("watch", "list", "cli-demo").stdout, "watch")[0]["waiting_run_id"] is None

    resumed = machine("watch", "resume", "cli-demo", "follow")
    assert resumed.exit_code == 0, resumed.output
    record = only(resumed.stdout, "watch.resumed")
    assert record["waiting_run_id"] not in (None, armed)


def test_an_unknown_watch_is_a_refusal_record(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path, WATCHED_DOCUMENT)

    result = machine("watch", "show", "cli-demo", "nobody")

    assert result.exit_code != 0
    assert refusal(result.stdout)["code"] == "watch.unknown"


def test_a_plain_apply_lands_the_documents_schedule_running(tmp_path: Path, server: str) -> None:
    path = tmp_path / "scheduled.yaml"
    path.write_text(SCHEDULED_DOCUMENT)
    assert invoke("apply", str(path)).exit_code == 0
    assert rows_of("schedule", "list", "cli-demo")[0]["paused"] is False


def test_a_schedule_is_listed_paused_resumed_and_deleted(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("schedule", "create", "cli-demo", "hourly", "--interval", "1h").exit_code == 0

    listed = invoke("schedule", "list", "cli-demo")
    assert listed.exit_code == 0
    assert "hourly" in listed.output

    paused = only(machine("schedule", "pause", "cli-demo", "hourly").stdout, "schedule.paused")
    assert (paused["code"], paused["pipeline"]) == ("hourly", "cli-demo")
    assert rows_of("schedule", "list", "cli-demo")[0]["paused"] is True
    resumed = only(machine("schedule", "resume", "cli-demo", "hourly").stdout, "schedule.resumed")
    assert (resumed["code"], resumed["pipeline"]) == ("hourly", "cli-demo")
    assert resumed["next_fire_at"], "resuming says when it fires next, from the next slot"
    assert rows_of("schedule", "list", "cli-demo")[0]["paused"] is False

    assert invoke("schedule", "firings", "cli-demo", "hourly").exit_code == 0
    assert rows_of("schedule", "firings", "cli-demo", "hourly") == []

    deleted = only(machine("schedule", "delete", "cli-demo", "hourly").stdout, "schedule.deleted")
    assert (deleted["code"], deleted["pipeline"]) == ("hourly", "cli-demo")
    assert rows_of("schedule", "list", "cli-demo") == []
    assert invoke("schedule", "delete", "cli-demo", "hourly").exit_code == 1


def test_json_output_is_the_servers_response_and_not_the_table(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("schedule", "create", "cli-demo", "hourly", "--interval", "90m").exit_code == 0
    rows = rows_of("schedule", "list", "cli-demo")
    assert len(rows) == 1
    assert {"id", "kind", "managed", "created_at", "next_fire_at"} <= set(rows[0])
    assert rows[0]["interval"] == "1h30m", "the server's own humane duration, not a rendering of it"


def test_an_alert_rule_is_created_listed_and_deleted(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = machine(
        "alerts",
        "rules",
        "create",
        "nightly-failures",
        "--event",
        "run_failed",
        "--pipeline",
        "cli-demo",
        "--throttle",
        "15m",
    )
    assert created.exit_code == 0, created.output
    declared = only(created.stdout, "alert_rule.created")
    assert declared["code"] == "nightly-failures"
    assert declared["event"] == "run_failed"
    assert declared["scope"] == "cli-demo"
    assert declared["importance"] is None, "a rule that named none fires for every pipeline"
    assert declared["notifier"] == "log"
    assert declared["throttle"] == "15m"

    row = rows_of("alerts", "rules", "list")[0]
    assert row["event"] == "run_failed"
    assert row["scope"] == "pipeline"
    assert row["pipeline"] == "cli-demo"
    assert row["throttle"] == "15m"
    assert row["paused"] is False

    removed = machine("alerts", "rules", "delete", "nightly-failures")
    assert only(removed.stdout, "alert_rule.deleted")["code"] == "nightly-failures"
    assert rows_of("alerts", "rules", "list") == []
    assert invoke("alerts", "rules", "delete", "nightly-failures").exit_code == 1


def test_a_rule_names_the_least_importance_it_fires_for(server: str) -> None:
    created = machine(
        "alerts",
        "rules",
        "create",
        "page-ops",
        "--event",
        "run_failed",
        "--importance",
        "critical",
    )
    assert created.exit_code == 0, created.output
    assert only(created.stdout, "alert_rule.created")["importance"] == "critical"
    assert rows_of("alerts", "rules", "list")[0]["importance"] == "critical"


def test_an_importance_that_is_not_one_is_refused_by_name(server: str) -> None:
    refused = invoke(
        "alerts",
        "rules",
        "create",
        "page-ops",
        "--event",
        "run_failed",
        "--importance",
        "urgent",
    )
    assert refused.exit_code == 1
    assert "is not an importance" in plain(refused.output)
    assert "routine, normal, critical" in plain(refused.output)


def test_the_rules_table_says_the_importance_inside_the_scope_cell(server: str) -> None:
    invoke(
        "alerts",
        "rules",
        "create",
        "page-ops",
        "--event",
        "run_failed",
        "--importance",
        "critical",
    )
    invoke("alerts", "rules", "create", "log-all", "--event", "run_failed")
    listed = {row["code"]: row for row in rows_of("alerts", "rules", "list")}
    assert watching(listed["page-ops"]["scope"], listed["page-ops"]["importance"]) == "global, critical and above"
    assert watching(listed["log-all"]["scope"], listed["log-all"]["importance"]) == "global"


def test_the_rules_table_says_an_alert_event_in_the_words_every_surface_uses(server: str) -> None:
    invoke("alerts", "rules", "create", "page-ops", "--event", "run_completed_with_errors")
    row = rows_of("alerts", "rules", "list")[0]
    assert row["event"] == "run_completed_with_errors", "the record carries the wire's word"
    assert alert_event(row["event"]) == "Completed with errors"
    assert alert_event("run_failed") == "Failed"
    assert alert_event("run_succeeded") == "Succeeded"
    assert alert_event("run_stuck") == "Stuck"
    # An event a newer server has and this build cannot name still reads as itself.
    assert alert_event("run_abandoned") == "run_abandoned"


def test_the_alert_rules_table_says_an_unthrottled_rule_has_no_window(server: str) -> None:
    invoke("alerts", "rules", "create", "log-all", "--event", "run_failed")
    invoke("alerts", "rules", "create", "page-ops", "--event", "run_failed", "--throttle", "90m")
    listed = {row["code"]: row for row in rows_of("alerts", "rules", "list")}
    assert listed["log-all"]["throttle"] == "0s", "the record carries the window the server stored"
    assert throttle_note(listed["log-all"]["throttle"]) == "none"
    assert throttle_note(listed["page-ops"]["throttle"]) == "1h30m"
    # A window this build cannot read is left as the server spelled it rather than dropped.
    assert throttle_note("a fortnight") == "a fortnight"


def test_a_rule_takes_its_body_from_a_file(tmp_path: Path, server: str) -> None:
    body = tmp_path / "alert-body.md.j2"
    body.write_text("{{ run.pipeline }} failed: {{ run.error }}\n")
    created = machine(
        "alerts",
        "rules",
        "create",
        "nightly-failures",
        "--event",
        "run_failed",
        "--template",
        "{{ run.pipeline }} is unhappy",
        "--body-file",
        str(body),
    )
    assert created.exit_code == 0, created.output
    declared = only(created.stdout, "alert_rule.created")
    assert declared["template"] is True
    assert declared["body"] is True


def test_a_rule_takes_one_body_and_not_two(tmp_path: Path, server: str) -> None:
    body = tmp_path / "alert-body.md.j2"
    body.write_text("{{ run.error }}")
    refused = invoke(
        "alerts",
        "rules",
        "create",
        "nightly-failures",
        "--event",
        "run_failed",
        "--body",
        "{{ run.error }}",
        "--body-file",
        str(body),
    )
    assert refused.exit_code == 1
    assert "--body or --body-file" in plain(refused.output)


def test_a_rule_whose_template_does_not_compile_is_refused(server: str) -> None:
    refused = invoke(
        "alerts",
        "rules",
        "create",
        "nightly-failures",
        "--event",
        "run_failed",
        "--template",
        "{% endfor %}",
    )
    assert refused.exit_code == 1
    assert "not a Jinja template" in plain(refused.output)


def test_a_rule_is_paused_and_resumed_from_the_command_line(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    invoke("alerts", "rules", "create", "nightly-failures", "--event", "run_failed")

    held = machine("alerts", "rules", "pause", "nightly-failures")
    assert held.exit_code == 0, held.output
    assert only(held.stdout, "alert_rule.paused")["code"] == "nightly-failures"
    assert rows_of("alerts", "rules", "list")[0]["paused"] is True

    going = machine("alerts", "rules", "resume", "nightly-failures")
    assert only(going.stdout, "alert_rule.resumed")["code"] == "nightly-failures"
    assert rows_of("alerts", "rules", "list")[0]["paused"] is False


def test_a_notification_is_put_back_on_the_queue_from_the_command_line(server: str) -> None:
    queued = machine("alerts", "test", "--subject", "one to send again")
    notification_id = only(queued.stdout, "notification.queued")["notification_id"]

    again = machine("alerts", "retry", notification_id)
    assert again.exit_code == 0, again.output
    retried = only(again.stdout, "notification.retried")
    assert retried["notification_id"] == notification_id
    # A retry starts the delivery over rather than adding a try to a spent budget.
    assert retried["attempt"] == 0


def test_a_rule_delivers_through_the_notifier_its_connections_kind_names(server: str) -> None:
    stored = invoke("connection", "ensure", "webhook", "ops-hook", "--set", "url=https://ops.example.org/hooks")
    assert stored.exit_code == 0, stored.output
    created = machine("alerts", "rules", "create", "page-ops", "--event", "run_failed", "--connection", "ops-hook")
    assert created.exit_code == 0, created.output
    declared = only(created.stdout, "alert_rule.created")
    assert declared["connection"] == "ops-hook"
    assert declared["notifier"] == "webhook", "the sender follows from the connection's kind"
    row = rows_of("alerts", "rules", "list")[0]
    assert row["connection"] == "ops-hook"
    assert row["notifier"] == "webhook"


def test_a_rule_naming_a_connection_this_instance_does_not_have_is_refused(server: str) -> None:
    result = invoke("alerts", "rules", "create", "pager", "--event", "run_failed", "--connection", "carrier-pigeon")
    assert result.exit_code == 1
    assert "no connection coded 'carrier-pigeon'" in plain(result.output)


def test_a_test_message_naming_no_target_goes_through_the_queue_a_real_alert_takes(server: str) -> None:
    queued = machine("alerts", "test", "--subject", "a test from the cli")
    assert queued.exit_code == 0, queued.output
    accepted = only(queued.stdout, "notification.queued")
    assert accepted["notifier"] == "log"
    assert accepted["connection"] is None
    assert accepted["subject"] == "a test from the cli"

    rows = rows_of("alerts", "queue")
    assert [row["subject"] for row in rows] == ["a test from the cli"]
    assert rows[0]["notifier"] == "log"
    assert rows[0]["status"] == "pending"
    assert rows[0]["id"] == accepted["notification_id"]


def test_a_test_message_names_one_target_and_the_sender_follows(server: str) -> None:
    stored = invoke("connection", "ensure", "webhook", "ops-hook", "--set", "url=https://ops.example.org/hooks")
    assert stored.exit_code == 0, stored.output
    queued = machine("alerts", "test", "--connection", "ops-hook")
    assert queued.exit_code == 0, queued.output
    accepted = only(queued.stdout, "notification.queued")
    assert accepted["notifier"] == "webhook", "the sender follows from the connection's kind"
    assert accepted["connection"] == "ops-hook"
    assert rows_of("alerts", "queue")[0]["connection"] == "ops-hook"


def test_a_test_message_naming_a_connection_this_instance_does_not_have_is_refused(server: str) -> None:
    refused = invoke("alerts", "test", "--connection", "carrier-pigeon")
    assert refused.exit_code == 1
    assert "no connection coded 'carrier-pigeon'" in plain(refused.output)


#: A clock file over the pipeline the other documents here define.
TRIGGERS_DOCUMENT = """
format: dirigent/v1
kind: triggers
code: cli-clocks
name: CLI clocks
description: Clocks for a pipeline defined in another file.
pipeline: cli-demo
triggers:
  schedules:
    - code: ops-nightly
      cron: "0 2 * * *"
"""


def apply_triggers(tmp_path: Path, text: str = TRIGGERS_DOCUMENT) -> Any:
    """Write the triggers document and apply it, returning the invocation."""
    path = tmp_path / "clocks.yaml"
    path.write_text(text)
    return invoke("apply", str(path))


def test_apply_says_which_pipeline_a_triggers_document_schedules(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)

    result = apply_triggers(tmp_path)

    assert result.exit_code == 0, result.output
    assert "triggers for cli-demo" in plain(result.output)
    owners = {row["code"]: row["trigger_document"] for row in rows_of("schedule", "list", "cli-demo")}
    assert owners == {"ops-nightly": "cli-clocks"}


def test_apply_refuses_a_triggers_document_whose_pipeline_is_absent(tmp_path: Path, server: str) -> None:
    result = apply_triggers(tmp_path)

    assert result.exit_code == 1
    assert "no pipeline coded 'cli-demo' exists on this instance" in plain(result.output)


def test_trigger_document_list_and_show_name_what_the_document_owns(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    apply_triggers(tmp_path)

    listed = rows_of("trigger-document", "list")
    assert [(row["code"], row["pipeline"]) for row in listed] == [("cli-clocks", "cli-demo")]

    shown = invoke("trigger-document", "show", "cli-clocks", "--json")
    assert shown.exit_code == 0, shown.output
    assert only(shown.output, "trigger_document")["fields"]["schedules"] == ["ops-nightly"]


def test_trigger_document_delete_takes_the_rows_it_owned(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    apply_triggers(tmp_path)

    result = machine("trigger-document", "delete", "cli-clocks")

    assert result.exit_code == 0, result.output
    assert only(result.stdout, "trigger_document.deleted")["code"] == "cli-clocks"
    assert rows_of("schedule", "list", "cli-demo") == []
    assert rows_of("trigger-document", "list") == []


def test_validate_checks_a_triggers_document_offline_and_against_a_server(tmp_path: Path, server: str) -> None:
    path = tmp_path / "clocks.yaml"
    path.write_text(TRIGGERS_DOCUMENT)

    offline = invoke("validate", str(path))
    assert offline.exit_code == 0, offline.output
    assert "valid" in plain(offline.output)

    absent = invoke("validate", str(path), "--server")
    assert absent.exit_code == 1
    assert "no pipeline coded 'cli-demo'" in plain(absent.output)

    apply_document(tmp_path)
    present = invoke("validate", str(path), "--server")
    assert present.exit_code == 0, present.output


def test_run_local_refuses_a_triggers_document(tmp_path: Path) -> None:
    path = tmp_path / "clocks.yaml"
    path.write_text(TRIGGERS_DOCUMENT)

    result = invoke("run", "--local", str(path))

    assert result.exit_code == 1
    assert "cannot be run" in plain(result.output)
    assert "run the pipeline it names" in plain(result.output)


ENDPOINT_DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: cli-echo
steps:
  ask:
    source:
      kind: endpoint
      path: /cli-echo/{who}
      methods: [POST]
  answer:
    depends_on: [ask]
    reply:
      status: 200
      body: ${steps.ask.output.body}
"""


def apply_endpoint(tmp_path: Path) -> str:
    """Apply the endpoint document with records, and read the token the apply minted."""
    path = tmp_path / "echo.yaml"
    path.write_text(ENDPOINT_DOCUMENT)
    result = machine("apply", str(path))
    assert result.exit_code == 0, result.output
    applied = only(result.stdout, "apply")["fields"]
    assert applied["sources"]["created"] == ["ask"]
    return str(applied["sources"]["tokens"][0]["token"])


def test_an_apply_that_creates_a_source_hands_over_its_token_once(tmp_path: Path, server: str) -> None:
    path = tmp_path / "echo.yaml"
    path.write_text(ENDPOINT_DOCUMENT)
    result = invoke("apply", str(path))
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "/endpoints/cli-echo/{who}" in text
    assert "Authorization: Bearer" in text
    assert "Each token and signing secret is shown once." in text
    again = machine("apply", str(path))
    assert only(again.stdout, "apply")["fields"]["sources"]["tokens"] == [], "a reapply mints nothing"


def test_a_source_is_called_with_its_token_and_its_journal_read_back(tmp_path: Path, server: str) -> None:
    token = apply_endpoint(tmp_path)
    called = machine(
        "source",
        "call",
        "cli-echo",
        "ask",
        "-p",
        "who=ada",
        "-q",
        "tag=a",
        "--body",
        '{"said": "hi"}',
        "--source-token",
        token,
    )
    assert called.exit_code == 0, called.output
    answer = only(called.stdout, "source.called")
    assert answer["status"] == 200
    assert answer["url"].endswith("/endpoints/cli-echo/ada")
    assert answer["body"] == {"said": "hi"}, "the reply is the answer"

    refused = machine("source", "call", "cli-echo", "ask", "-p", "who=ada", "--text", "hi", "--source-token", "wrong")
    assert refused.exit_code == 1, "a refusal exits non-zero"
    assert only(refused.stdout, "source.called")["status"] == 401

    journal = rows_of("source", "inputs", "cli-echo", "ask")
    assert [(row["outcome"], row["status"]) for row in journal] == [("replied", 200)]


def test_a_form_is_called_as_a_form(tmp_path: Path, server: str) -> None:
    token = apply_endpoint(tmp_path)
    called = machine("source", "call", "cli-echo", "ask", "-p", "who=ada", "--form", "a=1", "--source-token", token)
    assert called.exit_code == 0, called.output


def test_a_call_takes_one_body_and_name_value_pairs(tmp_path: Path, server: str) -> None:
    apply_endpoint(tmp_path)
    twice = machine("source", "call", "cli-echo", "ask", "--body", "{}", "--text", "x")
    assert twice.exit_code == 1
    assert refusal(twice.stdout)["code"] == "cli.one_input_body"
    malformed = machine("source", "call", "cli-echo", "ask", "-p", "who")
    assert malformed.exit_code == 1
    assert refusal(malformed.stdout)["code"] == "cli.takes_name_equals_value"


def test_a_source_is_listed_paused_resumed_and_given_a_new_token(tmp_path: Path, server: str) -> None:
    old = apply_endpoint(tmp_path)
    listed = rows_of("source", "list")
    assert [(row["pipeline"], row["code"], row["state"]) for row in listed] == [("cli-echo", "ask", "listening")]
    assert "token" not in listed[0]
    assert rows_of("source", "list", "cli-echo")[0]["token_prefix"] == old[:8]

    paused = machine("source", "pause", "cli-echo", "ask")
    assert only(paused.stdout, "source.paused")["state"] == "paused"
    shown = machine("source", "show", "cli-echo", "ask")
    assert only(shown.stdout, "source")["fields"]["state"] == "paused"
    resumed = machine("source", "resume", "cli-echo", "ask")
    assert only(resumed.stdout, "source.resumed")["state"] == "listening"

    rotated = machine("source", "rotate-token", "cli-echo", "ask")
    assert rotated.exit_code == 0, rotated.output
    minted = only(rotated.stdout, "source.token_rotated")
    assert minted["token"] != old
    assert minted["url"].endswith("/endpoints/cli-echo/{who}")
    rendered = invoke("source", "rotate-token", "cli-echo", "ask")
    assert "This is the only time it is shown." in plain(rendered.output)


def test_a_signed_source_is_called_with_a_body_signed_by_its_secret(tmp_path: Path, server: str) -> None:
    path = tmp_path / "signed.yaml"
    path.write_text(ENDPOINT_DOCUMENT.replace("methods: [POST]", "methods: [POST]\n      auth: {kind: hmac}"))
    applied = machine("apply", str(path))
    assert applied.exit_code == 0, applied.output
    [minted] = only(applied.stdout, "apply")["fields"]["sources"]["tokens"]
    assert minted["auth"] == "hmac"
    args = ["source", "call", "cli-echo", "ask", "-p", "who=ada", "--body", '{"said": "hi"}']
    unsigned = machine(*args)
    assert only(unsigned.stdout, "source.called")["status"] == 401
    called = machine(*args, "--signing-secret", minted["token"])
    assert called.exit_code == 0, called.output
    assert only(called.stdout, "source.called")["status"] == 200
