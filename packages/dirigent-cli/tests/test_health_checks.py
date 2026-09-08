"""The container health checks, which decide whether an orchestrator restarts a process."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_cli.health import (
    MISSED_BEATS,
    Check,
    database_check,
    is_beating,
    latest_heartbeat,
    named_server,
    scheduler_check,
    server_check,
    verdict,
    worker_check,
)
from dirigent_client.enums import ScheduleKind, WorkerStatus
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory
from dirigent_core.models import Base, Pipeline, Schedule, Worker, utcnow

HOST = "container-abc123"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'health.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
    )


@pytest.fixture
async def session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as opened:
        yield opened
    await engine.dispose()


async def register(
    session: AsyncSession, *, hostname: str, age: timedelta, status: WorkerStatus = WorkerStatus.RUNNING
) -> None:
    session.add(
        Worker(
            id=uuid4(),
            name=f"{hostname}-{uuid4().hex[:6]}",
            hostname=hostname,
            version="0.1.0",
            plugins={},
            tags=[],
            concurrency=1,
            status=status,
            last_seen_at=utcnow() - age,
        )
    )
    await session.commit()


async def test_a_worker_that_beat_a_moment_ago_is_healthy(settings: Settings, session: AsyncSession) -> None:
    await register(session, hostname=HOST, age=timedelta(seconds=1))
    assert (await worker_check(session, settings, HOST)).status == "healthy"


async def test_a_worker_that_stopped_beating_is_not_healthy(settings: Settings, session: AsyncSession) -> None:
    """Six missed beats is the tolerance, so seven is unambiguously stuck."""
    stale = settings.heartbeat * (MISSED_BEATS + 1)
    await register(session, hostname=HOST, age=stale)

    check = await worker_check(session, settings, HOST)

    assert check.status == "unhealthy"
    assert "went silent" in check.detail


async def test_a_worker_that_never_registered_is_absent_rather_than_broken(
    settings: Settings, session: AsyncSession
) -> None:
    """Nothing of it is here, which fails only where the caller said there should be one."""
    assert await latest_heartbeat(session, HOST) is None

    check = await worker_check(session, settings, HOST)

    assert check.status == "absent"
    assert check.failed(asserted=True), "dg health worker asserts a worker runs here"
    assert not check.failed(asserted=False), "dg health reports what is not here without failing"


async def test_a_worker_that_stopped_cleanly_is_history_rather_than_a_fault(
    settings: Settings, session: AsyncSession
) -> None:
    """A clean shutdown writes stopped, so a stopped dev instance reads as stopped, not broken."""
    await register(session, hostname=HOST, age=timedelta(hours=7), status=WorkerStatus.STOPPED)

    check = await worker_check(session, settings, HOST)

    assert check.status == "absent"
    assert check.detail == f"every worker on {HOST} has stopped"


async def test_the_bare_form_asks_about_every_worker_the_instance_has(
    settings: Settings, session: AsyncSession
) -> None:
    """From a laptop pointed at a real instance, the workers that matter are all of them."""
    await register(session, hostname="node-a", age=timedelta(seconds=1))
    await register(session, hostname="node-b", age=timedelta(seconds=2))
    await register(session, hostname="node-c", age=timedelta(days=2), status=WorkerStatus.STOPPED)

    check = await worker_check(session, settings)

    assert check.status == "healthy"
    assert check.detail == "2 of 2 workers beating"


async def test_another_hosts_worker_does_not_make_this_container_healthy(
    settings: Settings, session: AsyncSession
) -> None:
    """A healthy worker on another host does not make this host healthy."""
    await register(session, hostname="some-other-container", age=timedelta(seconds=1))
    assert (await worker_check(session, settings, HOST)).status == "absent"


async def test_the_newest_row_for_a_host_is_the_one_read(settings: Settings, session: AsyncSession) -> None:
    """A restarted worker leaves its old row behind; the live one is the newest."""
    await register(session, hostname=HOST, age=timedelta(hours=2))
    session.add(
        Worker(
            id=uuid4(),
            name=f"{HOST}-2",
            hostname=HOST,
            version="0.1.0",
            plugins={},
            tags=[],
            concurrency=1,
            status=WorkerStatus.RUNNING,
            last_seen_at=utcnow(),
        )
    )
    await session.commit()
    assert await latest_heartbeat(session, HOST) is not None
    assert (await worker_check(session, settings, HOST)).status == "healthy"


def test_the_tolerance_follows_the_configured_heartbeat() -> None:
    """The window is a multiple of the beat, so a slower heartbeat is not called a failure."""
    now = utcnow()
    seen = now - timedelta(seconds=100)
    assert not is_beating(seen, heartbeat=timedelta(seconds=10), now=now)
    assert is_beating(seen, heartbeat=timedelta(seconds=30), now=now)
    assert not is_beating(None, heartbeat=timedelta(seconds=30), now=now)


async def schedule(session: AsyncSession, *, due_in: timedelta, paused: bool = False) -> None:
    """Store one schedule of its own pipeline, next due whenever the test says."""
    pipeline = Pipeline(id=uuid4(), code=f"p-{uuid4().hex[:8]}")
    session.add(pipeline)
    session.add(
        Schedule(
            id=uuid4(),
            pipeline_id=pipeline.id,
            code="nightly",
            kind=ScheduleKind.INTERVAL,
            interval_seconds=3600,
            paused=paused,
            next_fire_at=utcnow() + due_in,
        )
    )
    await session.commit()


async def test_an_instance_with_no_schedules_has_nothing_to_be_late(settings: Settings, session: AsyncSession) -> None:
    check = await scheduler_check(session, settings)

    assert check.status == "healthy"
    assert check.detail == "no schedule is waiting to fire"


async def test_a_schedule_late_by_less_than_the_grace_is_not_a_failure(
    settings: Settings, session: AsyncSession
) -> None:
    """A tick is late by seconds all the time; the misfire grace is what says too late."""
    await schedule(session, due_in=-(settings.scheduler_misfire_grace - timedelta(seconds=30)))

    check = await scheduler_check(session, settings)

    assert check.status == "healthy"
    assert check.detail == "1 schedules waiting, none overdue"


async def test_a_schedule_later_than_the_grace_means_nothing_is_ticking(
    settings: Settings, session: AsyncSession
) -> None:
    """Leadership is invisible from another process, so the work is what gets checked."""
    await schedule(session, due_in=-(settings.scheduler_misfire_grace + timedelta(minutes=10)))
    await schedule(session, due_in=timedelta(hours=1))

    check = await scheduler_check(session, settings)

    assert check.status == "unhealthy"
    assert "1 of 2 schedules overdue" in check.detail


async def test_a_paused_schedule_is_never_overdue(settings: Settings, session: AsyncSession) -> None:
    """Pausing is a person saying not to fire it, not the scheduler failing to."""
    await schedule(session, due_in=-timedelta(days=30), paused=True)

    assert (await scheduler_check(session, settings)).status == "healthy"


def test_a_server_that_is_not_listening_is_absent_rather_than_unhealthy(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing on the port is "this host serves nothing", which the bare form reports."""

    def refuse(*_: object, **__: object) -> object:
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr(httpx2, "get", refuse)

    check = server_check(settings)

    assert check.status == "absent"
    assert str(settings.port) in check.detail


