"""The commands that talk to a server: definitions, execution, catalog, connections, admin."""

import asyncio
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final, NoReturn, cast
from uuid import UUID

import typer
import yaml
from rich.markup import escape

from dirigent_cli import schemas
from dirigent_cli.context import CliState, Session, client_for, state_of
from dirigent_cli.graph import GraphStep, render_graph, steps_of_document
from dirigent_cli.local import (
    ConnectionSpec,
    LocalError,
    LocalOutcome,
    LocalStarted,
    LogLine,
    SchemaSpec,
    Spill,
    StepTransition,
    load_connection_specs,
    load_schema_specs,
    run_document,
)
from dirigent_cli.output import (
    Detail,
    age,
    configure,
    console,
    elapsed,
    emit_event,
    emit_fact,
    emit_one,
    emit_problem,
    emit_record,
    emit_records,
    error_console,
    fields,
    flagged,
    json_mode,
    moment,
    muted,
    output_mode,
    prioritised,
    refuse,
    render_bool,
    stream_line,
    styled,
    table,
)
from dirigent_cli.params import ParamError, build_params
from dirigent_cli.project import (
    COMPOSE_TEMPLATE_NAME,
    ProjectError,
    check_template,
    find_project,
    scaffold,
    write_token_env,
)
from dirigent_cli.scaffold import ScaffoldedRecord, ScaffoldError, ScaffoldRecord, scaffold_pack
from dirigent_cli.sources import Document, SourceError, looks_like_a_document, read_document, read_path
from dirigent_cli.stream import Sink, track_steps, use_scratch_prefix
from dirigent_cli.timing import RunProfile, attempt_timing, by_step, profile, step_timing
from dirigent_client import (
    ApplyResult,
    AttemptEvent,
    AttemptOut,
    AttemptStatus,
    BackfillAccepted,
    BlockKind,
    Catalog,
    DocumentKind,
    ItemOut,
    LogEntryOut,
    LogLevel,
    NotFound,
    Page,
    PlanAction,
    ProvenanceSource,
    RunDetail,
    RunOut,
    RunPriority,
    RunReport,
    RunStatus,
    ValidationIssue,
)
from dirigent_common import JsonMap
from dirigent_core import migrations
from dirigent_core.config import STATE_DIR, Settings
from dirigent_core.documents import (
    DocumentError,
    TriggerTarget,
    load_pipeline_text,
    load_text,
    validate_against_catalog,
)
from dirigent_core.engine.definition import PipelineDefinition, TriggersDefinition, load_definition
from dirigent_core.engine.runs import RunWindow
from dirigent_core.engine.state import in_execution_order
from dirigent_core.schemas import code_from_id

RUNS_PAGE = 50

#: How many of a failed attempt's own log lines the diagnosis prints.
FAILURE_LOG_LINES = 20

# Refused before any work started. Distinct from 1 ("it ran and the answer was no") and
# from Click's own 2 for a usage error.
GUARD_EXIT = 3

pipeline_app = typer.Typer(name="pipeline", help="Inspect and manage stored pipelines.", no_args_is_help=True)
runs_app = typer.Typer(name="runs", help="Runs held by this instance.", no_args_is_help=True)
connection_app = typer.Typer(
    name="connection", help="Named credential records of contributed kinds.", no_args_is_help=True
)
schema_app = typer.Typer(name="schema", help="Named JSON Schemas the instance holds.", no_args_is_help=True)
blocks_app = typer.Typer(name="blocks", help="The block catalog every plugin contributes to.", no_args_is_help=True)
token_app = typer.Typer(name="token", help="API tokens.", no_args_is_help=True)
user_app = typer.Typer(name="user", help="Local accounts.", no_args_is_help=True)
auth_app = typer.Typer(name="auth", help="Logging in, and which identity the CLI holds.", no_args_is_help=True)
system_app = typer.Typer(name="system", help="What this instance is, and whether it is healthy.", no_args_is_help=True)
admin_app = typer.Typer(name="admin", help="Accounts and API tokens.", no_args_is_help=True)
admin_app.add_typer(user_app)
admin_app.add_typer(token_app)


#: The largest page any listing will answer, so a walk asks for as few round trips as it can.
MAX_PAGE = 500


def paged[T](fetch: Callable[[str | None, int], Page[T]], limit: int | None) -> Iterator[T]:
    """Yield a listing's items across pages until the caller's limit, hiding the cursor."""
    after: str | None = None
    remaining = limit
    while True:
        size = MAX_PAGE if remaining is None else min(remaining, MAX_PAGE)
        page = fetch(after, size)
        for row in page.items:
            yield row
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    return
        if page.next is None:
            return
        after = page.next


def fail(message: str) -> NoReturn:
    """Write a refusal the CLI decided on as a record, and exit non-zero."""
    refuse(message)
    raise typer.Exit(code=1)


def ask(label: str, *, hide: bool = False) -> str:
    """Read one value from the terminal, refusing under --json where nothing can answer.

    Prompting is done here rather than by Click's ``prompt=True`` so that a machine-mode
    invocation fails with a JSON object instead of blocking on a terminal that is a pipe.
    """
    if json_mode():
        fail(f"--json cannot prompt for {label}; pass it as an option")
    return str(typer.prompt(label, hide_input=hide))


def _apply_one(
    dg: Session,
    document: Document,
    *,
    code: str | None,
    dry_run: bool,
    paused: bool = False,
    source: ProvenanceSource | None = None,
) -> ApplyResult:
    """Apply one document and return the server's result."""
    return dg.call(
        dg.pipelines.apply(
            cast("dict[str, Any]", yaml.safe_load(document.text)),
            code=code,
            source=source if source is not None else document.source,
            source_ref=document.ref,
            dry_run=dry_run,
            pause_schedules=paused,
        )
    )


def _print_plan(result: ApplyResult, origin: str) -> bool:
    """Print one apply result the way a plan reads, and say whether it was accepted."""
    plan = result.plan
    if plan.action is PlanAction.INVALID:
        console.print(f"[red]invalid[/]  {plan.code}  [dim]({result.kind.value}, {origin})[/]")
        for issue in plan.issues:
            console.print(f"  [red]-[/] {issue.location}: {issue.message}")
        return False
    version = result.version or plan.next_version
    detail = (
        f"triggers for {plan.pipeline}"
        if result.kind is DocumentKind.TRIGGERS
        else (f"version {version}" if version else "")
    )
    console.print(f"{styled(plan.action.value):<10} {plan.code}  [dim]{detail} ({origin})[/]")
    for warning in plan.warnings:
        console.print(f"  [yellow]![/] {warning.location}: {warning.message}")
    diff = plan.diff
    if diff and plan.action is PlanAction.UPDATE:
        for label, changed in (
            ("added", diff.steps_added),
            ("removed", diff.steps_removed),
            ("changed", diff.steps_changed),
        ):
            if changed:
                console.print(f"  [dim]steps {label}:[/] {', '.join(changed)}")
        for label, flag in (("params", diff.params_changed), ("triggers", diff.triggers_changed)):
            if flag:
                console.print(f"  [dim]{label} changed[/]")
    return True


def _print_graph(steps: Sequence[GraphStep], title: str = "steps") -> None:
    """Print a pipeline's shape: roots at the margin, each step under what it waits for."""
    lines = render_graph(steps)
    if not lines:
        return
    console.print(f"\n[bold]{escape(title)}[/]  {muted('each step under the last one it waits for')}")
    for line in lines:
        console.print(f"  {escape(line)}", highlight=False)


def graph_steps(definition: PipelineDefinition) -> list[GraphStep]:
    """Read a definition's steps in the shape the tree is drawn from."""
    return [
        GraphStep(name=name, block=step.block, depends_on=tuple(step.depends_on), rule=step.rule.value)
        for name, step in definition.steps.items()
    ]


def _print_definition_graph(definition: PipelineDefinition) -> None:
    """Print the shape of a document, which needs no instance to be worth seeing."""
    _print_graph(graph_steps(definition), title=f"steps of {definition.code}")


def _runnable(text: str) -> PipelineDefinition:
    """Read a document a local run is about to execute, refusing the kind that cannot be run."""
    definition = load_text(text)
    if not isinstance(definition, PipelineDefinition):
        fail("a triggers document declares clocks for a pipeline and cannot be run; run the pipeline it names")
    return definition


def _print_document_graph(text: str) -> None:
    """Print the shape of a document read from a file, when it parses at all."""
    try:
        definition = load_text(text)
    except DocumentError:
        return
    if isinstance(definition, PipelineDefinition):
        _print_definition_graph(definition)


def apply_command(
    ctx: typer.Context,
    reference: Annotated[str | None, typer.Argument(help="A file, a URL, or - for standard input.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the plan without writing anything.")] = False,
    as_code: Annotated[str | None, typer.Option("--as", help="Register under a different code.")] = None,
    paused: Annotated[
        bool,
        typer.Option("--paused", help="Create the schedules this apply mints paused; existing ones are untouched."),
    ] = False,
    prune: Annotated[
        bool,
        typer.Option(
            "--prune",
            help="Reconcile: deactivate directory-provenance pipelines the project no longer holds. "
            "Marks this apply's documents with directory provenance, so a later prune knows its own.",
        ),
    ] = False,
) -> None:
    """Apply a pipeline document, or every document in the project when given none.

    `--paused` governs what this apply brings into being: a schedule it creates is created
    paused, and a schedule the instance already holds keeps the state it is in. `--prune`
    reconciles the whole project: what the project no longer holds is deactivated, never
    deleted, and only pipelines a directory apply wrote are ever touched.
    """
    state = state_of(ctx)
    if prune and reference is not None:
        fail("--prune reconciles a whole project, so it cannot be used with a single document")
    documents = _documents_to_apply(reference, as_code)
    source = ProvenanceSource.DIRECTORY if prune else None
    with client_for(state) as dg:
        results = [
            (
                _apply_one(dg, document, code=as_code, dry_run=dry_run, paused=paused, source=source),
                document.label,
            )
            for document in documents
        ]
        pruned = None
        if prune:
            keep = [result.plan.code for result, _ in results]
            pruned = dg.call(dg.pipelines.prune(keep, dry_run=dry_run))
    if state_of(ctx).json_output:
        emit_records("apply", [result for result, _ in results])
        if pruned is not None:
            emit_records("prune", [pruned])
        if any(result.plan.action is PlanAction.INVALID for result, _ in results):
            raise typer.Exit(code=1)
        return
    accepted = all(_print_plan(result, origin) for result, origin in results)
    if pruned is not None:
        for code in pruned.pruned:
            console.print(f"{styled('deactivated'):<10} {code}  [dim](absent from the project)[/]")
        for code in pruned.trigger_documents_removed:
            console.print(f"{styled('deleted'):<10} {code}  [dim](triggers document absent from the project)[/]")
        if not pruned.pruned and not pruned.trigger_documents_removed:
            console.print("[dim]Nothing to prune: the project holds everything it applied.[/]")
    if dry_run:
        for document in documents:
            _print_document_graph(document.text)
        console.print("[dim]Nothing was written: this was a dry run.[/]")
    if not accepted:
        raise typer.Exit(code=1)


