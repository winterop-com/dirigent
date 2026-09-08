"""What `--watch` prints: the run's event stream, rendered as transitions and block output."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from clisupport import records, refusal
from dirigent_cli.commands import (
    log_events,
    moment_of,
    print_events,
    remote_finished_event,
    transition_event,
)
from dirigent_cli.main import app
from dirigent_cli.output import Detail, configure
from dirigent_cli.stream import Sink
from dirigent_client import AttemptEvent, DagView, LogEntryOut, RunDetail, RunOut, RunReport, StepReport
from dirigent_client.enums import RunStatus

runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})

RUN_ID = uuid4()


@pytest.fixture(autouse=True)
def _rendering() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """These tests read what a person sees, so they ask for the rendering.

    NDJSON is what a command writes unasked, and under it the console is muted -- a test
    that read rendered output without asking would read nothing at all.
    """
    configure(output="console")
    yield


def attempt(
    step: str,
    status: str,
    *,
    started: str | None,
    finished: str | None = None,
    output: dict[str, Any] | None = None,
    output_uri: str | None = None,
    item: str | None = None,
) -> AttemptEvent:
    return AttemptEvent.model_validate(
        {
            "id": str(uuid4()),
            "step_name": step,
            "block_id": "http.request",
            "attempt": 1,
            "kind": "automatic",
            "status": status,
            "started_at": started,
            "finished_at": finished,
            "output": output,
            "output_uri": output_uri,
            "output_bytes": 24576 if output_uri else None,
            "item": item,
        }
    )


def transitions(*attempts: AttemptEvent, seen: dict[str, str] | None = None) -> list[Any]:
    """Read a stream's attempt events the way the watch does, in the order they arrived."""
    tracked = {} if seen is None else seen
    return [event for row in attempts for event in transition_event(row, tracked)]


