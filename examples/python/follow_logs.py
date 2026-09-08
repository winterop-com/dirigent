"""Start a run and print its log entries as the workers write them.

    export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...
    uv run python examples/python/follow_logs.py

The tail is server-sent events; the client reopens a dropped connection from the last entry
it yielded, so a proxy timing the stream out does not lose or repeat a line.
"""

import asyncio
import os
from pathlib import Path

from dirigent_client import Dirigent

DOCUMENT = Path(__file__).resolve().parents[1] / "hello-world.yaml"


async def main() -> int:
    """Apply, run, and stream the run's log entries until it settles."""
    async with Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"]) as dg:
        applied = await dg.pipelines.apply(DOCUMENT)
        accepted = await dg.pipelines.run(applied.plan.code)
        if accepted.run_id is None:
            print(f"not started: {accepted.detail}")
            return 0

        print(f"following run {accepted.run_id}")
        async for entry in dg.runs.follow_logs(accepted.run_id):
            where = entry.step_name or "-"
            print(f"  {entry.level.value:<7} {where:<12} {entry.message}")

        run = (await dg.runs.get(accepted.run_id)).run
        print(f"{run.status.value}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
