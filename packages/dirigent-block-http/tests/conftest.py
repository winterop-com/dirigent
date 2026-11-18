"""Names the packaged fixtures under the shorter ones these tests were written against."""

import pytest

from dirigent_common import HttpConnectionConfig
from dirigent_testing import FakeContext


@pytest.fixture
def ctx(block_ctx: FakeContext) -> FakeContext:
    """The packaged context, holding the ``api`` connection the tests address their requests through."""
    block_ctx.connections["api"] = HttpConnectionConfig(base_url="http://service.test")
    return block_ctx
