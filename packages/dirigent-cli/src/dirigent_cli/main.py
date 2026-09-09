"""The dirigent command line: installed as `dirigent` and as the short alias `dg`."""

import os
import shutil
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TextIO, cast

import typer
from pydantic import ValidationError
from typer import _click, rich_utils
from typer.core import TyperGroup

from dirigent_cli import commands, triggers
from dirigent_cli.aliases import add_alias, add_list_aliases
from dirigent_cli.context import CliState, state_of
from dirigent_cli.formatters import DEFAULT, names
from dirigent_cli.output import configure, detail_mode, emit_fact, emit_problem, emit_rendered, refuse
from dirigent_client.enums import UserRole
from dirigent_core import migrations
from dirigent_core.config import STATE_DIR, Settings, get_settings, redacted_url, reset_settings_cache
from dirigent_core.logging import LOG_FORMAT_ENV, configure_logging, silence_stdout
from dirigent_core.protocol import FORMATS, Format, Record, make
from dirigent_core.telemetry import configure_telemetry

if TYPE_CHECKING:
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

    from dirigent_cli.health import Check
    from dirigent_cli.stream import Sink
    from dirigent_common import JsonMap
    from dirigent_core import retention
    from dirigent_core.worker import Worker

#: Help is capped rather than stretched: a panel the width of a wide terminal is unreadable.
rich_utils.MAX_WIDTH = 100

RUN_PANEL = "Run"
DEFINE_PANEL = "Define"
CONNECT_PANEL = "Connect"
TRIGGER_PANEL = "Triggers"
PROCESS_PANEL = "Processes"
ADMIN_PANEL = "Administration"

PANEL_ORDER = (RUN_PANEL, DEFINE_PANEL, CONNECT_PANEL, TRIGGER_PANEL, PROCESS_PANEL, ADMIN_PANEL)


class PanelOrderedGroup(TyperGroup):
    """A group whose help panels follow PANEL_ORDER.

    Typer renders a panel where its first command appears and lists every plain command
    before every subcommand group, so panel order otherwise depends on which entries
    happen to be groups.
    """

    # Typer vendors its own click; the signature must match the base class or this is a
    # new method rather than an override.
    def list_commands(self, ctx: _click.Context) -> list[str]:
        """List the commands panel by panel, keeping registration order inside each panel."""

        def rank(name: str) -> int:
            command = self.get_command(ctx, name)
            panel = getattr(command, "rich_help_panel", None)
            return PANEL_ORDER.index(panel) if panel in PANEL_ORDER else len(PANEL_ORDER)

        return sorted(super().list_commands(ctx), key=rank)


app = typer.Typer(
    name="dirigent",
    cls=PanelOrderedGroup,
    help="A pipeline orchestrator. Pipelines are documents; blocks are what they run.",
    no_args_is_help=True,
    add_completion=True,
)

db_app = typer.Typer(name="db", help="Database schema management.", no_args_is_help=True)
config_app = typer.Typer(name="config", help="Inspect the effective configuration.", no_args_is_help=True)
health_app = typer.Typer(name="health", help="Process-side checks: everything this host runs, or one part.")
docker_app = typer.Typer(name="docker", help="The docker daemon this host's worker uses.", no_args_is_help=True)

app.add_typer(commands.runs_app, rich_help_panel=RUN_PANEL)
app.add_typer(commands.pipeline_app, rich_help_panel=DEFINE_PANEL)
app.add_typer(commands.blocks_app, rich_help_panel=DEFINE_PANEL)
app.add_typer(commands.schema_app, rich_help_panel=DEFINE_PANEL)
app.add_typer(commands.connection_app, rich_help_panel=CONNECT_PANEL)
app.add_typer(triggers.schedule_app, rich_help_panel=TRIGGER_PANEL)
app.add_typer(triggers.webhook_app, rich_help_panel=TRIGGER_PANEL)
app.add_typer(triggers.trigger_document_app, rich_help_panel=TRIGGER_PANEL)
app.add_typer(triggers.alerts_app, rich_help_panel=TRIGGER_PANEL)
app.add_typer(health_app, rich_help_panel=PROCESS_PANEL)
app.add_typer(docker_app, rich_help_panel=PROCESS_PANEL)
app.add_typer(db_app, rich_help_panel=ADMIN_PANEL)
app.add_typer(config_app, rich_help_panel=ADMIN_PANEL)
app.add_typer(commands.auth_app, rich_help_panel=ADMIN_PANEL)
app.add_typer(commands.system_app, rich_help_panel=ADMIN_PANEL)
app.add_typer(commands.admin_app, rich_help_panel=ADMIN_PANEL)

app.command("run", rich_help_panel=RUN_PANEL)(commands.run_command)
app.command("backfill", rich_help_panel=RUN_PANEL)(commands.backfill_command)
app.command("init", rich_help_panel=DEFINE_PANEL)(commands.init_command)
app.command("apply", rich_help_panel=DEFINE_PANEL)(commands.apply_command)
app.command("validate", rich_help_panel=DEFINE_PANEL)(commands.validate_command)
app.command("export", rich_help_panel=DEFINE_PANEL)(commands.export_command)


