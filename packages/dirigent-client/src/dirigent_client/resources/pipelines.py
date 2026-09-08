"""Pipelines: applying a document, and everything that can be done to a stored one."""

import builtins
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

import yaml

from dirigent_client.enums import LogLevel, ProvenanceSource, RunPriority
from dirigent_client.errors import DirigentError
from dirigent_client.resources.base import Resource, query, request_body
from dirigent_client.schemas import (
    ApplyRequest,
    ApplyResult,
    BackfillAccepted,
    BackfillRequest,
    JsonMap,
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

type DocumentSource = JsonMap | str | Path


class Pipelines(Resource):
    """Apply, export, activate, delete, and run the definitions an instance holds."""

    async def list(
        self, *, after: str | None = None, limit: int | None = None, tags: Sequence[str] = ()
    ) -> Page[PipelineOut]:
        """List every pipeline, with how many of its runs are still in flight.

        Naming more than one tag narrows: a pipeline is listed only if it wears all of them.
        """
        return await self._many(
            PipelineOut, "GET", "/pipelines", params=query(after=after, limit=limit, tag=[*tags] or None)
        )

    async def get(self, code: str) -> PipelineDetail:
        """Read a pipeline and the document its current version holds."""
        return await self._one(PipelineDetail, "GET", f"/pipelines/{code}")

    async def apply(
        self,
        document: DocumentSource,
        *,
        code: str | None = None,
        source: ProvenanceSource | None = None,
        source_ref: str | None = None,
        dry_run: bool = False,
        pause_schedules: bool = False,
    ) -> ApplyResult:
        """Validate a document against this instance and commit a new version, or plan one.

        A document this instance cannot run arrives as a 200 with ``action`` of ``invalid``
        and the issues on the plan, not as a refusal. ``pause_schedules`` creates the
        schedules this apply brings into being paused, and leaves existing ones alone.
        """
        parsed, provenance, ref = read_document(document)
        payload = ApplyRequest(
            document=parsed,
            code=code,
            source=source if source is not None else provenance,
            source_ref=source_ref if source_ref is not None else ref,
            pause_schedules=pause_schedules,
        )
        return await self._one(
            ApplyResult,
            "POST",
            "/pipelines/$apply",
            json=request_body(payload),
            params={"dry_run": dry_run},
        )

    async def prune(self, keep: Sequence[str], *, dry_run: bool = False) -> PruneResult:
        """Deactivate every directory-provenance pipeline whose code is not in ``keep``.

        The reconcile half of a directory apply: what the directory no longer holds is
        deactivated, never deleted, and a pipeline applied any other way is never touched.
        """
        payload = PruneRequest(keep=[*keep])
        return await self._one(
            PruneResult,
            "POST",
            "/pipelines/$prune",
            json=request_body(payload),
            params={"dry_run": dry_run},
        )

    async def versions(
        self, code: str, *, after: str | None = None, limit: int | None = None
    ) -> Page[PipelineVersionOut]:
        """List every immutable version, newest first, with its provenance."""
        return await self._many(
            PipelineVersionOut, "GET", f"/pipelines/{code}/versions", params=query(after=after, limit=limit)
        )

    async def export(self, code: str, *, version: int | None = None) -> str:
        """Render a stored pipeline as the canonical YAML a git repository holds."""
        return await self._transport.text(f"/pipelines/{code}/$export", params=query(version=version))

    async def validate(self, code: str, *, version: int | None = None) -> builtins.list[ValidationIssue]:
        """Report what a stored version would fail on if it ran now, against this instance.

        The issues are bounded by the document, so this one answers a bare array, not a page.
        builtins names the type because this class has a method called ``list``.
        """
        rows = await self._transport.json("POST", f"/pipelines/{code}/$validate", params=query(version=version))
        return [ValidationIssue.model_validate(row) for row in rows]

    async def activate(self, code: str) -> PipelineOut:
        """Make a pipeline runnable again, and let its schedules fire."""
        return await self._one(PipelineOut, "POST", f"/pipelines/{code}/$activate")

    async def deactivate(self, code: str) -> PipelineOut:
        """Deregister a pipeline: schedules pause, it stops being runnable, history is kept."""
        return await self._one(PipelineOut, "POST", f"/pipelines/{code}/$deactivate")

    async def delete(self, code: str) -> None:
        """Delete a pipeline and every run ever attributed to it, refusing while any is in flight."""
        await self._transport.request("DELETE", f"/pipelines/{code}")

    async def run(
        self,
        code: str,
        *,
        params: JsonMap | None = None,
        window: tuple[datetime, datetime] | None = None,
        log_levels: dict[str, LogLevel] | None = None,
        priority: RunPriority | None = None,
    ) -> RunAccepted:
        """Start an ad hoc run, with parameters validated against the pipeline's own schema.

        A ``run_id`` of ``None`` is not a failure: the pipeline's concurrency policy declined
        to start a second run while one is in flight, and ``detail`` says so.

        ``window`` is the logical data interval the run covers, half-open, which its document
        reads as ``${run.window.start}`` and ``${run.window.end}``.

        ``log_levels`` is which levels the run keeps, by block-id pattern; omitted keeps
        info and up.

        ``priority`` is how far ahead of other runs this one's attempts are claimed; omitted
        takes the pipeline's own.
        """
        payload = RunRequest(
            params=params or {},
            window_start=window[0] if window else None,
            window_end=window[1] if window else None,
            log_levels=log_levels,
            priority=priority,
        )
        return await self._one(RunAccepted, "POST", f"/pipelines/{code}/$run", json=request_body(payload))

    async def backfill(
        self,
        code: str,
        *,
        schedule: str,
        start: datetime,
        end: datetime,
        params: JsonMap | None = None,
        dry_run: bool = False,
    ) -> BackfillAccepted:
        """Fill the windows a schedule's cadence puts inside ``[start, end)``, oldest first.

        The schedule's clock is not touched: this creates the runs that interval should
        already have had. ``dry_run`` answers with the same plan and creates nothing.
        """
        payload = BackfillRequest(
            schedule=schedule,
            from_=start,
            to=end,
            params=params,
            dry_run=dry_run,
        )
        return await self._one(BackfillAccepted, "POST", f"/pipelines/{code}/$backfill", json=request_body(payload))


def read_document(document: DocumentSource) -> tuple[JsonMap, ProvenanceSource, str | None]:
    """Read a document from a mapping, a path, or its own text, and say where it came from."""
    if isinstance(document, dict):
        return dict(document), ProvenanceSource.API, None
    if isinstance(document, Path):
        return _parse(document.read_text()), ProvenanceSource.FILE, str(document)
    path = Path(document)
    if len(document) < 4096 and "\n" not in document and path.is_file():
        return _parse(path.read_text()), ProvenanceSource.FILE, document
    return _parse(document), ProvenanceSource.API, None


def _parse(text: str) -> JsonMap:
    """Read a document's text as YAML, which accepts its JSON form verbatim."""
    try:
        loaded: object = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise DirigentError(f"the document is not valid YAML or JSON: {error}") from error
    if not isinstance(loaded, dict):
        raise DirigentError(f"a document is a mapping, not {type(loaded).__name__}")
    return cast("JsonMap", loaded)
