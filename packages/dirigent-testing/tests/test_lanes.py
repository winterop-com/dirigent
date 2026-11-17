"""A lane with nothing to run against fails when it was asked for, and skips otherwise."""

from types import SimpleNamespace
from typing import cast

import pytest

from dirigent_testing import lane_selected, lane_unavailable


def config(markexpr: str) -> pytest.Config:
    options: dict[str, object] = {"markexpr": markexpr}

    def getoption(name: str, default: object = None) -> object:
        return options.get(name, default)

    return cast("pytest.Config", SimpleNamespace(getoption=getoption))


@pytest.mark.parametrize(
    ("markexpr", "selected"),
    [
        ("s3", True),
        ("s3 or queues", True),
        ("postgres and s3", True),
        ("not postgres and not s3 and not docker and not queues and not load", False),
        ("", False),
        ("s3x", False),
    ],
)
def test_a_lane_is_selected_only_when_the_expression_asks_for_it(markexpr: str, selected: bool) -> None:
    assert lane_selected(config(markexpr), "s3") is selected


def test_a_selected_lane_with_nothing_to_run_against_fails() -> None:
    with pytest.raises(pytest.fail.Exception, match="the s3 lane was selected"):
        lane_unavailable(config("s3"), "s3", "no server")


def test_a_lane_nobody_asked_for_skips() -> None:
    with pytest.raises(pytest.skip.Exception, match="no server"):
        lane_unavailable(config(""), "s3", "no server")
