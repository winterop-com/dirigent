"""What a held caller is answered with, read off its run's attempts."""

from uuid import uuid4

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.models import StepAttempt
from dirigent_core.sources.waiter import Hold, Replied, Unanswered, answer_of
from dirigent_plugin import ErrorClass

RUN = uuid4()

HOLD = Hold(run_id=RUN, replies=("answer",), path=("shape", "check", "answer"), timeout=30.0)


def attempt(step: str, status: AttemptStatus, *, number: int = 1, **fields: object) -> StepAttempt:
    """Build one attempt of the held run, as the reader would load it."""
    return StepAttempt(run_id=RUN, step_name=step, status=status, attempt=number, **fields)


def test_a_reply_still_to_settle_keeps_the_caller_waiting() -> None:
    attempts = [attempt("shape", AttemptStatus.SUCCEEDED), attempt("answer", AttemptStatus.PENDING)]
    assert answer_of(HOLD, RunStatus.RUNNING, attempts) is None


def test_a_delivered_reply_is_the_answer() -> None:
    rendered = {"status": 200, "body": {"ok": True}, "delivered": True}
    answered = answer_of(HOLD, RunStatus.SUCCEEDED, [attempt("answer", AttemptStatus.SUCCEEDED, output=rendered)])
    assert answered == Replied(step="answer", rendered=rendered)


def test_a_reply_that_answered_nobody_is_not_the_answer() -> None:
    rendered = {"status": 200, "delivered": False}
    answered = answer_of(HOLD, RunStatus.SUCCEEDED, [attempt("answer", AttemptStatus.SUCCEEDED, output=rendered)])
    assert answered == Unanswered(run_status=RunStatus.SUCCEEDED)


def test_a_refused_input_is_named_over_any_other_failure_on_the_way() -> None:
    attempts = [
        attempt("shape", AttemptStatus.FAILED, error="boom", error_class=ErrorClass.TRANSIENT.value),
        attempt("check", AttemptStatus.FAILED, error="no email", error_class=ErrorClass.REJECTED.value),
        attempt("answer", AttemptStatus.SKIPPED),
    ]
    answered = answer_of(HOLD, RunStatus.FAILED, attempts)
    assert answered == Unanswered(
        run_status=RunStatus.FAILED, step="check", error="no email", error_class=ErrorClass.REJECTED
    )


def test_a_failed_try_a_retry_replaced_is_not_the_answer() -> None:
    attempts = [
        attempt("shape", AttemptStatus.FAILED, error="boom", error_class=ErrorClass.TRANSIENT.value),
        attempt("shape", AttemptStatus.QUEUED, number=2),
        attempt("answer", AttemptStatus.PENDING),
    ]
    assert answer_of(HOLD, RunStatus.RUNNING, attempts) is None
