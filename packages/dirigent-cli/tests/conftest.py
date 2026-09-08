"""Fixtures every CLI test gets."""

from collections.abc import Iterator

import pytest

from dirigent_cli.output import configure


@pytest.fixture(autouse=True)
def _rich_output() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Put the output back to the default after a test that asked for another one.

    The mode is process-wide and a suite runs in one process, so a test that asks for the
    rendering would otherwise hand it to whatever runs next.
    """
    yield
    configure()
