"""One exception class per condition a caller has to handle differently."""

from typing import Any, Final, cast

from dirigent_client.messages import NO_PROBLEM_DOCUMENT, NOT_DIRIGENT, UNREACHABLE
from dirigent_client.schemas import Problem
from dirigent_common import Issue, JsonMap, validation_issues

#: The header a dirigent server puts on every response, including its errors.
VERSION_HEADER: Final = "X-Dirigent-Version"


class DirigentError(Exception):
    """A call against a dirigent instance did not produce a result."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        url: str = "",
        problem: Problem | None = None,
        code: str = "",
        params: JsonMap | None = None,
    ) -> None:
        """Carry the message, the status, the URL, and the problem the server sent."""
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url
        self.problem = problem
        self._code = code
        self._params = params or {}

    @property
    def code(self) -> str:
        """The dotted code of the refusal, from the problem when the server sent one."""
        return self.problem.code if self.problem else self._code

    @property
    def params(self) -> JsonMap:
        """The specifics the refusal rendered, for a re-render in another language."""
        return dict(self.problem.params) if self.problem else dict(self._params)

    @property
    def problems(self) -> list[Issue]:
        """List the individual failures, when the refusal was a list of them rather than one."""
        return list(self.problem.problems) if self.problem else []


class TransportError(DirigentError):
    """The server could not be reached, or the connection failed mid-request."""

    def __init__(self, url: str, error: Exception) -> None:
        """Name the URL that could not be reached."""
        params: JsonMap = {"url": url, "kind": type(error).__name__, "detail": str(error)}
        super().__init__(UNREACHABLE.render(**params), url=url, code=UNREACHABLE.code, params=params)
        self.cause = error


class NotDirigent(DirigentError):
    """Something answered, but it was not a dirigent instance."""

    def __init__(self, base_url: str, url: str, content_type: str) -> None:
        """Say what answered and where."""
        described = content_type.split(";")[0].strip() or "no content type"
        params: JsonMap = {"base_url": base_url, "described": described, "url": url}
        super().__init__(NOT_DIRIGENT.render(**params), url=url, code=NOT_DIRIGENT.code, params=params)
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
        return _synthesised(detail)
    if isinstance(detail, list):
        issues = validation_issues([entry for entry in detail if isinstance(entry, dict)])
        return _synthesised("; ".join(str(issue) for issue in issues), problems=issues)
    return None


def _synthesised(detail: str, *, problems: list[Issue] | None = None) -> Problem:
    """Build the problem a body that is not one stands in as."""
    return Problem(
        status=0,
        title="Error",
        detail=detail,
        code=NO_PROBLEM_DOCUMENT.code,
        params={"detail": detail},
        problems=problems or [],
    )


def error_for(status: int, url: str, problem: Problem | None, *, retry_after: float | None = None) -> DirigentError:
    """Build the exception a refusal deserves, from its status and whatever body it carried."""
    detail = problem.detail if problem and problem.detail else f"HTTP {status}"
    if status == 429:
        return RateLimited(detail, status=status, url=url, problem=problem, retry_after=retry_after)
    if status >= 500:
        return ServerError(detail, status=status, url=url, problem=problem)
    return _BY_STATUS.get(status, DirigentError)(detail, status=status, url=url, problem=problem)
