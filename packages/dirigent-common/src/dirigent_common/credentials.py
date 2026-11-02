"""Keeping a credential out of a header map, a query map and a URL, and the sealed fields that hold one instead.

What a connection or a step writes there is stored as written and shown to whoever can read it, so
each refuses a name that carries a credential, and a URL refuses a user and a password as well.
``CredentialValue``, ``CredentialHeader``, ``CredentialQuery`` and ``CredentialScheme`` are the
fields that credential goes in.

A header and a query parameter are judged by different rules. A header's name is an interface's
own vocabulary, and one ending in ``key`` or holding ``token`` is a credential unless it is known not
to be. A query parameter's name is any API's data: ``page_token`` and ``sort_key`` are ordinary there.
"""

import re
from collections.abc import Mapping
from typing import Annotated, Any, Final, cast
from urllib.parse import parse_qsl, urlsplit

from pydantic import AfterValidator, Field, SecretStr

from dirigent_common.messages import COMMON

#: What marks a field in a published schema as a header map that refuses a credential.
PLAIN_HEADERS_KEYWORD: Final = "x-dirigent-plain-headers"

#: What marks a field in a published schema as a query map that refuses a credential.
PLAIN_QUERY_KEYWORD: Final = "x-dirigent-plain-query"

#: What marks a field in a published schema as a URL that refuses a credential.
PLAIN_URL_KEYWORD: Final = "x-dirigent-plain-url"

#: The header a credential is sent in when a connection names neither a header nor a query parameter.
DEFAULT_CREDENTIAL_HEADER: Final = "Authorization"

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

#: A word that makes a query parameter's name, read without its separators, that of a credential.
QUERY_CREDENTIAL_COMPOUNDS: Final = (
    "accesskey",
    "accesstoken",
    "apikey",
    "authtoken",
    "clientsecret",
    "idtoken",
    "privatekey",
    "refreshtoken",
    "secretkey",
    "sessionid",
    "sessiontoken",
)

#: A whole word of a query parameter's name that does the same.
QUERY_CREDENTIAL_WORDS: Final = frozenset(
    {
        "auth",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "jwt",
        "passwd",
        "password",
        "pwd",
        "secret",
        "secrets",
    }
)

#: The word before a final ``key`` that makes it a credential; any other key is data.
QUERY_CREDENTIAL_KEYS: Final = frozenset(
    {
        "app",
        "application",
        "client",
        "consumer",
        "dev",
        "developer",
        "function",
        "functions",
        "licence",
        "license",
        "master",
        "sas",
        "service",
        "shared",
        "signing",
        "subscription",
        "user",
    }
)

#: The word before a final ``token`` that makes it a place in a listing; any other token is a credential.
QUERY_PAGING_TOKENS: Final = frozenset(
    {
        "after",
        "batch",
        "before",
        "continuation",
        "continue",
        "cursor",
        "delta",
        "last",
        "list",
        "marker",
        "more",
        "next",
        "offset",
        "page",
        "pagination",
        "paging",
        "prev",
        "previous",
        "resume",
        "scroll",
        "skip",
        "start",
        "sync",
    }
)

#: The first words of a presigned URL's own parameters, which a service hands out for one object for
#: a short time, and which a step reads back from an earlier answer.
QUERY_PRESIGNED_PREFIXES: Final = (("x", "amz"), ("x", "goog"))

#: The same, for the presigned forms with no shared prefix.
QUERY_PRESIGNED_NAMES: Final = frozenset({"awsaccesskeyid", "googleaccessid"})

#: Where a name changes from one word to the next without a separator.
WORD_BOUNDARY: Final = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

#: What separates two words of a name, and a reference standing in a URL at apply.
NOT_A_WORD: Final = re.compile(r"[^a-z0-9]+")

#: What a query parameter a credential is sent as may be called.
QUERY_NAME: Final = re.compile(r"[A-Za-z0-9_.~-]+")

#: What a header's name, or the scheme in front of a credential, may hold, as HTTP defines one.
HTTP_TOKEN: Final = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

#: What a credential may hold: visible ASCII with no whitespace, the only text a header value carries unchanged.
CREDENTIAL_TEXT: Final = re.compile(r"[\x21-\x7e]+")

CREDENTIAL_HEADER_REFUSED = COMMON.define(
    "credential_header_refused",
    "the {header} header carries a credential, and headers are stored as written; put its value in a connection's "
    "credential field, which is sealed, with its name in credential_header unless that is Authorization",
)

