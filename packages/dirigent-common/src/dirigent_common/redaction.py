"""Keeping a sealed value out of text somebody else reads.

An exception says what it was handed, and an HTTP library refusing a header value says it whole.
Whatever writes such text beside a viewer's reach scrubs it first, with every spelling the value
takes once a library has quoted it.
"""

import json
from collections.abc import Collection
from typing import Final, cast
from urllib.parse import quote, quote_plus

from pydantic import BaseModel, JsonValue, SecretStr

from dirigent_common.types import JsonMap

#: What a scrubbed secret is replaced by, matching the marker the API redacts a connection with.
REDACTED: Final = "***"

#: What the HTTP client leaves unescaped in a query value beyond the unreserved characters.
URL_SAFE_IN_A_QUERY: Final = "!$'()*,;:/?@[]"

#: The shortest secret replaced in an output. An output is data rather than a message about a
#: failure, and a shorter one would take ordinary text with it wherever those characters occur.
MIN_OUTPUT_SPELLING: Final = 4


class Spelling(str):
    """One way a secret reads, which remembers the secret it spells."""

    of: str

    def __new__(cls, text: str, of: str) -> "Spelling":
        """Hold the text and the secret behind it."""
        spelling = super().__new__(cls, text)
        spelling.of = of
        return spelling


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
    return {Spelling(one, secret) for one in written if one}


def could_be_data(secret: str) -> bool:
    """Whether a secret could as well be ordinary data: too short, or made only of letters or only of digits."""
    bare = secret.strip()
    return len(bare) < MIN_OUTPUT_SPELLING or bare.isalpha() or bare.isdigit()


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
    return _replaced(text, _longest_first(secrets))


def scrub_json(value: JsonValue, secrets: Collection[str]) -> JsonValue:
    """Scrub every string in a JSON value, its keys included, leaving its types and its shape as they are."""
    return _walked(value, _longest_first(secrets))


def scrub_output(output: JsonMap, secrets: Collection[str]) -> JsonMap:
    """Scrub a step's output of every spelling of every secret that could not be ordinary data.

    Judged on the secret rather than the spelling, so an encoded spelling of a word cannot change data either.
    """
    kept = [one for one in secrets if not could_be_data(one.of if isinstance(one, Spelling) else one)]
    return cast("JsonMap", scrub_json(cast("JsonValue", output), kept)) if kept else output


def _longest_first(secrets: Collection[str]) -> list[str]:
    """Order secrets so one containing another is replaced whole rather than left in pieces."""
    return sorted((one for one in secrets if one), key=len, reverse=True)


def _replaced(text: str, ordered: list[str]) -> str:
    """Replace every occurrence of each secret, in the order given."""
    for secret in ordered:
        text = text.replace(secret, REDACTED)
    return text


def _walked(value: JsonValue, ordered: list[str]) -> JsonValue:
    """Rebuild a JSON value with every string in it replaced."""
    if isinstance(value, str):
        return _replaced(value, ordered)
    if isinstance(value, list):
        return [_walked(element, ordered) for element in value]
    if isinstance(value, dict):
        return {_replaced(key, ordered): _walked(element, ordered) for key, element in value.items()}
    return value


__all__ = [
    "MIN_OUTPUT_SPELLING",
    "REDACTED",
    "could_be_data",
    "scrub",
    "scrub_json",
    "scrub_output",
    "secrets_of",
    "spellings",
]
