# Trigger examples

What starts a run on its own: a clock, or an inbound webhook. A trigger is declared in the
document and materialised by `dg apply`; the scheduler fires the clocks and the server
answers the hooks, on the instance the document was applied to. Operational state -- paused,
last fired, the firing and delivery history -- stays in the instance, so none of it appears
in these files. [docs/design.md](../../docs/design.md#the-misfire-policy) is the page behind
the clocks.

Each file is prefixed with the clock kind it teaches, the way `transform/`'s files are
prefixed with the engine kind: `cron-` for a calendar moment, `interval-` for a rolling
cadence, `at-` for a single firing. Every one of them also runs ad hoc, with nothing on the
allowlist and no network:

```bash
dg run --local examples/triggers/cron-nightly.yaml -p day=2026-01-01
```

One of them reads the window its firing covers, which no document declares and only a run
carries, so running it ad hoc means saying which interval it is for:

```bash
dg run --local examples/triggers/cron-windowed.yaml --window 2026-06-01..2026-06-02
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [cron-nightly.yaml](cron-nightly.yaml) | A calendar moment: five in the morning in the schedule's own zone, across daylight saving, with parameters pinned over the pipeline's defaults. |
| [cron-windowed.yaml](cron-windowed.yaml) | The interval a firing covers rather than the moment it happened at: `${run.window.start}` and `${run.window.end}`, derived from the cadence and read like a parameter. |
| [interval-rolling.yaml](interval-rolling.yaml) | A rolling cadence: when an interval beats a cron, and the misfire grace that turns a weekend outage into one firing rather than sixty. |
| [at-one-time.yaml](at-one-time.yaml) | The one-time firing: the backfill and the launch, and how a moment written without an offset is read in the schedule's own zone. |
| [managed-and-manual.yaml](managed-and-manual.yaml) | Against a real instance: what an apply materialises, what it removes, and the hand-made schedule it leaves alone. |
| [document-nightly.yaml](document-nightly.yaml) | A `kind: triggers` document: clocks for a pipeline defined elsewhere, owning its own rows and refusing a pipeline no instance holds. |
| [webhook-trigger.yaml](webhook-trigger.yaml) | The inbound trigger: a token minted at apply, a strict payload-to-parameter mapping, and everything else in the POST ignored. |

A pipeline carries as many schedules as it needs, each with its own zone and its own
parameters: nightly against production and hourly against staging is two schedules on one
pipeline, never two pipelines.

Every file here but one is a pipeline document that carries its own clocks, which is the
primary form: one file is one deployable unit, and its digest versions the triggers with the
steps. `document-nightly.yaml` is the other form, for a pipeline somebody else's file
defines -- it names `managed-and-manual`, so read the two together.
