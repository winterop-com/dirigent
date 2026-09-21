"""One error envelope for every refusal, in the shape RFC 9457 describes."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dirigent_client.schemas import Problem
from dirigent_common import Issue, JsonMap, Message, validation_issues
from dirigent_core import __version__
from dirigent_core.errors import DomainError
from dirigent_core.logging import redact_path
from dirigent_server.logging import get_logger
from dirigent_server.messages import HTTP_ERROR, INTERNAL, REQUEST_INVALID

VERSION_HEADER = "X-Dirigent-Version"

INTERNAL_DETAIL = INTERNAL.render()

_logger = get_logger("errors")


class Refusal(DomainError):
    """A refusal a route makes for which no core class already exists."""

    def __init__(
        self,
        message: Message,
        /,
        *,
        status: int = 400,
        headers: Mapping[str, str] | None = None,
        **params: Any,
    ) -> None:
        """Carry the status this refusal is answered with, and any header it has to set."""
        super().__init__(message, **params)
        self.status = status
        self.headers = dict(headers) if headers else None


def render(
    status: int,
    detail: str,
    *,
    code: str,
    params: JsonMap | None = None,
    problems: Sequence[Issue] = (),
    instance: str | None = None,
) -> Problem:
    """Build the one problem shape, from whichever handler is answering."""
    try:
        title = HTTPStatus(status).phrase
    except ValueError:  # pragma: no cover - a non-standard status from a plugin
        title = "Error"
    return Problem(
        status=status,
        title=title,
        detail=detail,
        code=code,
        params=params or {},
        problems=list(problems),
        instance=instance,
    )


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
    """Render an HTTPException as a problem: the framework's own 404, 405 and the like."""
    if not isinstance(error, StarletteHTTPException):  # pragma: no cover - registered for this class
        return await unhandled(request, error)
    detail = str(error.detail)
    problem = render(
        error.status_code,
        detail,
        code=HTTP_ERROR.code,
        params={"status": error.status_code, "detail": detail},
        instance=_where(request),
    )
    response = answer(problem)
    if isinstance(error, HTTPException) and error.headers:
        response.headers.update(error.headers)
    return response


async def validation_error(request: Request, error: Exception) -> JSONResponse:
    """Render a request-validation failure as a problem with its field list intact."""
    if not isinstance(error, RequestValidationError):  # pragma: no cover - registered for this class
        return await unhandled(request, error)
    issues = validation_issues(cast("list[dict[str, Any]]", error.errors()))
    detail = "; ".join(str(issue) for issue in issues)
    return answer(
        render(
            422,
            detail,
            code=REQUEST_INVALID.code,
            params={"detail": detail},
            problems=issues,
            instance=_where(request),
        )
    )


async def domain_error(request: Request, error: Exception) -> JSONResponse:
    """Render a refusal raised anywhere in the domain, at the status its class carries."""
    if not isinstance(error, DomainError):  # pragma: no cover - registered for this class
        return await unhandled(request, error)
    # A refusal that carries a list answers with the list: the problems are the refusal, and
    # the sentence before them only repeats what the caller can read there.
    listed = "; ".join(str(issue) for issue in error.problems)
    problem = render(
        error.status,
        listed or str(error),
        code=error.code,
        params=error.params,
        problems=error.problems,
        instance=_where(request),
    )
    response = answer(problem)
    headers = getattr(error, "headers", None)
    if headers:
        response.headers.update(cast("Mapping[str, str]", headers))
    return response


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
    return answer(render(500, INTERNAL_DETAIL, code=INTERNAL.code, instance=_where(request)))


def install_error_handlers(app: FastAPI) -> None:
    """Install the error envelope and the version header on the application."""
    app.middleware("http")(_stamp_version)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(DomainError, domain_error)
    app.add_exception_handler(Exception, unhandled)
