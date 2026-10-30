"""Every refusal the http family makes, catalogued under the ``http`` prefix."""

from dirigent_common import Catalogue

HTTP = Catalogue("http")

RESPONSE_TOO_LARGE = HTTP.define(
    "response_too_large",
    "the response is larger than max_response ({limit} bytes) and is not being read; "
    "raise max_response, or ask the endpoint for less",
)

STATUS_REFUSED = HTTP.define("status_refused", "{method} {url} answered {status}")

OFF_ORIGIN = HTTP.define(
    "off_origin",
    "{url} is not on {origin}, the origin of connection {connection}, "
    "and a connection's credentials go only to its own origin",
)

WEBHOOK_STATUS_REFUSED = HTTP.define("webhook.status_refused", "the receiver at {url} answered {status}")

WEBHOOK_NO_SECRET = HTTP.define(
    "webhook.no_secret",
    "connection {connection} has no hmac_secret, so this POST cannot be signed",
)


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

NO_TARGET = HTTP.define("no_target", "an HTTP block needs either a connection or an absolute url")

# What a block's ``check_config`` refuses at apply.

URL_BESIDE_CONNECTION = HTTP.define(
    "url_beside_connection",
    "{field} is an absolute URL beside connection {connection}: a step with a connection "
    "names a path on it, because the connection's credentials go only to its own origin",
)
