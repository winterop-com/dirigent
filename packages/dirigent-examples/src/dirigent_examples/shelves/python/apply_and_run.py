"""Apply a document, start a run, wait for it, and report what happened.

The canonical first script: everything a CI job or a scheduler-of-schedulers does.

    export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...
    uv run python examples/python/apply_and_run.py

hello-world.yaml uses shell.run, which executes code on the worker, so the instance must
allowlist it: DIRIGENT_ENABLED_UNSAFE_BLOCKS='["shell.run"]'.
"""

import asyncio
import os
from datetime import timedelta
from pathlib import Path

from dirigent_client import Dirigent, PlanAction, RunStatus

DOCUMENT = Path(__file__).resolve().parents[1] / "hello-world.yaml"


async def main() -> int:
    """Apply the document, run it, and wait for the run to settle."""
    async with Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"]) as dg:
        plan = await dg.pipelines.apply(DOCUMENT, dry_run=True)
        print(f"plan: {plan.plan.action.value} {plan.plan.code}")
        if plan.plan.action is PlanAction.INVALID:
            for issue in plan.plan.issues:
                print(f"  - {issue}")
            return 1

        applied = await dg.pipelines.apply(DOCUMENT)
        print(f"applied: {applied.plan.code} version {applied.version or applied.plan.current_version}")

        accepted = await dg.pipelines.run(applied.plan.code)
        if accepted.run_id is None:
            # Not a failure: the pipeline's concurrency policy declined a second run.
            print(f"not started: {accepted.detail}")
            return 0

        print(f"started: run {accepted.run_id}")
        run = await dg.runs.wait(accepted.run_id, timeout=timedelta(minutes=5))
        print(f"finished: {run.status.value} in {run.pipeline}")

        report = await dg.runs.report(run.id)
        for step in report.steps:
            print(f"  {step.outcome:<10} {step.step} ({step.block})")
        return 0 if run.status is RunStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
