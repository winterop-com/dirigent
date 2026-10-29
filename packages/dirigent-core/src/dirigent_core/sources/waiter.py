"""The reply waiter: one reader per server process answering every caller held for a reply.

A caller whose input can reach a reply is held once its run is committed. The reader reads the
replies of every held run together, woken by ``dirigent_settled`` and at most once per
``source_reply_poll``, and settles each caller with the first reply that answered, or with the
run's failure once no reply can answer any more. A caller still waiting at its deadline is
answered as timed out, and its run carries on.
"""

import asyncio
import contextlib
import time
from collections.abc import Coroutine, Sequence
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus, RunStatus
from dirigent_common import JsonMap
from dirigent_core import wakeups
from dirigent_core.config import Settings
from dirigent_core.engine.state import latest_attempts
from dirigent_core.logging import get_logger
from dirigent_core.models import Run, StepAttempt
from dirigent_plugin import ErrorClass

#: How long the reader idles between reads when no settle is heard.
REREAD_SECONDS: Final = 1.0

#: An attempt that may still move, which keeps a reply able to answer.
UNSETTLED: Final = frozenset(
    {AttemptStatus.PENDING, AttemptStatus.QUEUED, AttemptStatus.RUNNING, AttemptStatus.WAITING}
)

_logger = get_logger("waiter")


class Hold(BaseModel):
    """One caller held for its run's reply: which replies may answer it, and which steps lead to them."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    replies: tuple[str, ...]
    path: tuple[str, ...]
    """Every step on the way to a reply, the replies included, whose failure is the caller's answer."""

    timeout: float
    """Seconds the caller is held, already capped by the instance."""


class Replied(BaseModel):
    """A reply answered: what it rendered."""

    model_config = ConfigDict(frozen=True)

    step: str
    rendered: JsonMap


class Unanswered(BaseModel):
    """No reply can answer any more: the step that failed on the way, if one did."""

    model_config = ConfigDict(frozen=True)

    run_status: RunStatus | None
    step: str | None = None
    error: str | None = None
    error_class: ErrorClass | None = None


class TimedOut(BaseModel):
    """The caller's deadline passed with no answer."""

    model_config = ConfigDict(frozen=True)


type Answer = Replied | Unanswered | TimedOut


class _Caller:
    """A held caller's hold and the future its answer is set on."""

    def __init__(self, hold: Hold, future: asyncio.Future[Answer]) -> None:
        self.hold = hold
        self.future = future


class Waiter:
    """Holds callers for their replies, and reads all of their runs in one pass.

    Seats are reserved before a run is created, so a process never holds more callers than
    ``source_max_waiting``.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        """Bind the waiter to the sessions it reads with and the settings that bound it."""
        self.sessions = sessions
        self.settings = settings
        self.seats = 0
        self._callers: list[_Caller] = []
        self._joined = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._read_at = 0.0

    def reserve(self) -> bool:
        """Take a seat for a caller about to be held; False when every seat is taken."""
        if self.seats >= self.settings.source_max_waiting:
            return False
        self.seats += 1
        return True

    def release(self) -> None:
        """Give a seat back, for a caller that was answered or never held."""
        self.seats = max(0, self.seats - 1)

    async def wait(self, hold: Hold) -> Answer:
        """Hold a caller on a seat it reserved until its run answers it or its deadline passes."""
        self._ensure_started()
        future: asyncio.Future[Answer] = asyncio.get_running_loop().create_future()
        caller = _Caller(hold, future)
        self._callers.append(caller)
        self._joined.set()
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=hold.timeout)
        except TimeoutError:
            return TimedOut()
        finally:
            with contextlib.suppress(ValueError):
                self._callers.remove(caller)
            self.release()

    async def stop(self) -> None:
        """Stop the reader, answering nobody further."""
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def _ensure_started(self) -> None:
        """Start the reader on the running loop, the first time a caller is held."""
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        """Read whenever a settle is heard or a caller joins, spacing reads by ``source_reply_poll``."""
        spacing = self.settings.source_reply_poll.total_seconds()
        while not self._stopping.is_set():
            if not self._callers:
                self._joined.clear()
                await self._joined.wait()
                continue
            idle = spacing - (time.monotonic() - self._read_at)
            if idle > 0:
                await asyncio.sleep(idle)
            mark = wakeups.hub.mark(wakeups.SETTLED)
            self._joined.clear()
            self._read_at = time.monotonic()
            try:
                await self._read()
            except Exception as error:  # a failed read is retried on the next pass, never fatal
                _logger.warning("reading held replies failed", error=str(error))
            if self._callers and not wakeups.hub.moved(mark) and not self._joined.is_set():
                await _first(wakeups.hub.wait(mark, timeout=REREAD_SECONDS), self._joined.wait())

    async def _read(self) -> None:
        """Read every held run's status and attempts, and answer each caller its run can answer."""
        callers = [caller for caller in self._callers if not caller.future.done()]
        if not callers:
            return
        run_ids = {caller.hold.run_id for caller in callers}
        async with self.sessions() as session:
            found = await session.execute(sa.select(Run.id, Run.status).where(Run.id.in_(run_ids)))
            statuses: dict[UUID, RunStatus] = {run_id: run_status for run_id, run_status in found}
            attempts = (await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id.in_(run_ids)))).scalars()
            by_run: dict[UUID, list[StepAttempt]] = {}
            for attempt in attempts:
                by_run.setdefault(attempt.run_id, []).append(attempt)
        for caller in callers:
            answer = answer_of(caller.hold, statuses.get(caller.hold.run_id), by_run.get(caller.hold.run_id, []))
            if answer is not None and not caller.future.done():
                caller.future.set_result(answer)


def answer_of(hold: Hold, status: RunStatus | None, attempts: Sequence[StepAttempt]) -> Answer | None:
    """Say what a held caller is answered with now, or nothing while a reply may still answer."""
    newest = latest_attempts(attempts).values()
    for attempt in newest:
        if attempt.step_name in hold.replies and attempt.status is AttemptStatus.SUCCEEDED:
            rendered = attempt.output or {}
            if rendered.get("delivered") is True:
                return Replied(step=attempt.step_name, rendered=rendered)
    open_replies = [a for a in newest if a.step_name in hold.replies and a.status in UNSETTLED]
    if open_replies and status not in _SETTLED_RUNS:
        return None
    failed = [a for a in newest if a.step_name in hold.path and a.status is AttemptStatus.FAILED]
    failed.sort(
        key=lambda attempt: (attempt.error_class != ErrorClass.REJECTED.value, hold.path.index(attempt.step_name))
    )
    if not failed:
        return Unanswered(run_status=status)
    first = failed[0]
    return Unanswered(
        run_status=status,
        step=first.step_name,
        error=first.error,
        error_class=ErrorClass(first.error_class) if first.error_class in set(ErrorClass) else ErrorClass.UNKNOWN,
    )


_SETTLED_RUNS: Final = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.FAILED, RunStatus.CANCELLED}
)


async def _first(*waits: Coroutine[Any, Any, object]) -> None:
    """Return once any of these coroutines completes, cancelling the rest."""
    tasks = [asyncio.ensure_future(one) for one in waits]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
