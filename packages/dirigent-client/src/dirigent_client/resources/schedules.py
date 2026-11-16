"""A pipeline's schedules: their clocks, their state, and what they have actually done."""

from datetime import datetime, timedelta

from dirigent_client.enums import LogLevel, RunPriority
from dirigent_client.resources.base import Resource, query, request_body, segment
from dirigent_client.schemas import (
    FiringOut,
    Page,
    ScheduleIn,
    ScheduleOut,
    SchedulePreview,
    SchedulePreviewRequest,
)
from dirigent_common import JsonMap, to_timedelta


class Schedules(Resource):
    """Declare, redeclare, pause, and read the schedules hanging from a pipeline, and preview a clock."""

    async def list(self, pipeline: str, *, after: str | None = None, limit: int | None = None) -> Page[ScheduleOut]:
        """List every schedule on a pipeline, with when each one next fires."""
        return await self._many(
            ScheduleOut,
            "GET",
            f"/pipelines/{segment(pipeline)}/triggers/schedules",
            params=query(after=after, limit=limit),
        )

    async def get(self, pipeline: str, code: str) -> ScheduleOut:
        """Read one schedule by code."""
        return await self._one(ScheduleOut, "GET", f"/pipelines/{segment(pipeline)}/triggers/schedules/{segment(code)}")

    async def create(
        self,
        pipeline: str,
        code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        cron: str | None = None,
        interval: timedelta | str | None = None,
        at: datetime | None = None,
        timezone: str = "UTC",
        params: JsonMap | None = None,
        connection_pins: JsonMap | None = None,
        log_levels: dict[str, LogLevel] | None = None,
        priority: RunPriority | None = None,
    ) -> ScheduleOut:
        """Declare a schedule on a pipeline and compute when it first fires."""
        return await self._one(
            ScheduleOut,
            "POST",
            f"/pipelines/{segment(pipeline)}/triggers/schedules",
            json=_declaration(
                code, name, description, cron, interval, at, timezone, params, connection_pins, log_levels, priority
            ),
        )

    async def redeclare(
        self,
        pipeline: str,
        code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        cron: str | None = None,
        interval: timedelta | str | None = None,
        at: datetime | None = None,
        timezone: str = "UTC",
        params: JsonMap | None = None,
        connection_pins: JsonMap | None = None,
        log_levels: dict[str, LogLevel] | None = None,
        priority: RunPriority | None = None,
    ) -> ScheduleOut:
        """Replace a schedule's whole declaration, keeping whether it is paused.

        This is a declaration, not an edit: an argument left out takes the value ``create``
        gives it, so a schedule redeclared with only a new ``cron`` loses its parameters, its
        pins, its labels and its timezone. Read the schedule first to keep any of them.
        """
        return await self._one(
            ScheduleOut,
            "PUT",
            f"/pipelines/{segment(pipeline)}/triggers/schedules/{segment(code)}",
            json=_declaration(
                code, name, description, cron, interval, at, timezone, params, connection_pins, log_levels, priority
            ),
        )

    async def pause(self, pipeline: str, code: str) -> ScheduleOut:
        """Stop a schedule firing, without losing it or its history."""
        return await self._one(
            ScheduleOut, "POST", f"/pipelines/{segment(pipeline)}/triggers/schedules/{segment(code)}/$pause"
        )

    async def resume(self, pipeline: str, code: str) -> ScheduleOut:
        """Start a schedule firing again, from the next slot rather than the ones it missed."""
        return await self._one(
            ScheduleOut, "POST", f"/pipelines/{segment(pipeline)}/triggers/schedules/{segment(code)}/$resume"
        )

    async def delete(self, pipeline: str, code: str) -> None:
        """Remove a schedule and its firing history."""
        await self._transport.request("DELETE", f"/pipelines/{segment(pipeline)}/triggers/schedules/{segment(code)}")

    async def preview(
        self,
        *,
        cron: str | None = None,
        interval: str | None = None,
        at: str | None = None,
        timezone: str = "UTC",
    ) -> SchedulePreview:
        """Read back the next firings of a clock nobody has declared, with the scheduler's own arithmetic."""
        payload = SchedulePreviewRequest(cron=cron, interval=interval, at=at, timezone=timezone)
        return await self._one(SchedulePreview, "POST", "/schedules/$preview", json=request_body(payload))

    async def firings(
        self, pipeline: str, code: str, *, after: str | None = None, limit: int | None = None
    ) -> Page[FiringOut]:
        """Read what a schedule has actually done, newest first, including what it skipped."""
        return await self._many(
            FiringOut,
            "GET",
            f"/pipelines/{segment(pipeline)}/triggers/schedules/{segment(code)}/firings",
            params=query(after=after, limit=limit),
        )


def _declaration(
    code: str,
    name: str | None,
    description: str | None,
    cron: str | None,
    interval: timedelta | str | None,
    at: datetime | None,
    timezone: str,
    params: JsonMap | None,
    connection_pins: JsonMap | None,
    log_levels: dict[str, LogLevel] | None,
    priority: RunPriority | None,
) -> JsonMap:
    """Render a schedule declaration as the body the API takes."""
    payload = ScheduleIn(
        code=code,
        name=name,
        description=description,
        cron=cron,
        interval=to_timedelta(interval) if interval is not None else None,
        at=at,
        timezone=timezone,
        params=params or {},
        connection_pins=connection_pins or {},
        log_levels=log_levels,
        priority=priority,
    )
    return request_body(payload)
