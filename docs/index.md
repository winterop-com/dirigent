# dirigent

**A pipeline orchestrator where pipelines are data, not Python files.**

Dirigent runs directed graphs of work: fetch this, wait for that, fan out over those, and tell
someone if it breaks. It knows nothing about any particular system -- every integration arrives
as a plugin package contributing blocks to a catalog, and the catalog is what validates
pipelines and renders the builder's forms. Installing a plugin extends the product
without a frontend release.

## The mental model

A **pipeline** is a document: a parameter schema, a set of **steps**, and the edges between
them. Each step names a **block** -- an *operator* that does work, or a *sensor* that waits for
the world -- and gives it config. You apply that document to an instance, which stores it as an
immutable version, and every **run** pins the version it started from, so a run's history is
still readable years later.

The engine is a set of PostgreSQL tables and two kinds of loop, and deliberately nothing else:
there is no in-memory scheduler state anywhere, so any process can be killed at any moment and
the system resumes from the database. Waiting is the case this shape is built for -- a sensor
watching for a file, or an operator that submitted a job to some external system, parks as a
row with a due time rather than as a held worker, so ten thousand things in flight cost ten
thousand rows.

## What that buys you

- **Pipelines live in git, and apply is idempotent.** YAML in, canonical YAML out,
  byte-identical on a round trip. A CI job that applies the whole repository on every merge does
  not accumulate a version per commit, because a matching digest means "unchanged, nothing to
  do".
- **Submit-then-probe is the core primitive**, not an integration detail. Nearly every
  interesting external system publishes a job and then reports on it; every remote wait here is
  durable state polled by whichever worker is free.
- **Failures compose instead of being coded.** Retry policy over the block's own error
  classification, edge rules for what a failure means downstream, per-item isolation on a
  fan-out, and a run status derived from the leaves. An error branch is an ordinary step behind
  a `one_failed` edge, drawn in the graph.
- **One database, no broker.** One transaction per state transition, so no outbox and no
  reconciliation bugs. Scaling out is more replicas pointed at the same PostgreSQL.
- **It does not ship open.** An orchestrator is a credential vault with an execute button.
  Authentication from the first milestone, connection secrets encrypted at rest, and blocks that
  execute code on a worker disabled unless the instance explicitly allowlists them.

## Sixty seconds

The fastest way to see it work needs no server, no database, and no Docker:

```bash
uv tool install dirigent-cli
dg run --local examples/hello-world.yaml
```

```text
running examples/hello-world.yaml locally, on a throwaway database
  queued          greet (shell.run)
                  greet | hello from dirigent
                  greet | command finished
  succeeded       greet (shell.run)

succeeded  run 01a04d45-6737-70b7-9d19-0e9dc750c24a
```

`--local` applies and runs the document in a throwaway SQLite instance in a temporary
directory, with no server anywhere: the same apply, the same engine, the same worker loop,
deleted afterwards. A local run that executed differently would prove nothing.

[Getting started](getting-started.md) takes it from there -- `dg dev` for a laptop instance,
then the three-service compose stack, an admin account, and a token.

## Where to go next

- **[Getting started](getting-started.md)** is install to first successful run, then the real
  deployment: what each process does, what has to be configured, and what to do when it does
  not work.
- **[Tutorial](tutorial.md)** builds one realistic pipeline end to end -- a sensor, a fan-out,
  an error branch -- then breaks it on purpose so you can read a real diagnosis and learn what
  a run actually is.
- **[Concepts](concepts.md)** is the vocabulary: pipeline, step, block, run, item, attempt,
  connection, trigger, artifact, and how they relate.
- **[The command line](cli.md)** covers profiles, projects, the parameter builder, and what a
  run looks like while it is happening.
- **[Python](python.md)** is how to drive an instance from a program: the `dirigent-client`
  SDK, its accessors and its typed refusals, and the REST API underneath it.
- **[Block reference](blocks.md)** is every block an instance has, with its config and its
  output. Generated from the live catalog, so it cannot go stale. A family with more to say
  than a table has its own page: [transforms](transforms.md) and [jq](jq.md),
  [docker](docker.md), [git](git.md), [SQL](sql.md), [queues](queues.md), and
  [JSON Schema](json-schema.md).
- **[Plugins](plugins.md)** is how to contribute to that catalog: the five surfaces a package
  can extend, and what a block author writes.
- **[Operations](operations.md)** is for whoever has to run this: deployment shapes, every
  `DIRIGENT_*` setting, scaling, migrations, backups, health checks, what to monitor, and an
  honest list of what is not built.
- **[Telemetry](telemetry.md)** is the OpenTelemetry surface: which spans and metrics exist,
  which processes export them, and the exact environment that turns it on.
- **[Security](security.md)** is the threat model, what authenticates and what authorizes, the
  secrets lifecycle, and what is deliberately still missing.
- **[Design](design.md)** is the in-repo specification: architecture, data model, engine rules,
  and why each decision was made rather than the alternative.

## Where the project is

What an instance holds today: the execution engine, the plugin host and its catalog,
URI-addressed storage, envelope-encrypted connection secrets, the `dirigent/v1` document format
with `dg apply` / `dg export`, the authenticated REST surface, the web UI the server ships,
the scheduler with its advisory lock and misfire policy, webhook intake, alert rules delivered
through a retried notification queue, `dirigent-storage-s3`, the built-in block families
([HTTP, storage, shell, docker, git, sql, the queue sensors and the transform verbs](blocks.md)),
and OpenTelemetry instrumentation.

Retention is off until you configure it: each family has its own age and nothing
is pruned until one is set. See [retention](operations.md#retention), and [known
debt](operations.md#known-debt) before running this in anger. What is left to build is
[the roadmap](https://github.com/winterop-com/dirigent/blob/main/ROADMAP.md).

The block contract lives in `packages/dirigent-plugin`. It is small and stable on purpose,
because it is the only dirigent package a third-party block imports.
