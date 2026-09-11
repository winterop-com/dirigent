"""Tests for the trigger-rule truth table, the item policy, and run status derivation."""

from datetime import UTC, datetime, timedelta

import pytest

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.engine.definition import ItemPolicy, TriggerRule
from dirigent_core.engine.state import (
    Readiness,
    StepOutcome,
    StepState,
    aggregate_items,
    derive_run_status,
    evaluate_rule,
    in_execution_order,
)
from dirigent_core.ids import uuid7
from dirigent_core.models import StepAttempt

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

RUN = uuid7()

SUCCEEDED = StepOutcome.SUCCEEDED
FAILED = StepOutcome.FAILED
SKIPPED = StepOutcome.SKIPPED
RUNNING = StepOutcome.RUNNING
PENDING = StepOutcome.PENDING
CANCELLED = StepOutcome.CANCELLED


def test_a_step_with_no_prerequisites_is_always_ready() -> None:
    for rule in TriggerRule:
        assert evaluate_rule(rule, []) is Readiness.READY


@pytest.mark.parametrize(
    ("rule", "outcomes", "expected"),
    [
        (TriggerRule.ALL_SUCCESS, [SUCCEEDED], Readiness.READY),
        (TriggerRule.ALL_SUCCESS, [SUCCEEDED, SUCCEEDED], Readiness.READY),
        (TriggerRule.ALL_SUCCESS, [SUCCEEDED, RUNNING], Readiness.WAIT),
        (TriggerRule.ALL_SUCCESS, [PENDING], Readiness.WAIT),
        (TriggerRule.ALL_SUCCESS, [FAILED], Readiness.NEVER),
        (TriggerRule.ALL_SUCCESS, [SUCCEEDED, FAILED], Readiness.NEVER),
        (TriggerRule.ALL_SUCCESS, [SKIPPED], Readiness.NEVER),
        (TriggerRule.ALL_SUCCESS, [CANCELLED], Readiness.NEVER),
        (TriggerRule.ALL_SUCCESS, [FAILED, RUNNING], Readiness.NEVER),
        (TriggerRule.ALL_DONE, [SUCCEEDED, FAILED], Readiness.READY),
        (TriggerRule.ALL_DONE, [SKIPPED, CANCELLED], Readiness.READY),
        (TriggerRule.ALL_DONE, [SUCCEEDED, RUNNING], Readiness.WAIT),
        (TriggerRule.ALL_DONE, [PENDING], Readiness.WAIT),
        (TriggerRule.ONE_FAILED, [FAILED], Readiness.READY),
        (TriggerRule.ONE_FAILED, [FAILED, RUNNING], Readiness.READY),
        (TriggerRule.ONE_FAILED, [SUCCEEDED, RUNNING], Readiness.WAIT),
        (TriggerRule.ONE_FAILED, [SUCCEEDED], Readiness.NEVER),
        (TriggerRule.ONE_FAILED, [SUCCEEDED, SKIPPED], Readiness.NEVER),
        (TriggerRule.ALWAYS, [FAILED], Readiness.READY),
        (TriggerRule.ALWAYS, [SKIPPED], Readiness.READY),
        (TriggerRule.ALWAYS, [SUCCEEDED, CANCELLED], Readiness.READY),
        (TriggerRule.ALWAYS, [RUNNING], Readiness.WAIT),
    ],
)
def test_the_trigger_rule_truth_table(rule: TriggerRule, outcomes: list[StepOutcome], expected: Readiness) -> None:
    assert evaluate_rule(rule, outcomes) is expected


def test_terminal_outcomes_are_exactly_the_four_that_cannot_change() -> None:
    assert [outcome for outcome in StepOutcome if outcome.terminal] == [SUCCEEDED, FAILED, SKIPPED, CANCELLED]


@pytest.mark.parametrize(
    ("outcomes", "policy", "expected"),
    [
        ([], ItemPolicy.FAIL_FAST, SKIPPED),
        ([], ItemPolicy.CONTINUE, SKIPPED),
        ([SUCCEEDED, RUNNING], ItemPolicy.CONTINUE, RUNNING),
        ([SUCCEEDED, SUCCEEDED], ItemPolicy.FAIL_FAST, SUCCEEDED),
        ([SUCCEEDED, FAILED], ItemPolicy.FAIL_FAST, FAILED),
        ([SUCCEEDED, FAILED], ItemPolicy.CONTINUE, SUCCEEDED),
        ([FAILED, FAILED], ItemPolicy.CONTINUE, FAILED),
        ([SKIPPED, SKIPPED], ItemPolicy.CONTINUE, SKIPPED),
        # An item skipped because the item it pairs with did not succeed leaves the rest of
        # the batch as it found them, under either policy.
        ([SUCCEEDED, SKIPPED], ItemPolicy.FAIL_FAST, SUCCEEDED),
        ([SUCCEEDED, SKIPPED], ItemPolicy.CONTINUE, SUCCEEDED),
        ([SKIPPED, SKIPPED], ItemPolicy.FAIL_FAST, SKIPPED),
        ([FAILED, SKIPPED], ItemPolicy.FAIL_FAST, FAILED),
        ([FAILED, SKIPPED], ItemPolicy.CONTINUE, FAILED),
        ([SUCCEEDED, CANCELLED], ItemPolicy.CONTINUE, CANCELLED),
    ],
)
def test_the_item_policy_decides_whether_one_bad_item_sinks_the_batch(
    outcomes: list[StepOutcome], policy: ItemPolicy, expected: StepOutcome
) -> None:
    assert aggregate_items(outcomes, policy) is expected


