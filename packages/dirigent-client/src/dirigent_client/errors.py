"""One exception class per condition a caller has to handle differently."""

from typing import Any, Final, cast

from dirigent_client.schemas import Problem

#: The header a dirigent server puts on every response, including its errors.
VERSION_HEADER: Final = "X-Dirigent-Version"


class DirigentError(Exception):
    """A call against a dirigent instance did not produce a result."""

    def __init__(self, message: str, *, status: int = 0, url: str = "", problem: Problem | None = None) -> None:
        """Carry the message, the status, the URL, and the problem the server sent."""
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url
        self.problem = problem

    @property
    def problems(self) -> list[str]:
        """List the individual failures, when the refusal was a list of them rather than one."""
        return list(self.problem.problems) if self.problem else []


class TransportError(DirigentError):
    """The server could not be reached, or the connection failed mid-request."""

    def __init__(self, url: str, error: Exception) -> None:
        """Name the URL that could not be reached."""
        super().__init__(f"cannot reach {url}: {type(error).__name__}: {error}", url=url)
        self.cause = error


class NotDirigent(DirigentError):
    """Something answered, but it was not a dirigent instance."""

    def __init__(self, base_url: str, url: str, content_type: str) -> None:
        """Say what answered and where."""
        described = content_type.split(";")[0].strip() or "no content type"
        super().__init__(
            f"the server at {base_url} does not look like a dirigent instance (got {described} from {url})",
            url=url,
        )
        self.base_url = base_url
        self.content_type = content_type


class Unauthorized(DirigentError):
    """The request carried no credential, or one the instance does not accept."""


class Forbidden(DirigentError):
    """The credential is valid and does not permit this."""


class NotFound(DirigentError):
    """This instance holds no such thing."""


class Conflict(DirigentError):
    """The instance's current state does not allow this."""


class ValidationFailed(DirigentError):
    """The request was well formed and its content was refused, field by field."""


class RateLimited(DirigentError):
    """The instance is refusing this caller for now."""

    def __init__(
        self, message: str, *, status: int, url: str, problem: Problem | None, retry_after: float | None
    ) -> None:
        """Carry how long the server asked the caller to wait, when it said."""
        super().__init__(message, status=status, url=url, problem=problem)
        self.retry_after = retry_after


class ServerError(DirigentError):
    """The instance failed to handle the request; its own log has the detail."""


class WaitTimeout(DirigentError):
    """A run was still running when the caller's patience ran out; it was not cancelled."""


_BY_STATUS: Final[dict[int, type[DirigentError]]] = {
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    422: ValidationFailed,
}


def parse_problem(payload: object) -> Problem | None:
    """Read an error body as the problem shape, or nothing when it is not one."""
    if not isinstance(payload, dict):
        return None
    mapping = cast("dict[str, Any]", payload)
    try:
        return Problem.model_validate(mapping)
    except ValueError:
        return _loose(mapping)


def _loose(mapping: "dict[str, Any]") -> Problem | None:
    """Read a body that carries a detail but not the whole envelope, such as a bare 404."""
    detail = mapping.get("detail")
    if isinstance(detail, str):
        return Problem(status=0, title="Error", detail=detail)
    if isinstance(detail, list):
        rendered = [_one(item) for item in cast("list[object]", detail)]
        return Problem(status=0, title="Error", detail="; ".join(rendered), problems=rendered)
    return None


def _one(item: object) -> str:
    """Render one entry of a problem list, whether it is a string or a pydantic error."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        mapping = cast("dict[str, Any]", item)
        location = ".".join(str(part) for part in mapping.get("loc", []))
        message = str(mapping.get("msg", mapping))
        return f"{location}: {message}" if location else message
    return str(item)


def error_for(status: int, url: str, problem: Problem | None, *, retry_after: float | None = None) -> DirigentError:
    """Build the exception a refusal deserves, from its status and whatever body it carried."""
    detail = problem.detail if problem and problem.detail else f"HTTP {status}"
    if status == 429:
        return RateLimited(detail, status=status, url=url, problem=problem, retry_after=retry_after)
    if status >= 500:
        return ServerError(detail, status=status, url=url, problem=problem)
    return _BY_STATUS.get(status, DirigentError)(detail, status=status, url=url, problem=problem)
