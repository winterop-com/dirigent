"""The base format checker: standard formats plus dirigent's own."""

import time
import uuid
from datetime import timedelta

import pytest

from dirigent_common import base_format_checker, format_checker_with
from dirigent_common.formats import MAX_FORMAT_REGEX
from dirigent_common.schema_values import EvaluationOverrun, ValueValidator, bounded_evaluation

# A UUID whose version nibble is 7 and 4 respectively, both with a valid variant.
UUID7 = "018f6d8e-1a2b-7c3d-8e4f-0123456789ab"
UUID4 = str(uuid.uuid4())


@pytest.fixture
def checker() -> object:
    return base_format_checker()


def conforms(checker: object, value: object, fmt: str) -> bool:
    return checker.conforms(value, fmt)  # type: ignore[attr-defined,no-any-return]


def test_ulid_asserts_and_is_case_insensitive(checker: object) -> None:
    assert conforms(checker, "01ARZ3NDEKTSV4RRFFQ69G5FAV", "ulid")
    assert conforms(checker, "01arz3ndektsv4rrffq69g5fav", "ulid")
    assert not conforms(checker, "01ARZ3NDEKTSV4RRFFQ69G5FA", "ulid")  # 25 chars
    assert not conforms(checker, "01ARZ3NDEKTSV4RRFFQ69G5FAI", "ulid")  # I is not base32
    assert not conforms(checker, 123, "ulid")


def test_version_pinned_uuids_assert_their_version(checker: object) -> None:
    assert conforms(checker, UUID7, "uuid7")
    assert not conforms(checker, UUID4, "uuid7")
    assert conforms(checker, UUID4, "uuid4")
    assert not conforms(checker, UUID7, "uuid4")
    assert not conforms(checker, "not-a-uuid", "uuid7")


def test_the_hex_digests_assert_their_length(checker: object) -> None:
    assert conforms(checker, "d41d8cd98f00b204e9800998ecf8427e", "md5")
    assert conforms(checker, "da39a3ee5e6b4b0d3255bfef95601890afd80709", "sha1")
    assert conforms(checker, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "sha256")
    assert not conforms(checker, "d41d8cd98f00b204e9800998ecf8427e", "sha1")  # md5 length under sha1
    assert not conforms(checker, "xyz", "md5")


def test_base64_asserts_and_accepts_the_empty_string(checker: object) -> None:
    assert conforms(checker, "aGVsbG8=", "base64")
    assert conforms(checker, "", "base64")
    assert not conforms(checker, "not base64!!", "base64")


def test_a_standard_format_asserts_too(checker: object) -> None:
    """The nongpl extra provides the validators, so date-time actually asserts."""
    assert conforms(checker, "2026-01-01T00:00:00Z", "date-time")
    assert not conforms(checker, "not a date", "date-time")


def test_the_assembled_checker_has_base_formats_and_contributed_ones() -> None:
    """One host builds one checker: the base formats plus every contributed predicate."""
    assembled = format_checker_with({"even-digits": lambda value: isinstance(value, str) and len(value) % 2 == 0})
    assert conforms(assembled, UUID7, "uuid7")  # a base format still asserts
    assert conforms(assembled, "abcd", "even-digits")
    assert not conforms(assembled, "abc", "even-digits")


def test_humane_duration_asserts_what_a_document_writes(checker: object) -> None:
    """A name of dirigent's own, because the standard ``duration`` names ISO 8601."""
    assert conforms(checker, "5m", "humane-duration")
    assert conforms(checker, "1h30m", "humane-duration")
    assert conforms(checker, "300", "humane-duration")
    assert not conforms(checker, "PT5M", "humane-duration")
    assert not conforms(checker, "-5m", "humane-duration")
    assert not conforms(checker, 300, "humane-duration")
    assert conforms(checker, "PT5M", "duration"), "the standard format is left as the library defines it"


def test_a_contributed_predicate_that_raises_reads_as_invalid() -> None:
    """A predicate may raise to signal invalid, exactly as jsonschema's own checks may."""

    def strict(value: object) -> bool:
        raise ValueError("nope")

    assembled = format_checker_with({"strict": strict})
    assert not conforms(assembled, "anything", "strict")


