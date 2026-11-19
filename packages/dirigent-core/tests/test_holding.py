"""Held sources: one worker keeps each consumer open under a lease, and acknowledges only what became runs."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from dirigent_client.enums import ProvenanceSource, SourceState
from dirigent_common import JsonMap
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.directory import prune_absent
from dirigent_core.documents import load_text
from dirigent_core.engine.runs import Provenance, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import SOURCE_CONFIG_UNREADABLE
from dirigent_core.models import Pipeline, Run, Source
from dirigent_core.pipelines import apply_document, set_active
from dirigent_core.plugins import PluginHost
from dirigent_core.sources import holding, polling
from dirigent_core.sources.holding import Holder
from dirigent_core.sources.rows import set_paused, state_of
from dirigent_plugin import Contribution
from dirigent_plugin.sources import HeldSource, HoldContext, SourceHosting, SourceSpec
from engineblocks import EngineTestPlugin

WORKER = "worker-under-test"


class InboxConfig(BaseModel):
    """Which inbox to read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    max_in_flight: int | None = None


class Letter(BaseModel):
    """One message out of the inbox."""

    model_config = ConfigDict(frozen=True)

    text: str
    received_at: datetime


class Inbox:
    """An in-memory broker: what is waiting, what was handed out, and what was acknowledged."""

    def __init__(self) -> None:
        """Start with nothing waiting and no consumer opened."""
        self.reset()

    def reset(self) -> None:
        """Forget everything, as a fresh broker would."""
        self.waiting: list[str] = []
        self.unacked: list[str] = []
        self.acked: list[str] = []
        self.opened = 0
        self.closed = 0
        self.refuse_open = False

    def put(self, *texts: str) -> None:
        """Publish messages onto the inbox."""
        self.waiting.extend(texts)


INBOX = Inbox()


class InboxListener:
    """A consumer of the inbox: it hands out what is waiting and keeps it until acknowledged."""

    async def receive(self, limit: int, wait: timedelta) -> list[Letter]:
        if not INBOX.waiting:
            await asyncio.sleep(min(wait.total_seconds(), 0.02))
            return []
        taken, INBOX.waiting = INBOX.waiting[:limit], INBOX.waiting[limit:]
        INBOX.unacked.extend(taken)
        return [Letter(text=text, received_at=datetime.now(UTC)) for text in taken]

    async def ack(self) -> None:
        INBOX.acked.extend(INBOX.unacked)
        INBOX.unacked.clear()


class InboxSource(HeldSource[InboxConfig, Letter]):
    """A held kind over the in-memory inbox."""

    spec = SourceSpec(kind="tests.inbox", summary="An in-memory inbox", hosting=SourceHosting.HELD)
    config_model = InboxConfig
    output_model = Letter

    def max_in_flight(self, config: InboxConfig) -> int | None:
        return config.max_in_flight

    def label_of(self, output: Letter) -> str | None:
        return output.text

    def complete(self, config: InboxConfig, given: JsonMap, *, received_at: datetime) -> Letter:
        return Letter(text=str(given.get("text", "")), received_at=received_at)

    def listen(self, config: InboxConfig, ctx: HoldContext) -> Any:
        @asynccontextmanager
        async def opened() -> AsyncGenerator[InboxListener]:
            if INBOX.refuse_open:
                raise ConnectionError("the inbox refused the connection")
            INBOX.opened += 1
            try:
                yield InboxListener()
            finally:
                # What was handed out and not acknowledged goes back, as a broker redelivers it.
                INBOX.waiting[:0] = INBOX.unacked
                INBOX.unacked.clear()
                INBOX.closed += 1

        return opened()


@pytest.fixture(autouse=True)
def _fresh_inbox() -> None:  # pyright: ignore[reportUnusedFunction]
    """Start each test with an empty inbox."""
    INBOX.reset()


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """Wait on the inbox briefly, so a test does not sit out the default."""
    return settings.model_copy(update={"source_hold_wait": timedelta(milliseconds=20)})


@pytest.fixture
def host() -> PluginHost:
    """The engine's test blocks and the inbox kind."""
    return PluginHost({"engine-tests": EngineTestPlugin().contribute(), "inbox": Contribution(sources=[InboxSource()])})


DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: mailroom
{concurrency}
steps:
  letters:
    source:
      kind: tests.inbox
      name: front-desk
{extra}
  note:
    block: test.echo
    depends_on: [letters]
    config:
      value: ${{steps.letters.output.text}}
