"""The worker registry: who is alive, on what version, with which plugins and tags."""

import sqlalchemy as sa
from fastapi import APIRouter

from dirigent_client.enums import WorkerStatus
from dirigent_client.schemas import Page, WorkerOut
from dirigent_core.models import Worker, utcnow
from dirigent_core.registry import STALE_AFTER
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip
from dirigent_server.security import PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["workers"])


@router.get("/workers", operation_id="listWorkers", summary="List workers", response_model=Page[WorkerOut])
async def list_workers(
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[WorkerOut]:
    """List the worker registry, flagging anything stale or running different code."""
    digest = services.host.catalog().digest
    cutoff = utcnow() - STALE_AFTER
    statement = sa.select(Worker).order_by(Worker.name).limit(limit + 1)
    if after is not None:
        statement = statement.where(Worker.name > after)
    rows = await session.execute(statement)
    found = [
        WorkerOut(
            id=row.id,
            name=row.name,
            hostname=row.hostname,
            version=row.version,
            status=row.status,
            concurrency=row.concurrency,
            tags=list(row.tags),
            plugins=dict(row.plugins),
            catalog_digest=row.catalog_digest,
            code_matches_server=row.catalog_digest == digest,
            stale=row.last_seen_at < cutoff and row.status is not WorkerStatus.STOPPED,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
        )
        for row in rows.scalars()
    ]
    items, following = clip(found, limit, lambda row: row.name)
    return Page(items=items, next=following)