def test_assembly_does_not_mutate_the_base_checker() -> None:
    """The base checker stays the standard-plus-dirigent set; a contributed format lands only on the copy."""
    base = base_format_checker()
    before = set(base.checkers)
    format_checker_with({"even-digits": lambda value: True})
    assert "even-digits" not in before
    assert "even-digits" not in set(base.checkers)


#: Text that stdlib ``re`` takes seconds to compile, in step with its length.
SLOW_TO_COMPILE = "[a-\uffff]" * 2000


def test_regex_reads_a_pattern_without_compiling_it(checker: object) -> None:
    assert conforms(checker, r"^[a-z]+(?:-[a-z]+)*$", "regex")
    assert conforms(checker, r"(?P<x>a)(?P=x)", "regex")
    assert conforms(checker, r"(?<=ab)c", "regex")
    assert conforms(checker, 12, "regex")
    assert not conforms(checker, "a{3,2}", "regex")
    assert not conforms(checker, r"(a)\2", "regex")
    assert not conforms(checker, "(?<=a+)b", "regex"), "re refuses a look-behind of no fixed width"
    assert not conforms(checker, "(?<!ab|c)d", "regex")
    assert not conforms(checker, "a{99999999999999999999}", "regex")
    assert not conforms(checker, "(?:" * 2000 + "a" + ")" * 2000, "regex")


def test_regex_refuses_text_past_its_limit_before_reading_it(checker: object) -> None:
    started = time.monotonic()
    assert not conforms(checker, SLOW_TO_COMPILE, "regex")
    assert conforms(checker, "a" * MAX_FORMAT_REGEX, "regex")
    assert time.monotonic() - started < 0.5, "stdlib re takes seconds over this text"


def test_a_counted_repeat_costs_nothing_to_check(checker: object) -> None:
    """The regex package expands a counted repeat when it compiles; this check never compiles."""
    started = time.monotonic()
    assert conforms(checker, "a{4294967294}", "regex")
    assert conforms(checker, "(?:(?:a{65535}){65535}){65535}", "regex")
    assert time.monotonic() - started < 0.5


def test_uri_and_iri_assert_their_rfcs(checker: object) -> None:
    assert conforms(checker, "https://user@example.org:8080/a/b?q=1#frag", "uri")
    assert conforms(checker, "urn:isbn:0451450523", "uri")
    assert conforms(checker, "http://[::1]/", "uri")
    assert not conforms(checker, "/relative", "uri")
    assert not conforms(checker, "http://exa mple.org", "uri")
    assert conforms(checker, "/relative?x#y", "uri-reference")
    assert conforms(checker, "", "uri-reference")
    assert not conforms(checker, "http://ex\u00e4mple.org", "uri")
    assert conforms(checker, "http://ex\u00e4mple.org/\u00fc", "iri")
    assert conforms(checker, "http://example.org/\U0001f600", "iri"), "RFC 3987 takes every plane's ucschar"
    assert conforms(checker, "a:?\ue000", "iri"), "a private-use character may sit in the query"
    assert not conforms(checker, "a:/\ue000", "iri"), "and nowhere else"
    assert conforms(checker, "\u00fc/x", "iri-reference")
    assert not conforms(checker, "a b", "iri-reference")
    assert conforms(checker, 12, "iri")


@pytest.mark.parametrize("fmt", ["uri", "uri-reference", "iri", "iri-reference"])
def test_a_long_reference_costs_time_in_step_with_it(checker: object, fmt: str) -> None:
    """A parser that takes seconds over twenty thousand characters is not one a caller may feed."""
    started = time.monotonic()
    for text in ("PT1H" * 5000, "//" + "%41" * 7000 + "[", "a:" + "/a" * 10000 + " "):
        conforms(checker, text, fmt)
    assert time.monotonic() - started < 2


def test_a_reference_check_stops_at_the_evaluation_deadline(checker: object) -> None:
    validator = ValueValidator({"format": "iri-reference"}, format_checker=checker)
    started = time.monotonic()
    with pytest.raises(EvaluationOverrun), bounded_evaluation(timedelta(milliseconds=300)):
        validator.validate("PT1H" * 5_000_000)
    assert time.monotonic() - started < 2