def test_a_server_that_answers_badly_is_unhealthy(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_: object, **__: object) -> httpx2.Response:
        return httpx2.Response(503)

    monkeypatch.setattr(httpx2, "get", unavailable)

    check = server_check(settings)

    assert check.status == "unhealthy"
    assert "503" in check.detail


def test_liveness_and_readiness_ask_different_questions(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process that is up and cannot reach its database is the case anyone cares about."""
    asked: list[str] = []

    def record(url: str, **_: object) -> httpx2.Response:
        asked.append(url)
        return httpx2.Response(200)

    monkeypatch.setattr(httpx2, "get", record)

    live = server_check(settings, probe="liveness")
    ready = server_check(settings, probe="readiness")

    assert [url.rsplit(str(settings.port), 1)[-1] for url in asked] == ["/health", "/health/ready"]
    assert (live.probe, live.status) == ("liveness", "healthy")
    assert live.detail.endswith("is alive")
    assert (ready.probe, ready.status) == ("readiness", "healthy")
    assert ready.detail.endswith("is ready")


def test_a_check_fails_the_command_only_where_it_should() -> None:
    """Absent is a failure where the caller named the component, and nowhere else."""
    absent = Check(check="worker", status="absent", detail="none here")
    broken = Check(check="worker", status="unhealthy", detail="stopped beating")
    fine = Check(check="worker", status="healthy", detail="beating")

    assert [absent.failed(asserted=False), absent.failed(asserted=True)] == [False, True]
    assert [broken.failed(asserted=False), broken.failed(asserted=True)] == [True, True]
    assert [fine.failed(asserted=False), fine.failed(asserted=True)] == [False, False]


async def test_a_sqlite_database_that_is_not_there_is_absent(tmp_path: Path) -> None:
    """Opening a SQLite URL creates the file, so the check looks before it opens."""
    missing = tmp_path / "nowhere.db"
    settings = Settings(database_url=f"sqlite+aiosqlite:///{missing}", artifact_root=f"file://{tmp_path}")

    check = await database_check(settings)

    assert check.status == "absent"
    assert not missing.exists(), "looking at a database created one"


async def test_a_database_with_no_schema_names_the_command_that_fixes_it(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    empty.touch()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{empty}", artifact_root=f"file://{tmp_path}")

    check = await database_check(settings)

    assert check.status == "unhealthy"
    assert "dg db upgrade" in check.detail


def test_the_verdict_counts_absent_apart_from_healthy() -> None:
    """Nothing here is a different fact from nothing wrong here."""
    checks = [
        Check(check="database", status="healthy", detail=""),
        Check(check="worker", status="absent", detail=""),
        Check(check="server", status="unhealthy", detail=""),
    ]

    summary = verdict(checks)

    assert (summary["healthy"], summary["absent"], summary["unhealthy"]) == (1, 1, 1)
    assert summary["message"] == "1 of 3 checks failed: server"
    assert summary["level"] == "error"


def test_nothing_named_means_the_only_server_is_this_hosts_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container has no DG_URL, so its HEALTHCHECK keeps asking its own loopback."""
    monkeypatch.delenv("DG_URL", raising=False)
    assert named_server() is None
    assert named_server(url="http://dirigent.example.com") == "http://dirigent.example.com"
    monkeypatch.setenv("DG_URL", "http://one.example.com:3333")
    assert named_server() == "http://one.example.com:3333"


def test_the_named_server_is_the_one_asked(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """From a laptop, the server that matters is the one this shell talks to."""
    asked: list[str] = []

    def record(url: str, **_: object) -> httpx2.Response:
        asked.append(url)
        return httpx2.Response(200)

    monkeypatch.setattr(httpx2, "get", record)

    check = server_check(settings, server="http://dirigent.example.com")

    assert asked == ["http://dirigent.example.com/health/ready"]
    assert check.detail == "the server at dirigent.example.com is ready"