def detail_of(*attempts: AttemptEvent) -> RunDetail:
    """The detail the watch reads back, which counts a run's attempts rather than carrying them."""
    run = RunOut.model_validate(
        {
            "id": str(RUN_ID),
            "pipeline": "demo",
            "pipeline_version": 1,
            "status": "running",
            "triggered_by_kind": "adhoc",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    return RunDetail(run=run, dag=DagView(), items_total=0, attempts_total=len(attempts))


def entry(step: str | None, message: str, at: str) -> LogEntryOut:
    return LogEntryOut.model_validate(
        {"id": 1, "run_id": str(RUN_ID), "step_name": step, "message": message, "created_at": at, "level": "info"}
    )


def streamed(capsys: Any) -> list[dict[str, Any]]:
    """Read back the records one cycle wrote, which is what a watcher reacts to."""
    return records(capsys.readouterr().out)


def test_a_transition_and_the_output_it_caused_print_in_that_order(capsys: Any) -> None:
    moved = transitions(
        attempt("fetch", "running", started="2026-01-01T00:00:01+00:00"),
        attempt("fetch", "succeeded", started="2026-01-01T00:00:01+00:00", finished="2026-01-01T00:00:04+00:00"),
    )
    entries = [
        entry("fetch", "http call", "2026-01-01T00:00:02+00:00"),
        entry("fetch", "response body saved", "2026-01-01T00:00:03+00:00"),
    ]
    print_events(moved + log_events(entries), out=Sink("json"))
    written = streamed(capsys)
    assert [record["message"] for record in written] == [
        "running",
        "http call",
        "response body saved",
        "succeeded",
    ]
    assert [record["kind"] for record in written] == ["step", "log", "log", "step"]


def test_a_transition_wins_a_tie_against_output_written_in_the_same_instant(capsys: Any) -> None:
    """At an equal timestamp the cause prints first."""
    moved = transitions(attempt("fetch", "running", started="2026-01-01T00:00:01+00:00"))
    entries = [entry("fetch", "http call", "2026-01-01T00:00:01+00:00")]
    print_events(moved + log_events(entries))
    printed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert "running" in printed[0]
    assert "http call" in printed[1]


def test_an_attempt_with_no_timestamp_yet_sorts_to_the_front(capsys: Any) -> None:
    """An attempt with no started_at sorts to the front of its cycle."""
    moved = transitions(attempt("fetch", "queued", started=None))
    entries = [entry(None, "worker claimed the run", "2026-01-01T00:00:01+00:00")]
    print_events(moved + log_events(entries))
    printed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert "queued" in printed[0]


def test_an_attempt_is_announced_once_per_state_it_reaches() -> None:
    """The cursor is the state, not the attempt: a replayed attempt must not print twice."""
    seen: dict[str, str] = {}
    running = attempt("fetch", "running", started="2026-01-01T00:00:01+00:00")
    assert len(transitions(running, seen=seen)) == 1
    assert transitions(running, seen=seen) == []
    settled = attempt("fetch", "succeeded", started="2026-01-01T00:00:01+00:00", finished="2026-01-01T00:00:02+00:00")
    assert len(transitions(settled, seen=seen)) == 1


def test_a_pending_attempt_is_not_news() -> None:
    assert transitions(attempt("fetch", "pending", started=None)) == []


def test_a_fan_out_transition_is_named_by_the_item_the_event_carries(capsys: Any) -> None:
    """The label comes off the event, so nothing reads the run's item grid to print a line."""
    print_events(
        transitions(attempt("load", "running", started="2026-01-01T00:00:01+00:00", item="oslo")), out=Sink("json")
    )
    written = streamed(capsys)[-1]
    assert written["kind"] == "step"
    assert written["item"] == "oslo"


def test_a_timestamp_the_server_did_not_write_is_read_as_the_beginning_of_time() -> None:
    assert moment_of(None) == moment_of("")
    assert moment_of("2026-01-01T00:00:00Z") > moment_of(None)
    assert moment_of("2026-01-01T00:00:00") == moment_of("2026-01-01T00:00:00+00:00")


def test_strict_without_a_way_to_read_the_outcome_is_refused() -> None:
    """--strict is refused without --watch or --local."""
    result = runner.invoke(app, ["run", "some-pipeline", "--strict"])
    assert result.exit_code == 1
    assert "--watch" in refusal(result.stdout)["message"]


STARTED = "2026-01-01T00:00:01+00:00"
FINISHED = "2026-01-01T00:00:04+00:00"


def test_the_watched_stream_follows_the_same_ladder_as_a_local_run(capsys: Any) -> None:
    """One rendering ladder, whether the run is here or on a server."""
    produced = attempt(
        "fetch",
        "succeeded",
        output={"status": 200, "headers": {"a": "1", "b": "2"}},
        started=STARTED,
        finished=FINISHED,
    )
    ladder = (
        (Detail.SUMMARY, ["step"]),
        (Detail.VALUES, ["step", "output"]),
        (Detail.FULL, ["step", "output"]),
    )
    for level, expected in ladder:
        print_events(transitions(produced), level, out=Sink("json"))
        written = streamed(capsys)
        assert [record["kind"] for record in written] == expected, level
        if level is Detail.SUMMARY:
            continue
        assert written[-1]["status"] == 200
        assert written[-1]["headers"] == {"a": "1", "b": "2"}, "the whole value, however deep"


def test_a_watched_output_that_spilled_names_its_artifact(capsys: Any) -> None:
    spilled = attempt(
        "fetch",
        "succeeded",
        output={"status": 200},
        output_uri="file:///scratch/a.json",
        started=STARTED,
        finished=FINISHED,
    )
    print_events(transitions(spilled), Detail.VALUES, out=Sink("json"))
    written = streamed(capsys)[-1]
    assert written["kind"] == "output"
    assert written["artifact"] == "file:///scratch/a.json"
    assert written["bytes"] == 24576
    assert "status" not in written, "an output that spilled is named, not guessed at"


def test_a_watched_stream_writes_the_same_events_in_the_json_spelling(capsys: Any) -> None:
    """One protocol: the same events, the same field names, one object per line."""
    moved = transitions(
        attempt("fetch", "running", started="2026-01-01T00:00:01+00:00"),
        attempt("fetch", "succeeded", output={"status": 200}, started=STARTED, finished=FINISHED),
    )
    entries = [entry("fetch", "http call", "2026-01-01T00:00:02+00:00")]
    print_events(moved + log_events(entries), Detail.VALUES, out=Sink("json"))
    events = streamed(capsys)
    assert [event["kind"] for event in events] == ["step", "log", "step", "output"]
    assert all(event["v"] == 1 for event in events)
    assert events[-1]["status"] == 200
    assert events[2]["duration_ms"] == 3000
    assert events[1]["message"] == "http call"


def test_the_closing_event_carries_the_per_step_summary_the_table_would_have_shown() -> None:
    attempts = [
        attempt("fetch", "succeeded", output={"status": 200}, started=STARTED, finished=FINISHED),
        attempt("push", "failed", started=STARTED, finished=FINISHED),
    ]
    finished = remote_finished_event(detail_of(*attempts), "demo", 1, attempts=attempts, items=[])
    assert finished.exit_code == 1
    assert [step.step for step in finished.steps] == ["fetch", "push"]
    assert [failure.step for failure in finished.failures] == ["push"]


def test_the_closing_event_carries_what_the_table_reads_rather_than_a_second_query() -> None:
    """The rendering is of this record, so a field the table spends a column on lives here."""
    attempts = [
        attempt("fetch", "succeeded", output={"status": 200}, started=STARTED, finished=FINISHED),
        attempt("push", "failed", started=STARTED, finished=FINISHED),
    ]
    detail = detail_of(*attempts)
    report = RunReport(
        run_id=detail.run.id,
        pipeline="demo",
        pipeline_version=3,
        status=RunStatus.COMPLETED_WITH_ERRORS,
        triggered_by="schedule",
        duration_ms=4200,
        items_total=2,
        items_failed=1,
        steps=[
            StepReport(step="fetch", block="http.request", outcome="succeeded", attempts=1, warnings=2),
            StepReport(step="push", block="http.request", outcome="failed", attempts=1, depends_on=["fetch"]),
        ],
    )
    logs = {row.id: ["error: it refused"] for row in attempts if row.step_name == "push"}
    finished = remote_finished_event(detail, "demo", 1, attempts=attempts, items=[], report=report, logs=logs)

    assert finished.pipeline_version == 3, "the fields block reads the version off the record"
    assert finished.triggered_by == "schedule"
    assert (finished.duration_ms, finished.items_total, finished.items_failed) == (4200, 2, 1)
    steps = {row.step: row for row in finished.steps}
    assert steps["fetch"].warnings == 2, "a succeeded step can still be flagged"
    assert steps["push"].depends_on == ["fetch"], "the after column"
    assert finished.failures[0].logs == ["error: it refused"], "the diagnosis needs no second fetch"
