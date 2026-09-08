"""Time-ordered identifiers: every row dirigent mints gets a UUIDv7.

Ordering has to hold inside a millisecond as well as across them, because several queries
order by ``(something, id)`` to break a tie deterministically and a commit can mint many rows
in one millisecond. The low bits of ``rand_a`` therefore carry a counter, which is RFC 9562's
own "monotonic random" method 3.
"""

import os
import threading
import time
from uuid import UUID

#: Twelve bits is what ``rand_a`` has; wrapping costs the tie-break, not correctness.
COUNTER_BITS = 12

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> UUID:
    """Mint an RFC 9562 version 7 UUID: 48 bits of Unix milliseconds, then a counter, then randomness."""
    global _last_ms, _counter
    timestamp_ms = time.time_ns() // 1_000_000
    with _lock:
        if timestamp_ms == _last_ms:
            _counter = (_counter + 1) % (1 << COUNTER_BITS)
        else:
            # Not zero: starting the counter somewhere random keeps two processes minting in
            # the same millisecond from colliding on their first few identifiers.
            _last_ms = timestamp_ms
            _counter = int.from_bytes(os.urandom(2), "big") % (1 << (COUNTER_BITS - 1))
        counter = _counter
    value = bytearray(timestamp_ms.to_bytes(6, "big") + os.urandom(10))
    value[6] = 0x70 | (counter >> 8)
    value[7] = counter & 0xFF
    value[8] = (value[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(value))
