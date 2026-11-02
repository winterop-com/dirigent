"""Keeping a credential out of a header map, and the sealed fields that hold one instead.

A header map in a connection or a step is stored as written and shown to whoever can read it, so
it refuses a name that carries a credential. ``CredentialValue``, ``CredentialHeader`` and
``CredentialScheme`` are the fields that credential goes in.
"""

import re
from collections.abc import Mapping
from typing import Annotated, Any, Final, cast

from pydantic import AfterValidator, Field, SecretStr

from dirigent_common.messages import COMMON

#: What marks a field in a published schema as a header map that refuses a credential.
PLAIN_HEADERS_KEYWORD: Final = "x-dirigent-plain-headers"

#: A word that makes a header's name, read without its separators, the name of a credential.
CREDENTIAL_WORDS: Final = (
    "accesskey",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
)

#: A whole segment of a header's name that does the same.
CREDENTIAL_SEGMENTS: Final = frozenset({"auth", "session"})

#: The segment before a final ``key`` that says the key addresses something rather than unlocks it.
ADDRESSING_KEYS: Final = frozenset({"cache", "dedup", "deduplication", "idempotency", "partition", "routing", "sort"})

#: What a header's name, or the scheme in front of a credential, may hold, as HTTP defines one.
HTTP_TOKEN: Final = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

#: What a credential may hold: visible ASCII with no whitespace, the only text a header value carries unchanged.
CREDENTIAL_TEXT: Final = re.compile(r"[\x21-\x7e]+")

CREDENTIAL_HEADER_REFUSED = COMMON.define(
    "credential_header_refused",
    "the {header} header carries a credential, and headers are stored as written; put its value in a connection's "
    "credential field, which is sealed, with its name in credential_header unless that is Authorization",
)

BAD_CREDENTIAL = COMMON.define(
    "bad_credential",
    "a credential must be visible ASCII with no whitespace, or it cannot be sent as a header value; "
    "a scheme such as Bearer goes in credential_scheme",
)

BAD_CREDENTIAL_WORD = COMMON.define(
    "bad_credential_word", "credential_header and credential_scheme must each be one HTTP token"
)


def carries_credential(name: str) -> bool:
    """Whether a header's name, in any case and with a hyphen or an underscore, is that of a credential."""
    segments = re.split(r"[-_]", name.lower())
    if any(word in "".join(segments) for word in CREDENTIAL_WORDS) or CREDENTIAL_SEGMENTS.intersection(segments):
        return True
    return segments[-1] == "key" and (len(segments) == 1 or segments[-2] not in ADDRESSING_KEYS)


def _refuse_credentials(headers: dict[str, str]) -> dict[str, str]:
    """Refuse a map holding a credential's name, repeating the name and never the value."""
    for name in headers:
        if carries_credential(name):
            raise ValueError(CREDENTIAL_HEADER_REFUSED.render(header=name))
    return headers


def _fits_a_header(credential: SecretStr | None) -> SecretStr | None:
    """Read an empty credential as unset, and reject one that cannot be sent without saying what it held."""
    if credential is None or not credential.get_secret_value():
        return None
    if CREDENTIAL_TEXT.fullmatch(credential.get_secret_value()) is None:
        raise ValueError(BAD_CREDENTIAL.render())
    return credential


def _is_a_token[Word: str | None](word: Word) -> Word:
    """Reject a header name or a scheme that is not an HTTP token."""
    if word is not None and HTTP_TOKEN.fullmatch(word) is None:
        raise ValueError(BAD_CREDENTIAL_WORD.render())
    return word


#: A header map that refuses a credential, at validation and, through its schema keyword, at apply.
PlainHeaders = Annotated[
    dict[str, str],
    AfterValidator(_refuse_credentials),
    Field(json_schema_extra={PLAIN_HEADERS_KEYWORD: True}),
]

#: The sealed value of a credential sent in a header.
CredentialValue = Annotated[SecretStr | None, AfterValidator(_fits_a_header)]

#: The header a credential is sent in.
CredentialHeader = Annotated[str, AfterValidator(_is_a_token)]

#: The word sent before a credential in its header.
CredentialScheme = Annotated[str | None, AfterValidator(_is_a_token)]


def plain_header_fields_of(schema: Mapping[str, Any]) -> frozenset[str]:
    """Name the fields a config schema publishes as a header map that refuses a credential."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return frozenset()
    return frozenset(
        str(name)
        for name, declared in cast("dict[str, Any]", properties).items()
        if isinstance(declared, dict) and cast("dict[str, Any]", declared).get(PLAIN_HEADERS_KEYWORD) is True
    )


def credential_header_value(credential: str, scheme: str | None) -> str:
    """Write what a credential's header holds: the credential, after its scheme when it has one."""
    return f"{scheme} {credential}" if scheme else credential


__all__ = [
    "BAD_CREDENTIAL",
    "BAD_CREDENTIAL_WORD",
    "CREDENTIAL_HEADER_REFUSED",
    "PLAIN_HEADERS_KEYWORD",
    "CredentialHeader",
    "CredentialScheme",
    "CredentialValue",
    "PlainHeaders",
    "carries_credential",
    "credential_header_value",
    "plain_header_fields_of",
]
