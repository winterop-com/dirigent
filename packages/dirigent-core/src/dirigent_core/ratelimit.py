"""One token bucket, shared by every surface that has to refuse a caller going too fast.

The bucket is in-memory and therefore per-process: behind N replicas a caller gets N buckets,
so the effective limit is the configured rate times the replica count. Keys are chosen by the
caller, so the number of them is bounded and the least recently used one is evicted, and a long
one is held as its hash, so what a caller sends does not decide how much memory a key takes.
"""

import hashlib
import time

from pydantic import BaseModel, ConfigDict, Field

#: How many distinct keys one bucket tracks before it starts evicting the least recent.
DEFAULT_MAX_KEYS = 4096

#: The longest key held as it was written.
MAX_KEY_LENGTH = 128


class TokenBucket(BaseModel):
    """A per-key rate limiter: a bucket that refills at the configured rate."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    buckets: dict[str, tuple[float, float]] = Field(default_factory=dict[str, tuple[float, float]])
    max_keys: int = Field(default=DEFAULT_MAX_KEYS, ge=1)

    def allow(self, key: str, *, per_minute: int, capacity: int | None = None, now: float | None = None) -> bool:
        """Take one token for a key, or report that the caller is going too fast.

        ``capacity`` is how many tokens a full bucket holds, which is how large a burst it
        takes; unset, it holds a minute's worth.
        """
        moment = now if now is not None else time.monotonic()
        rate = per_minute / 60.0
        full = float(capacity if capacity is not None else per_minute)
        held = _held_key(key)
        tokens, last = self.buckets.pop(held, (full, moment))
        tokens = min(full, tokens + (moment - last) * rate)
        allowed = tokens >= 1.0
        self.buckets[held] = (tokens - 1.0 if allowed else tokens, moment)
        self._evict()
        return allowed

    def _evict(self) -> None:
        """Drop least-recently-used keys, so a stranger cannot grow this dictionary forever."""
        while len(self.buckets) > self.max_keys:
            self.buckets.pop(next(iter(self.buckets)))

    def forget(self, key: str) -> None:
        """Drop a key's bucket."""
        self.buckets.pop(_held_key(key), None)


def _held_key(key: str) -> str:
    """The key a bucket is stored under: itself, or its hash when it is too long."""
    if len(key) <= MAX_KEY_LENGTH:
        return key
    return f"sha256:{hashlib.sha256(key.encode()).hexdigest()}"
