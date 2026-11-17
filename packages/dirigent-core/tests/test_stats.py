"""Run stats, folded from runs and attempts seeded with known durations and errors."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunItemStatus, RunStatus
from dirigent_core import stats as stats_module
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import save_pipeline
from dirigent_core.models import Pipeline, PipelineVersion, Run, RunItem, StepAttempt
from dirigent_core.stats import RECENT_RUNS, item_stats, percentile, run_stats, run_summary

END = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)

WEEK = timedelta(days=7)


def _definition(code: str, tags: list[str]) -> PipelineDefinition:
    """A one-step pipeline, which is all a stats read needs of one."""
    return PipelineDefinition(
        code=code, tags=tags, steps={"only": StepDefinition(block="test.echo", config={"value": "hi"})}
    )


def _run(
    version: PipelineVersion,
    status: RunStatus,
    *,
    finished: datetime | None,
    took: timedelta | None = None,
) -> Run:
    """A run row that settled at ``finished`` after running ``took``, or never started."""
    return Run(
        pipeline_id=version.pipeline_id,
        pipeline_version_id=version.id,
        status=status,
        started_at=finished - took if finished is not None and took is not None else None,
        finished_at=finished,
    )


def _failed(run_id: UUID, step: str, *, code: str | None, error: str, at: datetime) -> StepAttempt:
    """One failed attempt of a step, saying ``error`` under ``code``."""
    return StepAttempt(
        run_id=run_id,
        step_name=step,
        block_id="test.echo",
        status=AttemptStatus.FAILED,
        error_code=code,
        error=error,
        finished_at=at,
    )


async def seed(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Two pipelines' worth of runs, one week of them inside the window and a few outside it.

    ``alpha`` wears ``nightly`` and settled ten runs on 9 March taking one to ten seconds, one
    of them after a retried ``pull``. ``beta`` failed twice and was cancelled once on 8 March,
    and completed with errors on 7 March; its ``load`` failed three times on ``http.status``.
    """
    async with session_scope(sessions) as session:
        alpha = await save_pipeline(session, _definition("alpha", ["nightly"]))
        beta = await save_pipeline(session, _definition("beta", []))
        ninth = datetime(2026, 3, 9, 10, 0, tzinfo=UTC)
        eighth = datetime(2026, 3, 8, 10, 0, tzinfo=UTC)
        alphas = [
            _run(alpha, RunStatus.SUCCEEDED, finished=ninth + timedelta(minutes=n), took=timedelta(seconds=n))
            for n in range(1, 11)
        ]
        first = _run(beta, RunStatus.FAILED, finished=eighth, took=timedelta(seconds=4))
        second = _run(beta, RunStatus.FAILED, finished=eighth + timedelta(hours=1), took=timedelta(seconds=6))
        never = _run(beta, RunStatus.CANCELLED, finished=eighth + timedelta(hours=2))
        partial = _run(
            beta,
            RunStatus.COMPLETED_WITH_ERRORS,
            finished=datetime(2026, 3, 7, 8, tzinfo=UTC),
            took=timedelta(seconds=3),
        )
        before = _run(alpha, RunStatus.FAILED, finished=datetime(2026, 3, 1, tzinfo=UTC), took=timedelta(seconds=1))
        running = Run(
            pipeline_id=alpha.pipeline_id,
            pipeline_version_id=alpha.id,
            status=RunStatus.RUNNING,
            started_at=END - timedelta(minutes=5),
        )
        paused = Run(
            pipeline_id=beta.pipeline_id,
            pipeline_version_id=beta.id,
            status=RunStatus.PAUSED,
            started_at=END - timedelta(hours=1),
        )
        session.add_all([*alphas, first, second, never, partial, before, running, paused])
        await session.flush()
        session.add_all(
            [
                _failed(alphas[0].id, "pull", code="http.status", error="HTTP 503", at=ninth - timedelta(hours=1)),
                _failed(first.id, "load", code="http.status", error="HTTP 500", at=eighth - timedelta(hours=1)),
                _failed(second.id, "load", code="http.status", error="HTTP 502", at=eighth),
                _failed(second.id, "fetch", code=None, error="socket closed", at=eighth + timedelta(minutes=30)),
                _failed(partial.id, "load", code="http.status", error="HTTP 500", at=datetime(2026, 3, 7, tzinfo=UTC)),
                _failed(
                    before.id,
                    "pull",
                    code="refused.elsewhere",
                    error="out of the window",
                    at=datetime(2026, 3, 1, tzinfo=UTC),
                ),
                _failed(running.id, "pull", code="still.going", error="in flight", at=END - timedelta(minutes=1)),
                _failed(paused.id, "load", code="http.status", error="HTTP 500", at=END - timedelta(minutes=30)),
            ]
        )


