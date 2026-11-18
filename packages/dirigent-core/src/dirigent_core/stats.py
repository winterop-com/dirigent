"""How the runs in a window went: per day, per pipeline, and where they failed.

Every stats statement is anchored on the runs whose ``finished_at`` falls in the window, which
is the ``ix_runs_finished_at`` range scan, and reaches attempts through ``run_id`` alone. A run
queued, running or paused has not settled and is in none of it.

The summary per pipeline is anchored on the runs whose ``created_at`` falls in the window
instead, the ``ix_runs_created_at`` range scan, so a run still in flight is in it.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptStatus, RunItemStatus, RunStatus
from dirigent_client.schemas import (
    TERMINAL_RUN_STATUSES,
    DayCounts,
    ErrorCount,
    ItemDay,
    ItemHealth,
    ItemStats,
    PipelineDurations,
    PipelineRuns,
    RecentRun,
    RunStats,
    RunSummary,
    StatsWindow,
    StepFailures,
)
from dirigent_core.models import Pipeline, PipelineVersion, Run, RunItem, StepAttempt
from dirigent_core.pipelines import carries_tag

#: The longest window a stats read covers, which also bounds the trend at one row per day.
MAX_WINDOW: Final = timedelta(days=366)

#: How many of each pipeline's most recent settled runs its duration percentiles are measured
#: over. The percentiles are ordered in Python, so SQLite and PostgreSQL answer the same.
DURATION_SAMPLE: Final = 1_000

#: The most recent fan-out elements an item stats read covers, newest run first.
ITEM_SAMPLE: Final = 50_000

#: The run statuses an item's record is read from: settled, and not cancelled part-way.
ITEM_RUN_STATUSES: Final = (RunStatus.SUCCEEDED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.FAILED)

#: How many rows ``top_errors`` and ``failing_steps`` answer with at most.
TOP: Final = 10

#: How many of each pipeline's most recent runs a summary names.
RECENT_RUNS: Final = 30


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
    last = (scope.end - timedelta(microseconds=1)).date()
    while current <= last:
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
    """Measure each pipeline's settled runs from start to finish, over its own most recent sample."""
    rank = (
        sa.func.row_number()
        .over(partition_by=Run.pipeline_id, order_by=(Run.finished_at.desc(), Run.id.desc()))
        .label("rank")
    )
    ranked = scope.narrow(
        sa.select(Pipeline.code, Run.started_at, Run.finished_at, rank)
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .where(Run.started_at.is_not(None))
    ).subquery()
    statement = sa.select(ranked.c.code, ranked.c.started_at, ranked.c.finished_at).where(
        ranked.c.rank <= DURATION_SAMPLE
    )
    rows = (await scope.session.execute(statement)).all()
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


async def run_summary(
    session: AsyncSession,
    *,
    end: datetime,
    since: timedelta,
    pipeline: str | None = None,
    tags: Sequence[str] = (),
    latest: RunStatus | None = None,
) -> RunSummary:
    """Summarise the runs created in ``[end - since, end)`` per pipeline, in three statements.

    One counts the runs per pipeline and state, one ranks each pipeline's runs newest first and
    keeps the first ``RECENT_RUNS``, and one reads the settled runs' durations, over the most
    recent sample. ``latest`` keeps only the pipelines whose newest run in the window is in that
    state; ``tags`` narrows by what each pipeline wears now, as the runs listing does.
    """
    start = end - since

    def narrow[*Row](statement: sa.Select[*Row]) -> sa.Select[*Row]:
        narrowed = statement.where(Run.created_at >= start, Run.created_at < end)
        if pipeline is not None:
            narrowed = narrowed.where(Pipeline.code == pipeline)
        for tag in tags:
            narrowed = narrowed.where(carries_tag(session, tag))
        return narrowed

    counted = narrow(
        sa.select(Run.pipeline_id, Run.status, sa.func.count())
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .group_by(Run.pipeline_id, Run.status)
    )
    counts: dict[object, dict[RunStatus, int]] = defaultdict(dict)
    for pipeline_id, status, runs in (await session.execute(counted)).all():
        counts[pipeline_id][RunStatus(status)] = runs

    rank = (
        sa.func.row_number()
        .over(partition_by=Run.pipeline_id, order_by=(Run.created_at.desc(), Run.id.desc()))
        .label("rank")
    )
    ranked = narrow(
        sa.select(Run.pipeline_id, Pipeline.code, Pipeline.name, Run.id, Run.status, Run.created_at, rank)
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
    ).subquery()
    newest = sa.select(ranked).where(ranked.c.rank <= RECENT_RUNS).order_by(ranked.c.pipeline_id, ranked.c.rank)
    recent: dict[object, list[RecentRun]] = defaultdict(list)
    named: dict[object, tuple[str, str | None]] = {}
    for row in (await session.execute(newest)).all():
        named[row.pipeline_id] = (row.code, row.name)
        recent[row.pipeline_id].append(RecentRun(id=row.id, status=RunStatus(row.status), created_at=row.created_at))

    order = sa.func.row_number().over(partition_by=Run.pipeline_id, order_by=(Run.created_at.desc(), Run.id.desc()))
    sampled = narrow(
        sa.select(Run.pipeline_id, Run.started_at, Run.finished_at, order.label("rank"))
        .select_from(Run)
        .join(Pipeline, Pipeline.id == Run.pipeline_id)
        .where(
            Run.status.in_(TERMINAL_RUN_STATUSES),
            Run.started_at.is_not(None),
            Run.finished_at.is_not(None),
        )
    ).subquery()
    timed = sa.select(sampled.c.pipeline_id, sampled.c.started_at, sampled.c.finished_at).where(
        sampled.c.rank <= DURATION_SAMPLE
    )
    measured: dict[object, list[int]] = defaultdict(list)
    for pipeline_id, started, finished in (await session.execute(timed)).all():
        if started is None or finished is None:  # pragma: no cover - both are held by the statement
            continue
        measured[pipeline_id].append(max(0, round((finished - started).total_seconds() * 1000)))

    rows = [
        PipelineRuns(
            pipeline=named[pipeline_id][0],
            name=named[pipeline_id][1],
            latest=runs[0],
            counts=counts.get(pipeline_id, {}),
            recent=runs[::-1],
            median_duration_ms=percentile(measured[pipeline_id], 50) if measured.get(pipeline_id) else None,
        )
        for pipeline_id, runs in recent.items()
        if latest is None or runs[0].status is latest
    ]
    rows.sort(key=lambda row: row.pipeline)
    rows.sort(key=lambda row: row.latest.created_at, reverse=True)
    return RunSummary(window=StatsWindow(start=start, end=end), pipelines=rows)


