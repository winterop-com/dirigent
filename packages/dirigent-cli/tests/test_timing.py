"""Where a run's wall clock went, computed off the attempt rows and nothing else."""

import uuid
from datetime import UTC, datetime, timedelta

from dirigent_cli.timing import attempt_timing, by_step, critical_path, profile, step_timing
from dirigent_client import AttemptKind, AttemptStatus, DagNode, DagView, RunDetail, RunOut, RunStatus, TriggerKind
from dirigent_client.schemas import AttemptOut

START = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    """A moment this many seconds into the run."""
    return START + timedelta(seconds=seconds)


def attempt(
    step: str = "one",
    *,
    created: float = 0,
    started: float | None = None,
    finished: float | None = None,
    heartbeat: float | None = None,
    deadline: float | None = None,
    pokes: int = 0,
    item: uuid.UUID | None = None,
    number: int = 1,
    status: AttemptStatus = AttemptStatus.SUCCEEDED,
) -> AttemptOut:
    """One attempt, spelled as the moments the engine writes down."""
    return AttemptOut(
        id=uuid.uuid4(),
        step_name=step,
        block_id="shell.run",
        attempt=number,
        kind=AttemptKind.AUTOMATIC,
        status=status,
        run_item_id=item,
        poke_count=pokes,
        created_at=at(created),
        started_at=None if started is None else at(started),
        finished_at=None if finished is None else at(finished),
        heartbeat_at=None if heartbeat is None else at(heartbeat),
        deadline_at=None if deadline is None else at(deadline),
    )


def node(code: str, *, after: list[str] | None = None, fan_out: bool = False, attempts: int = 1) -> DagNode:
    """One node of the run's graph."""
    return DagNode(
        code=code,
        block="shell.run",
        outcome="succeeded",
        depends_on=after or [],
        rule="all_succeeded",
        fan_out=fan_out,
        attempts=attempts,
    )


def detail_of(*nodes: DagNode) -> RunDetail:
    """A finished run whose graph is these nodes."""
    return RunDetail(
        run=RunOut(
            id=uuid.uuid4(),
            pipeline="demo",
            pipeline_version=1,
            status=RunStatus.SUCCEEDED,
            triggered_by_kind=TriggerKind.ADHOC,
            started_at=START,
            finished_at=at(100),
            created_at=START,
        ),
        dag=DagView(nodes=list(nodes)),
    )


def test_an_attempt_that_waited_for_a_worker_splits_queued_from_running() -> None:
    timing = attempt_timing(attempt(created=0, started=4, finished=10), at=at(10))
    assert (timing.queued_ms, timing.running_ms, timing.waiting_ms) == (4000, 6000, 0)
    assert timing.total_ms == 10_000


def test_a_retrys_backoff_is_waiting_and_only_the_rest_is_queued() -> None:
    """A backoff is the engine parking the attempt; the queue is what came after it."""
    backed_off = attempt(created=0, started=30, finished=31, number=2).model_copy(update={"available_at": at(29)})
    timing = attempt_timing(backed_off, at=at(31))
    assert (timing.waiting_ms, timing.queued_ms, timing.running_ms) == (29_000, 1000, 1000)
    assert timing.total_ms == 31_000, "the three still add up to the attempt's own wall clock"


def test_a_first_attempt_held_back_for_its_upstream_counts_none_of_that_as_its_own() -> None:
    """A first attempt becomes claimable when the steps above it finish, and that is their time."""
    waited_for = attempt(created=0, started=20, finished=21).model_copy(update={"available_at": at(19)})
    timing = attempt_timing(waited_for, at=at(21))
    assert (timing.waiting_ms, timing.queued_ms, timing.running_ms) == (0, 1000, 1000)


def test_a_step_that_never_started_puts_nothing_on_the_clock() -> None:
    """A skipped step sat through the steps above it, and that time is theirs."""
    skipped = attempt(created=0, finished=40, status=AttemptStatus.SKIPPED)
    assert attempt_timing(skipped, at=at(40)).total_ms == 0


def test_a_parked_attempt_counts_the_probes_before_the_last_one_as_waiting() -> None:
    """Everything up to the last probe is waiting; the probe that settled it is running."""
    timing = attempt_timing(attempt(created=0, started=1, heartbeat=61, finished=62, pokes=6), at=at(62))
    assert (timing.queued_ms, timing.waiting_ms, timing.running_ms) == (1000, 60_000, 1000)


def test_an_attempt_still_parked_is_waiting_up_to_now() -> None:
    parked = attempt(created=0, started=1, heartbeat=30, pokes=3, status=AttemptStatus.WAITING)
    timing = attempt_timing(parked, at=at(90))
    assert (timing.waiting_ms, timing.running_ms) == (89_000, 0)


