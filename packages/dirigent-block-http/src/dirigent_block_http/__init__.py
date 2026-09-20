"""The HTTP block family: calling an endpoint, waiting for one, and posting a signed body."""

from dirigent_block_http.connections import HttpConnectionKind
from dirigent_block_http.http import HttpReadySensor, HttpRequestOperator
from dirigent_block_http.webhooks import WebhookPostOperator
from dirigent_plugin import Contribution, extension


class HttpBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the HTTP blocks and the connection kind they are addressed through."""
        return Contribution(
            operators=[HttpRequestOperator(), WebhookPostOperator()],
            sensors=[HttpReadySensor()],
            connection_kinds=[HttpConnectionKind()],
        )


plugin = HttpBlocks()

__all__ = [
    "HttpBlocks",
    "HttpConnectionKind",
    "HttpReadySensor",
    "HttpRequestOperator",
    "WebhookPostOperator",
    "plugin",
]
