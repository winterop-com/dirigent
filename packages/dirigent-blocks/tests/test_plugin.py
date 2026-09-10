"""Tests for the built-in block pack's plugin wiring."""

from pluginkit import PluginManager

from dirigent_blocks import BuiltinBlocks, plugin
from dirigent_common import API_VERSION
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

BUILT_IN_BLOCKS = [
    "convert.std",
    "docker.build",
    "docker.compose.down",
    "docker.compose.up",
    "docker.run",
    "filter.jq",
    "git.checkout",
    "http.ready",
    "http.request",
    "kafka.consume",
    "kafka.produce",
    "log.write",
    "map.jq",
    "pipeline.run",
    "rabbitmq.consume",
    "rabbitmq.publish",
    "report.render",
    "shell.run",
    "sql.execute",
    "sql.query",
    "storage.copy",
    "storage.exists",
    "storage.read",
    "storage.write",
    "time.sleep",
    "time.window",
    "transform.jq",
    "validate.schema",
    "value.const",
    "webhook.post",
]

#: The shelf every built-in block declares, which is what a catalog is arranged by.
BUILT_IN_GROUPS = {
    "convert.std": "transform",
    "docker.build": "execute",
    "docker.compose.down": "execute",
    "docker.compose.up": "execute",
    "docker.run": "execute",
    "filter.jq": "transform",
    "git.checkout": "git",
    "http.ready": "http",
    "http.request": "http",
    "kafka.consume": "kafka",
    "kafka.produce": "kafka",
    "log.write": "log",
    "map.jq": "transform",
    "pipeline.run": "execute",
    "rabbitmq.consume": "rabbitmq",
    "rabbitmq.publish": "rabbitmq",
    "report.render": "report",
    "shell.run": "execute",
    "sql.execute": "sql",
    "sql.query": "sql",
    "storage.copy": "storage",
    "storage.exists": "storage",
    "storage.read": "storage",
    "storage.write": "storage",
    "time.sleep": "time",
    "time.window": "time",
    "transform.jq": "transform",
    "validate.schema": "validate",
    "value.const": "value",
    "webhook.post": "webhook",
}

BUILT_IN_NOTIFIERS = ["email", "log", "slack", "webhook"]


def test_the_pack_contributes_the_built_in_blocks() -> None:
    contribution = BuiltinBlocks().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == BUILT_IN_BLOCKS
    assert sorted(connection.id for connection in contribution.connection_kinds) == [
        "docker",
        "email",
        "git",
        "http",
        "kafka",
        "rabbitmq",
        "slack",
        "sql",
        "webhook",
    ]
    assert sorted(notifier.id for notifier in contribution.notifiers) == BUILT_IN_NOTIFIERS


def test_every_built_in_block_declares_the_group_it_shelves_under() -> None:
    contribution = BuiltinBlocks().contribute()
    groups = {operator.spec.id: operator.spec.group for operator in contribution.operators}
    groups.update({sensor.spec.id: sensor.spec.group for sensor in contribution.sensors})
    assert groups == BUILT_IN_GROUPS


def test_only_the_local_execution_blocks_declare_themselves_unsafe() -> None:
    contribution = BuiltinBlocks().contribute()
    unsafe = sorted(operator.spec.id for operator in contribution.operators if operator.spec.local_execution)
    assert unsafe == ["docker.build", "docker.compose.down", "docker.compose.up", "docker.run", "shell.run"]


def test_the_pack_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="builtin")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [BUILT_IN_BLOCKS]


def test_the_pack_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    # The group is shared: every installed dirigent plugin package registers into it, and
    # this workspace also has dirigent-storage-s3 and dirigent-parquet. What matters is that
    # this pack is found.
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("builtin") is not None
