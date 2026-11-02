"""Which header names carry a credential, and what a header map does with one."""

import pytest
from pydantic import BaseModel, Field, ValidationError

from dirigent_common import PLAIN_HEADERS_KEYWORD, PlainHeaders, carries_credential, plain_header_fields_of


class _Holder(BaseModel):
    headers: PlainHeaders = Field(default_factory=dict[str, str])
    labels: dict[str, str] = Field(default_factory=dict[str, str])


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
    assert plain_header_fields_of(schema) == {"headers"}
