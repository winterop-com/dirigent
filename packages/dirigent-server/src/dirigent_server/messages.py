"""Every refusal the API makes that no core class already names, catalogued."""

from dirigent_common import Catalogue

SERVER = Catalogue("server")

REQUEST_INVALID = SERVER.define("request_invalid", "{detail}")

HTTP_ERROR = SERVER.define("http", "{detail}")

INTERNAL = SERVER.define("internal", "the server failed to handle this request; the server log has the detail")
