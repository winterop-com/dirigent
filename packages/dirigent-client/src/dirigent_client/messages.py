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
