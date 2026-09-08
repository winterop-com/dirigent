"""How a value that is not already JSON is spelled as JSON.

One conversion, so a parquet column, a database column and anything else that arrives as a
Python object reach a document as the same string. A caller that has already refused a shape
its own format cannot carry -- a nested arrow column, say -- refuses it before asking here.
"""

import base64
import datetime
import decimal
import math
import uuid

from pydantic import JsonValue


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
    raise ValueError(f"a value of type {type(value).__name__} has no JSON spelling")