def test_a_tolerated_failure_reads_as_success_to_dependents() -> None:
    tolerated = StepState(name="push", outcome=FAILED, tolerated=True)
    assert tolerated.rule_outcome is SUCCEEDED
    assert tolerated.has_errors is True
    strict = StepState(name="push", outcome=FAILED)
    assert strict.rule_outcome is FAILED
    assert strict.has_errors is False


def test_a_run_still_in_flight_has_no_derived_status() -> None:
    assert derive_run_status({"a": StepState(name="a", outcome=RUNNING)}) is None
    assert derive_run_status({"a": StepState(name="a", outcome=PENDING)}) is None


def test_all_succeeded_is_succeeded() -> None:
    states = {"a": StepState(name="a", outcome=SUCCEEDED), "b": StepState(name="b", outcome=SKIPPED)}
    assert derive_run_status(states) is RunStatus.SUCCEEDED


def test_a_required_path_failing_fails_the_run() -> None:
    states = {"a": StepState(name="a", outcome=SUCCEEDED), "b": StepState(name="b", outcome=FAILED)}
    assert derive_run_status(states) is RunStatus.FAILED


def test_a_tolerated_failure_completes_the_run_with_errors() -> None:
    states = {"a": StepState(name="a", outcome=FAILED, tolerated=True)}
    assert derive_run_status(states) is RunStatus.COMPLETED_WITH_ERRORS


def test_item_failures_alone_complete_the_run_with_errors() -> None:
    states = {"a": StepState(name="a", outcome=SUCCEEDED, item_failures=1, tolerated=True)}
    assert derive_run_status(states) is RunStatus.COMPLETED_WITH_ERRORS


def test_cancellation_wins_over_everything() -> None:
    states = {"a": StepState(name="a", outcome=FAILED)}
    assert derive_run_status(states, cancelled=True) is RunStatus.CANCELLED
    assert derive_run_status({"a": StepState(name="a", outcome=CANCELLED)}) is RunStatus.CANCELLED


def _attempt(step: str, *, started: int | None, finished: int | None = None, attempt: int = 1) -> StepAttempt:
    """One attempt placed on a clock of whole seconds, so a test can say what ran when."""
    return StepAttempt(
        id=uuid7(),
        run_id=RUN,
        step_name=step,
        block_id="test.block",
        attempt=attempt,
        status=AttemptStatus.SUCCEEDED,
        started_at=EPOCH + timedelta(seconds=started) if started is not None else None,
        finished_at=EPOCH + timedelta(seconds=finished) if finished is not None else None,
    )


def test_attempts_are_ordered_by_when_they_ran_rather_than_by_name() -> None:
    """The table has to agree with the stream printed above it, which is in execution order."""
    rows = [
        _attempt("archive", started=2, finished=3),
        _attempt("fetch", started=1, finished=2),
        _attempt("report", started=3, finished=4),
    ]
    assert [row.step_name for row in in_execution_order(rows)] == ["fetch", "archive", "report"]


def test_a_step_that_never_started_sorts_after_every_step_that_did() -> None:
    rows = [_attempt("skipped", started=None), _attempt("ran", started=5, finished=6)]
    assert [row.step_name for row in in_execution_order(rows)] == ["ran", "skipped"]


def test_a_retry_follows_the_attempt_it_retries() -> None:
    rows = [
        _attempt("load", started=9, finished=10, attempt=2),
        _attempt("load", started=1, finished=2, attempt=1),
        _attempt("next", started=11, finished=12),
    ]
    assert [(row.step_name, row.attempt) for row in in_execution_order(rows)] == [("load", 1), ("load", 2), ("next", 1)]


def test_a_fan_outs_items_stay_in_item_order_within_their_step() -> None:
    """Which item was claimed first says nothing; the index is the sequence that means something."""
    rows = [_attempt("push", started=3 - index, finished=5) for index in range(3)]
    indexes = {row.id: index for index, row in enumerate(rows)}
    assert [indexes[row.id] for row in in_execution_order(rows, indexes)] == [0, 1, 2]


def test_steps_that_have_not_started_keep_the_order_their_author_wrote() -> None:
    """Nothing has run, so there is no execution order to fall back on -- and none to invent."""
    rows = [_attempt(name, started=None) for name in ("apple", "zebra", "middle")]
    order = ["zebra", "middle", "apple"]
    assert [row.step_name for row in in_execution_order(rows, None, order)] == order


def test_steps_that_started_together_are_separated_by_the_document_and_not_the_alphabet() -> None:
    rows = [_attempt(name, started=1, finished=2) for name in ("apple", "zebra", "middle")]
    order = ["zebra", "middle", "apple"]
    assert [row.step_name for row in in_execution_order(rows, None, order)] == order