def _documents_to_apply(reference: str | None, as_code: str | None) -> list[Document]:
    """Read the document, or every document in the project when none was named."""
    if reference is not None:
        try:
            return [read_document(reference)]
        except SourceError as error:
            fail(str(error))
    project = find_project()
    if project is None:
        fail("no document was named and this directory is not a project; run dg init, or name a file")
    if as_code is not None:
        fail("--as recodes one document, so it cannot be used when applying a whole project")
    try:
        paths = cast("Any", project).documents()
    except ProjectError as error:
        fail(str(error))
    if not paths:
        fail(f"{cast('Any', project).pipelines_dir} holds no documents")
    # Pipelines go before triggers documents: one that names a pipeline the instance does not
    # hold yet is refused, and applying the pipeline first is what makes it present.
    return sorted((read_path(path) for path in paths), key=_declares_triggers)


def _declares_triggers(document: Document) -> bool:
    """Peek at a document's kind, without holding an unreadable one against the format here."""
    try:
        return isinstance(load_text(document.text), TriggersDefinition)
    except DocumentError:
        return False


def export_command(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="The pipeline to export.")],
    file: Annotated[Path | None, typer.Option("-f", "--file", help="Write to a file instead of stdout.")] = None,
    version: Annotated[int | None, typer.Option(help="Export this version instead of the current one.")] = None,
) -> None:
    """Export a pipeline as canonical YAML."""
    with client_for(state_of(ctx)) as dg:
        text = dg.call(dg.pipelines.export(code, version=version))
    if state_of(ctx).json_output:
        return emit_fact("pipeline.exported", message="exported", code=code, version=version, document=text)
    if file is None:
        console.print(text, end="", highlight=False, markup=False)
        return
    file.write_text(text)
    console.print(f"Wrote [bold]{file}[/].")


def validate_command(
    ctx: typer.Context,
    reference: Annotated[str | None, typer.Argument(help="A file, a URL, or - for standard input.")] = None,
    server: Annotated[
        bool, typer.Option("--server", help="Also check it against a server's catalog and requirements.")
    ] = False,
) -> None:
    """Check a document offline, or against a server's catalog too with --server.

    Offline, a triggers document is checked at the schema level: its clocks and its codes.
    `--server` adds the pipeline it names and the parameters its schedules pin.
    """
    state = state_of(ctx)
    documents = _documents_to_apply(reference, None)
    failures = 0
    parsed: list[tuple[PipelineDefinition | TriggersDefinition, str]] = []
    for document in documents:
        try:
            parsed.append((load_text(document.text), document.label))
        except DocumentError as error:
            emit_fact(
                "validation",
                level="error",
                message="invalid",
                document=document.label,
                problems=list(error.problems),
            )
            failures += 1
    catalog: Catalog | None = None
    connections: list[str] = []
    pipelines: list[str] = []
    targets: dict[str, TriggerTarget] = {}
    if server:
        with client_for(state) as dg:
            catalog = dg.call(dg.blocks.catalog())
            connections = [
                row.code
                for row in paged(lambda after, size: dg.call(dg.connections.list(after=after, limit=size)), None)
            ]
            pipelines = [
                row.code for row in paged(lambda after, size: dg.call(dg.pipelines.list(after=after, limit=size)), None)
            ]
            targets = _trigger_targets(dg, {one.pipeline for one, _ in parsed if isinstance(one, TriggersDefinition)})
    for definition, label in parsed:
        issues = validate_against_catalog(
            definition,
            catalog or Catalog(),
            connections=connections,
            pipelines=pipelines,
            check_blocks=catalog is not None,
            target=targets.get(definition.pipeline) if isinstance(definition, TriggersDefinition) else None,
        )
        if issues:
            emit_fact(
                "validation",
                level="error",
                message="invalid",
                code=definition.code,
                document=label,
                problems=[str(issue) for issue in issues],
            )
            failures += 1
            continue
        emit_fact(
            "validation",
            message="valid",
            code=definition.code,
            document=label,
            checked="document and catalog" if catalog is not None else "document, offline",
            steps=[step._asdict() for step in graph_steps(definition)]
            if isinstance(definition, PipelineDefinition)
            else None,
        )
    emit_fact(
        "validated",
        level="error" if failures else "info",
        message="invalid" if failures else "valid",
        documents=len(documents),
        invalid=failures,
    )
    if failures:
        raise typer.Exit(code=1)


def _trigger_targets(dg: Session, wanted: set[str]) -> dict[str, TriggerTarget]:
    """Read each pipeline a triggers document names, as the server currently holds it."""
    found: dict[str, TriggerTarget] = {}
    for code in sorted(wanted):
        try:
            detail = dg.call(dg.pipelines.get(code))
        except NotFound:
            continue
        current = load_definition(detail.document) if detail.document else None
        found[code] = TriggerTarget(code=code, active=detail.active, definition=current)
    return found


def init_command(
    ctx: typer.Context,
    directory: Annotated[Path, typer.Argument(help="Where to create the instance and project.")] = Path(),
    template: Annotated[str, typer.Option(help="Which template to scaffold: basic, ci or compose.")] = "basic",
    documents_only: Annotated[
        bool,
        typer.Option("--documents-only", help="Scaffold the documents and initialise no instance."),
    ] = False,
    admin: Annotated[str, typer.Option(help="The first admin account's username.")] = "admin",
    password: Annotated[str | None, typer.Option(help="Its password; prompted for when omitted.")] = None,
) -> None:
    """Initialise a uv project and the instance it addresses, ready for `dg dev`.

    Writes the documents and a `pyproject.toml` pinning the running dirigent, so `uv sync`
    builds the project's environment and `uv run dg` is the runtime it was scaffolded on.
    Then creates the state directory, migrates the schema, creates the first admin and mints
    it a token. `--documents-only` stops after the documents. `--template compose` writes the
    documents and a container stack instead, and initialises nothing locally: the instance is
    the containers.
    """
    import asyncio

    from dirigent_core.auth import MIN_PASSWORD_LENGTH, WeakPassword

    state = state_of(ctx)
    # Run once by a person at a terminal, so it renders unless records were asked for.
    if not state.chosen:
        configure(output="console")
    root = directory.resolve()
    # Refusing and asking both happen before anything is written, so a run that cannot
    # finish has not half-created a project, and nobody is asked for a password to satisfy
    # a command that was going to fail anyway.
    try:
        check_template(template)
    except ProjectError as error:
        _init_fail(str(error))
    stack = template == COMPOSE_TEMPLATE_NAME
    if stack and documents_only:
        _init_fail("--documents-only does not apply to the compose template, which writes no instance to skip")
    if stack and admin != "admin":
        _init_fail("--admin does not apply to the compose template; the stack's first admin is named admin")
    if not documents_only and not stack:
        _refuse_an_existing_instance(root)
    secret = (
        ""
        if documents_only
        else (password or os.environ.get(BOOTSTRAP_PASSWORD_ENV) or _prompt_for_a_password(stack=stack))
    )
    if not documents_only and len(secret) < MIN_PASSWORD_LENGTH:
        _init_fail(str(WeakPassword()))
    version = cli_version()
    try:
        made = scaffold(directory, template=template, version=version, password=secret)
    except ProjectError as error:
        _init_fail(str(error))
    left = [_within(path, directory) for path in made.skipped]
    if documents_only or stack:
        starting = [
            "uv sync",
            "docker compose up -d",
            "uv run dg auth login --username admin",
        ]
        emit_fact(
            "project.scaffolded",
            message="scaffolded",
            template=template,
            directory=str(directory),
            version=version,
            files=[_within(path, directory) for path in made.files],
            **({"skipped": left} if left else {}),
            **({"next": starting} if stack else {}),
        )
        return
    settings = instance_settings(root)
    migrated = migrations.head_revision(settings) or "none"
    migrations.upgrade("head", settings)
    token = asyncio.run(first_admin(settings, admin, secret))
    env_file = write_token_env(root, token)
    emit_fact(
        "instance.initialised",
        message="initialised",
        template=template,
        directory=str(root),
        state=STATE_DIR,
        schema=migrated,
        admin=admin,
        token=token,
        version=version,
        files=[_within(path, root) for path in [*made.files, env_file]],
        **({"skipped": [_within(path, root) for path in made.skipped]} if made.skipped else {}),
    )


#: Where the first admin's password comes from when the command is not asked interactively.
BOOTSTRAP_PASSWORD_ENV: Final = "DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD"


def instance_settings(root: Path) -> Settings:
    """Point an instance's state at one directory, whatever the working directory is.

    The defaults are relative, so initialising somewhere else would otherwise migrate the
    schema of the instance the shell happens to be standing in.
    """
    state = root / STATE_DIR
    return Settings(
        database_url=f"sqlite+aiosqlite:///{state / 'dirigent.db'}",
        artifact_root=f"file://{state / 'artifacts'}",
    )


def _init_fail(message: str, *, problems: Sequence[str] = ()) -> NoReturn:
    """Refuse an init: a record where records were asked for, plain sentences otherwise."""
    if json_mode():
        refuse(message, problems=problems)
    else:
        error_console.print(message, highlight=False, markup=False)
        for problem in problems:
            error_console.print(f"  {problem}", highlight=False, markup=False)
    raise typer.Exit(code=1)


def _refuse_an_existing_instance(root: Path) -> None:
    """Refuse to initialise over an instance that is already there.

    Migrating and re-admining a live database is not what somebody running init a second
    time means by it, and there is no undo for the version it would apply.
    """
    existing = instance_settings(root).sqlite_path
    if existing is not None and existing.exists():
        _init_fail(
            f"{existing} already exists, so this directory holds an instance already",
            problems=[
                "dg dev --keep-state starts it",
                "dg db upgrade brings its schema forward",
                "dg init --documents-only scaffolds documents beside it",
            ],
        )


