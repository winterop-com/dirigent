"""Where a run's wall clock went: queued, running and waiting, per attempt and per step.

Every number here is read off the attempt rows the server already keeps, so a profile says
what the timestamps prove and nothing else. An attempt spends its life in three states a
reader can tell apart. It is QUEUED once its upstream is done and it is claimable -- which
is what ``available_at`` marks -- until a worker takes it up, so queued time is workers
being busy and nothing else. It is WAITING while the engine deliberately parks it: a
retry's backoff before it may be claimed at all, and the interval between a sensor's
probes. It is RUNNING while a call is in flight. An attempt that never started spent no
time of its own: what it sat through belongs to the steps above it.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from dirigent_client.enums import AttemptStatus
from dirigent_client.schemas import AttemptOut, DagNode, RunDetail

#: What an unfinished step sorts as, so an aware moment is never compared with a naive one.
UNSETTLED: Final = datetime.min.replace(tzinfo=UTC)

#: How often an attempt has to have parked before the gap between its probes is a cadence
#: rather than one interval that happened once.
MIN_PROBES: Final = 2

#: Waiting this many times the work it waited on is a probe cadence set for a slower world.
IDLE_PROBE_RATIO: Final = 10

#: A deadline this many times the wait it needed was guessed rather than measured.
SLACK_DEADLINE_RATIO: Final = 20

#: How many elements a fan-out needs before running them one after another is worth saying.
SERIAL_FAN_OUT_MIN: Final = 2

#: What an attempt settled as when nothing of its own ended it: the deadline or a cancel
#: reached it while it was parked, so its last probe is not what its final span measures.
PARKED_TO_THE_END: Final = frozenset({AttemptStatus.SKIPPED, AttemptStatus.CANCELLED})


class AttemptTiming(BaseModel):
    """Where one attempt's wall clock went."""

    model_config = ConfigDict(frozen=True)

    queued_ms: int = 0
    """From becoming claimable until a worker took it up, which is workers being busy."""

    running_ms: int = 0
    """The call itself, which on an attempt that parked is the probe that settled it."""

    waiting_ms: int = 0
    """Parked on purpose: a retry's backoff, and the intervals between a sensor's probes."""

    @property
    def total_ms(self) -> int:
        """Add the three up, which is the attempt's own wall clock."""
        return self.queued_ms + self.running_ms + self.waiting_ms


class StepTiming(BaseModel):
    """Where one step's wall clock went, and how many tries it took."""

    model_config = ConfigDict(frozen=True)

    step: str
    block: str
    attempts: int = 0
    queued_ms: int = 0
    running_ms: int = 0
    waiting_ms: int = 0
    finished_at: datetime | None = None

    @property
    def total_ms(self) -> int:
        """Add the three up, which is what this step put on the run's clock."""
        return self.queued_ms + self.running_ms + self.waiting_ms


class ProfileWarning(BaseModel):
    """One cause the timestamps prove, said as the sentence a reader acts on."""

    model_config = ConfigDict(frozen=True)

    step: str
    cause: str
    message: str


