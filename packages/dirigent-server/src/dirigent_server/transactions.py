"""Where a request's transaction is committed: before its response, not after."""

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_core.database import with_deadlock_retry


class Transactional(APIRoute):
    """A route that commits its request's transaction before the response is sent.

    The alternative is to commit in the exit of the dependency that opened it, which FastAPI
    runs after the response has gone out. Two things follow from that, and both are wrong: a
    client that reads straight back can miss the write it was just told about, and a commit
    that fails does so after the client has a 2xx it will believe.

    Committing here happens while the response can still be changed, so a commit that fails
    is the error the client sees.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the handler so what it decided is durable before anybody is told."""
        handle = super().get_route_handler()

        async def commit_then_respond(request: Request) -> Response:
            response = await handle(request)
            session: AsyncSession | None = getattr(request.state, "session", None)
            if session is not None and session.in_transaction():
                await session.commit()
            return response

        return commit_then_respond


async def retried_on_deadlock[T](session: AsyncSession, work: Callable[[], Awaitable[T]]) -> T:
    """Run a route's write in a savepoint of the request's transaction, again after a deadlock.

    The savepoint is what a deadlock rolls back, taking the locks it took with it, so the
    transaction lives on for the attempt after it. ``work`` re-reads everything it decides on.
    """

    async def once() -> T:
        async with session.begin_nested():
            return await work()

    return await with_deadlock_retry(once)
