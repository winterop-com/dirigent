"""What a record kind renders as, where one line is not enough of it.

A formatter turns a record into a line. Some records carry more than a line's worth --
the closing ``run`` record carries every step and every failure -- and those get a
rendering keyed by ``kind``, built here and returned to the formatter to print.

The rendering is read off the record and nothing else. A local run deletes its database on
the way out, so the record is what survives it, and a stream read back by ``dg format``
next week has nothing else to consult either.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Final, cast

from pydantic import BaseModel
from rich.console import Group, RenderableType
from rich.markup import escape

from dirigent_cli import schemas
from dirigent_cli.graph import GraphStep, render_graph
from dirigent_cli.output import (
    Detail,
    build_fields,
    build_table,
    detail_mode,
    elapsed,
    flagged,
    labelled,
    muted,
    prioritised,
    render_output,
    styled,
)
from dirigent_core.protocol import Record

#: Fields a record carries for what is drawn beneath its line rather than for the line. A
#: line carries whole values, and a run's every step is not a line's worth of them.
BULKY: Final = frozenset(
    {"steps", "failures", "windows", "packages", "settings", "history", "problems", "issues", "files", "token"}
)


def line(record: Record) -> Record:
    """Drop what is rendered beneath the line from the line itself."""
    return {name: value for name, value in record.items() if name not in BULKY}


def beneath(record: Record) -> RenderableType | None:
    """Render what this record carries beyond its line, or nothing when it carries none."""
    kind = record.get("kind")
    render = RENDERERS.get(str(kind))
    return None if render is None else render(record)


def _mappings(record: Record, field: str) -> list[Mapping[str, object]]:
    """Read one of the record's own collections as the mappings it was written from."""
    raw = record.get(field)
    if not isinstance(raw, list):
        return []
    return [item for item in cast("list[object]", raw) if isinstance(item, Mapping)]


def _texts(record: Record, field: str) -> list[str]:
    """Read one of the record's own collections as the lines it renders as."""
    raw = record.get(field)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in cast("list[object]", raw)]


def _rows[Row: BaseModel](record: Record, field: str, model: type[Row]) -> list[Row]:
    """Read one of the record's own collections back into the shape it was written from."""
    raw = record.get(field)
    if not isinstance(raw, list):
        return []
    items = cast("list[object]", raw)
    return [model.model_validate(item) for item in items if isinstance(item, Mapping)]


def _run(record: Record) -> RenderableType | None:
    """Render a closing run record: what the run was, what each step did, what failed."""
    steps: list[schemas.StepSummary] = _rows(record, "steps", schemas.StepSummary)
    failures: list[schemas.FailureSummary] = _rows(record, "failures", schemas.FailureSummary)
    if not steps and not failures:
        return None
    level = detail_mode()
    parts: list[RenderableType] = []
    header = _header(record)
    if header is not None:
        parts.extend((header, ""))
    if steps:
        parts.append(_steps(steps, level, watched=_is_watched(record)))
    if _is_watched(record):
        outputs = _outputs(steps, level)
        if outputs is not None:
            parts.extend(("", outputs))
    parts.extend(_failures(failures, level))
    parts.extend(_kept(record))
    return Group(*parts)


def _is_watched(record: Record) -> bool:
    """Report whether this run was watched on a server, which knows more than a local one."""
    return record.get("duration_ms") is not None or record.get("items_total") is not None


def _header(record: Record) -> RenderableType | None:
    """Render what a watched run was: its version, what triggered it, how long, how many."""
    if not _is_watched(record):
        return None
    total = record.get("items_total") or 0
    failed = record.get("items_failed") or 0
    return build_fields(
        f"run {record.get('run_id')}{prioritised(record.get('priority'))}",
        {
            "pipeline": f"{record.get('pipeline')} (version {record.get('pipeline_version')})",
            "status": record.get("message"),
            "triggered by": record.get("triggered_by") or "-",
            "duration": elapsed(record.get("duration_ms")),
            "items": f"{total - failed}/{total}" if total else "-",
        },
    )


def _steps(steps: Sequence[schemas.StepSummary], level: Detail, *, watched: bool) -> RenderableType:
    """Render what each step did.

    A watched run reports attempts and the error the server recorded; a local run has its
    outputs to hand and shows those instead of listing them again underneath.
    """
    if watched:
        return build_table(
            "steps",
            ["step", "block", "outcome", "after", "attempts", "duration", "error"],
            [
                [
                    labelled(row.step, row.item) + flagged(row.warnings),
                    row.block,
                    styled(row.status),
                    ", ".join(row.depends_on) or "-",
                    str(row.attempts),
                    elapsed(row.duration_ms),
                    row.error or "-",
                ]
                for row in steps
            ],
        )
    return build_table(
        "steps",
        ["step", "block", "outcome", "after", "duration", "output"],
        [
            [
                labelled(row.step, row.item) + flagged(row.warnings),
                row.block,
                styled(row.status),
                ", ".join(row.depends_on) or "-",
                elapsed(row.duration_ms),
                render_output(row.output, level, uri=row.artifact_uri, size_bytes=row.artifact_bytes),
            ]
            for row in steps
        ],
    )


