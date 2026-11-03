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

INSTANCE_UNAVAILABLE = MCP.define(
    "instance_unavailable",
    "the instance behind this server did not say whose token this is, so nothing was done; send again",
)

HOST_NOT_LOOPBACK = MCP.define(
    "host_not_loopback",
    "this server is bound to loopback and answers only to a loopback name, not {host}",
)

REMOTE_BIND_REFUSED = MCP.define(
    "remote_bind_refused",
    "{host} is reachable from other machines; pass --allow-remote to serve MCP there",
)

TRUNCATED_PAGE = MCP.define(
    "truncated_page",
    "{shown} of the {total} rows asked for fit under the {cap}-byte bound on an answer, so only those are "
    "shown and `next` is left out; ask again with limit={shown} for a page that carries its own `next`",
)

TRUNCATED_ANSWER = MCP.define(
    "truncated_answer",
    "this answer is {size} bytes, over the {cap}-byte bound on an answer, so only the start of its JSON "
    "is shown under `preview`; {narrow}",
)

NARROW_A_LISTING = MCP.define("narrow_a_listing", "ask for fewer rows with `limit`, or narrow the listing")

NARROW_AN_OUTPUT = MCP.define(
    "narrow_an_output", "pass `path`, a JSON pointer such as /rows/0, to read one part of the output"
)

NARROW_A_READ = MCP.define("narrow_a_read", "read the parts it names with the tools that list them")

EDIT_NOT_FOUND = MCP.define(
    "edit_not_found", "edit {index}: its `old` text does not occur in the pipeline's current document"
)

EDIT_AMBIGUOUS = MCP.define(
    "edit_ambiguous",
    "edit {index}: its `old` text occurs {count} times in the pipeline's current document, and has to "
    "occur once; quote more of the text around it",
)

EDIT_EMPTY = MCP.define("edit_empty", "edit {index}: its `old` text is empty, and has to quote the text it replaces")

EDITS_REFUSED = MCP.define(
    "edits_refused",
    "nothing was planned or applied, since {problems}; export_pipeline answers the text the edits are matched in",
)

POINTER_INVALID = MCP.define("pointer_invalid", "{path!r} is not a JSON pointer, which starts with / such as /rows/0")

POINTER_MISSES = MCP.define("pointer_misses", "{path!r} reaches nothing in the output: there is no {token!r} there")

NO_ATTEMPT = MCP.define("no_attempt", "run {run_id} has no attempt {attempt_id}")

NO_STORED_OUTPUT = MCP.define(
    "no_stored_output", "run {run_id} holds no artifact at {uri}, where the output was written"
)

REMOTE_BIND = MCP.define(
    "remote_bind",
    "serving MCP on {host}, which other machines can reach: put TLS in front of it, since every "
    "request carries an API token",
)
