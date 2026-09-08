"""Tests for the clock sensors: the window arithmetic, and the wait a sleep parks for."""

from datetime import UTC, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from dirigent_blocks.clock import (
    MAX_WAIT,
    MIN_SLEEP_POLL,
    MIN_WAIT,
    TimeSleepConfig,
    TimeSleepOutput,
    TimeSleepSensor,
    TimeWindowConfig,
    TimeWindowOutput,
    TimeWindowSensor,
    entered_at,
    next_opening,
    wait_for,
)
from dirigent_plugin import NotYet
from dirigent_testing import FakeContext

OSLO = "Europe/Oslo"


def at(text: str, zone: str = "UTC") -> datetime:
    """Read a local wall-clock moment in one zone, which is how a window is written."""
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(zone))


def freeze(monkeypatch: pytest.MonkeyPatch, clock: str) -> None:
    """Hold the sensor's one reading of the clock still at a wall-clock moment."""

    def reading(zone: ZoneInfo) -> datetime:
        return at(clock).astimezone(zone)

    monkeypatch.setattr("dirigent_blocks.clock.now_in", reading)


# -- the config ------------------------------------------------------------------


def test_the_default_window_is_the_whole_day_in_utc() -> None:
    config = TimeWindowConfig()
    assert config.timezone == "UTC"
    assert config.days == []
    assert entered_at(config, datetime(2026, 8, 29, 3, 0, tzinfo=UTC)) is not None


def test_a_timezone_that_is_not_iana_is_refused_at_validation() -> None:
    with pytest.raises(ValidationError, match="not an IANA timezone"):
        TimeWindowConfig(timezone="CEST")
    assert TimeWindowConfig(timezone=OSLO).zone == ZoneInfo(OSLO)


def test_a_window_of_zero_width_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty"):
        TimeWindowConfig(after=time(6, 0), before=time(6, 0))


# -- an ordinary window ----------------------------------------------------------


@pytest.mark.parametrize(
    ("clock", "inside"),
    [
        ("2026-08-29T05:59", False),
        ("2026-08-29T06:00", True),
        ("2026-08-29T12:00", True),
        ("2026-08-29T17:59:59", True),
        ("2026-08-29T18:00", False),
        ("2026-08-29T23:00", False),
    ],
)
def test_a_daytime_window_is_half_open_from_after_to_before(clock: str, inside: bool) -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert (entered_at(config, at(clock)) is not None) is inside


def test_entering_reports_when_the_window_opened_not_when_it_was_observed() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert entered_at(config, at("2026-08-29T14:30")) == at("2026-08-29T06:00")


def test_a_window_is_read_in_its_own_zone_and_not_the_workers() -> None:
    config = TimeWindowConfig(after=time(9, 0), before=time(17, 0), timezone=OSLO)
    # 08:00 UTC is 10:00 in Oslo in August, which is inside; 06:00 UTC is 08:00, which is not.
    assert entered_at(config, datetime(2026, 8, 29, 8, 0, tzinfo=UTC)) is not None
    assert entered_at(config, datetime(2026, 8, 29, 6, 0, tzinfo=UTC)) is None


# -- crossing midnight -----------------------------------------------------------


@pytest.mark.parametrize(
    ("clock", "inside"),
    [
        ("2026-08-29T21:59", False),
        ("2026-08-29T22:00", True),
        ("2026-08-29T23:59", True),
        ("2026-08-30T00:30", True),
        ("2026-08-30T03:59", True),
        ("2026-08-30T04:00", False),
        ("2026-08-30T12:00", False),
    ],
)
def test_a_night_window_is_one_window_and_not_an_empty_intersection(clock: str, inside: bool) -> None:
    config = TimeWindowConfig(after=time(22, 0), before=time(4, 0))
    assert config.crosses_midnight
    assert (entered_at(config, at(clock)) is not None) is inside


def test_the_small_hours_of_a_night_window_report_the_previous_evening() -> None:
    config = TimeWindowConfig(after=time(22, 0), before=time(4, 0))
    assert entered_at(config, at("2026-08-30T01:00")) == at("2026-08-29T22:00")


# -- the day filter --------------------------------------------------------------


def test_a_day_set_closes_the_window_on_every_other_day() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0), days=["sat", "sun"])
    assert entered_at(config, at("2026-08-29T12:00")) is not None, "2026-08-29 is a Saturday"
    assert entered_at(config, at("2026-08-31T12:00")) is None, "2026-08-31 is a Monday"


def test_a_night_window_is_named_by_the_day_it_opens_on() -> None:
    config = TimeWindowConfig(after=time(22, 0), before=time(4, 0), days=["fri"])
    assert entered_at(config, at("2026-08-28T23:00")) is not None, "Friday evening"
    assert entered_at(config, at("2026-08-29T02:00")) is not None, "Saturday morning, opened Friday"
    assert entered_at(config, at("2026-08-29T23:00")) is None, "Saturday evening opens nothing"


# -- the wait --------------------------------------------------------------------


def test_the_next_opening_is_today_when_the_window_has_not_opened_yet() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert next_opening(config, at("2026-08-29T03:00")) == at("2026-08-29T06:00")


def test_the_next_opening_is_tomorrow_once_today_is_over() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert next_opening(config, at("2026-08-29T19:00")) == at("2026-08-30T06:00")


