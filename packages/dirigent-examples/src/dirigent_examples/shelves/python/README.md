# Driving an instance from Python

The YAML files above are pipelines. These are programs that drive an instance: each one is a
single file using [`dirigent-client`](../../packages/dirigent-client), the typed async SDK.

Every script reads `DG_URL` and `DG_TOKEN` from the environment, exactly as `dg` does:

```bash
export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...   # dg dev prints both
uv run python examples/python/apply_and_run.py
```

| Script | What it shows |
| --- | --- |
| [`apply_and_run.py`](apply_and_run.py) | Plan, apply, run, wait for the terminal state, print the report. |
| [`follow_logs.py`](follow_logs.py) | Stream a run's log entries as the workers write them. |
| [`list_and_filter.py`](list_and_filter.py) | Query pipelines and runs by pipeline, status, and window. |
| [`connections.py`](connections.py) | Create a credential record, check it, read it back redacted, delete it. |
| [`error_handling.py`](error_handling.py) | Provoke each typed refusal, and handle each on its own terms. |
| [`ci_gate.py`](ci_gate.py) | Apply and run in a build job, exiting non-zero when no run started or the run does not succeed. |

`apply_and_run.py`, `follow_logs.py`, and `ci_gate.py` apply
[`hello-world.yaml`](../hello-world.yaml), which uses `shell.run`. That block executes code
on the worker, so the instance must allowlist it:

```bash
export DIRIGENT_ENABLED_UNSAFE_BLOCKS='["shell.run"]'
```

The REST API remains available directly; see [docs/python.md](../../docs/python.md) for the
SDK reference and for what the raw endpoints answer with.
