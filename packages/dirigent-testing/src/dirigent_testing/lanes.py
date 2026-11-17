"""What a lane's fixture does when the service the lane runs against is not there."""

import re
from typing import NoReturn

import pytest


def lane_selected(config: pytest.Config, lane: str) -> bool:
    """Whether the run's marker expression asks for ``lane`` rather than excluding it."""
    expression = str(config.getoption("markexpr", default="") or "")
    return re.search(rf"(?<!not )\b{re.escape(lane)}\b", expression) is not None


def lane_unavailable(config: pytest.Config, lane: str, reason: str) -> NoReturn:
    """Fail when the run selected ``lane``, so a lane with nothing to run against is red; skip otherwise."""
    if lane_selected(config, lane):
        pytest.fail(f"the {lane} lane was selected and cannot run: {reason}", pytrace=False)
    pytest.skip(reason)
