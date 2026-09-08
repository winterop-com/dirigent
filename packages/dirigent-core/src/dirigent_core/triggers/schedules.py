"""Schedules: the clock a pipeline carries, and the arithmetic that advances it.

A schedule declares exactly one clock -- cron, interval, or a one-time firing -- in its own
timezone, which is a column on the row and never a property of whichever process is leader.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from cronsim import CronSim, CronSimError
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import RunPriority, ScheduleKind
from dirigent_common import EntityName, JsonMap
from dirigent_common.durations import Duration, DurationError, parse_duration, refuse_negative
from dirigent_core.engine.definition import (
    ParameterError,
    PipelineDefinition,
    ScheduleSpec,
    anchor_naive_moment,
)
from dirigent_core.engine.runs import RunWindow
from dirigent_core.logging import get_logger
from dirigent_core.models import Pipeline, Schedule, ScheduleFiring, utcnow

_logger = get_logger("scheduler")


class ScheduleError(Exception):
    """A schedule could not be declared, found, or advanced."""


class DuplicateSchedule(ScheduleError):
    """A pipeline already has a schedule of that code."""

    def __init__(self, pipeline: str, code: str) -> None:
        """Name the pipeline and the schedule."""
        super().__init__(f"pipeline {pipeline!r} already has a schedule coded {code!r}")
        self.pipeline = pipeline
        self.code = code


class UnknownSchedule(ScheduleError):
    """No schedule of that code exists on this pipeline."""

    def __init__(self, pipeline: str, code: str) -> None:
        """Name the pipeline and the schedule."""
        super().__init__(f"pipeline {pipeline!r} has no schedule coded {code!r}")
        self.pipeline = pipeline
        self.code = code


class ScheduleRequest(BaseModel):
    """What it takes to declare a schedule, from a document, the API, or the CLI."""

    model_config = ConfigDict(frozen=True)

    code: EntityName
    name: str | None = None
    description: str | None = None
    cron: str | None = None
    interval: Duration | None = None
    at: datetime | None = None
    timezone: str = "UTC"
    params: JsonMap = Field(default_factory=dict)
    connection_pins: JsonMap = Field(default_factory=dict)
    log_levels: JsonMap | None = None
    """The log-level map every fired run carries, or None for the default: info and up."""

    priority: RunPriority | None = None
    """The priority every fired run carries, or None to take the pipeline's own."""

    @model_validator(mode="after")
    def _anchor_a_naive_moment(self) -> "ScheduleRequest":
        """Read a naive ``at`` in the zone this schedule declares."""
        anchored = anchor_naive_moment(self.at, self.timezone)
        return self if anchored is self.at else self.model_copy(update={"at": anchored})

    @classmethod
    def from_spec(cls, spec: ScheduleSpec) -> "ScheduleRequest":
        """Read a document's schedule declaration as a request."""
        return cls(
            code=spec.code,
            name=spec.name,
            description=spec.description,
            cron=spec.cron,
            interval=spec.interval,
            at=spec.at,
            timezone=spec.timezone,
            params=dict(spec.params),
            priority=spec.priority,
        )

    def kind(self) -> ScheduleKind:
        """Report which of the three clocks this request declares."""
        if self.cron is not None:
            return ScheduleKind.CRON
        if self.interval is not None:
            return ScheduleKind.INTERVAL
        return ScheduleKind.ONE_TIME


def check_schedule(request: ScheduleRequest) -> None:
    """Refuse a schedule that names no clock, more than one, or a zone or expression nothing can read."""
    declared = [field for field in ("cron", "interval", "at") if getattr(request, field) is not None]
    if len(declared) != 1:
        named = ", ".join(declared) or "none"
        raise ScheduleError(f"a schedule declares exactly one of cron, interval, or at ({named})")
    resolve_zone(request.timezone)
    if request.cron is not None:
        _check_cron(request.cron, request.timezone)
    if request.interval is not None:
        _check_interval(request.interval)


def _check_interval(interval: timedelta) -> None:
    """Refuse an interval the row cannot hold: it is stored as whole seconds."""
    seconds = interval.total_seconds()
    if seconds < 1 or seconds != int(seconds):
        raise ScheduleError(
            f"an interval schedule fires every whole number of seconds, at least one, not every {seconds}s"
        )


def check_schedule_params(definition: PipelineDefinition, params: JsonMap, format_checker: FormatChecker) -> None:
    """Refuse pinned parameters the pipeline's schema would refuse when the schedule fires.

    A schedule's pins are the whole parameter object of every run it creates, so this is the
    same validation run creation does, moved to the moment the schedule is declared.
    """
    try:
        definition.validate_params(dict(params), format_checker)
    except ParameterError as error:
        raise ScheduleError(str(error)) from error