def _say_version(asked: bool) -> None:
    """Answer --version with one plain line, the way every CLI does, and stop."""
    if asked:
        typer.echo(f"dg {distribution_version('dirigent-cli')}")
        raise typer.Exit


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_say_version, is_eager=True, help="Print dg's version and exit."),
    ] = False,
    url: Annotated[str | None, typer.Option("--url", help="The server to talk to.")] = None,
    token: Annotated[str | None, typer.Option("--token", help="The bearer token to present.")] = None,
    profile: Annotated[str | None, typer.Option("--profile", help="Which profile to use.")] = None,
    verbose: Annotated[
        int,
        typer.Option("-v", "--verbose", count=True, help="Engine events and API calls, dirigent's own only."),
    ] = 0,
    debug: Annotated[
        bool,
        typer.Option("--debug", "-d", help="Engine internals: claims, references, probes, leases."),
    ] = False,
    debug_all: Annotated[
        bool,
        typer.Option("--debug-all", help="Everything, including every library's own logging."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write JSON. The same as --output json."),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("-o", "--output", help="Output to write: json (the default) or console."),
    ] = None,
) -> None:
    """Resolve which server the CLI talks to and how loud to be, before any command runs.

    Precedence is flags, then DG_URL / DG_TOKEN / DIRIGENT_LOG_LEVEL, then the profile.
    """
    ctx.obj = CliState(
        url=url,
        token=token,
        profile=profile,
        verbose=verbose,
        debug=debug,
        debug_all=debug_all,
        output=resolve_output(output, json_output=json_output),
    )
    ctx.obj.configure_output()


def resolve_output(named: str | None, *, json_output: bool) -> Format:
    """Resolve the output: the flag, then the environment, then the terminal.

    ``--json`` is the same request as ``--output json``, and the environment is where a
    container says it once. Unasked, a terminal gets the rendering and anything else gets
    NDJSON: a pipe, a container's log, an agent's shell and CI are never terminals, so a
    script reads records without asking, and a person reads lines without asking.
    """
    chosen = named or ("json" if json_output else None) or os.environ.get(LOG_FORMAT_ENV)
    if chosen is None:
        return "console" if sys.stdout.isatty() else "json"
    resolved = chosen.lower()
    if resolved not in FORMATS:
        # The output that was asked for is exactly what is missing, so the refusal is written
        # in the default one rather than in the one that was named.
        emit_problem(
            f"{chosen!r} is not an output format",
            status=2,
            title="Not an output format",
            problems=[f"the outputs are {', '.join(FORMATS)}"],
        )
        raise typer.Exit(code=2)
    return cast("Format", resolved)


DEV_ADMIN = "dev"
DEV_PASSWORD = "dirigent-dev"  # noqa: S105
DEV_TOKEN_NAME = "dev"

SCHEDULER_ENV = "DIRIGENT_SCHEDULER_ENABLED"

UI_ENV = "DIRIGENT_UI_ENABLED"


def distribution_version(name: str) -> str:
    """Read an installed distribution's version, or report that it is absent."""
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


@app.command(name="format", rich_help_panel=RUN_PANEL)
def format_command(
    formatter: Annotated[
        str | None,
        typer.Argument(help=f"Which formatter renders the records. One of: {', '.join(names())}."),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("-f", "--file", help="A file holding one record per line; standard input when omitted."),
    ] = None,
) -> None:
    """Render an NDJSON stream for reading, from a pipe or from a file.

    A line that is not a record is passed through untouched, so a mixed log still reads.
    """
    from dirigent_cli.formatters import looks_like_a_template, registry, rendered

    # Rendering is what this command is. Every other command writes NDJSON unless asked
    # otherwise, and inheriting that default here would mute the console doing the work.
    configure(output="console", detail=detail_mode())
    registered = registry()
    named = DEFAULT if formatter is None else formatter
    if named not in registered:
        if looks_like_a_template(named):
            # docker and kubectl take a template here, so the habit is worth answering rather
            # than refusing. Picking fields out of a record is what jq does, over this stream.
            emit_problem(
                "a formatter renders whole records; it takes no template",
                status=2,
                title="Not a formatter",
                problems=["to pick fields out, use jq:  dg dev | jq -r '.step'"],
            )
        else:
            # The formatter that would render this refusal is the one that is missing, so it
            # is written in the default output rather than rendered.
            emit_problem(
                f"{named!r} is not a formatter",
                status=2,
                title="Not a formatter",
                problems=[f"the formatters are {', '.join(registered)}"],
            )
        raise typer.Exit(code=2)
    lines = file.read_text().splitlines() if file is not None else sys.stdin
    for item in rendered(lines, registered[named]):
        emit_rendered(item)


@config_app.command("show")
def config_show() -> None:
    """Show the effective configuration, with secrets redacted."""
    settings = get_settings()
    emit_fact(
        "config",
        message="effective configuration",
        settings={
            name: ("***" if name == "secret_key" and value is not None else str(value))
            for name, value in settings.model_dump().items()
        },
    )


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Argument(help="The revision to reach; the newest when omitted.")] = "head",
) -> None:
    """Bring the database schema up to a revision, creating it when empty."""
    settings = get_settings()
    migrations.upgrade(revision, settings)
    emit_fact(
        "db.upgraded",
        message="upgraded",
        database=redacted_url(settings),
        target=revision,
        revision=migrations.current_revision(settings),
    )


