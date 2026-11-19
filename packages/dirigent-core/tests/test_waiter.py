"""What a held caller is answered with, read off its run's attempts."""

import re
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import create_run, save_pipeline
from dirigent_core.models import StepAttempt
from dirigent_core.sources.waiter import Hold, Replied, Unanswered, Waiter, answer_of
from dirigent_plugin import ErrorClass

RUN = uuid4()

HOLD = Hold(run_id=RUN, source_id=uuid4(), replies=("answer",), path=("shape", "check", "answer"), timeout=30.0)


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
    assert answered == Unanswered(run_status=RunStatus.FAILED, step="check", error_class=ErrorClass.REJECTED)


def test_a_failed_try_a_retry_replaced_is_not_the_answer() -> None:
    attempts = [
        attempt("shape", AttemptStatus.FAILED, error="boom", error_class=ErrorClass.TRANSIENT.value),
        attempt("shape", AttemptStatus.QUEUED, number=2),
        attempt("answer", AttemptStatus.PENDING),
    ]
    assert answer_of(HOLD, RunStatus.RUNNING, attempts) is None


async def test_a_read_loads_the_output_of_the_answering_reply_alone(
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    settings: Settings,
) -> None:
    definition = PipelineDefinition(
        code="held",
        steps={
            "shape": StepDefinition(block="test.echo", config={"value": "a"}),
            "answer": StepDefinition(block="test.echo", config={"value": "b"}, depends_on=["shape"]),
        },
    )
    rendered = {"status": 200, "body": {"ok": True}, "delivered": True}
    async with session_scope(sessions) as session:
        run = await create_run(session, services, await save_pipeline(session, definition))
        assert run is not None
        made = (await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run.id))).scalars()
        attempts = {attempt.step_name: attempt for attempt in made}
        attempts["shape"].output = {"rows": ["x" * 1000] * 100}
        attempts["shape"].fetched_output = {"rows": ["y" * 1000] * 100}
        attempts["answer"].output = rendered
        for attempt in attempts.values():
            attempt.status = AttemptStatus.SUCCEEDED
    statements: list[str] = []

    def seen(_connection: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", seen)
    try:
        hold = Hold(run_id=run.id, source_id=uuid4(), replies=("answer",), path=("shape", "answer"), timeout=5.0)
        waiter = Waiter(sessions, settings)
        waiter.reserve(hold.source_id)
        answered = await waiter.wait(hold)
        await waiter.stop()
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", seen)

    assert answered == Replied(step="answer", rendered=rendered)
    assert not [statement for statement in statements if "fetched_output" in statement]
    outputs = [statement for statement in statements if re.search(r"step_attempts\.output\b", statement)]
    assert outputs
    assert all("step_attempts.id IN" in statement for statement in outputs)
