"""Where a request's transaction is committed: before its response, not after."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession


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
