"""Tests for the built-in pack's plugin wiring: the outbound channels it carries itself."""

from pluginkit import PluginManager

from dirigent_blocks import BuiltinBlocks, plugin
from dirigent_common import API_VERSION
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

OUTBOUND_CHANNELS = ["email", "slack", "webhook"]


def test_the_pack_contributes_the_outbound_channels_and_their_connection_kinds() -> None:
    contribution = BuiltinBlocks().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(notifier.id for notifier in contribution.notifiers) == OUTBOUND_CHANNELS
    assert sorted(kind.id for kind in contribution.connection_kinds) == OUTBOUND_CHANNELS


def test_the_pack_contributes_no_block_of_its_own() -> None:
    """Every block is a family's; this package is what installs them all at once."""
    contribution = BuiltinBlocks().contribute()
    assert contribution.block_ids() == []
    assert contribution.storage_backends == []


def test_the_pack_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="builtin")
    contributions = manager.caller(contribute)()
    collected = [sorted(notifier.id for notifier in contribution.notifiers) for contribution in contributions]
    assert collected == [OUTBOUND_CHANNELS]


def test_the_pack_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    # The group is shared: every installed dirigent plugin package registers into it, the
    # seven families included. What matters is that this pack is found.
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("builtin") is not None
