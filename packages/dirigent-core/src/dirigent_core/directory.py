"""Applying a directory of documents: the seed at boot, and the reconcile behind prune.

A DIRECTORY CARRIES SCHEMAS AS WELL AS DOCUMENTS. A plain JSON Schema file is stored the way
``dg schema create`` stores it, and stored before the pipelines, so a document whose
``requires.schemas`` names one converges in the same pass.

THE WALK NEVER STOPS FOR ONE DOCUMENT. A directory deployed from git holds many pipelines,
and a broken one must not keep a server from starting the others: a document that cannot be
read, carries its own connections or schemas, or fails validation lands in the summary as
refused, with a warning in the log, and the walk carries on.

PRUNE ONLY EVER TOUCHES WHAT A DIRECTORY APPLIED. A pipeline is deactivated -- never
deleted, so history survives -- and only when its current version's provenance says a
directory apply wrote it. A pipeline authored in the UI or applied from a file by hand is
never pruned, however absent it is. A walk that discovered nothing refuses to prune at all:
an empty mount is an accident, not an instruction to turn everything off.
"""

from pathlib import Path
from typing import Final, cast

import sqlalchemy as sa
import yaml
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import ProvenanceSource
from dirigent_client.schemas import PlanAction, PruneResult
from dirigent_common import JsonMap
from dirigent_core.database import session_scope
from dirigent_core.documents import DocumentError, carried_refusal, load_text, safe_load
from dirigent_core.engine.definition import KIND_TRIGGERS
from dirigent_core.engine.runs import Provenance
from dirigent_core.engine.services import EngineServices
from dirigent_core.logging import get_logger
from dirigent_core.models import Pipeline, PipelineVersion
from dirigent_core.pipelines import apply_document, set_active
from dirigent_core.scheduler import release_lead, try_lead
from dirigent_core.schemas import SchemaRefused, check_valid_schema, find_schema, resolve_identity, store_schema
from dirigent_core.trigger_documents import delete_absent_trigger_documents

_logger = get_logger(__name__)

#: The suffixes a document may carry, the same set a project's pipelines directory takes.
DOCUMENT_SUFFIXES: Final = (".yaml", ".yml", ".json")

#: Where a file sorts in the walk, and which applier it goes to.
_RANK_SCHEMA: Final = 0
_RANK_PIPELINE: Final = 1
_RANK_TRIGGERS: Final = 2

#: The keywords a plain JSON Schema is recognised by when it names no ``$schema``.
_SCHEMA_KEYWORDS: Final = ("type", "properties", "$id")


def discover_documents(root: Path) -> list[Path]:
    """List every document under the directory, however deep, in a stable order.

    A corpus deployed from git nests -- a directory per team, per system, per cadence -- and
    a walk that stopped at the first level would silently apply half of it. The order is the
    relative path, so two runs of one tree agree.
    """
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.rglob("*") if path.suffix in DOCUMENT_SUFFIXES and path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )


class RefusedDocument(BaseModel):
    """One document the walk could not apply, and the first reason why."""

    path: str
    code: str | None = None
    message: str


class DirectorySummary(BaseModel):
    """What one walk of the directory did, list by list."""

    applied: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    refused: list[RefusedDocument] = []
    pruned: list[str] = []
    trigger_documents_removed: list[str] = []
    """The triggers documents the directory no longer holds, deleted with the rows they owned."""

    schemas: list[str] = []
    """Which of the codes above are schemas rather than pipelines, so a reader can tell them apart."""

    prune_refusal: str | None = None
    """Why nothing was pruned when pruning was asked for, or nothing at all."""

    skipped: bool = False
    """Another process held the apply lock, so it is doing this work."""

    aborted: str | None = None
    """Why the walk stopped early: an instance fault, which no list of refusals should wear."""