def _prompt_for_a_password(*, stack: bool = False) -> str:
    """Ask for the first admin's password, or say how to give it without a prompt."""
    if not sys.stdin.isatty():
        _init_fail(f"no password for the first admin: pass --password, or set {BOOTSTRAP_PASSWORD_ENV}")
    asked = "password for the stack's first admin" if stack else "password for the first admin"
    return str(typer.prompt(asked, hide_input=True, confirmation_prompt=True))


def cli_version() -> str:
    """The version of dirigent-cli that is running, which is the image tag it scaffolds."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("dirigent-cli")
    except PackageNotFoundError:
        return "0.0.0"


async def first_admin(settings: Settings, username: str, password: str) -> str:
    """Create the instance's first admin and mint it one token, which is returned once."""
    from dirigent_client.enums import UserRole
    from dirigent_core.auth import AuthError, create_user, issue_token
    from dirigent_core.database import create_engine, create_session_factory, session_scope

    engine = create_engine(settings)
    try:
        async with session_scope(create_session_factory(engine)) as session:
            user = await create_user(session, username, password, role=UserRole.ADMIN)
            issued = await issue_token(session, user, name="init")
            return issued.secret.get_secret_value()
    except AuthError as error:
        _init_fail(str(error))
    finally:
        await engine.dispose()


def _within(path: Path, directory: Path) -> str:
    """Name a path against the directory it is under, or in full when it is not under it."""
    try:
        return str(path.resolve().relative_to(directory.resolve()))
    except ValueError:
        return str(path)


@pipeline_app.command("list")
def pipeline_list(
    ctx: typer.Context,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Only pipelines wearing this tag; repeat it to name more."),
    ] = None,
) -> None:
    """List the pipelines this instance holds, or the ones wearing every tag named."""
    tags = tag or []
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.pipelines.list(after=after, limit=size, tags=tags)), None))
    if state_of(ctx).json_output:
        return emit_records("pipeline", rows)
    table(
        "pipelines",
        ["code", "name", "tags", "version", "active", "runs in flight", "updated"],
        [
            [
                row.code,
                row.name or "-",
                " ".join(row.tags) or "-",
                str(row.current_version or "-"),
                render_bool(row.active),
                str(row.active_runs),
                moment(row.updated_at),
            ]
            for row in rows
        ],
    )


@pipeline_app.command("show")
def pipeline_show(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="The pipeline to show.")],
) -> None:
    """Show a pipeline, and the shape of the document its current version holds."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.pipelines.get(code))
    if state_of(ctx).json_output:
        return emit_one("pipeline", row)
    fields(
        f"pipeline {code}",
        {
            "id": row.id,
            "name": row.name or "-",
            "description": row.description or "-",
            "tags": " ".join(row.tags) or "-",
            "active": "yes" if row.active else "no",
            "current version": row.current_version,
            "runs in flight": row.active_runs,
            "created": moment(row.created_at),
        },
    )
    if row.document:
        _print_graph(steps_of_document(row.document))


@pipeline_app.command("versions")
def pipeline_versions(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="The pipeline whose history to list.")],
) -> None:
    """List a pipeline's immutable versions, newest first, with their provenance."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.pipelines.versions(code, after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("pipeline_version", rows)
    table(
        f"versions of {code}",
        ["version", "digest", "source", "applied by", "created"],
        [
            [
                str(row.version),
                row.digest[7:19],
                row.provenance_ref or row.provenance_source.value,
                row.applied_by or "-",
                moment(row.created_at),
            ]
            for row in rows
        ],
    )


@pipeline_app.command("validate")
def pipeline_validate(
    ctx: typer.Context,
    code: Annotated[str | None, typer.Argument(help="The pipeline to re-check; omitted with --all.")] = None,
    version: Annotated[int | None, typer.Option("--version", help="Check this version, not the current one.")] = None,
    every: Annotated[bool, typer.Option("--all", help="Check every pipeline this instance holds.")] = False,
) -> None:
    """Re-check what the instance already holds against what it has now.

    An instance drifts -- a plugin uninstalled, a connection deleted, the allowlist tightened
    -- and a pipeline that applied cleanly then fails when it next runs. This is the check
    apply makes, run again on demand.
    """
    state = state_of(ctx)
    if every and (code is not None or version is not None):
        fail("--all checks every pipeline, so it takes neither a code nor a version")
    if not every and code is None:
        fail("name a pipeline, or pass --all to check every one of them")
    with client_for(state) as dg:
        codes = (
            [row.code for row in paged(lambda after, size: dg.call(dg.pipelines.list(after=after, limit=size)), None)]
            if every
            else [cast("str", code)]
        )
        checked: dict[str, list[ValidationIssue]] = {
            one: list(dg.call(dg.pipelines.validate(one, version=version))) for one in codes
        }
    if state.json_output:
        for one, found in checked.items():
            emit_record(
                "validation",
                code=one,
                valid=not found,
                issues=[issue.model_dump(mode="json") for issue in found],
            )
        if any(checked.values()):
            raise typer.Exit(code=1)
        return
    for one, found in checked.items():
        if not found:
            console.print(f"[green]valid[/]    {one}")
            continue
        console.print(f"[red]invalid[/]  {one}")
        for issue in found:
            stream_line(f"  {issue}")
    if any(checked.values()):
        raise typer.Exit(code=1)


