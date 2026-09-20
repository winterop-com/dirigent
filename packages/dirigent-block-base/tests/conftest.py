"""Names the packaged fixtures under the shorter ones these tests were written against."""

import pytest

from dirigent_testing import FakeContext


@pytest.fixture
def ctx(block_ctx: FakeContext) -> FakeContext:
    return block_ctx
