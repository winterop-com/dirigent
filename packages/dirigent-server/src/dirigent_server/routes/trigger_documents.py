"""Triggers documents: the clocks and webhooks one document declares for another's pipeline.

A document is applied through ``POST /pipelines/$apply`` like any other; what is here is
reading the ones the instance holds, and removing one with the rows it owns.
"""

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import Page, TriggerDocumentDetail, TriggerDocumentOut
from dirigent_core.models import Pipeline, TriggerDocument
from dirigent_core.trigger_documents import (
    delete_trigger_document,
    find_trigger_document,
    list_trigger_documents,
    owned_codes,
)
from dirigent_server.dependencies import SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip
from dirigent_server.security import OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["triggers"])


def render(row: TriggerDocument, pipeline: str) -> TriggerDocumentOut:
    """Render a triggers document row beside the code of the pipeline it fires."""
    return TriggerDocumentOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        pipeline=pipeline,
        digest=row.digest,
        provenance_source=row.provenance_source,
        provenance_ref=row.provenance_ref,
        applied_by=row.applied_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/trigger-documents",
    operation_id="listTriggerDocuments",
    summary="List triggers documents",
    response_model=Page[TriggerDocumentOut],
)
async def list_all(
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[TriggerDocumentOut]:
    """List every triggers document, in code order, with the pipeline each one fires."""
    rows = await list_trigger_documents(session, after=after, limit=limit + 1)
    found = [render(row, await _pipeline_code(session, row)) for row in rows]
    items, following = clip(found, limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.get(
    "/trigger-documents/{code}",
    operation_id="getTriggerDocument",
    summary="Read a triggers document",
    response_model=TriggerDocumentDetail,
)
async def get_one(code: str, session: SessionDep, principal: PrincipalDep) -> TriggerDocumentDetail:
    """Read one triggers document, the document itself, and the rows it owns."""
    row = await _require(session, code)
    schedules, webhooks = await owned_codes(session, row.id)
    base = render(row, await _pipeline_code(session, row))
    return TriggerDocumentDetail(
        **base.model_dump(),
        document=dict(row.document),
        schedules=schedules,
        webhooks=webhooks,
    )


@router.delete(
    "/trigger-documents/{code}",
    operation_id="deleteTriggerDocument",
    summary="Delete a triggers document and its rows",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete(code: str, session: SessionDep, principal: OperatorDep) -> Response:
    """Remove a triggers document, and with it every schedule and webhook it declared.

    The pipeline it named is untouched, and so is anything the pipeline's own document or an
    operator declared on it.
    """
    await delete_trigger_document(session, await _require(session, code))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _require(session: AsyncSession, code: str) -> TriggerDocument:
    """Read a triggers document by code, translating "no such thing" into a 404."""
    row = await find_trigger_document(session, code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no triggers document coded {code!r}")
    return row


async def _pipeline_code(session: AsyncSession, row: TriggerDocument) -> str:
    """Name the pipeline a triggers document fires; the cascade guarantees it is there."""
    found = await session.execute(sa.select(Pipeline.code).where(Pipeline.id == row.pipeline_id))
    return str(found.scalar_one())