@pipeline_app.command("activate")
def pipeline_activate(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Make a pipeline runnable again."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.pipelines.activate(code))
    emit_fact("pipeline.activated", message="activated", code=code)


@pipeline_app.command("deactivate")
def pipeline_deactivate(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Stop a pipeline being runnable. Its history is kept."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.pipelines.deactivate(code))
    emit_fact("pipeline.deactivated", message="deactivated", code=code)


@pipeline_app.command("delete")
def pipeline_delete(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Delete a pipeline and every run ever attributed to it. Runs in flight refuse it."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.pipelines.delete(code))
    emit_fact("pipeline.deleted", message="deleted", code=code, runs="deleted")


def parse_params(
    pairs: list[str] | None,
    *,
    schema: dict[str, Any] | None = None,
    files: list[Path] | None = None,
) -> dict[str, Any]:
    """Build a run's parameters from files and flags, coerced against the pipeline's schema."""
    try:
        return build_params(schema or {}, pairs=pairs or [], files=files or [])
    except ParamError as error:
        fail(str(error))


#: What separates the two ends of a ``--window`` value.
WINDOW_SEPARATOR: Final = ".."

#: The grammar, said once, so every refusal says the same thing.
WINDOW_GRAMMAR: Final = "--window takes START..END: two ISO 8601 instants separated by '..'"


def read_instant(value: str, flag: str) -> datetime:
    """Read one ISO 8601 instant off a flag, anchored in UTC where it names no offset.

    A bare flag names no timezone, and a value whose meaning depended on the shell's own
    would put the same command on two different windows on two machines.
    """
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise ParamError(f"{flag} takes one ISO 8601 instant, and {value!r} is not one: {error}") from error
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def check_interval(start: datetime, end: datetime) -> None:
    """Refuse an empty or backwards interval, which covers nothing at all."""
    if start >= end:
        raise ParamError(
            f"an interval runs forwards and covers something: {start.isoformat()} is not before {end.isoformat()}"
        )


def read_window(value: str) -> tuple[datetime, datetime]:
    """Read a ``START..END`` window, or say what the grammar is."""
    start_text, separator, end_text = value.partition(WINDOW_SEPARATOR)
    if not separator:
        raise ParamError(f"{WINDOW_GRAMMAR}, not {value!r}")
    start = read_instant(start_text, "--window")
    end = read_instant(end_text, "--window")
    check_interval(start, end)
    return start, end


def parse_window(value: str | None) -> tuple[datetime, datetime] | None:
    """Read the ``--window`` flag, or nothing where it was not given."""
    if value is None:
        return None
    try:
        return read_window(value)
    except ParamError as error:
        fail(str(error))


def parse_log_levels(values: list[str] | None) -> dict[str, LogLevel] | None:
    """Read the repeated ``--log-level`` flag into the map a run carries.

    A bare level means every block: ``--log-level debug`` is ``{"*": debug}``. A
    ``PATTERN=LEVEL`` pair names one family, and a later repeat of the same pattern wins.
    """
    if not values:
        return None
    levels: dict[str, LogLevel] = {}
    for value in values:
        pattern, _, named = value.partition("=")
        if not named:
            pattern, named = "*", value
        if not pattern:
            fail(f"--log-level {value!r} names no pattern before the =")
        try:
            levels[pattern] = LogLevel(named.lower())
        except ValueError:
            allowed = ", ".join(level.value for level in LogLevel)
            fail(f"--log-level {value!r}: {named!r} is not a level ({allowed})")
    return levels


def parse_priority(value: str | None) -> RunPriority | None:
    """Read the priority a run was asked for, naming the vocabulary when it is not one."""
    if value is None:
        return None
    try:
        return RunPriority(value.lower())
    except ValueError:
        fail(f"--priority {value!r} is not a priority ({', '.join(priority.value for priority in RunPriority)})")


def run_command(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="A pipeline code, or a document file, URL, or -.")],
    param: Annotated[
        list[str] | None,
        typer.Option(
            "-p",
            "--param",
            help="key=value, repeatable; a dotted key addresses a nested leaf and [i] an array element.",
        ),
    ] = None,
    params_file: Annotated[
        list[Path] | None,
        typer.Option("-P", "--params-file", help="A whole parameter payload, in YAML or JSON."),
    ] = None,
    watch: Annotated[bool, typer.Option("--watch", help="Poll until the run finishes.")] = False,
    local: Annotated[bool, typer.Option("--local", help="Run it here, with no server at all.")] = False,
    as_code: Annotated[str | None, typer.Option("--as", help="Register a document under another code.")] = None,
    connections: Annotated[
        Path | None,
        typer.Option("--connections", help="A connections document the --local run creates its credentials from."),
    ] = None,
    schema_files: Annotated[
        list[Path] | None,
        typer.Option(
            "--schema", help="A JSON Schema file a --local run holds by code, so a document may name it; repeatable."
        ),
    ] = None,
    also_apply: Annotated[
        list[Path] | None,
        typer.Option(
            "--also-apply", help="Another document a --local run should apply first, such as a child pipeline."
        ),
    ] = None,
    enable_unsafe: Annotated[
        list[str] | None,
        typer.Option(
            "--enable-unsafe",
            help="Allow a block that runs code on the worker; repeatable, or comma-separated.",
        ),
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Treat completed_with_errors as a failure.")] = False,
    keep: Annotated[
        bool,
        typer.Option("--keep", help="Leave a --local run's throwaway instance on disk, and say where."),
    ] = False,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Hold a --local run's instance in DIR and keep it, so a later run reads it."),
    ] = None,
    window: Annotated[
        str | None,
        typer.Option("--window", help="The logical interval this run covers, as START..END in ISO 8601."),
    ] = None,
    log_level: Annotated[
        list[str] | None,
        typer.Option(
            "--log-level",
            help="A level to keep (debug) or PATTERN=LEVEL for one block family; repeatable. "
            "Omitted keeps info and up.",
        ),
    ] = None,
    priority: Annotated[
        str | None,
        typer.Option(
            "--priority",
            help="How far ahead of other runs this one is claimed: low, normal, or high. "
            "Omitted takes the pipeline's own.",
        ),
    ] = None,
) -> None:
    """Run a pipeline by code, or apply and run a document in one command.

    A code starts a run of a stored pipeline. A document is applied first, as ``dg apply``
    would, and then run. ``--local`` does either in a throwaway instance with no server.
    """
    state = state_of(ctx)
    if strict and not (watch or local):
        fail("--strict decides on a run's outcome, so it needs --watch or --local")
    if keep and not local:
        fail("--keep leaves a --local run's throwaway instance behind; a real instance keeps its own")
    if root is not None and not local:
        fail("--root holds a --local run's instance in a directory; a real instance has its own")
    covered = parse_window(window)
    levels = parse_log_levels(log_level)
    wanted = parse_priority(priority)
    if wanted is not None and local:
        fail("--priority orders a run against the others queued, and a --local run has none")
    if local:
        _run_locally(
            state,
            target,
            param or [],
            params_file or [],
            connections,
            schema_files or [],
            also_apply or [],
            enable_unsafe or [],
            window=covered,
            log_levels={pattern: level.value for pattern, level in levels.items()} if levels else None,
            strict=strict,
            keep=keep,
            root=root,
        )
        return
    with client_for(state) as dg:
        code = target
        schema: dict[str, Any] = {}
        if looks_like_a_document(target):
            try:
                document = read_document(target)
                schema = dict(load_pipeline_text(document.text).params)
            except (SourceError, DocumentError) as error:
                fail(str(error))
            result = _apply_one(dg, document, code=as_code, dry_run=False)
            if not _print_plan(result, document.label):
                if state.json_output:
                    emit_problem(
                        f"{result.plan.code} does not validate",
                        status=422,
                        title="Unprocessable Content",
                        problems=[f"{issue.location}: {issue.message}" for issue in result.plan.issues],
                    )
                raise typer.Exit(code=1)
            code = result.plan.code
        else:
            stored = dg.call(dg.pipelines.get(code))
            schema = dict((stored.document or {}).get("params") or {})
        params = parse_params(param, schema=schema, files=params_file)
        accepted = dg.call(dg.pipelines.run(code, params=params, window=covered, log_levels=levels, priority=wanted))
        if accepted.run_id is None:
            if state.json_output:
                emit_problem(accepted.detail or "the concurrency policy refused this run", status=409, title="Skipped")
                return
            console.print(f"[yellow]skipped[/] {accepted.detail or 'the concurrency policy refused this run'}")
            return
        sink(state).event(
            "run",
            message="started",
            pipeline=code,
            run_id=str(accepted.run_id),
            local=False,
            **({"priority": wanted.value} if wanted is not None else {}),
        )
        if watch:
            _watch(dg, accepted.run_id, code, strict=strict, state=state)


def backfill_command(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument(help="The pipeline whose windows are being filled.")],
    schedule: Annotated[
        str,
        typer.Option("--schedule", help="The schedule on that pipeline whose cadence defines the windows."),
    ],
    from_: Annotated[
        str,
        typer.Option("--from", help="First instant to enumerate, inclusive; ISO 8601, UTC where no offset is given."),
    ],
    to: Annotated[
        str,
        typer.Option("--to", help="Last instant to enumerate, exclusive; ISO 8601, UTC where no offset is given."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Ask the server for the plan and create nothing."),
    ] = False,
) -> None:
    """Create one run per window a schedule's cadence has already gone past.

    The schedule's own clock is untouched: this fills what is behind it. Every run is
    attributed to the backfill, carries the window that firing would have carried, and is
    given the schedule's own pinned parameters.
    """
    state = state_of(ctx)
    try:
        start = read_instant(from_, "--from")
        end = read_instant(to, "--to")
        check_interval(start, end)
    except ParamError as error:
        fail(str(error))
    with client_for(state) as dg:
        accepted = dg.call(dg.pipelines.backfill(pipeline, schedule=schedule, start=start, end=end, dry_run=dry_run))
    _report_backfill(accepted, state=state)


def _report_backfill(accepted: BackfillAccepted, *, state: CliState) -> None:
    """Write what the backfill amounted to as one record, windows and all."""
    sink(state).event(
        "backfill",
        message="planned" if accepted.dry_run else "created",
        pipeline=accepted.pipeline,
        schedule=accepted.schedule,
        dry_run=accepted.dry_run,
        windows_total=len(accepted.windows),
        runs_created=accepted.created,
        windows=[one.model_dump(mode="json") for one in accepted.windows],
    )


def _run_locally(
    state: CliState,
    target: str,
    pairs: list[str],
    params_files: list[Path],
    connections: Path | None,
    schemas_files: list[Path],
    also_apply: list[Path],
    enable_unsafe: list[str],
    *,
    window: tuple[datetime, datetime] | None = None,
    log_levels: dict[str, str] | None = None,
    strict: bool,
    keep: bool = False,
    root: Path | None = None,
) -> None:
    """Apply and run a document in a throwaway instance, streaming what it logs."""
    if state.url is not None or state.profile is not None or state.token is not None:
        fail("--local runs here with no server, so it cannot be combined with --url, --token, or --profile")
    if not looks_like_a_document(target):
        fail(f"--local runs a document, and {target!r} is not a file, a URL, or '-'")
    try:
        document = read_document(target)
        specs: list[ConnectionSpec] = load_connection_specs(connections) if connections else []
        schema_specs = [load_schema_specs(path) for path in schemas_files]
        supporting = [read_document(str(path)).text for path in also_apply]
        schema = dict(_runnable(document.text).params)
    except (SourceError, LocalError, DocumentError) as error:
        fail(str(error))
    params = parse_params(pairs, schema=schema, files=params_files)
    settings = _local_settings(enable_unsafe)
    outcome = asyncio.run(
        _stream_local(
            document.text,
            params,
            specs,
            schema_specs,
            supporting,
            settings,
            window=window,
            log_levels=log_levels,
            state=state,
            keep=keep,
            root=root,
        )
    )
    if outcome is None:  # pragma: no cover - the generator always ends with an outcome
        fail("the local run produced no outcome")
    _report_outcome(outcome, strict=strict, state=state)


def split_unsafe(values: list[str]) -> list[str]:
    """Read the --enable-unsafe flag, which is repeatable and also takes a comma-separated list."""
    return [block.strip() for value in values for block in value.split(",") if block.strip()]


def _local_settings(enable_unsafe: list[str]) -> Any:
    """Fold --enable-unsafe into the settings a local run inherits.

    The flag adds to the allowlist for this command; it never turns the gate off.
    """
    from dirigent_core.config import get_settings

    settings = get_settings()
    named = split_unsafe(enable_unsafe)
    if not named:
        return settings
    allowed = sorted({*settings.enabled_unsafe_blocks, *named})
    return settings.model_copy(update={"enabled_unsafe_blocks": allowed})


async def _stream_local(
    text: str,
    params: dict[str, Any],
    connections: list[ConnectionSpec],
    schemas: list[SchemaSpec],
    also: list[str],
    settings: Any,
    *,
    window: tuple[datetime, datetime] | None = None,
    log_levels: dict[str, str] | None = None,
    state: CliState,
    keep: bool = False,
    root: Path | None = None,
) -> LocalOutcome | None:
    """Drive a local run, printing each transition and log line as it lands."""
    outcome: LocalOutcome | None = None
    covered = RunWindow(start=window[0], end=window[1]) if window else None
    try:
        async for item in run_document(
            text,
            params=params,
            window=covered,
            log_levels=dict(log_levels) if log_levels else None,
            connections=connections,
            schemas=schemas,
            also=also,
            inherited=settings,
            keep=keep,
            root=root,
        ):
            match item:
                case LocalStarted():
                    track_steps(item.steps)
                    sink(state).event(
                        "run",
                        message="started",
                        pipeline=item.pipeline,
                        run_id=str(item.run_id),
                        local=True,
                        scratch=item.scratch,
                        root=str(item.root),
                    )
                    use_scratch_prefix(item.scratch)
                case StepTransition():
                    _show_transition(item, state=state)
                case LogLine():
                    _show_log(item, state=state)
                case LocalOutcome():
                    outcome = item
    except LocalError as error:
        remedies = (
            [
                "for this run only: dg run --local ... --enable-unsafe shell.run",
                "for the instance:  export DIRIGENT_ENABLED_UNSAFE_BLOCKS='[\"shell.run\"]'",
            ]
            if "DIRIGENT_ENABLED_UNSAFE_BLOCKS" in str(error)
            else []
        )
        refuse(str(error), status=GUARD_EXIT, title="Refused", problems=remedies)
        raise typer.Exit(code=GUARD_EXIT) from error
    return outcome


def sink(state: CliState) -> Sink:
    """The writer this invocation's story goes to, in the spelling it asked for."""
    return Sink(state.output)


def _show_transition(item: StepTransition, *, state: CliState) -> None:
    """Write one attempt's change of state, and what it produced once it has settled."""
    level = state.detail
    out = sink(state)
    out.event(
        "step",
        at=item.at,
        step=item.step,
        item=item.item,
        message=item.status.value,
        block=item.block,
        attempt=item.attempt,
        **_settled_fields(item),
    )
    if not item.settled or not (item.output or item.spill):
        return
    if level is Detail.SUMMARY:
        return
    out.event(
        "output",
        at=item.at,
        step=item.step,
        item=item.item,
        message=item.status.value,
        **_output_fields(item),
    )


def _show_log(item: LogLine, *, state: CliState) -> None:
    """Write one line a block logged."""
    if item.level == "debug" and state.detail is not Detail.FULL:
        return
    sink(state).event(
        "log",
        at=item.at,
        level=item.level,
        step=item.step,
        item=item.item,
        message=item.message,
        fields=dict(item.fields),
    )


def _settled_fields(item: StepTransition) -> dict[str, Any]:
    """The fields a transition carries once it has settled, and nothing before."""
    return {"duration_ms": item.duration_ms} if item.settled and item.duration_ms is not None else {}


def _output_fields(item: StepTransition) -> dict[str, Any]:
    """What a settled step produced: the values themselves, or the artifact holding them."""
    if item.spill is not None:
        return {"artifact": item.spill.uri, "bytes": item.spill.size_bytes}
    return dict(item.output or {})


def _attempt_settled_fields(attempt: AttemptOut) -> dict[str, Any]:
    """The same, for an attempt read back from a server."""
    duration = _attempt_duration_ms(attempt)
    return {"duration_ms": duration} if duration is not None else {}


def _attempt_output_fields(attempt: AttemptOut) -> dict[str, Any]:
    """The same, for an attempt read back from a server."""
    if attempt.output_uri is not None:
        return {"artifact": attempt.output_uri, "bytes": attempt.output_bytes}
    return dict(attempt.output or {})


def _uri(spill: Spill | None) -> str | None:
    """Read a spill's URI, or nothing when the output inlined."""
    return spill.uri if spill is not None else None


def _bytes(spill: Spill | None) -> int | None:
    """Read a spill's size, or nothing when the output inlined."""
    return spill.size_bytes if spill is not None else None


def _report_outcome(outcome: LocalOutcome, *, strict: bool, state: CliState) -> None:
    """Print a local run's outcome and exit with the code CI should read."""
    tolerated = outcome.tolerated and not strict
    code = 0 if tolerated else outcome.exit_code
    out = sink(state)
    finished = _local_finished_event(outcome, code)
    out.event(
        "run",
        level="error" if outcome.exit_code else "info",
        message=outcome.status.value,
        pipeline=outcome.pipeline,
        run_id=str(outcome.run_id),
        exit_code=code,
        error=outcome.error,
        steps=[step.model_dump(mode="json") for step in finished.steps],
        failures=[row.model_dump(mode="json") for row in finished.failures],
        kept_at=finished.kept_at,
    )
    if not out.rendered:
        if code:
            raise typer.Exit(code=code)
        return
    if tolerated:
        console.print("[yellow]warning[/] the run completed with errors; --strict would fail on this")
        return
    if code:
        raise typer.Exit(code=code)


def _local_finished_event(outcome: LocalOutcome, code: int) -> schemas.RunFinished:
    """Turn a local run's outcome into the closing event of its stream."""
    return schemas.RunFinished(
        run_id=outcome.run_id,
        pipeline=outcome.pipeline,
        status=outcome.status.value,
        error=outcome.error,
        exit_code=code,
        steps=[
            schemas.StepSummary(
                step=row.step,
                item=row.item,
                block=row.block,
                status=row.status.value,
                depends_on=row.depends_on,
                warnings=row.warnings,
                duration_ms=row.duration_ms,
                output=row.output,
                artifact_uri=_uri(row.spill),
                artifact_bytes=_bytes(row.spill),
            )
            for row in outcome.results
        ],
        failures=[
            schemas.FailureSummary(
                step=row.step,
                block=row.block,
                attempt=row.attempt,
                error_class=row.error_class,
                error=row.error,
                logs=row.logs,
                input=row.input,
            )
            for row in outcome.failures
        ],
        kept_at=str(outcome.kept_at) if outcome.kept_at is not None else None,
    )


# Tie-break for two things stamped with the same instant: a transition prints before the
# output it caused.
_TRANSITION_FIRST = 0
_LOG_SECOND = 1

#: One thing that happened, in the order it happened: when, its tie-break rank, and what.
type WatchEvent = tuple[datetime, int, AttemptOut | LogEntryOut, str | None]


def moment_of(value: object) -> datetime:
    """Read a server timestamp for ordering, treating a missing one as the beginning of time."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:  # pragma: no cover - the server writes ISO instants
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def item_labels(items: Sequence[ItemOut], attempts: Sequence[AttemptOut]) -> dict[UUID, str]:
    """Map each attempt of a fan-out step to the element it was created for."""
    keys = {item.id: item.item_key.strip() or str(item.item_index) for item in items}
    return {
        attempt.id: keys[attempt.run_item_id]
        for attempt in attempts
        if attempt.run_item_id is not None and attempt.run_item_id in keys
    }


def run_items(dg: Session, run_id: UUID) -> list[ItemOut]:
    """Walk a run's fan-out items, which the detail counts rather than carries."""
    return list(paged(lambda after, size: dg.call(dg.runs.items(run_id, after=after, limit=size)), None))


def run_attempts(
    dg: Session,
    run_id: UUID,
    *,
    step: str | None = None,
    status: AttemptStatus | None = None,
) -> list[AttemptOut]:
    """Walk a run's attempts, which the detail counts rather than carries."""
    return list(
        paged(
            lambda after, size: dg.call(dg.runs.attempts(run_id, step=step, status=status, after=after, limit=size)),
            None,
        )
    )


def in_run_order(attempts: Sequence[AttemptOut], items: Sequence[ItemOut], steps: Sequence[str]) -> list[AttemptOut]:
    """Order walked attempts the way a person watched them, which creation order is not.

    A step sorts on when it first started rather than on when its rows were written, and the
    order the DAG names its nodes in is the written order for the steps that never started.
    """
    indexes = {item.id: item.item_index for item in items}
    positions = {
        attempt.id: indexes[attempt.run_item_id]
        for attempt in attempts
        if attempt.run_item_id is not None and attempt.run_item_id in indexes
    }
    return in_execution_order(attempts, positions, steps)


def transition_event(attempt: AttemptEvent, seen: dict[str, str]) -> list[WatchEvent]:
    """Report one streamed attempt when it has moved since the stream last named it.

    The server replays every attempt on connect and after a reconnection, so an attempt in a
    state already printed is nothing to say.
    """
    key = f"{attempt.step_name}#{attempt.item or ''}#{attempt.attempt}"
    if seen.get(key) == attempt.status.value or attempt.status is AttemptStatus.PENDING:
        return []
    seen[key] = attempt.status.value
    return [(moment_of(attempt.finished_at or attempt.started_at), _TRANSITION_FIRST, attempt, attempt.item)]


def log_events(entries: list[LogEntryOut], labels: dict[UUID, str] | None = None) -> list[WatchEvent]:
    """Report a page of log entries, with the fan-out element each was written by."""
    found = labels or {}
    return [
        (moment_of(entry.created_at), _LOG_SECOND, entry, found.get(entry.step_attempt_id or UUID(int=0)))
        for entry in entries
    ]


def print_events(events: list[WatchEvent], level: Detail = Detail.SUMMARY, *, out: Sink | None = None) -> None:
    """Write transitions and log lines in the order they happened."""
    writer = out or Sink()
    for when, _, subject, label in sorted(events, key=lambda event: (event[0], event[1])):
        if isinstance(subject, LogEntryOut):
            if subject.level is LogLevel.DEBUG and level is not Detail.FULL:
                continue
            writer.event(
                "log",
                at=subject.created_at,
                level=subject.level.value,
                step=subject.step_name,
                item=label,
                message=subject.message,
                fields=dict(subject.fields or {}),
            )
            continue
        writer.event(
            "step",
            at=when,
            step=subject.step_name,
            item=label,
            message=subject.status.value,
            block=subject.block_id,
            attempt=subject.attempt,
            **_attempt_settled_fields(subject),
        )
        if subject.status is not AttemptStatus.SUCCEEDED or not (subject.output or subject.output_uri):
            continue
        if level is Detail.SUMMARY:
            continue
        writer.event(
            "output",
            at=when,
            step=subject.step_name,
            item=label,
            message=subject.status.value,
            **_attempt_output_fields(subject),
        )


def _attempt_duration_ms(attempt: AttemptOut) -> int | None:
    """Report how long one attempt took, or nothing when it never started or never finished."""
    if attempt.started_at is None or attempt.finished_at is None:
        return None
    return round((attempt.finished_at - attempt.started_at).total_seconds() * 1000)


def _watch(dg: Session, run_id: UUID, pipeline: str, *, strict: bool, state: CliState) -> None:
    """Read a run's event stream to its end, printing its transitions and its blocks' output.

    The stream ends with the run's terminal state; the closing record is read from the run
    detail and the report.
    """
    seen: dict[str, str] = {}
    labels: dict[UUID, str] = {}
    # A step's colour follows the order the document wrote it in, which the stream never states.
    track_steps(node.code for node in dg.call(dg.runs.get(run_id)).dag.nodes)
    for event in dg.iterate(dg.runs.events(run_id)):
        if isinstance(event, RunOut):
            continue
        if isinstance(event, AttemptEvent):
            if event.item is not None:
                labels[event.id] = event.item
            _relay(transition_event(event, seen), state)
            continue
        _relay(log_events([event], labels), state)
    watched = dg.call(dg.runs.get(run_id))
    items = run_items(dg, run_id)
    attempts = in_run_order(run_attempts(dg, run_id), items, [node.code for node in watched.dag.nodes])
    tolerated = watched.run.status is RunStatus.COMPLETED_WITH_ERRORS and not strict
    code = 0 if tolerated or watched.run.status is RunStatus.SUCCEEDED else 1
    out = sink(state)
    finished = remote_finished_event(
        watched,
        pipeline,
        code,
        attempts=attempts,
        items=items,
        report=dg.call(dg.runs.report(run_id)),
        logs=failure_logs(dg, run_id),
    )
    out.event(
        "run",
        level="error" if code else "info",
        message=watched.run.status.value,
        pipeline=pipeline,
        run_id=str(run_id),
        pipeline_version=finished.pipeline_version,
        triggered_by=finished.triggered_by,
        duration_ms=finished.duration_ms,
        items_total=finished.items_total,
        items_failed=finished.items_failed,
        exit_code=code,
        priority=watched.run.priority.value,
        error=watched.run.error,
        steps=[step.model_dump(mode="json") for step in finished.steps],
        failures=[row.model_dump(mode="json") for row in finished.failures],
    )
    if not out.rendered:
        if code:
            raise typer.Exit(code=code)
        return
    if tolerated:
        console.print("[yellow]warning[/] the run completed with errors; --strict would fail on this")
        return
    if code:
        raise typer.Exit(code=code)


def _relay(events: list[WatchEvent], state: CliState) -> None:
    """Send events wherever this invocation is reading them."""
    print_events(events, state.detail, out=sink(state))


def remote_finished_event(
    watched: RunDetail,
    pipeline: str,
    code: int,
    *,
    attempts: Sequence[AttemptOut],
    items: Sequence[ItemOut],
    report: RunReport | None = None,
    logs: Mapping[UUID, list[str]] | None = None,
) -> schemas.RunFinished:
    """Turn a finished server-side run into the closing event of its stream.

    The report and the failure log lines are folded in here rather than fetched again when
    the run is rendered: the record is what the table and the diagnosis are read from.
    """
    labels = item_labels(items, attempts)
    reported = {step.step: step for step in (report.steps if report is not None else [])}
    fetched = logs or {}
    return schemas.RunFinished(
        run_id=watched.run.id,
        pipeline=pipeline,
        pipeline_version=report.pipeline_version if report is not None else None,
        status=watched.run.status.value,
        triggered_by=report.triggered_by if report is not None else None,
        duration_ms=report.duration_ms if report is not None else None,
        items_total=report.items_total if report is not None else 0,
        items_failed=report.items_failed if report is not None else 0,
        error=watched.run.error,
        exit_code=code,
        steps=[
            schemas.StepSummary(
                step=attempt.step_name,
                item=labels.get(attempt.id),
                block=attempt.block_id,
                status=attempt.status.value,
                depends_on=list(reported[attempt.step_name].depends_on) if attempt.step_name in reported else [],
                warnings=reported[attempt.step_name].warnings if attempt.step_name in reported else 0,
                attempts=attempt.attempt,
                duration_ms=_attempt_duration_ms(attempt),
                output=attempt.output,
                error=attempt.error,
                artifact_uri=attempt.output_uri,
                artifact_bytes=attempt.output_bytes,
            )
            for attempt in attempts
            if attempt.status in SETTLED_ATTEMPTS
        ],
        failures=[
            schemas.FailureSummary(
                step=attempt.step_name,
                block=attempt.block_id,
                attempt=attempt.attempt,
                error_class=attempt.error_class,
                error=attempt.error,
                logs=fetched.get(attempt.id, []),
            )
            for attempt in attempts
            if attempt.status is AttemptStatus.FAILED
        ],
    )


def failure_logs(dg: Session, run_id: UUID) -> dict[UUID, list[str]]:
    """Read the last log lines of every failed attempt, once, for the closing record."""
    collected: dict[UUID, list[str]] = {}
    for attempt in run_attempts(dg, run_id, status=AttemptStatus.FAILED):
        page = dg.call(dg.runs.logs(run_id, step=attempt.step_name, limit=FAILURE_LOG_LINES))
        collected[attempt.id] = [f"{entry.level.value}: {entry.message}" for entry in page.items]
    return collected


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    pipeline: Annotated[str | None, typer.Option(help="Only runs of this pipeline.")] = None,
    status: Annotated[str | None, typer.Option(help="Only runs in this state.")] = None,
    since: Annotated[str | None, typer.Option(help="Only runs within this window, such as 24h.")] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Only runs whose pipeline wears this tag; repeat it to name more."),
    ] = None,
    limit: Annotated[int, typer.Option(help="How many runs at most; the server decides when omitted.")] = RUNS_PAGE,
) -> None:
    """List runs, newest first, or the ones whose pipeline wears every tag named."""
    if status is not None and status not in set(RunStatus):
        fail(f"{status!r} is not a run status ({', '.join(sorted(RunStatus))})")
    tags = tag or []
    with client_for(state_of(ctx)) as dg:
        rows = list(
            paged(
                lambda after, size: dg.call(
                    dg.runs.list(
                        pipeline=pipeline,
                        status=RunStatus(status) if status else None,
                        since=since,
                        tags=tags,
                        after=after,
                        limit=size,
                    )
                ),
                limit,
            )
        )
    if state_of(ctx).json_output:
        return emit_records("run", rows)
    table(
        "runs",
        ["run", "pipeline", "status", "triggered by", "started", "finished"],
        [
            [
                str(row.id) + prioritised(row.priority.value),
                row.pipeline,
                styled(row.status.value),
                row.triggered_by_label or row.triggered_by_kind.value,
                moment(row.started_at),
                moment(row.finished_at),
            ]
            for row in rows
        ],
    )


