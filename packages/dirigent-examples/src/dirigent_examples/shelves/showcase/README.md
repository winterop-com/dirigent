# Showcase

Pipelines sized like the work, rather than cut down to one lesson. Every other shelf is
deliberately small -- one behaviour per file, so nothing distracts from it. This one is the
other extreme: documents with fifteen steps, eight-wide fan-outs, gates in the middle and a
page at the end, because that is what an operated pipeline looks like and it is what the
screens in [the screens page](../../docs/screens.md) are photographed on.

Nothing here needs infrastructure, a credential, an allowlist entry, or a network: where a
step has to do something it is `playground.generate`, a node that reaches nothing. The schemas
are carried in the documents, and the files land under the run's own scratch prefix.

| File | What it shows | Ends as |
| --- | --- | --- |
| [nightly-regional-load.yaml](nightly-regional-load.yaml) | Sixteen steps: a maintenance window, a gated catalogue read, submit-deposit-await per region, a per-region gate and write, two joins, and a page | `succeeded` |
| [one-region-refuses.yaml](one-region-refuses.yaml) | Eight exports where one fails until its retry budget is spent, the gap named rather than implied, and a report template of its own | `completed_with_errors` |
| [morning-briefing.yaml](morning-briefing.yaml) | The three jq verbs one per hop -- `filter.jq`, `map.jq`, `transform.jq` -- four feeds each narrowed and banded, joined and gated | `succeeded` |

```bash
dg run --local examples/showcase/nightly-regional-load.yaml
dg run --local examples/showcase/one-region-refuses.yaml     # completed_with_errors, by design
dg run --local examples/showcase/morning-briefing.yaml
```

## Watching one happen

A run that is green before the screen has drawn it teaches nothing about what a fan-out looks
like while it is in flight. `nightly-regional-load.yaml` carries a `pace` for that: it is the
seconds each region's export takes before its readiness probe answers, so eight items sit in
progress for as long as you ask them to.

```bash
dg run --local examples/showcase/nightly-regional-load.yaml -p pace=6
```

On an instance, the same knob is what the run screen is photographed through:

```bash
dg apply examples/showcase/nightly-regional-load.yaml
dg run nightly-regional-load -p pace=8 --watch
```

## What each one carries

All three carry their own `schemas:`, so a `--local` run has the shapes without an instance
holding them. An instance refuses a document that carries a schema, which is why
`dg pipeline new` moves a carried section into `requires:` when it copies a starter.

Two of them carry a `triggers:` section with a clock -- `nightly-regional-load` at 03:00 Oslo
time, `morning-briefing` at 06:30 -- so applying either brings its schedule with it. `dg dev
--seed` applies them paused.

All three declare a `report:`, so every run of them writes its own account of itself:
`one-region-refuses` brings a template that leads with the items that did not make it, and the
other two take the page the engine ships.
