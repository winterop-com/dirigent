"""A run's facts, assembled from a run driven to settlement by the engine."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AlertEvent, LogLevel, RunItemStatus, RunStatus
from dirigent_common import render
from dirigent_core.alerting import AlertRuleRequest, create_rule
from dirigent_core.artifacts import canonical_json, load_document
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import (
    ItemPolicy,
    PipelineDefinition,
    ReportSpec,
    RetryPolicy,
    StepDefinition,
)
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.runs import cancel_run, retry_step
from dirigent_core.models import ArtifactRef, LogEntry, Notification, Pipeline, PipelineVersion, Run
from dirigent_core.plugins import PluginHost
from dirigent_core.reporting import DEFAULT_TEMPLATE, RunFacts, as_context, run_facts
from dirigent_plugin import AlertMessage, Contribution, Notifier
from engineblocks import EngineTestPlugin, FailOperator
from test_engine import drain, reload, start, steps

FAST_RETRY = RetryPolicy(max_attempts=1)

RENDERED_AT = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)

CHAIN = PipelineDefinition(
    code="reported-chain",
    steps=steps(
        first=StepDefinition(block="test.echo", config={"value": "hei"}),
        second=StepDefinition(
            block="test.echo",
            depends_on=["first"],
            config={"value": "${steps.first.output.value} again"},
        ),
    ),
)


async def facts_of(
    sessions: async_sessionmaker[AsyncSession],
    run: Run,
    definition: PipelineDefinition,
    *,
    base_url: str | None = None,
) -> RunFacts:
    """Read one run's facts back, the way a route or the engine would."""
    async with session_scope(sessions) as session:
        reloaded = await session.get(Run, run.id)
        assert reloaded is not None
        pipeline = await session.get(Pipeline, reloaded.pipeline_id)
        version = await session.get(PipelineVersion, reloaded.pipeline_version_id)
        assert pipeline is not None
        assert version is not None
        return await run_facts(
            session, reloaded, pipeline, version, definition, base_url=base_url, rendered_at=RENDERED_AT
        )


