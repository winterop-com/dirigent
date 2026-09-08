"""One error envelope for every refusal, in the shape RFC 9457 describes."""

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dirigent_client.schemas import Problem
from dirigent_core import __version__
from dirigent_core.logging import redact_path
from dirigent_server.logging import get_logger

VERSION_HEADER = "X-Dirigent-Version"

INTERNAL_DETAIL = "the server failed to handle this request; the server log has the detail"

_logger = get_logger("errors")


def render(status: int, detail: str, *, problems: list[str] | None = None, instance: str | None = None) -> Problem:
    """Build the one problem shape, from whichever handler is answering."""
    try:
        title = HTTPStatus(status).phrase
    except ValueError:  # pragma: no cover - a non-standard status from a plugin
        title = "Error"
    return Problem(status=status, title=title, detail=detail, problems=problems or [], instance=instance)


def _problems_of(detail: Any) -> tuple[str, list[str]]:
    """Split whatever was raised into one sentence and, when there is one, a list."""
    if isinstance(detail, str):
        return detail, []
    if isinstance(detail, list):
        rendered = [_one(item) for item in cast(list[object], detail)]
        return "; ".join(rendered), rendered
    return str(detail), []


def _one(item: object) -> str:
    """Render one entry of a problem list, whether it is a string or a pydantic error."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        mapping = cast(dict[str, Any], item)
        location = ".".join(str(part) for part in mapping.get("loc", []))
        message = str(mapping.get("msg", mapping))
        return f"{location}: {message}" if location else message
    return str(item)


def _where(request: Request) -> str:
    """Name the path that was asked for, never including a credential from it."""
    return redact_path(request.url.path)


def answer(problem: Problem) -> JSONResponse:
    """Serialise a problem into a response."""
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        headers={VERSION_HEADER: __version__},
    )


async def _stamp_version(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Put the version header on every response."""
    response = await call_next(request)
    response.headers[VERSION_HEADER] = __version__
    return response


async def http_error(request: Request, error: Exception) -> JSONResponse:
    """Render an HTTPException as a problem."""
    if not isinstance(error, StarletteHTTPException):  # pragma: no cover - registered for this class
        return await unhandled(request, error)
    detail, problems = _problems_of(error.detail)
    response = answer(render(error.status_code, detail, problems=problems, instance=_where(request)))
    if isinstance(error, HTTPException) and error.headers:
        response.headers.update(error.headers)
    return response


async def validation_error(request: Request, error: Exception) -> JSONResponse:
    """Render a request-validation failure as a problem with its field list intact."""
    if not isinstance(error, RequestValidationError):  # pragma: no cover - registered for this class
        return await unhandled(request, error)
    detail, problems = _problems_of(error.errors())
    return answer(render(422, detail, problems=problems, instance=_where(request)))


async def unhandled(request: Request, error: Exception) -> JSONResponse:
    """Answer an unhandled exception in the same shape, and say nothing about it.

    An unexpected exception's message may carry a DSN, a path, or a fragment of a payload,
    so it goes to the log only and never to the caller.
    """
    _logger.error(
        "unhandled exception",
        path=_where(request),
        method=request.method,
        error=f"{type(error).__name__}: {error}",
        exc_info=error,
    )
    return answer(render(500, INTERNAL_DETAIL, instance=_where(request)))


def install_error_handlers(app: FastAPI) -> None:
    """Install the error envelope and the version header on the application."""
    app.middleware("http")(_stamp_version)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, unhandled)
