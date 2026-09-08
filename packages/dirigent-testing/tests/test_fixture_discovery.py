"""Installing the package is the whole setup: no conftest in this directory re-exports anything."""

import pytest

from dirigent_testing import FakeContext, FakeStorage


def test_pytest_loaded_the_package_as_a_plugin(request: pytest.FixtureRequest) -> None:
    assert request.config.pluginmanager.hasplugin("dirigent_testing")


def test_the_fixtures_arrive_wired_to_each_other(block_ctx: FakeContext, block_storage: FakeStorage) -> None:
    assert block_ctx.storage is block_storage
    assert block_ctx.scratch == "file://scratch"
