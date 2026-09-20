"""Tests for the storage family's plugin wiring."""

from pluginkit import PluginManager

from dirigent_block_storage import StorageBlocks, plugin
from dirigent_common import API_VERSION
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

STORAGE_BLOCKS = [
    "storage.copy",
    "storage.exists",
    "storage.read",
    "storage.write",
]

#: The shelf each block declares, which is what a catalog is arranged by.
STORAGE_GROUPS = {
    "storage.copy": "storage",
    "storage.exists": "storage",
    "storage.read": "storage",
    "storage.write": "storage",
}


def test_the_family_contributes_its_blocks_and_nothing_else() -> None:
    contribution = StorageBlocks().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == STORAGE_BLOCKS
    assert sorted(kind.id for kind in contribution.connection_kinds) == []
    assert sorted(notifier.id for notifier in contribution.notifiers) == []
    assert contribution.storage_backends == []


def test_every_block_declares_the_group_it_shelves_under() -> None:
    contribution = StorageBlocks().contribute()
    groups = {operator.spec.id: operator.spec.group for operator in contribution.operators}
    groups.update({sensor.spec.id: sensor.spec.group for sensor in contribution.sensors})
    assert groups == STORAGE_GROUPS


def test_no_block_here_declares_itself_unsafe() -> None:
    contribution = StorageBlocks().contribute()
    unsafe = sorted(operator.spec.id for operator in contribution.operators if operator.spec.local_execution)
    assert unsafe == []


def test_the_family_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="block-storage")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [STORAGE_BLOCKS]


def test_the_family_is_discovered_under_its_entry_point_name() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    # The group is shared: every installed dirigent plugin package registers into it. What
    # matters is that this family is found under the name its entry point gives it.
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("block-storage") is not None
