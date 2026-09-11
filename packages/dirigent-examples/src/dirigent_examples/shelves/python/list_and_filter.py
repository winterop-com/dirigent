"""Query runs by pipeline, status, and how far back to look, and print them as a table.

    export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...
    uv run python examples/python/list_and_filter.py

Every listing answers a page: `items`, and a `next` cursor to pass back as `after` when
there is more. A window (`since`) and a limit are still how a report bounds itself; the
cursor is how it reads past the first page without asking for a bigger one.
"""

import asyncio
import os

from dirigent_client import Dirigent, RunStatus

#: The window a report covers, in the humane duration grammar the whole product uses.
WINDOW = "24h"


async def main() -> int:
    """Print the pipelines this instance holds, and its recent runs."""
    async with Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"]) as dg:
        pipelines = await dg.pipelines.list()
        print(f"{'pipeline':<28} {'version':<8} {'active':<7} {'in flight'}")
        for pipeline in pipelines.items:
            version = str(pipeline.current_version or "-")
            print(f"{pipeline.code:<28} {version:<8} {str(pipeline.active):<7} {pipeline.active_runs}")

        print(f"\nruns in the last {WINDOW}")
        print(f"{'run':<38} {'pipeline':<20} {'status':<22} {'started'}")
        for run in (await dg.runs.list(since=WINDOW, limit=20)).items:
            started = run.started_at.isoformat() if run.started_at else "-"
            print(f"{run.id!s:<38} {run.pipeline:<20} {run.status.value:<22} {started}")

        # Walking the cursor is how a report covers a window larger than one page.
        failed = []
        after = None
        while True:
            page = await dg.runs.list(status=RunStatus.FAILED, since=WINDOW, after=after)
            failed.extend(page.items)
            if page.next is None:
                break
            after = page.next

        print(f"\n{len(failed)} failed in the last {WINDOW}")
        for run in failed:
            print(f"  {run.id}  {run.pipeline}  {run.error or 'no error recorded'}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
