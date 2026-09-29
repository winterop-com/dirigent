"""The wording every installed pack refuses in, for a surface that renders its own sentences."""

from fastapi import APIRouter

from dirigent_client.schemas import Labels
from dirigent_server.dependencies import ServicesDep
from dirigent_server.security import PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["labels"])


@router.get("/labels", operation_id="getLabels", summary="Contributed refusal wording", response_model=Labels)
async def get_labels(services: ServicesDep, principal: PrincipalDep) -> Labels:
    """Serve every code an installed pack can refuse under, with the template it renders from."""
    return Labels(templates={code: message.text for code, message in services.host.labels.items()})