@runs_app.command("show")
def runs_show(
    ctx: typer.Context,
    run_id: Annotated[UUID, typer.Argument(help="The run to show.")],
) -> None:
    """Show a run: its status, its DAG, where each step's time went, and its item grid."""
    with client_for(state_of(ctx)) as dg:
        detail = dg.call(dg.runs.get(run_id))
        items = run_items(dg, run_id)
        attempts = in_run_order(run_attempts(dg, run_id), items, [node.code for node in detail.dag.nodes])
    now = datetime.now(UTC)
    grouped = by_step(attempts)
    timings = {node.code: step_timing(node, grouped.get(node.code, []), at=now) for node in detail.dag.nodes}
    if state_of(ctx).json_output:
        document = detail.model_dump(mode="json")
        for node in cast("list[dict[str, Any]]", document["dag"]["nodes"]):
            timing = timings[cast("str", node["code"])]
            node.update(timing.model_dump(mode="json", include={"queued_ms", "running_ms", "waiting_ms"}))
        return emit_record(
            "run.detail",
            fields={
                **document,
                "items": [item.model_dump(mode="json") for item in items],
                "attempts": [
                    {
                        **attempt.model_dump(mode="json"),
                        **attempt_timing(attempt, at=now).model_dump(mode="json"),
                    }
                    for attempt in attempts
                ],
            },
        )
    run = detail.run
    fields(
        f"run {run_id}",
        {
            "pipeline": f"{run.pipeline} (version {run.pipeline_version})",
            "status": run.status.value,
            "triggered by": run.triggered_by_label or run.triggered_by_kind.value,
            "started": moment(run.started_at),
            "finished": moment(run.finished_at),
            "trace": run.trace_id or "-",
            "error": run.error or "-",
            **(
                {"waiting for": f"a worker carrying {', '.join(detail.waiting_for_workers)}"}
                if detail.waiting_for_workers
                else {}
            ),
            **(
                {"log levels": ", ".join(f"{pattern}={level.value}" for pattern, level in run.log_levels.items())}
                if run.log_levels
                else {}
            ),
        },
    )
    console.print()
    table(
        "steps",
        ["step", "block", "outcome", "after", "attempts", "queued", "running", "waiting", "items"],
        [
            [
                node.code,
                node.block,
                styled(node.outcome),
                ", ".join(node.depends_on) or "-",
                str(node.attempts),
                elapsed(timings[node.code].queued_ms),
                elapsed(timings[node.code].running_ms),
                elapsed(timings[node.code].waiting_ms),
                f"{node.items_total - node.items_failed}/{node.items_total}" if node.fan_out else "-",
            ]
            for node in detail.dag.nodes
        ],
    )
    if items:
        console.print()
        table(
            "items",
            ["step", "index", "key", "status", "error"],
            [
                [
                    item.step_name,
                    str(item.item_index),
                    item.item_key,
                    styled(item.status.value),
                    item.error or "-",
                ]
                for item in items
            ],
        )


