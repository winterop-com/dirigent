"""What `dg dev --seed` does to a live instance, read off the records the seeding emits."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from dirigent_cli.seeding import seed_directories, seed_installed
from dirigent_client import Dirigent, PlanAction
from dirigent_client.enums import UserRole
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_core.protocol import Record
from dirigent_server import create_app

PLAIN = """
format: dirigent/v1
kind: pipeline
code: seeded-plain
description: A document an instance stores as it stands, with a clock on it.
triggers:
  schedules:
    - code: nightly
      cron: "0 5 * * *"
      timezone: Europe/Oslo
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, hello]
"""

CARRYING = """
format: dirigent/v1
kind: pipeline
code: seeded-carrying
description: A document that carries the connection it names, so it also runs standalone.
connections:
  carried-service:
    kind: http
    config:
      base_url: https://carried.test
requires:
  connections: [carried-service]
steps:
  fetch:
    block: http.request
    config:
      connection: carried-service
      path: /things
"""

REFUSED = """
format: dirigent/v1
kind: pipeline
code: seeded-refused
description: A document naming a connection no instance holds.
requires:
  connections: [nobody-created-this]
steps:
  fetch:
    block: http.request
    config:
      connection: nobody-created-this
      path: /things
"""

CONNECTIONS = """
connections:
  declared-service:
    kind: http
    config:
      base_url: https://declared.test
"""

NOT_A_DOCUMENT = """
title: A note beside the corpus, which is not a document.
values: [1, 2, 3]
"""


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A small corpus: two documents an instance stores, one it refuses, and two other files."""
    directory = tmp_path / "corpus"
    (directory / "shelf").mkdir(parents=True)
    (directory / "connections.yaml").write_text(CONNECTIONS)
    (directory / "notes.yaml").write_text(NOT_A_DOCUMENT)
    (directory / "shelf" / "plain.yaml").write_text(PLAIN)
    (directory / "shelf" / "carrying.yaml").write_text(CARRYING)
    (directory / "shelf" / "refused.yaml").write_text(REFUSED)
    return directory


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """An instance pointed at a throwaway database, artifact root, and secret key."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}",
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        enabled_unsafe_blocks=["shell.run"],
    )


@pytest.fixture
def token(settings: Settings) -> str:
    """Create the schema and one admin account, and return a bearer token for it."""

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with session_scope(create_session_factory(engine)) as session:
                user = await create_user(session, "tester", "a test password", role=UserRole.ADMIN)
                issued = await issue_token(session, user, name="seeding-tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    return asyncio.run(prepare())


@pytest.fixture
async def dg(settings: Settings, token: str) -> AsyncIterator[Dirigent]:
    """A client whose requests reach the real application, so the seeding meets real routes."""
    app = create_app(settings, scheduler=False)
    async with (
        httpx2.ASGITransport(app) as transport,
        app.router.lifespan_context(app),
        Dirigent(url="http://testserver", token=token, http_transport=transport) as client,
    ):
        yield client


async def seeded(client: Dirigent, directory: Path) -> list[Record]:
    """Seed one directory and collect every record the seeding wrote."""
    return [record async for record in seed_directories(client, [directory])]


def of_kind(stream: list[Record], kind: str) -> list[Record]:
    """Take the records of one kind, which is what a reader reacts to."""
    return [record for record in stream if record["kind"] == kind]


async def test_a_corpus_is_applied_and_its_refusals_reported(dg: Dirigent, corpus: Path) -> None:
    stream = await seeded(dg, corpus)
    applied = of_kind(stream, "seed.applied")
    assert [record["pipeline"] for record in applied] == ["seeded-carrying", "seeded-plain"]
    assert {record["action"] for record in applied} == {PlanAction.CREATE.value}
    assert [record["schedules_paused"] for record in applied] == [[], ["nightly"]]
    refused = of_kind(stream, "seed.refused")
    assert len(refused) == 1
    assert refused[0]["document"].endswith("refused.yaml")
    assert "nobody-created-this" in refused[0]["reason"]


async def test_a_seeded_schedule_lands_paused(dg: Dirigent, corpus: Path) -> None:
    await seeded(dg, corpus)
    clocks = (await dg.schedules.list("seeded-plain")).items
    assert [(one.code, one.paused) for one in clocks] == [("nightly", True)]


async def test_the_connections_a_file_and_a_document_declare_are_created(dg: Dirigent, corpus: Path) -> None:
    stream = await seeded(dg, corpus)
    created = of_kind(stream, "seed.connection")
    assert [(record["connection"], record["connection_kind"], record["action"]) for record in created] == [
        ("declared-service", "http", "created"),
        ("carried-service", "http", "created"),
    ]
    assert created[0]["origin"].endswith("connections.yaml")
    assert created[1]["origin"].endswith("carrying.yaml")
    assert {row.code for row in (await dg.connections.list()).items} == {"declared-service", "carried-service"}


async def test_a_carried_section_is_created_and_not_stored_with_the_document(dg: Dirigent, corpus: Path) -> None:
    await seeded(dg, corpus)
    stored = await dg.pipelines.get("seeded-carrying")
    assert stored.document is not None
    assert "connections" not in stored.document
    assert stored.document["requires"] == {"connections": ["carried-service"]}


async def test_the_closing_record_counts_what_the_seeding_did(dg: Dirigent, corpus: Path) -> None:
    stream = await seeded(dg, corpus)
    done = of_kind(stream, "seed.done")[0]
    assert stream[-1] is done
    assert done["directories"] == [str(corpus)]
    assert done["pipelines"] == 2
    assert done["refused"] == 1
    assert done["connections"] == ["carried-service", "declared-service"]


async def test_seeding_the_same_corpus_twice_changes_nothing(dg: Dirigent, corpus: Path) -> None:
    await seeded(dg, corpus)
    stream = await seeded(dg, corpus)
    assert {record["action"] for record in of_kind(stream, "seed.applied")} == {PlanAction.UNCHANGED.value}
    assert {record["action"] for record in of_kind(stream, "seed.connection")} == {"updated"}
    assert of_kind(stream, "seed.done")[0]["refused"] == 1


async def test_the_installed_corpus_is_seeded_with_no_directory_named(dg: Dirigent) -> None:
    """`dg dev --seed-installed` reads what the build ships, not what a checkout holds."""
    stream = [record async for record in seed_installed(dg)]
    applied = of_kind(stream, "seed.applied")
    assert {record["pipeline"] for record in applied} >= {"hello-world", "report-to-file"}
    origins = {record["document"] for record in applied}
    assert all(origin.startswith("examples:") for origin in origins)
    closing = of_kind(stream, "seed.done")[-1]
    assert closing["plugins"] == ["examples"]
    assert closing["pipelines"] == len(applied)
