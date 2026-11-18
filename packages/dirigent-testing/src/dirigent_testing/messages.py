"""Every refusal a test double makes, catalogued under the ``testing`` prefix."""

from dirigent_common import Catalogue

TESTING = Catalogue("testing")

TEST_REFUSAL = TESTING.define("refusal", "{detail}")

UNKNOWN_CONNECTION = TESTING.define("unknown_connection", "no connection coded {ref} ({available})")

CONNECTION_WRONG_MODEL = TESTING.define(
    "connection_wrong_model", "connection {ref} is a {installed}, and this reads a {wanted}"
)

UNKNOWN_SCHEMA = TESTING.define("unknown_schema", "no shape coded {code} ({available})")

UNKNOWN_SCHEME = TESTING.define(
    "unknown_scheme", "no storage backend claims scheme {scheme} (registered: {registered})"
)

OUTSIDE_ROOT = TESTING.define("outside_root", "{uri} resolves outside the storage root {root}")
