"""Text a database stores as written: no NUL, and no half of a surrogate pair.

PostgreSQL refuses a NUL in text and in JSONB, and no driver encodes half a pair, so text a
caller writes holding either is refused where it arrives rather than when it is written.
"""

import re
from typing import Final, cast

from pydantic_core import PydanticCustomError

from dirigent_common.messages import TEXT_UNSTORABLE

#: The pydantic error type the refusal is raised as, which names its catalogued message.
UNSTORABLE_KIND: Final = "text_unstorable"

#: A NUL, or half a surrogate pair, which JSON and YAML escapes both reach.
UNSTORABLE: Final = re.compile("[\x00\ud800-\udfff]")


def is_storable(text: str) -> bool:
    """Report whether a database stores this text as written."""
    return UNSTORABLE.search(text) is None


def refuse_unstorable[T](value: T) -> T:
    """Pass a value through, refusing text no database stores as written."""
    if isinstance(value, str) and not is_storable(value):
        raise PydanticCustomError(UNSTORABLE_KIND, "{sentence}", {"sentence": TEXT_UNSTORABLE.text})
    return value


def unstorable_at(value: object, at: tuple[str | int, ...] = ()) -> list[str]:
    """Name every place in a parsed document whose key or text no database stores as written.

    A key that holds one is named by the mapping it is in, and what is under it is not read.
    """
    if isinstance(value, str):
        return [] if is_storable(value) else [_where(at)]
    found: list[str] = []
    if isinstance(value, dict):
        for key, inner in cast("dict[object, object]", value).items():
            if not is_storable(str(key)):
                found.append(_where(at))
                continue
            found.extend(unstorable_at(inner, (*at, str(key))))
    elif isinstance(value, list):
        for index, inner in enumerate(cast("list[object]", value)):
            found.extend(unstorable_at(inner, (*at, index)))
    return found


def _where(at: tuple[str | int, ...]) -> str:
    """Spell a place in a document the way a validation issue does."""
    return ".".join(str(part) for part in at) or "(document)"
