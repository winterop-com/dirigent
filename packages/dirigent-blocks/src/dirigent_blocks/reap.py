"""The orphan reaper: compose stacks a run left behind, taken down on the daemon that holds them.

``docker.compose.up`` names its project ``dirigent-<run id>`` and compose labels every container
of it ``com.docker.compose.project``, so a stack is addressable by the run that created it long
after that run has gone. A stack is an orphan when its run is terminal, or when no such run
exists at all, and the project is still up: a worker died mid-run, a pipeline was cancelled
between ``up`` and ``down``, a ``down`` step never ran.

The reaper sees only the daemon it is pointed at. With one docker-in-docker sidecar per worker
that is exactly the stacks that worker created, which is the deployment this is written for.
"""

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

from dirigent_blocks import subprocess
from dirigent_blocks.capture import tail
from dirigent_blocks.compose import PROJECT_LABEL
from dirigent_blocks.docker import DockerDaemon, open_client, resolve_endpoint
from dirigent_plugin import BlockFailure

#: A compose project this instance created, and the run id written into its name.
DIRIGENT_PROJECT = re.compile(r"^dirigent-([0-9a-f]{32})$")

#: The status a project whose run no longer exists is reported under.
UNKNOWN_RUN = "unknown"

#: How long one reap invocation of the CLI or the daemon may take.
REAP_TIMEOUT_SECONDS = 180.0


class RunFact(NamedTuple):
    """What the reaper needs to know about the run a project was named after."""

    status: str
    """The run's status, as the instance spells it."""

    active: bool
    """Whether the run may still be driving this stack, in which case it is never touched."""


#: Answers what a run id is doing, or ``None`` where the instance holds no such run.
type RunLookup = Callable[[UUID], Awaitable[RunFact | None]]


class Project(NamedTuple):
    """One compose project on the daemon, with the moment its youngest container was created."""

    name: str
    run_id: UUID
    created: datetime


class Reaped(NamedTuple):
    """One project the reaper acted on, or would have acted on."""

    project: str
    run_id: UUID
    run_status: str
    torn_down: bool
    """False for a dry run, and for a teardown the CLI refused."""

    detail: str = ""
    """What compose said, when it said anything worth carrying."""


def daemon(environ: Mapping[str, str], timeout: float = REAP_TIMEOUT_SECONDS) -> DockerDaemon:
    """Build the daemon facade the reaper reads the project list through."""
    endpoint = resolve_endpoint(None, environ)
    return DockerDaemon(open_client(endpoint, timeout), endpoint.socket)


async def projects(client: DockerDaemon) -> list[Project]:
    """List this instance's compose projects on the daemon, newest container first per project.

    A project's age is its **youngest** container's, so a stack something is still adding to is
    young however long its first container has been up.
    """
    listed = await client.list_labelled({"label": [PROJECT_LABEL]})
    newest: dict[str, tuple[UUID, datetime]] = {}
    for container in listed:
        name = container.labels.get(PROJECT_LABEL, "")
        found = DIRIGENT_PROJECT.match(name)
        if found is None:
            continue
        created = datetime.fromtimestamp(container.created, tz=UTC)
        run_id = UUID(found.group(1))
        held = newest.get(name)
        if held is None or created > held[1]:
            newest[name] = (run_id, created)
    return sorted(
        (Project(name, run_id, created) for name, (run_id, created) in newest.items()),
        key=lambda project: project.name,
    )


async def orphans(
    found: list[Project], look_up: RunLookup, *, grace: timedelta, now: datetime | None = None
) -> list[tuple[Project, str]]:
    """Choose the projects to reap, and say which status each was chosen for.

    A project younger than the grace is left alone whatever its run says, because a stack whose
    ``up`` has only just returned is a stack whose ``down`` has not been reached yet. A run that
    is still active is never reaped; one that is terminal, and one the instance no longer holds,
    both are.
    """
    moment = now or datetime.now(UTC)
    chosen: list[tuple[Project, str]] = []
    for project in found:
        if moment - project.created < grace:
            continue
        fact = await look_up(project.run_id)
        if fact is None:
            chosen.append((project, UNKNOWN_RUN))
        elif not fact.active:
            chosen.append((project, fact.status))
    return chosen


async def reap(
    environ: Mapping[str, str],
    root: Path,
    look_up: RunLookup,
    *,
    grace: timedelta,
    dry_run: bool = False,
    command_path: list[str] | None = None,
    now: datetime | None = None,
) -> list[Reaped]:
    """Run one pass: list the projects, choose the orphans, and take each one down.

    A teardown that fails is reported rather than raised, so one stack the daemon will not let
    go of does not stop the pass reaching the next.
    """
    async with daemon(environ) as client:
        found = await projects(client)
    chosen = await orphans(found, look_up, grace=grace, now=now)
    argv_head = command_path or ["docker", "compose"]
    results: list[Reaped] = []
    for project, status in chosen:
        if dry_run:
            results.append(Reaped(project.name, project.run_id, status, torn_down=False))
            continue
        results.append(await _tear_down(argv_head, project, status, environ, root))
    return results


async def _tear_down(
    command_path: list[str], project: Project, status: str, environ: Mapping[str, str], root: Path
) -> Reaped:
    """Take one orphaned project down, volumes and orphans included, and say how it went."""
    try:
        code, out, err = await subprocess.output(
            argv=[*command_path, "-p", project.name, "down", "-v", "--remove-orphans"],
            directory=root,
            environ=dict(environ),
            timeout_seconds=REAP_TIMEOUT_SECONDS,
            what="docker compose down",
        )
    except BlockFailure as error:
        return Reaped(project.name, project.run_id, status, torn_down=False, detail=str(error))
    if code != 0:
        return Reaped(
            project.name,
            project.run_id,
            status,
            torn_down=False,
            detail=tail(err) or tail(out) or f"docker compose down exited {code}",
        )
    return Reaped(project.name, project.run_id, status, torn_down=True)
