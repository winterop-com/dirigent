"""Tests for the execute family's plugin wiring."""

from pluginkit import PluginManager

from dirigent_block_execute import ExecuteBlocks, plugin
from dirigent_common import API_VERSION
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

EXECUTE_BLOCKS = [
    "docker.build",
    "docker.compose.down",
    "docker.compose.up",
    "docker.run",
    "git.checkout",
    "shell.run",
]

#: The shelf each block declares, which is what a catalog is arranged by.
EXECUTE_GROUPS = {
    "docker.build": "execute",
    "docker.compose.down": "execute",
    "docker.compose.up": "execute",
    "docker.run": "execute",
    "git.checkout": "git",
    "shell.run": "execute",
}


def test_the_family_contributes_its_blocks_and_nothing_else() -> None:
    contribution = ExecuteBlocks().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == EXECUTE_BLOCKS
    assert sorted(kind.id for kind in contribution.connection_kinds) == ["docker", "git"]
    assert sorted(notifier.id for notifier in contribution.notifiers) == []
    assert contribution.storage_backends == []


def test_every_block_declares_the_group_it_shelves_under() -> None:
    contribution = ExecuteBlocks().contribute()
    groups = {operator.spec.id: operator.spec.group for operator in contribution.operators}
    groups.update({sensor.spec.id: sensor.spec.group for sensor in contribution.sensors})
    assert groups == EXECUTE_GROUPS


def test_every_block_that_runs_code_on_the_worker_declares_itself_unsafe() -> None:
    contribution = ExecuteBlocks().contribute()
    unsafe = sorted(operator.spec.id for operator in contribution.operators if operator.spec.local_execution)
    assert unsafe == ["docker.build", "docker.compose.down", "docker.compose.up", "docker.run", "shell.run"]


def test_the_family_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="block-execute")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [EXECUTE_BLOCKS]


def test_the_family_is_discovered_under_its_entry_point_name() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    # The group is shared: every installed dirigent plugin package registers into it. What
    # matters is that this family is found under the name its entry point gives it.
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("block-execute") is not None
