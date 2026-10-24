"""A step is a block, a source or a reply: its rules, a run entered by hand, and a reply the server settles."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptKind, AttemptStatus, BodyKind, RunStatus, StepKind
from dirigent_client.schemas import EndpointInput
from dirigent_core.database import session_scope
from dirigent_core.documents import DocumentError, load_pipeline_text, validate_against_catalog
from dirigent_core.engine import EngineServices
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import Entry, RunCreationError, create_run, retry_step
from dirigent_core.messages import (
    BODY_WITHOUT_TYPE,
    ENDPOINT_BODY_NOT_JSON,
    ENTRY_AMBIGUOUS,
    ENTRY_INPUT_REFUSED,
    ENTRY_ON_NO_SOURCES,
    GIVEN_NO_ENTRY,
    NOT_ENTERED,
    REPLY_NO_SOURCE,
    ROOT_BESIDE_SOURCES,
    SCHEDULE_ON_SOURCES,
    SOURCE_NOT_RETRYABLE,
    UNKNOWN_KIND,
    UNSUPPORTED_MEDIA,
)
from dirigent_core.models import Run, StepAttempt
from dirigent_core.pipelines import save_pipeline
from dirigent_core.plugins import PluginHost
from dirigent_core.sources.endpoint import EndpointConfig, EndpointSource
from dirigent_core.sources.entries import EntryRefused, hand_entry
from dirigent_core.sources.kinds import built_in_kinds
from dirigent_plugin.sources import InboundRequest, ReceiveContext, Refusal
from test_engine import drain

RECEIVED_AT = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)

GREET = """
format: dirigent/v1
kind: pipeline
code: greet
steps:
  ask:
    source:
      kind: endpoint
      path: /greet/{name}
      methods: [POST]
    sample:
      path_params: {name: Oslo}
      body: {mood: cheerful}
  shape:
    block: test.echo
    depends_on: [ask]
    config:
      value: "hello ${steps.ask.output.path_params.name}"
  answer:
    depends_on: [shape]
    reply:
      status: 201
      body: {said: "${steps.shape.output.value}"}
"""

TWO_DOORS = """
format: dirigent/v1
kind: pipeline
code: two-doors
steps:
  front:
    source: {kind: endpoint, path: /front}
  back:
    source: {kind: endpoint, path: /back}
  either:
    block: test.echo
    depends_on: [front, back]
    rule: all_done
    config: {value: in}
"""


def document(text: str) -> Any:
    """Read a pipeline document as an apply would."""
    return load_pipeline_text(text)


def refused(text: str) -> str:
    """Read a document the model refuses, and say why."""
    with pytest.raises(DocumentError) as raised:
        load_pipeline_text(text)
    return str(raised.value)


def issues(text: str, host: PluginHost) -> list[str]:
    """The codes a document's sources and replies are refused with, against the built-in kinds."""
    found = validate_against_catalog(document(text), host.catalog(), source_kinds=built_in_kinds())
    return [issue.code for issue in found]


# -- the node model -------------------------------------------------------------------


def test_a_step_is_a_block_a_source_or_a_reply() -> None:
    definition = document(GREET)
    assert [definition.steps[name].kind for name in ("ask", "shape", "answer")] == [
        StepKind.SOURCE,
        StepKind.BLOCK,
        StepKind.REPLY,
    ]
    assert definition.sources == ["ask"]
    assert definition.replies == ["answer"]
    assert definition.steps["ask"].block_id == "endpoint"
    assert definition.steps["answer"].block_id == "reply"


def test_a_step_that_is_two_forms_at_once_is_refused() -> None:
    reason = refused(
        GREET.replace("      kind: endpoint\n", "      kind: endpoint\n").replace(
            "  shape:\n    block: test.echo", "  shape:\n    block: test.echo\n    reply: {status: 200}"
        )
    )
    assert "exactly one of block, source or reply" in reason


def test_a_source_takes_no_config_of_a_step() -> None:
    reason = refused(GREET.replace("    sample:\n", "    retry: {max_attempts: 3}\n    sample:\n"))
    assert "a source takes name, description and sample" in reason


def test_only_a_source_takes_a_sample() -> None:
    reason = refused(
        GREET.replace(
            "    block: test.echo\n    depends_on: [ask]", "    block: test.echo\n    sample: {}\n    depends_on: [ask]"
        )
    )
    assert "only a source takes a sample" in reason


def test_a_reply_takes_a_body_or_a_body_from_but_not_both() -> None:
    reason = refused(GREET.replace("      status: 201\n", "      status: 201\n      body_from: scratch://x\n"))
    assert "body or body_from, not both" in reason


def test_a_reply_status_outside_http_is_refused() -> None:
    assert "whole number from 200 to 599" in refused(GREET.replace("status: 201", "status: 99"))


# -- the rules a document with sources keeps ------------------------------------------


