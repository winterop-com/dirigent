"""Tests for the attempt-level retry decision and the backoff schedule."""

import random
from datetime import timedelta

import pytest
from pydantic import BaseModel

from dirigent_core.engine.definition import RetryPolicy
from dirigent_core.engine.failure import Failure, backoff_delay, classify, should_retry
from dirigent_plugin import BlockFailure, ErrorClass, Operator, OperatorSpec, RemoteHandle, StepContext


class Config(BaseModel):
    """Nothing; these blocks exist only to be classified."""


class Output(BaseModel):
    """Nothing; these blocks exist only to be classified."""


class HonestOperator(Operator[Config, Output]):
    """Classifies by the contract's default."""

    spec = OperatorSpec(id="test.honest", summary="Classify by default.", idempotent=True)
    config_model = Config
    output_model = Output

    async def execute(self, config: Config, ctx: StepContext) -> Output | RemoteHandle:
        """Never called."""
        return Output()


class OpinionatedOperator(HonestOperator):
    """Knows that its API's conflict status is not worth retrying."""

    spec = OperatorSpec(id="test.opinionated", summary="Classify its own way.")

    def classify_error(self, error: Exception) -> ErrorClass:
        """Call everything rejected, because only this block knows its API."""
        return ErrorClass.REJECTED


class BrokenClassifier(HonestOperator):
    """Its classifier raises, which must not mask the failure it was asked about."""

    spec = OperatorSpec(id="test.broken", summary="Raise while classifying.")

    def classify_error(self, error: Exception) -> ErrorClass:
        """Fail at the one job this hook has."""
        raise RuntimeError("the classifier itself is broken")


@pytest.mark.parametrize(
    ("error_class", "attempt", "max_attempts", "expected"),
    [
        (ErrorClass.TRANSIENT, 1, 3, True),
        (ErrorClass.TRANSIENT, 2, 3, True),
        (ErrorClass.TRANSIENT, 3, 3, False),
        (ErrorClass.TRANSIENT, 1, 1, False),
        (ErrorClass.REJECTED, 1, 5, False),
        (ErrorClass.REJECTED, 3, 5, False),
        (ErrorClass.UNKNOWN, 1, 3, True),
        (ErrorClass.UNKNOWN, 2, 3, True),
        (ErrorClass.UNKNOWN, 3, 3, False),
        (ErrorClass.UNKNOWN, 1, 1, False),
    ],
)
def test_the_retry_matrix(error_class: ErrorClass, attempt: int, max_attempts: int, expected: bool) -> None:
    policy = RetryPolicy(max_attempts=max_attempts)
    assert should_retry(error_class, attempt=attempt, policy=policy) is expected


def test_backoff_grows_exponentially_and_is_clamped() -> None:
    policy = RetryPolicy(backoff=timedelta(seconds=10), multiplier=2.0, max_backoff=timedelta(seconds=60), jitter=0.0)
    delays = [backoff_delay(policy, attempt).total_seconds() for attempt in range(1, 6)]
    assert delays == [10.0, 20.0, 40.0, 60.0, 60.0]


def test_jitter_spreads_the_delay_without_leaving_the_band() -> None:
    policy = RetryPolicy(backoff=timedelta(seconds=10), multiplier=1.0, jitter=0.5)
    rng = random.Random(1234)
    delays = [backoff_delay(policy, 1, rng).total_seconds() for _ in range(200)]
    assert all(5.0 <= delay <= 15.0 for delay in delays)
    assert len(set(delays)) > 1


def test_backoff_is_never_negative() -> None:
    policy = RetryPolicy(backoff=timedelta(seconds=1), multiplier=1.0, jitter=1.0)
    assert all(backoff_delay(policy, 1).total_seconds() >= 0.0 for _ in range(100))


def test_a_block_owns_its_classification() -> None:
    assert classify(HonestOperator(), BlockFailure("x", error_class=ErrorClass.TRANSIENT)) is ErrorClass.TRANSIENT
    assert classify(OpinionatedOperator(), RuntimeError("conflict")) is ErrorClass.REJECTED


def test_a_broken_classifier_falls_back_to_the_contract_default() -> None:
    assert classify(BrokenClassifier(), ValueError("nonsense")) is ErrorClass.UNKNOWN


def test_a_failure_carries_the_message_a_block_meant_to_send() -> None:
    deliberate = Failure.of(HonestOperator(), BlockFailure("refused", error_class=ErrorClass.REJECTED))
    assert deliberate.message == "refused"
    assert deliberate.error_class is ErrorClass.REJECTED

    accidental = Failure.of(HonestOperator(), ValueError("nonsense"))
    assert accidental.message == "ValueError: nonsense"
    assert accidental.error_class is ErrorClass.UNKNOWN


def test_the_engine_can_raise_its_own_classified_failures() -> None:
    assert Failure.rejected("bad config").error_class is ErrorClass.REJECTED
    assert Failure.transient("network").error_class is ErrorClass.TRANSIENT