@db_app.command("current")
def db_current() -> None:
    """Show the revision the database is stamped with."""
    settings = get_settings()
    current = migrations.current_revision(settings)
    head = migrations.head_revision(settings)
    if current is None:
        refuse("the database has never been migrated", title="Not migrated", problems=["run dg db upgrade"])
        raise typer.Exit(code=1)
    emit_fact(
        "db.revision",
        message="at head" if current == head else "behind head",
        revision=current,
        head=head,
        at_head=current == head,
    )


@db_app.command("history")
def db_history() -> None:
    """Show the migration history."""
    emit_fact("db.history", message="migration history", history=migrations.history(get_settings()).rstrip())


@commands.connection_app.command("ensure")
def connection_ensure(
    kind_id: Annotated[str, typer.Argument(metavar="KIND", help="The connection kind, such as s3.")],
    code: Annotated[str, typer.Argument(help="What to call it; documents reference this code.")],
    name: Annotated[str | None, typer.Option(help="A human title for this connection.")] = None,
    set_value: Annotated[list[str] | None, typer.Option("--set", help="field=value, repeatable.")] = None,
    description: Annotated[str | None, typer.Option(help="What this credential is for.")] = None,
) -> None:
    """Write a connection straight to the database, creating it or bringing it to this config.

    Process-side the way ``dg db upgrade`` is: it reads the database URL and the instance key
    rather than a token, so a one-shot container can put a credential in place before
    anything else starts. The config is validated against its kind and its secret half sealed
    with the instance key exactly as the API does it, so the row is indistinguishable from one
    made through ``dg connection create``.

    The row is brought to what the arguments say, whole: a field left out is cleared.
    """
    import asyncio

    from dirigent_core.plugins import load_plugin_host
    from dirigent_core.secrets import REDACTED, SecretBox, SecretError, redact, secret_fields

    settings = get_settings()
    kinds = load_plugin_host().connection_kinds
    kind = kinds.get(kind_id)
    if kind is None:
        known = ", ".join(sorted(kinds)) or "none are installed"
        commands.fail(f"no connection kind {kind_id!r} is installed ({known})")
    model = kind.config_model
    config = commands.parse_params(set_value, schema=model.model_json_schema())
    try:
        validated = model.model_validate(config)
    except ValidationError as error:
        # include_input=False: the input here is a credential, and pydantic's default error
        # payload echoes the value that failed.
        commands.fail(f"{code} is not a usable {kind_id} connection: {error.errors(include_input=False)}")
    key = settings.secret_key.get_secret_value() if settings.secret_key else None
    try:
        public, envelope, key_id = SecretBox(key).encrypt_config(model, validated)
    except SecretError as error:
        commands.fail(str(error))
    written = asyncio.run(
        store_connection(
            settings,
            code=code,
            kind=kind_id,
            name=name,
            description=description,
            config=public,
            envelope=envelope,
            key_id=key_id,
        )
    )
    # A sealed field is not on the row at all, so the marker is put back: the record says the
    # credential is set without saying what it is.
    visible = redact(model, dict(public))
    for field in secret_fields(model):
        visible.setdefault(field, REDACTED if envelope is not None else None)
    emit_fact(
        f"connection.{written}",
        message=written,
        code=code,
        connection_kind=kind_id,
        name=name,
        description=description,
        config=visible,
    )


async def store_connection(
    settings: Settings,
    *,
    code: str,
    kind: str,
    name: str | None,
    description: str | None,
    config: "JsonMap",
    envelope: bytes | None,
    key_id: str | None,
) -> str:
    """Insert or overwrite one connection row, and say which of the two happened."""
    import sqlalchemy as sa

    from dirigent_core.database import create_engine, create_session_factory, session_scope
    from dirigent_core.models import Connection

    engine = create_engine(settings)
    try:
        async with session_scope(create_session_factory(engine)) as session:
            found = await session.execute(sa.select(Connection).where(Connection.code == code))
            row = found.scalar_one_or_none()
            written = "updated" if row is not None else "created"
            if row is None:
                row = Connection(code=code)
                session.add(row)
            row.kind = kind
            row.name = name
            row.description = description
            row.config = config
            row.secret_envelope = envelope
            row.secret_key_id = key_id
        return written
    finally:
        await engine.dispose()


@health_app.callback(invoke_without_command=True)
def health_here(ctx: typer.Context) -> None:
    """Check the instance this shell resolves: database, workers, schedules, the server.

    A part that is simply not there is reported and does not fail the command; naming one
    is what asserts it should be running.
    """
    if ctx.invoked_subcommand is not None:
        return
    from dirigent_cli.health import every_check, named_server

    state = state_of(ctx)
    server = named_server(url=state.url, profile=state.profile)
    _checked(every_check(get_settings(), server=server), asserted=False, summarise=True)


