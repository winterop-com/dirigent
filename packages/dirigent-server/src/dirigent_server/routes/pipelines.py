"""Pipelines: apply, export, versions, activation, deletion, the ad hoc run, and backfill."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import (
    ApplyRequest,
    ApplyResult,
    BackfillAccepted,
    BackfilledRun,
    BackfillRequest,
    LastRun,
    Page,
    PipelineDetail,
    PipelineOut,
    PipelineVersionOut,
    PruneRequest,
    PruneResult,
    RunAccepted,
    RunRequest,
    ValidationIssue,
)
from dirigent_core.directory import prune_absent
from dirigent_core.documents import DocumentError, carried_refusal, load_document
from dirigent_core.engine import Attribution, ParameterError, create_run
from dirigent_core.engine.definition import load_definition
from dirigent_core.engine.runs import Provenance, RunCreationError, RunWindow
from dirigent_core.models import Pipeline
from dirigent_core.pipelines import (
    NO_COUNTS,
    PipelineCounts,
    PipelineError,
    PipelineInUse,
    UnknownPipeline,
    apply_document,
    delete_pipeline,
    export_pipeline,
    get_version,
    last_runs,
    list_pipelines,
    list_versions,
    listing_counts,
    require_pipeline,
    revalidate,
    set_active,
)
from dirigent_core.triggers.backfill import BackfillError, backfill
from dirigent_core.triggers.schedules import find_schedule
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, int_cursor
from dirigent_server.security import AdminDep, OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["pipelines"])


def render(row: Pipeline, counts: PipelineCounts = NO_COUNTS, last: LastRun | None = None) -> PipelineOut:
    """Render a pipeline row with the counts and the last run a listing draws beside it."""
    return PipelineOut.model_validate(row, from_attributes=True).model_copy(
        update={
            "active_runs": counts.active_runs,
            "schedules": counts.schedules,
            "webhooks": counts.webhooks,
            "last_run": last,
        }
    )


@router.get(
    "/pipelines",
    operation_id="listPipelines",
    summary="List pipelines",
    response_model=Page[PipelineOut],
)
async def list_all(
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
    tag: Annotated[
        list[str] | None, Query(description="Only pipelines wearing this tag; repeat it to name more.")
    ] = None,
) -> Page[PipelineOut]:
    """List every pipeline, what fires it, how many runs are in flight, and how the last one went.

    ``tag`` repeats, and repeating it narrows: a pipeline is listed only if it wears every
    tag named.
    """
    rows = await list_pipelines(session, after=after, limit=limit + 1, tags=tag or ())
    page, following = clip(rows, limit, lambda row: row.code)
    ids = [row.id for row in page]
    counts = await listing_counts(session, ids)
    latest = await last_runs(session, ids)
    found = [render(row, counts.get(row.id, NO_COUNTS), latest.get(row.id)) for row in page]
    return Page(items=found, next=following)


@router.post(
    "/pipelines/$apply",
    operation_id="applyPipeline",
    summary="Apply a pipeline document",
    response_model=ApplyResult,
)
async def apply(
    payload: ApplyRequest,
    session: SessionDep,
    services: ServicesDep,
    principal: OperatorDep,
    dry_run: Annotated[bool, Query(description="Report the plan without writing anything.")] = False,
) -> ApplyResult:
    """Validate a document against this instance and commit a new version, or plan one.

    ``pause_schedules`` on the request creates this apply's new schedules paused; one the
    instance already holds keeps the paused state it has.
    """
    raw = dict(payload.document)
    if payload.code is not None:
        raw["code"] = payload.code
    try:
        definition = load_document(raw)
    except DocumentError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.problems) from error
    refusal = carried_refusal(definition)
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=[refusal])
    return await apply_document(
        session,
        services,
        definition,
        provenance=Provenance(source=payload.source, ref=payload.source_ref, applied_by=principal.label),
        dry_run=dry_run,
        pause_schedules=payload.pause_schedules,
    )


@router.post(
    "/pipelines/$prune",
    operation_id="prunePipelines",
    summary="Deactivate directory pipelines absent from a set",
    response_model=PruneResult,
)
async def prune(
    payload: PruneRequest,
    session: SessionDep,
    principal: OperatorDep,
    dry_run: Annotated[bool, Query(description="Report what would be deactivated without writing.")] = False,
) -> PruneResult:
    """The reconcile half of a directory apply.

    Every active pipeline whose current version a directory apply wrote, and whose code is
    not in ``keep``, is deactivated -- never deleted. A directory-provenance triggers document
    absent from ``keep`` is deleted instead, and takes the rows it owned with it. An empty
    ``keep`` is refused outside a dry run: an empty directory is an accident, not an
    instruction to turn everything off.
    """
    if not payload.keep and not dry_run:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=["keep names no codes, and pruning against an empty set would deactivate every directory pipeline"],
        )
    return await prune_absent(session, set(payload.keep), dry_run=dry_run)


@router.get(
    "/pipelines/{code}",
    operation_id="getPipeline",
    summary="Read a pipeline",
    response_model=PipelineDetail,
)
async def get_one(code: str, session: SessionDep, principal: PrincipalDep) -> PipelineDetail:
    """Read a pipeline and the document its current version holds."""
    pipeline = await _require(session, code)
    document = None
    if pipeline.current_version is not None:
        document = (await get_version(session, pipeline)).ordered_document
    counts = await listing_counts(session, [pipeline.id])
    latest = await last_runs(session, [pipeline.id])
    base = render(pipeline, counts.get(pipeline.id, NO_COUNTS), latest.get(pipeline.id))
    return PipelineDetail(**base.model_dump(), document=document)


@router.get(
    "/pipelines/{code}/versions",
    operation_id="listPipelineVersions",
    summary="List a pipeline's versions",
    response_model=Page[PipelineVersionOut],
)
async def versions(
    code: str,
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[PipelineVersionOut]:
    """List every immutable version, newest first, with its provenance."""
    pipeline = await _require(session, code)
    rows = await list_versions(session, pipeline.id, after=int_cursor(after), limit=limit + 1)
    found = [PipelineVersionOut.model_validate(row, from_attributes=True) for row in rows]
    items, following = clip(found, limit, lambda row: row.version)
    return Page(items=items, next=following)


@router.get(
    "/pipelines/{code}/$export",
    operation_id="exportPipeline",
    summary="Export a pipeline as canonical YAML",
    response_class=PlainTextResponse,
    responses={200: {"content": {"application/yaml": {}}, "description": "The canonical document."}},
)
async def export(
    code: str,
    session: SessionDep,
    principal: PrincipalDep,
    version: Annotated[int | None, Query(description="Export this version instead of the current one.")] = None,
) -> PlainTextResponse:
    """Render a stored pipeline as the canonical YAML a git repository holds."""
    try:
        text = await export_pipeline(session, code, version=version)
    except PipelineError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return PlainTextResponse(text, media_type="application/yaml")


@router.post(
    "/pipelines/{code}/$validate",
    operation_id="validatePipeline",
    summary="Re-check a stored pipeline against this instance",
    response_model=list[ValidationIssue],
)
async def validate_stored(
    code: str,
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    version: Annotated[int | None, Query(description="Check this version instead of the current one.")] = None,
) -> list[ValidationIssue]:
    """Report what a stored version would fail on if it ran now, or an empty list."""
    try:
        return await revalidate(session, services, code, version=version)
    except PipelineError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post(
    "/pipelines/{code}/$activate",
    operation_id="activatePipeline",
    summary="Activate a pipeline",
    response_model=PipelineOut,
)
async def activate(code: str, session: SessionDep, principal: OperatorDep) -> PipelineOut:
    """Make a pipeline runnable again, and let its schedules fire."""
    return render(await _act(session, code, active=True))


@router.post(
    "/pipelines/{code}/$deactivate",
    operation_id="deactivatePipeline",
    summary="Deactivate a pipeline",
    response_model=PipelineOut,
)
async def deactivate(code: str, session: SessionDep, principal: OperatorDep) -> PipelineOut:
    """Deregister a pipeline: schedules pause, it stops being runnable, history is kept."""
    return render(await _act(session, code, active=False))


@router.delete(
    "/pipelines/{code}",
    operation_id="deletePipeline",
    summary="Delete a pipeline and its history",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete(code: str, session: SessionDep, principal: AdminDep) -> Response:
    """Delete a pipeline and every run ever attributed to it, in one transaction.

    Admin, unlike every other pipeline verb, and it takes the history with it: the runs,
    their items, attempts, logs and artifact references, plus the versions, schedules and
    webhooks the definition owns. Runs still in flight refuse the delete with a 409 --
    finish or cancel them first. Deactivating is the reversible verb an operator has.
    """
    try:
        await delete_pipeline(session, code)
    except UnknownPipeline as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PipelineInUse as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/pipelines/{code}/$run",
    operation_id="runPipeline",
    summary="Start an ad hoc run",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    code: str,
    payload: RunRequest,
    session: SessionDep,
    services: ServicesDep,
    principal: OperatorDep,
) -> RunAccepted:
    """Validate parameters against the pipeline's schema and instantiate a run."""
    pipeline = await _require(session, code)
    if not pipeline.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"pipeline {code!r} is deactivated")
    if pipeline.current_version is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"pipeline {code!r} has no versions yet")
    version = await get_version(session, pipeline)
    definition = load_definition(version.document)
    try:
        definition.validate_params(payload.params, services.format_checker)
    except ParameterError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    try:
        run = await create_run(
            session,
            services,
            version,
            params=payload.params,
            attribution=Attribution(
                kind=principal.trigger_kind,
                id=principal.token_id or principal.user_id,
                label=principal.label,
            ),
            window=_window(payload),
            log_levels={pattern: level.value for pattern, level in payload.log_levels.items()}
            if payload.log_levels
            else None,
            priority=payload.priority,
        )
    except RunCreationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if run is None:
        return RunAccepted(status="skipped", detail="a run of this pipeline is already in flight")
    return RunAccepted(run_id=run.id, status=run.status.value)