CREDENTIAL_PARAMETER_REFUSED = COMMON.define(
    "credential_parameter_refused",
    "the {parameter} query parameter carries a credential, and a query is stored as written; put its value in a "
    "connection's credential field, which is sealed, with its name in credential_query",
)

URL_USERINFO_REFUSED = COMMON.define(
    "url_userinfo_refused",
    "a URL here cannot carry a user or a password, because it is stored as written; put the credential in a "
    "connection's sealed fields",
)

URL_PASSWORD_REFUSED = COMMON.define(
    "url_password_refused",
    "a URL here cannot carry a password, because it is stored as written; put it in the connection's sealed field",
)

CREDENTIAL_TWO_PLACES = COMMON.define(
    "credential_two_places",
    "credential goes in one place: credential_query sends it as a query parameter, so credential_header and "
    "credential_scheme cannot be set beside it",
)

BAD_CREDENTIAL = COMMON.define(
    "bad_credential",
    "a credential must be visible ASCII with no whitespace, or it cannot be sent as a header value; "
    "a scheme such as Bearer goes in credential_scheme",
)

BAD_CREDENTIAL_WORD = COMMON.define(
    "bad_credential_word", "credential_header and credential_scheme must each be one HTTP token"
)

BAD_CREDENTIAL_QUERY = COMMON.define(
    "bad_credential_query", "credential_query must be a query parameter's name: letters, digits, and _ . ~ -"
)


def carries_credential(name: str) -> bool:
    """Whether a header's name, in any case and with a hyphen or an underscore, is that of a credential."""
    segments = re.split(r"[-_]", name.lower())
    if any(word in "".join(segments) for word in CREDENTIAL_WORDS) or CREDENTIAL_SEGMENTS.intersection(segments):
        return True
    return segments[-1] == "key" and (len(segments) == 1 or segments[-2] not in ADDRESSING_KEYS)


def carries_credential_parameter(name: str) -> bool:
    """Whether a query parameter's name, in any case and any separator or none, is that of a credential.

    Paging names such as ``page_token`` and ``nextToken``, a bare ``key``, ``sort_key`` and a presigned
    URL's own parameters are not.
    """
    words = [word for word in NOT_A_WORD.split(WORD_BOUNDARY.sub(" ", name).lower()) if word]
    if not words:
        return False
    compact = "".join(words)
    if compact in QUERY_PRESIGNED_NAMES or tuple(words[:2]) in QUERY_PRESIGNED_PREFIXES:
        return False
    if any(word in compact for word in QUERY_CREDENTIAL_COMPOUNDS) or QUERY_CREDENTIAL_WORDS.intersection(words):
        return True
    before = words[-2] if len(words) > 1 else ""
    if words[-1] == "token":
        return before not in QUERY_PAGING_TOKENS
    return words[-1] == "key" and before in QUERY_CREDENTIAL_KEYS


def credential_parameter_in(url: str) -> str | None:
    """The first name in a URL's query or fragment that carries a credential, if one does."""
    try:
        split = urlsplit(url)
    except ValueError:
        return None
    for part in (split.query, split.fragment):
        for name, _value in parse_qsl(part, keep_blank_values=True):
            if carries_credential_parameter(name):
                return name
    return None


def userinfo_in(url: str) -> bool:
    """Whether a URL names a user, a password, or both, before its host."""
    try:
        return "@" in urlsplit(url).netloc
    except ValueError:
        return False


def password_in(url: str) -> bool:
    """Whether a URL names a password before its host."""
    try:
        return ":" in urlsplit(url).netloc.rpartition("@")[0]
    except ValueError:
        return False


def refuse_credential_parameter(url: str) -> str:
    """Refuse a URL whose query holds a credential's name, repeating the name and never the value."""
    parameter = credential_parameter_in(url)
    if parameter is not None:
        raise ValueError(CREDENTIAL_PARAMETER_REFUSED.render(parameter=parameter))
    return url


def _refuse_credentials_in_url(url: str) -> str:
    """Refuse a URL carrying a user, a password, or a credential's name in its query."""
    if userinfo_in(url):
        raise ValueError(URL_USERINFO_REFUSED.render())
    return refuse_credential_parameter(url)


def refuse_password_in_url(url: str) -> str:
    """Refuse a URL carrying a password or a credential's name in its query, where a user is not a secret."""
    if password_in(url):
        raise ValueError(URL_PASSWORD_REFUSED.render())
    return refuse_credential_parameter(url)