class RunProfile(BaseModel):
    """A run broken into where its wall clock went, along the chain that decided it."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    pipeline: str
    status: str
    duration_ms: int | None = None
    critical_path: list[str] = Field(default_factory=list[str])
    queued_ms: int = 0
    running_ms: int = 0
    waiting_ms: int = 0
    steps: list[StepTiming] = Field(default_factory=list[StepTiming])
    warnings: list[ProfileWarning] = Field(default_factory=list[ProfileWarning])


def _ms(start: datetime | None, end: datetime | None) -> int:
    """Measure one span in milliseconds, and call anything that runs backwards nothing."""
    if start is None or end is None:
        return 0
    return max(0, round((end - start).total_seconds() * 1000))


def attempt_timing(attempt: AttemptOut, *, at: datetime) -> AttemptTiming:
    """Split one attempt's wall clock into queued, running and waiting.

    ``available_at`` is when the attempt became claimable, so a retry's backoff is the span
    before it and the queue is the span after it. An attempt that parked keeps its first
    ``started_at`` across every probe, and ``heartbeat_at`` is when the last probe took it
    up: everything before that is waiting, and the probe that settled it is running.
    """
    ready = attempt.available_at or attempt.created_at
    # A first attempt is made claimable when the steps above it finish, and that span is
    # their time rather than its own; only a retry is written down and then held back.
    backoff_ms = _ms(attempt.created_at, attempt.available_at) if attempt.attempt > 1 else 0
    started = attempt.started_at
    if started is None:
        if attempt.status is not AttemptStatus.QUEUED:
            return AttemptTiming()
        return AttemptTiming(queued_ms=_ms(ready, at), waiting_ms=backoff_ms)
    queued_ms = _ms(ready, started)
    if attempt.finished_at is None and attempt.status is AttemptStatus.WAITING:
        return AttemptTiming(queued_ms=queued_ms, waiting_ms=backoff_ms + _ms(started, at))
    end = attempt.finished_at or at
    heartbeat = attempt.heartbeat_at
    parked = attempt.poke_count >= 1 and heartbeat is not None and started <= heartbeat <= end
    if parked and attempt.status in PARKED_TO_THE_END:
        # A deadline or a cancel reached the attempt where it lay, so no probe was running
        # when it settled and the whole span from its first probe on was a wait.
        return AttemptTiming(queued_ms=queued_ms, waiting_ms=backoff_ms + _ms(started, end))
    boundary = heartbeat if parked else started
    return AttemptTiming(
        queued_ms=queued_ms,
        waiting_ms=backoff_ms + _ms(started, boundary),
        running_ms=_ms(boundary, end),
    )


def _settled_at(attempt: AttemptOut) -> datetime | None:
    """Say when this attempt last moved, which is what orders one step against another."""
    return attempt.finished_at or attempt.started_at


def _lineage(attempts: Sequence[AttemptOut]) -> list[AttemptOut]:
    """Take the attempts that decided when a step finished.

    A retry runs after the attempt it retries, so one element's tries add up to wall clock;
    a fan-out's elements run beside each other, so the element that finished last speaks for
    the step and the others are not on its clock twice.
    """
    if not attempts:
        return []
    last = max(attempts, key=lambda row: (_settled_at(row) is not None, _settled_at(row) or UNSETTLED))
    return [row for row in attempts if row.run_item_id == last.run_item_id]


def step_timing(node: DagNode, attempts: Sequence[AttemptOut], *, at: datetime) -> StepTiming:
    """Fold one step's attempts into what the step put on the run's clock."""
    lineage = _lineage(attempts)
    timings = [attempt_timing(row, at=at) for row in lineage]
    finished = [row.finished_at for row in attempts if row.finished_at is not None]
    return StepTiming(
        step=node.code,
        block=node.block,
        attempts=len(attempts),
        queued_ms=sum(one.queued_ms for one in timings),
        running_ms=sum(one.running_ms for one in timings),
        waiting_ms=sum(one.waiting_ms for one in timings),
        finished_at=max(finished) if finished else None,
    )


def by_step(attempts: Iterable[AttemptOut]) -> dict[str, list[AttemptOut]]:
    """Group a run's attempts by the step they are tries of."""
    grouped: dict[str, list[AttemptOut]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.step_name, []).append(attempt)
    return grouped


def critical_path(nodes: Sequence[DagNode], timings: Mapping[str, StepTiming]) -> list[str]:
    """Walk back from the step that finished last through whichever upstream held it up.

    A step cannot start before its last upstream finished, so the chain of last-finishing
    dependencies is the one that decided the run's wall clock.
    """
    ran = {node.code: node for node in nodes if node.code in timings}
    if not ran:
        return []
    position = {node.code: index for index, node in enumerate(nodes)}

    def finished(code: str) -> tuple[datetime, int]:
        # Two steps can settle in the same millisecond, and the document's order is the only
        # thing left that says which of them the other one waited for.
        return timings[code].finished_at or UNSETTLED, position[code]

    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = max(ran, key=finished)
    while current is not None and current not in seen:
        chain.append(current)
        seen.add(current)
        upstream = [code for code in ran[current].depends_on if code in ran and code not in seen]
        current = max(upstream, key=finished) if upstream else None
    return list(reversed(chain))


