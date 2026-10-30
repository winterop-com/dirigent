"""The bound on what a YAML stream's aliases add once they are written out."""

import pytest

from dirigent_common import YamlExpansionError, bounded_load, bounded_load_all


def nested(levels: int) -> str:
    """Aliases nested so that each level multiplies the last by nine."""
    rows = ["- &a0 [x, x, x, x, x, x, x, x, x]"]
    rows += [f"- &a{level} [{', '.join([f'*a{level - 1}'] * 9)}]" for level in range(1, levels)]
    return "\n".join(rows) + "\n"


def test_aliases_past_the_value_bound_are_refused() -> None:
    with pytest.raises(YamlExpansionError, match="more than 100,000 values"):
        bounded_load(nested(7))


def test_aliases_past_the_byte_bound_are_refused() -> None:
    text = "a: &a " + "x" * (1024 * 1024) + "\nb: [" + ", ".join(["*a"] * 20) + "]\n"
    with pytest.raises(YamlExpansionError, match="more than 16,777,216 bytes"):
        bounded_load(text)


def test_a_node_holding_itself_is_refused() -> None:
    with pytest.raises(YamlExpansionError, match="contains itself"):
        bounded_load("a: &a [*a]\n")


def test_a_long_chain_of_aliases_is_refused_rather_than_raised_as_a_recursion_error() -> None:
    rows = ["- &a0 [x]"] + [f"- &a{level} [*a{level - 1}]" for level in range(1, 5000)]
    with pytest.raises(YamlExpansionError):
        bounded_load("\n".join(rows) + "\n")


def test_nesting_past_the_stack_is_refused_rather_than_raised_as_a_recursion_error() -> None:
    with pytest.raises(YamlExpansionError, match="nests too deeply"):
        bounded_load("[" * 5000 + "]" * 5000)


def test_the_bound_counts_across_a_stream() -> None:
    document = nested(5)
    with pytest.raises(YamlExpansionError, match="more than 100,000 values"):
        bounded_load_all("---\n".join([document] * 20))


def test_a_few_aliases_load_as_the_values_they_name() -> None:
    assert bounded_load("a: &a [1, 2]\nb: *a\n") == {"a": [1, 2], "b": [1, 2]}
