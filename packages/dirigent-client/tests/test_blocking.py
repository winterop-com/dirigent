"""The blocking bridge: the same accessors, driven from synchronous code."""

from collections.abc import Callable

import httpx2
import pytest

from clientsupport import BASE_URL, STAMPED
from dirigent_client import BlockingDirigent, NotFound

ID = "0193b0f0-0000-7000-8000-000000000001"
WHEN = "2026-01-01T00:00:00+00:00"

PIPELINE = {
    "id": ID,
    "code": "demo",
    "active": True,
    "current_version": 1,
    "active_runs": 0,
    "created_at": WHEN,
    "updated_at": WHEN,
}


def blocking(handler: Callable[[httpx2.Request], httpx2.Response]) -> BlockingDirigent:
    """Build a blocking client answering from a handler rather than from a network."""
    return BlockingDirigent(url=BASE_URL, token="a-token", http_transport=httpx2.MockTransport(handler))


def test_a_call_runs_to_completion_and_returns_the_parsed_answer() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"items": [PIPELINE], "next": None}, headers=STAMPED)

    with blocking(handler) as dg:
        assert [row.code for row in dg.call(dg.pipelines.list()).items] == ["demo"]
        assert dg.url == BASE_URL


def test_a_refusal_reaches_the_synchronous_caller_as_the_same_exception() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"detail": "no pipeline coded 'demo'"}, headers=STAMPED)

    with blocking(handler) as dg, pytest.raises(NotFound):
        dg.call(dg.pipelines.get("demo"))


def test_a_log_tail_reads_as_an_ordinary_iterator() -> None:
    body = (
        f'{{"id": 1, "run_id": "{ID}", "step_name": "greet", '
        f'"level": "info", "message": "hello", "created_at": "{WHEN}"}}'
    )
    stream = f"event: log\ndata: {body}\n\nevent: end\ndata: {{}}\n\n"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text=stream, headers={**STAMPED, "content-type": "text/event-stream"})

    with blocking(handler) as dg:
        assert [entry.message for entry in dg.iterate(dg.runs.follow_logs(ID))] == ["hello"]