def resolve_zone(name: str) -> ZoneInfo:
    """Resolve an IANA timezone name, or say plainly that this host does not know it."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ScheduleError(f"{name!r} is not an IANA timezone this host knows (try 'UTC' or 'Europe/Oslo')") from error


def _check_cron(expression: str, timezone: str) -> None:
    """Parse a cron expression once at declaration time, so a bad one never reaches a tick."""
    try:
        next(CronSim(expression, datetime.now(resolve_zone(timezone))))
    except CronSimError as error:
        raise ScheduleError(f"{expression!r} is not a cron expression: {error}") from error
    except StopIteration as error:  # pragma: no cover - an expression that never fires again
        raise ScheduleError(f"{expression!r} names no future time") from error


def next_fire_after(
    *,
    kind: ScheduleKind,
    cron: str | None,
    interval_seconds: int | None,
    run_at: datetime | None,
    timezone: str,
    after: datetime,
) -> datetime | None:
    """Compute the first firing strictly after an instant, in the schedule's own timezone.

    Returns None when the clock has run out, which only a one-time schedule can do. Cron is
    evaluated in the declared zone rather than in UTC, so a nightly job stays nightly across
    a daylight-saving boundary.
    """
    match kind:
        case ScheduleKind.CRON:
            if cron is None:  # pragma: no cover - the check refuses this at declaration time
                raise ScheduleError("a cron schedule has no expression")
            local = after.astimezone(resolve_zone(timezone))
            try:
                return next(CronSim(cron, local)).astimezone(UTC)
            except (CronSimError, StopIteration) as error:
                raise ScheduleError(f"{cron!r} names no time after {after.isoformat()}: {error}") from error
        case ScheduleKind.INTERVAL:
            if not interval_seconds:  # pragma: no cover - the check refuses this at declaration time
                raise ScheduleError("an interval schedule has no interval")
            return after + timedelta(seconds=interval_seconds)
        case ScheduleKind.ONE_TIME:
            if run_at is None:  # pragma: no cover - the check refuses this at declaration time
                raise ScheduleError("a one-time schedule has no instant")
            return run_at if run_at > after else None


#: How many firings a preview answers with, which is what a dialog reads a clock by.
PREVIEW_FIRINGS: Final = 3


def preview_firings(
    *,
    cron: str | None = None,
    interval: str | None = None,
    at: str | None = None,
    timezone: str = "UTC",
    count: int = PREVIEW_FIRINGS,
    now: datetime | None = None,
) -> list[datetime]:
    """Walk the next firings of a clock nothing has declared yet, in the zone it declares.

    The three expressions arrive as the text they were written as, because a clock is read
    back while it is being typed: what does not parse raises the same ScheduleError declaring
    it would. A one-time clock answers the one moment it names, or nothing once it has passed.
    """
    request = _clock(cron=cron, interval=interval, at=at, timezone=timezone)
    check_schedule(request)
    moment = now or utcnow()
    firings: list[datetime] = []
    for _ in range(count):
        following = next_fire_after(
            kind=request.kind(),
            cron=request.cron,
            interval_seconds=int(request.interval.total_seconds()) if request.interval else None,
            run_at=request.at,
            timezone=request.timezone,
            after=moment,
        )
        if following is None:
            break
        firings.append(following)
        moment = following
    return firings


def _clock(*, cron: str | None, interval: str | None, at: str | None, timezone: str) -> ScheduleRequest:
    """Read three typed expressions as the request the schedule arithmetic takes."""
    return ScheduleRequest(
        code="preview",
        cron=cron or None,
        interval=_interval(interval),
        at=_moment(at),
        timezone=timezone,
    )


def _interval(text: str | None) -> timedelta | None:
    """Read an interval as the duration it is written as."""
    if not text:
        return None
    try:
        parsed = parse_duration(text)
        if not isinstance(parsed, timedelta):  # pragma: no cover - a string parses or raises
            raise DurationError(text)
        return refuse_negative(parsed)
    except ValueError as error:
        raise ScheduleError(str(error)) from error


def _moment(text: str | None) -> datetime | None:
    """Read a one-time clock as the instant it names."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError as error:
        raise ScheduleError(f"{text!r} is not a moment: write one as 2026-06-01T09:00:00Z") from error


