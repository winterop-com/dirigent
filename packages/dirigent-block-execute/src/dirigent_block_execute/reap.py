"""The orphan reaper: what a run left on the daemon, taken off it once the run has ended.

``docker.compose.up`` names its project ``dirigent-<instance id>-<run id>`` and compose labels
every container of it ``com.docker.compose.project``, so a stack is addressable by the instance
and the run that created it long after that run has gone. ``docker.run`` labels each container it
creates ``dirigent.instance`` and ``dirigent.run``. Only what carries this instance's own id is
ever considered: another instance's stacks and containers on a shared daemon, and anything made
before the instance id was written, are left alone. Of its own, a stack or a container is an
orphan when its run is terminal, or when no such run exists at all, and it is still there: a
worker died mid-run, a pipeline was cancelled between ``up`` and ``down``, a ``down`` step never
ran, a container was created and never collected.

The reaper sees only the daemon it is pointed at.
"""

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx2
from pydantic import BaseModel, ConfigDict

from dirigent_block_execute import subprocess
from dirigent_block_execute.capture import tail
from dirigent_block_execute.compose import PROJECT_LABEL
from dirigent_block_execute.docker import INSTANCE_LABEL, RUN_LABEL, DockerDaemon, open_client, resolve_endpoint
from dirigent_plugin import BlockFailure

#: A compose project this instance created, and the run id written into its name.
DIRIGENT_PROJECT = re.compile(r"^dirigent-([0-9a-f]{32})-([0-9a-f]{32})$")

#: The status a project whose run no longer exists is reported under.
UNKNOWN_RUN = "unknown"

#: How long one reap invocation of the CLI or the daemon may take.
REAP_TIMEOUT_SECONDS = 180.0


class RunFact(BaseModel):
    """What the reaper needs to know about the run a project or a container belongs to."""

    model_config = ConfigDict(frozen=True)

    status: str
    """The run's status, as the instance spells it."""

    active: bool
    """Whether the run may still be driving this stack, in which case it is never touched."""


#: Answers what a run id is doing, or ``None`` where the instance holds no such run.
type RunLookup = Callable[[UUID], Awaitable[RunFact | None]]


class Candidate(Protocol):
    """Something on the daemon that belongs to a run, and how old it is."""

    @property
    def run_id(self) -> UUID:
        """The run it belongs to."""
        ...

    @property
    def created(self) -> datetime:
        """When it was created, by the daemon's clock."""
        ...


class Project(BaseModel):
    """One compose project on the daemon, with the moment its youngest container was created."""

    model_config = ConfigDict(frozen=True)

    name: str
    run_id: UUID
    created: datetime


class Container(BaseModel):
    """One container ``docker.run`` created, with the run its label names."""

    model_config = ConfigDict(frozen=True)

    id: str
    run_id: UUID
    created: datetime