def _window(payload: RunRequest) -> RunWindow | None:
    """Read the window a run was asked for, which the body has both ends of or neither."""
    if payload.window_start is None or payload.window_end is None:
        return None
    return RunWindow(start=payload.window_start, end=payload.window_end)


@router.post(
    "/pipelines/{code}/$backfill",
    operation_id="backfillPipeline",
    summary="Fill the windows a schedule's cadence has already gone past",
    response_model=BackfillAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_backfill(
    code: str,
    payload: BackfillRequest,
    session: SessionDep,
    services: ServicesDep,
    principal: OperatorDep,
) -> BackfillAccepted:
    """Enumerate a schedule's firings inside an interval and create one run per window.

    The schedule's own clock is untouched: this fills what has already gone past, and every
    run it creates is attributed to the backfill rather than to a firing.
    """
    del principal
    pipeline = await _require(session, code)
    if not pipeline.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"pipeline {code!r} is deactivated")
    if pipeline.current_version is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"pipeline {code!r} has no versions yet")
    schedule = await find_schedule(session, pipeline.id, payload.schedule)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline {code!r} has no schedule coded {payload.schedule!r}",
        )
    version = await get_version(session, pipeline)
    try:
        filled = await backfill(
            session,
            services,
            version,
            schedule,
            start=payload.from_,
            end=payload.to,
            params=payload.params,
            dry_run=payload.dry_run,
        )
    except BackfillError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ParameterError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except RunCreationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return BackfillAccepted(
        pipeline=pipeline.code,
        schedule=schedule.code,
        dry_run=payload.dry_run,
        windows=[
            BackfilledRun(
                window_start=one.window.start,
                window_end=one.window.end,
                run_id=one.run_id,
                detail=one.detail,
            )
            for one in filled
        ],
    )


async def _require(session: AsyncSession, code: str) -> Pipeline:
    """Read a pipeline by code, translating "no such thing" into a 404."""
    try:
        return await require_pipeline(session, code)
    except UnknownPipeline as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


async def _act(session: AsyncSession, code: str, *, active: bool) -> Pipeline:
    """Activate or deactivate, translating "no such thing" into a 404."""
    try:
        return await set_active(session, code, active=active)
    except UnknownPipeline as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
