"""Endpoint intake: the routes a pipeline's endpoint sources declare, under the instance's endpoint prefix.

Mounted outside ``/api/v1``, which requires a principal as a property of the mount: a call to
an endpoint authenticates with the token its source was given, or with nothing for a source
that writes out ``public``.
"""

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from dirigent_client.schemas import InputAccepted
from dirigent_core.sources.intake import Call, Ignore, Intake, Refusal, lowered
from dirigent_server.bodies import read_capped
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.errors import answer, render
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["endpoints"])

#: The methods a received source may declare, which is every method this route takes.
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


#: Every answer an endpoint gives, in the order its checks are made.
RESPONSES: dict[int | str, dict[str, object]] = {
    202: {"description": "The input became a run; the body says where to read it."},
    204: {"description": "The input was a sign of life, such as a handshake, and started no run."},
    400: {"description": "The body is not what its content type says."},
    401: {"description": "The source takes a bearer token, and the one presented is not its own."},
    404: {"description": "No source answers this path."},
    405: {"description": "A source answers this path, but not with this method."},
    409: {"description": "The pipeline's concurrency policy, or the run itself, refused the input."},
    413: {"description": "The body is larger than the source reads."},
    415: {"description": "The source does not take this content type."},
    429: {"description": "The instance or the source is taking calls faster than its rate."},
    503: {"description": "The source or its pipeline is paused, or as many of its runs are in flight as it allows."},
}


def intake_of(request: Request) -> Intake:
    """Return this process's intake: its routes as last read, and its buckets."""
    intake: Intake = request.app.state.intake
    return intake


async def call_endpoint(path: str, request: Request, session: SessionDep, services: ServicesDep) -> Response:
    """Turn one call into a run of the pipeline whose source answers it, or refuse it with why."""
    call = Call(
        method=request.method,
        path=f"/{path}",
        query=request.query_params.multi_items(),
        headers=lowered(request.headers.items()),
        caller=request.client.host if request.client else None,
    )
    taken = await intake_of(request).take(session, services, call, lambda limit: read_capped(request, limit))
    if isinstance(taken, Ignore):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if isinstance(taken, Refusal):
        return _refused(request, taken)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=taken.model_dump(mode="json"),
        headers={"Location": taken.run_url},
    )


for _method in METHODS:
    router.add_api_route(
        "/{path:path}",
        call_endpoint,
        methods=[_method],
        operation_id=f"callEndpoint{_method.title()}",
        summary=f"Call an endpoint source with {_method}",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=InputAccepted,
        responses=RESPONSES,
    )


def _refused(request: Request, refusal: Refusal) -> Response:
    """Answer a refusal in the one problem shape, with any header it has to set."""
    problem = render(
        refusal.status, refusal.message, code=refusal.code, params=refusal.params, instance=request.url.path
    )
    response = answer(problem)
    response.headers.update(refusal.headers)
    return response