class Reaped(BaseModel):
    """One project or container the reaper acted on, or would have acted on."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    run_status: str
    torn_down: bool
    """False for a dry run, and for a teardown the daemon or the CLI refused."""

    project: str = ""
    """The compose project, or empty for a container ``docker.run`` left."""

    container: str = ""
    """The short id of a container ``docker.run`` left, or empty for a compose project."""

    detail: str = ""
    """What compose or the daemon said, when it said anything worth carrying."""


def daemon(environ: Mapping[str, str], timeout: float = REAP_TIMEOUT_SECONDS) -> DockerDaemon:
    """Build the daemon facade the reaper reads the project list through."""
    endpoint = resolve_endpoint(None, environ)
    return DockerDaemon(open_client(endpoint, timeout), endpoint.socket)


async def projects(client: DockerDaemon, instance: UUID) -> list[Project]:
    """List this instance's compose projects on the daemon, newest container first per project.

    A project's age is its **youngest** container's, so a stack something is still adding to is
    young however long its first container has been up.
    """
    listed = await client.list_labelled({"label": [PROJECT_LABEL]})
    newest: dict[str, tuple[UUID, datetime]] = {}
    for container in listed:
        name = container.labels.get(PROJECT_LABEL, "")
        found = DIRIGENT_PROJECT.match(name)
        if found is None or found.group(1) != instance.hex:
            continue
        created = datetime.fromtimestamp(container.created, tz=UTC)
        run_id = UUID(found.group(2))
        held = newest.get(name)
        if held is None or created > held[1]:
            newest[name] = (run_id, created)
    return sorted(
        (Project(name=name, run_id=run_id, created=created) for name, (run_id, created) in newest.items()),
        key=lambda project: project.name,
    )


async def containers(client: DockerDaemon, instance: UUID) -> list[Container]:
    """List the containers this instance's ``docker.run`` created on the daemon, never a compose service's."""
    listed = await client.list_labelled({"label": [RUN_LABEL, f"{INSTANCE_LABEL}={instance}"]})
    found: list[Container] = []
    for container in listed:
        if PROJECT_LABEL in container.labels or not container.id:
            continue
        if container.labels.get(INSTANCE_LABEL) != str(instance):
            continue
        try:
            run_id = UUID(container.labels.get(RUN_LABEL, ""))
        except ValueError:
            continue
        found.append(
            Container(id=container.id, run_id=run_id, created=datetime.fromtimestamp(container.created, tz=UTC))
        )
    return sorted(found, key=lambda one: one.id)


async def orphans[T: Candidate](
    found: list[T], look_up: RunLookup, *, grace: timedelta, now: datetime | None = None
) -> list[tuple[T, str]]:
    """Choose the projects or containers to reap, and say which status each was chosen for.

    One younger than the grace is left alone whatever its run says, because a stack whose
    ``up`` has only just returned is a stack whose ``down`` has not been reached yet, and a
    container just created is one whose handle has not been stored yet. A run that is still
    active is never reaped; one that is terminal, and one the instance no longer holds, both are.
    """
    moment = now or datetime.now(UTC)
    chosen: list[tuple[T, str]] = []
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
    instance: UUID,
    grace: timedelta,
    dry_run: bool = False,
    command_path: list[str] | None = None,
    now: datetime | None = None,
) -> list[Reaped]:
    """Run one pass: list the projects and containers, choose the orphans, and take each one down.

    A teardown that fails is reported rather than raised, so one stack or container the daemon
    will not let go of does not stop the pass reaching the next.
    """
    results: list[Reaped] = []
    async with daemon(environ) as client:
        found = await projects(client, instance)
        for container, status in await orphans(await containers(client, instance), look_up, grace=grace, now=now):
            results.append(await _remove(client, container, status, dry_run=dry_run))
    chosen = await orphans(found, look_up, grace=grace, now=now)
    argv_head = command_path or ["docker", "compose"]
    for project, status in chosen:
        if dry_run:
            results.append(Reaped(project=project.name, run_id=project.run_id, run_status=status, torn_down=False))
            continue
        results.append(await _tear_down(argv_head, project, status, environ, root))
    return results


async def _remove(client: DockerDaemon, container: Container, status: str, *, dry_run: bool) -> Reaped:
    """Remove one orphaned container and its anonymous volumes, and say how it went."""
    reaped = Reaped(container=container.id[:12], run_id=container.run_id, run_status=status, torn_down=False)
    if dry_run:
        return reaped
    try:
        removed = await client.remove(container.id)
    except (httpx2.HTTPError, OSError) as error:
        return reaped.model_copy(update={"detail": str(error)})
    if not removed:
        return reaped.model_copy(update={"detail": "the daemon refused to remove the container"})
    return reaped.model_copy(update={"torn_down": True})


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
        return Reaped(
            project=project.name, run_id=project.run_id, run_status=status, torn_down=False, detail=str(error)
        )
    if code != 0:
        return Reaped(
            project=project.name,
            run_id=project.run_id,
            run_status=status,
            torn_down=False,
            detail=tail(err) or tail(out) or f"docker compose down exited {code}",
        )
    return Reaped(project=project.name, run_id=project.run_id, run_status=status, torn_down=True)
