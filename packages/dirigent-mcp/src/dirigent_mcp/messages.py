"""Every refusal the MCP server makes itself, catalogued: the ones no instance sent."""

from dirigent_common import Catalogue

MCP = Catalogue("mcp")

NO_INSTANCE = MCP.define("no_instance", "set {url_env} to the instance, and {token_env} to an API token for it")

NO_HTTP_INSTANCE = MCP.define(
    "no_http_instance",
    "set {url_env} to the instance; over HTTP each caller presents its own API token as a bearer token",
)

NO_CREDENTIAL = MCP.define(
    "no_credential",
    "this call arrived without a bearer token, and every call acts as the caller who presents one",
)

UNAUTHENTICATED = MCP.define(
    "unauthenticated",
    "authentication required: present an API token for the instance as a bearer token",
)

CROSS_ORIGIN = MCP.define(
    "cross_origin",
    "this MCP request was caused by a page on another origin, which this server does not answer",
)

HOST_NOT_LOOPBACK = MCP.define(
    "host_not_loopback",
    "this server is bound to loopback and answers only to a loopback name, not {host}",
)

REMOTE_BIND_REFUSED = MCP.define(
    "remote_bind_refused",
    "{host} is reachable from other machines; pass --allow-remote to serve MCP there",
)

REMOTE_BIND = MCP.define(
    "remote_bind",
    "serving MCP on {host}, which other machines can reach: put TLS in front of it, since every "
    "request carries an API token",
)
