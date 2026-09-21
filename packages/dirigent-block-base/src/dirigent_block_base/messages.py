"""Every refusal the base family makes, catalogued under the ``base`` prefix."""

from dirigent_common import Catalogue

BASE = Catalogue("base")

TEMPLATE_FAILED = BASE.define("template_failed", "{detail}")

TEMPLATE_REFUSED = BASE.define("template_refused", "{detail}")

CHILD_RUN_GONE = BASE.define("child_run_gone", "run {run} disappeared before its result could be read")

NOT_A_RUN_HANDLE = BASE.define("not_a_run_handle", "the handle {handle} does not name a run")

VALUE_REFUSED = BASE.define("value_refused", "at {location}: {detail}")
