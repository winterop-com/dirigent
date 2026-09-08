"""Process-side health checks: the instance this shell resolves, as seen from here.

Each check answers one question without a token: does the configured database answer and
hold the right schema, are workers beating, are schedules firing on time, does the server
answer. Bare, ``dg health`` checks the whole instance -- and a machine with no instance on
it says so in one line instead of reporting the absence of everything, part by part.

A named check asserts its component is here, so finding none of it fails; that is the form
a container's ``HEALTHCHECK`` runs, where the environment is the instance and exactly one
component lives. The named ``worker`` check is scoped to this hostname for the same reason,
while the bare form asks about every worker the instance has.
"""

import asyncio
import socket
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx2
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_cli.profiles import ProfileError, resolve_endpoint
from dirigent_client.enums import WorkerStatus
from dirigent_core.config import Settings, redacted_url
from dirigent_core.database import create_engine, create_session_factory
from dirigent_core.migrations import current_revision_async, head_revision
from dirigent_core.models import Schedule, Worker, utcnow

#: How many beats a worker may miss before it counts as not working.
MISSED_BEATS = 6

READY_TIMEOUT = 5.0
LIVE_PATH = "/health"
READY_PATH = "/health/ready"
HTTP_OK = 200

type Verdict = Literal["healthy", "unhealthy", "absent"]
"""What a check decided. ``absent`` is "there is none of this", not "it is broken"."""

type Probe = Literal["liveness", "readiness"]
"""Whether a check asked "are you there" or "can you do your job"."""


class Check(BaseModel):
    """What one check found: which check it was, what it decided, and why."""

    model_config = ConfigDict(frozen=True)

    check: str
    status: Verdict
    detail: str
    probe: Probe = "readiness"

    def failed(self, *, asserted: bool) -> bool:
        """Report whether this ends the command in a failure.

        Absent fails only when the caller named the component, because naming it is the
        assertion that it should be there.
        """
        return self.status == "unhealthy" or (asserted and self.status == "absent")


def where_database(settings: Settings) -> str:
    """Name the database a person would recognise: the file for SQLite, the URL otherwise."""
    target = settings.sqlite_path
    return str(target) if target is not None else redacted_url(settings)


def named_server(*, url: str | None = None, profile: str | None = None) -> str | None:
    """The server this shell names through a flag, ``DG_URL`` or a profile, or None.

    None means nothing was named, so the only server worth asking about is this host's own
    loopback -- which is what a container is.
    """
    try:
        endpoint = resolve_endpoint(url=url, profile=profile)
    except ProfileError:
        return None
    return None if endpoint.source == "default" else endpoint.url


async def latest_heartbeat(session: AsyncSession, hostname: str) -> datetime | None:
    """Read the most recent heartbeat any worker on this host has written."""
    # Must match on hostname, not worker name: a worker names itself hostname-pid, and this
    # check runs in a different process with a different pid.
    rows = await session.execute(sa.select(Worker.last_seen_at).where(Worker.hostname == hostname))
    return max(rows.scalars(), default=None)


def is_beating(seen: datetime | None, *, heartbeat: timedelta, now: datetime | None = None) -> bool:
    """Say whether a heartbeat that old still counts as a worker that is working."""
    if seen is None:
        return False
    return (now or utcnow()) - seen < heartbeat * MISSED_BEATS


async def worker_check(session: AsyncSession, settings: Settings, hostname: str | None = None) -> Check:
    """Report whether workers are beating: this host's when one is named, the instance's else.

    A clean shutdown writes ``stopped``, so a stopped worker is history rather than a
    fault: only workers that claim to be alive and have gone silent count against this.
    """
    query = sa.select(Worker.last_seen_at, Worker.status)
    if hostname is not None:
        query = query.where(Worker.hostname == hostname)
    rows = (await session.execute(query)).all()
    place = f" on {hostname}" if hostname is not None else ""
    if not rows:
        return Check(check="worker", status="absent", detail=f"no worker has ever registered{place}")
    alive = [seen for seen, status in rows if status != WorkerStatus.STOPPED]
    if not alive:
        return Check(check="worker", status="absent", detail=f"every worker{place} has stopped")
    beating = [seen for seen in alive if is_beating(seen, heartbeat=settings.heartbeat)]
    if not beating:
        quiet = int((utcnow() - max(alive)).total_seconds())
        noun = f"the worker{place}" if len(alive) == 1 else f"all {len(alive)} workers{place}"
        return Check(check="worker", status="unhealthy", detail=f"{noun} went silent, the last {quiet}s ago")
    if hostname is not None:
        return Check(check="worker", status="healthy", detail=f"a worker on {hostname} is beating")
    return Check(check="worker", status="healthy", detail=f"{len(beating)} of {len(alive)} workers beating")


async def scheduler_check(session: AsyncSession, settings: Settings, *, now: datetime | None = None) -> Check:
    """Report whether the schedules that should have fired have fired.

    Leadership is a session-scoped advisory lock, so no other process can see who holds it.
    What is visible is the work: a schedule later than the misfire grace means nothing is
    ticking, whichever process was meant to be doing it.
    """
    moment = now or utcnow()
    rows = await session.execute(
        sa.select(Schedule.next_fire_at).where(Schedule.paused.is_(False), Schedule.next_fire_at.is_not(None))
    )
    waiting = sorted(when for when in rows.scalars() if when is not None)
    if not waiting:
        return Check(check="scheduler", status="healthy", detail="no schedule is waiting to fire")
    threshold = moment - settings.scheduler_misfire_grace
    overdue = [when for when in waiting if when < threshold]
    if overdue:
        late = int((moment - overdue[0]).total_seconds())
        return Check(
            check="scheduler",
            status="unhealthy",
            detail=f"{len(overdue)} of {len(waiting)} schedules overdue, the oldest by {late}s: nothing is firing them",
        )
    return Check(check="scheduler", status="healthy", detail=f"{len(waiting)} schedules waiting, none overdue")