def test_a_step_adds_up_its_retries_and_takes_only_the_last_element_of_a_fan_out() -> None:
    first = uuid.uuid4()
    second = uuid.uuid4()
    tries = [
        attempt("map", created=0, started=1, finished=2, item=first),
        attempt("map", created=0, started=1, finished=5, item=second),
        attempt("map", created=5, started=6, finished=9, item=second, number=2),
    ]
    timing = step_timing(node("map", fan_out=True), tries, at=at(9))
    assert timing.attempts == 3, "every try is counted"
    assert timing.running_ms == 7000, "only the element that finished last is on the run's clock, tries and all"
    assert timing.queued_ms == 2000, "its retry queued behind it, so both of that element's waits count"


def test_the_critical_path_is_the_chain_of_last_finishing_dependencies() -> None:
    nodes = [
        node("extract"),
        node("slow", after=["extract"]),
        node("fast", after=["extract"]),
        node("load", after=["slow", "fast"]),
    ]
    attempts = [
        attempt("extract", created=0, started=0, finished=10),
        attempt("slow", created=10, started=10, finished=80),
        attempt("fast", created=10, started=10, finished=12),
        attempt("load", created=80, started=80, finished=90),
    ]
    timings = {one.code: step_timing(one, by_step(attempts)[one.code], at=at(90)) for one in nodes}
    assert critical_path(nodes, timings) == ["extract", "slow", "load"]


def test_a_profile_attributes_the_run_to_the_chain_that_decided_it() -> None:
    nodes = [node("extract"), node("slow", after=["extract"]), node("load", after=["slow"])]
    attempts = [
        attempt("extract", created=0, started=2, finished=10),
        attempt("slow", created=10, started=10, heartbeat=70, finished=72, pokes=6),
        attempt("load", created=72, started=72, finished=100),
    ]
    measured = profile(detail_of(*nodes), attempts, at=at(100))
    assert measured.critical_path == ["extract", "slow", "load"]
    assert measured.duration_ms == 100_000
    assert (measured.queued_ms, measured.running_ms, measured.waiting_ms) == (2000, 38_000, 60_000)
    assert [one.step for one in measured.steps] == ["extract", "slow", "load"]


def test_a_probe_cadence_longer_than_the_work_is_warned_about() -> None:
    nodes = [node("sensor")]
    attempts = [attempt("sensor", created=0, started=0, heartbeat=299, finished=300, pokes=5)]
    measured = profile(detail_of(*nodes), attempts, at=at(300))
    causes = [one.cause for one in measured.warnings]
    assert "probe-cadence" in causes
    said = next(one.message for one in measured.warnings if one.cause == "probe-cadence")
    assert "5 probes" in said and said.endswith(".")


def test_a_deadline_many_times_the_wait_it_needed_is_warned_about() -> None:
    nodes = [node("sensor")]
    attempts = [attempt("sensor", created=0, started=0, heartbeat=9, finished=10, pokes=3, deadline=3600)]
    measured = profile(detail_of(*nodes), attempts, at=at(10))
    assert "slack-deadline" in [one.cause for one in measured.warnings]


def test_a_fan_out_whose_elements_never_overlapped_is_warned_about() -> None:
    nodes = [node("map", fan_out=True)]
    elements = [
        attempt("map", created=0, started=0, finished=10, item=uuid.uuid4()),
        attempt("map", created=0, started=10, finished=20, item=uuid.uuid4()),
        attempt("map", created=0, started=20, finished=30, item=uuid.uuid4()),
    ]
    measured = profile(detail_of(*nodes), elements, at=at(30))
    assert [one.cause for one in measured.warnings] == ["serial-fan-out"]


def test_a_fan_out_that_did_overlap_is_told_nothing() -> None:
    """Only the timestamps decide: elements that ran together prove nothing was serialised."""
    nodes = [node("map", fan_out=True)]
    elements = [
        attempt("map", created=0, started=0, finished=10, item=uuid.uuid4()),
        attempt("map", created=0, started=1, finished=11, item=uuid.uuid4()),
    ]
    assert profile(detail_of(*nodes), elements, at=at(11)).warnings == []


def test_a_run_that_was_never_slow_is_told_nothing() -> None:
    nodes = [node("one"), node("two", after=["one"])]
    attempts = [
        attempt("one", created=0, started=0, finished=1),
        attempt("two", created=1, started=1, finished=2),
    ]
    assert profile(detail_of(*nodes), attempts, at=at(2)).warnings == []


def test_an_attempt_the_deadline_ended_while_parked_counts_none_of_it_as_running() -> None:
    """Nothing was probing when the deadline reached it, so the whole span was a wait."""
    timed_out = attempt(created=0, started=1, heartbeat=9, finished=11, pokes=4, status=AttemptStatus.SKIPPED)
    timing = attempt_timing(timed_out, at=at(11))
    assert (timing.waiting_ms, timing.running_ms) == (10_000, 0)


def test_a_cadence_is_only_warned_about_where_the_work_was_measured() -> None:
    nodes = [node("sensor")]
    attempts = [
        attempt("sensor", created=0, started=0, heartbeat=8, finished=10, pokes=4, status=AttemptStatus.SKIPPED)
    ]
    assert profile(detail_of(*nodes), attempts, at=at(10)).warnings == []
