"""Claim routing by worker tags: what a run pins, and which worker may claim it."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import WorkerStatus
from dirigent_core.database import session_scope
from dirigent_core.documents import worker_routing_issues
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, Requirements, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Run, utcnow
from dirigent_core.models import Worker as WorkerRow
from dirigent_core.registry import STALE_AFTER, live_worker_tags, unmet_worker_tags


def tagged(*tags: str) -> PipelineDefinition:
    """A one-step pipeline requiring the given worker tags."""
    return PipelineDefinition(
        code="routed",
        steps={"only": StepDefinition(block="test.echo")},
        requires=Requirements(workers=list(tags)),
    )


async def start(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, definition: PipelineDefinition
) -> Run:
    """Save a pipeline version and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version)
    assert run is not None
    return run


def register(session: AsyncSession, name: str, *tags: str, seen_ago: timedelta = timedelta()) -> None:
    """Write a registry row for a worker carrying the given tags."""
    session.add(
        WorkerRow(
            name=name,
            hostname="somewhere",
            version="0",
            tags=list(tags),
            status=WorkerStatus.RUNNING,
            last_seen_at=utcnow() - seen_ago,
        )
    )


async def test_a_run_pins_the_tags_its_document_requires(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A later version of the document cannot re-route a run already in flight."""
    run = await start(sessions, services, tagged("docker", "gpu"))
    async with sessions() as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert stored.worker_tags == ["docker", "gpu"]


async def test_a_run_requiring_nothing_pins_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A document that says nothing about workers leaves the run claimable by any of them."""
    run = await start(sessions, services, tagged())
    async with sessions() as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert stored.worker_tags == []


async def test_an_untagged_worker_claims_a_run_that_requires_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The unrouted case stays exactly as it was."""
    await start(sessions, services, tagged())
    engine = Engine(sessions, services, owner="plain")
    assert await engine.claim() is not None


async def test_a_tagged_worker_claims_a_run_that_requires_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Carrying a capability never narrows what a worker is allowed to run."""
    await start(sessions, services, tagged())
    engine = Engine(sessions, services, owner="docker-host", tags=["docker"])
    assert await engine.claim() is not None


async def test_an_untagged_worker_never_claims_a_routed_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A run requiring a tag waits rather than landing on a worker that cannot run it."""
    await start(sessions, services, tagged("docker"))
    engine = Engine(sessions, services, owner="plain")
    assert await engine.claim() is None


async def test_a_worker_carrying_only_some_of_the_tags_never_claims(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Routing is a subset test, not an intersection."""
    await start(sessions, services, tagged("docker", "gpu"))
    engine = Engine(sessions, services, owner="half", tags=["docker"])
    assert await engine.claim() is None


async def test_a_worker_carrying_every_tag_and_more_claims(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A worker carrying a superset of what the run wants is exactly what routing is for."""
    await start(sessions, services, tagged("docker"))
    engine = Engine(sessions, services, owner="big", tags=["gpu", "docker", "arm64"])
    assert await engine.claim() is not None


async def test_the_registry_reports_the_tags_live_workers_carry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A worker that stopped heartbeating carries nothing as far as routing is concerned."""
    async with session_scope(sessions) as session:
        register(session, "beating", "docker")
        register(session, "silent", "gpu", seen_ago=STALE_AFTER + timedelta(minutes=1))
    async with sessions() as session:
        assert await live_worker_tags(session) == {"docker"}
        assert await unmet_worker_tags(session, ["docker", "gpu"]) == ["gpu"]
        assert await unmet_worker_tags(session, []) == []


async def test_a_stopped_worker_carries_nothing(sessions: async_sessionmaker[AsyncSession]) -> None:
    """A drained worker's row lingers; its tags do not count as capacity."""
    async with session_scope(sessions) as session:
        session.add(
            WorkerRow(name="drained", hostname="somewhere", version="0", tags=["docker"], status=WorkerStatus.STOPPED)
        )
    async with sessions() as session:
        assert await live_worker_tags(session) == set()


@pytest.mark.parametrize(
    ("required", "carried", "expected"),
    [
        (["docker"], {"docker"}, []),
        ([], set[str](), list[str]()),
        (["docker", "gpu"], {"docker"}, ["requires.workers"]),
    ],
)
def test_the_document_check_reports_tags_nobody_carries(
    required: list[str], carried: set[str], expected: list[str]
) -> None:
    """The check is about the instance as it stands now, so it warns rather than refusing."""
    issues = worker_routing_issues(tagged(*required), carried)
    assert [issue.location for issue in issues] == expected
    if issues:
        assert issues[0].message == "no live worker carries gpu; a run of this pipeline would wait until one does"
