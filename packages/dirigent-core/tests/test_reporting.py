"""A run's facts, assembled from a run driven to settlement by the engine."""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import RunItemStatus, RunStatus
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.engine import EngineServices
from dirigent_core.engine.definition import ItemPolicy, PipelineDefinition, RetryPolicy, StepDefinition
from dirigent_core.engine.executor import Engine
from dirigent_core.models import Pipeline, PipelineVersion, Run
from dirigent_core.plugins import PluginHost
from dirigent_core.reporting import RunFacts, as_context, run_facts
from engineblocks import FailOperator
from test_engine import drain, start, steps

FAST_RETRY = RetryPolicy(max_attempts=1)

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
        return await run_facts(session, reloaded, pipeline, version, definition, base_url=base_url)


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
