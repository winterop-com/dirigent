"""Attempt-level failure semantics: classify, then decide whether to try again.

The block classifies; the engine owns the policy. ``transient`` and ``unknown`` both retry
while budget remains, and ``rejected`` never retries. A sensor's ``NotYet`` is not a failure
and never reaches here.
"""

import random
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dirigent_common import JsonMap, Message
from dirigent_core.engine.definition import RetryPolicy
from dirigent_core.messages import BLOCK_RAISED
from dirigent_plugin import AnyOperator, AnySensor, BlockFailure, ErrorClass, classify_default


def classify(block: AnyOperator | AnySensor, error: Exception) -> ErrorClass:
    """Ask the block to classify a failure, falling back to the contract's default."""
    try:
        return block.classify_error(error)
    except Exception:  # a broken classifier must not mask the failure it was asked about
        return classify_default(error)


def should_retry(error_class: ErrorClass, *, attempt: int, policy: RetryPolicy) -> bool:
    """Decide whether a failed attempt earns another one.

    Only ``rejected`` is refused another attempt: a failure the engine cannot explain is what
    ``max_attempts`` was declared for.
    """
    if attempt >= policy.max_attempts:
        return False
    return error_class is not ErrorClass.REJECTED


def backoff_delay(policy: RetryPolicy, attempt: int, rng: random.Random | None = None) -> timedelta:
    """Compute the delay before attempt ``attempt + 1``: exponential, clamped, jittered.

    The delay is written to ``available_at``, never slept on.
    """
    growth = policy.multiplier ** max(attempt - 1, 0)
    seconds = min(policy.backoff.total_seconds() * growth, policy.max_backoff.total_seconds())
    if policy.jitter:
        spread = seconds * policy.jitter
        seconds += (rng or random).uniform(-spread, spread)
    return timedelta(seconds=max(seconds, 0.0))


class Failure(BaseModel):
    """One classified failure, ready for the retry decision and for the attempt row."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    params: JsonMap = Field(default_factory=dict)
    error_class: ErrorClass

    @classmethod
    def of(cls, block: AnyOperator | AnySensor, error: Exception) -> "Failure":
        """Build a failure from an exception a block raised, keeping its code when it has one."""
        error_class = classify(block, error)
        if isinstance(error, BlockFailure):
            return cls(code=error.code, message=error.message, params=error.params, error_class=error_class)
        params: JsonMap = {"kind": type(error).__name__, "detail": str(error)}
        return cls(
            code=BLOCK_RAISED.code,
            message=BLOCK_RAISED.render(**params),
            params=params,
            error_class=error_class,
        )

    @classmethod
    def rejected(cls, message: Message, /, **params: Any) -> "Failure":
        """Build a failure the engine itself raised and that retrying cannot fix."""
        return cls(code=message.code, message=message.render(**params), params=params, error_class=ErrorClass.REJECTED)

    @classmethod
    def unknown(cls, message: Message, /, **params: Any) -> "Failure":
        """Build a failure the engine itself raised that it cannot classify either way."""
        return cls(code=message.code, message=message.render(**params), params=params, error_class=ErrorClass.UNKNOWN)

    @classmethod
    def transient(cls, message: Message, /, **params: Any) -> "Failure":
        """Build a failure the engine itself raised that another attempt may survive."""
        return cls(code=message.code, message=message.render(**params), params=params, error_class=ErrorClass.TRANSIENT)