@health_app.command("worker")
def health_worker() -> None:
    """Say whether a worker on this host is still heartbeating, and exit 0 or 1."""
    from dirigent_cli.health import worker_health

    _checked([worker_health(get_settings())], asserted=True)


@health_app.command("server")
def health_server(
    ctx: typer.Context,
    liveness: Annotated[
        bool, typer.Option("--liveness", help="Ask whether the process answers at all, not whether it is ready.")
    ] = False,
) -> None:
    """Ask the server -- the named one, or this host's own -- for its readiness, and exit 0 or 1."""
    from dirigent_cli.health import named_server, server_check

    state = state_of(ctx)
    server = named_server(url=state.url, profile=state.profile)
    check = server_check(get_settings(), server=server, probe="liveness" if liveness else "readiness")
    _checked([check], asserted=True)


@health_app.command("scheduler")
def health_scheduler() -> None:
    """Say whether the schedules that should have fired have fired, and exit 0 or 1."""
    from dirigent_cli.health import scheduler_health

    _checked([scheduler_health(get_settings())], asserted=True)


@health_app.command("database")
def health_database() -> None:
    """Say whether the configured database answers, and exit 0 or 1."""
    from dirigent_cli.health import database_health

    _checked([database_health(get_settings())], asserted=True)


def _checked(checks: "Sequence[Check]", *, asserted: bool, summarise: bool = False) -> None:
    """Write one record per check, then the verdict, and exit 1 if any of them failed."""
    from dirigent_cli.output import output_mode
    from dirigent_cli.stream import Sink

    sink = Sink(output_mode())
    failed = False
    for check in checks:
        failed = failed or check.failed(asserted=asserted)
        sink.event(
            "check",
            level="error" if check.failed(asserted=asserted) else "info",
            message=check.detail,
            check=check.check,
            status=check.status,
            probe=check.probe,
        )
    if summarise:
        from dirigent_cli.health import verdict

        sink.event("health", **verdict(checks))
    if failed:
        raise typer.Exit(code=1)


def _level(ctx: typer.Context, settings: Settings) -> str:
    """Choose the level a process entry point runs at: -v first, then its own settings."""
    state = ctx.find_object(CliState)
    return state.level if state is not None and state.verbose else settings.log_level


def _cap_foreign(ctx: typer.Context) -> bool:
    """Report whether a raised verbosity should stay pointed at dirigent's own loggers.

    A process at its configured level logs whatever it is configured to, uvicorn's access
    lines included; a person who asked for more detail asked for dirigent's, and only
    --debug-all asks for everybody's.
    """
    state = ctx.find_object(CliState)
    if state is None or state.debug_all:
        return False
    return bool(state.verbose or state.debug)


@app.command(name="prune", rich_help_panel=ADMIN_PANEL)
def prune_command(
    ctx: typer.Context,
    runs: Annotated[str | None, typer.Option(help="Keep settled runs younger than this, such as 30d.")] = None,
    logs: Annotated[str | None, typer.Option(help="Keep log entries younger than this.")] = None,
    deliveries: Annotated[str | None, typer.Option(help="Keep webhook deliveries younger than this.")] = None,
    firings: Annotated[str | None, typer.Option(help="Keep schedule firings younger than this.")] = None,
    notifications: Annotated[str | None, typer.Option(help="Keep sent alerts younger than this.")] = None,
    scratch: Annotated[
        bool,
        typer.Option("--scratch/--no-scratch", help="Delete a pruned run's artifacts from storage too."),
    ] = True,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report what would go without deleting it.")] = False,
) -> None:
    """Delete what the retention ages have outlived, against this host's database.

    An age given here beats the configured one, and a family with neither is not pruned:
    a prune deletes what it was asked to delete and never guesses at an age.
    """
    import asyncio

    settings = get_settings()
    state = state_of(ctx)
    try:
        policy = _prune_policy(settings, runs, logs, deliveries, firings, notifications, scratch=scratch)
    except ValueError as error:
        refuse(str(error), status=2, title="Invalid age")
        raise typer.Exit(code=2) from error
    asyncio.run(_prune(settings, policy, state, dry_run=dry_run))


def _prune_policy(
    settings: Settings,
    runs: str | None,
    logs: str | None,
    deliveries: str | None,
    firings: str | None,
    notifications: str | None,
    *,
    scratch: bool,
) -> "retention.Policy":
    """Resolve each family's age: the flag, then the setting, then not pruned at all."""
    from dirigent_common import parse_duration
    from dirigent_core import retention

    def age(given: str | None, configured: timedelta | None) -> timedelta | None:
        return cast("timedelta", parse_duration(given)) if given is not None else configured

    return retention.Policy(
        runs=age(runs, settings.retention_runs),
        logs=age(logs, settings.retention_logs),
        deliveries=age(deliveries, settings.retention_deliveries),
        firings=age(firings, settings.retention_firings),
        notifications=age(notifications, settings.retention_notifications),
        scratch=scratch,
    )


