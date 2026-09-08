"""End-to-end runs on the standalone internals: real blocks, real engine, one SQLite file."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_blocks.connections import HttpConnectionConfig
from dirigent_client.enums import AttemptStatus, RunItemStatus, RunStatus
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import (
    ItemPolicy,
    PipelineDefinition,
    RetryPolicy,
    StepDefinition,
    TimeoutAction,
)
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import Base, Connection, Run, RunItem, StepAttempt
from dirigent_core.plugins import load_plugin_host

RESPONSES: dict[str, httpx2.Response] = {}
REQUESTS: list[httpx2.Request] = []


def service(request: httpx2.Request) -> httpx2.Response:
    """Answer a request from the scripted table, or 404 when nothing matches."""
    REQUESTS.append(request)
    return RESPONSES.get(request.url.path, httpx2.Response(404, json={"error": "no such path"}))


@pytest.fixture(autouse=True)
def _fake_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Replace only the transport: connections are still resolved and decrypted for real."""
    from dirigent_core.engine import context

    original = context.build_http_client

    def patched(config: Any) -> httpx2.AsyncClient:
        real = original(config)
        return httpx2.AsyncClient(
            base_url=real.base_url,
            headers=real.headers,
            auth=real.auth,
            transport=httpx2.MockTransport(service),
        )

    monkeypatch.setattr(context, "build_http_client", patched)
    RESPONSES.clear()
    REQUESTS.clear()
    yield
    RESPONSES.clear()
    REQUESTS.clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A standalone instance: one SQLite file, a local artifact root, shell.run allowed."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        enabled_unsafe_blocks=["shell.run"],
    )


@pytest.fixture
def services(settings: Settings) -> EngineServices:
    """The services a dg dev process would assemble."""
    return EngineServices.build(settings, load_plugin_host())


