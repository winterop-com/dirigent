"""Waiting for a run, and following its story across a connection that drops."""

from datetime import timedelta
from typing import Any

import httpx2
import pytest

from clientsupport import Recorder, client_of
from dirigent_client import AttemptEvent, LogEntryOut, NotFound, RunOut, RunStatus, TransportError, WaitTimeout
from dirigent_client.resources.runs import POLL_BACKOFF, POLL_MAX_SECONDS

ID = "0193b0f0-0000-7000-8000-000000000001"
WHEN = "2026-01-01T00:00:00+00:00"

STAMPED = {"X-Dirigent-Version": "0.1.0"}


def detail(status: str) -> httpx2.Response:
    """One run-detail answer with the run in the given state."""
    run = {
        "id": ID,
        "pipeline": "demo",
        "pipeline_version": 1,
        "status": status,
        "triggered_by_kind": "adhoc",
        "created_at": WHEN,
    }
    body: dict[str, Any] = {"run": run, "items": [], "attempts": [], "dag": {"nodes": [], "edges": []}}
    return httpx2.Response(200, json=body, headers=STAMPED)


def sse(*events: str) -> httpx2.Response:
    """One server-sent-event stream, as the log tail serves it."""
    return httpx2.Response(
        200,
        text="".join(events),
        headers={**STAMPED, "content-type": "text/event-stream"},
    )


def log_event(entry_id: int, message: str) -> str:
    """One ``log`` event carrying a serialised entry."""
    body = (
        f'{{"id": {entry_id}, "run_id": "{ID}", "step_name": "greet", '
        f'"level": "info", "message": "{message}", "created_at": "{WHEN}"}}'
    )
    return f"event: log\ndata: {body}\n\n"


END = "event: end\ndata: {}\n\n"
EXPIRED = "event: expired\ndata: {}\n\n"

ATTEMPT_ID = "0193b0f0-0000-7000-8000-000000000002"


def attempt_event(status: str, *, item: str | None = None) -> str:
    """One ``attempt`` event carrying a serialised attempt state."""
    named = f'"{item}"' if item is not None else "null"
    body = (
        f'{{"id": "{ATTEMPT_ID}", "step_name": "greet", "block_id": "shell.run", "attempt": 1, '
        f'"kind": "automatic", "status": "{status}", "item": {named}}}'
    )
    return f"event: attempt\ndata: {body}\n\n"


def run_event(status: str) -> str:
    """One ``run`` event carrying the state the run settled in."""
    body = (
        f'{{"id": "{ID}", "pipeline": "demo", "pipeline_version": 1, "status": "{status}", '
        f'"triggered_by_kind": "adhoc", "created_at": "{WHEN}"}}'
    )
    return f"event: run\ndata: {body}\n\n"


async def test_the_event_stream_yields_attempts_logs_and_the_state_the_run_settled_in() -> None:
    answers = [
        sse(
            attempt_event("running", item="oslo"),
            log_event(1, "started"),
            attempt_event("succeeded"),
            run_event("succeeded"),
            END,
        )
    ]
    async with client_of(Recorder(answers)) as dg:
        story = [event async for event in dg.runs.events(ID)]
    assert [type(event) for event in story] == [AttemptEvent, LogEntryOut, AttemptEvent, RunOut]
    assert isinstance(story[0], AttemptEvent) and story[0].item == "oslo"
    assert isinstance(story[-1], RunOut) and story[-1].status is RunStatus.SUCCEEDED


async def test_an_event_stream_that_drops_resumes_after_the_last_log_entry_seen(no_sleep: list[float]) -> None:
    opened: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(str(request.url.query, "utf-8"))
        if len(opened) == 1:
            return sse(attempt_event("running"), log_event(4, "first half"))
        return sse(attempt_event("running"), attempt_event("succeeded"), run_event("succeeded"), END)

    async with client_of(Recorder(handler)) as dg:
        story = [event async for event in dg.runs.events(ID)]
    assert [entry.message for entry in story if isinstance(entry, LogEntryOut)] == ["first half"]
    assert opened[1] == "after=4", "the logs resume; the attempts are replayed and deduped by the reader"


async def test_an_event_stream_that_expires_is_reopened_from_the_last_entry_seen(
    no_sleep: list[float],
) -> None:
    """``expired`` is the server's wall-clock limit, not the end of the run."""
    opened: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(str(request.url.query, "utf-8"))
        if len(opened) == 1:
            return sse(log_event(4, "before the hour was up"), EXPIRED)
        return sse(log_event(5, "and on it went"), run_event("succeeded"), END)

    async with client_of(Recorder(handler)) as dg:
        story = [event async for event in dg.runs.events(ID)]
    assert [entry.message for entry in story if isinstance(entry, LogEntryOut)] == [
        "before the hour was up",
        "and on it went",
    ]
    assert opened[1] == "after=4"


async def test_an_event_stream_that_closes_saying_nothing_reconnects_until_it_gives_up(
    no_sleep: list[float],
) -> None:
    """A stream that names neither ending was cut, and a cut spends the reconnect budget."""
    opened: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(1)
        return sse()

    async with client_of(Recorder(handler)) as dg:
        assert [event async for event in dg.runs.events(ID, reconnects=2)] == []
    assert len(opened) == 3


