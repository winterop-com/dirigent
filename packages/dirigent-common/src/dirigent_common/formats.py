"""The base JSON Schema format checker every validation in dirigent draws from.

A JSON Schema ``format`` keyword only asserts when a validator is given a checker for it;
without one it is an annotation the value ignores. This is the one checker the engine and
the blocks share, so ``format: date-time``, ``uuid`` and the like actually gate -- and it is
the seam a plugin pack later adds its own formats to, which is why it lives in the shared
leaf rather than in any one package.

It seeds from the library's standard formats (the non-GPL extra provides their validators)
and adds dirigent's own. ``regex`` is read without being compiled, and ``uri``, ``iri``, their
references and ``uri-template`` are matched by the ``regex`` package under the evaluation's
deadline, so a check over text a caller chose costs time in step with it and stops with the
evaluation. A predicate that does not run under the deadline, the library's or a pack's, is handed
no text longer than ``MAX_FORMAT_TEXT``, and a longer text fails it.

None of dirigent's own are standard JSON Schema formats, so a tool that does not know them
treats them as annotations and passes anything -- the graceful degradation every non-core
format has; on a dirigent instance they assert. Each guards on a
string first and parses where parsing is more correct than a pattern. The draft is 2020-12.
"""

import base64
import binascii
import re
import uuid
from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Any, Final

import regex
from jsonschema import FormatChecker

from dirigent_common.durations import is_duration
from dirigent_common.schema_values import matches_whole

#: Python's own reader of ``re`` syntax, which ``re.compile`` parses with before it compiles.
_regex_syntax: Any = import_module("re._parser")
_regex_ops: Any = import_module("re._constants")

#: RFC 3986's IPv6address, as the library's ``uri`` check spells it.
_IPV6: Final[str] = import_module("rfc3986_validator").IPv6_RE

#: A Crockford base32 ULID: 26 characters, the first at most ``7`` so the timestamp fits 48 bits.
_ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")

#: Hex digests, by their fixed nibble length; a digest is hex of either case.
_HEX = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

#: The longest text ``format: regex`` reads as a pattern, or a predicate that does not run under
#: the evaluation's deadline is handed. A longer text fails the format.
MAX_FORMAT_TEXT: Final = 8192

_URI_TEMPLATE_VARIABLE: Final = (
    r"[a-zA-Z0-9_](?:[a-zA-Z0-9_./]|%[0-9A-Fa-f]{2})*+"
    r"(?::(?=0{0,2}[1-9])[0-9]{1,3}+|\*|\[\])?"
    r"(?:=[^,}]*+)?"
)

#: What the library's ``uri-template`` check takes: RFC 6570's expressions, with its own extensions
#: of a default, a comma operator, a trailing joiner and a ``name/key``, between literals that hold
#: no brace. Every repetition is possessive, so the match costs time in step with the text.
_URI_TEMPLATE: Final = regex.compile(
    rf"[^{{}}]*+(?:\{{(?:[+#./;?&]|,\+?)?{_URI_TEMPLATE_VARIABLE}(?:,{_URI_TEMPLATE_VARIABLE})*+[,./;&]?\}}[^{{}}]*+)*+",
    regex.VERSION0,
)

#: RFC 3987's ``ucschar``: the characters past ASCII an IRI may hold unescaped.
_UCSCHAR: Final = "\u00a0-\ud7ff\uf900-\ufdcf\ufdf0-\uffef" + "".join(
    f"{chr(plane * 0x10000 + (0x1000 if plane == 14 else 0))}-{chr(plane * 0x10000 + 0xFFFD)}" for plane in range(1, 15)
)

#: RFC 3987's ``iprivate``, which only an IRI's query may hold.
_IPRIVATE: Final = "\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd"