def _warnings(
    nodes: Sequence[DagNode], grouped: Mapping[str, list[AttemptOut]], *, at: datetime
) -> list[ProfileWarning]:
    """Name the causes the timestamps prove, one sentence each."""
    found: list[ProfileWarning] = []
    for node in nodes:
        attempts = grouped.get(node.code, [])
        for attempt in attempts:
            found.extend(_probe_warnings(node.code, attempt, at=at))
        serialised = _serial_fan_out(node, attempts)
        if serialised is not None:
            found.append(serialised)
    return found


def _probe_warnings(step: str, attempt: AttemptOut, *, at: datetime) -> list[ProfileWarning]:
    """Say when a probe cadence outlasted the work, and when a deadline outlasted the wait."""
    if attempt.poke_count < MIN_PROBES:
        return []
    timing = attempt_timing(attempt, at=at)
    found: list[ProfileWarning] = []
    # The parked span alone, so a retry's backoff is not read as one of the probe intervals.
    parked_ms = _ms(attempt.started_at, attempt.heartbeat_at)
    cadence = round(parked_ms / attempt.poke_count)
    # Only a probe that was measured proves anything: an attempt the deadline ended while it
    # lay parked has no work to compare its cadence against.
    if timing.running_ms > 0 and parked_ms > IDLE_PROBE_RATIO * timing.running_ms:
        found.append(
            ProfileWarning(
                step=step,
                cause="probe-cadence",
                message=(
                    f"{step} spent {_seconds(parked_ms)} parked between {attempt.poke_count} probes "
                    f"and {_seconds(timing.running_ms)} probing, which is a probe about every "
                    f"{_seconds(cadence)} for work that answered in less than one interval."
                ),
            )
        )
    waited = parked_ms + timing.running_ms
    budget = _ms(attempt.started_at, attempt.deadline_at)
    if budget > SLACK_DEADLINE_RATIO * max(waited, 1):
        found.append(
            ProfileWarning(
                step=step,
                cause="slack-deadline",
                message=(
                    f"{step} settled after {_seconds(waited)} of waiting under a deadline of "
                    f"{_seconds(budget)}, so its budget is {budget // max(waited, 1)} times the wait it needed."
                ),
            )
        )
    return found


def _serial_fan_out(node: DagNode, attempts: Sequence[AttemptOut]) -> ProfileWarning | None:
    """Say when a fan-out's elements ran one after another rather than beside each other."""
    if not node.fan_out:
        return None
    windows = sorted(
        (row.started_at, row.finished_at)
        for row in attempts
        if row.run_item_id is not None and row.started_at is not None and row.finished_at is not None
    )
    if len(windows) < SERIAL_FAN_OUT_MIN:
        return None
    if any(later < earlier_end for (_, earlier_end), (later, _) in zip(windows, windows[1:], strict=False)):
        return None
    return ProfileWarning(
        step=node.code,
        cause="serial-fan-out",
        message=(
            f"the {len(windows)} elements of {node.code} ran one after another rather than beside each other, "
            f"which is a concurrency limit or a single worker turning a fan-out back into a queue."
        ),
    )


def _seconds(value: int) -> str:
    """Spell a measured span the way a sentence reads it."""
    return f"{value / 1000:.1f}s"


def profile(detail: RunDetail, attempts: Sequence[AttemptOut], *, at: datetime) -> RunProfile:
    """Break a run into where its wall clock went, along the chain that decided it."""
    grouped = by_step(attempts)
    timings = {
        node.code: step_timing(node, grouped[node.code], at=at) for node in detail.dag.nodes if node.code in grouped
    }
    path = critical_path(detail.dag.nodes, timings)
    on_path = [timings[code] for code in path]
    run = detail.run
    return RunProfile(
        run_id=str(run.id),
        pipeline=run.pipeline,
        status=run.status.value,
        duration_ms=_ms(run.started_at, run.finished_at) if run.started_at and run.finished_at else None,
        critical_path=path,
        queued_ms=sum(one.queued_ms for one in on_path),
        running_ms=sum(one.running_ms for one in on_path),
        waiting_ms=sum(one.waiting_ms for one in on_path),
        steps=on_path,
        warnings=_warnings(detail.dag.nodes, grouped, at=at),
    )
