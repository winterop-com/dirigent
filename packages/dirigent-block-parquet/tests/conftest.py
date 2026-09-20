"""Shared fixtures: the dirigent-testing doubles under this suite's own names."""

import pytest

from dirigent_testing import FakeContext, FakeStorage


@pytest.fixture
def storage(block_storage: FakeStorage) -> FakeStorage:
    return block_storage


@pytest.fixture
def ctx(block_ctx: FakeContext) -> FakeContext:
    return block_ctx
