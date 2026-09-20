"""Every refusal the API answers with carries a status, and it is one a caller can act on."""

import importlib

from dirigent_core.documents import DocumentError
from dirigent_core.errors import DomainError
from dirigent_core.pipelines import UnknownPipeline

#: Every module that declares a refusal. Imported here so the walk below sees them all.
MODULES = (
    "dirigent_core.alerting",
    "dirigent_core.auth",
    "dirigent_core.documents",
    "dirigent_core.engine.definition",
    "dirigent_core.engine.references",
    "dirigent_core.engine.runs",
    "dirigent_core.pipelines",
    "dirigent_core.plugins",
    "dirigent_core.schemas",
    "dirigent_core.secrets",
    "dirigent_core.storage",
    "dirigent_core.triggers.backfill",
    "dirigent_core.triggers.schedules",
    "dirigent_core.triggers.webhooks",
)

REFUSAL_STATUSES = frozenset({403, 404, 409, 422})


def _descendants(base: type[DomainError]) -> set[type[DomainError]]:
    found: set[type[DomainError]] = set()
    for one in base.__subclasses__():
        found.add(one)
        found |= _descendants(one)
    return found


def _refusals() -> set[type[DomainError]]:
    for module in MODULES:
        importlib.import_module(module)
    return {one for one in _descendants(DomainError) if one.__module__ in MODULES}


def test_every_refusal_carries_a_status_the_api_can_answer_with() -> None:
    refusals = _refusals()

    assert {"UnknownPipeline", "DocumentError", "WrongPassword"} <= {one.__name__ for one in refusals}
    for one in sorted(refusals, key=lambda found: found.__name__):
        assert isinstance(one.status, int), one.__name__
        assert one.status in REFUSAL_STATUSES, (one.__name__, one.status)


def test_a_refusal_carries_no_problems_unless_it_was_given_a_list() -> None:
    assert UnknownPipeline("nightly").problems == []
    assert DocumentError("refused", ["steps is required"]).problems == ["steps is required"]
    assert DocumentError("refused").problems == ["refused"]