@runs_app.command("cancel")
def runs_cancel(ctx: typer.Context, run_id: Annotated[UUID, typer.Argument()]) -> None:
    """Cancel a run: stop what has not started, and tell the remote about what has."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.runs.cancel(run_id))
    emit_fact("run.cancelled", message="cancelled", run_id=str(run_id), status=row.status.value)


RETRYABLE = (AttemptStatus.FAILED, AttemptStatus.SKIPPED, AttemptStatus.CANCELLED)

#: Attempt states nothing moves an attempt out of, which is what "step_finished" means.
SETTLED_ATTEMPTS = (
    AttemptStatus.SUCCEEDED,
    AttemptStatus.FAILED,
    AttemptStatus.SKIPPED,
    AttemptStatus.CANCELLED,
)


@runs_app.command("retry")
def runs_retry(
    ctx: typer.Context,
    run_id: Annotated[UUID, typer.Argument(help="The run holding the failed step.")],
    step: Annotated[str, typer.Option("--step", help="Which step to retry.")],
    failed_items: Annotated[bool, typer.Option("--failed-items", help="Retry every failed item of a fan-out.")] = False,
) -> None:
    """Create one manual attempt of a failed step, reading its upstream stored outputs."""
    with client_for(state_of(ctx)) as dg:
        candidates = [row for row in run_attempts(dg, run_id, step=step) if row.status in RETRYABLE]
        if not candidates:
            fail(f"run {run_id} has no settled failure of step {step!r} to retry")
        retried = candidates if failed_items else candidates[-1:]
        labels = item_labels(run_items(dg, run_id), retried)
        for attempt in retried:
            created = dg.call(dg.runs.retry(attempt.id))
            emit_fact(
                "run.retried",
                message="queued",
                step=step,
                item=labels.get(attempt.id),
                run_id=str(run_id),
                attempt=created.attempt,
            )


@runs_app.command("logs")
def runs_logs(
    ctx: typer.Context,
    run_id: Annotated[UUID, typer.Argument(help="The run whose logs to read.")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Stream new entries as they land.")] = False,
    step: Annotated[str | None, typer.Option("--step", help="Only entries from this step.")] = None,
) -> None:
    """Read a run's log entries, or follow them live."""
    state = state_of(ctx)
    with client_for(state) as dg:
        entries = list(
            paged(lambda after, size: dg.call(dg.runs.logs(run_id, after=after, limit=size, step=step)), None)
        )
        if state.json_output and not follow:
            return emit_records("log_entry", entries)
        for entry in entries:
            _relay_log(entry, state)
        if not follow:
            return
        cursor = entries[-1].id if entries else 0
        for entry in dg.iterate(dg.runs.follow_logs(run_id, after=cursor, step=step)):
            _relay_log(entry, state)


def _relay_log(entry: LogEntryOut, state: CliState) -> None:
    """Write one followed log entry."""
    sink(state).event(
        "log",
        at=entry.created_at,
        level=entry.level.value,
        step=entry.step_name,
        message=entry.message,
        fields=dict(entry.fields or {}),
    )