def server_check(
    settings: Settings, *, server: str | None = None, probe: Probe = "readiness", timeout: float = READY_TIMEOUT
) -> Check:
    """Ask the server -- the one this shell names, or this host's own -- if it is alive or ready.

    Liveness answers without touching a dependency, so it separates "the process is gone"
    from "the process is up and cannot reach its database" -- which is the case anyone
    actually cares about.
    """
    base = server or f"http://127.0.0.1:{settings.port}"
    where = base.split("://", 1)[-1]
    path = READY_PATH if probe == "readiness" else LIVE_PATH
    try:
        response = httpx2.get(f"{base}{path}", timeout=timeout)
    except httpx2.ConnectError:
        detail = f"nothing is answering at {where}" if server else f"nothing is serving {where}"
        return Check(check="server", status="absent", detail=detail, probe=probe)
    except httpx2.HTTPError as error:
        return Check(
            check="server", status="unhealthy", detail=f"the server at {where}: {type(error).__name__}", probe=probe
        )
    if response.status_code != HTTP_OK:
        return Check(
            check="server",
            status="unhealthy",
            detail=f"the server at {where} answered {response.status_code} to {path}",
            probe=probe,
        )
    word = "ready" if probe == "readiness" else "alive"
    return Check(check="server", status="healthy", detail=f"the server at {where} is {word}", probe=probe)


async def database_check(settings: Settings) -> Check:
    """Say whether the configured database answers, and holds the schema this code expects.

    Reachable is not the same as usable: a database nobody has migrated answers ``SELECT 1``
    and has no tables, and one left behind by a half-finished upgrade answers everything and
    is missing a column. Both are what a readiness check is for.
    """
    where = where_database(settings)
    # Opening a SQLite URL creates the file, so a machine with no instance on it would be
    # given an empty database by the command that came to look at one.
    target = settings.sqlite_path
    if target is not None and not target.exists():
        return Check(check="database", status="absent", detail=f"no database at {target}")
    try:
        stamped = await current_revision_async(settings)
    except Exception as error:  # any driver error means the same thing to whoever asked
        return Check(check="database", status="unhealthy", detail=f"{where} is unreachable: {type(error).__name__}")
    if stamped is None:
        return Check(
            check="database",
            status="unhealthy",
            detail=f"the database at {where} answers, but holds no schema; run `dg db upgrade`",
        )
    head = head_revision(settings)
    if head is not None and stamped != head:
        return Check(
            check="database",
            status="unhealthy",
            detail=f"the database at {where} is at schema {stamped}, and this dirigent expects {head};"
            " run `dg db upgrade`",
        )
    return Check(check="database", status="healthy", detail=f"the database at {where} answers, schema {stamped}")


async def _opened[T](settings: Settings, work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run one piece of work against the configured database, and close it again."""
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            return await work(session)
    finally:
        await engine.dispose()


async def _instance(settings: Settings) -> list[Check]:
    """Run every database-backed check: the database itself, then what it knows."""
    database = await database_check(settings)
    if database.status != "healthy":
        # Workers and schedules cannot be read through a database with no schema, and
        # three failures where there is one fault reads as three faults.
        return [database]
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            return [database, await worker_check(session, settings), await scheduler_check(session, settings)]
    finally:
        await engine.dispose()


def every_check(settings: Settings, *, server: str | None = None) -> list[Check]:
    """Run every check of the instance this shell resolves, in the order an operator reads.

    A database that is simply not there ends it early: on a machine with no instance and no
    named server there is nothing else worth probing, and the verdict says so in one line.
    """
    found = asyncio.run(_instance(settings))
    if found[0].status == "absent" and server is None:
        return found
    return [*found, server_check(settings, server=server)]


def worker_health(settings: Settings, hostname: str | None = None) -> Check:
    """Run the worker check for this host, which is what a worker's HEALTHCHECK asserts."""
    host = hostname or socket.gethostname()
    return asyncio.run(_opened(settings, lambda session: worker_check(session, settings, host)))


def scheduler_health(settings: Settings) -> Check:
    """Run the scheduler check against the configured database."""
    return asyncio.run(_opened(settings, lambda session: scheduler_check(session, settings)))


def database_health(settings: Settings) -> Check:
    """Run the database check against the configured database."""
    return asyncio.run(database_check(settings))


def verdict(checks: Sequence[Check]) -> dict[str, Any]:
    """Sum up what was found, so the last line is the answer rather than an addition problem."""
    counted = Counter(check.status for check in checks)
    broken = [check.check for check in checks if check.status == "unhealthy"]
    absent = {check.check: check for check in checks if check.status == "absent"}
    if broken:
        message = f"{len(broken)} of {len(checks)} checks failed: {', '.join(broken)}"
    elif "database" in absent:
        message = f"there is no instance here: {absent['database'].detail}, and no server was named"
    elif {"worker", "server"} <= absent.keys():
        message = "an instance's database is here, and nothing is running against it"
    elif absent:
        message = f"nothing is broken; there is no {', no '.join(absent)}"
    else:
        message = "everything checked is healthy"
    return {
        "level": "error" if broken else "info",
        "message": message,
        "checked": len(checks),
        "healthy": counted["healthy"],
        "absent": counted["absent"],
        "unhealthy": counted["unhealthy"],
    }
