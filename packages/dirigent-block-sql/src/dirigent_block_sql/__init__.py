"""The SQL block family: reading and writing a database through one connection kind."""

from dirigent_block_sql.engines import SqlAlchemyEngine, SqlEngine, SqlSession
from dirigent_block_sql.markers import ENGINES_GROUP
from dirigent_block_sql.sql import SqlConnectionConfig, SqlConnectionKind, SqlExecuteOperator, SqlQueryOperator
from dirigent_plugin import Contribution, extension


class SqlBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the two SQL blocks and the connection kind that addresses a database."""
        return Contribution(
            operators=[SqlQueryOperator(), SqlExecuteOperator()],
            connection_kinds=[SqlConnectionKind()],
        )


plugin = SqlBlocks()

__all__ = [
    "ENGINES_GROUP",
    "SqlAlchemyEngine",
    "SqlBlocks",
    "SqlConnectionConfig",
    "SqlConnectionKind",
    "SqlEngine",
    "SqlExecuteOperator",
    "SqlQueryOperator",
    "SqlSession",
    "plugin",
]