def test_a_pipeline_whose_steps_all_descend_from_its_source_is_valid(host: PluginHost) -> None:
    assert issues(GREET, host) == []


def test_a_root_beside_the_sources_is_refused(host: PluginHost) -> None:
    beside = GREET + "  stray:\n    block: test.echo\n    config: {value: alone}\n"
    assert ROOT_BESIDE_SOURCES.code in issues(beside, host)


def test_a_schedule_on_a_pipeline_with_sources_is_refused(host: PluginHost) -> None:
    scheduled = GREET + "triggers:\n  schedules:\n    - code: nightly\n      cron: '0 5 * * *'\n"
    assert SCHEDULE_ON_SOURCES.code in issues(scheduled, host)


def test_a_reply_without_a_source_is_refused(host: PluginHost) -> None:
    alone = """
format: dirigent/v1
kind: pipeline
code: no-door
steps:
  work:
    block: test.echo
    config: {value: x}
  answer:
    depends_on: [work]
    reply: {status: 200}
"""
    assert REPLY_NO_SOURCE.code in issues(alone, host)


def test_a_source_of_a_kind_nobody_provides_is_refused(host: PluginHost) -> None:
    assert UNKNOWN_KIND.code in issues(GREET.replace("kind: endpoint", "kind: carrier_pigeon"), host)


def test_branches_of_two_sources_join_under_all_done(host: PluginHost) -> None:
    assert issues(TWO_DOORS, host) == []
    assert issues(TWO_DOORS.replace("    rule: all_done\n", ""), host) != []


# -- a run entered by hand --------------------------------------------------------------


def test_a_hand_run_enters_the_only_source_with_its_sample() -> None:
    entry = hand_entry(document(GREET), built_in_kinds(), None, None, received_at=RECEIVED_AT)
    assert entry is not None
    assert entry.step == "ask"
    assert entry.via == "hand"
    assert entry.output["method"] == "POST"
    assert entry.output["path"] == "/greet/Oslo"
    assert entry.output["body"] == {"mood": "cheerful"}


def test_an_input_given_by_hand_replaces_the_sample() -> None:
    given: dict[str, Any] = {"path_params": {"name": "Bergen"}, "body": {"mood": "wet"}}
    entry = hand_entry(document(GREET), built_in_kinds(), "ask", given, received_at=RECEIVED_AT)
    assert entry is not None
    assert entry.output["path"] == "/greet/Bergen"


def test_an_input_the_kind_cannot_make_whole_is_refused() -> None:
    with pytest.raises(EntryRefused) as raised:
        hand_entry(document(GREET), built_in_kinds(), None, {"method": "GET"}, received_at=RECEIVED_AT)
    assert raised.value.code == ENTRY_INPUT_REFUSED.code


def test_a_pipeline_with_two_sources_needs_one_named() -> None:
    with pytest.raises(EntryRefused) as raised:
        hand_entry(document(TWO_DOORS), built_in_kinds(), None, None, received_at=RECEIVED_AT)
    assert raised.value.code == ENTRY_AMBIGUOUS.code
    entry = hand_entry(document(TWO_DOORS), built_in_kinds(), "back", None, received_at=RECEIVED_AT)
    assert entry is not None
    assert entry.step == "back"


def test_a_pipeline_without_sources_takes_no_entry() -> None:
    plain = document("format: dirigent/v1\nkind: pipeline\ncode: plain\nsteps:\n  one: {block: test.echo}\n")
    assert hand_entry(plain, built_in_kinds(), None, None, received_at=RECEIVED_AT) is None
    with pytest.raises(EntryRefused) as raised:
        hand_entry(plain, built_in_kinds(), "one", None, received_at=RECEIVED_AT)
    assert raised.value.code == ENTRY_ON_NO_SOURCES.code


# -- the engine -------------------------------------------------------------------------