@pytest.fixture
async def db(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A database created from the ORM metadata."""
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory the engine uses."""
    return create_session_factory(db)


@pytest.fixture
def engine(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> Engine:
    """The engine, leasing as the embedded dev worker does."""
    return Engine(sessions, services, owner="dev-worker")


async def store_connection(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> None:
    """Store the API connection with its bearer token encrypted at rest."""
    config = HttpConnectionConfig(base_url="http://service.test", bearer_token=SecretStr("s3cret"))
    public, envelope, key_id = services.secrets.encrypt_config(HttpConnectionConfig, config)
    async with session_scope(sessions) as session:
        session.add(Connection(code="api", kind="http", config=public, secret_envelope=envelope, secret_key_id=key_id))


async def start(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    definition: PipelineDefinition,
    **params: Any,
) -> Run:
    """Save a pipeline version and create one run of it."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        run = await create_run(session, services, version, params=params or None)
    assert run is not None
    return run


async def drain(engine: Engine, *, step: timedelta = timedelta(seconds=5), limit: int = 200) -> None:
    """Claim and run every due unit, advancing a virtual clock so waits come due."""
    moment = datetime.now(UTC)
    for _ in range(limit):
        unit = await engine.claim(now=moment)
        if unit is None:
            return
        await engine.run_unit(unit, now=moment)
        moment += step
    raise AssertionError("the run never settled")


async def reload(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> Run:
    """Read a run back."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        return run


async def attempts(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> dict[str, StepAttempt]:
    """Read a run's latest attempt per step."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(StepAttempt).where(StepAttempt.run_id == run_id).order_by(StepAttempt.attempt)
        )
        return {attempt.step_name: attempt for attempt in rows.scalars()}


async def test_a_three_step_pipeline_runs_to_completion(
    engine: Engine,
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    tmp_path: Path,
) -> None:
    RESPONSES["/v1/day"] = httpx2.Response(200, json={"rows": 42})
    await store_connection(sessions, services)

    # Must live inside the artifact root: file:// addresses nothing outside it.
    drop = tmp_path / "artifacts" / "drops" / "2026-08-28.json"
    drop.parent.mkdir(parents=True)
    drop.write_text('{"rows": 42}')

    definition = PipelineDefinition(
        code="daily-load",
        params={"type": "object", "required": ["day"], "properties": {"day": {"type": "string"}}},
        steps={
            "fetch": StepDefinition(
                block="http.request",
                config={"connection": "api", "method": "GET", "path": "/v1/day", "query": {"day": "${params.day}"}},
            ),
            "stage": StepDefinition(
                block="storage.copy",
                depends_on=["fetch"],
                config={
                    "source": f"file://{tmp_path}/artifacts/drops/${{params.day}}.json",
                    "target": "${run.scratch}/staged.json",
                },
            ),
            "report": StepDefinition(
                block="shell.run",
                depends_on=["stage"],
                config={
                    "command": "echo staged ${steps.fetch.output.status} from ${steps.stage.output.bytes_copied} bytes"
                },
            ),
        },
    )
    run = await start(sessions, services, definition, day="2026-08-28")
    await drain(engine)

    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED
    settled = await attempts(sessions, run.id)
    assert settled["fetch"].output is not None
    assert settled["fetch"].output["status"] == 200
    assert settled["fetch"].output["json_body"] == {"rows": 42}
    assert settled["stage"].output is not None
    assert settled["stage"].output["bytes_copied"] == 12
    assert settled["report"].output is not None
    assert settled["report"].output["stdout"].strip() == "staged 200 from 12 bytes"

    assert REQUESTS[0].headers["authorization"] == "Bearer s3cret", "the stored secret was decrypted"
    assert REQUESTS[0].url.params["day"] == "2026-08-28"
    staged = Path(f"{tmp_path}/artifacts/runs/{run.id}/staged.json")
    assert staged.read_text() == '{"rows": 42}'


async def test_a_fan_out_with_one_bad_item_completes_with_errors(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    RESPONSES["/v1/ingest/no"] = httpx2.Response(202, json={"accepted": True})
    RESPONSES["/v1/ingest/se"] = httpx2.Response(202, json={"accepted": True})
    RESPONSES["/v1/ingest/dk"] = httpx2.Response(422, json={"error": "unknown region"})
    await store_connection(sessions, services)

    definition = PipelineDefinition(
        code="regional-push",
        params={"type": "object", "properties": {"regions": {"type": "array", "default": ["no", "se", "dk"]}}},
        steps={
            "push": StepDefinition(
                block="http.request",
                for_each="${params.regions}",
                items=ItemPolicy.CONTINUE,
                retry=RetryPolicy(max_attempts=3, backoff=timedelta(0), jitter=0.0),
                config={
                    "connection": "api",
                    "method": "POST",
                    "path": "/v1/ingest/${item}",
                    "success_status": [202],
                    "body": {"region": "${item}"},
                },
            )
        },
    )
    run = await start(sessions, services, definition)
    await drain(engine)

    assert (await reload(sessions, run.id)).status is RunStatus.COMPLETED_WITH_ERRORS
    async with sessions() as session:
        rows = await session.execute(sa.select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.item_index))
        items = list(rows.scalars())
    assert [(item.item_key, item.status) for item in items] == [
        ("no", RunItemStatus.SUCCEEDED),
        ("se", RunItemStatus.SUCCEEDED),
        ("dk", RunItemStatus.FAILED),
    ]
    assert items[2].failing_step == "push"
    assert "422" in (items[2].error or "")

    async with sessions() as session:
        tried = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))
        failed = [attempt for attempt in tried.scalars() if attempt.status is AttemptStatus.FAILED]
    assert len(failed) == 1, "a 4xx is rejected, so it never consumes a second attempt"


async def test_a_sensor_that_times_out_skips_its_branch(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    definition = PipelineDefinition(
        code="waiting-load",
        steps={
            "wait_for_drop": StepDefinition(
                block="storage.exists",
                config={"uri": f"file://{tmp_path}/artifacts/drops/never.parquet"},
                poll=timedelta(seconds=1),
                deadline=timedelta(seconds=3),
                on_timeout=TimeoutAction.SKIP,
            ),
            "load": StepDefinition(block="shell.run", depends_on=["wait_for_drop"], config={"command": "echo go"}),
        },
    )
    run = await start(sessions, services, definition)
    await drain(engine, step=timedelta(seconds=2))

    settled = await attempts(sessions, run.id)
    assert settled["wait_for_drop"].status is AttemptStatus.SKIPPED
    assert "deadline" in (settled["wait_for_drop"].error or "")
    assert settled["load"].status is AttemptStatus.SKIPPED
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_a_sensor_observes_the_drop_when_it_arrives(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices, tmp_path: Path
) -> None:
    drops = tmp_path / "artifacts" / "drops"
    drops.mkdir(parents=True)
    definition = PipelineDefinition(
        code="patient-load",
        steps={
            "wait_for_drop": StepDefinition(
                block="storage.exists",
                config={"uri": f"file://{drops}/*.parquet"},
                poll=timedelta(seconds=1),
                deadline=timedelta(seconds=30),
                on_timeout=TimeoutAction.FAIL,
            ),
            "load": StepDefinition(
                block="shell.run",
                depends_on=["wait_for_drop"],
                config={"command": "echo loaded ${steps.wait_for_drop.output.size} bytes"},
            ),
        },
    )
    run = await start(sessions, services, definition)

    moment = datetime.now(UTC)
    for index in range(20):
        if index == 3:
            (drops / "climate.parquet").write_bytes(b"parquet-data")
        unit = await engine.claim(now=moment)
        if unit is None:
            break
        await engine.run_unit(unit, now=moment)
        moment += timedelta(seconds=2)

    settled = await attempts(sessions, run.id)
    assert settled["wait_for_drop"].status is AttemptStatus.SUCCEEDED
    assert settled["load"].output is not None
    assert settled["load"].output["stdout"].strip() == "loaded 12 bytes"
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


def test_the_installed_catalog_is_what_a_dev_process_would_serve(services: EngineServices) -> None:
    catalog = services.host.catalog()
    assert sorted(entry.id for entry in catalog.blocks) == [
        "convert.arrow",
        "convert.std",
        "docker.build",
        "docker.compose.down",
        "docker.compose.up",
        "docker.run",
        "filter.jq",
        "git.checkout",
        "http.ready",
        "http.request",
        "kafka.consume",
        "kafka.produce",
        "map.jq",
        "pipeline.run",
        "rabbitmq.consume",
        "shell.run",
        "sql.execute",
        "sql.query",
        "storage.copy",
        "storage.exists",
        "time.sleep",
        "time.window",
        "transform.jq",
        "validate.schema",
        "value.const",
        "webhook.post",
    ]
    assert [entry.id for entry in catalog.connection_kinds] == [
        "docker",
        "email",
        "git",
        "http",
        "kafka",
        "rabbitmq",
        "s3",
        "slack",
        "sql",
        "webhook",
    ]
    assert sorted(entry.id for entry in catalog.notifiers) == ["email", "log", "slack", "webhook"]
    assert sorted(entry.id for entry in catalog.storage_schemes) == ["s3"]
    assert catalog.digest.startswith("sha256:")


def test_the_engine_serialises_claims_on_sqlite() -> None:
    from dirigent_core.engine.executor import SQLITE_CLAIM_LOCK

    assert isinstance(SQLITE_CLAIM_LOCK, asyncio.Lock)


# -- the docker reaper's half that is a database read ----------------------------


async def test_the_reaper_reads_a_runs_status_out_of_the_database(
    engine: Engine, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    from dirigent_cli import reaper

    definition = PipelineDefinition(
        code="reaper-subject",
        steps={"only": StepDefinition(block="value.const", config={"value": 1})},
    )
    run = await start(sessions, services, definition)
    look_up = reaper.lookup(sessions)

    queued = await look_up(run.id)
    assert queued is not None
    assert queued.active is True

    await drain(engine)
    settled = await look_up(run.id)
    assert settled is not None
    assert settled.active is False
    assert settled.status == RunStatus.SUCCEEDED.value

    assert await look_up(UUID(int=0)) is None


async def test_the_reaping_chore_logs_a_record_for_each_project_a_pass_took(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    from dirigent_blocks.reap import Reaped
    from dirigent_cli import reaper

    def a_daemon() -> bool:
        return True

    run_id = UUID(int=7)
    taken = [Reaped(f"dirigent-{run_id.hex}", run_id, "cancelled", torn_down=True)]

    async def one_pass(_settings: object, _sessions: object, *, dry_run: bool = False) -> list[Reaped]:
        return taken

    monkeypatch.setattr(reaper, "reachable", a_daemon)
    monkeypatch.setattr(reaper, "pass_once", one_pass)
    chore = reaper.chore(settings, sessions)
    assert chore is not None
    assert chore.name == "docker-reap"
    await chore.run()
