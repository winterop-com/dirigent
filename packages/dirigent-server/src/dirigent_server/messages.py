"""Every refusal the API makes that no core class already names, catalogued."""

from dirigent_common import Catalogue

SERVER = Catalogue("server")

REQUEST_INVALID = SERVER.define("request_invalid", "{detail}")

HTTP_ERROR = SERVER.define("http", "{detail}")

INTERNAL = SERVER.define("internal", "the server failed to handle this request; the server log has the detail")

UNAUTHENTICATED = SERVER.define("unauthenticated", "authentication required: present a bearer token or log in")

FORBIDDEN = SERVER.define("forbidden", "not permitted for your role")

CROSS_SITE = SERVER.define(
    "cross_site",
    "this write was initiated by another site, and a session cookie may not be spent across "
    "origins; automation authenticating with a bearer token is unaffected",
)

BAD_CREDENTIALS = SERVER.define("bad_credentials", "invalid username or password")

TOO_MANY_LOGINS = SERVER.define(
    "too_many_logins",
    "too many login attempts; this instance accepts {per_minute} a minute",
)

NO_TOKEN = SERVER.define("no_token", "no live token named {name}")

NO_USER_TOKEN = SERVER.define("no_user_token", "no live token named {name} for {username}")

ACCOUNT_GONE = SERVER.define("account_gone", "the authenticated account is gone")

NO_USER = SERVER.define("no_user", "no user named {username}")

NO_NOTIFICATION = SERVER.define("no_notification", "no notification {id}")

NO_ALERT_RULE = SERVER.define("no_alert_rule", "no alert rule coded {code}")

NO_TRIGGER_DOCUMENT = SERVER.define("no_trigger_document", "no triggers document coded {code}")

NO_CONNECTION = SERVER.define("no_connection", "no connection coded {code}")

CONNECTION_EXISTS = SERVER.define("connection_exists", "a connection coded {code} exists")

CONNECTION_REFERENCED = SERVER.define(
    "connection_referenced",
    "connection {code} is still referenced; delete what uses it first",
)

REDACTED_SECRET = SERVER.define(
    "redacted_secret",
    "{fields} came back as {redacted}, which is what a read shows for a secret "
    "that is set, not a secret. Send the real value, or leave the field out to keep what is stored.",
)

UNKNOWN_CONNECTION_KIND = SERVER.define("unknown_connection_kind", "no connection kind {kind} is installed ({known})")

CONNECTION_CONFIG_INVALID = SERVER.define("connection_config_invalid", "{detail}")

NO_SCHEMA = SERVER.define("no_schema", "no schema coded {code}")

SCHEMA_EXISTS = SERVER.define("schema_exists", "a schema coded {code} exists")

DOCUMENT_REFUSED = SERVER.define("document_refused", "{detail}")

PRUNE_NAMES_NOTHING = SERVER.define(
    "prune_names_nothing",
    "keep names no codes, and pruning against an empty set would deactivate every directory pipeline",
)

NO_BLOCK = SERVER.define("no_block", "no block {block_id} is installed")

NO_RUN = SERVER.define("no_run", "no run {run_id}")

RUN_DEFINITION_GONE = SERVER.define("run_definition_gone", "the run's definition is gone")

BAD_SINCE = SERVER.define("bad_since", "{detail}")

NOT_A_DURATION = SERVER.define("not_a_duration", "{since} is not a duration")

NO_ARTIFACT = SERVER.define("no_artifact", "no artifact {artifact_id}")

ARTIFACT_EMPTY = SERVER.define("artifact_empty", "artifact {artifact_id} holds no content")

IDEMPOTENCY_KEY_REQUIRED = SERVER.define(
    "idempotency_key_required",
    "an Idempotency-Key header is required, so a retried request creates one attempt",
)

NO_ATTEMPT = SERVER.define("no_attempt", "no attempt {attempt_id}")

TOO_MANY_TAILS = SERVER.define("too_many_tails", "you already have {maximum} streams open on this server")

NO_ICON = SERVER.define("no_icon", "this bundle carries no icon")

BAD_CURSOR = SERVER.define("bad_cursor", "{name}={after} is not a cursor this listing gave out")

PLAYGROUND_BAD_KNOB = SERVER.define("playground_bad_knob", "{detail}")

PLAYGROUND_HEADER_REFUSED = SERVER.define(
    "playground_header_refused",
    "the playground will not set {header} on itself: a header that plants a cookie, opens "
    "this origin to another site, or weakens what a browser enforces here teaches nothing",
)

PLAYGROUND_OFF_INSTANCE = SERVER.define(
    "playground_off_instance",
    "{to} is not a path on this instance, and the playground redirects nowhere else: an "
    "open redirect is a phishing tool wearing this instance's own domain",
)

PLAYGROUND_UNAUTHENTICATED = SERVER.define(
    "playground_unauthenticated",
    "this route wants a credential: the basic pair {username}/{username}, or the documented "
    "bearer token. Both are public constants and guard nothing",
)
