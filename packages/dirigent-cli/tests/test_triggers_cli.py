"""``dg schedule``, ``dg webhook``, and ``dg alerts``, driven against a real server."""

import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from clisupport import asking_for_the_rendering, only, plain, rows
from dirigent_cli.main import app, hoist_globals
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

HOOK_URL = re.compile(r"http://127\.0\.0\.1:\d+/hooks/\S+")

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


def minted_url(output: str) -> str:
    """Read the one URL ``dg webhook create`` printed, token and all.

    Read plain: a URL with an escape sequence inside it is not a URL anything can POST to.
    """
    text = plain(output)
    found = HOOK_URL.findall(text)
    assert len(found) == 1, f"the token is printed once and only once:\n{text}"
    return str(found[0])


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


def test_a_webhook_prints_its_token_and_the_url_to_post_to_once(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    result = invoke("webhook", "create", "cli-demo", "from-github", "--map", "greeting=$.message.text")
    assert result.exit_code == 0, result.output
    token = minted_url(result.output).rsplit("/", 1)[1]
    assert plain(result.output).count(token) == 2, "once in the URL to POST to, and once on its own"
    assert "This token is shown once." in plain(result.output)
    assert "POST" in result.output

    row = rows_of("webhook", "list", "cli-demo")[0]
    assert row["params_from_payload"] == {"greeting": "$.message.text"}
    assert row["token_prefix"] == token[:8]
    assert "token" not in row


def test_a_webhook_carries_the_priority_it_was_given(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = invoke("webhook", "create", "cli-demo", "from-github", "--priority", "low")
    assert created.exit_code == 0, created.output
    assert rows_of("webhook", "list", "cli-demo")[0]["priority"] == "low"


def test_a_minted_webhook_token_survives_the_json_output(tmp_path: Path, server: str) -> None:
    """The token is shown once, so the spelling a script asked for must not drop it."""
    apply_document(tmp_path)
    result = invoke("--json", "webhook", "create", "cli-demo", "from-github")
    assert result.exit_code == 0, result.output
    minted = only(result.stdout, "webhook.created")
    assert minted["token"], "a script that minted a webhook can read its token"
    assert minted["url"], "and where to POST it"

    row = rows_of("webhook", "list", "cli-demo")[0]
    assert row["token_prefix"] == minted["token"][:8], "it is the token the instance stored"


def test_a_rotated_webhook_token_survives_the_json_output(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    invoke("webhook", "create", "cli-demo", "from-github")
    result = invoke("--json", "webhook", "rotate-token", "cli-demo", "from-github")
    assert result.exit_code == 0, result.output
    rotated = only(result.stdout, "webhook.token_rotated")
    assert rotated["token"]
    assert rows_of("webhook", "list", "cli-demo")[0]["token_prefix"] == rotated["token"][:8]


def test_a_mapping_without_an_equals_sign_is_refused(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    result = invoke("webhook", "create", "cli-demo", "from-github", "--map", "greeting")
    assert result.exit_code == 1
    assert "--map takes param=$.path.into.payload" in plain(result.output)
    assert rows_of("webhook", "list", "cli-demo") == []


def test_a_listing_shows_a_prefix_rather_than_the_token(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = invoke("webhook", "create", "cli-demo", "from-github")
    token = minted_url(created.output).rsplit("/", 1)[1]
    listed = invoke("webhook", "list", "cli-demo")
    assert listed.exit_code == 0
    assert "from-github" in listed.output
    assert f"{token[:8]}..." in plain(listed.output)
    assert token not in plain(listed.output), "the instance keeps only the hash; a listing shows the prefix"


def test_rotating_a_token_prints_a_different_one(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = invoke("webhook", "create", "cli-demo", "from-github")
    first = minted_url(created.output)
    rotated = invoke("webhook", "rotate-token", "cli-demo", "from-github")
    assert rotated.exit_code == 0
    assert "rotated" in rotated.output
    second = minted_url(rotated.output)
    assert second != first
    assert rows_of("webhook", "list", "cli-demo")[0]["token_prefix"] == second.rsplit("/", 1)[1][:8]


def test_deliveries_show_what_arrived_at_a_webhook(tmp_path: Path, server: str) -> None:
    import httpx2

    apply_document(tmp_path)
    created = invoke("webhook", "create", "cli-demo", "from-github", "--map", "greeting=$.message.text")
    url = minted_url(created.output)
    delivered = httpx2.post(url, json={"message": {"text": "hello"}}, timeout=30.0)
    assert delivered.status_code == 201, delivered.text

    listed = invoke("webhook", "deliveries", "cli-demo", "from-github")
    assert listed.exit_code == 0
    assert "accepted" in plain(listed.output)
    rows = rows_of("webhook", "deliveries", "cli-demo", "from-github")
    assert [row["outcome"] for row in rows] == ["accepted"]
    assert rows[0]["mapped_params"] == {"greeting": "hello"}


def test_a_webhook_is_deleted(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    assert invoke("webhook", "create", "cli-demo", "from-github").exit_code == 0
    deleted = only(machine("webhook", "delete", "cli-demo", "from-github").stdout, "webhook.deleted")
    assert (deleted["code"], deleted["pipeline"]) == ("from-github", "cli-demo")
    assert rows_of("webhook", "list", "cli-demo") == []
    assert invoke("webhook", "delete", "cli-demo", "from-github").exit_code == 1


def test_an_alert_rule_is_created_listed_and_deleted(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    created = machine(
        "alerts",
        "rules",
        "create",
        "nightly-failures",
        "--event",
        "run_failed",
        "--notifier",
        "log",
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
        "--notifier",
        "log",
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
        "--notifier",
        "log",
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
        "--notifier",
        "log",
        "--template",
        "{% endfor %}",
    )
    assert refused.exit_code == 1
    assert "not a Jinja template" in plain(refused.output)


def test_a_rule_is_paused_and_resumed_from_the_command_line(tmp_path: Path, server: str) -> None:
    apply_document(tmp_path)
    invoke("alerts", "rules", "create", "nightly-failures", "--event", "run_failed", "--notifier", "log")

    held = machine("alerts", "rules", "pause", "nightly-failures")
    assert held.exit_code == 0, held.output
    assert only(held.stdout, "alert_rule.paused")["code"] == "nightly-failures"
    assert rows_of("alerts", "rules", "list")[0]["paused"] is True

    going = machine("alerts", "rules", "resume", "nightly-failures")
    assert only(going.stdout, "alert_rule.resumed")["code"] == "nightly-failures"
    assert rows_of("alerts", "rules", "list")[0]["paused"] is False


def test_a_notification_is_put_back_on_the_queue_from_the_command_line(server: str) -> None:
    queued = machine("alerts", "test", "log", "--subject", "one to send again")
    notification_id = only(queued.stdout, "notification.queued")["notification_id"]

    again = machine("alerts", "retry", notification_id)
    assert again.exit_code == 0, again.output
    retried = only(again.stdout, "notification.retried")
    assert retried["notification_id"] == notification_id
    # A retry starts the delivery over rather than adding a try to a spent budget.
    assert retried["attempt"] == 0


def test_a_rule_naming_a_notifier_this_instance_does_not_have_is_refused(server: str) -> None:
    result = invoke("alerts", "rules", "create", "pager", "--event", "run_failed", "--notifier", "carrier-pigeon")
    assert result.exit_code == 1
    assert "no notifier 'carrier-pigeon' is installed" in plain(result.output)


def test_a_test_message_goes_through_the_queue_a_real_alert_takes(server: str) -> None:
    queued = machine("alerts", "test", "log", "--subject", "a test from the cli")
    assert queued.exit_code == 0, queued.output
    accepted = only(queued.stdout, "notification.queued")
    assert accepted["notifier"] == "log"
    assert accepted["subject"] == "a test from the cli"

    rows = rows_of("alerts", "queue")
    assert [row["subject"] for row in rows] == ["a test from the cli"]
    assert rows[0]["notifier"] == "log"
    assert rows[0]["status"] == "pending"
    assert rows[0]["id"] == accepted["notification_id"]


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
