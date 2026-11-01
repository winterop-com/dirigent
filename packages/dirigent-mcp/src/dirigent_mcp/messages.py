"""Every refusal the MCP server makes itself, catalogued: the ones no instance sent."""

from dirigent_common import Catalogue

MCP = Catalogue("mcp")

NO_INSTANCE = MCP.define("no_instance", "set {url_env} to the instance, and {token_env} to an API token for it")

NO_CREDENTIAL = MCP.define(
    "no_credential",
    "this call arrived without a bearer token, and every call acts as the caller who presents one",
)
