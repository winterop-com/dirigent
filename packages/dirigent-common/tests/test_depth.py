"""How deep a stored value may nest, and how a deeper one is shown."""

from typing import Any

from pydantic import JsonValue

from dirigent_common.depth import MAX_STORED_DEPTH, nests_past, shown
from dirigent_common.messages import VALUE_NOT_SHOWN


def nested(depth: int) -> list[Any]:
    """A list holding itself ``depth`` levels down."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


def test_a_value_nesting_exactly_the_limit_passes() -> None:
    assert not nests_past(nested(MAX_STORED_DEPTH))
    assert nests_past(nested(MAX_STORED_DEPTH + 1))
    assert not nests_past({"a": nested(MAX_STORED_DEPTH - 1)})
    assert nests_past({"a": nested(MAX_STORED_DEPTH)})
    assert not nests_past("text")
    assert not nests_past({})


def test_a_value_inside_the_limit_is_shown_as_it_is() -> None:
    value: JsonValue = {"a": nested(5)}
    assert shown(value) is value


def test_a_value_past_the_limit_is_cut_where_it_passes_it() -> None:
    value: JsonValue = {"a": nested(10), "b": 1}
    cut = shown(value, limit=4)
    marker = VALUE_NOT_SHOWN.render(limit=4)
    assert cut == {"a": [[[marker]]], "b": 1}
    assert not nests_past(cut, 4)