async def _prune(settings: Settings, policy: "retention.Policy", state: CliState, *, dry_run: bool) -> None:
    """Sweep directly against the configured database, and write what went."""
    from dirigent_core import retention
    from dirigent_core.database import create_engine, create_session_factory, session_scope
    from dirigent_core.engine.services import EngineServices
    from dirigent_core.plugins import load_plugin_host
    from dirigent_core.scheduler import prune as prune_all

    out = commands.sink(state)
    if not retention.configured(policy):
        refuse(
            "no family has an age, so there is nothing to prune",
            status=2,
            title="Nothing configured",
            problems=["give --runs, --logs, --deliveries, --firings or --notifications, or configure one"],
        )
        raise typer.Exit(code=2)
    engine = create_engine(settings)
    try:
        sessions = create_session_factory(engine)
        services = EngineServices.build(settings, load_plugin_host())
        if dry_run:
            async with session_scope(sessions) as session:
                counts = await retention.counted(session, policy)
            out.event("prune", message="would prune", dry_run=True, total=sum(counts.values()), **counts)
            return
        swept = await prune_all(sessions, services, policy)
        out.event(
            "prune",
            message="pruned",
            dry_run=False,
            total=swept.total,
            artifacts=swept.scratch_deleted,
            unreachable=swept.scratch_failed or None,
            **swept.counts,
        )
    finally:
        await engine.dispose()


@app.command(rich_help_panel=PROCESS_PANEL)
def server(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option(help="Address to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to bind.")] = None,
    reload: Annotated[bool, typer.Option(help="Reload on source changes.")] = False,
    scheduler: Annotated[
        bool,
        typer.Option("--scheduler/--no-scheduler", help="Embed the scheduler, or leave it to its own process."),
    ] = True,
    ui: Annotated[
        bool | None,
        typer.Option(
            "--ui/--no-ui", help="Serve the web UI, or run as an API only; the ui_enabled setting decides when omitted."
        ),
    ] = None,
) -> None:
    """Run the API server, with the scheduler embedded unless it is isolated."""
    import os

    import uvicorn

    if not scheduler:
        # Must travel through the environment: uvicorn builds the app in a reloader
        # subprocess, where an argument to this function would not survive.
        os.environ[SCHEDULER_ENV] = "false"
        reset_settings_cache()
    if ui is not None:
        # The same subprocess constraint as the scheduler flag.
        os.environ[UI_ENV] = "true" if ui else "false"
        reset_settings_cache()
    settings = get_settings()
    _process_logging(_level(ctx, settings), cap_foreign=_cap_foreign(ctx))
    if settings.is_sqlite and settings.scheduler_enabled:
        refuse(
            "dg server embeds the scheduler, and leadership is a PostgreSQL advisory lock: on SQLite "
            "nothing stops a second server double-firing every schedule",
            status=commands.GUARD_EXIT,
            title="SQLite cannot elect a leader",
            problems=[
                "use dg dev for the standalone mode",
                "or pass --no-scheduler",
                "or point DIRIGENT_DATABASE_URL at PostgreSQL",
            ],
        )
        raise typer.Exit(code=commands.GUARD_EXIT)
    uvicorn.run(
        "dirigent_cli.main:build_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@docker_app.command("reap")
def docker_reap(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Say what would be taken down, and take nothing down."),
    ] = False,
) -> None:
    """Take down compose stacks this host's daemon still holds for runs that have ended.

    The same pass a worker runs on `docker_reap_interval`, on demand. It sees only the daemon
    this host's environment names, which with one daemon per worker is that worker's own stacks.
    """
    import asyncio

    from dirigent_cli import reaper
    from dirigent_cli.output import output_mode
    from dirigent_cli.stream import Sink

    settings = get_settings()
    _process_logging(_level(ctx, settings), cap_foreign=_cap_foreign(ctx), stream=sys.stderr)
    if not reaper.reachable():
        refuse(
            "docker is not on this host's PATH, so there is no daemon to reap stacks from",
            status=commands.GUARD_EXIT,
            title="No docker daemon",
        )
        raise typer.Exit(code=commands.GUARD_EXIT)
    asyncio.run(_docker_reap(settings, Sink(output_mode()), dry_run=dry_run))


async def _docker_reap(settings: Settings, sink: "Sink", *, dry_run: bool) -> None:
    """Run one reaping pass and write a record per project it acted on."""
    from dirigent_cli import reaper
    from dirigent_core.database import create_engine, create_session_factory

    engine = create_engine(settings)
    try:
        reaped = await reaper.pass_once(settings, create_session_factory(engine), dry_run=dry_run)
    finally:
        await engine.dispose()
    for one in reaped:
        sink.event("docker_reaped", message=reaper.outcome(one, dry_run=dry_run), **reaper.record(one))


def build_app() -> "FastAPI":
    """Build the ASGI application; uvicorn calls this as its factory."""
    from dirigent_server import create_app

    return create_app(get_settings())