"""


def mailroom(extra: str = "", concurrency: str = "") -> str:
    """The mailroom document, with lines added under its source."""
    return DOCUMENT.format(extra=extra, concurrency=concurrency)


async def apply(sessions: async_sessionmaker[AsyncSession], services: EngineServices, text: str) -> None:
    """Apply a document in its own transaction."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(text))


async def the_source(sessions: async_sessionmaker[AsyncSession]) -> Source:
    """Read the one source row back."""
    async with sessions() as session:
        return (await session.execute(sa.select(Source))).scalar_one()


async def run_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    """How many runs exist."""
    async with sessions() as session:
        return int((await session.execute(sa.select(sa.func.count()).select_from(Run))).scalar_one())


async def eventually(check: Callable[[], Awaitable[bool]], *, within: float = 5.0) -> None:
    """Wait until a check holds, failing the test when it does not in time."""
    deadline = asyncio.get_running_loop().time() + within
    while not await check():
        assert asyncio.get_running_loop().time() < deadline, "the condition never held"
        await asyncio.sleep(0.02)


async def test_each_message_becomes_a_run_and_is_acknowledged_after_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom())
    starting = await the_source(sessions)
    assert state_of(starting, pipeline_active=True, unsettled=0, bound=None, is_polled=True) is SourceState.STARTING
    holder = Holder(sessions, services, owner=WORKER)
    try:
        assert len(await holder.tick()) == 1
        INBOX.put("first", "second")

        async def both_acked() -> bool:
            return INBOX.acked == ["first", "second"]

        await eventually(both_acked)
        assert await run_count(sessions) == 2
        row = await the_source(sessions)
        assert (row.lease_owner, row.accepted) == (WORKER, 2)
        assert state_of(row, pipeline_active=True, unsettled=0, bound=None, is_polled=True) is SourceState.LISTENING
        assert await holder.tick() == [], "a source this worker holds is not taken up twice"
    finally:
        await holder.stop()
    assert INBOX.closed == 1
    assert (await the_source(sessions)).lease_owner is None, "stopping lets the lease go"


async def test_pausing_closes_the_consumer_and_resuming_opens_it_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom())
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def opened_once() -> bool:
            return INBOX.opened == 1

        await eventually(opened_once)
        async with session_scope(sessions) as session:
            row = (await session.execute(sa.select(Source))).scalar_one()
            pipeline = await session.get(Pipeline, row.pipeline_id)
            assert pipeline is not None
            await set_paused(session, pipeline, row, paused=True)

        async def closed() -> bool:
            return INBOX.closed == 1

        await eventually(closed)
        assert await holder.tick() == [], "a paused source is not taken up"
        async with session_scope(sessions) as session:
            row = (await session.execute(sa.select(Source))).scalar_one()
            pipeline = await session.get(Pipeline, row.pipeline_id)
            assert pipeline is not None
            await set_paused(session, pipeline, row, paused=False)
        assert len(await holder.tick()) == 1
        INBOX.put("after")

        async def delivered() -> bool:
            return INBOX.acked == ["after"]

        await eventually(delivered)
    finally:
        await holder.stop()


async def test_deactivating_the_pipeline_closes_the_consumer_and_reactivating_opens_it_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom())
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def opened_once() -> bool:
            return INBOX.opened == 1

        await eventually(opened_once)
        async with session_scope(sessions) as session:
            await set_active(session, "mailroom", active=False)

        async def let_go() -> bool:
            return INBOX.closed == 1 and (await the_source(sessions)).lease_owner is None

        await eventually(let_go)
        INBOX.put("while-inactive")
        assert await holder.tick() == [], "a source of an inactive pipeline is not taken up"
        assert (await run_count(sessions), INBOX.acked) == (0, [])

        async with session_scope(sessions) as session:
            await set_active(session, "mailroom", active=True)
        assert len(await holder.tick()) == 1

        async def delivered() -> bool:
            return INBOX.acked == ["while-inactive"]

        await eventually(delivered)
        assert await run_count(sessions) == 1
    finally:
        await holder.stop()


