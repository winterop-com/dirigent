# Demo examples

Documents that exist to show a surface rather than move data: the run form, the rendered
description, the `requires` preflight saying no with every reason at once, and a pair that
share one display name to prove a title is not a key.

```bash
dg run --local examples/demo/params-showcase.yaml -p day=2026-01-01 -p dataset=climate
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [params-showcase.yaml](params-showcase.yaml) | Every control a run form is built from, in one parameter schema. |
| [markdown-showcase.yaml](markdown-showcase.yaml) | A description is markdown: what the UI renders, from one document that uses all of it. |
| [requires.yaml](requires.yaml) | The preflight refused on purpose: every missing thing named in one list, before anything is stored. |
| [weekly-import-nepal.yaml](weekly-import-nepal.yaml) | Two pipelines, one display name: `name` is a title, not a key, and only `code` tells them apart. |
| [weekly-import-malawi.yaml](weekly-import-malawi.yaml) | The other half of the shared-name pair: same `name: Weekly import`, different code. |
