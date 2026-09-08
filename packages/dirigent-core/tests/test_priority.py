"""Claim order: priority first, then round-robin fairness between runs, then due time."""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunPriority, RunStatus, TriggerKind
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.claim import due_attempt_statement, select_due
from dirigent_core.engine.definition import (
    PipelineDefinition,
    ScheduleSpec,
    StepDefinition,
    TriggerSpecs,
    WebhookSpec,
)
from dirigent_core.engine.runs import Attribution, EngineRuns, create_run, save_pipeline
from dirigent_core.models import Pipeline, Run, Schedule, StepAttempt, WebhookTrigger, utcnow
from dirigent_core.triggers.materialize import materialize_triggers
from dirigent_core.triggers.schedules import ScheduleRequest, create_schedule
from dirigent_core.triggers.webhooks import WebhookRequest, create_webhook


def fanned(code: str, count: int, *, priority: RunPriority = RunPriority.NORMAL) -> PipelineDefinition:
    """A one-step pipeline whose fan-out gives the claim ``count`` due attempts at once."""
    return PipelineDefinition(
        code=code,
        priority=priority,
        steps={
            "push": StepDefinition(
                block="test.echo",
                for_each=[f"item-{index}" for index in range(count)],
                config={"value": "${item}"},
            )
        },
    )


async def pipeline_of(session: AsyncSession, pipeline_id: UUID) -> Pipeline:
    """Read the pipeline row a version belongs to."""
    pipeline = await session.get(Pipeline, pipeline_id)
    assert pipeline is not None
    return pipeline


async def start(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    definition: PipelineDefinition,
    *,
    priority: RunPriority | None = None,
) -> Run:
    """Save a pipeline version and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version, priority=priority)
    assert run is not None
    return run


async def claimed_runs(sessions: async_sessionmaker[AsyncSession], count: int) -> list[UUID]:
    """Take up to ``count`` attempts in claim order and name the run each belongs to.

    The claim query is what is under test, so each row is taken and settled here rather than
    executed: what matters is which run the next due attempt came from.
    """
    taken: list[UUID] = []
    for _ in range(count):
        async with session_scope(sessions) as session:
            attempt = await select_due(session, utcnow())
            if attempt is None:
                break
            taken.append(attempt.run_id)
            attempt.status = AttemptStatus.SUCCEEDED
    return taken


def took_turns(taken: Sequence[UUID]) -> bool:
    """Report whether the runs alternated rather than one draining before the other."""
    return all(first != second for first, second in zip(taken, taken[1:], strict=False))


async def test_two_runs_interleave_rather_than_one_draining_first(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A big fan-out does not take every slot ahead of the small run queued behind it."""
    big = await start(sessions, services, fanned("big", 8))
    small = await start(sessions, services, fanned("small", 2))

    taken = await claimed_runs(sessions, 4)

    assert len(taken) == 4
    assert took_turns(taken), f"the two runs should take turns, and took {taken}"
    assert set(taken) == {big.id, small.id}