@runs_app.command("report")
def runs_report(
    ctx: typer.Context,
    run_id: Annotated[UUID, typer.Argument(help="The run to summarise.")],
) -> None:
    """Summarise a run: what each step amounted to, and how long it took."""
    with client_for(state_of(ctx)) as dg:
        report = dg.call(dg.runs.report(run_id))
    if state_of(ctx).json_output:
        return emit_one("run.report", report)
    _print_report(report)


def _print_report(report: RunReport) -> None:
    """Print a run report."""
    fields(
        f"run {report.run_id}",
        {
            "pipeline": f"{report.pipeline} (version {report.pipeline_version})",
            "status": report.status.value,
            "triggered by": report.triggered_by or "-",
            "duration": elapsed(report.duration_ms),
            "items": f"{report.items_total - report.items_failed}/{report.items_total}" if report.items_total else "-",
        },
    )
    console.print()
    table(
        "steps",
        ["step", "block", "outcome", "after", "attempts", "duration", "error"],
        [
            [
                step.step + flagged(step.warnings),
                step.block,
                styled(step.outcome),
                ", ".join(step.depends_on) or "-",
                str(step.attempts),
                elapsed(step.duration_ms),
                step.error or "-",
            ]
            for step in report.steps
        ],
    )


@runs_app.command("profile")
def runs_profile(
    ctx: typer.Context,
    run_id: Annotated[UUID, typer.Argument(help="The run to break down.")],
) -> None:
    """Break a run into where its wall clock went, and name what held it up.

    A run is as slow as the chain through its DAG that decided when it ended: each step on
    that chain waited for the one before it, so the queued, running and waiting time along it
    adds up to the run. Everything off the chain ran beside it and cost the run nothing.

    The warnings say only what the timestamps prove -- a probe cadence longer than the work it
    waited on, a deadline many times the wait it needed, a fan-out whose elements never
    overlapped -- so a run with none of those is told nothing rather than guessed at.
    """
    with client_for(state_of(ctx)) as dg:
        detail = dg.call(dg.runs.get(run_id))
        items = run_items(dg, run_id)
        attempts = in_run_order(run_attempts(dg, run_id), items, [node.code for node in detail.dag.nodes])
    _write_profile(profile(detail, attempts, at=datetime.now(UTC)))


def _write_profile(measured: RunProfile) -> None:
    """Write the profile as records, rendered by the same formatter `dg format` renders with."""
    sink = Sink(output_mode())
    sink.event(
        "run.profile",
        message=f"{measured.status} in {elapsed(measured.duration_ms)}",
        run_id=measured.run_id,
        pipeline=measured.pipeline,
        status=measured.status,
        duration_ms=measured.duration_ms,
        critical_path=measured.critical_path,
        queued_ms=measured.queued_ms,
        running_ms=measured.running_ms,
        waiting_ms=measured.waiting_ms,
    )
    for row in measured.steps:
        sink.event(
            "run.profile.step",
            step=row.step,
            message="on the critical path",
            run_id=measured.run_id,
            block=row.block,
            attempts=row.attempts,
            queued_ms=row.queued_ms,
            running_ms=row.running_ms,
            waiting_ms=row.waiting_ms,
        )
    for warning in measured.warnings:
        sink.event(
            "run.profile.warning",
            level="warning",
            step=warning.step,
            message=warning.message,
            run_id=measured.run_id,
            cause=warning.cause,
        )


@blocks_app.command("new")
def blocks_new(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The pack's name: dirigent-NAME, contributing NAME.hello.")],
    directory: Annotated[
        Path, typer.Option(help="The directory to create the pack under; here when omitted.")
    ] = Path(),
) -> None:
    """Scaffold a new block pack: a package, one operator, and a passing test.

    The generated pack registers through the same entry-point group every installed pack
    does, so `uv sync && uv run pytest` inside it is a working plugin from the first minute.
    """
    try:
        written = scaffold_pack(directory.resolve(), name)
    except ScaffoldError as error:
        fail(str(error))
    root = directory.resolve() / f"dirigent-{name}"
    if state_of(ctx).json_output:
        for path in written:
            emit_event(ScaffoldRecord(path=str(path)))
        emit_event(ScaffoldedRecord(directory=str(root), next=["uv sync", "uv run pytest"]))
        return
    for path in written:
        console.print(f"  {path.relative_to(root.parent)}")
    console.print("\nA working pack. Wire the [bold]tool.uv.sources[/] its README names, then:")
    console.print("  [bold]uv sync && uv run pytest[/]")


@blocks_app.command("list")
def blocks_list(
    ctx: typer.Context,
    kind: Annotated[str | None, typer.Option(help="Only operators, or only sensors.")] = None,
) -> None:
    """List the blocks this instance can run."""
    if kind is not None and kind not in set(BlockKind):
        fail(f"{kind!r} is not a block kind ({', '.join(sorted(BlockKind))})")
    with client_for(state_of(ctx)) as dg:
        catalog = dg.call(dg.blocks.catalog(kind=BlockKind(kind) if kind else None))
    if state_of(ctx).json_output:
        emit_records("block", catalog.blocks)
        emit_records("storage_scheme", catalog.storage_schemes)
        emit_records("connection_kind", catalog.connection_kinds)
        return
    table(
        "blocks",
        ["id", "kind", "plugin", "summary"],
        [[block.id, block.kind.value, block.plugin, block.summary] for block in catalog.blocks],
    )
    console.print(
        f"[dim]storage schemes:[/] {', '.join(entry.id for entry in catalog.storage_schemes) or '-'}   "
        f"[dim]connection kinds:[/] {', '.join(entry.id for entry in catalog.connection_kinds) or '-'}"
    )


@blocks_app.command("show")
def blocks_show(
    ctx: typer.Context,
    block_id: Annotated[str, typer.Argument(help="The block to describe.")],
) -> None:
    """Show one block's config and output schemas."""
    with client_for(state_of(ctx)) as dg:
        entry = dg.call(dg.blocks.get(block_id))
    if state_of(ctx).json_output:
        return emit_one("block", entry)
    fields(
        f"block {block_id}",
        {
            "kind": entry.kind.value,
            "plugin": entry.plugin,
            "summary": entry.summary,
            "idempotent": "yes" if entry.idempotent else "no",
            "runs code on the worker": "yes" if entry.local_execution else "no",
        },
    )
    console.print("\n[bold]config[/]")
    _print_schema(entry.config_schema)
    console.print("\n[bold]output[/]")
    _print_schema(entry.output_schema)


def _print_schema(schema: dict[str, Any]) -> None:
    """Print a published JSON Schema as a field list."""
    properties = cast("dict[str, Any]", schema.get("properties") or {})
    required = set(cast("list[str]", schema.get("required") or []))
    if not properties:
        console.print("  [dim]no fields[/]")
        return
    for name, body in properties.items():
        kind = body.get("type") or ("enum" if "enum" in body else "any")
        mark = "[red]*[/]" if name in required else " "
        default = f" [dim](default {body['default']!r})[/]" if "default" in body else ""
        console.print(f"  {mark} {name:<22} {kind}{default}")


@connection_app.command("list")
def connection_list(
    ctx: typer.Context,
) -> None:
    """List the credential records this instance holds, with their secrets redacted."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.connections.list(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("connection", rows)
    table(
        "connections",
        ["code", "name", "kind", "last check", "healthy", "description"],
        [
            [
                row.code,
                row.name or "-",
                row.kind,
                moment(row.last_check_at),
                render_bool(row.last_check_healthy),
                row.description or "-",
            ]
            for row in rows
        ],
    )


@connection_app.command("create")
def connection_create(
    ctx: typer.Context,
    kind_id: Annotated[str, typer.Argument(metavar="KIND", help="The connection kind, such as http.")],
    code: Annotated[str, typer.Argument(help="What to call it; documents reference this code.")],
    name: Annotated[str | None, typer.Option(help="A human title for this connection.")] = None,
    set_value: Annotated[list[str] | None, typer.Option("--set", help="field=value, repeatable.")] = None,
    description: Annotated[str | None, typer.Option(help="What this credential is for.")] = None,
) -> None:
    """Create a connection, prompting for the secret fields without echoing them.

    Prompting happens only on a terminal; in a script every value must arrive via ``--set``.
    """
    with client_for(state_of(ctx)) as dg:
        schema = _connection_schema(dg.call(dg.blocks.catalog()), kind_id)
        config = parse_params(set_value, schema=schema)
        required = set(cast("list[str]", schema.get("required") or []))
        interactive = sys.stdin.isatty() and not json_mode()
        for field, body in cast("dict[str, Any]", schema.get("properties") or {}).items():
            if field in config:
                continue
            # An optional secret nobody set is simply unset: a prompt is an offer, and
            # refusing the invocation for declining it would make the bot-token form of a
            # slack connection unreachable from any script.
            if json_mode() and field in required:
                fail(f"--json cannot prompt for {field}; pass it as --set {field}=...")
            if not interactive:
                continue
            if _is_secret_field(body):
                value = typer.prompt(f"{field}", hide_input=True, default="", show_default=False)
                if value:
                    config[field] = value
            elif field in required:
                config[field] = typer.prompt(f"{field}")
        created = dg.call(dg.connections.create(code, kind=kind_id, config=config, name=name, description=description))
    emit_fact(
        "connection.created",
        message="created",
        code=created.code,
        connection_kind=created.kind,
        name=created.name,
        description=created.description,
        config=created.config,
    )


def _connection_schema(catalog: Catalog, kind_id: str) -> dict[str, Any]:
    """Find one connection kind's published schema in the catalog."""
    for entry in catalog.connection_kinds:
        if entry.id == kind_id:
            return entry.config_schema
    known = ", ".join(entry.id for entry in catalog.connection_kinds) or "none"
    fail(f"no connection kind {kind_id!r} is installed ({known})")


def _is_secret_field(body: dict[str, Any]) -> bool:
    """Report whether a schema field is one the server will redact.

    ``format: password`` is the same declaration that makes the engine encrypt the field,
    so hiding the prompt and encrypting the value stay in agreement.
    """
    if body.get("format") == "password":
        return True
    options = cast("list[object]", body.get("anyOf") or [])
    return any(
        isinstance(option, dict) and cast("dict[str, Any]", option).get("format") == "password" for option in options
    )


