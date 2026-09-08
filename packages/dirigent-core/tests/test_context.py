"""Tests for the client core builds from a connection config it reads structurally."""

import httpx2
from pydantic import BaseModel, SecretStr

from dirigent_core.engine.context import build_http_client


class _TokenConfig(BaseModel):
    """A pack's connection kind that authenticates with a personal access token."""

    base_url: str = "https://play.example/api"
    api_token: SecretStr | None = None


class _SchemedTokenConfig(_TokenConfig):
    """A token connection that names the scheme its token is sent under."""

    api_token_scheme: str = "Bearer"


class _BasicConfig(BaseModel):
    """A connection kind that authenticates with the basic pair alone."""

    base_url: str = "https://play.example/api"
    basic_username: str | None = None
    basic_password: SecretStr | None = None


class _BearerAndTokenConfig(_TokenConfig):
    """A connection kind that names both credential header fields."""

    bearer_token: SecretStr | None = None


class _BareConfig(BaseModel):
    """A connection kind carrying no HTTP fields at all."""

    note: str = "nothing to read"


def test_api_token_is_sent_under_the_default_scheme() -> None:
    """A config carrying only an api_token authorizes with ApiToken."""
    client = build_http_client(_TokenConfig(api_token=SecretStr("d2pat_x")))

    assert client.headers["authorization"] == "ApiToken d2pat_x"
    assert client.auth is None


def test_api_token_scheme_overrides_the_default() -> None:
    """A config that names a scheme has its token sent under that scheme."""
    client = build_http_client(_SchemedTokenConfig(api_token=SecretStr("t")))

    assert client.headers["authorization"] == "Bearer t"


def test_bearer_token_wins_over_an_api_token() -> None:
    """A config carrying both header credentials sends the bearer one."""
    client = build_http_client(_BearerAndTokenConfig(api_token=SecretStr("t"), bearer_token=SecretStr("b")))

    assert client.headers["authorization"] == "Bearer b"


def test_empty_api_token_authorizes_nothing() -> None:
    """An api_token present but empty leaves the client unauthenticated."""
    client = build_http_client(_TokenConfig(api_token=SecretStr("")))

    assert "authorization" not in client.headers


def test_basic_credentials_stay_basic_auth() -> None:
    """A config carrying only the basic pair gets httpx basic auth and no header."""
    client = build_http_client(_BasicConfig(basic_username="admin", basic_password=SecretStr("district")))

    assert isinstance(client.auth, httpx2.BasicAuth)
    assert "authorization" not in client.headers


def test_a_config_naming_no_fields_gets_a_bare_client() -> None:
    """A connection kind with none of the standard fields still yields a usable client."""
    client = build_http_client(_BareConfig())

    assert client.auth is None
    assert "authorization" not in client.headers