def _outputs(steps: Sequence[schemas.StepSummary], level: Detail) -> RenderableType | None:
    """Render what each settled step produced, for a run whose steps table has no room."""
    produced = [row for row in steps if row.output or row.artifact_uri]
    if not produced:
        return None
    return build_table(
        "outputs",
        ["step", "output"],
        [
            [
                labelled(row.step, row.item),
                render_output(row.output, level, uri=row.artifact_uri, size_bytes=row.artifact_bytes),
            ]
            for row in produced
        ],
    )


def _failures(failures: Sequence[schemas.FailureSummary], level: Detail) -> list[RenderableType]:
    """Render what actually went wrong, step by step, with each attempt's own log lines."""
    lines: list[RenderableType] = []
    for failure in failures:
        lines.append(
            f"\n[bold red]{failure.step}[/] failed  [dim]{failure.block}, attempt {failure.attempt}"
            f"{', ' + failure.error_class if failure.error_class else ''}[/]"
        )
        lines.extend(f"  [red]{text}[/]" for text in (failure.error or "no error was recorded").splitlines())
        if failure.input and level is not Detail.SUMMARY:
            lines.append("  [dim]it was given:[/]")
            lines.extend(f"    [dim]{text}[/]" for text in render_output(failure.input, level).splitlines())
        if failure.logs:
            lines.append("  [dim]last log lines:[/]")
            lines.extend(f"    [dim]{text}[/]" for text in failure.logs)
    return lines


def _kept(record: Record) -> list[RenderableType]:
    """Say where a local run's instance was kept, and how to point a server at it."""
    kept = record.get("kept_at")
    if not kept:
        return []
    lines: list[RenderableType] = ["\n[dim]the instance was kept at[/]", f"  {kept}"]
    scratch = record.get("scratch")
    if scratch:
        lines.extend(("[dim]this run wrote under[/]", f"  {scratch}"))
    lines.extend(
        (
            "[dim]point a server at it with[/]",
            f"  DIRIGENT_DATABASE_URL=sqlite+aiosqlite:///{kept}/dirigent.db",
        )
    )
    return lines


def _issued(record: Record) -> RenderableType | None:
    """Hand over a minted token: the form it is used in, and that it is shown once."""
    token = record.get("token")
    if not token:
        return None
    return Group(
        "",
        f"  [bold]export DG_TOKEN={escape(str(token))}[/]",
        "",
        "[yellow]This is the only time the token is shown.[/]",
    )


def _files(record: Record) -> list[RenderableType]:
    """List what was written, named against the directory it was written into."""
    written = _texts(record, "files")
    if not written:
        return []
    directory = escape(str(record.get("directory") or "."))
    parts: list[RenderableType] = [
        f"Created a [bold]{escape(str(record.get('template') or 'basic'))}[/] project in [bold]{directory}[/]:",
        *(f"  [green]+[/] {escape(path)}" for path in written),
    ]
    skipped = _texts(record, "skipped")
    if skipped:
        parts.extend(f"  [dim]= {escape(path)} (already there, left alone)[/]" for path in skipped)
    if "pyproject.toml" in skipped:
        version = escape(str(record.get("version") or ""))
        parts.append(f"\nAdd [bold]dirigent-cli=={version}[/] to that pyproject.toml by hand.")
    return parts


def _scaffolded(record: Record) -> RenderableType | None:
    """Render a project scaffolded beside an instance somebody else runs."""
    parts = _files(record)
    if not parts:
        return None
    steps = _texts(record, "next")
    if steps:
        parts.append(
            "\nThe instance is the containers: the stack builds this project's image on the"
            "\npublished one, and the first admin comes from DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD"
            "\nin .env."
            "\n\nStart it from that directory:"
        )
        parts.extend(f"  [bold]{index}. {escape(step)}[/]" for index, step in enumerate(steps, start=1))
        return Group(*parts)
    parts.append(
        "\nThat is a working set of documents and no instance: nothing is running yet."
        "\n  Initialise one here:  [bold]dg init[/]"
        "\n  Or address one that exists:  [bold]export DG_URL=... DG_TOKEN=...[/]"
    )
    return Group(*parts)


