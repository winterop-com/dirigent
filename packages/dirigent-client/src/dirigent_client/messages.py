"""Every refusal the client itself makes, catalogued: the ones no server sent."""

from dirigent_common import Catalogue

CLIENT = Catalogue("client")

UNREACHABLE = CLIENT.define("unreachable", "cannot reach {url}: {kind}: {detail}")

NOT_DIRIGENT = CLIENT.define(
    "not_dirigent",
    "the server at {base_url} does not look like a dirigent instance (got {described} from {url})",
)

NO_PROBLEM_DOCUMENT = CLIENT.define("no_problem_document", "{detail}")

NO_ANSWER = CLIENT.define("no_answer", "{detail}")


# What a wire shape refuses at validation. Pydantic owns the code a validator's refusal
# reaches the wire under, so these are rendered into the ``ValueError`` it wraps.

EMPTY_LOG_LEVEL_PATTERN = CLIENT.define("empty_log_level_pattern", "log_levels: a pattern may not be empty")

WINDOW_HAS_TWO_ENDS = CLIENT.define(
    "window_has_two_ends",
    "a window has two ends: give both window_start and window_end, or neither",
)
