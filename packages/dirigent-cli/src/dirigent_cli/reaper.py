"""Wiring the docker orphan reaper to an instance: what a run id means, and when a pass runs.

The reaping itself is ``dirigent_blocks.reap``, which knows docker and nothing else. This
module supplies the half it cannot have: the run lookup, which is a database read, and the
worker chore that puts a pass on a cadence.
"""

import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_blocks import reap, subprocess
from dirigent_blocks.docker import DAEMON_ENV
from dirigent_client.schemas import TERMINAL_RUN_STATUSES
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.logging import get_logger
from dirigent_core.models import Run
from dirigent_core.worker import Chore

#: The docker config directory is inherited too: a pass runs the host's own CLI, and on a host
#: whose compose plugin is configured rather than installed system-wide, this is where it says so.
REAP_ENV = ("DOCKER_CONFIG", *DAEMON_ENV)

_logger = get_logger("worker")


def lookup(sessions: async_sessionmaker[AsyncSession]) -> reap.RunLookup:
    """Build the reaper's run lookup against this instance's database."""

    async def look_up(run_id: UUID) -> reap.RunFact | None:
        async with session_scope(sessions) as session:
            run = await session.get(Run, run_id)
            if run is None:
                return None
            return reap.RunFact(status=run.status.value, active=run.status not in TERMINAL_RUN_STATUSES)

    return look_up


def environment(root: Path) -> dict[str, str]:
    """The environment a reaping docker invocation runs under: the worker's daemon, and its home.

    A pass is worker maintenance rather than a step, so it keeps the worker's own ``HOME``
    instead of a scratch one: that is where a docker install that is not system-wide puts the
    compose plugin the teardown runs.
    """
    built = subprocess.environment(list(REAP_ENV), {}, root)
    home = os.environ.get("HOME")
    if home:
        built["HOME"] = home
    return built


def reachable() -> bool:
    """Whether this host has a docker CLI at all, which is the cheapest gate there is."""
    return shutil.which("docker") is not None


async def pass_once(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], *, dry_run: bool = False
) -> list[reap.Reaped]:
    """Run one reaping pass against the daemon this host's environment names."""
    with tempfile.TemporaryDirectory(prefix="dirigent-reap-") as home:
        root = Path(home)
        return await reap.reap(
            environment(root),
            root,
            lookup(sessions),
            grace=settings.docker_reap_grace,
            dry_run=dry_run,
        )


def record(reaped: reap.Reaped) -> Mapping[str, object]:
    """The fields one reaped project contributes, whether a record or a log line carries them."""
    fields: dict[str, object] = {
        "project": reaped.project,
        "run_id": str(reaped.run_id),
        "run_status": reaped.run_status,
        "torn_down": reaped.torn_down,
    }
    if reaped.detail:
        fields["detail"] = reaped.detail
    return fields


def outcome(reaped: reap.Reaped, *, dry_run: bool = False) -> str:
    """What happened to one project, in the words a record and a log line both carry."""
    if dry_run:
        return "would reap"
    return "reaped" if reaped.torn_down else "could not reap"


def chore(settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> Chore | None:
    """Build the worker's reaping chore, or none where this worker cannot reach a daemon.

    A worker with no docker CLI on its PATH has no stacks to reap and no way to reap them, so
    it runs no loop at all rather than one that fails every five minutes.
    """
    interval = settings.docker_reap_interval
    if interval <= timedelta(0) or not reachable():
        return None

    async def run() -> None:
        for reaped in await pass_once(settings, sessions):
            _logger.info(outcome(reaped), kind="docker_reaped", **record(reaped))

    return Chore(name="docker-reap", interval=interval, run=run)
