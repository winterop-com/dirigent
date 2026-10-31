"""What `dg dev --seed` does to a live instance, read off the records the seeding emits."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from dirigent_cli.seeding import seed_directories, seed_installed
from dirigent_client import Dirigent, PlanAction, SourceState
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

BOTH_SOURCES = """
format: dirigent/v1
kind: pipeline
code: seeded-sources
description: A document with one source a worker pokes and one a caller calls.
steps:
  poked:
    source:
      kind: sensor
      block: playground.arrive
      config:
        after: 5s
        after_pokes: 0
      poll: 1s
      max_in_flight: 2
  called:
    source:
      kind: endpoint
      path: /seeded-sources
      auth:
        kind: public
  after_poked:
    block: shell.run
    depends_on: [poked]
    config:
      argv: [echo, poked]
  after_called:
    block: shell.run
    depends_on: [called]
    config:
      argv: [echo, called]
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


async def test_a_seeded_source_that_starts_runs_by_itself_lands_paused(dg: Dirigent, tmp_path: Path) -> None:
    directory = tmp_path / "self-starting"
    directory.mkdir()
    (directory / "both.yaml").write_text(BOTH_SOURCES)

    stream = await seeded(dg, directory)

    assert (await dg.sources.get("seeded-sources", "poked")).state is SourceState.PAUSED
    assert (await dg.sources.get("seeded-sources", "called")).state is SourceState.LISTENING
    [applied] = of_kind(stream, "seed.applied")
    assert applied["sources_paused"] == ["poked"]


async def test_re_seeding_leaves_a_resumed_source_running_and_names_nothing(dg: Dirigent, tmp_path: Path) -> None:
    directory = tmp_path / "self-starting"
    directory.mkdir()
    (directory / "both.yaml").write_text(BOTH_SOURCES)
    await seeded(dg, directory)
    await dg.sources.resume("seeded-sources", "poked")

    stream = await seeded(dg, directory)

    [applied] = of_kind(stream, "seed.applied")
    assert applied["action"] == PlanAction.UNCHANGED.value
    assert applied["sources_paused"] == []
    assert (await dg.sources.get("seeded-sources", "poked")).state is not SourceState.PAUSED


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


SCHEMA_FIRST = """
format: dirigent/v1
kind: pipeline
code: seeded-gated
description: A document carrying the shape its gate validates against.
schemas:
  seeded-shape:
    $id: seeded-shape
    title: Seeded shape
    description: The shape as the corpus first declared it.
    type: object
requires:
  schemas: [seeded-shape]
steps:
  gate:
    block: validate.schema
    config:
      input: {}
      schema: seeded-shape
"""

SCHEMA_RELABELLED = SCHEMA_FIRST.replace("title: Seeded shape", "title: Renamed shape").replace(
    "description: The shape as the corpus first declared it.\n    type: object",
    "type: object",
)


async def test_re_seeding_a_carried_schema_relabels_it_from_what_the_document_declares(
    dg: Dirigent, tmp_path: Path
) -> None:
    """A corpus labels a schema the same way on a fresh instance and on a seeded one.

    Storing a schema reads its own ``title`` and ``description`` and editing one reads
    neither, so the replacement has to send what the document declares -- or the second seed
    of a changed corpus would leave the first seed's labels behind.
    """
    directory = tmp_path / "gated"
    directory.mkdir()
    (directory / "gated.yaml").write_text(SCHEMA_FIRST)
    [record async for record in seed_directories(dg, [directory])]

    stored = await dg.schemas.get("seeded-shape")
    assert stored.name == "Seeded shape"
    assert stored.description == "The shape as the corpus first declared it."

    (directory / "gated.yaml").write_text(SCHEMA_RELABELLED)
    [record async for record in seed_directories(dg, [directory])]

    relabelled = await dg.schemas.get("seeded-shape")
    assert relabelled.name == "Renamed shape"
    # The document dropped the description, so the one belonging to the old shape goes with it.
    assert relabelled.description is None


