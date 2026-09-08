"""The block catalog every installed plugin contributes to."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from dirigent_client.schemas import BlockEntry, BlockKind, Catalog
from dirigent_server.dependencies import ServicesDep
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no block {block_id!r} is installed")
    return entry
