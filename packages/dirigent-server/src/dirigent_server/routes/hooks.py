"""Webhook intake.

Mounted outside ``/api/v1``, which requires a principal as a property of the mount: a
webhook's token *is* its credential, and it authenticates as the trigger, not as a person.
"""

from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status

from dirigent_client.enums import WebhookOutcome
from dirigent_client.schemas import HookAccepted
from dirigent_core.ratelimit import TokenBucket
from dirigent_core.triggers import SIGNATURE_HEADER, deliver, resolve_webhook
from dirigent_core.triggers.webhooks import UNKNOWN_TOKEN, hash_token
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.logging import get_logger
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["hooks"])

#: Per-process, not distributed: behind N API replicas the effective limit is the configured
#: rate times the replica count.
BUCKETS = TokenBucket()

#: Passed *before* anything is looked up, and keyed on the hash of the token that was
#: offered rather than on a token that exists. A limit applied only after the lookup would
#: give a real-but-disabled token a 429 past its rate while an unknown token never got one,
#: telling the holder of a revoked token that it addresses something real.
INTAKE_BUCKETS = TokenBucket()

_logger = get_logger("hooks")


@router.post(
    "/hooks/{token}",
    operation_id="deliverWebhook",
    summary="Deliver a webhook payload",
    response_model=HookAccepted,
    status_code=status.HTTP_201_CREATED,
    responses={
        202: {"description": "Accepted, but the pipeline's concurrency policy started no run."},
        400: {"description": "The body is not a JSON object, or a mapped path is not in it."},
        401: {"description": "A required signature is missing or does not match the body."},
        404: {"description": "No webhook accepts this token; a disabled one answers the same way."},
        409: {"description": "The pipeline cannot accept a run right now."},
        413: {"description": "The body is larger than this instance reads."},
        422: {"description": "The mapped payload does not satisfy the pipeline's parameters."},
        429: {"description": "This token is delivering faster than its rate limit."},
    },
)
async def deliver_hook(
    token: str,
    request: Request,
    response: Response,
    session: SessionDep,
    services: ServicesDep,
    signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
) -> HookAccepted:
    """Verify, map, and enqueue one inbound delivery, and answer with the run it started."""
    offered = hash_token(token)
    intake_limit = services.settings.webhook_intake_rate_per_minute
    if not INTAKE_BUCKETS.allow(offered, per_minute=intake_limit):
        _logger.warning("webhook intake rate limited", prefix=offered[:8], limit=intake_limit)
        return _throttled(response, f"this endpoint accepts {intake_limit} deliveries a minute per token")

    webhook = await resolve_webhook(session, token)
    if webhook is None:
        _logger.warning("webhook token did not resolve", prefix=offered[:8])
        response.status_code = status.HTTP_404_NOT_FOUND
        return HookAccepted(outcome=WebhookOutcome.REJECTED, detail=UNKNOWN_TOKEN)

    # Only a live webhook gets its own limit. A disabled one is answered exactly as an
    # unknown token is, and applying its configured limit here would give it a different 429
    # threshold from an unknown token -- the oracle the matching 404 bodies exist to close.
    if webhook.active and not BUCKETS.allow(webhook.token_hash, per_minute=webhook.rate_limit_per_minute):
        _logger.warning("webhook rate limited", webhook=webhook.name, limit=webhook.rate_limit_per_minute)
        return _throttled(response, f"this webhook accepts {webhook.rate_limit_per_minute} deliveries a minute")

    delivered = await deliver(
        session,
        services,
        webhook,
        body=await _read_body(request, limit=services.settings.webhook_max_payload),
        signature=signature,
        source=request.client.host if request.client else None,
    )
    response.status_code = delivered.status
    return HookAccepted(run_id=delivered.run_id, outcome=delivered.outcome, detail=delivered.reason)


def _throttled(response: Response, detail: str) -> HookAccepted:
    """Answer a throttled caller identically wherever the refusal came from."""
    response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
    response.headers["Retry-After"] = "60"
    return HookAccepted(outcome=WebhookOutcome.REJECTED, detail=detail)


async def _read_body(request: Request, *, limit: int) -> bytes:
    """Read the body, stopping one byte past the limit rather than after all of it.

    ``request.body()`` buffers whatever arrives before the size can be checked, so an
    unauthenticated caller could make the process allocate a gigabyte to be told a megabyte
    is the maximum. What comes back goes to the ordinary refusal path, so an oversized
    delivery is still recorded in the history.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            break
    return b"".join(chunks)
