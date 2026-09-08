"""``pipeline.run``: one pipeline starting another on the same instance."""

from datetime import timedelta
from typing import ClassVar, Final
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel, EntityName
from dirigent_plugin import (
    BlockFailure,
    ErrorClass,
    Operator,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    RunSnapshot,
    RunState,
    StepContext,
)

DEFAULT_MAX_DEPTH: Final = 5

MAX_DEPTH_LIMIT: Final = 32

CHILD_POLL: Final = timedelta(seconds=5)

STARTED: Final = "started"

SKIPPED: Final = "skipped"

PIPELINE_META: Final = "pipeline"


class PipelineRunConfig(BlockModel):
    """Which pipeline to start, with what parameters, and whether to wait for it."""

    pipeline: EntityName
    """The code of the pipeline to run, on this same instance."""

    params: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    """The child's parameters, validated against *its* schema when the step executes.

    Written out rather than inherited from the parent. A child's parameter schema is its
    own published interface, and quietly forwarding whatever the parent happened to be run
    with is how two pipelines end up coupled through a field neither of them declares."""

    wait: bool = True
    """Whether the step waits for the child to finish, or reports it started and moves on."""

    strict: bool = False
    """Whether a child that finished ``completed_with_errors`` fails this step."""

    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=1, le=MAX_DEPTH_LIMIT)
    """How many pipelines deep the chain reaching this run may already be."""


class PipelineRunOutput(BlockModel):
    """What the child run amounted to, which downstream steps reference by field."""

    pipeline: str
    run_id: str | None = None
    """The child run, or None when its concurrency policy meant no run was created."""

    status: str
    """The child's run status, ``started`` when this step did not wait, or ``skipped``."""


class PipelineRunOperator(Operator[PipelineRunConfig, PipelineRunOutput]):
    """Starts a run of another pipeline on this instance, and optionally waits for it."""

    spec = OperatorSpec(
        id="pipeline.run",
        group="execute",
        summary="Run another pipeline on this instance.",
        idempotent=False,
        default_poll=CHILD_POLL,
    )
    config_model: ClassVar[type[BaseModel]] = PipelineRunConfig
    output_model: ClassVar[type[BaseModel]] = PipelineRunOutput

    async def execute(self, config: PipelineRunConfig, ctx: StepContext) -> PipelineRunOutput | RemoteHandle:
        """Create the child run, then hand back a claim on it or report that it started."""
        started = await ctx.runs.start(config.pipeline, config.params, max_depth=config.max_depth)
        if started.run_id is None:
            ctx.log.warning(
                "the child pipeline's concurrency policy dropped this run",
                pipeline=config.pipeline,
            )
            return PipelineRunOutput(pipeline=config.pipeline, status=SKIPPED)
        ctx.log.info("child run started", pipeline=config.pipeline, run_id=str(started.run_id), waiting=config.wait)
        if not config.wait:
            return PipelineRunOutput(pipeline=config.pipeline, run_id=str(started.run_id), status=STARTED)
        return RemoteHandle(
            block_id=self.spec.id,
            ref=str(started.run_id),
            meta={PIPELINE_META: config.pipeline},
        )

    async def probe(self, handle: RemoteHandle, config: PipelineRunConfig, ctx: StepContext) -> ProbeResult:
        """Read where the child run has got to, and map its state onto this step's."""
        snapshot = await ctx.runs.snapshot(_run_id(handle))
        if snapshot is None:
            return ProbeResult(status=ProbeStatus.GONE, message=f"this instance no longer holds run {handle.ref}")
        match snapshot.state:
            case RunState.QUEUED | RunState.RUNNING:
                return ProbeResult(
                    status=ProbeStatus.RUNNING,
                    message=_progress_message(snapshot),
                    progress=snapshot.progress,
                )
            case RunState.SUCCEEDED:
                return ProbeResult(status=ProbeStatus.SUCCEEDED, message=f"run {handle.ref} succeeded")
            case RunState.COMPLETED_WITH_ERRORS:
                tolerated = f"run {handle.ref} finished with errors its own pipeline tolerated"
                if config.strict:
                    return ProbeResult(status=ProbeStatus.FAILED, message=f"{tolerated}, and strict is set")
                return ProbeResult(status=ProbeStatus.SUCCEEDED, message=tolerated)
            case RunState.FAILED | RunState.CANCELLED:
                return ProbeResult(
                    status=ProbeStatus.FAILED,
                    message=f"run {handle.ref} {snapshot.state.value}: {snapshot.error or 'no reason was recorded'}",
                )

    async def fetch(self, handle: RemoteHandle, config: PipelineRunConfig, ctx: StepContext) -> PipelineRunOutput:
        """Report the settled child: which run it was, and what it settled as."""
        snapshot = await ctx.runs.snapshot(_run_id(handle))
        if snapshot is None:
            raise BlockFailure(
                f"run {handle.ref} disappeared before its result could be read",
                error_class=ErrorClass.TRANSIENT,
            )
        ctx.log.info(
            "child run finished",
            pipeline=config.pipeline,
            run_id=handle.ref,
            status=snapshot.state.value,
            error=snapshot.error,
        )
        return PipelineRunOutput(
            pipeline=snapshot.pipeline or handle.meta.get(PIPELINE_META, config.pipeline),
            run_id=handle.ref,
            status=snapshot.state.value,
        )

    async def cancel(self, handle: RemoteHandle, config: PipelineRunConfig, ctx: StepContext) -> bool:
        """Cancel the child run; False means it had already settled on its own."""
        cancelled = await ctx.runs.cancel(_run_id(handle), reason="the run waiting on it was cancelled")
        ctx.log.info("child run cancelled" if cancelled else "the child run had already settled", run_id=handle.ref)
        return cancelled


def _run_id(handle: RemoteHandle) -> UUID:
    """Read the child run's id off the handle, refusing a handle that does not name one."""
    try:
        return UUID(handle.ref)
    except ValueError as error:
        raise BlockFailure(f"the handle {handle.ref!r} does not name a run", error_class=ErrorClass.REJECTED) from error


def _progress_message(snapshot: RunSnapshot) -> str:
    """Say how far the child has come, in the units an operator watching it thinks in."""
    return f"{snapshot.finished_steps} of {snapshot.total_steps} steps finished"
