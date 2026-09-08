"""A pipeline's persisted triggers: its schedules and its inbound webhooks.

The instance keeps only the hash of a webhook's token, so the token is readable exactly
once: when it is minted or rotated.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import LogLevel
from dirigent_client.schemas import (
    DeliveryOut,
    FiringOut,
    Page,
    ScheduleIn,
    ScheduleOut,
    SchedulePreview,
    SchedulePreviewRequest,
    WebhookIn,
    WebhookOut,
    WebhookTokenOut,
)
from dirigent_common.durations import format_duration
from dirigent_core.engine.definition import load_definition
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import (
    Pipeline,
    Schedule,
    ScheduleFiring,
    TriggerDocument,
    WebhookDelivery,
    WebhookTrigger,
)
from dirigent_core.pipelines import UnknownPipeline, get_version, require_pipeline
from dirigent_core.triggers import (
    DuplicateSchedule,
    ScheduleError,
    ScheduleRequest,
    WebhookError,
    WebhookRequest,
    check_schedule_params,
    check_webhook_mapping,
    create_schedule,
    create_webhook,
    delete_schedule,
    delete_webhook,
    find_schedule,
    find_webhook,
    list_deliveries,
    list_firings,
    list_schedules,
    list_webhooks,
    preview_firings,
    rotate_token,
    set_active,
    set_paused,
    update_schedule,
)
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, int_cursor
from dirigent_server.security import OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["triggers"])


def _schedule_request(payload: ScheduleIn) -> ScheduleRequest:
    """Read a schedule declaration as the request the core schedule service takes."""
    return ScheduleRequest(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        cron=payload.cron,
        interval=payload.interval,
        at=payload.at,
        timezone=payload.timezone,
        params=payload.params,
        connection_pins=payload.connection_pins,
        log_levels={pattern: level.value for pattern, level in payload.log_levels.items()}
        if payload.log_levels
        else None,
        priority=payload.priority,
    )


def _webhook_request(payload: WebhookIn) -> WebhookRequest:
    """Read a webhook declaration as the request the core webhook service takes."""
    return WebhookRequest(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        params_from_payload=payload.params_from_payload,
        hmac_secret=payload.hmac_secret,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        priority=payload.priority,
    )


async def owning_documents(session: AsyncSession, rows: Sequence[Schedule | WebhookTrigger]) -> dict[UUID, str]:
    """Read the code of every triggers document that owns one of these rows."""
    wanted = {row.trigger_document_id for row in rows if row.trigger_document_id is not None}
    if not wanted:
        return {}
    found = await session.execute(
        sa.select(TriggerDocument.id, TriggerDocument.code).where(TriggerDocument.id.in_(wanted))
    )
    return {document_id: code for document_id, code in found.all()}


def render_schedule(row: Schedule, documents: Mapping[UUID, str] = MappingProxyType({})) -> ScheduleOut:
    """Render a schedule row, writing its interval back as the humane duration it was."""
    return ScheduleOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        kind=row.kind,
        cron=row.cron,
        interval=format_duration(timedelta(seconds=row.interval_seconds)) if row.interval_seconds else None,
        at=row.run_at,
        timezone=row.timezone,
        params=dict(row.params),
        log_levels={pattern: LogLevel(str(level)) for pattern, level in row.log_levels.items()}
        if row.log_levels
        else None,
        priority=row.priority,
        paused=row.paused,
        managed=row.managed,
        trigger_document=documents.get(row.trigger_document_id) if row.trigger_document_id else None,
        next_fire_at=row.next_fire_at,
        last_fired_at=row.last_fired_at,
        created_at=row.created_at,
    )


def render_webhook(row: WebhookTrigger, documents: Mapping[UUID, str] = MappingProxyType({})) -> WebhookOut:
    """Render a webhook row, saying whether it is signed rather than how."""
    return WebhookOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        token_prefix=row.token_prefix,
        params_from_payload=dict(row.params_from_payload),
        signed=row.hmac_secret is not None,
        active=row.active,
        managed=row.managed,
        trigger_document=documents.get(row.trigger_document_id) if row.trigger_document_id else None,
        rate_limit_per_minute=row.rate_limit_per_minute,
        priority=row.priority,
        last_delivery_at=row.last_delivery_at,
        created_at=row.created_at,
    )


async def _schedule_out(session: AsyncSession, row: Schedule) -> ScheduleOut:
    """Render one schedule, with the code of whichever triggers document owns it."""
    return render_schedule(row, await owning_documents(session, [row]))


async def _webhook_out(session: AsyncSession, row: WebhookTrigger) -> WebhookOut:
    """Render one webhook, with the code of whichever triggers document owns it."""
    return render_webhook(row, await owning_documents(session, [row]))


@router.post(
    "/schedules/$preview",
    operation_id="previewSchedule",
    summary="Read back what a clock would fire",
    response_model=SchedulePreview,
)
async def preview_schedule(payload: SchedulePreviewRequest, principal: PrincipalDep) -> SchedulePreview:
    """Compute the next firings of a clock nothing has declared, with the scheduler's own arithmetic."""
    try:
        return SchedulePreview(
            firings=preview_firings(
                cron=payload.cron,
                interval=payload.interval,
                at=payload.at,
                timezone=payload.timezone,
            )
        )
    except ScheduleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get(
    "/pipelines/{code}/triggers/schedules",
    operation_id="listSchedules",
    summary="List a pipeline's schedules",
    response_model=Page[ScheduleOut],
)
async def schedules(
    code: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[ScheduleOut]:
    """List every schedule on a pipeline, with when each one next fires."""
    pipeline = await _require(session, code)
    rows = await list_schedules(session, pipeline.id, after=after, limit=limit + 1)
    documents = await owning_documents(session, rows)
    items, following = clip([render_schedule(row, documents) for row in rows], limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.get(
    "/pipelines/{code}/triggers/schedules/{schedule}",
    operation_id="getSchedule",
    summary="Read one schedule",
    response_model=ScheduleOut,
)
async def get_schedule(code: str, schedule: str, session: SessionDep, principal: PrincipalDep) -> ScheduleOut:
    """Read one schedule by code."""
    return await _schedule_out(session, await _require_schedule(session, code, schedule))


@router.post(
    "/pipelines/{code}/triggers/schedules",
    operation_id="createSchedule",
    summary="Declare a schedule",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_schedule(
    code: str, payload: ScheduleIn, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> ScheduleOut:
    """Declare a schedule on a pipeline and compute when it first fires."""
    pipeline = await _require(session, code)
    try:
        await _check_pins(session, services, pipeline.id, payload)
        return await _schedule_out(session, await create_schedule(session, pipeline, _schedule_request(payload)))
    except DuplicateSchedule as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ScheduleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.patch(
    "/pipelines/{code}/triggers/schedules/{schedule}",
    operation_id="updateSchedule",
    summary="Redeclare a schedule",
    response_model=ScheduleOut,
)
async def edit_schedule(
    code: str,
    schedule: str,
    payload: ScheduleIn,
    session: SessionDep,
    services: ServicesDep,
    principal: OperatorDep,
) -> ScheduleOut:
    """Change a schedule's clock or parameters, keeping whether it is paused."""
    row = await _require_schedule(session, code, schedule)
    try:
        await _check_pins(session, services, row.pipeline_id, payload)
        return await _schedule_out(session, await update_schedule(session, row, _schedule_request(payload)))
    except ScheduleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.post(
    "/pipelines/{code}/triggers/schedules/{schedule}/$pause",
    operation_id="pauseSchedule",
    summary="Pause a schedule",
    response_model=ScheduleOut,
)
async def pause(code: str, schedule: str, session: SessionDep, principal: OperatorDep) -> ScheduleOut:
    """Stop a schedule firing, without losing it or its history."""
    row = await _require_schedule(session, code, schedule)
    return await _schedule_out(session, await set_paused(session, row, paused=True))


@router.post(
    "/pipelines/{code}/triggers/schedules/{schedule}/$resume",
    operation_id="resumeSchedule",
    summary="Resume a schedule",
    response_model=ScheduleOut,
)
async def resume(code: str, schedule: str, session: SessionDep, principal: OperatorDep) -> ScheduleOut:
    """Start a schedule firing again, from the next slot rather than from the ones it missed."""
    row = await _require_schedule(session, code, schedule)
    return await _schedule_out(session, await set_paused(session, row, paused=False))


@router.get(
    "/pipelines/{code}/triggers/schedules/{schedule}/firings",
    operation_id="listScheduleFirings",
    summary="List a schedule's firings",
    response_model=Page[FiringOut],
)
async def firings(
    code: str,
    schedule: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[FiringOut]:
    """Read what a schedule has actually done, newest first, including what it skipped."""
    row = await _require_schedule(session, code, schedule)
    rows = await list_firings(session, row.id, after=int_cursor(after), limit=limit + 1)
    items, following = clip([_firing(entry) for entry in rows], limit, lambda entry: entry.id)
    return Page(items=items, next=following)


def _firing(row: ScheduleFiring) -> FiringOut:
    """Render one firing row."""
    return FiringOut(
        id=row.id,
        scheduled_for=row.scheduled_for,
        created_at=row.created_at,
        outcome=row.outcome,
        misfired=row.misfired,
        run_id=row.run_id,
        detail=row.detail,
    )


@router.delete(
    "/pipelines/{code}/triggers/schedules/{schedule}",
    operation_id="deleteSchedule",
    summary="Delete a schedule",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_schedule(code: str, schedule: str, session: SessionDep, principal: OperatorDep) -> Response:
    """Remove a schedule and its firing history."""
    row = await _require_schedule(session, code, schedule)
    await delete_schedule(session, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/pipelines/{code}/triggers/webhooks",
    operation_id="listWebhooks",
    summary="List a pipeline's webhooks",
    response_model=Page[WebhookOut],
)
async def webhooks(
    code: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[WebhookOut]:
    """List every webhook on a pipeline, with its mapping but never its token."""
    pipeline = await _require(session, code)
    rows = await list_webhooks(session, pipeline.id, after=after, limit=limit + 1)
    documents = await owning_documents(session, rows)
    items, following = clip([render_webhook(row, documents) for row in rows], limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.get(
    "/pipelines/{code}/triggers/webhooks/{webhook}",
    operation_id="getWebhook",
    summary="Read one webhook",
    response_model=WebhookOut,
)
async def get_webhook(code: str, webhook: str, session: SessionDep, principal: PrincipalDep) -> WebhookOut:
    """Read one webhook by code, with its mapping but never its token."""
    return await _webhook_out(session, await _require_webhook(session, code, webhook))


@router.post(
    "/pipelines/{code}/triggers/webhooks",
    operation_id="createWebhook",
    summary="Declare a webhook and mint its token",
    response_model=WebhookTokenOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_webhook(
    code: str, payload: WebhookIn, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> WebhookTokenOut:
    """Declare a webhook and return its token, which is shown here and nowhere else again."""
    pipeline = await _require(session, code)
    await _check_mapping(session, pipeline.id, payload)
    try:
        minted = await create_webhook(session, pipeline, _webhook_request(payload), secrets=services.secrets)
    except WebhookError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _token(minted.webhook_id, minted.code, minted.token.get_secret_value(), minted.prefix)


@router.post(
    "/pipelines/{code}/triggers/webhooks/{webhook}/$rotate-token",
    operation_id="rotateWebhookToken",
    summary="Rotate a webhook's token",
    response_model=WebhookTokenOut,
)
async def rotate(code: str, webhook: str, session: SessionDep, principal: OperatorDep) -> WebhookTokenOut:
    """Mint a new token and forget the old one immediately; callers must be updated."""
    row = await _require_webhook(session, code, webhook)
    minted = await rotate_token(session, row)
    return _token(minted.webhook_id, minted.code, minted.token.get_secret_value(), minted.prefix)


def _token(webhook_id: UUID, code: str, token: str, prefix: str) -> WebhookTokenOut:
    """Render a minted token together with the path it is presented at."""
    return WebhookTokenOut(webhook_id=webhook_id, code=code, token=token, prefix=prefix, url_path=f"/hooks/{token}")


@router.post(
    "/pipelines/{code}/triggers/webhooks/{webhook}/$disable",
    operation_id="disableWebhook",
    summary="Disable a webhook",
    response_model=WebhookOut,
)
async def disable(code: str, webhook: str, session: SessionDep, principal: OperatorDep) -> WebhookOut:
    """Refuse deliveries without rotating or losing the token."""
    row = await _require_webhook(session, code, webhook)
    return await _webhook_out(session, await set_active(session, row, active=False))


@router.post(
    "/pipelines/{code}/triggers/webhooks/{webhook}/$enable",
    operation_id="enableWebhook",
    summary="Enable a webhook",
    response_model=WebhookOut,
)
async def enable(code: str, webhook: str, session: SessionDep, principal: OperatorDep) -> WebhookOut:
    """Accept deliveries again on the token that was already issued."""
    row = await _require_webhook(session, code, webhook)
    return await _webhook_out(session, await set_active(session, row, active=True))


@router.get(
    "/pipelines/{code}/triggers/webhooks/{webhook}/deliveries",
    operation_id="listWebhookDeliveries",
    summary="List a webhook's deliveries",
    response_model=Page[DeliveryOut],
)
async def deliveries(
    code: str,
    webhook: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[DeliveryOut]:
    """Read what has arrived, newest first, refusals included."""
    row = await _require_webhook(session, code, webhook)
    rows = await list_deliveries(session, row.id, after=int_cursor(after), limit=limit + 1)
    items, following = clip([_delivery(entry) for entry in rows], limit, lambda entry: entry.id)
    return Page(items=items, next=following)


def _delivery(row: WebhookDelivery) -> DeliveryOut:
    """Render one delivery row."""
    return DeliveryOut(
        id=row.id,
        created_at=row.created_at,
        outcome=row.outcome,
        run_id=row.run_id,
        reason=row.reason,
        mapped_params=row.mapped_params,
        source=row.source,
    )


@router.delete(
    "/pipelines/{code}/triggers/webhooks/{webhook}",
    operation_id="deleteWebhook",
    summary="Delete a webhook",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_webhook(code: str, webhook: str, session: SessionDep, principal: OperatorDep) -> Response:
    """Remove a webhook, its token, and its delivery history."""
    row = await _require_webhook(session, code, webhook)
    await delete_webhook(session, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _check_pins(session: AsyncSession, services: EngineServices, pipeline_id: UUID, payload: ScheduleIn) -> None:
    """Check a schedule's pinned parameters against the definition its firings will run.

    A pipeline with no version yet declares no parameters to check against.
    """
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None or pipeline.current_version is None:
        return
    version = await get_version(session, pipeline)
    check_schedule_params(load_definition(version.document), payload.params, services.format_checker)


async def _check_mapping(session: AsyncSession, pipeline_id: UUID, payload: WebhookIn) -> None:
    """Check a webhook's mapping against the definition its deliveries will run.

    A pipeline with no version yet declares no parameters to check against.
    """
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None or pipeline.current_version is None:
        return
    version = await get_version(session, pipeline)
    try:
        check_webhook_mapping(load_definition(version.document), payload.params_from_payload)
    except WebhookError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


async def _require(session: AsyncSession, code: str) -> Pipeline:
    """Read a pipeline by code, translating "no such thing" into a 404."""
    try:
        return await require_pipeline(session, code)
    except UnknownPipeline as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


async def _require_schedule(session: AsyncSession, pipeline_code: str, code: str) -> Schedule:
    """Read one schedule within its pipeline, or say which half was not found."""
    pipeline = await _require(session, pipeline_code)
    schedule = await find_schedule(session, pipeline.id, code)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline {pipeline_code!r} has no schedule coded {code!r}",
        )
    return schedule


async def _require_webhook(session: AsyncSession, pipeline_code: str, code: str) -> WebhookTrigger:
    """Read one webhook within its pipeline, or say which half was not found."""
    pipeline = await _require(session, pipeline_code)
    webhook = await find_webhook(session, pipeline.id, code)
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline {pipeline_code!r} has no webhook coded {code!r}",
        )
    return webhook
