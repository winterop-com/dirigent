"""The one place a request is made, authenticated, retried, and turned into an exception."""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Final, Self

import httpx2

from dirigent_client.errors import (
    VERSION_HEADER,
    DirigentError,
    NotDirigent,
    TransportError,
    error_for,
    parse_problem,
)

#: Where the API is unless an instance says otherwise. A server that sets ``api_prefix``
#: serves it somewhere else, and a connection has to be told the same thing.
API_PREFIX: Final = "/api/v1"


def _normalise_prefix(prefix: str) -> str:
    """Spell a prefix the one way the server spells it: a leading slash, no trailing one.

    The server normalises its own setting the same way, so a connection configured by hand
    with "api/v1" or "/api/v1/" addresses the same instance as one configured with neither.
    """
    trimmed = prefix.strip().strip("/")
    return f"/{trimmed}" if trimmed else ""


DEFAULT_TIMEOUT: Final = 30.0
DEFAULT_RETRIES: Final = 2
BACKOFF_SECONDS: Final = 0.25
BACKOFF_MAX_SECONDS: Final = 4.0

#: A POST or a PATCH can have taken effect before the connection broke, so repeating one
#: risks a second run, a second token, a second account.
IDEMPOTENT_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


def backoff_for(attempt: int) -> float:
    """Say how long to wait before the given retry."""
    return min(BACKOFF_SECONDS * 2.0**attempt, BACKOFF_MAX_SECONDS)


def _retry_after(response: httpx2.Response) -> float | None:
    """Read a Retry-After header as seconds, ignoring the HTTP-date spelling of it."""
    raw: str | None = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class Transport:
    """An authenticated connection to one instance."""

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        headers: Mapping[str, str] | None = None,
        http_transport: httpx2.AsyncBaseTransport | None = None,
        api_prefix: str = API_PREFIX,
    ) -> None:
        """Open a connection pool bound to one base URL and one credential."""
        self.url = url.rstrip("/")
        self.api_prefix = _normalise_prefix(api_prefix)
        self.retries = retries
        sent = {**(headers or {})}
        if token:
            sent["Authorization"] = f"Bearer {token}"
        self._client = httpx2.AsyncClient(
            base_url=self.url,
            headers=sent,
            timeout=timeout,
            transport=http_transport,
        )

    def session_cookie(self, name: str) -> str | None:
        """Read a cookie the instance set on this connection, or report that it set none."""
        return self._client.cookies.get(name)

    def present(self, secret: str) -> None:
        """Present this credential on every later request of this connection.

        A session arrives as a cookie, and a cookie the instance marked ``Secure`` is never
        sent back over plain HTTP -- so a client that relied on the jar could log in and then
        be refused by the next call. A client is not a browser: it holds the credential
        either way, and presenting it as a bearer token is what makes a session usable
        wherever a token is.
        """
        self._client.headers["Authorization"] = f"Bearer {secret}"

    async def __aenter__(self) -> Self:
        """Enter the connection's context."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the underlying connection pool."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.aclose()

    def endpoint(self, path: str, *, prefixed: bool = True) -> str:
        """Render one API path as the absolute URL it is fetched from."""
        return f"{self.url}{self.api_prefix if prefixed else ''}{path}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        prefixed: bool = True,
        accept: tuple[int, ...] = (),
        **kwargs: Any,
    ) -> httpx2.Response:
        """Make one authenticated request, retrying what is safe and raising what is not."""
        target = f"{self.api_prefix if prefixed else ''}{path}"
        sent: dict[str, Any] = dict(kwargs)
        if timeout is not None:
            sent["timeout"] = timeout
        retryable = method.upper() in IDEMPOTENT_METHODS
        attempts = self.retries + 1 if retryable else 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = await self._client.request(method, target, **sent)
            except httpx2.HTTPError as error:
                if last:
                    raise TransportError(self.url, error) from error
                await asyncio.sleep(backoff_for(attempt))
                continue
            if response.status_code in accept:
                return response
            if response.status_code >= 500 and not last:
                await response.aclose()
                await asyncio.sleep(backoff_for(attempt))
                continue
            if response.status_code >= 400:
                raise self._refusal(response, target)
            return response
        raise DirigentError("the request was never made", url=self.endpoint(path))  # pragma: no cover

    def _refusal(self, response: httpx2.Response, target: str) -> DirigentError:
        """Turn an error response into the exception its status and body deserve."""
        if VERSION_HEADER not in response.headers:
            return NotDirigent(self.url, target, response.headers.get("content-type", ""))
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return error_for(
            response.status_code,
            f"{self.url}{target}",
            parse_problem(payload),
            retry_after=_retry_after(response),
        )

    async def json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make one request and return its parsed body, or nothing when it answered 204."""
        response = await self.request(method, path, **kwargs)
        return None if response.status_code == 204 else response.json()

    async def text(self, path: str, **kwargs: Any) -> str:
        """GET a path that answers with text rather than JSON, such as an export."""
        return (await self.request("GET", path, **kwargs)).text

    @asynccontextmanager
    async def stream(self, path: str, **kwargs: Any) -> AsyncGenerator[httpx2.Response]:
        """Open a streaming GET, held open for as long as the caller reads it."""
        target = f"{self.api_prefix}{path}"
        try:
            async with self._client.stream("GET", target, timeout=None, **kwargs) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise self._refusal(response, target)
                yield response
        except httpx2.HTTPError as error:
            raise TransportError(self.url, error) from error
