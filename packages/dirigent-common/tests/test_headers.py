"""Which header names carry a credential, and what a header map does with one."""

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dirigent_common import (
    OUTPUT_URL_FIELDS,
    PLAIN_HEADERS_KEYWORD,
    PLAIN_QUERY_KEYWORD,
    PLAIN_URL_KEYWORD,
    PlainHeaders,
    PlainQuery,
    PlainUrl,
    carries_credential,
    carries_credential_parameter,
    credential_parameter_values,
    plain_fields_of,
    redact_credential_parameters,
    refuse_password_in_url,
    spellings,
)


class _Holder(BaseModel):
    headers: PlainHeaders = Field(default_factory=dict[str, str])
    labels: dict[str, str] = Field(default_factory=dict[str, str])
    query: PlainQuery = Field(default_factory=dict[str, str | int | float | bool])
    url: PlainUrl | None = None
    path: PlainUrl = "/"


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "authorization",
        "AUTHORIZATION",
        "Proxy-Authorization",
        "X-Authorization",
        "Cookie",
        "Set-Cookie",
        "X-Api-Key",
        "x_api_key",
        "X-APIKEY",
        "Api-Key",
        "XApiKey",
        "X-Auth",
        "X-Auth-Token",
        "X-Amz-Security-Token",
        "X-Client-Secret",
        "X-Password",
        "X-Session-Id",
        "X-Proxy-Key",
        "X-Functions-Key",
        "Ocp-Apim-Subscription-Key",
        "Key",
    ],
)
def test_a_name_that_carries_a_credential(name: str) -> None:
    assert carries_credential(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Accept",
        "Content-Type",
        "User-Agent",
        "X-Correlation-Id",
        "X-GitHub-Api-Version",
        "X-Routing-Key",
        "Idempotency-Key",
        "X-Partition-Key",
        "X-Author",
        "X-Keyboard",
    ],
)
def test_a_name_that_carries_none(name: str) -> None:
    assert carries_credential(name) is False


def test_a_header_map_refuses_a_credential_and_names_where_it_goes() -> None:
    with pytest.raises(ValidationError, match="the X-Api-Key header carries a credential.*credential field"):
        _Holder.model_validate({"headers": {"X-Api-Key": "dummy"}})


def test_a_published_schema_says_which_field_refuses_a_credential() -> None:
    schema = _Holder.model_json_schema()
    assert schema["properties"]["headers"][PLAIN_HEADERS_KEYWORD] is True
    assert plain_fields_of(schema, PLAIN_HEADERS_KEYWORD) == {"headers"}
    assert plain_fields_of(schema, PLAIN_QUERY_KEYWORD) == {"query"}
    assert plain_fields_of(schema, PLAIN_URL_KEYWORD) == {"url", "path"}


@pytest.mark.parametrize(
    "name",
    [
        "access_token",
        "accessToken",
        "ACCESS_TOKEN",
        "auth_token",
        "id_token",
        "refresh_token",
        "token",
        "Token",
        "my_service_token",
        "csrf_token",
        "api_key",
        "api-key",
        "apiKey",
        "apikey",
        "APIKey",
        "x-api-key",
        "subscription-key",
        "app_key",
        "client_secret",
        "clientSecret",
        "secret",
        "password",
        "passwd",
        "pwd",
        "auth",
        "auth[token]",
        "jwt",
        "session_id",
        "sessionId",
    ],
)
def test_a_query_name_that_carries_a_credential(name: str) -> None:
    assert carries_credential_parameter(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "page_token",
        "pageToken",
        "next_page_token",
        "nextPageToken",
        "continuation_token",
        "continuationToken",
        "nextToken",
        "next_token",
        "syncToken",
        "$skiptoken",
        "$deltatoken",
        "cursor",
        "key",
        "Key",
        "sort_key",
        "partition_key",
        "start_key",
        "max_tokens",
        "token_type",
        "session",
        "author",
        "page",
        "per_page",
        "_count",
        "orgUnit",
        "q",
        "X-Amz-Signature",
        "X-Amz-Credential",
        "X-Amz-Security-Token",
        "X-Goog-Credential",
        "AWSAccessKeyId",
        "sig",
        "signature",
    ],
)
def test_a_query_name_that_carries_none(name: str) -> None:
    assert carries_credential_parameter(name) is False


