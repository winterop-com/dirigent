"""Endpoint intake: the routes a pipeline's endpoint sources declare, under the instance's endpoint prefix.

Mounted outside ``/api/v1``, which requires a principal as a property of the mount: a call to
an endpoint authenticates with the token its source was given, or with nothing for a source
that writes out ``public``.
"""

import time
from datetime import timedelta
from typing import cast

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import InputOutcome
from dirigent_client.schemas import InputAccepted
from dirigent_common.durations import format_duration
from dirigent_core.engine.replies import BODYLESS, encode_body
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import REPLY_FAILED, REPLY_REJECTED, REPLY_TIMED_OUT, REPLY_UNANSWERED
from dirigent_core.sources.intake import Accepted, Call, Ignore, Intake, Refusal, lowered, settle_input
from dirigent_core.sources.waiter import Answer, Replied, TimedOut, Unanswered, Waiter
from dirigent_server.bodies import read_capped
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.errors import answer, render
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["endpoints"])

#: The methods a received source may declare, which is every method this route takes.
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


#: Every answer an endpoint gives, in the order its checks are made.
RESPONSES: dict[int | str, dict[str, object]] = {
    200: {"description": "A reply of the run answered; its status, headers and body are the pipeline's."},
    202: {"description": "The input became a run no reply answers; the body says where to read it."},
    204: {"description": "The input was a sign of life, such as a handshake, and started no run."},
    400: {"description": "The body is not what its content type says."},
    401: {"description": "The source takes a bearer token, and the one presented is not its own."},
    404: {"description": "No source answers this path."},
    405: {"description": "A source answers this path, but not with this method."},
    409: {"description": "The pipeline's concurrency policy, or the run itself, refused the input."},
    413: {"description": "The body is larger than the source reads."},
    415: {"description": "The source does not take this content type."},
    422: {"description": "A step on the way to the reply refused the input, so no reply answered."},
    429: {"description": "The instance or the source is taking calls faster than its rate."},
    502: {"description": "The run failed, or settled, before any reply answered."},
    503: {
        "description": (
            "The source or its pipeline is paused, as many of its runs are in flight as it allows, "
            "or this server holds as many callers as it may."
        )
    },
    504: {"description": "No reply answered within the caller's timeout; the run carries on."},
}


def intake_of(request: Request) -> Intake:
    """Return this process's intake: its routes as last read, and its buckets."""
    intake: Intake = request.app.state.intake
    return intake


def waiter_of(request: Request) -> Waiter:
    """Return this process's reply waiter, which holds every caller a reply may answer."""
    waiter: Waiter = request.app.state.waiter
    return waiter


async def call_endpoint(path: str, request: Request, session: SessionDep, services: ServicesDep) -> Response:
    """Turn one call into a run of the pipeline whose source answers it, answered with its reply or the run."""
    call = Call(
        method=request.method,
        path=f"/{path}",
        query=request.query_params.multi_items(),
        headers=lowered(request.headers.items()),
        caller=request.client.host if request.client else None,
    )
    waiter = waiter_of(request)
    taken = await intake_of(request).take(
        session, services, call, lambda limit: read_capped(request, limit), waiter=waiter
    )
    if isinstance(taken, Ignore):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if isinstance(taken, Refusal):
        return _refused(request, taken)
    if taken.hold is None:
        return _accepted(taken.accepted)
    return await _held(request, session, services, waiter, taken)


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


def _accepted(accepted: InputAccepted) -> Response:
    """Answer an input no reply answers with the run it started and where to read it."""
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=accepted.model_dump(mode="json"),
        headers={"Location": accepted.run_url},
    )


async def _held(
    request: Request, session: AsyncSession, services: EngineServices, waiter: Waiter, taken: Accepted
) -> Response:
    """Commit the run, hold the caller for its answer, and journal what the caller was answered with."""
    hold = taken.hold
    assert hold is not None  # only a held input reaches here
    started = time.monotonic()
    try:
        await session.commit()
    except BaseException:
        waiter.release(hold.source_id)
        raise
    answered = await waiter.wait(hold)
    response = await _answer(request, session, services, taken.accepted, answered, hold.timeout)
    outcome = InputOutcome.TIMED_OUT if isinstance(answered, TimedOut) else InputOutcome.REPLIED
    await settle_input(session, taken.input_id, outcome, response.status_code, started)
    return response


async def _answer(
    request: Request,
    session: AsyncSession,
    services: EngineServices,
    accepted: InputAccepted,
    answered: Answer,
    timeout: float,
) -> Response:
    """Render what a held caller is answered with: the reply, or the run's failure as a problem."""
    run = str(accepted.run_id)
    where = {"Location": accepted.run_url}
    if isinstance(answered, Replied):
        return await _replied(session, services, answered)
    if isinstance(answered, TimedOut):
        waited = format_duration(timedelta(seconds=timeout))
        return _problem(
            request,
            504,
            REPLY_TIMED_OUT.code,
            REPLY_TIMED_OUT.render(run=run, timeout=waited),
            where,
            run=run,
            timeout=waited,
        )
    return _unanswered(request, answered, run, where)


def _unanswered(request: Request, answered: Unanswered, run: str, where: dict[str, str]) -> Response:
    """Map a run no reply can answer any more: a refused input is 422, anything else 502."""
    if answered.step is None:
        state = answered.run_status.value if answered.run_status is not None else "gone"
        return _problem(
            request,
            502,
            REPLY_UNANSWERED.code,
            REPLY_UNANSWERED.render(run=run, status=state),
            where,
            run=run,
            status=state,
        )
    detail = answered.error or "no error was recorded"
    message = REPLY_REJECTED if answered.refused else REPLY_FAILED
    code = 422 if message is REPLY_REJECTED else 502
    rendered = message.render(run=run, step=repr(answered.step), detail=detail)
    return _problem(request, code, message.code, rendered, where, run=run, step=repr(answered.step), detail=detail)


async def _replied(session: AsyncSession, services: EngineServices, replied: Replied) -> Response:
    """Answer with what a reply rendered, streaming ``body_from`` out of storage."""
    rendered = replied.rendered
    code = int(rendered.get("status") or 200)  # pyright: ignore[reportArgumentType] - the reply rendered a whole number
    given = rendered.get("headers")
    headers = (
        {name: str(value) for name, value in cast("dict[str, object]", given).items()}
        if isinstance(given, dict)
        else {}
    )
    content_type = str(rendered.get("content_type") or "application/json")
    uri = rendered.get("body_from")
    if isinstance(uri, str) and code not in BODYLESS:
        storage = await services.bound_storage(session)
        size = rendered.get("body_bytes")
        if isinstance(size, int):
            headers["content-length"] = str(size)
        return StreamingResponse(storage.open_read(uri), status_code=code, media_type=content_type, headers=headers)
    if code in BODYLESS:
        return Response(status_code=code, headers=headers)
    return Response(
        content=encode_body(rendered.get("body"), content_type),
        status_code=code,
        media_type=content_type,
        headers=headers,
    )


def _problem(
    request: Request, code: int, message_code: str, said: str, headers: dict[str, str], **params: str
) -> Response:
    """Answer a held caller in the one problem shape, naming the run it started."""
    response = answer(render(code, said, code=message_code, params=dict(params), instance=request.url.path))
    response.headers.update(headers)
    return response


def _refused(request: Request, refusal: Refusal) -> Response:
    """Answer a refusal in the one problem shape, with any header it has to set."""
    problem = render(
        refusal.status, refusal.message, code=refusal.code, params=refusal.params, instance=request.url.path
    )
    response = answer(problem)
    response.headers.update(refusal.headers)
    return response