async def prune_absent(session: AsyncSession, keep: set[str], *, dry_run: bool = False) -> PruneResult:
    """Reconcile against a directory: deactivate absent pipelines, delete absent triggers documents.

    The narrowing is by the CURRENT version's provenance: what a directory applied last, a
    directory may take away. Deactivation pauses nothing retroactively beyond what
    deactivation always means, and history survives untouched. A triggers document has no
    history worth keeping, so it is deleted instead, and the cascade takes the schedules and
    webhooks it owned -- never the pipeline's own inline ones. A schema is never pruned.
    """
    rows = await session.execute(
        sa.select(Pipeline.code)
        .join(
            PipelineVersion,
            sa.and_(
                PipelineVersion.pipeline_id == Pipeline.id,
                PipelineVersion.version == Pipeline.current_version,
            ),
        )
        .where(
            Pipeline.active.is_(True),
            PipelineVersion.provenance_source == ProvenanceSource.DIRECTORY,
            Pipeline.code.notin_(keep) if keep else sa.true(),
        )
        .order_by(Pipeline.code)
    )
    absent = [str(code) for (code,) in rows.all()]
    documents = await delete_absent_trigger_documents(session, keep, dry_run=dry_run)
    if not dry_run:
        for code in absent:
            await set_active(session, code, active=False)
    return PruneResult(pruned=absent, trigger_documents_removed=documents, dry_run=dry_run)


async def apply_directory(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    root: Path,
    *,
    prune: bool = False,
    dry_run: bool = False,
    pause_schedules: bool = False,
    lock_key: int | None = None,
) -> DirectorySummary:
    """Apply every schema and document in the directory, then reconcile when asked to.

    Each one is applied in its own transaction, so one that fails rolls back alone.
    With a ``lock_key``, the whole walk runs under the same PostgreSQL advisory lock the
    scheduler uses for leadership: several servers booting together elect one applier, and
    the others skip with a log line rather than racing it.
    """
    summary = DirectorySummary()
    async with session_scope(sessions) as holder:
        if lock_key is not None and not await try_lead(holder, lock_key):
            _logger.info("directory apply skipped: another process holds the lock", root=str(root))
            summary.skipped = True
            return summary
        try:
            await _walk(sessions, services, root, summary, dry_run=dry_run, pause_schedules=pause_schedules)
            if prune:
                await _prune(sessions, summary, dry_run=dry_run)
        except SQLAlchemyError as error:
            summary.aborted = str(error).splitlines()[0]
            _logger.error("directory apply aborted by an instance fault", root=str(root), error=summary.aborted)
        finally:
            if lock_key is not None:
                await release_lead(holder, lock_key)
    return summary


async def _walk(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    root: Path,
    summary: DirectorySummary,
    *,
    dry_run: bool,
    pause_schedules: bool,
) -> None:
    """Apply each discovered file into the summary, refusing without stopping.

    Schemas go first, pipeline documents after them, and triggers documents last, so a
    directory carrying all three converges in one pass: a pipeline is refused while a schema
    its ``requires`` names is absent, and a triggers document is refused while the pipeline it
    names is absent. Applying each ahead of what needs it is what makes it present.
    """
    documents = discover_documents(root)
    if not documents:
        _logger.warning("directory apply found no documents", root=str(root))
        return
    walked: dict[str, str] = {}
    for rank, path in sorted(((_walk_rank(path), path) for path in documents), key=lambda pair: pair[0]):
        if rank == _RANK_SCHEMA:
            await _apply_schema(sessions, root, path, summary, dry_run=dry_run)
        else:
            await _apply_one(
                sessions, services, root, path, summary, walked, dry_run=dry_run, pause_schedules=pause_schedules
            )


def _walk_rank(path: Path) -> int:
    """Peek at a file once to place it in the walk, without holding it against the format.

    A ``.json`` file that parses to an object carrying neither ``format`` nor ``kind`` is a
    plain JSON Schema when it names ``$schema``, or failing that any of the keywords a schema
    is written with. One that cannot be read at all sorts with the pipelines, so it is refused
    where its own path says it should be.
    """
    try:
        raw = safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return _RANK_PIPELINE
    if not isinstance(raw, dict):
        return _RANK_PIPELINE
    body = cast("JsonMap", raw)
    if body.get("kind") == KIND_TRIGGERS:
        return _RANK_TRIGGERS
    unenveloped = path.suffix == ".json" and "format" not in body and "kind" not in body
    if unenveloped and ("$schema" in body or any(keyword in body for keyword in _SCHEMA_KEYWORDS)):
        return _RANK_SCHEMA
    return _RANK_PIPELINE


