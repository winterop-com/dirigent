"""Turning a connection's configuration into the client that talks to it.

The one builder serves a step's ``ctx.http`` and a connection's check alike. It lives beside the
configuration rather than in the standard library of blocks, so an adapter pack can use the
shared HTTP connection without depending on that library.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final

import httpx2
from pydantic import BaseModel, SecretStr

from dirigent_common.credentials import DEFAULT_CREDENTIAL_HEADER, credential_header_value

#: What an HTTP connection is assumed to call its fields, so a client can be built for any
#: connection kind without importing the package that contributed it.
BASE_URL_FIELD: Final = "base_url"
VERIFY_TLS_FIELD: Final = "verify_tls"
FOLLOW_REDIRECTS_WITH_AUTH_FIELD: Final = "follow_redirects_with_auth"
TIMEOUT_FIELD: Final = "timeout"
BEARER_FIELD: Final = "bearer_token"
API_TOKEN_FIELD: Final = "api_token"
API_TOKEN_SCHEME_FIELD: Final = "api_token_scheme"
CREDENTIAL_FIELD: Final = "credential"
CREDENTIAL_HEADER_FIELD: Final = "credential_header"
CREDENTIAL_SCHEME_FIELD: Final = "credential_scheme"
CREDENTIAL_QUERY_FIELD: Final = "credential_query"
BASIC_USER_FIELD: Final = "basic_username"
BASIC_PASSWORD_FIELD: Final = "basic_password"

#: The authorization scheme an ``api_token`` is sent under when the config names none, which
#: is the scheme a personal access token is usually presented with.
DEFAULT_API_TOKEN_SCHEME: Final = "ApiToken"

#: The timeout of a client whose config names none, in seconds.
DEFAULT_HTTP_TIMEOUT: Final = 30.0

#: The header ``bearer_token``, ``api_token`` and basic credentials are sent in.
AUTHORIZATION: Final = "Authorization"


def build_client(config: BaseModel, *, transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
    """Build a client from any connection config that names the standard HTTP fields.

    The fields are read by name, so a config that names none of them gets a bare client.

    A credential is read from one of two fields. ``bearer_token`` is sent as
    ``Authorization: Bearer``; ``api_token`` is sent under the scheme the config's
    ``api_token_scheme`` names, and ``ApiToken`` when it names none, which is the scheme a
    personal access token usually needs. ``bearer_token`` wins if a config carries both.
    ``credential`` is sent in the header ``credential_header`` names, ``Authorization`` when it
    names none, after ``credential_scheme`` when one is set; it wins over either token in the
    same header. ``credential_query`` sends it as that query parameter instead of a header.
    ``basic_username`` and ``basic_password`` become the client's auth, which httpx applies
    per request, so basic credentials beside a token win over the header.

    Every one of these is sent only to the origin of ``base_url``: a request to any other
    origin, such as an absolute link a response handed back, goes without it.

    ``transport`` replaces the network, which is how a test double answers the requests.
    """
    base_url = _text(config, BASE_URL_FIELD) or ""
    configured = getattr(config, TIMEOUT_FIELD, None)
    timeout = configured.total_seconds() if isinstance(configured, timedelta) else DEFAULT_HTTP_TIMEOUT
    verify = getattr(config, VERIFY_TLS_FIELD, True)
    headers: dict[str, str] = {}
    bearer = _text(config, BEARER_FIELD)
    api_token = _text(config, API_TOKEN_FIELD)
    if bearer:
        headers[AUTHORIZATION] = f"Bearer {bearer}"
    elif api_token:
        scheme = _text(config, API_TOKEN_SCHEME_FIELD) or DEFAULT_API_TOKEN_SCHEME
        headers[AUTHORIZATION] = f"{scheme} {api_token}"
    credential = _text(config, CREDENTIAL_FIELD)
    credential_header = _text(config, CREDENTIAL_HEADER_FIELD) or DEFAULT_CREDENTIAL_HEADER
    credential_query = _text(config, CREDENTIAL_QUERY_FIELD)
    if credential and not credential_query:
        headers[credential_header] = credential_header_value(credential, _text(config, CREDENTIAL_SCHEME_FIELD))
    auth: httpx2.Auth | None = None
    user = _text(config, BASIC_USER_FIELD)
    if user:
        auth = httpx2.BasicAuth(user, _text(config, BASIC_PASSWORD_FIELD) or "")
    pinned = list(headers)
    if auth is not None and AUTHORIZATION not in pinned:
        pinned.append(AUTHORIZATION)
    hooks: dict[str, list[Callable[..., Any]]] = {"request": []}
    if credential and credential_query:
        hooks["request"].append(CredentialParameterOnOrigin(base_url, credential_query, credential))
    if pinned:
        hooks["request"].append(CredentialOnOrigin(base_url, *pinned))
    if base_url and getattr(config, FOLLOW_REDIRECTS_WITH_AUTH_FIELD, False) is True:
        hooks["request"].append(BaseRedirect(base_url, verify=bool(verify)))
    return httpx2.AsyncClient(
        base_url=base_url,
        headers=headers,
        auth=auth,
        verify=bool(verify),
        timeout=timeout,
        event_hooks=hooks,
        transport=transport,
    )


def _text(config: BaseModel, name: str) -> str | None:
    """Read a field that may be a plain string, a secret, or absent."""
    value: Any = getattr(config, name, None)
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


class CredentialOnOrigin:
    """A request hook that takes credential headers off a request leaving a base URL's origin.

    It runs after a client's auth has set its header, so it removes basic credentials too. A
    client drops ``Authorization`` itself when a redirect changes the origin, and no other
    header. Placed before :class:`BaseRedirect`, it judges a request by the base it was
    addressed under.
    """

    def __init__(self, base_url: str, *headers: str) -> None:
        """Hold the origin the headers may go to."""
        self._origin = _origin_of(httpx2.URL(base_url))
        self._headers = headers

    async def __call__(self, request: httpx2.Request) -> None:
        """Remove the headers from a request to any other origin."""
        if _origin_of(request.url) != self._origin:
            for header in self._headers:
                request.headers.pop(header, None)


class CredentialParameterOnOrigin:
    """A request hook that sets a credential's query parameter on a base URL's origin and removes it elsewhere.

    Set here rather than on the client, so a redirect that stays on the origin keeps it and one that leaves does
    not carry it, whatever the ``Location`` it was told wrote. Placed before :class:`BaseRedirect`, like
    :class:`CredentialOnOrigin`.
    """

    def __init__(self, base_url: str, name: str, value: str) -> None:
        """Hold the origin the parameter may go to, and what it says there."""
        self._origin = _origin_of(httpx2.URL(base_url))
        self._name = name
        self._value = value

    async def __call__(self, request: httpx2.Request) -> None:
        """Set the parameter on a request to the origin, and take it off a request to any other."""
        if _origin_of(request.url) == self._origin:
            request.url = request.url.copy_set_param(self._name, self._value)
        else:
            request.url = request.url.copy_remove_param(self._name)


def _origin_of(url: httpx2.URL) -> tuple[str, str, int | None]:
    """The scheme, host and port a URL is sent to; a default port reads as ``None``."""
    return url.scheme, url.host, url.port


class BaseRedirect:
    """A request hook that sends every request under a base URL to where that base redirects.

    The base is resolved once, on the first request, by following its redirects without a
    credential. Each request is then rewritten onto the resolved base before it is sent, so its
    credential and its method reach the target rather than being dropped or turned into a GET
    by a redirect on the way.
    """

    def __init__(self, base_url: str, *, verify: bool) -> None:
        """Hold the configured base until the first request resolves it."""
        self._base = base_url.rstrip("/")
        self._verify = verify
        self._resolved: str | None = None

    async def __call__(self, request: httpx2.Request) -> None:
        """Rewrite a request under the configured base onto the resolved one."""
        url = str(request.url)
        if url != self._base and not url.startswith(f"{self._base}/"):
            return
        if self._resolved is None:
            self._resolved = await resolve_base(self._base, verify=self._verify)
        if self._resolved == self._base:
            return
        request.url = httpx2.URL(self._resolved + url[len(self._base) :])
        request.headers["Host"] = request.url.netloc.decode()


async def resolve_base(base_url: str, *, verify: bool) -> str:
    """Follow a base URL's redirects without a credential and answer where the base itself lands.

    The walk stops before a redirect that goes deeper under the base it has reached, on the same
    host: that one is the service sending an anonymous caller somewhere inside itself, such as
    its sign-in page, not the base moving. A base that does not answer is kept as it is.
    """
    base = base_url.rstrip("/")
    try:
        async with httpx2.AsyncClient(verify=verify, timeout=10.0, follow_redirects=True) as probe:
            response = await probe.get(f"{base}/")
    except httpx2.HTTPError:
        return base
    current = httpx2.URL(base)
    for hop in [*(earlier.url for earlier in response.history[1:]), response.url]:
        landed = httpx2.URL(str(hop).rstrip("/"))
        if landed.host == current.host and landed.path.startswith(f"{current.path.rstrip('/')}/"):
            break
        current = landed
    return str(current).rstrip("/")
