"""What every client test builds on: a client wired to a handler instead of a network."""

import json
from collections.abc import Callable
from typing import Any

import httpx2

from dirigent_client import VERSION_HEADER, Dirigent

BASE_URL = "https://dirigent.test"

#: The client reads a response without this header as not coming from dirigent at all, so
#: every faked response has to carry it.
STAMPED = {VERSION_HEADER: "0.1.0"}

type Call = tuple[str, str, str, Any]


class Recorder:
    """A mock transport that records what was asked and answers from a script."""

    def __init__(self, answers: list[httpx2.Response] | Callable[[httpx2.Request], httpx2.Response]) -> None:
        """Answer either from a fixed list, in order, or from a handler."""
        self.calls: list[Call] = []
        self._answers = answers

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Record one request and produce the answer the script names for it."""
        body: Any = None
        if request.content:
            body = json.loads(request.content)
        self.calls.append((request.method, request.url.path, str(request.url.query, "utf-8"), body))
        if callable(self._answers):
            return self._answers(request)
        return self._answers[min(len(self.calls) - 1, len(self._answers) - 1)]

    @property
    def last(self) -> Call:
        """Return the most recent request."""
        return self.calls[-1]

    @property
    def paths(self) -> list[str]:
        """Return every path that was asked for, in order."""
        return [call[1] for call in self.calls]


def ok(payload: Any, *, status: int = 200) -> httpx2.Response:
    """One successful JSON answer, stamped the way a dirigent instance stamps it."""
    return httpx2.Response(status, json=payload, headers=STAMPED)


def refusal(
    status: int,
    detail: str,
    *,
    problems: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    """One refusal in the problem shape every error response takes."""
    return httpx2.Response(
        status,
        json={
            "status": status,
            "title": "Error",
            "detail": detail,
            "problems": problems or [],
            "instance": "/api/v1/somewhere",
        },
        headers={**STAMPED, **(headers or {})},
    )


def client_of(recorder: Recorder, **kwargs: Any) -> Dirigent:
    """Build a client whose every request goes to the recorder rather than to a socket."""
    return Dirigent(url=BASE_URL, token="a-token", http_transport=httpx2.MockTransport(recorder), **kwargs)