class _Record:
    """One step's element read across the window's runs, newest first, as the rows arrive."""

    def __init__(self, status: RunItemStatus, run_id: UUID, settled: datetime | None, index: int) -> None:
        """Start the record from the newest run that carried the element."""
        self.last_status = status
        self.last_run_id = run_id
        self.last_at = settled
        self.index = index
        self.counts: Counter[RunItemStatus] = Counter()
        self.durations: list[int] = []
        self.days: dict[date, Counter[RunItemStatus]] = {}
        self.last_failed_at: datetime | None = None
        self.last_error: str | None = None


async def item_stats(
    session: AsyncSession, pipeline: Pipeline, *, end: datetime, since: timedelta, step: str | None = None
) -> ItemStats:
    """Read each fan-out element's record over the runs of one pipeline that settled in ``[end - since, end)``.

    One row per step and element key: how often it succeeded, failed and was skipped, its
    uptime, how long it took, and how it stands in the newest run. A cancelled run is in none
    of it. The read covers the window's most recent ``ITEM_SAMPLE`` elements.
    """
    start = end - since
    day = _day(session).label("day")
    statement = (
        sa.select(
            RunItem.step_name,
            RunItem.item_key,
            RunItem.item_index,
            RunItem.status,
            RunItem.started_at,
            RunItem.finished_at,
            RunItem.error,
            Run.id,
            Run.finished_at,
            day,
        )
        .select_from(RunItem)
        .join(Run, Run.id == RunItem.run_id)
        .where(
            Run.pipeline_id == pipeline.id,
            Run.finished_at >= start,
            Run.finished_at < end,
            Run.status.in_(ITEM_RUN_STATUSES),
        )
        .order_by(Run.finished_at.desc(), Run.id.desc())
        .limit(ITEM_SAMPLE)
    )
    if step is not None:
        statement = statement.where(RunItem.step_name == step)
    records: dict[tuple[str, str], _Record] = {}
    for name, key, index, status, began, finished, error, run_id, settled, on in (
        await session.execute(statement)
    ).all():
        state = RunItemStatus(status)
        record = records.get((name, key))
        if record is None:
            record = records[(name, key)] = _Record(state, run_id, settled, index)
        record.counts[state] += 1
        record.days.setdefault(_as_date(on), Counter())[state] += 1
        if state in (RunItemStatus.SUCCEEDED, RunItemStatus.FAILED) and began is not None and finished is not None:
            record.durations.append(max(0, round((finished - began).total_seconds() * 1000)))
        if state is RunItemStatus.FAILED and record.last_failed_at is None:
            record.last_failed_at = finished or settled
            record.last_error = error
    order = {name: place for place, name in enumerate(await _step_order(session, pipeline))}
    rows = sorted(records.items(), key=lambda pair: (order.get(pair[0][0], len(order)), pair[0][0], pair[1].index))
    return ItemStats(
        pipeline=pipeline.code,
        window=StatsWindow(start=start, end=end),
        items=[_health(name, key, record) for (name, key), record in rows],
    )


def _health(step: str, item: str, record: _Record) -> ItemHealth:
    """Write one element's record as the row the wire carries."""
    up, down = record.counts[RunItemStatus.SUCCEEDED], record.counts[RunItemStatus.FAILED]
    return ItemHealth(
        step=step,
        item=item,
        runs=record.counts.total(),
        succeeded=up,
        failed=down,
        skipped=record.counts[RunItemStatus.SKIPPED],
        uptime=up / (up + down) if up + down else None,
        p50_duration_ms=percentile(record.durations, 50) if record.durations else None,
        p95_duration_ms=percentile(record.durations, 95) if record.durations else None,
        last_status=record.last_status,
        last_run_id=record.last_run_id,
        last_at=record.last_at,
        last_failed_at=record.last_failed_at,
        last_error=record.last_error,
        days=[
            ItemDay(
                day=on,
                succeeded=counted[RunItemStatus.SUCCEEDED],
                failed=counted[RunItemStatus.FAILED],
                skipped=counted[RunItemStatus.SKIPPED],
            )
            for on, counted in sorted(record.days.items())
        ],
    )


async def _step_order(session: AsyncSession, pipeline: Pipeline) -> list[str]:
    """The step names of the pipeline's current version, in the order its author wrote them."""
    if pipeline.current_version is None:
        return []
    found = await session.execute(
        sa.select(PipelineVersion.step_order).where(
            PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version
        )
    )
    return list(found.scalar_one_or_none() or [])
