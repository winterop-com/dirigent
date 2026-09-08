"""The base JSON Schema format checker every validation in dirigent draws from.

A JSON Schema ``format`` keyword only asserts when a validator is given a checker for it;
without one it is an annotation the value ignores. This is the one checker the engine and
the blocks share, so ``format: date-time``, ``uuid`` and the like actually gate -- and it is
the seam a plugin pack later adds its own formats to, which is why it lives in the shared
leaf rather than in any one package.

It seeds from the library's standard formats (the non-GPL extra provides their validators)
and adds dirigent's own. None of the ones added here are standard JSON Schema formats, so a
tool that does not know them treats them as annotations and passes anything -- the graceful
degradation every non-core format has; on a dirigent instance they assert. Each guards on a
string first and parses where parsing is more correct than a pattern. The draft is 2020-12.
"""

import base64
import binascii
import re
import uuid
from collections.abc import Callable, Mapping

from jsonschema import FormatChecker

from dirigent_common.durations import is_duration

#: A Crockford base32 ULID: 26 characters, the first at most ``7`` so the timestamp fits 48 bits.
_ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")

#: Hex digests, by their fixed nibble length; a digest is hex of either case.
_HEX = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}


def _is_uuid_version(value: object, version: int) -> bool:
    """Whether the value parses as a UUID of exactly this version."""
    if not isinstance(value, str):
        return False
    try:
        return uuid.UUID(value).version == version
    except ValueError:
        return False


def _is_hex_digest(value: object, length: int) -> bool:
    """Whether the value is a hex string of exactly this many characters."""
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value) is not None


def _is_base64(value: object) -> bool:
    """Whether the value is standard base64. The empty string is valid: it decodes to no bytes."""
    if not isinstance(value, str):
        return False
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return True


def base_format_checker() -> FormatChecker:
    """Build the format checker dirigent validates values against, standard formats plus its own."""
    checker = FormatChecker()

    @checker.checks("ulid")
    def _is_ulid(value: object) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
        """A 26-character Crockford base32 ULID. Canonically uppercase; lowercase decodes too."""
        return isinstance(value, str) and _ULID.fullmatch(value.upper()) is not None

    @checker.checks("uuid4")
    def _is_uuid4(value: object) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
        """A UUID that is specifically version 4 (random)."""
        return _is_uuid_version(value, 4)

    @checker.checks("uuid7")
    def _is_uuid7(value: object) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
        """A UUID that is specifically version 7 (time-ordered) -- what dirigent's own ids are."""
        return _is_uuid_version(value, 7)

    for _name, _length in _HEX.items():

        @checker.checks(_name)
        def _is_digest(value: object, length: int = _length) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
            """A hex digest of the fixed length this algorithm produces, either case."""
            return _is_hex_digest(value, length)

    @checker.checks("humane-duration")
    def _humane_duration(value: object) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
        """A duration in dirigent's spelling, such as ``30s`` or ``1h30m``; never ISO 8601."""
        return is_duration(value)

    @checker.checks("base64")
    def _base64(value: object) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
        """A standard base64 string; the empty string counts, decoding to no bytes."""
        return _is_base64(value)

    return checker


def format_checker_with(contributed: Mapping[str, Callable[[object], bool]]) -> FormatChecker:
    """Build the checker an instance validates against: the base formats plus contributed ones.

    A pack contributes a predicate per format name; a value is invalid when the predicate
    returns False or raises, which is the whole shape of a jsonschema format check. The base
    checker is copied rather than added to, so each host's assembly is its own and the shared
    base stays exactly the standard-plus-dirigent set every call builds.
    """
    checker = base_format_checker()
    for name, predicate in contributed.items():
        checker.checks(name, raises=(Exception,))(predicate)
    return checker
