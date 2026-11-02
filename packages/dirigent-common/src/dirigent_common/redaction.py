"""Keeping a sealed value out of text somebody else reads.

An exception says what it was handed, and an HTTP library refusing a header value says it whole.
Whatever writes such text beside a viewer's reach scrubs it first, with every spelling the value
takes once a library has quoted it.
"""

import json
from collections.abc import Collection
from typing import Final
from urllib.parse import quote, quote_plus

from pydantic import BaseModel, JsonValue, SecretStr

#: What a scrubbed secret is replaced by, matching the marker the API redacts a connection with.
REDACTED: Final = "***"

#: What the HTTP client leaves unescaped in a query value beyond the unreserved characters.
URL_SAFE_IN_A_QUERY: Final = "!$'()*,;:/?@[]"


def spellings(secret: str) -> set[str]:
    """Name every way a secret reads in an error: as it is, trimmed, and as ``repr``, a URL and JSON escape it."""
    raw = secret.encode("utf-8", "surrogateescape")
    written = {
        secret,
        secret.strip(),
        repr(secret)[1:-1],
        repr(secret.strip())[1:-1],
        repr(raw)[2:-1],
        quote(raw),
        quote(raw, safe=""),
        quote_plus(raw),
        quote(raw, safe=URL_SAFE_IN_A_QUERY),
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }
    return {one for one in written if one}


def secrets_of(config: BaseModel) -> set[str]:
    """Name every spelling of every secret an opened config holds."""
    found: set[str] = set()
    for name in type(config).model_fields:
        value = getattr(config, name, None)
        if isinstance(value, SecretStr):
            found |= spellings(value.get_secret_value())
    return found


def scrub(text: str, secrets: Collection[str] = ()) -> str:
    """Replace every occurrence of a secret with the redaction marker.

    A tool prints what it was given. ``git`` echoes a remote URL, an ssh command line and,
    when a credential is wrong, sometimes the credential itself, so a block that hands a
    process a secret hands this the same strings and nothing reaches a log or a failure
    message with them still in it. Longest first, so a secret that contains another is
    replaced whole rather than left in pieces.
    """
    for secret in sorted((one for one in secrets if one), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def scrub_json(value: JsonValue, secrets: Collection[str]) -> JsonValue:
    """Scrub every string in a JSON value, its keys included."""
    if isinstance(value, str):
        return scrub(value, secrets)
    if isinstance(value, list):
        return [scrub_json(element, secrets) for element in value]
    if isinstance(value, dict):
        return {scrub(key, secrets): scrub_json(element, secrets) for key, element in value.items()}
    return value


__all__ = ["REDACTED", "scrub", "scrub_json", "secrets_of", "spellings"]
