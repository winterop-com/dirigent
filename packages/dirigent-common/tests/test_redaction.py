"""What a secret looks like once a library has quoted it, and scrubbing it out of the text."""

from pydantic import BaseModel, JsonValue, SecretStr

from dirigent_common import REDACTED, raised_detail, scrub, scrub_json, secrets_of, spellings


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