async def assert_the_stats_fold(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The whole read over the seeded week, which the PostgreSQL lane asserts with the same body."""
    await seed(sessions)
    async with session_scope(sessions) as session:
        stats = await run_stats(session, end=END, since=WEEK)

    assert (stats.window.start, stats.window.end) == (END - WEEK, END)
    assert [day.day for day in stats.trend] == [date(2026, 3, 3) + timedelta(days=n) for n in range(8)]
    by_day = {day.day: day for day in stats.trend}
    assert by_day[date(2026, 3, 9)].model_dump(exclude={"day"}) == {
        "total": 10,
        "succeeded": 10,
        "failed": 0,
        "completed_with_errors": 0,
        "cancelled": 0,
    }
    assert (by_day[date(2026, 3, 8)].total, by_day[date(2026, 3, 8)].failed) == (3, 2)
    assert by_day[date(2026, 3, 8)].cancelled == 1
    assert by_day[date(2026, 3, 7)].completed_with_errors == 1
    assert sum(day.total for day in stats.trend) == 14, (
        "neither the run before the window nor the ones running or paused"
    )

    durations = {row.pipeline: row for row in stats.durations}
    assert durations["alpha"].model_dump() == {
        "pipeline": "alpha",
        "runs": 10,
        "p50_ms": 5000,
        "p95_ms": 10000,
        "max_ms": 10000,
    }
    assert (durations["beta"].runs, durations["beta"].max_ms) == (3, 6000), "the cancelled run never started"

    [status, socket] = stats.top_errors
    assert (status.code, status.count, status.pipeline) == ("http.status", 4, None), "it spans both pipelines"
    assert status.last_at == datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
    assert (socket.code, socket.message, socket.count, socket.pipeline) == (None, "socket closed", 1, "beta")

    assert [(row.pipeline, row.step, row.failures) for row in stats.failing_steps] == [
        ("beta", "load", 3),
        ("alpha", "pull", 1),
        ("beta", "fetch", 1),
    ]


async def test_the_stats_fold_a_week_of_runs(sessions: async_sessionmaker[AsyncSession]) -> None:
    await assert_the_stats_fold(sessions)


async def test_the_stats_narrow_to_a_pipeline_and_to_a_tag(sessions: async_sessionmaker[AsyncSession]) -> None:
    await seed(sessions)
    async with session_scope(sessions) as session:
        of_alpha = await run_stats(session, end=END, since=WEEK, pipeline="alpha")
        nightly = await run_stats(session, end=END, since=WEEK, tags=["nightly"])
        nobody = await run_stats(session, end=END, since=WEEK, tags=["nightly", "weekly"])

    for narrowed in (of_alpha, nightly):
        assert sum(day.total for day in narrowed.trend) == 10
        assert [row.pipeline for row in narrowed.durations] == ["alpha"]
        [only] = narrowed.top_errors
        assert (only.code, only.count, only.pipeline) == ("http.status", 1, "alpha")
        assert [(row.step, row.failures) for row in narrowed.failing_steps] == [("pull", 1)]
    assert sum(day.total for day in nobody.trend) == 0
    assert (nobody.durations, nobody.top_errors, nobody.failing_steps) == ([], [], [])


async def test_a_shorter_window_leaves_out_what_settled_before_it(sessions: async_sessionmaker[AsyncSession]) -> None:
    await seed(sessions)
    async with session_scope(sessions) as session:
        stats = await run_stats(session, end=END, since=timedelta(days=2))

    assert [day.day for day in stats.trend] == [date(2026, 3, 8), date(2026, 3, 9), date(2026, 3, 10)]
    assert sum(day.total for day in stats.trend) == 11, "alpha's ten, and beta's cancel at noon on 8 March"


def test_a_percentile_is_the_nearest_rank() -> None:
    assert percentile([7], 50) == 7
    assert percentile([7], 95) == 7
    assert percentile([4, 1, 3, 2], 50) == 2
    assert percentile([4, 1, 3, 2], 95) == 4
    assert percentile(list(range(1, 101)), 95) == 95


async def seed_recent(sessions: async_sessionmaker[AsyncSession]) -> None:
    """A day of runs created every ten minutes for ``alpha``, a few for ``beta``, and one before the day.

    ``alpha`` (``nightly``) ran forty times, the last three failed and every fifth one before them
    took ten seconds and the rest two. ``beta`` succeeded once and is still running once.
    """
    async with session_scope(sessions) as session:
        alpha = await save_pipeline(session, _definition("alpha", ["nightly"]))
        beta = await save_pipeline(session, _definition("beta", []))
        rows: list[Run] = []
        for n in range(40):
            created = END - timedelta(minutes=10 * (40 - n))
            took = timedelta(seconds=10 if n % 5 == 0 else 2)
            status = RunStatus.FAILED if n >= 37 else RunStatus.SUCCEEDED
            rows.append(
                Run(
                    pipeline_id=alpha.pipeline_id,
                    pipeline_version_id=alpha.id,
                    status=status,
                    created_at=created,
                    started_at=created,
                    finished_at=created + took,
                )
            )
        for created, status in (
            (END - timedelta(hours=3), RunStatus.SUCCEEDED),
            (END - timedelta(minutes=1), RunStatus.RUNNING),
        ):
            rows.append(
                Run(
                    pipeline_id=beta.pipeline_id,
                    pipeline_version_id=beta.id,
                    status=status,
                    created_at=created,
                    started_at=created,
                    finished_at=created + timedelta(seconds=7) if status is RunStatus.SUCCEEDED else None,
                )
            )
        rows.append(
            Run(
                pipeline_id=beta.pipeline_id,
                pipeline_version_id=beta.id,
                status=RunStatus.FAILED,
                created_at=END - timedelta(days=2),
            )
        )
        session.add_all(rows)


async def assert_the_summary_folds(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The summary over the seeded day, which the PostgreSQL lane asserts with the same body."""
    await seed_recent(sessions)
    async with session_scope(sessions) as session:
        summary = await run_summary(session, end=END, since=timedelta(days=1))

    assert (summary.window.start, summary.window.end) == (END - timedelta(days=1), END)
    assert [row.pipeline for row in summary.pipelines] == ["beta", "alpha"], "the one that ran last first"
    beta, alpha = summary.pipelines

    assert alpha.counts == {RunStatus.SUCCEEDED: 37, RunStatus.FAILED: 3}
    assert len(alpha.recent) == RECENT_RUNS
    assert [run.created_at for run in alpha.recent] == sorted(run.created_at for run in alpha.recent)
    assert alpha.recent[-1] == alpha.latest
    assert (alpha.latest.status, alpha.latest.created_at) == (RunStatus.FAILED, END - timedelta(minutes=10))
    assert alpha.median_duration_ms == 2000

    assert beta.counts == {RunStatus.SUCCEEDED: 1, RunStatus.RUNNING: 1}, "the run two days back is outside"
    assert [run.status for run in beta.recent] == [RunStatus.SUCCEEDED, RunStatus.RUNNING]
    assert beta.median_duration_ms == 7000, "the running one has not settled"


async def test_the_summary_folds_a_day_of_runs_per_pipeline(sessions: async_sessionmaker[AsyncSession]) -> None:
    await assert_the_summary_folds(sessions)


async def test_the_summary_narrows_to_a_pipeline_a_tag_and_the_newest_state(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await seed_recent(sessions)
    day = timedelta(days=1)
    async with session_scope(sessions) as session:
        of_beta = await run_summary(session, end=END, since=day, pipeline="beta")
        nightly = await run_summary(session, end=END, since=day, tags=["nightly"])
        failing = await run_summary(session, end=END, since=day, latest=RunStatus.FAILED)
        hour = await run_summary(session, end=END, since=timedelta(hours=1))
        nobody = await run_summary(session, end=END, since=day, tags=["weekly"])

    assert [row.pipeline for row in of_beta.pipelines] == ["beta"]
    assert [row.pipeline for row in nightly.pipelines] == ["alpha"]
    assert [row.pipeline for row in failing.pipelines] == ["alpha"]
    assert {row.pipeline: sum(row.counts.values()) for row in hour.pipelines} == {"alpha": 6, "beta": 1}
    assert nobody.pipelines == []


async def test_a_window_ending_at_midnight_has_no_empty_day_after_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    midnight = datetime(2026, 3, 10, tzinfo=UTC)
    async with session_scope(sessions) as session:
        stats = await run_stats(session, end=midnight, since=timedelta(days=2))
    assert [day.day for day in stats.trend] == [date(2026, 3, 8), date(2026, 3, 9)]


async def test_durations_are_sampled_per_pipeline(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stats_module, "DURATION_SAMPLE", 3)
    await seed(sessions)
    await seed_recent(sessions)
    async with session_scope(sessions) as session:
        stats = await run_stats(session, end=END, since=WEEK)
        summary = await run_summary(session, end=END, since=timedelta(days=1))

    assert {row.pipeline: row.runs for row in stats.durations} == {"alpha": 3, "beta": 3}
    assert {row.pipeline: row.median_duration_ms for row in summary.pipelines} == {"alpha": 2000, "beta": 7000}


# -- each fan-out element's record ------------------------------------------------


def _checks() -> PipelineDefinition:
    """A pipeline whose two steps fan out over targets, which is what an item read is about."""
    return PipelineDefinition(
        code="checks",
        steps={
            "reachable": StepDefinition(block="test.echo", for_each=["a", "b"], config={"value": "${item}"}),
            "answers": StepDefinition(block="test.echo", depends_on=["reachable"], config={"value": "x"}),
        },
    )


def _element(
    run: Run, step: str, key: str, index: int, status: RunItemStatus, *, took: int, error: str | None = None
) -> RunItem:
    """One element of one run's grid, that ran ``took`` seconds and ended as ``status``."""
    assert run.finished_at is not None
    return RunItem(
        run_id=run.id,
        step_name=step,
        item_index=index,
        item_key=key,
        status=status,
        error=error,
        started_at=run.finished_at - timedelta(seconds=took + 1),
        finished_at=run.finished_at - timedelta(seconds=1),
    )


async def seed_items(sessions: async_sessionmaker[AsyncSession]) -> Pipeline:
    """Four runs over two targets: ``b`` fails on the 8th and its dependent check is skipped then.

    ``a`` succeeds every time, taking one to four seconds. A cancelled run and a run outside the
    window carry elements that count for nothing.
    """
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, _checks())
        eighth, ninth = datetime(2026, 3, 8, 10, 0, tzinfo=UTC), datetime(2026, 3, 9, 10, 0, tzinfo=UTC)
        runs = [
            _run(version, RunStatus.SUCCEEDED, finished=eighth - timedelta(hours=1), took=timedelta(seconds=9)),
            _run(version, RunStatus.COMPLETED_WITH_ERRORS, finished=eighth, took=timedelta(seconds=9)),
            _run(version, RunStatus.SUCCEEDED, finished=ninth, took=timedelta(seconds=9)),
            _run(version, RunStatus.SUCCEEDED, finished=ninth + timedelta(hours=1), took=timedelta(seconds=9)),
        ]
        cancelled = _run(version, RunStatus.CANCELLED, finished=ninth + timedelta(hours=2), took=timedelta(seconds=9))
        old = _run(version, RunStatus.FAILED, finished=datetime(2026, 2, 1, tzinfo=UTC), took=timedelta(seconds=9))
        session.add_all([*runs, cancelled, old])
        await session.flush()
        for took, run in enumerate(runs, start=1):
            down = run.status is RunStatus.COMPLETED_WITH_ERRORS
            b = RunItemStatus.FAILED if down else RunItemStatus.SUCCEEDED
            session.add_all(
                [
                    _element(run, "reachable", "a", 0, RunItemStatus.SUCCEEDED, took=took),
                    _element(run, "reachable", "b", 1, b, took=10 * took, error="HTTP 503" if down else None),
                    _element(
                        run, "answers", "b", 1, RunItemStatus.SKIPPED if down else RunItemStatus.SUCCEEDED, took=1
                    ),
                ]
            )
        for run in (cancelled, old):
            session.add(_element(run, "reachable", "a", 0, RunItemStatus.FAILED, took=1))
        pipeline = await session.get(Pipeline, version.pipeline_id)
        assert pipeline is not None
        return pipeline


async def test_each_element_is_read_as_its_own_record_over_the_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await assert_the_items_fold(sessions)


async def assert_the_items_fold(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The whole item read over the seeded runs, which the PostgreSQL lane asserts with the same body."""
    pipeline = await seed_items(sessions)
    async with session_scope(sessions) as session:
        read = await item_stats(session, pipeline, end=END, since=WEEK)
    rows = {(row.step, row.item): row for row in read.items}
    assert [(row.step, row.item) for row in read.items] == [("reachable", "a"), ("reachable", "b"), ("answers", "b")]
    a, b, answers = rows["reachable", "a"], rows["reachable", "b"], rows["answers", "b"]
    assert (a.runs, a.succeeded, a.failed, a.uptime) == (4, 4, 0, 1.0), "a cancelled or older run counts for nothing"
    assert (a.p50_duration_ms, a.p95_duration_ms) == (2000, 4000)
    assert (b.succeeded, b.failed, b.uptime) == (3, 1, 0.75)
    assert (b.last_status, b.last_error) == (RunItemStatus.SUCCEEDED, "HTTP 503")
    assert b.last_failed_at == datetime(2026, 3, 8, 9, 59, 59, tzinfo=UTC)
    assert [(day.day, day.succeeded, day.failed) for day in b.days] == [
        (date(2026, 3, 8), 1, 1),
        (date(2026, 3, 9), 2, 0),
    ]
    assert (answers.skipped, answers.uptime) == (1, 1.0), "a skipped element is neither up nor down"


async def test_an_element_read_narrows_to_one_step(sessions: async_sessionmaker[AsyncSession]) -> None:
    pipeline = await seed_items(sessions)
    async with session_scope(sessions) as session:
        read = await item_stats(session, pipeline, end=END, since=WEEK, step="answers")
    assert [(row.step, row.item) for row in read.items] == [("answers", "b")]
