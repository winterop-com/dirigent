"""The two name grammars: what they accept, what they refuse, and how they validate."""

import pytest
from pydantic import BaseModel, ValidationError

from dirigent_common import EntityName, StepName, is_entity_name, is_step_name
from dirigent_common.names import entity_name_error, step_name_error


class Named(BaseModel):
    entity: EntityName
    step: StepName


@pytest.mark.parametrize(
    "value",
    ["a", "daily-climate-load", "a1", "x-1", "load-2024-daily", "a" * 63],
)
def test_entity_names_that_are_accepted(value: str) -> None:
    assert is_entity_name(value)
    assert Named(entity=value, step="ok").entity == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1abc",
        "-abc",
        "abc-",
        "ab--c",
        "Abc",
        "ab_c",
        "ab.c",
        "ab c",
        "http.request",
        "a" * 64,
    ],
)
def test_entity_names_that_are_refused(value: str) -> None:
    assert not is_entity_name(value)
    with pytest.raises(ValidationError):
        Named(entity=value, step="ok")


@pytest.mark.parametrize("value", ["a", "wait_for_drop", "push", "step_1", "a_b_c"])
def test_step_names_that_are_accepted(value: str) -> None:
    assert is_step_name(value)
    assert Named(entity="pipeline", step=value).step == value


@pytest.mark.parametrize("value", ["", "_x", "1x", "Wait", "wait-for-drop", "wait.for", "x" * 64])
def test_step_names_that_are_refused(value: str) -> None:
    assert not is_step_name(value)
    with pytest.raises(ValidationError):
        Named(entity="pipeline", step=value)


def test_the_two_grammars_are_deliberately_disjoint_where_it_matters() -> None:
    assert is_step_name("wait_for_drop") and not is_entity_name("wait_for_drop")
    assert is_entity_name("daily-load") and not is_step_name("daily-load")


def test_the_rejection_messages_say_what_a_name_may_contain() -> None:
    assert "single" in entity_name_error("pipeline name", "Bad Name")
    assert "snake_case" in step_name_error("Bad-Name")
