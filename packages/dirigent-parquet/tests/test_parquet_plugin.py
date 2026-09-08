"""Tests for the parquet pack's plugin wiring."""

from pluginkit import PluginManager

from dirigent_common import API_VERSION
from dirigent_parquet import ParquetPlugin, plugin
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

PARQUET_BLOCKS = ["convert.arrow"]


def test_the_pack_contributes_the_codec_and_nothing_else() -> None:
    contribution = ParquetPlugin().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == PARQUET_BLOCKS
    assert contribution.connection_kinds == []
    assert contribution.notifiers == []
    assert contribution.storage_backends == []


def test_the_codec_shelves_under_the_transform_group() -> None:
    contribution = ParquetPlugin().contribute()
    assert [operator.spec.group for operator in contribution.operators] == ["transform"]


def test_the_codec_declares_itself_safe() -> None:
    contribution = ParquetPlugin().contribute()
    assert [operator.spec.id for operator in contribution.operators if operator.spec.local_execution] == []


def test_the_pack_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="parquet")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [PARQUET_BLOCKS]


def test_the_pack_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("parquet") is not None