def _reference_patterns(wide: str, private: str) -> tuple["regex.Pattern[str]", "regex.Pattern[str]"]:
    """Compile RFC 3986's URI and URI-reference, or with ``wide`` and ``private`` RFC 3987's IRI forms.

    Every repetition is possessive: none of them holds the character that ends it, so giving
    one back can never let the rest match, and the match costs time in step with the text.
    """
    unreserved = rf"a-zA-Z0-9_.~\-{wide}"
    sub = r"!$&'()*+,;="
    pct = r"%[0-9A-Fa-f]{2}"
    octet = r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)"
    authority = (
        rf"(?:(?:[{unreserved}{sub}:]|{pct})*+@)?"
        rf"(?:\[(?:{_IPV6}|v[0-9A-Fa-f]+\.[a-zA-Z0-9_.~\-{sub}:]+)\]"
        rf"|(?:{octet}\.){{3}}{octet}"
        rf"|(?:[{unreserved}{sub}]|{pct})*+)"
        r"(?::[0-9]*+)?"
    )
    pchar = rf"(?:[{unreserved}{sub}:@]|{pct})"
    segments = rf"(?:/{pchar}*+)*+"
    tail = rf"(?:\?(?:{pchar}|[/?{private}])*+)?(?:\#(?:{pchar}|[/?])*+)?"
    absolute = rf"/(?:{pchar}++{segments})?"
    uri = rf"[a-zA-Z][a-zA-Z0-9+.\-]*+:(?://{authority}{segments}|{absolute}|{pchar}++{segments}|){tail}"
    noscheme = rf"(?:[{unreserved}{sub}@]|{pct})++{segments}"
    relative = rf"(?://{authority}{segments}|{absolute}|{noscheme}|){tail}"
    return regex.compile(uri, regex.VERSION0), regex.compile(rf"(?:{uri}|{relative})", regex.VERSION0)


_URI, _URI_REFERENCE = _reference_patterns("", "")
_IRI, _IRI_REFERENCE = _reference_patterns(_UCSCHAR, _IPRIVATE)

#: The operators of a parsed pattern whose argument holds further parsed patterns.
_NESTING: Final = {
    _regex_ops.SUBPATTERN,
    _regex_ops.BRANCH,
    _regex_ops.MAX_REPEAT,
    _regex_ops.MIN_REPEAT,
    _regex_ops.POSSESSIVE_REPEAT,
    _regex_ops.ASSERT,
    _regex_ops.ASSERT_NOT,
    _regex_ops.ATOMIC_GROUP,
    _regex_ops.GROUPREF_EXISTS,
}


def _is_pattern(value: str) -> bool:
    """Whether ``value`` is a pattern Python's ``re`` compiles, read without compiling it.

    The parse costs time in step with the text. A look-behind must have one width, which
    ``re`` checks only when it compiles.
    """
    if len(value) > MAX_FORMAT_TEXT:
        return False
    try:
        pending: list[Any] = [_regex_syntax.parse(value)]
        while pending:
            parsed = pending.pop()
            if not isinstance(parsed, _regex_syntax.SubPattern):
                pending.extend(item for item in parsed if isinstance(item, list | tuple | _regex_syntax.SubPattern))
                continue
            for operator, argument in parsed.data:
                if operator in (_regex_ops.ASSERT, _regex_ops.ASSERT_NOT) and argument[0] < 0:
                    low, high = argument[1].getwidth()
                    if low != high:
                        return False
                if operator in _NESTING:
                    pending.append(argument)
    except (re.error, RecursionError, OverflowError):
        return False
    return True


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


def _within_the_limit(predicate: Callable[[object], bool]) -> Callable[[object], bool]:
    """Fail a text longer than ``MAX_FORMAT_TEXT`` without handing it to ``predicate``."""

    def check(value: object) -> bool:
        if isinstance(value, str) and len(value) > MAX_FORMAT_TEXT:
            return False
        return predicate(value)

    return check


def base_format_checker() -> FormatChecker:
    """Build the format checker dirigent validates values against, standard formats plus its own."""
    checker = FormatChecker()
    checker.checkers = {
        name: (_within_the_limit(predicate), raises) for name, (predicate, raises) in checker.checkers.items()
    }

    @checker.checks("regex")
    def _regex(value: object) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
        """A pattern Python's ``re`` takes, at most ``MAX_FORMAT_TEXT`` characters long."""
        return not isinstance(value, str) or _is_pattern(value)

    for _name, _reference in {
        "uri": _URI,
        "uri-reference": _URI_REFERENCE,
        "iri": _IRI,
        "iri-reference": _IRI_REFERENCE,
        "uri-template": _URI_TEMPLATE,
    }.items():

        @checker.checks(_name)
        def _is_reference(value: object, pattern: "regex.Pattern[str]" = _reference) -> bool:  # pyright: ignore[reportUnusedFunction] - the decorator registers it
            """An RFC 3986 URI, an RFC 3987 IRI or a URI template, matched within the evaluation's deadline."""
            return not isinstance(value, str) or matches_whole(pattern, value)

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
    base stays exactly the standard-plus-dirigent set every call builds. A text longer than
    ``MAX_FORMAT_TEXT`` fails a contributed format without reaching its predicate.
    """
    checker = base_format_checker()
    for name, predicate in contributed.items():
        checker.checks(name, raises=(Exception,))(_within_the_limit(predicate))
    return checker