async def test_a_pruned_pipeline_whose_document_is_applied_again_takes_its_source_up_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    from_directory = Provenance(source=ProvenanceSource.DIRECTORY, ref="mailroom.yaml")
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(mailroom()), provenance=from_directory)
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def opened_once() -> bool:
            return INBOX.opened == 1

        await eventually(opened_once)
        async with session_scope(sessions) as session:
            assert (await prune_absent(session, services, {"elsewhere"})).pruned == ["mailroom"]

        async def let_go() -> bool:
            return INBOX.closed == 1 and (await the_source(sessions)).lease_owner is None

        await eventually(let_go)
        INBOX.put("while-pruned")
        assert await holder.tick() == []

        async with session_scope(sessions) as session:
            result = await apply_document(session, services, load_text(mailroom()), provenance=from_directory)
        assert result.reactivated is True
        assert len(await holder.tick()) == 1

        async def delivered() -> bool:
            return INBOX.acked == ["while-pruned"]

        await eventually(delivered)
        assert await run_count(sessions) == 1
    finally:
        await holder.stop()


async def test_a_batch_received_for_an_inactive_pipeline_makes_no_run_and_is_not_acknowledged(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom())
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def opened_once() -> bool:
            return INBOX.opened == 1

        await eventually(opened_once)
        async with session_scope(sessions) as session:
            # Deactivated with no notification, as when the worker misses it.
            await session.execute(sa.update(Pipeline).values(active=False))
        INBOX.put("unseen")

        async def let_go() -> bool:
            return INBOX.closed == 1 and (await the_source(sessions)).lease_owner is None

        await eventually(let_go)
        assert (await run_count(sessions), INBOX.acked, INBOX.waiting) == (0, [], ["unseen"])
        row = await the_source(sessions)
        assert (row.poll_failures, row.last_error) == (0, None), "an inactive pipeline is not a failing source"
    finally:
        await holder.stop()


