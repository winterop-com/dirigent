# Composition examples

Pipelines made of pipelines: a child that stands on its own, a parent that runs it per
region, and a handoff to a second instance when the next stage belongs to somebody else.
`pipeline.run` keeps the child a first-class run -- its own id, its own log, its own row --
rather than steps inlined into the parent.

```bash
dg run --local examples/composition/composition-parent.yaml --also-apply examples/composition/composition-child.yaml -p day=2026-01-01 --enable-unsafe shell.run
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [composition-child.yaml](composition-child.yaml) | The reusable unit: callable on its own, or by whatever composes it. |
| [composition-parent.yaml](composition-parent.yaml) | `pipeline.run` per region: one child waited for, one fired and left to finish alone. |
| [chained-instances.yaml](chained-instances.yaml) | Across the boundary: the result handed to another dirigent instance as a signed webhook, because the next stage is theirs. |