def first_fire_at(request: ScheduleRequest, *, now: datetime | None = None) -> datetime | None:
    """Compute when a newly declared schedule fires for the first time."""
    moment = now or utcnow()
    return next_fire_after(
        kind=request.kind(),
        cron=request.cron,
        interval_seconds=int(request.interval.total_seconds()) if request.interval else None,
        run_at=request.at,
        timezone=request.timezone,
        after=moment,
    )


def next_fire_for(schedule: Schedule, after: datetime) -> datetime | None:
    """Compute a stored schedule's next firing strictly after an instant."""
    return next_fire_after(
        kind=schedule.kind,
        cron=schedule.cron,
        interval_seconds=schedule.interval_seconds,
        run_at=schedule.run_at,
        timezone=schedule.timezone,
        after=after,
    )


#: The smallest step there is, which is what makes an enumeration's lower bound inclusive:
#: the arithmetic only answers "strictly after", and an occurrence exactly on the bound counts.
RESOLUTION: Final = timedelta(microseconds=1)


def previous_fire_before(schedule: Schedule, before: datetime) -> datetime | None:
    """Compute the occurrence immediately before an instant, in the schedule's own timezone.

    Cron runs backwards through the same grid it runs forwards through, evaluated in the
    declared zone, so the interval between two firings is the wall-clock cadence rather than
    a fixed number of hours: a nightly schedule's window is 23 hours across a spring-forward
    morning and 25 across a fall-back one. An interval schedule steps back by its interval.
    A one-time schedule has no previous occurrence.
    """
    match schedule.kind:
        case ScheduleKind.CRON:
            if schedule.cron is None:  # pragma: no cover - the check refuses this at declaration time
                raise ScheduleError("a cron schedule has no expression")
            local = before.astimezone(resolve_zone(schedule.timezone))
            try:
                return next(CronSim(schedule.cron, local, reverse=True)).astimezone(UTC)
            except (CronSimError, StopIteration) as error:
                raise ScheduleError(f"{schedule.cron!r} names no time before {before.isoformat()}: {error}") from error
        case ScheduleKind.INTERVAL:
            if not schedule.interval_seconds:  # pragma: no cover - refused at declaration time
                raise ScheduleError("an interval schedule has no interval")
            return before - timedelta(seconds=schedule.interval_seconds)
        case ScheduleKind.ONE_TIME:
            return None


def window_for(schedule: Schedule, scheduled_for: datetime) -> RunWindow | None:
    """Derive the logical data interval a firing covers, or None when the clock defines none.

    The window ends at the firing's own due time and starts at the occurrence before it, so a
    run reads the interval that has just closed rather than the one it is inside. A one-time
    schedule has no cadence and therefore no window.
    """
    start = previous_fire_before(schedule, scheduled_for)
    if start is None or start >= scheduled_for:
        return None
    return RunWindow(start=start, end=scheduled_for)


def occurrences_between(schedule: Schedule, *, start: datetime, end: datetime) -> Iterator[datetime]:
    """Walk the firings a schedule's cadence puts inside ``[start, end)``, oldest first.

    An interval schedule has no absolute grid -- its arithmetic is purely relative -- so the
    caller's own lower bound anchors it. Cron has a grid, and the walk picks up whatever of it
    falls inside the interval, including an occurrence exactly on the lower bound.
    """
    if schedule.kind is ScheduleKind.INTERVAL:
        if not schedule.interval_seconds:  # pragma: no cover - refused at declaration time
            raise ScheduleError("an interval schedule has no interval")
        step = timedelta(seconds=schedule.interval_seconds)
        moment = start
        while moment < end:
            yield moment
            moment += step
        return
    moment = start - RESOLUTION
    while True:
        occurrence = next_fire_for(schedule, moment)
        if occurrence is None or occurrence >= end:
            return
        yield occurrence
        moment = occurrence


class Advance(BaseModel):
    """What a due schedule's clock does next, and whether this firing counted as a misfire."""

    model_config = ConfigDict(frozen=True)

    next_fire_at: datetime | None
    misfired: bool
    lateness: timedelta

    @property
    def exhausted(self) -> bool:
        """Report whether the clock has run out, which pauses a one-time schedule."""
        return self.next_fire_at is None


def advance_clock(schedule: Schedule, *, now: datetime, grace: timedelta) -> Advance:
    """Decide where a due schedule's clock lands next, applying the misfire policy.

    A firing later than the grace window fires once and computes the next firing from now,
    abandoning the missed slots. One inside the window advances from the slot it owed, so a
    cron schedule stays on its own grid rather than drifting by the length of the tick.
    """
    due = schedule.next_fire_at or now
    lateness = now - due
    misfired = lateness > grace
    return Advance(
        next_fire_at=next_fire_for(schedule, now if misfired else due),
        misfired=misfired,
        lateness=lateness,
    )


