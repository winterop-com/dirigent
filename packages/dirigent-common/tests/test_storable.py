"""Which text a database stores as written, and where in a document the text it would not is."""

import pytest
from pydantic import BaseModel, ValidationError, field_validator

from dirigent_common import validation_issues
from dirigent_common.storable import is_storable, refuse_unstorable, unstorable_at


class Named(BaseModel):
    name: str | None = None

    @field_validator("*")
    @classmethod
    def _storable(cls, value: object) -> object:
        return refuse_unstorable(value)


@pytest.mark.parametrize("text", ["plain", "blå", "\U0001f600", "\\u0000", "\\ud800", ""])
def test_text_a_database_stores_passes(text: str) -> None:
    assert is_storable(text)
    assert Named(name=text).name == text


@pytest.mark.parametrize("text", ["a\x00b", "\ud800", "lone \udfff"])
def test_a_nul_or_half_a_pair_is_refused_under_its_catalogued_code(text: str) -> None:
    assert not is_storable(text)
    with pytest.raises(ValidationError) as refused:
        Named(name=text)
    issues = validation_issues(refused.value.errors())
    assert [(issue.code, issue.location) for issue in issues] == [("validation.text_unstorable", "name")]


def test_every_place_in_a_document_is_named() -> None:
    document = {
        "code": "fine",
        "steps": {"one": {"config": {"args": ["ok", "no\x00"], "nested": {"deep": "\udc80"}}}},
        "bad\x00key": {"under": "\x00 not read"},
    }
    assert unstorable_at(document) == ["steps.one.config.args.1", "steps.one.config.nested.deep", "(document)"]
    assert unstorable_at({"name": "fine", "list": [1, None, True]}) == []
