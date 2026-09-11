"""Apply a document and run it, exiting non-zero when no run started or the run does not succeed.

The shape of a deploy job: one script, one exit code, no interpretation needed by whoever
reads the build log.

    export DG_URL=https://dirigent.example.org DG_TOKEN=...
    uv run python examples/python/ci_gate.py pipelines/daily-load.yaml

In a GitHub workflow:

    - run: uv run python examples/python/ci_gate.py pipelines/daily-load.yaml
      env:
        DG_URL: ${{ vars.DG_URL }}
        DG_TOKEN: ${{ secrets.DG_TOKEN }}
"""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from dirigent_client import Dirigent, DirigentError, PlanAction, ProvenanceSource, RunStatus, WaitTimeout

#: How long the job is willing to wait for the run before it gives up on it.
BUDGET = timedelta(hours=2)

#: Statuses this gate accepts. A run that tolerated an item failure is not a green build.
ACCEPTED = (RunStatus.SUCCEEDED,)


async def gate(document: Path, reference: str) -> int:
    """Apply, run, wait, and report; the return value is the job's exit code."""
    async with Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"]) as dg:
        applied = await dg.pipelines.apply(document, source=ProvenanceSource.FILE, source_ref=reference)
        plan = applied.plan
        if plan.action is PlanAction.INVALID:
            print(f"::error::{document} does not validate against this instance")
            for issue in plan.issues:
                print(f"  {issue}")
            return 1
        print(f"{plan.action.value} {plan.code} -> version {applied.version or plan.current_version}")

        accepted = await dg.pipelines.run(plan.code)
        if accepted.run_id is None:
            print(f"::error::not started: {accepted.detail}")
            return 1

        try:
            run = await dg.runs.wait(accepted.run_id, timeout=BUDGET)
        except WaitTimeout as timed_out:
            print(f"::error::{timed_out.message}")
            return 1

        report = await dg.runs.report(run.id)
        for step in report.steps:
            print(f"  {step.outcome:<10} {step.step:<24} {step.error or ''}")
        if run.status in ACCEPTED:
            print(f"{run.status.value} in {(report.duration_ms or 0) / 1000:.1f}s")
            return 0
        print(f"::error::run {run.id} {run.status.value}: {run.error or 'see the step table above'}")
        return 1


def main() -> int:
    """Read the document from the command line and run the gate over it."""
    reference = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "hello-world.yaml")
    try:
        return asyncio.run(gate(Path(reference), reference))
    except DirigentError as refusal:
        print(f"::error::{refusal.message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