async def test_a_paused_apply_inserts_a_held_source_paused_and_no_consumer_opens(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        applied = await apply_document(session, services, load_text(mailroom()), paused=True)
    assert applied.sources.created == ["letters"]
    assert applied.sources.paused == ["letters"]
    assert (await the_source(sessions)).paused is True

    holder = Holder(sessions, services, owner=WORKER)
    try:
        assert await holder.tick() == []
        assert INBOX.opened == 0
        async with session_scope(sessions) as session:
            row = (await session.execute(sa.select(Source))).scalar_one()
            pipeline = await session.get(Pipeline, row.pipeline_id)
            assert pipeline is not None
            await set_paused(session, pipeline, row, paused=False)
        assert len(await holder.tick()) == 1
    finally:
        await holder.stop()


async def test_another_workers_live_lease_is_left_alone(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom())
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
        row.lease_owner = "another-worker"
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    holder = Holder(sessions, services, owner=WORKER)
    try:
        assert await holder.tick() == []
        assert len(await holder.tick(now=datetime.now(UTC) + timedelta(minutes=6))) == 1
    finally:
        await holder.stop()


async def test_a_batch_no_run_can_be_made_of_is_not_acknowledged_and_comes_back(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await apply(sessions, services, mailroom())

    async def refused(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(polling, "create_run", refused)
    holder = Holder(sessions, services, owner=WORKER)
    try:
        INBOX.put("lost?")
        await holder.tick()

        async def failed() -> bool:
            return (await the_source(sessions)).poll_failures == 1

        await eventually(failed)
        assert INBOX.acked == []
        assert INBOX.waiting == ["lost?"], "the broker has it again"
        row = await the_source(sessions)
        assert row.lease_owner is None
        assert state_of(row, pipeline_active=True, unsettled=0, bound=None, is_polled=True) is SourceState.FAILING

        monkeypatch.setattr(polling, "create_run", create_run)
        assert await holder.tick() == [], "it backs off first"
        assert len(await holder.tick(now=datetime.now(UTC) + timedelta(hours=1))) == 1

        async def delivered() -> bool:
            return INBOX.acked == ["lost?"]

        await eventually(delivered)
    finally:
        await holder.stop()


async def test_a_batch_that_fails_after_every_open_doubles_the_backoff(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    await apply(sessions, services, mailroom())

    async def refused(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(polling, "create_run", refused)
    holder = Holder(sessions, services, owner=WORKER)
    backoff = services.settings.source_backoff
    try:
        INBOX.put("poison")
        moment = datetime.now(UTC)
        for failures in range(1, 4):
            closed = INBOX.closed
            await holder.tick(now=moment)

            async def failed_again(closed: int = closed) -> bool:
                return INBOX.closed == closed + 1 and (await the_source(sessions)).lease_owner is None

            await eventually(failed_again)
            row = await the_source(sessions)
            assert row.poll_failures == failures
            assert row.next_poll_at is not None
            waited = row.next_poll_at - datetime.now(UTC)
            assert waited > backoff * 2 ** (failures - 1) - timedelta(seconds=5)
            moment = datetime.now(UTC) + timedelta(hours=1)
    finally:
        await holder.stop()


async def test_a_consumer_held_until_its_lease_renews_is_no_longer_failing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    INBOX.refuse_open = True
    await apply(sessions, services, mailroom())
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def failed() -> bool:
            return (await the_source(sessions)).poll_failures == 1

        await eventually(failed)
        await holder.stop()
        INBOX.refuse_open = False
        short = services.settings.model_copy(update={"source_poll_lease": timedelta(milliseconds=200)})
        holder = Holder(sessions, services.model_copy(update={"settings": short}), owner=WORKER)
        await holder.tick(now=datetime.now(UTC) + timedelta(hours=1))

        async def opened() -> bool:
            return INBOX.opened == 1

        await eventually(opened)
        assert (await the_source(sessions)).poll_failures == 1, "opening alone clears nothing"

        async def renewed() -> bool:
            row = await the_source(sessions)
            return (row.poll_failures, row.last_error) == (0, None)

        await eventually(renewed)
    finally:
        await holder.stop()


async def test_a_consumer_that_will_not_open_is_failing_and_backs_off(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    INBOX.refuse_open = True
    await apply(sessions, services, mailroom())
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def failed() -> bool:
            return (await the_source(sessions)).poll_failures == 1

        await eventually(failed)
        row = await the_source(sessions)
        assert row.last_error == "the inbox refused the connection"
        assert row.next_poll_at is not None and row.next_poll_at > datetime.now(UTC)
    finally:
        await holder.stop()


async def test_a_source_whose_stored_fields_its_kind_no_longer_reads_fails_by_name_and_backs_off(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A pack upgrade can leave a row whose config the installed kind refuses."""
    await apply(sessions, services, mailroom())
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Source))).scalar_one()
        row.config = {"folder": "front-desk"}
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()

        async def failed() -> bool:
            return (await the_source(sessions)).poll_failures == 1

        await eventually(failed)
        row = await the_source(sessions)
        assert row.last_error == SOURCE_CONFIG_UNREADABLE.render(
            code="letters", kind="tests.inbox", detail="name: Field required"
        )
        assert row.lease_owner is None
        assert row.next_poll_at is not None and row.next_poll_at > datetime.now(UTC), "it is not taken up again at once"
        assert INBOX.opened == 0
    finally:
        await holder.stop()


async def test_a_source_whose_lease_ran_out_under_a_live_consumer_is_not_opened_a_second_time(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom())
    holder = Holder(sessions, services, owner=WORKER)
    try:
        assert len(await holder.tick()) == 1

        async def opened() -> bool:
            return INBOX.opened == 1

        await eventually(opened)
        async with session_scope(sessions) as session:
            await session.execute(sa.update(Source).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        assert await holder.tick() == [], "the consumer still open keeps its source"
        assert (INBOX.opened, len(holder.holding)) == (1, 1)
    finally:
        await holder.stop()
    assert INBOX.closed == 1


async def test_what_a_held_source_raises_past_its_own_record_is_logged(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    INBOX.refuse_open = True
    await apply(sessions, services, mailroom())

    async def unrecordable(*_: object, **__: object) -> None:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(holding, "_failed", unrecordable)
    holder = Holder(sessions, services, owner=WORKER)
    try:
        await holder.tick()
        [task] = holder.holding.values()
        await asyncio.wait([task])
        with capture_logs() as logs:
            await holder.tick(now=datetime.now(UTC) - timedelta(hours=1))
        [said] = [entry for entry in logs if entry["event"] == "held source stopped unrecorded"]
        assert (said["log_level"], said["error"]) == ("error", "the database went away")
    finally:
        await holder.stop()


async def test_max_in_flight_holds_back_the_next_message(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, mailroom(extra="      max_in_flight: 1"))
    holder = Holder(sessions, services, owner=WORKER)
    try:
        INBOX.put("one", "two")
        await holder.tick()

        async def one_taken() -> bool:
            return INBOX.acked == ["one"]

        await eventually(one_taken)
        await asyncio.sleep(0.2)
        assert INBOX.waiting == ["two"], "the second waits while the first run is unsettled"
    finally:
        await holder.stop()
