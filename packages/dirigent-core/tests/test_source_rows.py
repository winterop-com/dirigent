"""The source rows an apply reconciles, the routes a server answers from, and a source's state."""

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import SourceState
from dirigent_core.database import session_scope
from dirigent_core.documents import load_pipeline_text
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.models import Source, SourceRoute
from dirigent_core.pipelines import apply_document, require_pipeline
from dirigent_core.sources import intake as intake_module
from dirigent_core.sources.intake import Intake, Listening, Matched, RouteTable
from dirigent_core.sources.rows import RouteRaced, reconcile_sources, state_of
from dirigent_plugin.sources import Route

ECHO = """
format: dirigent/v1
kind: pipeline
code: {code}
steps:
  ask:
    source:
      kind: endpoint
      path: {path}
  answer:
    depends_on: [ask]
    reply:
      status: 200
"""


def echo(code: str = "echo", path: str = "/echo/{who}") -> PipelineDefinition:
    """Read an echo document answering one path."""
    definition = load_pipeline_text(ECHO.format(code=code, path=path))
    assert isinstance(definition, PipelineDefinition)
    return definition


async def apply(sessions: async_sessionmaker[AsyncSession], services: EngineServices, definition: Any) -> Any:
    """Apply one document in a transaction of its own."""
    async with session_scope(sessions) as session:
        return await apply_document(session, services, definition)


async def routes_of(sessions: async_sessionmaker[AsyncSession]) -> list[tuple[str, str]]:
    """Read every claimed route as a method and the template it is written as."""
    async with sessions() as session:
        rows = await session.execute(sa.select(SourceRoute.method, SourceRoute.template).order_by(SourceRoute.template))
        return [(method, template) for method, template in rows]


def listening(template: str, *methods: str) -> Listening:
    """One source answering one template."""
    return Listening(source_id=uuid4(), route=Route(methods=methods or ("POST",), template=template))


def test_the_most_literal_template_is_matched_first() -> None:
    general = listening("/customers/{id}")
    literal = listening("/customers/new")
    found = RouteTable(listening=[general, literal]).find("POST", "/customers/new")
    assert isinstance(found, Matched)
    assert found.source_id == literal.source_id
    other = RouteTable(listening=[general, literal]).find("POST", "/customers/42")
    assert isinstance(other, Matched)
    assert (other.source_id, other.path_params) == (general.source_id, {"id": "42"})


def test_a_path_answered_with_other_methods_names_every_one_of_them() -> None:
    table = RouteTable(listening=[listening("/a/{x}", "PUT"), listening("/a/b", "POST", "PATCH")])
    assert table.find("GET", "/a/b") == ["PATCH", "POST", "PUT"]
    assert table.find("GET", "/elsewhere") is None


@pytest.mark.parametrize(
    ("paused", "active", "unsettled", "bound", "state"),
    [
        (False, True, 0, None, SourceState.LISTENING),
        (False, True, 3, 4, SourceState.LISTENING),
        (False, True, 4, 4, SourceState.BACKLOGGED),
        (True, True, 0, None, SourceState.PAUSED),
        (True, True, 2, None, SourceState.DRAINING),
        (False, False, 0, 1, SourceState.PAUSED),
        (False, False, 1, 1, SourceState.DRAINING),
    ],
)
def test_a_sources_state_is_read_from_its_row_its_pipeline_and_its_runs(
    paused: bool, active: bool, unsettled: int, bound: int | None, state: SourceState
) -> None:
    row = Source(paused=paused)
    assert state_of(row, pipeline_active=active, unsettled=unsettled, bound=bound) is state


async def test_renaming_a_template_parameter_keeps_the_route_answered(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, echo(path="/echo/{who}"))
    applied = await apply(sessions, services, echo(path="/echo/{name}"))
    assert applied.sources.updated == ["ask"]
    assert await routes_of(sessions) == [("POST", "/echo/{name}")]


async def test_a_paused_apply_inserts_a_received_source_live(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        applied = await apply_document(session, services, echo(), paused=True)
    assert applied.sources.created == ["ask"]
    assert applied.sources.paused == []
    async with sessions() as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
    assert row.paused is False


async def test_a_dry_run_names_a_source_the_document_stopped_declaring_and_keeps_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, echo())
    plain = load_pipeline_text(
        "format: dirigent/v1\nkind: pipeline\ncode: echo\nsteps:\n  one:\n    block: test.echo\n"
        "    config: {value: hi}\n"
    )
    async with session_scope(sessions) as session:
        planned = await apply_document(session, services, plain, dry_run=True)
    assert planned.sources.removed == ["ask"]
    assert await routes_of(sessions) == [("POST", "/echo/{who}")]


async def test_dropping_every_source_retires_its_rows_and_releases_its_routes(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, echo())
    plain = load_pipeline_text(
        "format: dirigent/v1\nkind: pipeline\ncode: echo\nsteps:\n  one:\n    block: test.echo\n"
        "    config: {value: hi}\n"
    )
    applied = await apply(sessions, services, plain)
    assert applied.sources.removed == ["ask"]
    assert await routes_of(sessions) == []
    async with sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Source))).scalar_one() == 0


async def test_a_route_claimed_between_plan_and_write_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, echo(code="first", path="/same"))
    second = echo(code="second", path="/same")
    async with session_scope(sessions) as session:
        await apply_document(session, services, echo(code="second", path="/elsewhere"))
    with pytest.raises(RouteRaced):
        async with session_scope(sessions) as session:
            pipeline = await require_pipeline(session, "second")
            await reconcile_sources(session, services.settings, services.sources, services.secrets, pipeline, second)


async def test_a_server_rereads_its_routes_once_a_source_changes(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[int] = []
    read = intake_module.read_routes

    async def counted(session: AsyncSession) -> RouteTable:
        reads.append(1)
        return await read(session)

    monkeypatch.setattr(intake_module, "read_routes", counted)
    intake = Intake()
    await apply(sessions, services, echo())
    async with sessions() as session:
        first = await intake.routes(session)
        again = await intake.routes(session)
    assert again is first, "nothing changed, so nothing is read again"
    await apply(sessions, services, echo(code="other", path="/other"))
    async with sessions() as session:
        fresh = await intake.routes(session)
    assert sorted(entry.route.template for entry in fresh.listening) == ["/echo/{who}", "/other"]
    assert len(reads) == 2