async def _apply_schema(
    sessions: async_sessionmaker[AsyncSession],
    root: Path,
    path: Path,
    summary: DirectorySummary,
    *,
    dry_run: bool,
) -> None:
    """Store one JSON Schema the directory carries, in its own transaction."""
    ref = path.relative_to(root).as_posix()
    try:
        body = cast("JsonMap", safe_load(path.read_text()))
        check_valid_schema(body)
        code, name, description = resolve_identity(
            body, code=None, name=None, description=None, fallback_code=path.stem
        )
    except (OSError, ValueError, yaml.YAMLError, SchemaRefused) as error:
        summary.refused.append(RefusedDocument(path=ref, message=str(error)))
        _logger.warning("directory schema refused", path=ref, error=str(error))
        return
    async with session_scope(sessions) as session:
        existing = await find_schema(session, code)
        if existing is None:
            summary.applied.append(code)
        elif existing.body == body and existing.name == name and existing.description == description:
            summary.unchanged.append(code)
        else:
            summary.updated.append(code)
        if not dry_run:
            await store_schema(session, body, fallback_code=path.stem)
    summary.schemas.append(code)


async def _apply_one(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    root: Path,
    path: Path,
    summary: DirectorySummary,
    walked: dict[str, str],
    *,
    dry_run: bool,
    pause_schedules: bool,
) -> None:
    """Apply one document into the summary."""
    ref = path.relative_to(root).as_posix()
    try:
        definition = load_text(path.read_text())
    except (OSError, DocumentError) as error:
        summary.refused.append(RefusedDocument(path=ref, message=str(error)))
        _logger.warning("directory document refused", path=ref, error=str(error))
        return
    if definition.code in walked:
        message = f"code '{definition.code}' was already applied from {walked[definition.code]} in this walk"
        summary.refused.append(RefusedDocument(path=ref, code=definition.code, message=message))
        _logger.warning("directory document refused", path=ref, pipeline=definition.code, error=message)
        return
    walked[definition.code] = ref
    carried = carried_refusal(definition)
    if carried is not None:
        summary.refused.append(RefusedDocument(path=ref, code=definition.code, message=carried))
        _logger.warning("directory document refused", path=ref, pipeline=definition.code, error=carried)
        return
    try:
        async with session_scope(sessions) as session:
            result = await apply_document(
                session,
                services,
                definition,
                provenance=Provenance(source=ProvenanceSource.DIRECTORY, ref=ref),
                dry_run=dry_run,
                pause_schedules=pause_schedules,
            )
    except SQLAlchemyError:
        # A database fault is the instance's, not this document's: refusing 59 documents
        # one by one is how a schema drift hides. The walk stops and says so once.
        raise
    except Exception as error:  # noqa: BLE001 - one broken document must not stop the walk
        summary.refused.append(RefusedDocument(path=ref, code=definition.code, message=str(error)))
        _logger.warning("directory document refused", path=ref, pipeline=definition.code, error=str(error))
        return
    plan = result.plan
    if plan.action is PlanAction.INVALID:
        first = plan.issues[0].message if plan.issues else "invalid"
        summary.refused.append(RefusedDocument(path=ref, code=plan.code, message=first))
        _logger.warning("directory document refused", path=ref, pipeline=plan.code, error=first)
    elif plan.action is PlanAction.CREATE:
        summary.applied.append(plan.code)
    elif plan.action is PlanAction.UPDATE:
        summary.updated.append(plan.code)
    else:
        summary.unchanged.append(plan.code)


async def _prune(sessions: async_sessionmaker[AsyncSession], summary: DirectorySummary, *, dry_run: bool) -> None:
    """Reconcile after the walk: deactivate what the directory no longer holds.

    Schema codes are dropped from what is kept: they name no pipeline, and no schema is pruned.
    """
    codes = {
        *summary.applied,
        *summary.updated,
        *summary.unchanged,
        *(refused.code for refused in summary.refused if refused.code is not None),
    }
    if not codes:
        summary.prune_refusal = "the directory held no documents, and an empty directory never prunes"
        _logger.warning("directory prune refused", reason=summary.prune_refusal)
        return
    keep = codes - set(summary.schemas)
    async with session_scope(sessions) as session:
        result = await prune_absent(session, keep, dry_run=dry_run)
    summary.pruned = result.pruned
    summary.trigger_documents_removed = result.trigger_documents_removed
