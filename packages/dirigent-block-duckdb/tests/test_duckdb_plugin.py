"""Tests for the duckdb engine's plugin wiring."""

from pluginkit import PluginManager

from dirigent_block_duckdb import DuckdbEngine, DuckdbEngines, plugin
from dirigent_block_sql import ENGINES_GROUP
from dirigent_block_sql import markers as sql_markers
from dirigent_block_sql.engines import registry
from dirigent_plugin import PROJECT_NAME


def test_the_package_contributes_the_duckdb_engine_and_nothing_else() -> None:
    contributed = DuckdbEngines().engines()
    assert [type(engine) for engine in contributed] == [DuckdbEngine]
    assert [engine.backend for engine in contributed] == ["duckdb"]


def test_the_engine_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(sql_markers)
    manager.register(plugin, name="duckdb")
    collected = [[engine.backend for engine in contributed] for contributed in manager.caller(sql_markers.engines)()]
    assert collected == [["duckdb"]]


def test_the_engine_is_discovered_under_its_entry_point_name() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(sql_markers)
    registered = manager.load_entrypoints(ENGINES_GROUP)
    assert registered >= 1
    assert manager.get_plugin("duckdb") is not None


def test_the_installed_registry_dispatches_the_duckdb_backend_to_this_engine() -> None:
    """What an installed engine package buys: a url naming duckdb has an engine to be driven by."""
    assert isinstance(registry()["duckdb"], DuckdbEngine)
