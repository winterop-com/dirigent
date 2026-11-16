"""The coverage exclusions drop stub bodies, never a function that merely mentions an ellipsis."""

import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
EXCLUDED: Final[list[str]] = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["coverage"]["report"][
    "exclude_lines"
]


@pytest.mark.parametrize(
    "line",
    [
        "def _reject_escaping(at: tuple[str, ...] = ()) -> None:",
        "    handler: Callable[..., Awaitable[None]],",
        '    metavar="[FIELD]...",',
        "async def request(self, *parts: str, retry: tuple[int, ...] = (429, 503)) -> Response:",
    ],
)
def test_a_line_that_mentions_an_ellipsis_is_measured(line: str) -> None:
    assert not any(re.search(pattern, line) for pattern in EXCLUDED)


def test_a_stub_body_is_excluded() -> None:
    assert any(re.search(pattern, "        ...") for pattern in EXCLUDED)
