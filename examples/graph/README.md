# Graph examples

The shapes a DAG takes: a straight line, branches that split and join, a fan over a list,
and a chain deep enough to watch the engine walk it. Every one runs with `dg run --local`,
and the ones that call out use only Postman Echo.

```bash
dg run --local examples/graph/linear.yaml -p day=2026-01-01 --enable-unsafe shell.run
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [linear.yaml](linear.yaml) | The straight line: fetch, archive, report, each step reading the one before it. |
| [parallel-branches.yaml](parallel-branches.yaml) | Two branches from one root, joined by a step that reads both. |
| [fan-out.yaml](fan-out.yaml) | `for_each` over a list: one item per region, and a refusal that fails the item rather than the fan. |
| [fan-in.yaml](fan-in.yaml) | The other direction: parallel fetches whose whole fan one step reads back as a list. |
| [wide-fan.yaml](wide-fan.yaml) | A fan wide enough to fill every worker slot, for watching concurrency rather than reading about it. |
| [deep-chain.yaml](deep-chain.yaml) | Ten steps in one line, each reading the one above it. |
| [skip-diamond.yaml](skip-diamond.yaml) | A diamond where one road is taken and the other settles as skipped, not failed. |
| [parallel-sleep.yaml](parallel-sleep.yaml) | Three independent waits at once, and the join that waits for all of them. |
