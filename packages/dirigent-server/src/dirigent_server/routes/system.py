"""What this instance is, and whether everything it depends on is answering."""

import asyncio

import sqlalchemy as sa
from fastapi import APIRouter

from dirigent_client.schemas import ConnectionHealth, SystemInfo
from dirigent_core import __version__
from dirigent_core.models import Connection, Worker, utcnow
from dirigent_core.registry import STALE_AFTER
from dirigent_server.dependencies import ServicesDep, SessionDep, SettingsDep
from dirigent_server.routes.connections import check
from dirigent_server.security import PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["system"])


@router.get(
    "/system/info",
    operation_id="getSystemInfo",
    summary="Describe the instance and check every connection",
    response_model=SystemInfo,
)
async def system_info(
    session: SessionDep,
    services: ServicesDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> SystemInfo:
    """Describe the instance, and fan out over every connection's own health check."""
    catalog = services.host.catalog()
    rows = list((await session.execute(sa.select(Connection).order_by(Connection.code))).scalars())
    reports = await asyncio.gather(*(check(row, services) for row in rows))
    live = await session.execute(
        sa.select(sa.func.count()).select_from(Worker).where(Worker.last_seen_at >= utcnow() - STALE_AFTER)
    )
    return SystemInfo(
        version=__version__,
        environment=settings.environment,
        database="sqlite" if settings.is_sqlite else "postgresql",
        checked_at=utcnow(),
        plugins=catalog.plugins,
        blocks=len(catalog.blocks),
        storage_schemes=services.storage.schemes,
        notifiers=[entry.id for entry in catalog.notifiers],
        connection_kinds=[entry.id for entry in catalog.connection_kinds],
        workers_live=int(live.scalar_one()),
        unsafe_blocks_enabled=list(settings.enabled_unsafe_blocks),
        secrets_configured=services.secrets.available,
        connections=[
            ConnectionHealth(
                code=row.code,
                name=row.name,
                kind=row.kind,
                connected=report.healthy,
                detail=report.detail,
                version=report.version,
            )
            for row, report in zip(rows, reports, strict=True)
        ],
    )
