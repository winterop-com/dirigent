"""Tests for the HTTP family's plugin wiring."""

from pluginkit import PluginManager

from dirigent_block_http import HttpBlocks, plugin
from dirigent_common import API_VERSION
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

HTTP_BLOCKS = [
    "http.ready",
    "http.request",
    "webhook.post",
]

#: The shelf each block declares, which is what a catalog is arranged by.
HTTP_GROUPS = {
    "http.ready": "http",
    "http.request": "http",
    "webhook.post": "webhook",
}


def test_the_family_contributes_its_blocks_and_nothing_else() -> None:
    contribution = HttpBlocks().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == HTTP_BLOCKS
    assert sorted(kind.id for kind in contribution.connection_kinds) == ["http"]
    assert sorted(notifier.id for notifier in contribution.notifiers) == []
    assert contribution.storage_backends == []


def test_every_block_declares_the_group_it_shelves_under() -> None:
    contribution = HttpBlocks().contribute()
    groups = {operator.spec.id: operator.spec.group for operator in contribution.operators}
    groups.update({sensor.spec.id: sensor.spec.group for sensor in contribution.sensors})
    assert groups == HTTP_GROUPS


def test_no_block_here_declares_itself_unsafe() -> None:
    contribution = HttpBlocks().contribute()
    unsafe = sorted(operator.spec.id for operator in contribution.operators if operator.spec.local_execution)
    assert unsafe == []


def test_the_family_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="block-http")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [HTTP_BLOCKS]


def test_the_family_is_discovered_under_its_entry_point_name() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    # The group is shared: every installed dirigent plugin package registers into it. What
    # matters is that this family is found under the name its entry point gives it.
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("block-http") is not None
