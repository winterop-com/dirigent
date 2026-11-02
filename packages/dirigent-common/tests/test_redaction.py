"""What a secret looks like once a library has quoted it, and scrubbing it out of the text."""

import json
from urllib.parse import quote, quote_plus

import pytest
from pydantic import BaseModel, JsonValue, SecretStr

from dirigent_common import (
    MIN_OUTPUT_SPELLING,
    REDACTED,
    raised_detail,
    scrub,
    scrub_json,
    scrub_output,
    secrets_of,
    spellings,
)


class Holding(BaseModel):
    plain: str = "shown"
    token: SecretStr | None = None
    other: SecretStr | None = None


def test_every_spelling_a_library_quotes_is_scrubbed() -> None:
    secret = "DUMMY-token\n"
    for said in (
        f"Illegal header value b'Bearer {secret!r}'",
        f"value {secret}",
        f"value {secret.strip()}",
        f"Illegal header value {repr(('Bearer ' + secret).encode())}",
    ):
        assert "DUMMY-token" not in scrub(said, spellings(secret)), said


def test_a_secret_percent_encoded_or_json_escaped_is_scrubbed() -> None:
    secret = 'pa ss/wörd"\n'
    for said in (
        f"amqp://user:{quote(secret)}@broker/",
        f"amqp://user:{quote(secret, safe='')}@broker/",
        f"https://host/?token={quote_plus(secret)}",
        f"body was {json.dumps({'value': secret})}",
        f"body was {json.dumps({'value': secret}, ensure_ascii=False)}",
    ):
        scrubbed = scrub(said, spellings(secret))
        assert REDACTED in scrubbed, said
        assert "ss" not in scrubbed, said


def test_a_secret_no_encoder_can_spell_is_still_scrubbed_as_written() -> None:
    secret = "broken\udcff"
    assert scrub(f"value {secret}", spellings(secret)) == f"value {REDACTED}"


def test_a_config_names_the_secrets_it_holds_and_nothing_else() -> None:
    found = secrets_of(Holding(token=SecretStr("DUMMY-a"), other=None))
    assert "DUMMY-a" in found
    assert "shown" not in found


def test_an_empty_secret_scrubs_nothing() -> None:
    assert spellings("") == set()
    assert scrub("text", [""]) == "text"


def test_scrubbing_json_reaches_every_string() -> None:
    held: JsonValue = {"a": ["DUMMY", {"b": "x DUMMY y"}], "DUMMY": 1, "n": None}
    assert scrub_json(held, ["DUMMY"]) == {"a": [REDACTED, {"b": f"x {REDACTED} y"}], REDACTED: 1, "n": None}


def test_a_long_secret_is_scrubbed_before_the_detail_is_cut() -> None:
    secret = "DUMMY" * 1000
    said = raised_detail(ValueError(f"refused {secret}"), redact=[secret])
    assert said == f"refused {REDACTED}"
    assert "DUMMY" not in raised_detail(ValueError(f"{'x' * 3000} {secret}"), redact=[secret])


def test_a_detail_with_nothing_to_redact_is_cut_as_it_was() -> None:
    said = raised_detail(ValueError("x" * 3000))
    assert said.endswith("[truncated, 3000 characters]")


def test_an_output_keeps_its_types_and_its_shape() -> None:
    output: dict[str, JsonValue] = {
        "a": 1,
        "b": 1.5,
        "c": True,
        "d": None,
        "e": [1, "x DUMMY-token", {"DUMMY-token": 2}],
    }
    assert scrub_output(output, spellings("DUMMY-token")) == {
        "a": 1,
        "b": 1.5,
        "c": True,
        "d": None,
        "e": [1, f"x {REDACTED}", {REDACTED: 2}],
    }


def test_an_output_is_not_scrubbed_of_a_spelling_shorter_than_the_minimum() -> None:
    assert MIN_OUTPUT_SPELLING == 4
    assert scrub_output({"said": "a-b a-b-c"}, spellings("a-b")) == {"said": "a-b a-b-c"}
    assert scrub_output({"said": "a-b a-b-c"}, spellings("a-b-c")) == {"said": f"a-b {REDACTED}"}


@pytest.mark.parametrize("word", ["district", "playground", "PlayGround", "blåbær", "123456", " district\n", "a b"])
def test_a_secret_that_could_be_data_changes_no_spelling_of_itself_in_an_output(word: str) -> None:
    every = spellings(word)
    output: dict[str, JsonValue] = {one: [f"said {one}", {one: one}] for one in every}
    assert scrub_output(output, every) == output


@pytest.mark.parametrize("secret", ["district1", "s3cret-Token", "a b c d", "12-34"])
def test_a_mixed_secret_is_replaced_in_every_spelling(secret: str) -> None:
    for one in spellings(secret):
        assert scrub_output({"said": f"x {one} y", f"k{one}": 1}, spellings(secret)) == {
            "said": f"x {REDACTED} y",
            f"k{REDACTED}": 1,
        }


def test_a_word_beside_a_mixed_secret_stays_and_the_mixed_one_goes() -> None:
    held = spellings("district") | spellings("s3cret-Token")
    assert scrub_output({"said": "district s3cret-Token"}, held) == {"said": f"district {REDACTED}"}


def test_a_message_still_loses_a_word_that_is_a_secret() -> None:
    assert scrub("refused district", spellings("district")) == f"refused {REDACTED}"
    assert scrub_json({"said": "district"}, spellings("district")) == {"said": REDACTED}


def test_an_output_with_nothing_to_scrub_is_handed_back_as_it_is() -> None:
    output: dict[str, JsonValue] = {"said": "x"}
    assert scrub_output(output, ()) is output
