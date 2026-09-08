"""Clock sensors: ``time.window`` waits for a window to open, ``time.sleep`` waits a duration."""

from datetime import UTC, date, datetime, time, timedelta
from typing import ClassVar, Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from dirigent_common import BlockModel, Duration
from dirigent_plugin import NotYet, Sensor, SensorSpec, StepContext

type DayName = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

#: Indexed with ``date.weekday()``, so the order is that function's and not a preference.
WEEKDAYS: Final[tuple[DayName, ...]] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

DEFAULT_TIMEZONE: Final = "UTC"

MAX_WAIT: Final = timedelta(hours=1)

MIN_WAIT: Final = timedelta(seconds=1)

SEARCH_DAYS: Final = 8

#: The shortest park a sleep asks for, so the last sliver of a wait is one poke and not many.
MIN_SLEEP_POLL: Final = timedelta(milliseconds=100)


class TimeWindowConfig(BlockModel):
    """The window a step may proceed in, in one named timezone."""

    after: time = time(0, 0)
    """The local time the window opens."""

    before: time = time(23, 59, 59)
    """The local time it closes; earlier than ``after`` means the window crosses midnight."""

    timezone: str = DEFAULT_TIMEZONE
    """The IANA zone the window is read in. A window without one is a window in someone's head."""

    days: list[DayName] = Field(default_factory=list["DayName"])
    """The days the window opens on; empty means every day."""

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        """Reject a zone this machine's database does not have, at validation and not at poke."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"{value!r} is not an IANA timezone name, such as 'Europe/Oslo' or 'UTC'") from error
        return value

    @model_validator(mode="after")
    def _check_window(self) -> "TimeWindowConfig":
        """Reject a window of zero width, which no clock is ever inside."""
        if self.after == self.before:
            raise ValueError(
                f"a window from {self.after} to {self.before} is empty; "
                f"omit the sensor rather than writing a window nothing falls in"
            )
        return self

    @property
    def zone(self) -> ZoneInfo:
        """The zone object the window is evaluated in."""
        return ZoneInfo(self.timezone)

    @property
    def crosses_midnight(self) -> bool:
        """Report whether this window opens on one day and closes on the next."""
        return self.after > self.before

    def opens_on(self, day: date) -> bool:
        """Report whether a window opens on a given date."""
        return not self.days or WEEKDAYS[day.weekday()] in self.days

    def opening(self, day: date) -> datetime:
        """The moment the window opens on a given date, in its own zone."""
        return datetime.combine(day, self.after, tzinfo=self.zone)


class TimeWindowOutput(BlockModel):
    """The observation that the clock is inside the window, passed downstream like any output."""

    entered_at: datetime
    """When the window this poke fell inside opened, not when the poke happened."""

    timezone: str


class TimeWindowSensor(Sensor[TimeWindowConfig, TimeWindowOutput]):
    """Waits until the local clock in a named timezone is inside a window."""

    spec = SensorSpec(
        id="time.window",
        summary="Wait until the local clock is inside a time window.",
        default_poll=timedelta(minutes=1),
        default_deadline=timedelta(hours=24),
    )
    config_model: ClassVar[type[BaseModel]] = TimeWindowConfig
    output_model: ClassVar[type[BaseModel]] = TimeWindowOutput

    async def poke(self, config: TimeWindowConfig, ctx: StepContext) -> TimeWindowOutput | NotYet:
        """Look at one clock once, and either proceed or say how long the wait is."""
        moment = now_in(config.zone)
        entered = entered_at(config, moment)
        if entered is not None:
            # The stream carries the time of every line, so a block repeating it says nothing
            # the reader cannot already see; the window it opened is in the output.
            ctx.log.info("the window is open", timezone=config.timezone)
            return TimeWindowOutput(entered_at=entered, timezone=config.timezone)
        wait = wait_for(config, moment)
        ctx.log.debug("the window is closed", wait_seconds=round(wait.total_seconds(), 1), timezone=config.timezone)
        return NotYet(next_poll_in=wait)


def now_in(zone: ZoneInfo) -> datetime:
    """Read the current moment in one zone."""
    return datetime.now(zone)


def entered_at(config: TimeWindowConfig, moment: datetime) -> datetime | None:
    """Return when the window the moment falls inside opened, or None when it is closed."""
    local = moment.astimezone(config.zone)
    today = local.date()
    clock = local.timetz().replace(tzinfo=None)
    if not config.crosses_midnight:
        if config.after <= clock < config.before and config.opens_on(today):
            return config.opening(today)
        return None
    if clock >= config.after and config.opens_on(today):
        return config.opening(today)
    yesterday = today - timedelta(days=1)
    if clock < config.before and config.opens_on(yesterday):
        return config.opening(yesterday)
    return None


def next_opening(config: TimeWindowConfig, moment: datetime) -> datetime | None:
    """Find the next moment the window opens, searching a little over a week ahead."""
    local = moment.astimezone(config.zone)
    for offset in range(SEARCH_DAYS):
        day = local.date() + timedelta(days=offset)
        if not config.opens_on(day):
            continue
        opening = config.opening(day)
        if opening > local:
            return opening
    return None  # pragma: no cover - a non-empty day set always opens within eight days


def wait_for(config: TimeWindowConfig, moment: datetime) -> timedelta:
    """Say how long to park a closed window, bounded at both ends."""
    opening = next_opening(config, moment)
    if opening is None:  # pragma: no cover - next_opening always finds one
        return MAX_WAIT
    return max(MIN_WAIT, min(opening - moment.astimezone(config.zone), MAX_WAIT))


class TimeSleepConfig(BlockModel):
    """How long the wait lasts."""

    wait_for: Duration = Field(alias="for")
    """How long to wait, measured from when the attempt started.

    The step's deadline still ends the wait, so a `for` longer than a day needs a `deadline`
    beside it: the sensor default is 24 hours."""


class TimeSleepOutput(BlockModel):
    """What the wait amounted to, passed downstream like any other output."""

    started_at: datetime
    """When the wait began, which is when the attempt started and not when a poke ran."""

    waited_ms: int
    """How long the wait actually lasted, which is the configured duration plus poll latency."""


class TimeSleepSensor(Sensor[TimeSleepConfig, TimeSleepOutput]):
    """Waits a fixed duration without occupying a worker.

    Each poke reads the clock and returns, so an hour's wait is a parked row rather than an
    hour of a worker's concurrency. This is the block to reach for instead of `shell.run`
    with `sleep`, which asks an instance to allowlist arbitrary code execution in order to do
    something harmless.

    The deadline is anchored on the attempt's start, so a worker restarting mid-wait resumes
    the same wait instead of starting the clock again.
    """

    spec = SensorSpec(
        id="time.sleep",
        summary="Wait a fixed duration.",
        default_poll=timedelta(seconds=1),
        default_deadline=timedelta(hours=24),
    )
    config_model: ClassVar[type[BaseModel]] = TimeSleepConfig
    output_model: ClassVar[type[BaseModel]] = TimeSleepOutput

    async def poke(self, config: TimeSleepConfig, ctx: StepContext) -> TimeSleepOutput | NotYet:
        """Read the clock once: finish, or say how much of the wait is left."""
        moment = datetime.now(UTC)
        remaining = ctx.started_at + config.wait_for - moment
        if remaining > timedelta(0):
            ctx.log.debug(
                "still waiting",
                waited_ms=milliseconds(moment - ctx.started_at),
                remaining_ms=milliseconds(remaining),
            )
            return NotYet(next_poll_in=max(remaining, MIN_SLEEP_POLL))
        waited = moment - ctx.started_at
        ctx.log.info("the wait is over", waited_ms=milliseconds(waited))
        return TimeSleepOutput(started_at=ctx.started_at, waited_ms=milliseconds(waited))


def milliseconds(value: timedelta) -> int:
    """Render a duration as the whole milliseconds emitted data measures timings in."""
    return round(value.total_seconds() * 1000)