async def start(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices, text: str, entry: Entry | None
) -> Run:
    """Save a pipeline and create one run of it, entered where ``entry`` says."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, document(text))
        run = await create_run(session, services, version, entry=entry)
    assert run is not None
    return run


async def attempts(sessions: async_sessionmaker[AsyncSession], run_id: Any) -> dict[str, StepAttempt]:
    """Read the newest attempt of every step of a run."""
    async with sessions() as session:
        rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == run_id))
        newest: dict[str, StepAttempt] = {}
        for row in rows.scalars():
            if row.step_name not in newest or row.attempt > newest[row.step_name].attempt:
                newest[row.step_name] = row
        return newest


async def test_a_run_entered_by_hand_flows_from_its_source_to_its_reply(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    entry = hand_entry(document(GREET), services.sources, None, None, received_at=RECEIVED_AT)
    run = await start(sessions, services, GREET, entry)
    await drain(engine)

    async with sessions() as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        assert stored.status is RunStatus.SUCCEEDED
        assert stored.source_step == "ask"
    settled = await attempts(sessions, run.id)
    assert settled["ask"].kind is AttemptKind.RECEIVED
    assert settled["ask"].status is AttemptStatus.SUCCEEDED
    assert settled["ask"].input == {"via": "hand"}
    assert settled["answer"].status is AttemptStatus.SUCCEEDED
    rendered = settled["answer"].output or {}
    assert rendered["status"] == 201
    assert rendered["body"] == {"said": "hello Oslo"}
    assert rendered["delivered"] is False, "a hand run holds no caller to deliver to"


async def test_a_reply_is_settled_by_the_server_and_never_claimed(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    entry = hand_entry(document(GREET), services.sources, None, None, received_at=RECEIVED_AT)
    run = await start(sessions, services, GREET, entry)
    claimed: list[str] = []
    moment = datetime.now(UTC)
    while (unit := await engine.claim(now=moment)) is not None:
        async with sessions() as session:
            row = await session.get(StepAttempt, unit.attempt_id)
            assert row is not None
            claimed.append(row.step_name)
        await engine.run_unit(unit, now=moment)
    assert claimed == ["shape"], "neither the source nor the reply is ever a worker's"
    assert (await attempts(sessions, run.id))["answer"].status is AttemptStatus.SUCCEEDED


async def test_the_source_a_run_did_not_enter_is_skipped_as_not_entered(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    entry = hand_entry(document(TWO_DOORS), services.sources, "front", None, received_at=RECEIVED_AT)
    run = await start(sessions, services, TWO_DOORS, entry)
    await drain(engine)
    settled = await attempts(sessions, run.id)
    assert settled["front"].status is AttemptStatus.SUCCEEDED
    assert settled["back"].status is AttemptStatus.SKIPPED
    assert settled["back"].error_code == NOT_ENTERED.code
    assert settled["either"].status is AttemptStatus.SUCCEEDED


async def test_a_pipeline_with_sources_is_not_run_without_an_entry(sessions: Any, services: EngineServices) -> None:
    with pytest.raises(RunCreationError) as raised:
        await start(sessions, services, GREET, None)
    assert raised.value.code == GIVEN_NO_ENTRY.code


async def test_a_source_is_not_retried(engine: Engine, sessions: Any, services: EngineServices) -> None:
    entry = hand_entry(document(GREET), services.sources, None, None, received_at=RECEIVED_AT)
    run = await start(sessions, services, GREET, entry)
    await drain(engine)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        with pytest.raises(RunCreationError) as raised:
            await retry_step(session, services, stored, "ask", idempotency_key="again")
    assert raised.value.code == SOURCE_NOT_RETRYABLE.code


def inbound(body: bytes = b"", **headers: str) -> InboundRequest:
    """A request to the echo route, as intake would hand it to the endpoint kind."""
    return InboundRequest(
        method="POST",
        path="/echo",
        route="/echo",
        headers={name.replace("_", "-"): value for name, value in headers.items()},
        body=body,
        received_at=RECEIVED_AT,
    )


ECHO_ROUTE = EndpointConfig(path="/echo")

NO_CONTEXT = cast("ReceiveContext", None)


def test_an_endpoint_refuses_a_media_type_it_does_not_take_before_reading_the_body() -> None:
    refused = EndpointSource().admit(ECHO_ROUTE, inbound(content_type="application/pdf"))
    assert refused is not None
    assert (refused.status, refused.code) == (415, UNSUPPORTED_MEDIA.code)
    untyped = EndpointSource().admit(ECHO_ROUTE, inbound(content_length="4"))
    assert untyped is not None
    assert (untyped.status, untyped.code) == (415, BODY_WITHOUT_TYPE.code)
    assert EndpointSource().admit(ECHO_ROUTE, inbound()) is None


async def test_an_endpoint_reads_a_body_by_its_content_type_and_drops_credentials() -> None:
    read = await EndpointSource().receive(
        ECHO_ROUTE,
        inbound(b'{"said": "hi"}', content_type="application/json", authorization="Bearer secret"),
        NO_CONTEXT,
    )
    assert isinstance(read, EndpointInput)
    assert (read.body_kind, read.body, read.body_bytes) == (BodyKind.JSON, {"said": "hi"}, 14)
    assert "authorization" not in read.headers
    form = await EndpointSource().receive(
        ECHO_ROUTE, inbound(b"said=hi", content_type="application/x-www-form-urlencoded"), NO_CONTEXT
    )
    assert isinstance(form, EndpointInput)
    assert form.body_kind is BodyKind.FORM


async def test_an_endpoint_refuses_a_body_that_is_not_what_it_says() -> None:
    refused = await EndpointSource().receive(
        ECHO_ROUTE, inbound(b"{not json", content_type="application/json"), NO_CONTEXT
    )
    assert isinstance(refused, Refusal)
    assert (refused.status, refused.code) == (400, ENDPOINT_BODY_NOT_JSON.code)