def _initialised(record: Record) -> RenderableType | None:
    """Render a new instance: what was written, what it is, and what it is not."""
    parts = _files(record)
    token = escape(str(record.get("token") or ""))
    parts.append(
        build_fields(
            "instance",
            {
                "state": record.get("state"),
                "schema": record.get("schema"),
                "admin": record.get("admin"),
            },
        )
    )
    admin = escape(str(record.get("admin") or "admin"))
    parts.append(
        "\nThe instance lives in this directory. Its database is .dirigent/state, and the"
        f"\ntoken of its first admin, [bold]{admin}[/], is in .env, where the local profile reads it."
        "\nShown here once:"
        f"\n  [bold]{token}[/]"
        "\n\nStart the instance in a second terminal here; it keeps running:"
        "\n  [bold]uv sync[/]"
        "\n  [bold]uv run dg dev --keep-state[/]  [dim]# plain dg dev empties .dirigent/state first[/]"
        f"\nThe UI is at http://127.0.0.1:3333, and {admin} logs in with the password you gave."
        "\n\nThen apply the example here, and run it:"
        "\n  [bold]uv run dg apply[/]"
        "\n  [bold]uv run dg run hello-world --watch[/]"
        "\n\n[yellow]This is an instance for one person on one machine[/]: SQLite on this disk, and"
        "\nno secret key, so a connection carrying a credential cannot be stored until"
        "\nDIRIGENT_SECRET_KEY is set. A real server is the compose stack, with PostgreSQL"
        "\nand workers of its own."
    )
    return Group(*parts)


def _version(record: Record) -> RenderableType | None:
    """Render the installed packages as the table `dg version` used to draw itself."""
    packages = _mappings(record, "packages")
    if not packages:
        return None
    return build_table(
        "dirigent",
        ["package", "version"],
        [[str(one.get("package")), str(one.get("version"))] for one in packages],
    )


def _config(record: Record) -> RenderableType | None:
    """Render the effective configuration as a setting-per-row table."""
    settings = record.get("settings")
    if not isinstance(settings, Mapping):
        return None
    held = cast("Mapping[str, object]", settings)
    return build_fields("effective configuration", dict(held)) if held else None


def _db_history(record: Record) -> RenderableType | None:
    """Render the migration history the record carries, as alembic wrote it."""
    history = str(record.get("history") or "")
    return history or None


def _problems(record: Record) -> list[RenderableType]:
    """Render what a refusal or a check found wrong, one line each."""
    found: list[RenderableType] = [f"  [red]-[/] {escape(text)}" for text in _texts(record, "problems")]
    found.extend(
        f"  [red]-[/] {escape(str(one.get('location')))}: {escape(str(one.get('message')))}"
        for one in _mappings(record, "issues")
    )
    return found


def _refusal(record: Record) -> RenderableType | None:
    """Render the problems a refusal carries, which its line no longer spells out."""
    found = _problems(record)
    return Group(*found) if found else None


def _validation(record: Record) -> RenderableType | None:
    """Render what a checked document is wrong about, or the shape of one that is right."""
    parts = _problems(record)
    steps = _mappings(record, "steps")
    if steps:
        parts.append(f"  {muted('each step under the last one it waits for')}")
        parts.extend(f"    {escape(drawn)}" for drawn in render_graph([_graph_step(one) for one in steps]))
    return Group(*parts) if parts else None


def _graph_step(one: Mapping[str, object]) -> GraphStep:
    """Read one step of a validated document back into the shape the tree is drawn from."""
    depends = one.get("depends_on")
    return GraphStep(
        name=str(one.get("name")),
        block=str(one.get("block")),
        depends_on=tuple(str(item) for item in cast("list[object]", depends or [])),
        rule=str(one.get("rule")),
    )


def _backfill(record: Record) -> RenderableType | None:
    """Render a backfill: the windows it enumerated, and the run each one became."""
    windows: list[schemas.BackfillWindow] = _rows(record, "windows", schemas.BackfillWindow)
    if not windows:
        return None
    return build_table(
        f"{record.get('pipeline')} {record.get('schedule')}",
        ["window start", "window end", "run"],
        [[one.window_start, one.window_end, one.run_id or one.detail or "-"] for one in windows],
    )


def _profile(record: Record) -> RenderableType | None:
    """Render a run profile: the chain that decided the run, and the split along it."""
    path = record.get("critical_path")
    if not isinstance(path, list):
        return None
    chain = " -> ".join(str(code) for code in cast("list[object]", path)) or "-"
    duration = record.get("duration_ms")
    parts = [
        ("queued", record.get("queued_ms")),
        ("running", record.get("running_ms")),
        ("waiting", record.get("waiting_ms")),
    ]
    return build_table(
        f"critical path: {chain}",
        ["where the time went", "duration", "share of the run"],
        [[name, elapsed(value), _share(value, duration)] for name, value in parts],
    )


def _share(part: object, whole: object) -> str:
    """Say what fraction of the run one part of it was, where the run has a duration."""
    if not isinstance(part, int) or not isinstance(whole, int) or whole <= 0:
        return "-"
    return f"{round(100 * part / whole)}%"


#: What each record kind renders beneath its line. A kind that is not here renders as its
#: line alone, which is what makes a record from a newer dirigent readable rather than fatal.
RENDERERS: Final[Mapping[str, Callable[[Record], RenderableType | None]]] = {
    "run": _run,
    "run.profile": _profile,
    "backfill": _backfill,
    "version": _version,
    "config": _config,
    "db.history": _db_history,
    "validation": _validation,
    "error": _refusal,
    "token.issued": _issued,
    "project.scaffolded": _scaffolded,
    "instance.initialised": _initialised,
}
