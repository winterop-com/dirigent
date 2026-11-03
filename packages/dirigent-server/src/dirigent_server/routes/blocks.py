"""The block catalog every installed plugin contributes to."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from dirigent_client.schemas import BlockEntry, BlockKind, Catalog, ConnectionKindEntry
from dirigent_server.dependencies import ServicesDep
from dirigent_server.errors import Refusal
from dirigent_server.messages import NO_BLOCK, UNKNOWN_CONNECTION_KIND
from dirigent_server.security import PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["blocks"])


@router.get("/blocks", operation_id="getCatalog", summary="The block catalog", response_model=Catalog)
async def get_catalog(
    services: ServicesDep,
    principal: PrincipalDep,
    kind: Annotated[BlockKind | None, Query(description="Return only operators, or only sensors.")] = None,
) -> Catalog:
    """Serve every contributed operator, sensor, storage scheme, notifier, and connection kind."""
    catalog = services.host.catalog()
    if kind is None:
        return catalog
    return catalog.model_copy(update={"blocks": [block for block in catalog.blocks if block.kind is kind]})


@router.get(
    "/blocks/{block_id}",
    operation_id="getBlock",
    summary="One block's schemas",
    response_model=BlockEntry,
)
async def get_block(block_id: str, services: ServicesDep, principal: PrincipalDep) -> BlockEntry:
    """Serve one catalog entry."""
    entry = services.host.catalog().block(block_id)
    if entry is None:
        raise Refusal(NO_BLOCK, status=status.HTTP_404_NOT_FOUND, block_id=repr(block_id))
    return entry


@router.get(
    "/connection-kinds",
    operation_id="listConnectionKinds",
    summary="Every connection kind and its fields",
    response_model=list[ConnectionKindEntry],
)
async def list_connection_kinds(services: ServicesDep, principal: PrincipalDep) -> list[ConnectionKindEntry]:
    """Serve every installed connection kind with its fields, secret and required marked, and its credential forms."""
    return [ConnectionKindEntry.of(entry) for entry in services.host.catalog().connection_kinds]


@router.get(
    "/connection-kinds/{kind_id}",
    operation_id="getConnectionKind",
    summary="One connection kind and its fields",
    response_model=ConnectionKindEntry,
)
async def get_connection_kind(kind_id: str, services: ServicesDep, principal: PrincipalDep) -> ConnectionKindEntry:
    """Serve one connection kind with its fields."""
    kinds = services.host.catalog().connection_kinds
    for entry in kinds:
        if entry.id == kind_id:
            return ConnectionKindEntry.of(entry)
    raise Refusal(
        UNKNOWN_CONNECTION_KIND,
        status=status.HTTP_404_NOT_FOUND,
        kind=repr(kind_id),
        known=", ".join(entry.id for entry in kinds) or "none",
    )