async def test_an_event_stream_that_keeps_dropping_gives_up_and_raises(no_sleep: list[float]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadError("gone", request=request)

    async with client_of(Recorder(handler)) as dg:
        with pytest.raises(TransportError):
            [event async for event in dg.runs.events(ID, reconnects=1)]


async def test_waiting_returns_the_run_once_it_reaches_a_terminal_status(no_sleep: list[float]) -> None:
    answers = [detail("queued"), detail("running"), detail("succeeded")]
    recorder = Recorder(answers)
    async with client_of(recorder) as dg:
        run = await dg.runs.wait(ID)
    assert run.status is RunStatus.SUCCEEDED
    assert len(recorder.calls) == 3


async def test_a_quiet_run_is_polled_less_and_less_often(no_sleep: list[float]) -> None:
    answers = [detail("running")] * 4 + [detail("failed")]
    async with client_of(Recorder(answers)) as dg:
        run = await dg.runs.wait(ID, poll=1.0, timeout=timedelta(hours=1))
    assert run.status is RunStatus.FAILED
    assert no_sleep == [1.0, POLL_BACKOFF, POLL_BACKOFF**2, POLL_BACKOFF**3]


async def test_the_poll_interval_stops_growing_at_the_ceiling() -> None:
    assert min(POLL_MAX_SECONDS * POLL_BACKOFF, POLL_MAX_SECONDS) == POLL_MAX_SECONDS


async def test_a_run_that_never_settles_times_out_without_cancelling_it(no_sleep: list[float]) -> None:
    recorder = Recorder([detail("running")])
    async with client_of(recorder) as dg:
        with pytest.raises(WaitTimeout) as raised:
            await dg.runs.wait(ID, timeout=timedelta(seconds=0.5))
    assert "still running" in raised.value.message
    assert len(recorder.calls) == 1


async def test_following_a_log_stream_yields_every_entry_until_the_run_settles() -> None:
    answers = [sse(log_event(1, "started"), log_event(2, "finished"), END)]
    async with client_of(Recorder(answers)) as dg:
        entries = [entry async for entry in dg.runs.follow_logs(ID)]
    assert [entry.message for entry in entries] == ["started", "finished"]


async def test_a_stream_that_drops_mid_run_is_reopened_from_the_last_entry_seen(no_sleep: list[float]) -> None:
    opened: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(str(request.url.query, "utf-8"))
        if len(opened) == 1:
            raise httpx2.ReadError("the connection dropped", request=request)
        return sse(log_event(7, "back again"), END)

    async with client_of(Recorder(handler)) as dg:
        entries = [entry async for entry in dg.runs.follow_logs(ID)]
    assert [entry.message for entry in entries] == ["back again"]
    assert opened[0] == "follow=sse&after=0"
    assert opened[1] == "follow=sse&after=0"


async def test_a_reconnection_resumes_after_the_last_entry_already_yielded(no_sleep: list[float]) -> None:
    opened: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(str(request.url.query, "utf-8"))
        if len(opened) == 1:
            return sse(log_event(4, "first half"))
        return sse(log_event(5, "second half"), END)

    async with client_of(Recorder(handler)) as dg:
        entries = [entry async for entry in dg.runs.follow_logs(ID)]
    assert [entry.message for entry in entries] == ["first half", "second half"]
    assert opened[1] == "follow=sse&after=4"


async def test_a_log_stream_that_expires_is_reopened_and_followed_to_the_end(
    no_sleep: list[float],
) -> None:
    """The server closes a tail at its wall-clock limit; a run longer than that keeps streaming."""
    opened: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(str(request.url.query, "utf-8"))
        if len(opened) == 1:
            return sse(log_event(1, "the first hour"), EXPIRED)
        return sse(log_event(2, "the second hour"), END)

    async with client_of(Recorder(handler)) as dg:
        entries = [entry async for entry in dg.runs.follow_logs(ID)]
    assert [entry.message for entry in entries] == ["the first hour", "the second hour"]
    assert opened[1] == "follow=sse&after=1"


async def test_an_expiring_log_stream_never_runs_out_of_reconnections(no_sleep: list[float]) -> None:
    """The reconnect budget is for a broken transport; an expiry is the server working as asked."""
    opened: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(1)
        return sse(EXPIRED) if len(opened) <= 4 else sse(END)

    async with client_of(Recorder(handler)) as dg:
        assert [entry async for entry in dg.runs.follow_logs(ID, reconnects=1)] == []
    assert len(opened) == 5


async def test_a_stream_that_closes_without_the_end_event_stops_after_its_reconnections(
    no_sleep: list[float],
) -> None:
    opened: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(1)
        return sse()

    async with client_of(Recorder(handler)) as dg:
        assert [entry async for entry in dg.runs.follow_logs(ID, reconnects=2)] == []
    assert len(opened) == 3


async def test_a_stream_that_keeps_dropping_gives_up_and_raises(no_sleep: list[float]) -> None:
    opened: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(1)
        raise httpx2.ReadError("gone", request=request)

    async with client_of(Recorder(handler)) as dg:
        with pytest.raises(TransportError):
            [entry async for entry in dg.runs.follow_logs(ID, reconnects=1)]
    assert len(opened) == 2


async def test_a_refused_log_stream_is_a_refusal_rather_than_a_reconnection(no_sleep: list[float]) -> None:
    answer = httpx2.Response(404, json={"detail": f"no run {ID}"}, headers=STAMPED)
    async with client_of(Recorder([answer])) as dg:
        with pytest.raises(NotFound):
            [entry async for entry in dg.runs.follow_logs(ID)]


async def test_following_only_one_step_narrows_the_stream() -> None:
    opened: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        opened.append(str(request.url.query, "utf-8"))
        return sse(END)

    async with client_of(Recorder(handler)) as dg:
        assert [entry async for entry in dg.runs.follow_logs(ID, after=12, step="greet")] == []
    assert opened == ["follow=sse&after=12&step=greet"]
