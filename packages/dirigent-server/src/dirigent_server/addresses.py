"""An address no database stores as written, answered before anything reads it."""

from fastapi import FastAPI, Request, Response, status
from starlette.types import ASGIApp, Receive, Scope, Send

from dirigent_common.storable import is_storable
from dirigent_server.errors import answer, render
from dirigent_server.messages import ADDRESS_UNSTORABLE


class StorableAddresses:
    """Answer 404 to a request whose path or query holds a NUL or half a surrogate pair.

    It answers ahead of every route, credential and lookup, the endpoint sources' templated
    routes included. PostgreSQL fails a lookup by such text rather than finding nothing.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass one request through, or answer it without reading its body."""
        if scope["type"] == "http" and not storable_address(scope):
            await _not_found(scope["path"])(scope, receive, send)
            return
        await self.app(scope, receive, send)


def storable_address(scope: Scope) -> bool:
    """Whether a database stores the path, and every query key and value, as written."""
    query = Request(scope).query_params.multi_items()
    return is_storable(scope["path"]) and all(is_storable(key) and is_storable(value) for key, value in query)


def _not_found(path: str) -> Response:
    """Refuse an address that names nothing a database could hold."""
    return answer(
        render(
            status.HTTP_404_NOT_FOUND,
            ADDRESS_UNSTORABLE.render(),
            code=ADDRESS_UNSTORABLE.code,
            instance=path,
        )
    )


def install_storable_addresses(app: FastAPI) -> None:
    """Answer an address no database stores as written before anything else reads it.

    Registered after the body cap, so it answers ahead of the cap's credential lookup, and before
    the error handlers, so the version-header middleware they install wraps this refusal too.
    """
    app.add_middleware(StorableAddresses)