def test_a_query_map_refuses_a_credential_and_names_where_it_goes() -> None:
    with pytest.raises(ValidationError) as refused:
        _Holder.model_validate({"query": {"api_key": "DUMMYSECRET", "page": 1}})
    assert "the api_key query parameter carries a credential" in str(refused.value)
    assert "credential_query" in str(refused.value)


def test_a_query_map_keeps_a_page_token() -> None:
    assert _Holder(query={"page_token": "abc"}).query == {"page_token": "abc"}


@pytest.mark.parametrize(
    ("url", "said"),
    [
        ("https://user:DUMMYSECRET@host/x", "cannot carry a user or a password"),
        ("https://DUMMYSECRET@host/x", "cannot carry a user or a password"),
        ("https://a@b@host/x", "cannot carry a user or a password"),
        ("https://host/x?access_token=DUMMYSECRET", "the access_token query parameter"),
        ("https://host/x?page=1&api%5Fkey=DUMMYSECRET", "the api_key query parameter"),
        ("/x?token=DUMMYSECRET", "the token query parameter"),
        ("https://host/x#access_token=DUMMYSECRET", "the access_token query parameter"),
    ],
)
@pytest.mark.parametrize("field", ["url", "path"])
def test_a_url_refuses_a_credential_without_repeating_it(field: str, url: str, said: str) -> None:
    class Quiet(_Holder):
        model_config = ConfigDict(hide_input_in_errors=True)

    with pytest.raises(ValidationError) as refused:
        Quiet.model_validate({field: url})
    assert said in str(refused.value)
    assert "DUMMYSECRET" not in str(refused.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://host/x",
        "https://host/x?page_token=abc&key=v",
        "https://host/user@example.org",
        "https://host/x?to=a@example.org",
        "https://bucket.s3.amazonaws.com/o?X-Amz-Credential=a&X-Amz-Signature=b",
        "/relative?limit=3",
        "http://[not-a-host",
    ],
)
def test_a_url_holding_no_credential_is_kept(url: str) -> None:
    assert _Holder(url=url).url == url


def test_a_user_alone_passes_where_a_user_is_not_a_secret() -> None:
    assert refuse_password_in_url("amqp://reader@host/v") == "amqp://reader@host/v"
    with pytest.raises(ValueError, match="cannot carry a password"):
        refuse_password_in_url("ssh://reader:DUMMY@host/v")


@pytest.mark.parametrize("secret", ["plain", "a+b/c=d", "a b", "100%", "a&b=c?d#e", "ø"])
def test_a_secret_is_named_as_a_url_sends_it(secret: str) -> None:
    sent = str(httpx2.URL("https://host/x").copy_set_param("k", secret).query, "ascii").removeprefix("k=")
    assert sent in spellings(secret)


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://h/x?token=abc&page=2", "https://h/x?token=***&page=2"),
        ("https://h/x?page_token=abc", "https://h/x?page_token=abc"),
        ("https://h/x?api%5Fkey=a%2Bb#access_token=c", "https://h/x?api%5Fkey=***#access_token=***"),
        ("https://h/x#id_token=c", "https://h/x#id_token=***"),
        ("https://h/token=abc", "https://h/token=abc"),
        ("/x", "/x"),
        ("", ""),
    ],
)
def test_a_url_is_shown_with_its_credential_values_replaced(url: str, shown: str) -> None:
    assert redact_credential_parameters(url) == shown


def test_the_values_a_url_gives_credential_names_are_read_decoded() -> None:
    assert credential_parameter_values("https://h/x?token=a%2Bb&page=2&api_key=") == ["a+b"]


class _Target(BaseModel):
    url: PlainUrl | None = None


def test_a_field_an_earlier_step_supplied_passes_and_any_other_is_told_why_not() -> None:
    link = "https://h/x?token=abc"
    assert _Target.model_validate({"url": link}, context={OUTPUT_URL_FIELDS: {"url"}}).url == link
    with pytest.raises(ValidationError, match="not shown to come from an earlier step"):
        _Target.model_validate({"url": link}, context={OUTPUT_URL_FIELDS: frozenset[str]()})
    with pytest.raises(ValidationError, match="the token query parameter carries a credential"):
        _Target.model_validate({"url": link})


def test_userinfo_is_refused_even_in_a_field_an_earlier_step_supplied() -> None:
    with pytest.raises(ValidationError, match="cannot carry a user or a password"):
        _Target.model_validate({"url": "https://u:p@h/x"}, context={OUTPUT_URL_FIELDS: {"url"}})
