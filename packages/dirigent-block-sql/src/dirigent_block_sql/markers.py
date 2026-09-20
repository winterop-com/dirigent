"""The extension point an engine of the ``sql`` family is contributed through."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from dirigent_plugin import extension_point

if TYPE_CHECKING:
    from dirigent_block_sql.engines import SqlEngine

#: The version is part of the group name, so an incompatible contract ships as a new group.
ENGINES_GROUP: Final = "dirigent.sql.engines.v1"


@extension_point
def engines() -> "Sequence[SqlEngine]":
    """Collect the engines a plugin adds to the ``sql`` family, once per process."""
    raise NotImplementedError("an extension point is a declaration; call it via PluginManager.caller(...)")
