"""The DuckDB engine of dirigent's ``sql`` family, contributed to the family's engine registry."""

from collections.abc import Sequence

from dirigent_block_sql import SqlEngine
from dirigent_block_sql_duckdb.engine import DuckdbEngine
from dirigent_plugin import extension


class DuckdbEngines:
    """The plugin object the family discovers under the dirigent.sql.engines.v1 entry-point group."""

    @extension
    def engines(self) -> Sequence[SqlEngine]:
        """Contribute the duckdb engine, which a url naming the duckdb backend is driven through."""
        return [DuckdbEngine()]


plugin = DuckdbEngines()

__all__ = [
    "DuckdbEngine",
    "DuckdbEngines",
    "plugin",
]
