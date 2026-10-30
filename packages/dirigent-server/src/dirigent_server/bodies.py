"""Reading a request's body under a cap, for the routes a stranger may call."""

import asyncio
from datetime import timedelta
from enum import Enum, auto
from typing import Final

from fastapi import FastAPI, Request, Response, status
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dirigent_common import format_duration
from dirigent_core.auth import resolve_token
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_server.errors import Refusal, answer, render
from dirigent_server.messages import BODY_TIMED_OUT, UNAUTHENTICATED_BODY_TOO_LARGE
from dirigent_server.security import LOGIN_PATH, presented_secret

#: The most a caller who has not proved who it is may send to the versioned API.
UNAUTHENTICATED_MAX_BODY: Final = 1024 * 1024

#: The most a login may send, a credential or no credential: a username and a password.
LOGIN_MAX_BODY: Final = 16 * 1024

#: How long a body may take to arrive, from the first read to the last, before a caller who has
#: not proved who it is gets a 408 and a closed connection.
BODY_DEADLINE: Final = timedelta(seconds=30)


async def read_capped(request: Request, limit: int) -> bytes:
    """Read the body, stopping one byte past the limit rather than after all of it.

    ``request.body()`` buffers whatever arrives before the size can be checked, so an
    unauthenticated caller could make the process allocate a gigabyte to be told a megabyte
    is the maximum. What comes back may be longer than the limit, which is how a caller
    learns the body was too large.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            break
    return b"".join(chunks)


async def read_within_deadline(request: Request, limit: int) -> bytes:
    """Read a capped body, refusing one that has not arrived whole by the deadline."""
    try:
        async with asyncio.timeout(BODY_DEADLINE.total_seconds()):
            return await read_capped(request, limit)
    except TimeoutError as error:
        raise Refusal(
            BODY_TIMED_OUT,
            status=status.HTTP_408_REQUEST_TIMEOUT,
            headers={"Connection": "close"},
            timeout=format_duration(BODY_DEADLINE),
        ) from error


class _Held(Enum):
    """How holding a body ended."""

    WHOLE = auto()
    PAST_THE_CAP = auto()
    PAST_THE_DEADLINE = auto()


class UnauthenticatedBodyCap:
    """Refuse a body under the versioned API past the cap or deadline, unless its caller is authenticated.

    A route reads and parses its body before its dependencies run, so this sits in front of
    them. It holds a body up to the cap, then replays it to the route. Past the cap or the
    deadline it checks the credential before reading any more, so a credential that does not
    resolve earns no more memory or time than none at all.
    """

    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        """Wrap the application, and cap what arrives under the prefix."""
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass one request through, or answer 413 or 408 without reading the rest of its body."""
        path: str = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(self.api_prefix):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        login = path == f"{self.api_prefix}{LOGIN_PATH}"
        limit = LOGIN_MAX_BODY if login else UNAUTHENTICATED_MAX_BODY
        held, ended = await _hold(request, receive, limit)
        if ended is not _Held.WHOLE and (login or not await _authenticated(request)):
            refusal = _too_large(limit, path) if ended is _Held.PAST_THE_CAP else _too_late(path)
            await refusal(scope, receive, send)
            return

        async def replayed() -> Message:
            return held.pop(0) if held else await receive()

        await self.app(scope, replayed, send)


async def _hold(request: Request, receive: Receive, limit: int) -> tuple[list[Message], _Held]:
    """Read the body up to the cap and the deadline, and say how that ended."""
    declared = request.headers.get("content-length", "")
    if declared.isdecimal() and int(declared) > limit:
        return [], _Held.PAST_THE_CAP
    held: list[Message] = []
    size = 0
    try:
        async with asyncio.timeout(BODY_DEADLINE.total_seconds()):
            while True:
                message = await receive()
                held.append(message)
                if message["type"] != "http.request":
                    return held, _Held.WHOLE
                size += len(message.get("body", b""))
                if size > limit:
                    return held, _Held.PAST_THE_CAP
                if not message.get("more_body", False):
                    return held, _Held.WHOLE
    except TimeoutError:
        return held, _Held.PAST_THE_DEADLINE


def _too_large(limit: int, path: str) -> Response:
    """Refuse a body past the cap."""
    return answer(
        render(
            status.HTTP_413_CONTENT_TOO_LARGE,
            UNAUTHENTICATED_BODY_TOO_LARGE.render(limit=limit),
            code=UNAUTHENTICATED_BODY_TOO_LARGE.code,
            params={"limit": limit},
            instance=path,
        )
    )


def _too_late(path: str) -> Response:
    """Refuse a body past the deadline, closing the connection it was arriving on."""
    timeout = format_duration(BODY_DEADLINE)
    response = answer(
        render(
            status.HTTP_408_REQUEST_TIMEOUT,
            BODY_TIMED_OUT.render(timeout=timeout),
            code=BODY_TIMED_OUT.code,
            params={"timeout": timeout},
            instance=path,
        )
    )
    response.headers["Connection"] = "close"
    return response


async def _authenticated(request: Request) -> bool:
    """Whether the request presents a credential that resolves to a principal."""
    secret = presented_secret(request)
    if secret is None:
        return False
    async with session_scope(request.app.state.session_factory) as session:
        return await resolve_token(session, secret) is not None


def install_unauthenticated_body_cap(app: FastAPI, settings: Settings) -> None:
    """Cap what the versioned API reads from a caller it has not authenticated.

    Registered before the error handlers, so the version-header middleware they install wraps
    this refusal too.
    """
    app.add_middleware(UnauthenticatedBodyCap, api_prefix=settings.api_prefix)
