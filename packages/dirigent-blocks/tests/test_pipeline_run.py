"""Tests for ``pipeline.run``: starting another pipeline, waiting on it, and giving up on it."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from dirigent_blocks.pipelines import (
    DEFAULT_MAX_DEPTH,
    MAX_DEPTH_LIMIT,
    SKIPPED,
    STARTED,
    PipelineRunConfig,
    PipelineRunOperator,
    PipelineRunOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle, RunRefused, RunState
from dirigent_testing import FakeContext


def handle_for(run_id: object, pipeline: str = "child") -> RemoteHandle:
    """Build the handle the engine would have carried between execute and probe."""
    return RemoteHandle(block_id="pipeline.run", ref=str(run_id), meta={"pipeline": pipeline})


# -- the config ------------------------------------------------------------------


def test_the_config_defaults_to_waiting_at_a_bounded_depth() -> None:
    config = PipelineRunConfig(pipeline="child")
    assert config.wait is True
    assert config.strict is False
    assert config.max_depth == DEFAULT_MAX_DEPTH
    assert config.params == {}


def test_the_config_refuses_a_name_that_is_not_an_entity_name() -> None:
    with pytest.raises(ValidationError):
        PipelineRunConfig(pipeline="Not A Pipeline")


def test_the_config_refuses_a_depth_outside_its_bounds() -> None:
    with pytest.raises(ValidationError):
        PipelineRunConfig(pipeline="child", max_depth=0)
    with pytest.raises(ValidationError):
        PipelineRunConfig(pipeline="child", max_depth=MAX_DEPTH_LIMIT + 1)


# -- execute ---------------------------------------------------------------------


async def test_waiting_hands_the_engine_a_handle_on_the_child_run(ctx: FakeContext) -> None:
    config = PipelineRunConfig(pipeline="child", params={"day": "2026-01-01"})

    produced = await PipelineRunOperator().execute(config, ctx.as_context())

    assert isinstance(produced, RemoteHandle)
    assert produced.block_id == "pipeline.run"
    assert produced.meta["pipeline"] == "child"
    assert ctx.runs.started == [("child", {"day": "2026-01-01"}, DEFAULT_MAX_DEPTH)]
    assert "child run started" in ctx.log.messages()


async def test_not_waiting_finishes_the_step_the_moment_the_child_exists(ctx: FakeContext) -> None:
    config = PipelineRunConfig(pipeline="child", wait=False)

    produced = await PipelineRunOperator().execute(config, ctx.as_context())

    assert isinstance(produced, PipelineRunOutput)
    assert produced.status == STARTED
    assert produced.pipeline == "child"
    assert produced.run_id is not None


async def test_a_child_the_concurrency_policy_dropped_is_reported_rather_than_failed(ctx: FakeContext) -> None:
    ctx.runs.skip.add("child")

    produced = await PipelineRunOperator().execute(PipelineRunConfig(pipeline="child"), ctx.as_context())

    assert isinstance(produced, PipelineRunOutput)
    assert produced.status == SKIPPED
    assert produced.run_id is None
    assert "the child pipeline's concurrency policy dropped this run" in ctx.log.messages()


async def test_a_refusal_from_the_instance_reaches_the_step_as_a_rejection(ctx: FakeContext) -> None:
    ctx.runs.refusal = "pipeline 'child' cannot start itself"

    with pytest.raises(RunRefused) as refusal:
        await PipelineRunOperator().execute(PipelineRunConfig(pipeline="child"), ctx.as_context())

    assert refusal.value.error_class is ErrorClass.REJECTED
    assert PipelineRunOperator().classify_error(refusal.value) is ErrorClass.REJECTED


async def test_the_configured_depth_is_the_one_the_instance_is_asked_to_enforce(ctx: FakeContext) -> None:
    await PipelineRunOperator().execute(PipelineRunConfig(pipeline="child", max_depth=2), ctx.as_context())
    assert ctx.runs.started[0][2] == 2


# -- probe -----------------------------------------------------------------------


@pytest.mark.parametrize("state", [RunState.QUEUED, RunState.RUNNING])
async def test_an_unsettled_child_keeps_the_step_waiting_with_progress(ctx: FakeContext, state: RunState) -> None:
    run_id = ctx.runs.hold("child", state, total_steps=4, finished_steps=1)

    probe = await PipelineRunOperator().probe(handle_for(run_id), PipelineRunConfig(pipeline="child"), ctx.as_context())

    assert probe.status is ProbeStatus.RUNNING
    assert probe.progress == 0.25
    assert probe.message == "1 of 4 steps finished"


async def test_a_succeeded_child_settles_the_step(ctx: FakeContext) -> None:
    run_id = ctx.runs.hold("child", RunState.SUCCEEDED, total_steps=2, finished_steps=2)

    probe = await PipelineRunOperator().probe(handle_for(run_id), PipelineRunConfig(pipeline="child"), ctx.as_context())

    assert probe.status is ProbeStatus.SUCCEEDED


async def test_a_tolerated_child_succeeds_by_default_and_fails_under_strict(ctx: FakeContext) -> None:
    run_id = ctx.runs.hold("child", RunState.COMPLETED_WITH_ERRORS)
    handle = handle_for(run_id)

    lenient = await PipelineRunOperator().probe(handle, PipelineRunConfig(pipeline="child"), ctx.as_context())
    strict = await PipelineRunOperator().probe(
        handle, PipelineRunConfig(pipeline="child", strict=True), ctx.as_context()
    )

    assert lenient.status is ProbeStatus.SUCCEEDED
    assert "tolerated" in (lenient.message or "")
    assert strict.status is ProbeStatus.FAILED
    assert "strict is set" in (strict.message or "")


@pytest.mark.parametrize("state", [RunState.FAILED, RunState.CANCELLED])
async def test_a_failed_or_cancelled_child_fails_the_step_and_carries_its_reason(
    ctx: FakeContext, state: RunState
) -> None:
    run_id = ctx.runs.hold("child", state)
    ctx.runs.snapshots[run_id] = ctx.runs.snapshots[run_id].model_copy(update={"error": "the load step failed"})

    probe = await PipelineRunOperator().probe(handle_for(run_id), PipelineRunConfig(pipeline="child"), ctx.as_context())

    assert probe.status is ProbeStatus.FAILED
    assert "the load step failed" in (probe.message or "")


async def test_a_failed_child_with_no_recorded_reason_still_explains_itself(ctx: FakeContext) -> None:
    run_id = ctx.runs.hold("child", RunState.FAILED)
    probe = await PipelineRunOperator().probe(handle_for(run_id), PipelineRunConfig(pipeline="child"), ctx.as_context())
    assert "no reason was recorded" in (probe.message or "")


async def test_a_child_this_instance_no_longer_holds_reads_as_gone(ctx: FakeContext) -> None:
    config = PipelineRunConfig(pipeline="child")
    probe = await PipelineRunOperator().probe(handle_for(uuid4()), config, ctx.as_context())
    assert probe.status is ProbeStatus.GONE


async def test_a_handle_that_does_not_name_a_run_is_a_rejection(ctx: FakeContext) -> None:
    handle = RemoteHandle(block_id="pipeline.run", ref="not-a-uuid")
    with pytest.raises(BlockFailure) as failure:
        await PipelineRunOperator().probe(handle, PipelineRunConfig(pipeline="child"), ctx.as_context())
    assert failure.value.error_class is ErrorClass.REJECTED


# -- fetch and cancel ------------------------------------------------------------


async def test_fetching_reports_which_run_it_was_and_how_it_settled(ctx: FakeContext) -> None:
    run_id = ctx.runs.hold("child", RunState.COMPLETED_WITH_ERRORS)
    config = PipelineRunConfig(pipeline="child")

    output = await PipelineRunOperator().fetch(handle_for(run_id), config, ctx.as_context())

    assert output == PipelineRunOutput(pipeline="child", run_id=str(run_id), status="completed_with_errors")
    assert "child run finished" in ctx.log.messages()


async def test_a_child_that_vanished_between_probe_and_fetch_is_transient(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as failure:
        await PipelineRunOperator().fetch(handle_for(uuid4()), PipelineRunConfig(pipeline="child"), ctx.as_context())
    assert failure.value.error_class is ErrorClass.TRANSIENT


async def test_cancelling_the_step_cancels_the_child_run(ctx: FakeContext) -> None:
    run_id = ctx.runs.hold("child", RunState.RUNNING)

    assert await PipelineRunOperator().cancel(handle_for(run_id), PipelineRunConfig(pipeline="child"), ctx.as_context())

    assert ctx.runs.cancelled == [run_id]
    assert ctx.runs.snapshots[run_id].state is RunState.CANCELLED
    assert "child run cancelled" in ctx.log.messages()


async def test_cancelling_a_child_that_already_settled_reports_that_nothing_happened(ctx: FakeContext) -> None:
    run_id = ctx.runs.hold("child", RunState.SUCCEEDED)

    accepted = await PipelineRunOperator().cancel(
        handle_for(run_id), PipelineRunConfig(pipeline="child"), ctx.as_context()
    )

    assert accepted is False
    assert "the child run had already settled" in ctx.log.messages()


# -- the whole loop --------------------------------------------------------------


async def test_execute_probe_fetch_reads_as_one_story(ctx: FakeContext) -> None:
    operator = PipelineRunOperator()
    config = PipelineRunConfig(pipeline="child")

    submitted = await operator.execute(config, ctx.as_context())
    assert isinstance(submitted, RemoteHandle)
    run_id = UUID(submitted.ref)

    running = await operator.probe(submitted, config, ctx.as_context())
    assert running.status is ProbeStatus.RUNNING

    ctx.runs.snapshots[run_id] = ctx.runs.snapshots[run_id].model_copy(
        update={"state": RunState.SUCCEEDED, "total_steps": 1, "finished_steps": 1}
    )
    settled = await operator.probe(submitted, config, ctx.as_context())
    assert settled.status is ProbeStatus.SUCCEEDED

    output = await operator.fetch(submitted, config, ctx.as_context())
    assert output.status == "succeeded"
    assert output.run_id == str(run_id)


def test_the_block_declares_a_cadence_a_child_run_reads_well_against() -> None:
    spec = PipelineRunOperator().spec
    assert spec.id == "pipeline.run"
    assert spec.default_poll is not None
    assert not spec.idempotent
    assert not spec.local_execution