STATION_SCHEMA = """{
  "$id": "https://schemas.test/station-shape.json",
  "title": "Station shape",
  "type": "object"
}
"""

NEEDS_THE_SCHEMA = """
format: dirigent/v1
kind: pipeline
code: seeded-held-to-a-file
description: A document held to a shape a schema file beside it declares.
requires:
  schemas: [station-shape]
steps:
  gate:
    block: validate.schema
    config:
      input: {}
      schema: station-shape
"""

NEEDS_A_LATER_ONE = """
format: dirigent/v1
kind: pipeline
code: seeded-runs-another
description: A document that names a pipeline a document after it in the corpus supplies.
requires:
  pipelines: [seeded-supplied-later]
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, first]
"""

SUPPLIED_LATER = """
format: dirigent/v1
kind: pipeline
code: seeded-supplied-later
description: The pipeline an earlier document names.
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, later]
"""


async def test_a_standalone_schema_file_is_stored_before_the_documents_held_to_it(dg: Dirigent, tmp_path: Path) -> None:
    directory = tmp_path / "shaped"
    (directory / "schemas").mkdir(parents=True)
    (directory / "schemas" / "station.json").write_text(STATION_SCHEMA)
    (directory / "a-held.yaml").write_text(NEEDS_THE_SCHEMA)
    stream = await seeded(dg, directory)

    stored = of_kind(stream, "seed.schema")
    assert [(record["schema"], record["origin"].endswith("station.json")) for record in stored] == [
        ("station-shape", True)
    ]
    assert (await dg.schemas.get("station-shape")).name == "Station shape"
    assert [record["pipeline"] for record in of_kind(stream, "seed.applied")] == ["seeded-held-to-a-file"]
    assert of_kind(stream, "seed.done")[0]["schemas"] == ["station-shape"]


async def test_a_file_that_is_neither_a_document_nor_a_schema_is_left_alone(dg: Dirigent, corpus: Path) -> None:
    stream = await seeded(dg, corpus)
    assert of_kind(stream, "seed.schema") == []
    assert not any("notes.yaml" in str(record.get("document", "")) for record in stream)


async def test_a_document_naming_a_later_one_is_applied_once_the_later_one_is_in(dg: Dirigent, tmp_path: Path) -> None:
    directory = tmp_path / "ordered"
    directory.mkdir()
    (directory / "a-first.yaml").write_text(NEEDS_A_LATER_ONE)
    (directory / "b-later.yaml").write_text(SUPPLIED_LATER)
    stream = await seeded(dg, directory)

    assert [record["pipeline"] for record in of_kind(stream, "seed.applied")] == [
        "seeded-supplied-later",
        "seeded-runs-another",
    ]
    assert of_kind(stream, "seed.refused") == []
    assert of_kind(stream, "seed.done")[0]["refused"] == 0


async def test_a_document_that_never_resolves_is_reported_once(dg: Dirigent, corpus: Path) -> None:
    stream = await seeded(dg, corpus)
    refused = of_kind(stream, "seed.refused")
    assert [record["document"].rpartition("/")[2] for record in refused] == ["refused.yaml"]


async def test_the_installed_corpus_brings_its_connection_and_schema_files(dg: Dirigent) -> None:
    stream = [record async for record in seed_installed(dg)]
    closing = of_kind(stream, "seed.done")[-1]
    assert {"orders-topic", "playground", "shop-queue"} <= set(closing["connections"])
    assert {"ou-record", "playground-reading", "station-reading"} <= set(closing["schemas"])
    refused = {record["document"] for record in of_kind(stream, "seed.refused")}
    assert not any(
        "no schema coded 'station-reading'" in str(record["reason"]) for record in of_kind(stream, "seed.refused")
    )
    assert all(origin.startswith("examples:") for origin in refused)