async def find_schedule(session: AsyncSession, pipeline_id: UUID, code: str) -> Schedule | None:
    """Find one schedule by code within its pipeline."""
    found = await session.execute(sa.select(Schedule).where(Schedule.pipeline_id == pipeline_id, Schedule.code == code))
    return found.scalar_one_or_none()


async def list_schedules(
    session: AsyncSession,
    pipeline_id: UUID | None = None,
    *,
    after: str | None = None,
    limit: int | None = None,
) -> list[Schedule]:
    """List schedules in code order, for one pipeline or across the instance."""
    statement = sa.select(Schedule).order_by(Schedule.pipeline_id, Schedule.code)
    if pipeline_id is not None:
        statement = statement.where(Schedule.pipeline_id == pipeline_id)
    if after is not None:
        statement = statement.where(Schedule.code > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


async def create_schedule(
    session: AsyncSession,
    pipeline: Pipeline,
    request: ScheduleRequest,
    *,
    now: datetime | None = None,
    paused: bool = False,
) -> Schedule:
    """Declare a schedule on a pipeline, with its first firing already computed.

    ``paused`` is a column on the row being inserted rather than a second write, so a
    schedule asked for paused is never live for the width of a transaction.
    """
    check_schedule(request)
    if await find_schedule(session, pipeline.id, request.code) is not None:
        raise DuplicateSchedule(pipeline.code, request.code)
    schedule = Schedule(
        pipeline_id=pipeline.id,
        code=request.code,
        name=request.name,
        description=request.description,
        kind=request.kind(),
        cron=request.cron,
        interval_seconds=int(request.interval.total_seconds()) if request.interval else None,
        run_at=request.at,
        timezone=request.timezone,
        params=dict(request.params),
        connection_pins=dict(request.connection_pins),
        log_levels=dict(request.log_levels) if request.log_levels else None,
        priority=request.priority,
        next_fire_at=first_fire_at(request, now=now),
        paused=paused,
    )
    session.add(schedule)
    await session.flush()
    _logger.info(
        "schedule created",
        pipeline=pipeline.code,
        schedule=schedule.code,
        kind=schedule.kind.value,
        next_fire_at=schedule.next_fire_at.isoformat() if schedule.next_fire_at else None,
        paused=schedule.paused,
    )
    return schedule


async def update_schedule(
    session: AsyncSession,
    schedule: Schedule,
    request: ScheduleRequest,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Redeclare a schedule's clock and parameters, recomputing when it next fires.

    Operational state is untouched: a paused schedule stays paused through an edit.
    """
    check_schedule(request)
    schedule.name = request.name
    schedule.description = request.description
    schedule.kind = request.kind()
    schedule.cron = request.cron
    schedule.interval_seconds = int(request.interval.total_seconds()) if request.interval else None
    schedule.run_at = request.at
    schedule.timezone = request.timezone
    schedule.params = dict(request.params)
    schedule.connection_pins = dict(request.connection_pins)
    schedule.log_levels = dict(request.log_levels) if request.log_levels else None
    schedule.priority = request.priority
    schedule.next_fire_at = first_fire_at(request, now=now)
    await session.flush()
    _logger.info("schedule updated", schedule=schedule.code, kind=schedule.kind.value)
    return schedule


async def set_paused(session: AsyncSession, schedule: Schedule, *, paused: bool) -> Schedule:
    """Pause or resume a schedule; resuming recomputes the next firing from now.

    Resuming without recomputing would fire once for every slot missed while paused.
    """
    schedule.paused = paused
    if not paused:
        schedule.next_fire_at = next_fire_for(schedule, utcnow())
    await session.flush()
    _logger.info("schedule paused" if paused else "schedule resumed", schedule=schedule.code)
    return schedule


async def delete_schedule(session: AsyncSession, schedule: Schedule) -> None:
    """Remove a schedule; its firing history goes with it."""
    code = schedule.code
    await session.delete(schedule)
    await session.flush()
    _logger.info("schedule deleted", schedule=code)


async def list_firings(
    session: AsyncSession,
    schedule_id: UUID,
    *,
    after: int | None = None,
    limit: int | None = None,
) -> list[ScheduleFiring]:
    """Read a schedule's recent firings, newest first."""
    statement = (
        sa.select(ScheduleFiring).where(ScheduleFiring.schedule_id == schedule_id).order_by(ScheduleFiring.id.desc())
    )
    if after is not None:
        statement = statement.where(ScheduleFiring.id < after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())