def test_the_next_opening_skips_the_days_the_window_does_not_open_on() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0), days=["mon"])
    assert next_opening(config, at("2026-08-29T12:00")) == at("2026-08-31T06:00"), "Saturday waits for Monday"


def test_a_closed_window_waits_no_longer_than_an_hour() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert wait_for(config, at("2026-08-29T19:00")) == MAX_WAIT


def test_a_window_about_to_open_waits_exactly_that_long() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert wait_for(config, at("2026-08-29T05:30")) == timedelta(minutes=30)


def test_a_window_opening_this_instant_still_parks_briefly_rather_than_spinning() -> None:
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))
    assert wait_for(config, at("2026-08-29T05:59:59.9")) == MIN_WAIT


# -- the sensor ------------------------------------------------------------------


async def test_an_open_window_lets_the_step_proceed(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    freeze(monkeypatch, "2026-08-29T12:00")
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))

    observed = await TimeWindowSensor().poke(config, ctx.as_context())

    assert isinstance(observed, TimeWindowOutput)
    assert observed.entered_at == at("2026-08-29T06:00")
    assert observed.timezone == "UTC"
    assert "the window is open" in ctx.log.messages()


async def test_a_closed_window_is_not_yet_and_says_how_long(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    freeze(monkeypatch, "2026-08-29T05:00")
    config = TimeWindowConfig(after=time(6, 0), before=time(18, 0))

    observed = await TimeWindowSensor().poke(config, ctx.as_context())

    assert isinstance(observed, NotYet)
    assert observed.next_poll_in == timedelta(hours=1)
    assert "the window is closed" in ctx.log.messages()


async def test_the_default_window_is_always_open(ctx: FakeContext) -> None:
    observed = await TimeWindowSensor().poke(TimeWindowConfig(), ctx.as_context())
    assert isinstance(observed, TimeWindowOutput)


def test_the_sensor_declares_the_cadence_and_deadline_a_daily_window_needs() -> None:
    spec = TimeWindowSensor().spec
    assert spec.id == "time.window"
    assert spec.default_deadline == timedelta(hours=24)


def test_the_clock_is_read_in_the_configured_zone() -> None:
    from dirigent_blocks.clock import now_in

    assert now_in(ZoneInfo(OSLO)).tzinfo == ZoneInfo(OSLO)


async def test_a_sleep_that_has_not_run_its_course_parks_for_what_is_left(ctx: FakeContext) -> None:
    """The wait is a parked row: the poke returns at once and says when to come back."""
    observed = await TimeSleepSensor().poke(TimeSleepConfig.model_validate({"for": "5m"}), ctx.as_context())
    assert isinstance(observed, NotYet)
    assert observed.next_poll_in is not None
    assert timedelta(minutes=4) < observed.next_poll_in <= timedelta(minutes=5)
    assert "still waiting" in ctx.log.messages()


async def test_a_sleep_whose_duration_has_passed_reports_what_it_waited(ctx: FakeContext) -> None:
    ctx.started_at = datetime.now(UTC) - timedelta(seconds=30)
    observed = await TimeSleepSensor().poke(TimeSleepConfig.model_validate({"for": "5s"}), ctx.as_context())
    assert isinstance(observed, TimeSleepOutput)
    assert observed.started_at == ctx.started_at
    assert observed.waited_ms >= 30_000
    assert "the wait is over" in ctx.log.messages()


async def test_the_wait_is_measured_from_the_attempt_and_not_from_the_poke(ctx: FakeContext) -> None:
    """A worker restarting mid-wait resumes the wait rather than starting it again."""
    ctx.started_at = datetime.now(UTC) - timedelta(seconds=8)
    config = TimeSleepConfig.model_validate({"for": "10s"})
    observed = await TimeSleepSensor().poke(config, ctx.as_context())
    assert isinstance(observed, NotYet)
    assert observed.next_poll_in is not None
    assert observed.next_poll_in <= timedelta(seconds=2), "only the remainder is left to wait"


async def test_the_last_sliver_of_a_wait_is_one_poke_and_not_a_flurry(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    moment = datetime.now(UTC)

    class Held(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "Held":
            return cls.fromtimestamp(moment.timestamp(), tz or UTC)

    monkeypatch.setattr("dirigent_blocks.clock.datetime", Held)
    ctx.started_at = moment - timedelta(seconds=5) + timedelta(milliseconds=1)
    observed = await TimeSleepSensor().poke(TimeSleepConfig.model_validate({"for": "5s"}), ctx.as_context())
    assert isinstance(observed, NotYet)
    assert observed.next_poll_in == MIN_SLEEP_POLL


def test_a_sleep_is_configured_with_a_humane_duration() -> None:
    assert TimeSleepConfig.model_validate({"for": "1h30m"}).wait_for == timedelta(minutes=90)
    assert TimeSleepConfig.model_validate({"for": 5}).wait_for == timedelta(seconds=5)
    with pytest.raises(ValidationError):
        TimeSleepConfig.model_validate({"for": "a while"})
    with pytest.raises(ValidationError):
        TimeSleepConfig.model_validate({})


def test_the_sleep_sensor_declares_a_cadence_it_almost_never_uses() -> None:
    """Every poke names its own next poll, so the default is only the fallback."""
    spec = TimeSleepSensor().spec
    assert spec.id == "time.sleep"
    assert spec.default_poll == timedelta(seconds=1)
