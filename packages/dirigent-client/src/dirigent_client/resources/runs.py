"""Runs: reading them, acting on them, waiting for one, and following the story one tells."""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import Final
from uuid import UUID

import httpx2

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_client.errors import TransportError, WaitTimeout
from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import (
    ArtifactOut,
    AttemptEvent,
    AttemptOut,
    ItemOut,
    LogEntryOut,
    Page,
    RunDetail,
    RunOut,
    RunReport,
)

#: What a run's own report document is stored as, which is how it is told from a step's output.
MARKDOWN_CONTENT_TYPE: Final = "text/markdown"

POLL_SECONDS: Final = 1.0
POLL_MAX_SECONDS: Final = 15.0
POLL_BACKOFF: Final = 1.5
DEFAULT_WAIT: Final = timedelta(hours=1)
DEFAULT_RECONNECTS: Final = 5
RECONNECT_SECONDS: Final = 1.0


class Runs(Resource):
    """List, read, cancel, retry, and follow the runs an instance has executed."""

    async def list(
        self,
        *,
        pipeline: str | None = None,
        status: RunStatus | None = None,
        since: str | None = None,
        tags: Sequence[str] = (),
        after: str | None = None,
        limit: int | None = None,
    ) -> Page[RunOut]:
        """List runs newest first, filtered by pipeline, status, tag, and how far back to look.

        Naming more than one tag narrows: a run is listed only if its pipeline wears all of them.
        """
        return await self._many(
            RunOut,
            "GET",
            "/runs",
            params=query(
                pipeline=pipeline,
                status=status.value if status else None,
                since=since,
                tag=[*tags] or None,
                after=after,
                limit=limit,
            ),
        )

    async def get(self, run_id: UUID | str) -> RunDetail:
        """Read a run with the DAG view model, and how many items and attempts it has."""
        return await self._one(RunDetail, "GET", f"/runs/{run_id}")

    async def items(
        self,
        run_id: UUID | str,
        *,
        after: str | None = None,
        limit: int | None = None,
    ) -> Page[ItemOut]:
        """List a run's fan-out items in the order they were created, which is grid order."""
        return await self._many(ItemOut, "GET", f"/runs/{run_id}/items", params=query(after=after, limit=limit))

    async def attempts(
        self,
        run_id: UUID | str,
        *,
        step: str | None = None,
        status: AttemptStatus | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> Page[AttemptOut]:
        """List a run's attempts in the order they were created, filtered by step and by state."""
        return await self._many(
            AttemptOut,
            "GET",
            f"/runs/{run_id}/attempts",
            params=query(step=step, status=status.value if status else None, after=after, limit=limit),
        )

    async def artifacts(
        self,
        run_id: UUID | str,
        *,
        after: str | None = None,
        limit: int | None = None,
    ) -> Page[ArtifactOut]:
        """List what a run wrote down: each step's stored output, and its report document."""
        return await self._many(ArtifactOut, "GET", f"/runs/{run_id}/artifacts", params=query(after=after, limit=limit))

    async def artifact_text(self, artifact_id: UUID | str) -> str:
        """Read one artifact's content as the text it was stored as."""
        return await self._transport.text(f"/artifacts/{artifact_id}")

    async def report_document(self, run_id: UUID | str) -> str | None:
        """Read the markdown document this run rendered when it settled, if it rendered one."""
        page = await self.artifacts(run_id)
        found = next(
            (row for row in page.items if row.step_name is None and row.content_type == MARKDOWN_CONTENT_TYPE),
            None,
        )
        return None if found is None else await self.artifact_text(found.id)

    async def cancel(self, run_id: UUID | str) -> RunOut:
        """Stop what has not started, and tell the remote about what has."""
        return await self._one(RunOut, "POST", f"/runs/{run_id}/$cancel")

    async def retry(self, attempt_id: UUID | str, *, idempotency_key: str | None = None) -> AttemptOut:
        """Create one manual attempt of a failed step, reading its upstream stored outputs."""
        key = idempotency_key or str(uuid.uuid4())
        return await self._one(AttemptOut, "POST", f"/attempts/{attempt_id}/$retry", headers={"Idempotency-Key": key})

    async def logs(
        self,
        run_id: UUID | str,
        *,
        after: str | None = None,
        limit: int | None = None,
        step: str | None = None,
    ) -> Page[LogEntryOut]:
        """Read one page of a run's log entries, in write order."""
        return await self._many(
            LogEntryOut, "GET", f"/runs/{run_id}/$logs", params=query(after=after, limit=limit, step=step)
        )

    async def report(self, run_id: UUID | str) -> RunReport:
        """Summarise a run: what each step amounted to, and how long the whole thing took."""
        return await self._one(RunReport, "GET", f"/runs/{run_id}/$report")

    async def wait(
        self,
        run_id: UUID | str,
        *,
        timeout: timedelta = DEFAULT_WAIT,
        poll: float = POLL_SECONDS,
    ) -> RunOut:
        """Poll a run until it reaches a status nothing will move it out of."""
        deadline = time.monotonic() + timeout.total_seconds()
        interval = poll
        while True:
            run = (await self.get(run_id)).run
            if run.terminal:
                return run
            if time.monotonic() + interval > deadline:
                raise WaitTimeout(
                    f"run {run_id} was still {run.status.value} after {timeout}",
                    url=self._transport.endpoint(f"/runs/{run_id}"),
                )
            await asyncio.sleep(interval)
            interval = min(interval * POLL_BACKOFF, POLL_MAX_SECONDS)

    async def events(
        self,
        run_id: UUID | str,
        *,
        after: int = 0,
        reconnects: int = DEFAULT_RECONNECTS,
    ) -> AsyncIterator[AttemptEvent | LogEntryOut | RunOut]:
        """Stream one run's story: its attempts as they move, what they log, and how it ended.

        The server closes a stream two ways. ``end`` says the run settled, and the terminal
        state is the last thing sent before it. ``expired`` says the stream reached the
        server's wall-clock limit with the run still going; it is reopened from the last
        entry yielded, and costs no reconnect. A stream that closes saying neither was cut,
        and is reopened at the cost of one of ``reconnects`` -- the same budget a transport
        failure spends, and a log entry delivered restores it in full.

        Every attempt is replayed on connect, so a consumer dedupes what it has already read.
        """
        cursor = after
        remaining = reconnects
        while True:
            ended = False
            expired = False
            advanced = False
            try:
                async with self._transport.stream(f"/runs/{run_id}/$events", params=query(after=cursor)) as response:
                    async for event in httpx2.EventSource(response):
                        if event.event == "end":
                            ended = True
                            break
                        if event.event == "expired":
                            expired = True
                            break
                        if not event.data:
                            continue
                        if event.event == "attempt":
                            yield AttemptEvent.model_validate_json(event.data)
                        elif event.event == "log":
                            entry = LogEntryOut.model_validate_json(event.data)
                            cursor = entry.id
                            advanced = True
                            yield entry
                        elif event.event == "run":
                            yield RunOut.model_validate_json(event.data)
            except (TransportError, httpx2.StreamError):
                if remaining <= 0:
                    raise
                remaining -= 1
                await asyncio.sleep(RECONNECT_SECONDS)
                continue
            if ended:
                return
            if advanced:
                remaining = reconnects
            elif not expired:
                if remaining <= 0:
                    return
                remaining -= 1
            await asyncio.sleep(RECONNECT_SECONDS)

    async def follow_logs(
        self,
        run_id: UUID | str,
        *,
        after: int = 0,
        step: str | None = None,
        reconnects: int = DEFAULT_RECONNECTS,
    ) -> AsyncIterator[LogEntryOut]:
        """Stream a run's log entries until the run settles, reopening a dropped connection.

        The server closes a stream two ways. ``end`` says the run is terminal and there is
        nothing more to read. ``expired`` says the stream reached the server's wall-clock
        limit with the run still going; it is reopened from the last entry yielded, and
        costs no reconnect. A stream that closes saying neither was cut, and is reopened at
        the cost of one of ``reconnects`` -- the same budget a transport failure spends, and
        an entry delivered restores it in full.
        """
        cursor = after
        remaining = reconnects
        while True:
            ended = False
            expired = False
            advanced = False
            try:
                params = query(follow="sse", after=cursor, step=step)
                async with self._transport.stream(f"/runs/{run_id}/$logs", params=params) as response:
                    async for event in httpx2.EventSource(response):
                        if event.event == "end":
                            ended = True
                            break
                        if event.event == "expired":
                            expired = True
                            break
                        if event.event == "log" and event.data:
                            entry = LogEntryOut.model_validate_json(event.data)
                            cursor = entry.id
                            advanced = True
                            yield entry
            except (TransportError, httpx2.StreamError):
                if remaining <= 0:
                    raise
                remaining -= 1
                await asyncio.sleep(RECONNECT_SECONDS)
                continue
            if ended:
                return
            if advanced:
                remaining = reconnects
            elif not expired:
                if remaining <= 0:
                    return
                remaining -= 1
            await asyncio.sleep(RECONNECT_SECONDS)
