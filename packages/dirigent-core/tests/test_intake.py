"""What a source's intake checks again once a call's body has arrived."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_core.auth import hash_token
from dirigent_core.database import session_scope
from dirigent_core.documents import load_pipeline_text
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.models import Run, Source
from dirigent_core.pipelines import apply_document
from dirigent_core.sources.intake import Call, Intake
from dirigent_plugin.sources import Refusal

ENDPOINT = """
format: dirigent/v1
kind: pipeline
code: guarded
steps:
  ask:
    source:
      kind: endpoint
      path: /guarded
"""


async def test_a_token_rotated_while_the_body_arrives_refuses_the_call(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    definition = load_pipeline_text(ENDPOINT)
    assert isinstance(definition, PipelineDefinition)
    async with session_scope(sessions) as session:
        await apply_document(session, services, definition)
        row = (await session.execute(sa.select(Source))).scalar_one()
        row.token_hash = hash_token("before")

    async def read(_most: int) -> bytes:
        async with session_scope(sessions) as other:
            rotated = (await other.execute(sa.select(Source))).scalar_one()
            rotated.token_hash = hash_token("after")
        return b"{}"

    call = Call(
        method="POST",
        path="/guarded",
        query=[],
        headers={"authorization": "Bearer before", "content-type": "application/json"},
    )
    async with session_scope(sessions) as session:
        taken = await Intake().take(session, services, call, read)

    assert isinstance(taken, Refusal)
    assert taken.status == 401
    async with sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run))).scalar_one() == 0
