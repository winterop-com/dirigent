"""What a serving process says about itself: its version, where it answers, and what it loaded.

These are fields on the ``process`` records ``dg dev`` and ``dg server`` emit, so a pipe, a
container's log and a terminal's banner all read the same facts.
"""

from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Any

from dirigent_core import __version__
from dirigent_core.config import Settings
from dirigent_core.plugins import ENTRY_POINT_GROUP

if TYPE_CHECKING:
    from dirigent_core.plugins import PluginHost


def addresses(settings: Settings, bound: str) -> dict[str, Any]:
    """Name every address the instance answers on: the API, the UI when served, the docs, and MCP when enabled."""
    from dirigent_mcp.http import MCP_PATH

    fields: dict[str, Any] = {"api": bound}
    if settings.ui_enabled:
        fields["ui"] = bound
    fields["docs"] = f"{bound}/docs"
    if settings.mcp_enabled:
        fields["mcp"] = f"{bound}{MCP_PATH}"
    return fields


def packs(host: "PluginHost", *, group: str = ENTRY_POINT_GROUP) -> list[dict[str, Any]]:
    """List the distributions whose plugins contributed to this host, each once, by name, with its version.

    A plugin registered without an installed distribution is listed under its plugin name,
    with no version.
    """
    by_plugin: dict[str, EntryPoint] = {entry.name: entry for entry in entry_points(group=group)}
    found: dict[str, dict[str, Any]] = {}
    for plugin in sorted(host.contributions):
        entry = by_plugin.get(plugin)
        distribution = entry.dist if entry is not None else None
        if distribution is None:
            found.setdefault(plugin, {"name": plugin, "version": None})
        else:
            found.setdefault(distribution.name, {"name": distribution.name, "version": distribution.version})
    return sorted(found.values(), key=lambda pack: str(pack["name"]))


def loaded(host: "PluginHost") -> dict[str, Any]:
    """Count what the installed packs contribute: the packs themselves, blocks, connection kinds and source kinds."""
    return {
        "packs": packs(host),
        "blocks": len(host.blocks),
        "connection_kinds": len(host.connection_kinds),
        "source_kinds": len(host.sources),
    }


def facts(settings: Settings, host: "PluginHost", *, process: str, bound: str) -> dict[str, Any]:
    """Gather what a serving process announces once it answers, for its ``ready`` record."""
    return {"process": process, "version": __version__, **addresses(settings, bound), **loaded(host)}
