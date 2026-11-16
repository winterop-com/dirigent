"""How a value that is not already JSON is spelled as JSON.

One conversion, so a parquet column, a database column and anything else that arrives as a
Python object reach a document as the same string. A caller that has already refused a shape
its own format cannot carry -- a nested arrow column, say -- refuses it before asking here.
"""

import base64
import datetime
import decimal
import enum
import json
import math
import uuid
from collections.abc import Mapping
from pathlib import PurePath
from typing import Final, cast

from pydantic import BaseModel, JsonValue

from dirigent_common.messages import NO_JSON_SPELLING


def spelled(value: object) -> JsonValue:
    """Give one Python value its JSON spelling, refusing what has none.

    A date, time or timestamp becomes ISO 8601. A decimal becomes its exact digits as a
    string, because a float would round it. A UUID becomes its canonical text. Bytes become
    standard base64. A float that is not finite becomes null, JSON having no ``NaN``.
    """
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return base64.b64encode(value).decode()
    if isinstance(value, memoryview):
        return base64.b64encode(value.tobytes()).decode()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise ValueError(NO_JSON_SPELLING.render(kind=type(value).__name__))


#: The most bytes a log field shows as base64; a longer value is logged as its size.
LOGGED_BYTES: Final = 256

#: The most characters of a ``repr`` a log field keeps.
LOGGED_REPR_CHARS: Final = 200

#: How deep a log field's containers are followed before the rest is logged as its ``repr``.
LOGGED_DEPTH: Final = 32


def loggable(value: object) -> JsonValue:
    """Give a log field's value a JSON shape, whatever it is; this never raises.

    JSON values pass through and containers are followed. A non-finite float becomes the text
    ``NaN``, ``Infinity`` or ``-Infinity``. A set, frozenset or tuple becomes a list, a pydantic
    model its JSON dump, an enum its value and a path its text. Bytes up to ``LOGGED_BYTES``
    become base64, and longer ones the text ``<N bytes>``. Every other value :func:`spelled`
    knows takes that spelling, and anything else its ``repr``, cut to ``LOGGED_REPR_CHARS``.
    """
    return _loggable(value, 0)


def _loggable(value: object, depth: int) -> JsonValue:
    """Give one value its log shape, ``depth`` containers down."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        raw = memoryview(cast("bytes | bytearray | memoryview[int]", value))
        return spelled(raw.tobytes()) if raw.nbytes <= LOGGED_BYTES else f"<{raw.nbytes} bytes>"
    if isinstance(value, PurePath):
        return str(value)
    if depth >= LOGGED_DEPTH:
        return _shown(value)
    if isinstance(value, enum.Enum):
        return _loggable(value.value, depth + 1)
    if isinstance(value, Mapping):
        held = cast("Mapping[object, object]", value)
        return {_key(key, depth + 1): _loggable(inner, depth + 1) for key, inner in held.items()}
    if isinstance(value, list | tuple):
        return [_loggable(inner, depth + 1) for inner in cast("list[object] | tuple[object, ...]", value)]
    if isinstance(value, set | frozenset):
        members = [_loggable(inner, depth + 1) for inner in cast("set[object] | frozenset[object]", value)]
        return sorted(members, key=lambda member: json.dumps(member, sort_keys=True))
    if isinstance(value, BaseModel):
        try:
            dumped: object = value.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - a model that cannot dump itself is shown as its repr
            return _shown(value)
        return _loggable(dumped, depth + 1)
    try:
        return spelled(value)
    except ValueError:
        return _shown(value)


def _key(key: object, depth: int) -> str:
    """Give a mapping key its text, since a JSON object's keys are strings."""
    if isinstance(key, str):
        return key
    shaped = _loggable(key, depth)
    return shaped if isinstance(shaped, str) else json.dumps(shaped)


def _shown(value: object) -> str:
    """Show a value as its ``repr``, cut to ``LOGGED_REPR_CHARS``."""
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 - a repr that raises still leaves the type to show
        return f"<{type(value).__name__}>"
    if len(text) > LOGGED_REPR_CHARS:
        return f"{text[:LOGGED_REPR_CHARS]} [truncated, {len(text)} characters]"
    return text