def build_worker(
    settings: Settings,
    *,
    concurrency: int | None = None,
    tags: list[str] | None = None,
    name: str | None = None,
) -> tuple["Worker", "AsyncEngine"]:
    """Assemble a worker from the installed plugins and the configured database."""
    from dirigent_cli import reaper
    from dirigent_core.database import create_engine, create_session_factory
    from dirigent_core.engine import EngineServices
    from dirigent_core.plugins import load_plugin_host
    from dirigent_core.worker import Worker

    services = EngineServices.build(settings, load_plugin_host())
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    reaping = reaper.chore(settings, sessions)
    worker = Worker(
        sessions,
        services,
        name=name,
        concurrency=concurrency,
        tags=tags,
        chores=[reaping] if reaping is not None else [],
    )
    return worker, engine


@commands.user_app.command("create")
def user_create(
    username: Annotated[str, typer.Argument(help="The account to create.")],
    role: Annotated[UserRole, typer.Option("--role", help="What the account may do.")],
    password: Annotated[str | None, typer.Option(help="Its password; prompted for when omitted.")] = None,
    email: Annotated[str | None, typer.Option(help="Its email address, which is unique across accounts.")] = None,
) -> None:
    """Create a local account against this host's database, which is the first-run path.

    The role is named on every account; `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD` creates the
    first admin unattended.
    """
    import asyncio

    settings = get_settings()
    secret = password or typer.prompt("password", hide_input=True, confirmation_prompt=True)
    created = asyncio.run(_create_user(settings, username, secret, role, email))
    emit_fact(
        "user.created",
        message="created",
        username=created,
        role=role.value,
        database=redacted_url(settings),
        hint="log in with dg auth login, or mint a token with dg admin token create",
    )


async def _create_user(
    settings: Settings, username: str, password: str, role: UserRole, email: str | None = None
) -> str:
    """Create one account directly against the configured database."""
    from dirigent_core.auth import AuthError, create_user
    from dirigent_core.database import create_engine, create_session_factory, session_scope

    engine = create_engine(settings)
    try:
        async with session_scope(create_session_factory(engine)) as session:
            user = await create_user(session, username, password, role=role, email=email)
            return user.username
    except AuthError as error:
        refuse(str(error))
        raise typer.Exit(code=1) from error
    finally:
        await engine.dispose()


@app.command(rich_help_panel=PROCESS_PANEL)
def dev(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option(help="Address to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to bind.")] = None,
    ui: Annotated[
        bool | None,
        typer.Option(
            "--ui/--no-ui", help="Serve the web UI, or run as an API only; the ui_enabled setting decides when omitted."
        ),
    ] = None,
    wipe_state: Annotated[
        bool,
        typer.Option(
            "--wipe-state/--keep-state",
            help="Delete the state directory before starting, instead of running the instance that is there.",
        ),
    ] = False,
) -> None:
    """Run the API and an embedded worker in one process, on SQLite, with no dependencies.

    The database and the artifacts live in .dirigent/state under the working directory, so
    starting this somewhere else means a different instance, with none of the same runs.
    An instance that is there, made by dg init or by an earlier start, is the one that runs;
    --wipe-state deletes it first, and only a directory dirigent named itself is removed.
    """
    import asyncio
    import os

    if ui is not None:
        os.environ[UI_ENV] = "true" if ui else "false"
        reset_settings_cache()
    state = ctx.find_object(CliState)
    settings = get_settings()
    # A developer convenience starts its own logging at WARNING and -v is what asks for more,
    # while a named DIRIGENT_LOG_LEVEL still wins.
    _process_logging(
        state.level if state is not None else "WARNING",
        cap_foreign=state is None or not state.debug_all,
    )
    if not settings.is_sqlite:
        refuse(
            "dg dev is the SQLite standalone mode",
            status=commands.GUARD_EXIT,
            title="Not SQLite",
            problems=["use dg server on PostgreSQL"],
        )
        raise typer.Exit(code=commands.GUARD_EXIT)
    if wipe_state:
        cleared = clear_state(settings)
        if cleared is not None:
            emit(state_cleared(cleared))
    migrated = _migrate_quietly(settings)
    admin, token = asyncio.run(dev_admin(settings))
    bound = f"http://{host or settings.host}:{port or settings.port}"
    emit(dev_started(settings, bound=bound, admin=admin, token=token, migrated=migrated))
    asyncio.run(_dev(settings, host or settings.host, port or settings.port))


def clear_state(settings: Settings) -> Path | None:
    """Delete the state directory this instance owns, naming it, or report that none went.

    Only a directory spelled ``.dirigent/state`` is removed. A database configuration pointed
    somewhere else belongs to whoever pointed it there -- a test fixture and the UI's
    end-to-end harness both keep their database beside files they still need -- so the wipe
    is refused rather than guessed at.
    """
    database = settings.sqlite_path
    if database is None:
        return None
    directory = database.parent.resolve()
    if directory.parts[-2:] != Path(STATE_DIR).parts:
        return None
    if not directory.exists():
        return None
    shutil.rmtree(directory)
    return directory


def state_cleared(directory: Path) -> Record:
    """Build the record saying the state went, as --wipe-state asked.

    Emitted only when something was actually deleted, so a wipe of an empty machine stays
    quiet.
    """
    return make(
        "process",
        at=datetime.now(UTC),
        message="state cleared",
        process="dev",
        state=str(directory),
    )


