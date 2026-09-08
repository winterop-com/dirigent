"""Plugin markers and the collecting extension points a dirigent plugin implements."""

from typing import TYPE_CHECKING

from pluginkit import Extension, ExtensionPoint

from dirigent_common import Formatter

if TYPE_CHECKING:
    from dirigent_plugin.blocks import Contribution

PROJECT_NAME = "dirigent"

#: The version is part of the group name, so an incompatible contract ships as a new group.
ENTRY_POINT_GROUP = "dirigent.plugins.v1"

extension_point = ExtensionPoint(PROJECT_NAME)
extension = Extension(PROJECT_NAME)


@extension_point
def contribute() -> "Contribution":
    """Collect everything a plugin adds across the five surfaces, once at host startup."""
    raise NotImplementedError("an extension point is a declaration; call it via PluginManager.caller(...)")


@extension_point
def formatters() -> list[Formatter]:
    """Collect the formatters a plugin adds to ``dg format``, once at CLI startup."""
    raise NotImplementedError("an extension point is a declaration; call it via PluginManager.caller(...)")