@connection_app.command("show")
def connection_show(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument()],
) -> None:
    """Show one credential record, with its secrets redacted."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.connections.get(code))
    if state_of(ctx).json_output:
        return emit_one("connection", row)
    fields(
        f"connection {code}",
        {"name": row.name or "-", "kind": row.kind, "description": row.description or "-", **row.config},
    )


@connection_app.command("check")
def connection_check(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Ask a connection's own kind whether its external system answers."""
    with client_for(state_of(ctx)) as dg:
        report = dg.call(dg.connections.check(code))
    emit_fact(
        "connection.checked",
        message="healthy" if report.healthy else "unhealthy",
        code=code,
        healthy=report.healthy,
        detail=report.detail,
        version=report.version,
    )
    if not report.healthy:
        raise typer.Exit(code=1)


@connection_app.command("delete")
def connection_delete(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Remove a credential record."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.connections.delete(code))
    emit_fact("connection.deleted", message="deleted", code=code)


@schema_app.command("list")
@schema_app.command("ls", hidden=True)
def schema_list(ctx: typer.Context) -> None:
    """List the JSON Schemas this instance holds."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.schemas.list(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("schema", rows)
    table(
        "schemas",
        ["code", "name", "description"],
        [[row.code, row.name or "-", row.description or "-"] for row in rows],
    )


@schema_app.command("create")
def schema_create(
    ctx: typer.Context,
    reference: Annotated[str, typer.Argument(help="A JSON Schema file, or - for standard input.")],
    code: Annotated[
        str | None, typer.Option(help="What to call it; taken from $id or the filename when omitted.")
    ] = None,
    name: Annotated[str | None, typer.Option(help="A human title; taken from the schema's title when omitted.")] = None,
    description: Annotated[
        str | None, typer.Option(help="What the schema is for; taken from the schema's description when omitted.")
    ] = None,
) -> None:
    """Store a locally authored JSON Schema, taking its identity from its own keywords."""
    try:
        document = read_document(reference)
    except SourceError as error:
        fail(str(error))
    try:
        body = yaml.safe_load(document.text)
    except yaml.YAMLError as error:
        fail(f"{document.label} is not readable JSON or YAML: {error}")
    if not isinstance(body, dict):
        fail(f"{document.label} is not a JSON Schema: a schema is an object, and this is {type(body).__name__}")
    schema = cast("JsonMap", body)
    resolved = code
    if resolved is None and not (isinstance(schema.get("$id"), str) and code_from_id(cast("str", schema["$id"]))):
        resolved = code_from_id(Path(document.ref).name) if document.ref != "(stdin)" else None
    with client_for(state_of(ctx)) as dg:
        created = dg.call(dg.schemas.create(schema, code=resolved, name=name, description=description))
    if state_of(ctx).json_output:
        return emit_fact("schema.created", message="created", code=created.code, name=created.name)
    console.print(f"[green]stored[/] schema [bold]{created.code}[/]")


@schema_app.command("show")
def schema_show(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Show one schema: its labels and the JSON Schema body."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.schemas.get(code))
    if state_of(ctx).json_output:
        return emit_one("schema", row)
    fields(f"schema {code}", {"name": row.name or "-", "description": row.description or "-"})
    console.print_json(data=row.body)


@schema_app.command("delete")
def schema_delete(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Remove a schema."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.schemas.delete(code))
    emit_fact("schema.deleted", message="deleted", code=code)


@system_app.command("workers")
def workers_command(
    ctx: typer.Context,
) -> None:
    """List the worker registry: which workers are alive, on what version, with which plugins."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.workers.list(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("worker", rows)
    table(
        "workers",
        ["name", "host", "version", "status", "concurrency", "same code", "last seen"],
        [
            [
                row.name,
                row.hostname,
                row.version,
                styled(row.status.value),
                str(row.concurrency),
                render_bool(row.code_matches_server),
                age(row.last_seen_at),
            ]
            for row in rows
        ],
    )


@system_app.command("info")
def system_info(
    ctx: typer.Context,
) -> None:
    """Describe the instance, and check every connection it holds."""
    with client_for(state_of(ctx)) as dg:
        info = dg.call(dg.system.info())
    if state_of(ctx).json_output:
        return emit_one("system.info", info)
    fields(
        "instance",
        {
            "version": info.version,
            "environment": info.environment,
            "database": info.database,
            "plugins": ", ".join(info.plugins) or "-",
            "blocks": info.blocks,
            "storage schemes": ", ".join(info.storage_schemes) or "-",
            "workers live": info.workers_live,
            "secrets configured": "yes" if info.secrets_configured else "no",
            "unsafe blocks": ", ".join(info.unsafe_blocks_enabled) or "none",
        },
    )
    if info.connections:
        console.print()
        table(
            "connections",
            ["code", "name", "kind", "connected", "detail"],
            [
                [row.code, row.name or "-", row.kind, render_bool(row.connected), row.detail or "-"]
                for row in info.connections
            ],
        )


@token_app.command("create")
def token_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="What to call the token.")],
    user: Annotated[str | None, typer.Option("--user", help="Mint it for this account rather than your own.")] = None,
) -> None:
    """Mint a bearer token and print its secret once."""
    with client_for(state_of(ctx)) as dg:
        if user is None:
            created = dg.call(dg.admin.tokens.create(name))
        else:
            created = dg.call(dg.admin.users.create_token(user, name))
    if state_of(ctx).json_output:
        return emit_fact(
            "token.issued",
            message="created",
            username=created.username,
            name=created.name,
            prefix=created.prefix,
            token=created.token,
        )
    console.print(f"[green]created[/] token [bold]{created.name}[/] for [bold]{created.username}[/]")
    console.print(f"\n  {created.token}\n")
    console.print("[yellow]This is the only time the token is shown.[/] Store it, or create another.")


@token_app.command("list")
def token_list(
    ctx: typer.Context,
) -> None:
    """List API tokens, without their secrets."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.admin.tokens.list(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("token", rows)
    table(
        "tokens",
        ["user", "name", "prefix", "created", "last used", "revoked"],
        [
            [
                row.username,
                row.name,
                row.prefix,
                moment(row.created_at),
                moment(row.last_used_at),
                moment(row.revoked_at),
            ]
            for row in rows
        ],
    )


@token_app.command("revoke")
def token_revoke(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument()],
    user: Annotated[
        str | None, typer.Option("--user", help="Revoke this account's token rather than your own.")
    ] = None,
) -> None:
    """Revoke the live tokens of that name held by one account."""
    with client_for(state_of(ctx)) as dg:
        if user is None:
            dg.call(dg.admin.tokens.revoke(name))
        else:
            dg.call(dg.admin.users.revoke_token(user, name))
    if user is None:
        emit_fact("token.revoked", message="revoked", code=name)
    else:
        emit_fact("token.revoked", message="revoked", code=name, username=user)


@user_app.command("list")
def user_list(
    ctx: typer.Context,
) -> None:
    """List the accounts this instance holds."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.admin.users.list(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("user", rows)
    table(
        "users",
        ["username", "role", "active", "last login"],
        [[row.username, row.role.value, render_bool(row.active), moment(row.last_login_at)] for row in rows],
    )


@user_app.command("deactivate")
def user_deactivate(ctx: typer.Context, username: Annotated[str, typer.Argument()]) -> None:
    """Bar an account from logging in and revoke the sessions it already holds."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.admin.users.deactivate(username))
    if state_of(ctx).json_output:
        return emit_records("user", [row])
    console.print(f"[red]deactivated[/] user {row.username}")


@user_app.command("activate")
def user_activate(ctx: typer.Context, username: Annotated[str, typer.Argument()]) -> None:
    """Let an account log in again; the sessions it lost are not restored."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.admin.users.activate(username))
    if state_of(ctx).json_output:
        return emit_records("user", [row])
    console.print(f"[green]activated[/] user {row.username}")


@user_app.command("password")
def user_password(
    ctx: typer.Context,
    username: Annotated[str, typer.Argument(help="The account whose password to replace.")],
    password: Annotated[str | None, typer.Option(help="The password to set; asked for, hidden, when omitted.")] = None,
) -> None:
    """Set another account's password, ending every session it holds; its API tokens survive."""
    password = password or ask("new password", hide=True)
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.admin.users.reset_password(username, password))
    emit_fact("password.reset", message="reset", username=username, sessions="revoked")


@auth_app.command("password")
def auth_password(
    ctx: typer.Context,
    current: Annotated[str | None, typer.Option(help="The password in force; asked for, hidden, when omitted.")] = None,
    new: Annotated[str | None, typer.Option(help="The password to set; asked for, hidden, when omitted.")] = None,
) -> None:
    """Change this account's own password, ending every other session it holds."""
    current = current or ask("current password", hide=True)
    new = new or ask("new password", hide=True)
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.auth.change_password(current, new))
    emit_fact("password.changed", message="changed", other_sessions="revoked")


@auth_app.command("login")
def auth_login(
    ctx: typer.Context,
    username: Annotated[str | None, typer.Option(help="The account to log in as; asked for when omitted.")] = None,
    password: Annotated[str | None, typer.Option(help="Its password; asked for, hidden, when omitted.")] = None,
) -> None:
    """Log in and mint an API token to put in a profile.

    The token, not a cookie, is what goes into ``profiles.yaml`` or ``DG_TOKEN``.
    """
    state = state_of(ctx)
    username = username or ask("username")
    password = password or ask("password", hide=True)
    endpoint = state.endpoint(needs_token=False)
    with client_for(state, needs_token=False) as dg:
        dg.call(dg.auth.login(username, password))
        created = dg.call(dg.admin.tokens.create(f"cli-{username}"))
    emit_fact(
        "token.issued",
        message="logged in",
        username=username,
        url=endpoint.url,
        name=created.name,
        token=created.token,
    )


@auth_app.command("status")
def auth_status(ctx: typer.Context) -> None:
    """Say which server the CLI is talking to, and who it is."""
    state = state_of(ctx)
    if state.resolved.token is None:
        refuse(
            f"no token for {state.resolved.url}",
            title="Not authenticated",
            problems=["set DG_TOKEN", "or add a token to a profile", "or mint one with dg auth login"],
        )
        raise typer.Exit(code=1)
    with client_for(state) as dg:
        me = dg.call(dg.auth.whoami())
    emit_fact(
        "auth",
        message="authenticated",
        url=state.resolved.url,
        source=state.resolved.source,
        username=me.username,
        role=me.role.value,
        via=me.via.value if me.via else "-",
    )
