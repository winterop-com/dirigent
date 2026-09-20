"""The built-in pack: every block family at once, and the outbound alert channels."""

from dirigent_blocks.notifiers import (
    EmailConnectionKind,
    EmailNotifier,
    SlackConnectionKind,
    SlackNotifier,
    WebhookConnectionKind,
    WebhookNotifier,
)
from dirigent_plugin import Contribution, extension


class BuiltinBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the outbound alert channels and the connection kinds that address them."""
        return Contribution(
            notifiers=[WebhookNotifier(), SlackNotifier(), EmailNotifier()],
            connection_kinds=[WebhookConnectionKind(), SlackConnectionKind(), EmailConnectionKind()],
        )


plugin = BuiltinBlocks()

__all__ = [
    "BuiltinBlocks",
    "EmailConnectionKind",
    "EmailNotifier",
    "SlackConnectionKind",
    "SlackNotifier",
    "WebhookConnectionKind",
    "WebhookNotifier",
    "plugin",
]
