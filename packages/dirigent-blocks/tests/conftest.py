"""Names the packaged fixtures under the shorter ones these tests were written against."""

import pytest

from dirigent_testing import FakeContext, FakeStorage


@pytest.fixture
def storage(block_storage: FakeStorage) -> FakeStorage:
    return block_storage


@pytest.fixture
def ctx(block_ctx: FakeContext) -> FakeContext:
    return block_ctx


@pytest.fixture
def local_ctx(local_block_ctx: FakeContext) -> FakeContext:
    return local_block_ctx
