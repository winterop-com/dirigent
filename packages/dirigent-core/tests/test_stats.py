"""Run stats, folded from runs and attempts seeded with known durations and errors."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.database import session_scope
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import save_pipeline
from dirigent_core.models import PipelineVersion, Run, StepAttempt
from dirigent_core.stats import percentile, run_stats

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
