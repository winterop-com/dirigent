"""How deep a JSON value a run stores may nest, and how a deeper one is shown.

Pydantic walks a value 255 levels down and no further, and every read nests a stored value a
few levels deeper again: in a page, a report, an alert's context or a resolved config. A value
past :data:`MAX_STORED_DEPTH` is refused where it would be stored, and one stored before that
bound held is shown cut at it.
"""

from typing import Final, cast

from pydantic import JsonValue

from dirigent_common.messages import VALUE_NOT_SHOWN

#: The most levels of lists and objects a stored value may nest: a step's output, a source's
#: input, a run's parameters. Above the 128 an endpoint body may nest, and well inside the 255
#: pydantic walks.
MAX_STORED_DEPTH: Final = 160


def nests_past(value: JsonValue, limit: int = MAX_STORED_DEPTH) -> bool:
    """Say whether a value holds a list or object more than ``limit`` levels down.

    The value itself is the first level, so a value nesting exactly ``limit`` levels passes.
    """
    level = [value]
    for _ in range(limit):
        level = [
            child
            for held in level
            if isinstance(held, dict | list)
            for child in (held.values() if isinstance(held, dict) else held)
        ]
        if not level:
            return False
    return any(isinstance(held, dict | list) for held in level)


def shown[V: JsonValue](value: V, limit: int = MAX_STORED_DEPTH) -> V:
    """Return a value as it is, or when it nests past ``limit``, a copy cut there.

    Each list or object more than ``limit`` levels down is replaced by the sentence
    :data:`VALUE_NOT_SHOWN` says.
    """
    if not nests_past(value, limit):
        return value
    marker = VALUE_NOT_SHOWN.render(limit=limit)
    return cast("V", _cut(value, limit, marker))


def _cut(value: JsonValue, left: int, marker: str) -> JsonValue:
    """Copy a value down to ``left`` levels, putting ``marker`` where a deeper list or object was."""
    if not isinstance(value, dict | list):
        return value
    if left <= 0:
        return marker
    if isinstance(value, dict):
        return {key: _cut(inner, left - 1, marker) for key, inner in value.items()}
    return [_cut(inner, left - 1, marker) for inner in value]