async def test_a_settled_chain_reports_its_steps_in_execution_order(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    assert [step.step for step in facts.steps] == ["first", "second"]
    assert [step.outcome for step in facts.steps] == ["succeeded", "succeeded"]
    assert [step.attempts for step in facts.steps] == [1, 1]
    assert [step.depends_on for step in facts.steps] == [[], ["first"]]
    assert [step.block for step in facts.steps] == ["test.echo", "test.echo"]
    assert all(step.duration_ms is not None for step in facts.steps)
    assert all(step.error is None and step.warnings == 0 for step in facts.steps)


async def test_a_step_carries_the_output_of_its_last_attempt(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    outputs = {step.step: step.output for step in facts.steps}
    assert outputs == {"first": {"value": "hei", "length": 3}, "second": {"value": "hei again", "length": 9}}


async def test_the_run_namespace_says_what_the_run_was(engine: Engine, sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    assert facts.run["status"] == RunStatus.SUCCEEDED.value
    assert facts.run["pipeline"] == "reported-chain"
    assert facts.run["id"] == str(run.id)
    assert facts.run["window_start"] is None
    assert facts.run["window_end"] is None
    assert facts.run["trace_id"] is None
    assert facts.pipeline.code == "reported-chain"
    assert facts.pipeline.version == 1
    assert facts.items == []
    assert facts.items_total == 0
    assert facts.items_failed == 0


async def test_a_run_has_a_url_only_when_the_instance_names_one(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, CHAIN)
    await drain(engine)

    without = await facts_of(sessions, run, CHAIN)
    assert without.url is None
    assert without.run["url"] is None

    with_base = await facts_of(sessions, run, CHAIN, base_url="https://dirigent.example/")
    assert with_base.url == f"https://dirigent.example/runs/{run.id}"
    assert with_base.run["url"] == with_base.url


async def test_the_facts_render_as_plain_json(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """A template and a stored notification read the facts as JSON, so every value has to be one."""
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    context = as_context(await facts_of(sessions, run, CHAIN))

    assert json.loads(json.dumps(context)) == context
    assert context["pipeline"]["code"] == "reported-chain"
    assert [step["step"] for step in context["steps"]] == ["first", "second"]


async def test_a_failing_step_carries_its_error_and_its_failed_items(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = PipelineDefinition(
        code="reported-batch",
        steps=steps(
            push=StepDefinition(
                block="test.fail",
                for_each=["good-1", "bad", "good-2"],
                config={"fail_times": 1, "key": "${item}", "message": "the push broke"},
                items=ItemPolicy.CONTINUE,
                retry=FAST_RETRY,
            ),
            after=StepDefinition(block="test.echo", depends_on=["push"]),
        ),
    )
    run = await start(sessions, services, definition)
    FailOperator.attempts["good-1"] = 1
    FailOperator.attempts["good-2"] = 1
    await drain(engine)
    facts = await facts_of(sessions, run, definition)

    assert facts.run["status"] == RunStatus.COMPLETED_WITH_ERRORS.value
    push = next(step for step in facts.steps if step.step == "push")
    assert push.attempts == 3
    assert push.error == "the push broke"
    assert facts.items_total == 3
    assert facts.items_failed == 1
    failed = next(item for item in facts.items if item.status is RunItemStatus.FAILED)
    assert failed.key == "bad"
    assert failed.index == 1
    assert failed.failing_step == "push"
    assert failed.error == "the push broke"


async def test_a_step_names_the_uri_its_output_spilled_to(sessions: Any, settings: Settings, host: PluginHost) -> None:
    """An output too large to inline is a URI in the facts, so a report can link it."""
    services = EngineServices.build(settings.model_copy(update={"inline_artifact_max": 0}), host)
    engine = Engine(sessions, services, owner="worker-under-test")
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    assert all(step.output_uri is not None and step.output_uri.startswith("file://") for step in facts.steps)
    assert facts.steps[0].output == {"value": "hei", "length": 3}


async def test_the_step_map_and_the_step_list_are_the_same_facts(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A template reads one hop by name, and it reads what the list says about that hop."""
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    assert list(facts.step) == [step.step for step in facts.steps], "the map keeps execution order"
    assert facts.step["second"] is facts.steps[1]
    context = as_context(facts)
    assert context["step"]["second"] == context["steps"][1]
    assert context["step"]["second"]["output"]["value"] == "hei again"


async def test_a_step_says_how_large_its_output_was(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """The bytes are the stored output's, so the `bytes` filter has a size to render."""
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    first = facts.step["first"]
    assert first.output is not None
    assert first.output_bytes == len(canonical_json(first.output))
    async with sessions() as session:
        rows = await session.execute(
            sa.select(ArtifactRef.size_bytes).where(ArtifactRef.run_id == run.id, ArtifactRef.step_name == "first")
        )
        assert rows.scalar_one() == first.output_bytes


async def test_a_step_that_never_ran_carries_no_size(engine: Engine, sessions: Any, services: EngineServices) -> None:
    definition = PipelineDefinition(
        code="reported-halt",
        steps=steps(
            only=StepDefinition(block="test.fail", config={"fail_times": 1}, retry=FAST_RETRY),
            after=StepDefinition(block="test.echo", depends_on=["only"]),
        ),
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    facts = await facts_of(sessions, run, definition)

    assert facts.step["after"].output is None
    assert facts.step["after"].output_bytes is None


async def test_the_facts_say_when_they_were_assembled(engine: Engine, sessions: Any, services: EngineServices) -> None:
    run = await start(sessions, services, CHAIN)
    await drain(engine)
    facts = await facts_of(sessions, run, CHAIN)

    assert facts.rendered_at == RENDERED_AT
    assert as_context(facts)["rendered_at"] == "2026-01-01T05:00:00Z", "an ISO 8601 instant, for the iso filter"


# -- the report document ---------------------------------------------------------

REPORTED = CHAIN.model_copy(update={"code": "reported-document", "report": ReportSpec()})


@pytest.fixture
def host() -> PluginHost:
    """A plugin host carrying the engine's test blocks and one channel an alert can reach."""
    return PluginHost(
        {
            "engine-tests": EngineTestPlugin().contribute(),
            "report-tests": Contribution(notifiers=[RecordingNotifier()]),
        }
    )


class RecordingNotifier(Notifier):
    """A notifier that accepts everything, so a rule has something to name."""

    id = "recording"
    config_model = BaseModel

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Accept the message and forget it."""


def reporting(definition: PipelineDefinition, template: str | None = None) -> PipelineDefinition:
    """The same pipeline, asking for a report document."""
    return definition.model_copy(update={"report": ReportSpec(template=template)})


async def documents_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[ArtifactRef]:
    """Read the run-level artifacts a run left, which is where its report document lands."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(ArtifactRef)
            .where(ArtifactRef.run_id == run_id, ArtifactRef.step_attempt_id.is_(None))
            .order_by(ArtifactRef.id)
        )
        return list(rows.scalars())


async def only_document(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> ArtifactRef:
    """Read the one report document a run has, insisting there is exactly one."""
    rows = await documents_of(sessions, run_id)
    assert len(rows) == 1, f"{len(rows)} run-level artifacts"
    return rows[0]


async def warnings_of(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[LogEntry]:
    """Read the warnings a run's timeline carries."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(LogEntry).where(LogEntry.run_id == run_id, LogEntry.level == LogLevel.WARNING)
        )
        return list(rows.scalars())


async def test_a_settled_run_renders_the_built_in_document(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, REPORTED)
    await drain(engine)

    document = await only_document(sessions, run.id)
    assert document.content_type == "text/markdown"
    assert document.step_name is None
    assert document.uri is None, "a small document inlines"
    assert document.inline_value is not None
    text = document.inline_value["text"]
    assert isinstance(text, str)
    assert "reported-document" in text
    assert "| first |" in text
    assert "| second |" in text
    assert document.size_bytes == len(text.encode())
    assert document.digest is not None


async def test_a_run_of_a_document_with_no_report_leaves_none(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    run = await start(sessions, services, CHAIN)
    await drain(engine)

    assert await documents_of(sessions, run.id) == []


async def test_the_built_in_document_reads_as_the_markdown_it_is(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The table has one row per step under one header, so a reader sees the run at a glance."""
    run = await start(sessions, services, REPORTED)
    await drain(engine)
    facts = await facts_of(sessions, run, REPORTED)

    text = render(DEFAULT_TEMPLATE, as_context(facts), max_bytes=1_000_000)
    lines = text.splitlines()
    assert lines[0] == "# reported-document run succeeded"
    assert lines.count("| step | outcome | attempts | took | output | warnings |") == 1
    assert len([line for line in lines if line.startswith("| ") and " | succeeded | " in line]) == 2
    assert "## Failed items" not in text
    assert "## Error" not in text
    assert "\n\n\n" not in text, "the whitespace control leaves no gaps"


async def test_a_template_that_builds_more_than_the_cap_leaves_a_warning_and_no_document(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """A runaway template costs the report, never the run."""
    definition = reporting(REPORTED, "{% for index in range(100000) %}every single line of it, again{% endfor %}")
    run = await start(sessions, services, definition)
    await drain(engine)

    assert await documents_of(sessions, run.id) == []
    warned = await warnings_of(sessions, run.id)
    assert [entry.message for entry in warned] == ["the run's report was not rendered"]
    assert "1mb" in str((warned[0].fields or {})["reason"])
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_a_template_that_reaches_for_another_degrades_the_same_way(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    definition = reporting(REPORTED, '{% include "elsewhere.md" %}')
    run = await start(sessions, services, definition)
    await drain(engine)

    assert await documents_of(sessions, run.id) == []
    warned = await warnings_of(sessions, run.id)
    assert [entry.message for entry in warned] == ["the run's report was not rendered"]
    assert (await reload(sessions, run.id)).status is RunStatus.SUCCEEDED


async def test_a_document_too_large_to_inline_lands_under_the_runs_scratch(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(settings.model_copy(update={"inline_artifact_max": 0}), host)
    engine = Engine(sessions, services, owner="worker-under-test")
    run = await start(sessions, services, REPORTED)
    await drain(engine)

    document = await only_document(sessions, run.id)
    assert document.inline_value is None
    assert document.uri is not None
    assert document.uri.startswith("file://")
    assert document.uri.endswith(f"{run.id}/report.md")
    assert document.scheme == "file"
    assert await load_document(services.storage, document) != ""


async def test_a_cancelled_run_has_a_report(engine: Engine, sessions: Any, services: EngineServices) -> None:
    """The runs whose report matters most are the ones no step of them could have written."""
    run = await start(sessions, services, REPORTED)
    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await cancel_run(session, services, stored, reason="an operator asked")

    document = await only_document(sessions, run.id)
    assert document.inline_value is not None
    text = document.inline_value["text"]
    assert isinstance(text, str)
    assert "run cancelled" in text
    assert "an operator asked" in text


async def test_a_run_that_settles_a_second_time_rewrites_the_document_it_already_has(
    engine: Engine, sessions: Any, services: EngineServices
) -> None:
    """The id survives a retry, so a link an alert already carries keeps resolving."""
    definition = reporting(
        PipelineDefinition(
            code="reported-retry",
            steps=steps(
                only=StepDefinition(block="test.fail", config={"fail_times": 1}, retry=FAST_RETRY),
            ),
        )
    )
    run = await start(sessions, services, definition)
    await drain(engine)
    first = await only_document(sessions, run.id)
    assert (await reload(sessions, run.id)).status is RunStatus.FAILED
    failed = first.inline_value["text"] if first.inline_value else ""

    async with session_scope(sessions) as session:
        stored = await session.get(Run, run.id)
        assert stored is not None
        await retry_step(session, services, stored, "only", idempotency_key="retry-1")
    await drain(engine)

    second = await only_document(sessions, run.id)
    assert second.id == first.id
    assert (second.inline_value or {})["text"] != failed
    assert "run succeeded" in str((second.inline_value or {})["text"])


async def test_a_queued_alert_names_the_document_the_run_rendered(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(settings.model_copy(update={"alert_base_url": "https://dirigent.test/"}), host)
    engine = Engine(sessions, services, owner="worker-under-test")
    async with session_scope(sessions) as session:
        await create_rule(
            session,
            services,
            AlertRuleRequest(code="tell-ops", event=AlertEvent.RUN_SUCCEEDED, notifier="recording"),
        )
    run = await start(sessions, services, REPORTED)
    await drain(engine)

    document = await only_document(sessions, run.id)
    async with sessions() as session:
        rows = await session.execute(sa.select(Notification).where(Notification.run_id == run.id))
        notification = rows.scalar_one()
    context = notification.context
    assert context["run"]["report_url"] == f"https://dirigent.test/api/v1/artifacts/{document.id}"
    assert context["pipeline"]["code"] == "reported-document", "the whole facts, not the run namespace alone"
    assert [step["step"] for step in context["steps"]] == ["first", "second"]


async def test_an_alert_for_a_run_with_no_report_names_no_document(
    sessions: Any, settings: Settings, host: PluginHost
) -> None:
    services = EngineServices.build(settings.model_copy(update={"alert_base_url": "https://dirigent.test/"}), host)
    engine = Engine(sessions, services, owner="worker-under-test")
    async with session_scope(sessions) as session:
        await create_rule(
            session,
            services,
            AlertRuleRequest(code="tell-ops", event=AlertEvent.RUN_SUCCEEDED, notifier="recording"),
        )
    run = await start(sessions, services, CHAIN)
    await drain(engine)

    async with sessions() as session:
        rows = await session.execute(sa.select(Notification).where(Notification.run_id == run.id))
        notification = rows.scalar_one()
    assert notification.context["run"]["report_url"] is None


# -- what a settlement pays for ---------------------------------------------------


@pytest.fixture
def counted_facts(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Record the run of every facts assembly, so a settlement's cost is countable."""
    from dirigent_core import reporting

    assembled: list[UUID] = []
    original = reporting.run_facts

    async def counting(session: Any, run: Run, *args: Any, **kwargs: Any) -> RunFacts:
        assembled.append(run.id)
        return await original(session, run, *args, **kwargs)

    monkeypatch.setattr(reporting, "run_facts", counting)
    return assembled


async def test_a_run_with_no_report_and_no_rule_assembles_no_facts(
    engine: Engine, sessions: Any, services: EngineServices, counted_facts: list[UUID]
) -> None:
    """Nothing asked for the facts, so settling the run does not pay for them."""
    await start(sessions, services, CHAIN)
    await drain(engine)

    assert counted_facts == []


async def test_a_declared_report_assembles_the_facts_once(
    engine: Engine, sessions: Any, services: EngineServices, counted_facts: list[UUID]
) -> None:
    run = await start(sessions, services, REPORTED)
    await drain(engine)

    assert counted_facts == [run.id], "rendered once, and the alerts reuse what it built"


async def test_a_matching_rule_assembles_the_facts_a_report_did_not(
    engine: Engine, sessions: Any, services: EngineServices, counted_facts: list[UUID]
) -> None:
    """A rule reads the whole facts, so a pipeline with a rule and no report still gets them."""
    async with session_scope(sessions) as session:
        await create_rule(
            session,
            services,
            AlertRuleRequest(code="tell-ops", event=AlertEvent.RUN_SUCCEEDED, notifier="recording"),
        )
    run = await start(sessions, services, CHAIN)
    await drain(engine)

    assert counted_facts == [run.id]
    async with sessions() as session:
        rows = await session.execute(sa.select(Notification).where(Notification.run_id == run.id))
        notification = rows.scalar_one()
    assert [step["step"] for step in notification.context["steps"]] == ["first", "second"]