def _refuse_credential_parameters[Value](query: dict[str, Value]) -> dict[str, Value]:
    """Refuse a query map holding a credential's name, repeating the name and never the value."""
    for name in query:
        if carries_credential_parameter(name):
            raise ValueError(CREDENTIAL_PARAMETER_REFUSED.render(parameter=name))
    return query


def refuse_credential_in_two_places(header: str | None, query: str | None, scheme: str | None) -> None:
    """Refuse a credential told to go in a query parameter and somewhere else as well."""
    if query is not None and (header is not None or scheme is not None):
        raise ValueError(CREDENTIAL_TWO_PLACES.render())


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


def _is_a_query_name(name: str | None) -> str | None:
    """Reject a name that a query parameter cannot be sent under unchanged."""
    if name is not None and QUERY_NAME.fullmatch(name) is None:
        raise ValueError(BAD_CREDENTIAL_QUERY.render())
    return name


#: A header map that refuses a credential, at validation and, through its schema keyword, at apply.
PlainHeaders = Annotated[
    dict[str, str],
    AfterValidator(_refuse_credentials),
    Field(json_schema_extra={PLAIN_HEADERS_KEYWORD: True}),
]

#: A query map that refuses a credential, at validation and, through its schema keyword, at apply.
PlainQuery = Annotated[
    dict[str, str | int | float | bool],
    AfterValidator(_refuse_credential_parameters),
    Field(json_schema_extra={PLAIN_QUERY_KEYWORD: True}),
]

#: A URL that refuses a user, a password and a credential's name in its query, likewise.
PlainUrl = Annotated[
    str,
    AfterValidator(_refuse_credentials_in_url),
    Field(json_schema_extra={PLAIN_URL_KEYWORD: True}),
]

#: The sealed value of a credential sent in a header or a query parameter.
CredentialValue = Annotated[SecretStr | None, AfterValidator(_fits_a_header)]

#: The header a credential is sent in, ``Authorization`` when neither this nor a query parameter is named.
CredentialHeader = Annotated[str | None, AfterValidator(_is_a_token)]

#: The query parameter a credential is sent as, in place of a header.
CredentialQuery = Annotated[str | None, AfterValidator(_is_a_query_name)]

#: The word sent before a credential in its header.
CredentialScheme = Annotated[str | None, AfterValidator(_is_a_token)]


def plain_fields_of(schema: Mapping[str, Any], keyword: str) -> frozenset[str]:
    """Name the fields a config schema marks with a keyword, itself or on a branch of its union."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return frozenset()
    return frozenset(
        str(name)
        for name, declared in cast("dict[str, Any]", properties).items()
        if isinstance(declared, dict) and _marked(cast("dict[str, Any]", declared), keyword)
    )


def _marked(shape: dict[str, Any], keyword: str) -> bool:
    """Whether a field's schema or a branch of its union carries the keyword."""
    options = cast("list[dict[str, Any]]", shape.get("anyOf") or [])
    return shape.get(keyword) is True or any(_marked(option, keyword) for option in options)


def credential_header_value(credential: str, scheme: str | None) -> str:
    """Write what a credential's header holds: the credential, after its scheme when it has one."""
    return f"{scheme} {credential}" if scheme else credential


__all__ = [
    "BAD_CREDENTIAL",
    "BAD_CREDENTIAL_QUERY",
    "BAD_CREDENTIAL_WORD",
    "CREDENTIAL_HEADER_REFUSED",
    "CREDENTIAL_PARAMETER_REFUSED",
    "CREDENTIAL_TWO_PLACES",
    "DEFAULT_CREDENTIAL_HEADER",
    "PLAIN_HEADERS_KEYWORD",
    "PLAIN_QUERY_KEYWORD",
    "PLAIN_URL_KEYWORD",
    "URL_PASSWORD_REFUSED",
    "URL_USERINFO_REFUSED",
    "CredentialHeader",
    "CredentialQuery",
    "CredentialScheme",
    "CredentialValue",
    "PlainHeaders",
    "PlainQuery",
    "PlainUrl",
    "carries_credential",
    "carries_credential_parameter",
    "credential_header_value",
    "credential_parameter_in",
    "password_in",
    "plain_fields_of",
    "refuse_credential_in_two_places",
    "refuse_credential_parameter",
    "refuse_password_in_url",
    "userinfo_in",
]
