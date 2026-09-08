"""Applying, reading, and deleting a ``kind: triggers`` document.

The document names one pipeline and declares clocks and webhooks for it. It has no versions:
what it says is operational, and the digest is only what makes an unchanged re-apply cheap.
An unchanged one still reconciles, exactly as a pipeline document does.
"""

from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import DocumentKind, ProvenanceSource
from dirigent_client.schemas import ApplyResult, PipelinePlan, PlanAction
from dirigent_core.documents import TriggerTarget, digest_of, validate_against_catalog
from dirigent_core.engine.definition import TriggersDefinition, canonical_document, load_definition
from dirigent_core.engine.runs import Provenance
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.logging import get_logger
from dirigent_core.models import Pipeline, Schedule, TriggerDocument, WebhookTrigger
from dirigent_core.triggers.materialize import materialize_triggers, owner_issues

_logger = get_logger("triggers")

#: The owner a document that does not exist yet declares under: an id no row can hold, so
#: every code the pipeline already carries belongs to somebody else.
UNAPPLIED: Final = UUID(int=0)


async def find_trigger_document(session: AsyncSession, code: str) -> TriggerDocument | None:
    """Find the triggers document holding a code."""
    found = await session.execute(sa.select(TriggerDocument).where(TriggerDocument.code == code))
    return found.scalar_one_or_none()


async def list_trigger_documents(
    session: AsyncSession,
    *,
    after: str | None = None,
    limit: int | None = None,
) -> list[TriggerDocument]:
    """List triggers documents in code order."""
    statement = sa.select(TriggerDocument).order_by(TriggerDocument.code)
    if after is not None:
        statement = statement.where(TriggerDocument.code > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def owned_codes(session: AsyncSession, document_id: UUID) -> tuple[list[str], list[str]]:
    """List the schedules and the webhooks one triggers document owns, in code order."""
    schedules = await session.execute(
        sa.select(Schedule.code).where(Schedule.trigger_document_id == document_id).order_by(Schedule.code)
    )
    webhooks = await session.execute(
        sa.select(WebhookTrigger.code)
        .where(WebhookTrigger.trigger_document_id == document_id)
        .order_by(WebhookTrigger.code)
    )
    return list(schedules.scalars()), list(webhooks.scalars())


async def delete_trigger_document(session: AsyncSession, row: TriggerDocument) -> None:
    """Delete a triggers document, and with it every schedule and webhook it owns."""
    await session.delete(row)
    await session.flush()
    _logger.info("triggers document deleted", document=row.code)


async def delete_absent_trigger_documents(session: AsyncSession, keep: set[str], *, dry_run: bool = False) -> list[str]:
    """Delete every directory-provenance triggers document whose code is not in ``keep``.

    A pipeline is deactivated rather than deleted because its history is worth keeping. A
    triggers document has none: it is deleted, and its rows go with it.
    """
    rows = await session.execute(
        sa.select(TriggerDocument)
        .where(
            TriggerDocument.provenance_source == ProvenanceSource.DIRECTORY,
            TriggerDocument.code.notin_(keep) if keep else sa.true(),
        )
        .order_by(TriggerDocument.code)
    )
    absent = list(rows.scalars())
    if dry_run:
        return [row.code for row in absent]
    for row in absent:
        await delete_trigger_document(session, row)
    return [row.code for row in absent]


async def plan_triggers_apply(
    session: AsyncSession,
    services: EngineServices,
    definition: TriggersDefinition,
    pipeline: Pipeline | None,
    existing: TriggerDocument | None,
) -> PipelinePlan:
    """Work out what applying a triggers document would do, without writing anything."""
    digest = digest_of(definition)
    issues = validate_against_catalog(
        definition,
        services.host.catalog(),
        format_checker=services.format_checker,
        target=await _target(session, pipeline),
    )
    if not issues and pipeline is not None:
        issues = await owner_issues(
            session,
            pipeline,
            definition.triggers,
            owner=existing.id if existing is not None else UNAPPLIED,
        )
    if issues:
        return PipelinePlan(
            code=definition.code,
            pipeline=definition.pipeline,
            action=PlanAction.INVALID,
            digest=digest,
            issues=issues,
        )
    if existing is None:
        return PipelinePlan(code=definition.code, pipeline=definition.pipeline, action=PlanAction.CREATE, digest=digest)
    action = PlanAction.UNCHANGED if existing.digest == digest else PlanAction.UPDATE
    return PipelinePlan(code=definition.code, pipeline=definition.pipeline, action=action, digest=digest)


async def _target(session: AsyncSession, pipeline: Pipeline | None) -> TriggerTarget | None:
    """Read the pipeline a triggers document names, as the instance holds it now."""
    if pipeline is None:
        return None
    current = None
    if pipeline.current_version is not None:
        from dirigent_core.pipelines import get_version

        current = load_definition((await get_version(session, pipeline)).document)
    return TriggerTarget(code=pipeline.code, active=pipeline.active, definition=current)


async def apply_triggers_document(
    session: AsyncSession,
    services: EngineServices,
    definition: TriggersDefinition,
    *,
    provenance: Provenance | None = None,
    dry_run: bool = False,
    pause_schedules: bool = False,
) -> ApplyResult:
    """Validate, plan, and -- unless this is a dry run -- write the document and its rows.

    An unchanged document still reconciles, so a schedule deleted by hand comes back.
    """
    from dirigent_core.pipelines import find_pipeline

    pipeline = await find_pipeline(session, definition.pipeline)
    if pipeline is not None:
        # The plan reads the pipeline's rows and everything after it writes against that read.
        await lock_pipeline(session, pipeline.id)
    existing = await find_trigger_document(session, definition.code)
    plan = await plan_triggers_apply(session, services, definition, pipeline, existing)
    if pipeline is None or dry_run or plan.action is PlanAction.INVALID:
        return ApplyResult(
            kind=DocumentKind.TRIGGERS,
            plan=plan,
            pipeline_id=pipeline.id if pipeline is not None else None,
            dry_run=dry_run,
        )
    row = existing or TriggerDocument(code=definition.code)
    row.name = definition.name
    row.description = definition.description
    row.pipeline_id = pipeline.id
    row.document = canonical_document(definition)
    row.digest = plan.digest
    if provenance is not None:
        row.provenance_source = provenance.source
        row.provenance_ref = provenance.ref
        row.applied_by = provenance.applied_by
    if existing is None:
        session.add(row)
    await session.flush()
    triggers = await materialize_triggers(session, pipeline, definition, pause_created=pause_schedules, owner=row.id)
    _logger.info(
        "triggers document applied",
        document=definition.code,
        pipeline=pipeline.code,
        action=plan.action.value,
        digest=plan.digest,
    )
    return ApplyResult(kind=DocumentKind.TRIGGERS, plan=plan, pipeline_id=pipeline.id, triggers=triggers)
