# dirigent-client

The dirigent API contract: typed wire schemas and an async Python client.

```python
from datetime import timedelta

from dirigent_client import Dirigent

async with Dirigent(url="https://dirigent.example.org", token=token) as dg:
    plan = await dg.pipelines.apply("pipelines/daily-climate-load.yaml", dry_run=True)
    run = await dg.pipelines.run("daily-climate-load", params={"day": "2026-08-29"})
    final = await dg.runs.wait(run.run_id, timeout=timedelta(hours=2))
    async for entry in dg.runs.follow_logs(run.run_id):
        print(entry.message)
```

The package holds the pydantic schemas for every request and response the REST API speaks,
and `dirigent-server` imports them, so the client and the server can never disagree about a
shape. It depends on `dirigent-common`, `httpx2`, `pydantic`, and `pyyaml`, and on nothing else in the
workspace.

`docs/python.md` has the worked examples, and `examples/python/` has six runnable scripts.
