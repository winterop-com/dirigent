"""Every refusal the http family makes, catalogued under the ``http`` prefix."""

from dirigent_common import Catalogue

HTTP = Catalogue("http")

RESPONSE_TOO_LARGE = HTTP.define(
    "response_too_large",
    "the response is larger than max_response ({limit} bytes) and is not being read; "
    "raise max_response, or ask the endpoint for less",
)

STATUS_REFUSED = HTTP.define("status_refused", "{method} {url} answered {status}")

WEBHOOK_STATUS_REFUSED = HTTP.define("webhook.status_refused", "the receiver at {url} answered {status}")

WEBHOOK_NO_SECRET = HTTP.define(
    "webhook.no_secret",
    "connection {connection} has no hmac_secret, so this POST cannot be signed",
)
