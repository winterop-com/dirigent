"""A pipeline's persisted triggers: its schedules and its watches."""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import LogLevel
from dirigent_client.schemas import (
    FiringOut,
    Page,
    ScheduleIn,
    ScheduleOut,
    SchedulePreview,
    SchedulePreviewRequest,
    WatchOut,
)
from dirigent_common.durations import format_duration
from dirigent_core.engine.definition import load_definition
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import (
    Pipeline,
    Schedule,
    ScheduleFiring,
    TriggerDocument,
    Watch,
)
from dirigent_core.pipelines import get_version, require_pipeline
from dirigent_core.triggers import (
    ScheduleRequest,
    UnknownSchedule,
    UnknownWatch,
    check_schedule_params,
    create_schedule,
    delete_schedule,
    find_schedule,
    find_watch,
    list_firings,
    list_schedules,
    list_watches,
    preview_firings,
    set_paused,
    set_watch_paused,
    update_schedule,
)
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, int_cursor
from dirigent_server.security import OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional, retried_on_deadlock

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


async def owning_documents(session: AsyncSession, rows: Sequence[Schedule | Watch]) -> dict[UUID, str]:
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


def render_watch(row: Watch, documents: Mapping[UUID, str] = MappingProxyType({})) -> WatchOut:
    """Render a watch row: what it waits on, where it left off, and how its waits are going."""
    return WatchOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        step=row.step,
        params=dict(row.params),
        paused=row.paused,
        managed=row.managed,
        trigger_document=documents.get(row.trigger_document_id) if row.trigger_document_id else None,
        cursor=dict(row.cursor) if row.cursor is not None else None,
        waiting_run_id=row.waiting_run_id,
        failures=row.failures,
        last_error=row.last_error,
        last_error_at=row.last_error_at,
        rearm_at=row.rearm_at,
        last_armed_at=row.last_armed_at,
        created_at=row.created_at,
    )


async def _schedule_out(session: AsyncSession, row: Schedule) -> ScheduleOut:
    """Render one schedule, with the code of whichever triggers document owns it."""
    return render_schedule(row, await owning_documents(session, [row]))


@router.post(
    "/schedules/$preview",
    operation_id="previewSchedule",
    summary="Read back what a clock would fire",
    response_model=SchedulePreview,
)
async def preview_schedule(payload: SchedulePreviewRequest, principal: PrincipalDep) -> SchedulePreview:
    """Compute the next firings of a clock nothing has declared, with the scheduler's own arithmetic."""
    return SchedulePreview(
        firings=preview_firings(
            cron=payload.cron,
            interval=payload.interval,
            at=payload.at,
            timezone=payload.timezone,
        )
    )


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
    await _check_pins(session, services, pipeline.id, payload)
    return await _schedule_out(session, await create_schedule(session, pipeline, _schedule_request(payload)))


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
    await _check_pins(session, services, row.pipeline_id, payload)
    return await _schedule_out(session, await update_schedule(session, row, _schedule_request(payload)))


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
    "/pipelines/{code}/triggers/watches",
    operation_id="listWatches",
    summary="List a pipeline's watches",
    response_model=Page[WatchOut],
)
async def watches(
    code: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[WatchOut]:
    """List every watch on a pipeline, with the run each one has waiting."""
    pipeline = await _require(session, code)
    rows = await list_watches(session, pipeline.id, after=after, limit=limit + 1)
    documents = await owning_documents(session, rows)
    items, following = clip([render_watch(row, documents) for row in rows], limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.get(
    "/pipelines/{code}/triggers/watches/{watch}",
    operation_id="getWatch",
    summary="Read one watch",
    response_model=WatchOut,
)
async def get_watch(code: str, watch: str, session: SessionDep, principal: PrincipalDep) -> WatchOut:
    """Read one watch by code."""
    return await _watch_out(session, await _require_watch(session, code, watch))


@router.post(
    "/pipelines/{code}/triggers/watches/{watch}/$pause",
    operation_id="pauseWatch",
    summary="Pause a watch",
    response_model=WatchOut,
)
async def pause_watch(
    code: str, watch: str, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> WatchOut:
    """Stop a watch, cancelling the run it has waiting, and keep where it left off."""

    async def pause_once() -> WatchOut:
        row = await _require_watch(session, code, watch)
        return await _watch_out(session, await set_watch_paused(session, services, row, paused=True))

    return await retried_on_deadlock(session, pause_once)


@router.post(
    "/pipelines/{code}/triggers/watches/{watch}/$resume",
    operation_id="resumeWatch",
    summary="Resume a watch",
    response_model=WatchOut,
)
async def resume_watch(
    code: str, watch: str, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> WatchOut:
    """Start a watch again, arming a run from where its last success left off."""

    async def resume_once() -> WatchOut:
        row = await _require_watch(session, code, watch)
        return await _watch_out(session, await set_watch_paused(session, services, row, paused=False))

    return await retried_on_deadlock(session, resume_once)


async def _watch_out(session: AsyncSession, row: Watch) -> WatchOut:
    """Render one watch, with the code of whichever triggers document owns it."""
    return render_watch(row, await owning_documents(session, [row]))


async def _check_pins(session: AsyncSession, services: EngineServices, pipeline_id: UUID, payload: ScheduleIn) -> None:
    """Check a schedule's pinned parameters against the definition its firings will run.

    A pipeline with no version yet declares no parameters to check against.
    """
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None or pipeline.current_version is None:
        return
    version = await get_version(session, pipeline)
    check_schedule_params(load_definition(version.document), payload.params, services.format_checker)


async def _require(session: AsyncSession, code: str) -> Pipeline:
    """Read a pipeline by code, which refuses an unknown one as a 404 of its own."""
    return await require_pipeline(session, code)


async def _require_schedule(session: AsyncSession, pipeline_code: str, code: str) -> Schedule:
    """Read one schedule within its pipeline, or say which half was not found."""
    pipeline = await _require(session, pipeline_code)
    schedule = await find_schedule(session, pipeline.id, code)
    if schedule is None:
        raise UnknownSchedule(pipeline_code, code)
    return schedule


async def _require_watch(session: AsyncSession, pipeline_code: str, code: str) -> Watch:
    """Read one watch within its pipeline, or say which half was not found."""
    pipeline = await _require(session, pipeline_code)
    watch = await find_watch(session, pipeline.id, code)
    if watch is None:
        raise UnknownWatch(pipeline_code, code)
    return watch
