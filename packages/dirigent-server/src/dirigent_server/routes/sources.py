"""A pipeline's sources: what each listens to, its state, what has arrived, and what an operator does to it.

The instance keeps only the hash of a source's token, and a signing secret sealed with its own
key, so either is readable exactly once: when an apply mints it, or when it is rotated.
"""

from collections.abc import Sequence

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import Page, SetSecretRequest, SourceInputOut, SourceOut, SourceTokenOut
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Pipeline, Source
from dirigent_core.pipelines import require_pipeline
from dirigent_core.sources.rows import (
    in_flight,
    input_out,
    list_inputs,
    list_sources,
    require_source,
    rotate_source_token,
    set_paused,
    set_signing_secret,
    source_out,
)
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, int_cursor, uuid_cursor
from dirigent_server.security import OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["sources"])


@router.get("/sources", operation_id="listSources", summary="List every source", response_model=Page[SourceOut])
async def list_all(
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[SourceOut]:
    """List every pipeline's sources, with their state and what they have taken, never their tokens."""
    rows = await list_sources(session, after=uuid_cursor(after), limit=limit + 1)
    return await _page(session, services, rows, limit)


@router.get(
    "/pipelines/{code}/sources",
    operation_id="listPipelineSources",
    summary="List a pipeline's sources",
    response_model=Page[SourceOut],
)
async def list_of_pipeline(
    code: str,
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[SourceOut]:
    """List one pipeline's sources, with their state and what they have taken, never their tokens."""
    pipeline = await require_pipeline(session, code)
    rows = await list_sources(session, pipeline_id=pipeline.id, after=uuid_cursor(after), limit=limit + 1)
    return await _page(session, services, rows, limit)


@router.get(
    "/pipelines/{code}/sources/{source}",
    operation_id="getSource",
    summary="Read one source",
    response_model=SourceOut,
)
async def get_source(
    code: str, source: str, session: SessionDep, services: ServicesDep, principal: PrincipalDep
) -> SourceOut:
    """Read one source by its step code, never its token."""
    pipeline = await require_pipeline(session, code)
    row = await require_source(session, pipeline, source)
    return await _one(session, services, row, pipeline)


@router.post(
    "/pipelines/{code}/sources/{source}/$pause",
    operation_id="pauseSource",
    summary="Pause a source",
    response_model=SourceOut,
)
async def pause(
    code: str, source: str, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> SourceOut:
    """Refuse new inputs with 503, keeping the token and the counts; runs in flight carry on."""
    pipeline = await require_pipeline(session, code)
    row = await set_paused(session, pipeline, await require_source(session, pipeline, source), paused=True)
    return await _one(session, services, row, pipeline)


@router.post(
    "/pipelines/{code}/sources/{source}/$resume",
    operation_id="resumeSource",
    summary="Resume a source",
    response_model=SourceOut,
)
async def resume(
    code: str, source: str, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> SourceOut:
    """Take inputs again on the token that was already issued."""
    pipeline = await require_pipeline(session, code)
    row = await set_paused(session, pipeline, await require_source(session, pipeline, source), paused=False)
    return await _one(session, services, row, pipeline)


@router.post(
    "/pipelines/{code}/sources/{source}/$rotate-token",
    operation_id="rotateSourceToken",
    summary="Rotate a source's token or signing secret",
    response_model=SourceTokenOut,
)
async def rotate(
    code: str, source: str, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> SourceTokenOut:
    """Mint a new token or signing secret and forget the old one immediately; every caller has to be given it."""
    pipeline = await require_pipeline(session, code)
    row = await require_source(session, pipeline, source)
    return await rotate_source_token(session, services.settings, services.sources, services.secrets, pipeline, row)


@router.post(
    "/pipelines/{code}/sources/{source}/$set-secret",
    operation_id="setSourceSecret",
    summary="Set a signed source's signing secret",
    response_model=SourceOut,
)
async def set_secret(
    code: str,
    source: str,
    payload: SetSecretRequest,
    session: SessionDep,
    services: ServicesDep,
    principal: OperatorDep,
) -> SourceOut:
    """Replace an ``hmac`` source's signing secret with one its sender issued, such as a provider's own."""
    pipeline = await require_pipeline(session, code)
    row = await require_source(session, pipeline, source)
    secret = payload.secret.get_secret_value()
    await set_signing_secret(session, services.sources, services.secrets, pipeline, row, secret)
    return await _one(session, services, row, pipeline)


@router.get(
    "/pipelines/{code}/sources/{source}/inputs",
    operation_id="listSourceInputs",
    summary="List a source's inputs",
    response_model=Page[SourceInputOut],
)
async def inputs(
    code: str,
    source: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[SourceInputOut]:
    """Read what has arrived, newest first, refusals included."""
    pipeline = await require_pipeline(session, code)
    row = await require_source(session, pipeline, source)
    rows = await list_inputs(session, row.id, after=int_cursor(after), limit=limit + 1)
    items, following = clip([input_out(entry) for entry in rows], limit, lambda entry: entry.id)
    return Page(items=items, next=following)


async def _one(session: AsyncSession, services: EngineServices, row: Source, pipeline: Pipeline) -> SourceOut:
    """Render one source with the runs it has unsettled."""
    unsettled = (await in_flight(session, [row.id])).get(row.id, 0)
    return source_out(services.settings, services.sources, row, pipeline, unsettled)


async def _page(
    session: AsyncSession, services: EngineServices, rows: Sequence[tuple[Source, Pipeline]], limit: int
) -> Page[SourceOut]:
    """Render a page of sources, counting what each has unsettled in one query."""
    page, following = clip(list(rows), limit, lambda pair: pair[0].id)
    counts = await in_flight(session, [row.id for row, _ in page])
    items = [
        source_out(services.settings, services.sources, row, pipeline, counts.get(row.id, 0)) for row, pipeline in page
    ]
    return Page(items=items, next=following)
