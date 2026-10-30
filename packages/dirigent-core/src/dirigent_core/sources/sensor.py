"""The sensor kind: a sensor block poked outside any run, each success becoming one input.

A worker pokes the sensor on the source's cadence, or sooner when the sensor asks. A poke that
answers ``NotYet`` keeps the cursor it returns and starts no run; one that succeeds becomes a
run whose source node holds the sensor's output, and the next wait starts from where
:meth:`Sensor.resume_cursor` says, polled again at once. Only a sensor that declares
``source`` in its spec may be poked this way: it reads nothing of a run but its cursor and
when the wait began.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dirigent_common import Duration, Issue, JsonMap, validation_issues
from dirigent_core.messages import SENSOR_NOT_A_SOURCE, SENSOR_UNKNOWN
from dirigent_plugin import StepContext
from dirigent_plugin.blocks import NotYet, Sensor
from dirigent_plugin.sources import PollContext, Polled, PolledSource, SourceHosting, SourceSpec

type AnySensor = Sensor[Any, Any]

#: The cursor's fields: the sensor's own cursor, and when the wait it belongs to began.
CURSOR: str = "cursor"
SINCE: str = "since"


class SensorConfig(BaseModel):
    """A sensor source: which sensor, configured how, and how often it is poked."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    block: str = Field(min_length=1)
    """The sensor's block id, such as ``kafka.consume``."""

    config: JsonMap = Field(default_factory=dict)
    """The sensor's own config, as a step running it would write it."""

    poll: Duration | None = None
    """How long a worker waits between two pokes, or the sensor's own default."""

    max_in_flight: int | None = Field(default=None, ge=1)
    """How many unsettled runs from this source may exist before the next poke waits for one to settle."""


class SensorInput(BaseModel):
    """What a sensor succeeded with, which is the sensor's own output."""

    model_config = ConfigDict(frozen=True, extra="allow")


class SensorContexts(Protocol):
    """What a poll offers the sensor kind beyond a polled kind's own context."""

    def sensor_context(self, *, block: str, cursor: JsonMap | None, started_at: datetime) -> StepContext:
        """A context for one poke outside any run."""
        ...


class SensorSource(PolledSource[SensorConfig, BaseModel]):
    """A sensor poked outside any run."""

    spec = SourceSpec(
        kind="sensor",
        summary="A sensor poked outside any run, each success starting one",
        hosting=SourceHosting.POLLED,
    )
    config_model = SensorConfig
    output_model = SensorInput

    def __init__(self, sensors: Mapping[str, AnySensor] | None = None) -> None:
        """Hold the sensors this instance knows, or none for a check that has no host."""
        self._sensors = sensors

    def check_config(self, config: SensorConfig) -> list[Issue]:
        """Refuse a block that is no sensor a source may poke, and a config the sensor refuses."""
        if self._sensors is None:
            return []
        sensor = self._sensors.get(config.block)
        if sensor is None or not sensor.spec.source:
            message = SENSOR_UNKNOWN if sensor is None else SENSOR_NOT_A_SOURCE
            return [Issue.of(message, location="block", block=repr(config.block), known=self._known())]
        try:
            validated = sensor.config_model.model_validate(config.config)
        except ValidationError as error:
            issues = validation_issues(cast("list[Mapping[str, Any]]", error.errors()))
        else:
            issues = sensor.check_config(validated)
        return [
            issue.model_copy(update={"location": "config" + (f".{issue.location}" if issue.location else "")})
            for issue in issues
        ]

    def poll_every(self, config: SensorConfig) -> timedelta:
        """Poke as often as the source says, or as the sensor itself defaults to."""
        if config.poll is not None:
            return config.poll
        sensor = self._sensor(config)
        return sensor.spec.default_poll

    def max_in_flight(self, config: SensorConfig) -> int | None:
        """Bound the unsettled runs the way the source declares."""
        return config.max_in_flight

    def cursor_key(self, config: SensorConfig) -> JsonMap | None:
        """Keep the cursor for as long as the source pokes the same sensor, configured the same way."""
        return {"block": config.block, "config": config.config}

    def summary_of(self, config: SensorConfig) -> str | None:
        """Name the sensor the source pokes."""
        return config.block

    def complete(self, config: SensorConfig, given: JsonMap, *, received_at: datetime) -> BaseModel:
        """Make a hand run's input whole: what the sensor would have succeeded with."""
        sensor = self._sensors.get(config.block) if self._sensors is not None else None
        model = sensor.output_model if sensor is not None else SensorInput
        return model.model_validate(given)

    async def poll(
        self, config: SensorConfig, cursor: JsonMap | None, ctx: PollContext, limit: int
    ) -> Polled[BaseModel]:
        """Poke the sensor once, and hand over what it succeeded with."""
        sensor = self._sensor(config)
        now = datetime.now(UTC)
        held, since = _read(cursor, now)
        poke = cast("SensorContexts", ctx).sensor_context(block=config.block, cursor=held, started_at=since)
        answer = await sensor.poke(sensor.config_model.model_validate(config.config), poke)
        if isinstance(answer, NotYet):
            kept = answer.cursor if answer.cursor is not None else held
            return Polled(inputs=[], cursor=_write(kept, since), next_poll_in=answer.next_poll_in)
        ctx.log.info("the sensor succeeded", block=config.block)
        return Polled(inputs=[answer], cursor=_write(sensor.resume_cursor(answer), now), next_poll_in=timedelta(0))

    def _sensor(self, config: SensorConfig) -> AnySensor:
        """The sensor the source pokes, which apply has already checked is one a source may poke."""
        sensor = self._sensors.get(config.block) if self._sensors is not None else None
        if sensor is None or not sensor.spec.source:
            raise LookupError(SENSOR_NOT_A_SOURCE.render(block=repr(config.block), known=self._known()))
        return sensor

    def _known(self) -> str:
        """Name the sensors a source may poke."""
        known = sorted(code for code, sensor in (self._sensors or {}).items() if sensor.spec.source)
        return ", ".join(known) or "none are installed"


def _read(cursor: JsonMap | None, now: datetime) -> tuple[JsonMap | None, datetime]:
    """Read the sensor's own cursor and when its wait began, which is now for a source never poked."""
    held = (cursor or {}).get(CURSOR)
    began = (cursor or {}).get(SINCE)
    since = now
    if isinstance(began, str):
        try:
            since = datetime.fromisoformat(began)
        except ValueError:
            since = now
    return (cast("JsonMap", held) if isinstance(held, dict) else None), since


def _write(held: JsonMap | None, since: datetime) -> JsonMap:
    """Write the sensor's own cursor and when its wait began."""
    return {CURSOR: held, SINCE: since.isoformat()}