async def test_a_high_run_is_claimed_before_every_other(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Priority sorts ahead of fairness, so the urgent run's attempts all come first."""
    await start(sessions, services, fanned("ordinary", 3))
    urgent = await start(sessions, services, fanned("urgent", 3), priority=RunPriority.HIGH)

    assert await claimed_runs(sessions, 3) == [urgent.id] * 3


async def test_a_low_run_is_claimed_after_every_other(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Low means last, even where the low run's attempts were queued first."""
    await start(sessions, services, fanned("bulk", 3, priority=RunPriority.LOW))
    ordinary = await start(sessions, services, fanned("ordinary", 3))

    assert await claimed_runs(sessions, 3) == [ordinary.id] * 3


async def test_the_priority_is_pinned_at_creation(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Editing the document does not reorder a run that is already in flight."""
    run = await start(sessions, services, fanned("edited", 1, priority=RunPriority.HIGH))
    async with session_scope(sessions) as session:
        await save_pipeline(session, fanned("edited", 1, priority=RunPriority.LOW))

    async with sessions() as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert stored.priority is RunPriority.HIGH


async def test_a_run_takes_the_documents_priority_when_nothing_overrides_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The document's own word is what the layering starts from."""
    run = await start(sessions, services, fanned("nightly", 1, priority=RunPriority.LOW))
    assert run.priority is RunPriority.LOW


async def test_an_ad_hoc_run_overrides_the_documents_priority(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The same bulk pipeline, run by hand during an incident, is not low."""
    run = await start(sessions, services, fanned("nightly", 1, priority=RunPriority.LOW), priority=RunPriority.HIGH)
    assert run.priority is RunPriority.HIGH


async def test_a_schedule_overrides_the_documents_priority_for_what_it_fires(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A schedule's declared priority reaches the run it fires, and nothing else."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, fanned("scheduled", 1, priority=RunPriority.LOW))
        schedule = await create_schedule(
            session,
            await pipeline_of(session, version.pipeline_id),
            ScheduleRequest(code="nightly", cron="0 2 * * *", priority=RunPriority.NORMAL),
        )
        fired = await create_run(
            session,
            services,
            version,
            attribution=Attribution(kind=TriggerKind.SCHEDULE, id=schedule.id, label="schedule nightly"),
            priority=schedule.priority,
        )
        ad_hoc = await create_run(session, services, version)

    assert fired is not None and fired.priority is RunPriority.NORMAL
    assert ad_hoc is not None and ad_hoc.priority is RunPriority.LOW


async def test_a_webhook_overrides_the_documents_priority_for_what_it_triggers(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A webhook carries its own priority onto every delivery it accepts."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, fanned("hooked", 1, priority=RunPriority.LOW))
        minted = await create_webhook(
            session,
            await pipeline_of(session, version.pipeline_id),
            WebhookRequest(code="push", priority=RunPriority.HIGH),
        )
        webhook = await session.get(WebhookTrigger, minted.webhook_id)
        assert webhook is not None
        run = await create_run(
            session,
            services,
            version,
            attribution=Attribution(kind=TriggerKind.WEBHOOK, id=webhook.id, label="webhook push"),
            priority=webhook.priority,
        )

    assert run is not None
    assert run.priority is RunPriority.HIGH


async def test_a_declared_priority_is_materialized_and_redeclared(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A document's triggers section owns the priority on the rows it materializes."""
    declared = PipelineDefinition(
        code="declared",
        priority=RunPriority.LOW,
        steps={"only": StepDefinition(block="test.echo")},
        triggers=TriggerSpecs(
            schedules=[ScheduleSpec(code="nightly", cron="0 2 * * *", priority=RunPriority.NORMAL)],
            webhooks=[WebhookSpec(code="push", priority=RunPriority.HIGH)],
        ),
    )
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, declared)
        await materialize_triggers(session, await pipeline_of(session, version.pipeline_id), declared)

    async with sessions() as session:
        assert (await session.execute(sa.select(Schedule))).scalars().one().priority is RunPriority.NORMAL
        assert (await session.execute(sa.select(WebhookTrigger))).scalars().one().priority is RunPriority.HIGH

    lowered = declared.model_copy(
        update={
            "triggers": TriggerSpecs(
                schedules=[ScheduleSpec(code="nightly", cron="0 2 * * *", priority=RunPriority.LOW)],
                webhooks=[WebhookSpec(code="push")],
            )
        }
    )
    async with session_scope(sessions) as session:
        result = await materialize_triggers(session, await pipeline_of(session, version.pipeline_id), lowered)
        assert result.schedules_updated == ["nightly"]
        assert result.webhooks_updated == ["push"]

    async with sessions() as session:
        assert (await session.execute(sa.select(Schedule))).scalars().one().priority is RunPriority.LOW
        assert (await session.execute(sa.select(WebhookTrigger))).scalars().one().priority is None


async def test_a_child_run_inherits_the_priority_of_the_run_that_started_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A parent waiting on its child gains nothing from the child queueing behind everything."""
    async with session_scope(sessions) as session:
        await save_pipeline(session, fanned("child", 1))
    parent = await start(sessions, services, fanned("parent", 1), priority=RunPriority.HIGH)

    async with session_scope(sessions) as session:
        started = await EngineRuns(services, session=session, parent_run_id=parent.id).start("child", {}, max_depth=3)
        assert started.run_id is not None
        created = await session.get(Run, started.run_id)
        assert created is not None
        assert created.priority is RunPriority.HIGH


async def test_the_ranking_narrows_what_the_filters_found_and_adds_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """An attempt of a run that is no longer claimable stays unclaimed, rank or no rank."""
    run = await start(sessions, services, fanned("held", 2))
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        stored.status = RunStatus.CANCELLED

    async with sessions() as session:
        assert await select_due(session, utcnow()) is None


async def test_an_attempt_not_yet_due_waits_however_urgent_its_run_is(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Priority reorders the due rows; it does not make an attempt due before its time."""
    await start(sessions, services, fanned("later", 1), priority=RunPriority.HIGH)
    async with session_scope(sessions) as session:
        attempt = (await session.execute(sa.select(StepAttempt))).scalars().one()
        attempt.available_at = utcnow() + timedelta(hours=1)

    async with sessions() as session:
        assert await select_due(session, utcnow()) is None


def test_every_claimability_predicate_is_on_the_locked_relation() -> None:
    """The invariant that keeps two workers off one attempt, asserted on the statement itself.

    ``SKIP LOCKED`` re-checks a row that changed under it against the outer query's own
    predicates alone, so a status or due test living only in the ranking subquery is never
    re-evaluated and the claim hands out an attempt another worker has already taken. The
    subquery ranks; the outer select decides.
    """
    statement = due_attempt_statement(utcnow(), ["docker"], postgres=True).with_for_update(
        skip_locked=True, of=StepAttempt
    )
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    outer = sql[sql.rindex(") AS anon_1") :]

    assert "step_attempts.status = 'queued'" in outer
    assert "step_attempts.status = 'waiting'" in outer
    assert "step_attempts.available_at <=" in outer
    assert "step_attempts.next_poll_at <=" in outer
    assert "runs.status IN ('queued', 'running')" in outer
    assert "runs.worker_tags <@" in outer, "the tag routing decides claimability too"
    assert "FOR UPDATE OF step_attempts SKIP LOCKED" in outer
    assert "row_number()" not in outer, "the ranking is what the subquery is for"
