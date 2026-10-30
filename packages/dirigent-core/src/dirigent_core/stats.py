"""How the runs that settled in a window went: per day, per pipeline, and where they failed.

Every statement is anchored on the runs whose ``finished_at`` falls in the window, which is
the ``ix_runs_finished_at`` range scan, and reaches attempts through ``run_id`` alone. A run
still in flight has no ``finished_at`` and is in none of it.
"""

import math
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_client.schemas import (
    TERMINAL_RUN_STATUSES,
    DayCounts,
    ErrorCount,
    PipelineDurations,
    RunStats,
    StatsWindow,
    StepFailures,
)
from dirigent_core.models import Pipeline, Run, StepAttempt
from dirigent_core.pipelines import carries_tag

#: The longest window a stats read covers, which also bounds the trend at one row per day.
MAX_WINDOW: Final = timedelta(days=366)

#: The most recent settled runs the duration percentiles are measured over. The percentiles
#: are ordered in Python, so SQLite and PostgreSQL answer the same.
DURATION_SAMPLE: Final = 10_000

#: How many rows ``top_errors`` and ``failing_steps`` answer with at most.
TOP: Final = 10


class Scope:
    """Which runs a stats read covers: settled in ``[start, end)``, of a pipeline, wearing tags."""

    def __init__(
        self, session: AsyncSession, start: datetime, end: datetime, pipeline: str | None, tags: Sequence[str]
    ) -> None:
        """Hold the window and the narrowing every statement of one read shares."""
        self.session = session
        self.start = start
        self.end = end
        self.pipeline = pipeline
        self.tags = tuple(tags)

    def narrow[*Row](self, statement: sa.Select[*Row]) -> sa.Select[*Row]:
        """Hold a statement that joins ``runs`` and ``pipelines`` to the runs this read covers."""
        narrowed = statement.where(
            Run.finished_at >= self.start,
            Run.finished_at < self.end,
            Run.status.in_(TERMINAL_RUN_STATUSES),
        )
        if self.pipeline is not None:
            narrowed = narrowed.where(Pipeline.code == self.pipeline)
        for tag in self.tags:
            narrowed = narrowed.where(carries_tag(self.session, tag))
        return narrowed


async def run_stats(
    session: AsyncSession,
    *,
    end: datetime,
    since: timedelta,
    pipeline: str | None = None,
    tags: Sequence[str] = (),
) -> RunStats:
    """Summarise the runs that settled in ``[end - since, end)``, narrowed to a pipeline and to tags.

    ``tags`` narrows by what each run's pipeline wears now, as the runs listing does.
    """
    scope = Scope(session, end - since, end, pipeline, tags)
    return RunStats(
        window=StatsWindow(start=scope.start, end=scope.end),
        trend=await _trend(scope),
        durations=await _durations(scope),
        top_errors=await _top_errors(scope),
        failing_steps=await _failing_steps(scope),
    )


def _day(session: AsyncSession) -> sa.ColumnElement[date] | sa.ColumnElement[str]:
    """The UTC day a run settled on, in the spelling the session's dialect can answer.

    SQLite holds the instant as UTC text, which ``date()`` reads; PostgreSQL holds a
    ``timestamptz``, whose day depends on the session's zone unless it is read at UTC.
    """
    if session.get_bind().dialect.name == "postgresql":
        return sa.cast(sa.func.timezone("UTC", Run.finished_at), sa.Date())
    return sa.func.date(Run.finished_at, type_=sa.String())


async def _trend(scope: Scope) -> list[DayCounts]:
    """Count the settled runs per day and status, every day of the window present."""
    day = _day(scope.session).label("day")
    statement = (
        sa.select(day, Run.status, sa.func.count())
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .group_by(day, Run.status)
    )
    rows = (await scope.session.execute(scope.narrow(statement))).all()
    tallied: dict[date, Counter[RunStatus]] = {}
    current = scope.start.date()
    while current <= scope.end.date():
        tallied[current] = Counter()
        current += timedelta(days=1)
    for found, status, runs in rows:
        tallied.setdefault(_as_date(found), Counter())[RunStatus(status)] += runs
    return [
        DayCounts(
            day=day,
            total=counted.total(),
            succeeded=counted[RunStatus.SUCCEEDED],
            failed=counted[RunStatus.FAILED],
            completed_with_errors=counted[RunStatus.COMPLETED_WITH_ERRORS],
            cancelled=counted[RunStatus.CANCELLED],
        )
        for day, counted in sorted(tallied.items())
    ]


def _as_date(value: object) -> date:
    """Read a grouped day back as a date, whether the driver answered a date or its ISO text."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


async def _durations(scope: Scope) -> list[PipelineDurations]:
    """Measure each pipeline's settled runs from start to finish, over the most recent sample."""
    statement = (
        sa.select(Pipeline.code, Run.started_at, Run.finished_at)
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .where(Run.started_at.is_not(None))
        .order_by(Run.finished_at.desc())
        .limit(DURATION_SAMPLE)
    )
    rows = (await scope.session.execute(scope.narrow(statement))).all()
    measured: dict[str, list[int]] = {}
    for code, started, finished in rows:
        if started is None or finished is None:  # pragma: no cover - both are held by the statement
            continue
        measured.setdefault(code, []).append(max(0, round((finished - started).total_seconds() * 1000)))
    return [
        PipelineDurations(
            pipeline=code,
            runs=len(values),
            p50_ms=percentile(values, 50),
            p95_ms=percentile(values, 95),
            max_ms=max(values),
        )
        for code, values in sorted(measured.items())
    ]


def percentile(values: Sequence[int], rank: int) -> int:
    """The nearest-rank percentile: the smallest value that ``rank`` percent of them do not exceed."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(rank / 100 * len(ordered)) - 1)]


async def _top_errors(scope: Scope) -> list[ErrorCount]:
    """Group the failed attempts by the code they failed with, else by what they said."""
    key = sa.func.coalesce(StepAttempt.error_code, StepAttempt.error)
    count = sa.func.count()
    last = sa.func.max(StepAttempt.finished_at)
    statement = (
        sa.select(
            sa.func.max(StepAttempt.error_code),
            sa.func.max(StepAttempt.error),
            count,
            last,
            sa.func.min(Pipeline.code),
            sa.func.max(Pipeline.code),
        )
        .select_from(StepAttempt)
        .join(Run, Run.id == StepAttempt.run_id)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .where(StepAttempt.status == AttemptStatus.FAILED, key.is_not(None))
        .group_by(key)
        .order_by(count.desc(), last.desc())
        .limit(TOP)
    )
    rows = (await scope.session.execute(scope.narrow(statement))).all()
    return [
        ErrorCount(
            code=code, message=message, count=counted, last_at=last_at, pipeline=first if first == final else None
        )
        for code, message, counted, last_at, first, final in rows
    ]


async def _failing_steps(scope: Scope) -> list[StepFailures]:
    """Count the failed attempts per pipeline and step, the most failures first."""
    count = sa.func.count()
    last = sa.func.max(StepAttempt.finished_at)
    statement = (
        sa.select(Pipeline.code, StepAttempt.step_name, count, last)
        .select_from(StepAttempt)
        .join(Run, Run.id == StepAttempt.run_id)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .where(StepAttempt.status == AttemptStatus.FAILED)
        .group_by(Pipeline.code, StepAttempt.step_name)
        .order_by(count.desc(), last.desc())
        .limit(TOP)
    )
    rows = (await scope.session.execute(scope.narrow(statement))).all()
    return [
        StepFailures(pipeline=code, step=step, failures=failures, last_at=last_at)
        for code, step, failures, last_at in rows
    ]