def _migrate_quietly(settings: Settings) -> str | None:
    """Bring the schema up to date, and name the revision only when something moved."""
    head = migrations.head_revision(settings)
    if migrations.current_revision(settings) == head:
        return None
    migrations.upgrade("head", settings)
    return head


def dev_started(
    settings: Settings, *, bound: str, admin: str | None, token: str | None, migrated: str | None
) -> Record:
    """Build the record carrying what a person needs to start working against a dev instance.

    The token is minted once and never shown again, so it is a field on this record rather
    than something only a rendering ever held.
    """
    state = settings.sqlite_path
    fields: dict[str, Any] = {"process": "dev", "api": bound, "docs": f"{bound}/docs", "admin": admin}
    if state is not None:
        fields["state"] = str(state.parent.resolve())
    if token is not None:
        fields["token"] = token
    if migrated is not None:
        fields["migrated"] = migrated
    return make("process", at=datetime.now(UTC), message="starting", **fields)


def emit(record: Record) -> None:
    """Write one record to the stream in this invocation's output, and flush it.

    A reader that has gone ends the stream rather than the process: the pipe is closed and
    every later write goes to the void, while shutdown runs to completion.
    """
    from dirigent_cli.output import output_mode
    from dirigent_cli.stream import Sink

    try:
        Sink(output_mode()).write(record)
    except BrokenPipeError:
        silence_stdout()


def _process_logging(level: str, *, cap_foreign: bool, stream: TextIO | None = None) -> None:
    """Point a process's logging at its stream, in this invocation's output.

    The console grammar is the one records are rendered in, so a process read at a terminal
    is one stream of lines, and a process read by a pipe is one stream of records.
    """
    from dirigent_cli.output import output_mode
    from dirigent_cli.stream import ansi

    mode = output_mode()
    configure_logging(
        level,
        mode,
        cap_foreign=cap_foreign,
        stream=stream if stream is not None else sys.stdout,
        paint=ansi if mode == "console" else None,
    )


async def dev_admin(settings: Settings) -> tuple[str | None, str | None]:
    """Name the admin to log in as, and mint it a token where one is owed.

    An empty instance gets the development admin made for it. One that already has accounts
    -- ``dg init`` made it, or a person did -- keeps them: this names the admin that is
    there rather than one that is not, and mints nothing, because that account's token was
    handed over when it was created.
    """
    from dirigent_core.auth import create_user, find_user, issue_token, list_tokens, list_users
    from dirigent_core.database import create_engine, create_session_factory, session_scope

    engine = create_engine(settings)
    try:
        sessions = create_session_factory(engine)
        async with session_scope(sessions) as session:
            existing = await list_users(session)
            if existing:
                return (existing[0].username, None)
            await create_user(session, DEV_ADMIN, DEV_PASSWORD, role=UserRole.ADMIN, name="Development admin")
            user = await find_user(session, DEV_ADMIN)
            if user is None:  # pragma: no cover - it was just created
                return (None, None)
            if any(token.name == DEV_TOKEN_NAME and token.revoked_at is None for token in await list_tokens(session)):
                return (DEV_ADMIN, None)
            issued = await issue_token(session, user, name=DEV_TOKEN_NAME)
            return (DEV_ADMIN, issued.secret.get_secret_value())
    finally:
        await engine.dispose()


async def _dev(settings: Settings, host: str, port: int) -> None:
    """Run the API, the scheduler, and a worker as tasks in one event loop.

    The scheduler is started by the application's own lifespan, not here.
    """
    import asyncio

    import uvicorn

    from dirigent_core.worker import install_signal_handlers

    worker, engine = build_worker(settings, concurrency=None, tags=None, name=None)
    install_signal_handlers(worker)
    server_config = uvicorn.Config(build_app(), host=host, port=port, log_config=None)
    api = uvicorn.Server(server_config)
    worker_task = asyncio.create_task(worker.run())
    ready = asyncio.create_task(_announce_ready(api))
    try:
        await api.serve()
    finally:
        ready.cancel()
        worker.request_stop()
        await worker_task
        await engine.dispose()


async def _announce_ready(api: "uvicorn.Server") -> None:
    """Say ready once the port is actually accepting, and not a moment before."""
    import asyncio

    while not api.started:
        await asyncio.sleep(0.05)
    emit(make("process", at=datetime.now(UTC), message="ready", process="dev"))


@app.command(rich_help_panel=PROCESS_PANEL)
def worker(
    ctx: typer.Context,
    concurrency: Annotated[int | None, typer.Option(help="How many block calls run at a time.")] = None,
    tag: Annotated[list[str] | None, typer.Option(help="Capability tag this worker advertises.")] = None,
    name: Annotated[str | None, typer.Option(help="Registry name; defaults to hostname and pid.")] = None,
) -> None:
    """Run a worker: claim due work, execute it, probe what is waiting, and drain on SIGTERM."""
    import asyncio

    settings = get_settings()
    _process_logging(_level(ctx, settings), cap_foreign=_cap_foreign(ctx))
    configure_telemetry(settings)
    if settings.is_sqlite:
        refuse(
            "dg worker refuses to start on SQLite: its claim fallback is only correct with exactly one process",
            status=commands.GUARD_EXIT,
            title="SQLite claims only one process",
            problems=["use dg dev", "or point DIRIGENT_DATABASE_URL at PostgreSQL"],
        )
        raise typer.Exit(code=commands.GUARD_EXIT)
    asyncio.run(_worker(settings, concurrency, tag, name))


