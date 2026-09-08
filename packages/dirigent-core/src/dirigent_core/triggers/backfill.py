"""Backfill: one run per window a schedule's cadence should already have covered.

The cadence is the authority on what the windows are, so a backfill enumerates the firings a
schedule would have had inside an interval and creates a run for each, carrying the window
that firing would have carried. Nothing about the schedule's own clock is touched: its
``next_fire_at`` is where it was, and the runs are attributed to the backfill rather than to
a firing that never happened.
"""

from datetime import datetime
from itertools import islice
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import ScheduleKind, TriggerKind
from dirigent_common import JsonMap
from dirigent_core.engine.definition import load_definition
from dirigent_core.engine.runs import Attribution, RunWindow, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.logging import get_logger
from dirigent_core.models import PipelineVersion, Schedule
from dirigent_core.triggers.schedules import occurrences_between, window_for

#: How many runs one backfill request may create. A person filling a year of a nightly job
#: asks for 365 and is told to ask twice; a person who typed the wrong year is stopped.
BACKFILL_CAP: Final = 200

#: How far past the cap the enumeration walks before it gives up counting. A refusal is worth
#: an actual number, and the walk has to end somewhere: a minutely schedule over a decade is
#: five million firings.
COUNT_CEILING: Final = 10 * BACKFILL_CAP

_logger = get_logger("backfill")


class BackfillError(Exception):
    """A backfill could not be enumerated or run."""


class Filled(BaseModel):
    """One window a backfill enumerated, and what became of it."""

    model_config = ConfigDict(frozen=True)

    window: RunWindow
    run_id: UUID | None = None
    detail: str | None = None
    """Why no run was created, when none was."""


def windows_of(schedule: Schedule, *, start: datetime, end: datetime) -> list[RunWindow]:
    """Enumerate the windows a backfill over ``[start, end)`` would fill, oldest first.

    A firing exactly on ``start`` is enumerated and one exactly on ``end`` is not, so two
    adjacent backfills tile the interval between them without overlapping or leaving a gap.
    """
    if schedule.kind is ScheduleKind.ONE_TIME:
        raise BackfillError(
            f"schedule {schedule.code!r} fires once at one instant, so it has no cadence to "
            "enumerate; a backfill needs a cron or an interval schedule"
        )
    occurrences = list(islice(occurrences_between(schedule, start=start, end=end), COUNT_CEILING + 1))
    if len(occurrences) > BACKFILL_CAP:
        raise BackfillError(_too_many(schedule, start, end, len(occurrences)))
    windows = [window_for(schedule, occurrence) for occurrence in occurrences]
    return [window for window in windows if window is not None]


def _too_many(schedule: Schedule, start: datetime, end: datetime, counted: int) -> str:
    """Say what was asked for, what the cap is, and how much of it the interval enumerated."""
    how_many = f"more than {COUNT_CEILING}" if counted > COUNT_CEILING else str(counted)
    return (
        f"a backfill creates at most {BACKFILL_CAP} runs, and {schedule.code!r} over "
        f"{start.isoformat()}..{end.isoformat()} enumerates {how_many}; narrow the interval"
    )


async def backfill(
    session: AsyncSession,
    services: EngineServices,
    version: PipelineVersion,
    schedule: Schedule,
    *,
    start: datetime,
    end: datetime,
    params: JsonMap | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[Filled]:
    """Create one run per enumerated window, oldest first, or plan them and create nothing.

    Chronological order is the point: a pipeline whose windows depend on each other's output
    is filled in the order the data arrived, and the pipeline's own concurrency policy is left
    to decide what may be in flight at once.
    """
    windows = windows_of(schedule, start=start, end=end)
    resolved = dict(schedule.params) if params is None else dict(params)
    if dry_run:
        return [Filled(window=window) for window in windows]
    load_definition(version.document).validate_params(resolved, services.format_checker)
    filled: list[Filled] = []
    for window in windows:
        run = await create_run(
            session,
            services,
            version,
            params=resolved,
            attribution=Attribution(
                kind=TriggerKind.BACKFILL,
                id=schedule.id,
                label=f"backfill {schedule.code}",
            ),
            window=window,
            log_levels=dict(schedule.log_levels) if schedule.log_levels else None,
            priority=schedule.priority,
            now=now,
        )
        if run is None:
            filled.append(Filled(window=window, detail="a run of this pipeline is already in flight"))
            continue
        filled.append(Filled(window=window, run_id=run.id))
    _logger.info(
        "backfill created runs",
        schedule=schedule.code,
        windows=len(windows),
        created=sum(1 for one in filled if one.run_id is not None),
    )
    return filled
