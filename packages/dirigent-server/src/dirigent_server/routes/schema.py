"""The machine-readable shape of a document, for anything that edits one."""

from fastapi import APIRouter

from dirigent_common import JsonMap
from dirigent_core.documentschema import document_schema
from dirigent_server.dependencies import ServicesDep
from dirigent_server.security import PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["schema"])


@router.get(
    "/schema/document",
    operation_id="getDocumentSchema",
    summary="The JSON Schema a pipeline document is written against",
    response_model=JsonMap,
)
async def get_document_schema(services: ServicesDep, principal: PrincipalDep) -> JsonMap:
    """Serve ``dirigent/v1`` composed with this instance's block config schemas.

    Each installed block contributes an ``if``/``then`` case on a step, so a config key the
    named block does not take is wrong in an editor for the same reason an apply refuses it.
    An instance with a plugin another instance lacks therefore answers with a different schema.
    """
    return document_schema(services.host.catalog())