async def _worker(settings: Settings, concurrency: int | None, tags: list[str] | None, name: str | None) -> None:
    """Run one worker until it is asked to drain."""
    from dirigent_core.worker import install_signal_handlers

    worker, engine = build_worker(settings, concurrency=concurrency, tags=tags, name=name)
    install_signal_handlers(worker)
    try:
        await worker.run()
    finally:
        await engine.dispose()


@app.command(name="scheduler", rich_help_panel=PROCESS_PANEL)
def scheduler_command(ctx: typer.Context) -> None:
    """Run the scheduler on its own: take leadership, then turn clock time into runs.

    Leadership is an advisory lock, so starting this beside a server that still embeds a
    scheduler is harmless: the second one stands by.
    """
    import asyncio

    settings = get_settings()
    _process_logging(_level(ctx, settings), cap_foreign=_cap_foreign(ctx))
    configure_telemetry(settings)
    if settings.is_sqlite:
        refuse(
            "dg scheduler refuses to start on SQLite: leadership is a PostgreSQL advisory lock, and "
            "without one nothing stops a second scheduler double-firing every schedule",
            status=commands.GUARD_EXIT,
            title="SQLite cannot elect a leader",
            problems=["use dg dev", "or point DIRIGENT_DATABASE_URL at PostgreSQL"],
        )
        raise typer.Exit(code=commands.GUARD_EXIT)
    emit(
        make(
            "process",
            at=datetime.now(UTC),
            message="waiting for leadership",
            process="scheduler",
            database=redacted_url(settings),
        )
    )
    asyncio.run(_scheduler(settings))


async def _scheduler(settings: Settings) -> None:
    """Run one scheduler until it is asked to stop, releasing leadership on the way out."""
    from dirigent_core.database import create_engine, create_session_factory
    from dirigent_core.engine import EngineServices
    from dirigent_core.plugins import load_plugin_host
    from dirigent_core.scheduler import Scheduler, install_signal_handlers

    services = EngineServices.build(settings, load_plugin_host())
    engine = create_engine(settings)
    clock = Scheduler(create_session_factory(engine), services)
    install_signal_handlers(clock)
    try:
        await clock.run()
    finally:
        await engine.dispose()


#: Options declared on the group, which a person expects to work in any position.
GLOBAL_TOKENS = frozenset({"-v", "-vv", "-vvv", "--verbose", "-d", "--debug", "--debug-all", "--json", "--timestamps"})

#: The options declared on ``dg`` that take a value. Hoisting one moves its value with it.
GLOBAL_VALUE_OPTIONS = frozenset({"--url", "--token", "--profile", "-o", "--output"})

# Options that consume the next token; a verbosity-looking token after one of these is a
# value, not a flag. A new value-taking option must be added here.
VALUE_OPTIONS = frozenset(
    {
        "--url",
        "--token",
        "--profile",
        "-p",
        "--param",
        "-P",
        "--params-file",
        "-o",
        "--output",
        "-f",
        "--file",
        "--as",
        "--cron",
        "--interval",
        "--at",
        "--tz",
        "--step",
        "--template",
        "--connections",
        "--concurrency",
        "--tag",
        "--event",
        "--notifier",
        "--status",
        "--pipeline",
        "--since",
        "--enable-unsafe",
    }
)


def hoist_globals(argv: list[str]) -> list[str]:
    """Move the options declared on ``dg`` in front of the subcommand, values and all.

    Click reads a group's options only before the subcommand, so without this ``dg run
    --local doc.yaml -o json`` is refused for an option the help says is global. One that
    takes a value carries the next token with it, unless it was written as ``--url=...``.
    """
    hoisted: list[str] = []
    rest: list[str] = []
    previous = ""
    wants_value = False
    for index, token in enumerate(argv):
        if token == "--":
            rest.extend(argv[index:])
            break
        if wants_value:
            hoisted.append(token)
            wants_value = False
        elif token.split("=", 1)[0] in GLOBAL_VALUE_OPTIONS and previous not in VALUE_OPTIONS:
            hoisted.append(token)
            wants_value = "=" not in token
        elif token in GLOBAL_TOKENS and previous not in VALUE_OPTIONS:
            hoisted.append(token)
        else:
            rest.append(token)
        previous = token
    return hoisted + rest


# `serve` is what mkdocs and jekyll call it, and there is no reason to make anyone stop and
# think; `server` stays the name, so the three process commands keep naming a role.
add_alias(app, "server", "serve")

# Must stay last: a command registered after this walk does not get an alias.
LIST_ALIASES = add_list_aliases(app)


def run() -> None:
    """Entry point for the `dirigent` and `dg` console scripts."""
    app(args=hoist_globals(sys.argv[1:]))
