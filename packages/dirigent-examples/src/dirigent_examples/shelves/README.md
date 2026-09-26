# Example pipelines

Every file here is a real `dirigent/v1` document, and every one of them runs. A test walks
this directory on every CI run: the documents in `examples/` are validated against the real
block catalog, and every document, including the previews, must survive a
parse-export-reparse round trip unchanged.

[`python/`](python) is the other half of the corpus: the documents here describe pipelines,
and the scripts there drive an instance that holds them, through the `dirigent-client` SDK.

The documents live on topic shelves, each with its own README:

| Shelf | What lives there |
| --- | --- |
| [`graph/`](graph) | The shapes a DAG takes: lines, branches, fans, joins, and skips. |
| [`patterns/`](patterns) | One engine behaviour per file: rules, retries, the two clocks, item policies, triggers, concurrency, and the reference language. |
| [`playground/`](playground) | Documents that need something to happen: generated rows, a step that fails twice, a shape that drifts, a page to walk. |
| [`failure/`](failure) | Retries, budgets, timeouts, tolerated failures, and the cleanup edge. |
| [`transform/`](transform) | The reshaping verbs: jq programs and the `convert.std` codec, no allowlist anywhere. |
| [`recipes/`](recipes) | One question per file: how to group, join, pivot, clean, convert, check, store, and call. |
| [`triggers/`](triggers) | What starts a run on its own: the three clocks, and the inbound webhook. |
| [`sensors/`](sensors) | Steps that wait for the world: a drop landing, a clock window opening. |
| [`queues/`](queues) | A run started by a message: a Kafka topic and a RabbitMQ queue, waited on as sensors. |
| [`execute/`](execute) | Code on the worker: a shell step behind the allowlist. |
| [`docker/`](docker) | The container family: run one, watch it live, build an image and push it, and bring a whole compose stack up and down, on the worker's daemon or one a connection names. |
| [`git/`](git) | An existing project brought into a run: a repository checked out, then built and brought up from what it ships. |
| [`sql/`](sql) | A database read and written: bound parameters, one transaction, and a result handed to storage when it belongs in a file. |
| [`composition/`](composition) | Pipelines made of pipelines, and the handoff to a second instance. |
| [`s3/`](s3) | Object storage through the `s3://` scheme, with no S3 block anywhere. |
| [`demo/`](demo) | Surfaces shown off: the run form, rendered markdown, the requires preflight, the weekly-import shared-name pair. |
| [`showcase/`](showcase) | Pipelines sized like the work: fifteen steps, eight-wide fan-outs, gates in the middle and a page at the end. |
| [`open-data/`](open-data) | Real feeds against public, mostly keyless APIs: acme, health indicators, maps, earthquakes, humanitarian data. |
| [`validate/`](validate) | A gate that checks a value's shape and passes it through: `validate.schema`, with the shape carried and named. |
| [`schemas/`](schemas) | Not documents but the shapes they are held to: plain JSON Schemas, applied on their own and referenced by code. |

**The tag rule.** Every document's `tags:` is drawn from one vocabulary of three groups and
nothing else. The **shelf** is the directory the file sits in, exactly one, and every document
wears it. The **block families** are what its steps use, read off the block ids: `http`,
`transform` (the jq verbs and the `convert.std` codec), `storage` (a storage block, or a
converter's `source` and `target`), `execute` (shell and docker), `sql`, `git`, `webhook`
(`webhook.post`, or an inbound webhook trigger), `kafka`, `rabbitmq`, `pipeline`, `validate`,
and `sensor` for any sensor block. The **behaviours** are what the document teaches and what a
reader filters by: `schedule`, `fan-out`, `graph`, `failure`, `retry`, `timeout`,
`concurrency`, `params`, `references`, `rules`, `priority`, `window`, `composition`,
`credential`, `outputs`, `filter`, `map`, `relay`, `csv`, `parquet`, `jq`, `sparql`,
`geocode`, `briefing`, `observability`, `conventions`, `report` for a document that
declares a `report:` section, so every run of it writes its own account of itself, or renders
a page of its own with `report.render`, and `starter` for a document `dg pipeline new` may
copy into a project: a real multi-step flow on a real source. A source's name is never a tag:
the pipeline's `code` and `name` already say it is USGS or WHO GHO, and a word one document
wears is a filter nobody can use.

**The starter rule.** `starter` is the one tag a document opts into rather than wears by
description, and it is the narrowest. A document earns it by being a real multi-step flow on
a real source -- a public endpoint, or a service a connection names. What disqualifies one is
a run that fails by design, a single step, and a hello-world. Carrying does not: a document
carries its `connections:` and its `schemas:` so that `dg run --local` runs it alone, and the
copy names them instead. `dg pipeline new <code>` copies a starter's text verbatim into
`pipelines/`, rewriting the `code:` line, dropping `starter` from the `tags:` line, and
moving each carried section into `requires:`, so the comments come with it and its `requires`
is the list of what to create first.

**The tiering rule.** `examples/` is what runs: every document there is runnable, though some
need infrastructure whose setup their headers document -- the [`docker/`](docker) shelf needs a
Docker socket or a daemon a connection names, [`queues/`](queues) needs the brokers
`infra/compose.queues.yaml` starts, `sql-postgres-readonly.yaml` needs a PostgreSQL,
`s3-round-trip.yaml` needs an S3-compatible endpoint and a connection to it, and the documents
that make a real HTTP call need a `dg dev` to make it to.
`preview/` is for what cannot run yet because the *code* does not exist: documents whose block
ids belong to adapter packs nobody has written. A missing credential is not a preview; a
missing package is.

Almost nothing here reaches the network. Where a document needs something to *happen* --
rows to fan out over, a step that fails twice, a shape that drifts, a payload over the
storage threshold -- it uses `playground.generate`, a node that generates it and reaches
nothing at all. So you can run any of these for real without standing anything up:

```bash
dg run --local examples/hello-world.yaml
dg run --local examples/graph/linear.yaml -p day=2026-01-01 --enable-unsafe shell.run
dg run --local examples/failure/retries.yaml --enable-unsafe shell.run  # the retry policy fires
dg run --local examples/composition/chained-instances.yaml \
  --connections examples/connections.yaml -p day=2026-01-01
```

Most of these use `shell.run`, which executes code on the worker and is refused unless the
instance allowlists it. `--enable-unsafe shell.run` allows it for one command; the instance
setting allows it for good:

```bash
export DIRIGENT_ENABLED_UNSAFE_BLOCKS='["shell.run"]'
```

Not every one of them succeeds, and that is the point of three of them:

| Example | Ends as | Because |
| --- | --- | --- |
| `failure/retries.yaml` | `completed_with_errors` | The publish endpoint refuses three times; the failure is tolerated |
| `failure/error-handler.yaml` | `failed` | The load fails, so the alert branch runs and the success branch is skipped |
| `sensors/sensor-gate.yaml` | `succeeded` | The drop never lands, so the sensor skips and the branch skips with it |
| `failure/optional-step.yaml` | `completed_with_errors` | The metrics push exits 3 and is tolerated, so the branch below it still runs |
| `failure/retry-budget.yaml` | `failed` | A command that always exits 1, given three attempts to prove it |
| `failure/step-timeout.yaml` | `failed` | A thirty-second sleep against a two-second budget, so it fails in about two |
| `graph/skip-diamond.yaml` | `succeeded` | Green, with one step skipped: the handler had nothing to handle |
| `showcase/one-region-refuses.yaml` | `completed_with_errors` | One region's export answers 500 until its retry budget is spent; the other seven load |

`dg run --local` applies and runs the document in a throwaway SQLite instance that is
deleted afterwards -- no server, no Docker, no database. When a step fails it prints the
failing step, its block, the error class, the message, and that attempt's log lines before
the database goes away. Against a real instance it is the same two commands:

```bash
dg apply examples/graph/linear.yaml
dg run linear -p day=2026-01-01 --watch
```

The documents that are *about* HTTP are the exception, and they call the playground routes a
dirigent instance serves under `/api/v1/playground`, unauthenticated: the whole
[`recipes/` HTTP section](recipes/README.md), the connection and webhook files on
[`patterns/`](patterns), [`demo/requires.yaml`](demo/requires.yaml) and
[`composition/chained-instances.yaml`](composition/chained-instances.yaml). A local run mounts
no API of its own, so start an instance first and they reach that:

```bash
dg dev &
dg run --local examples/recipes/http-get-with-query.yaml
```

The CI lane that walks these files never touches the network: it validates the documents
and round-trips them, and the execution tests elsewhere use a mock transport.

## Engine patterns

[`patterns/`](patterns) is the reference shelf. Every other shelf is organised by what a
pipeline is *for*; that one is organised by what the engine *does*, one behaviour per file,
named for what it shows: the four trigger rules, the retry policy's five fields, `timeout`
against `deadline` against `on_timeout`, the two item policies, the three clocks a trigger can
be, the four concurrency policies, the four questions `pipeline.run` answers, and every
`${...}` form the reference language allows.

Each header says what to expect before you run it, because several of them fail on purpose:

```bash
dg run --local examples/patterns/rule-one-failed.yaml          # failed, and the alert branch ran
dg run --local examples/patterns/fan-out-continue.yaml         # completed_with_errors, two items of three
dg run --local examples/patterns/timeout-skips-the-step.yaml   # succeeded, having skipped the branch
```

Nothing on that shelf runs code on the worker, so none of it needs `--enable-unsafe`. Four
files are handed something a bare local run does not have -- a window, a connections file, a
child document -- and [patterns/README.md](patterns/README.md) indexes all of them with the
outcome each one settles as.

## Connections

Three of the examples reference a connection by code. Documents are portable precisely because
they name credentials rather than carrying them, so the credential has to exist wherever the
document is applied. On a server, create it once:

```bash
dg connection create http playground \
  --set base_url=http://127.0.0.1:3333/api/v1/playground \
  --set basic_username=playground --set basic_password=playground
```

A local run has no server to hold it, so it is handed the connection instead:

```bash
dg run --local examples/demo/requires.yaml --connections examples/connections.yaml
```

[connections.yaml](connections.yaml) is that file. The basic-auth credentials in it are the
playground's own documented pair, which guards nothing. `basic_password` is a `SecretStr`, so
it is encrypted at rest and redacted in every API response.

## Schemas

[`schemas/`](schemas) holds a few named JSON Schemas: the shape a read is expected to return,
written down so a pipeline can be refused the moment it sees a payload that moved. A schema is
locally authored -- it is a picture you hold of the payload, never something fetched from the
source -- so it lives here as a plain JSON Schema and is applied on its own, not as part of a
pipeline document:

```bash
dg schema create examples/schemas/ou-record.json
```

A schema reads its own identity from its keywords: `$id` becomes the `code` it is addressed
by, `title` its name, and `description` its body. A server that applies a directory at boot
stores the schemas it finds there too, before the pipelines that require them, so mounting this
whole directory lands the schemas as well as the documents. See
[schemas/README.md](schemas/README.md) and the [JSON Schema guide](../docs/json-schema.md).

## Recipes

[`recipes/`](recipes) is the widest shelf and the one to read while doing the work rather
than while learning the format. Each file answers one question a person doing data work
actually asks -- how do I group and sum, how do I join two lists, which types survive a
parquet round trip, where do credentials live -- in a complete pipeline whose header comment
is the lesson. Nothing on the shelf needs infrastructure, a credential, or an allowlist
entry: the data is inline, generated by a jq program, or generated by `playground.generate`.
The recipes under HTTP and webhooks call the instance's own playground, so those want a
`dg dev` running.

```bash
dg run --local examples/recipes/jq-group-by-and-sum.yaml
dg run --local examples/recipes/etl-csv-clean-validate-parquet.yaml
dg run --local examples/recipes/schema-refuses-then-rule.yaml   # fails, by design
```

Two of them end `failed` on purpose and say so in their headers:
`recipes/schema-refuses-then-rule.yaml`, where a gate refuses and the error branch runs, and
`recipes/reconcile-two-sources.yaml`, where the two sources disagree past the tolerance the
run was given. [recipes/README.md](recipes/README.md) indexes all forty-seven by the question
each one answers.

## The examples

Each shelf's README indexes its own documents; what stays at the root is the front door:

| File | What it demonstrates |
| --- | --- |
| [hello-world.yaml](hello-world.yaml) | The smallest runnable document: one step, no parameters, nothing granted |
| [connections.yaml](connections.yaml) | The credential file a `--local` run is handed |

Two of them are worth running twice, because a parameter flips which branch is taken:

```bash
# publish succeeds; still completed_with_errors as the cache times out
dg run --local examples/failure/retries.yaml -p status=200 --enable-unsafe shell.run
# the success branch, not the alert
dg run --local examples/failure/error-handler.yaml -p status=200 --enable-unsafe shell.run
```

## Preview documents

[`preview/`](preview) holds documents whose blocks or packages an instance may not have. They
are valid `dirigent/v1` and they round-trip, but applying one to an instance without what it
names is refused by the `requires` preflight with a list of what is missing. They are here to
show that the format never grows per-integration syntax: everything domain-specific lives
inside `config`, which the format treats as opaque and each block validates against its own
published schema.

[`preview/s3-parquet-to-ingestion.yaml`](preview/s3-parquet-to-ingestion.yaml) is the one on
the shelf today: every block it names is installed, and what it needs is the
`dirigent-storage-s3` package and an endpoint for the `s3://` scheme it addresses.

## Composing pipelines

A dirigent document holds exactly one pipeline, so a parent and its child are two files, and
the apply order matters: the child has to exist before the parent will apply at all. The
parent says so in `requires.pipelines`, so a missing child is refused up front, with the
code to apply first, rather than failing at the step.

```bash
dg apply examples/composition/composition-child.yaml
dg apply examples/composition/composition-parent.yaml
dg run composition-parent -p day=2026-01-01 --watch
```

A local run starts on an empty throwaway instance, so the child is handed over with
`--also-apply`, which applies a document without running it:

```bash
dg run --local examples/composition/composition-parent.yaml \
  --also-apply examples/composition/composition-child.yaml \
  -p day=2026-01-01 --enable-unsafe shell.run
```

## Why every example is self-contained

Almost every document here defines the pipeline it schedules or hooks, because a pipeline
document carries its own `triggers:` section and one file is then one deployable unit. That
is what keeps the schedule examples runnable on their own: each teaches one clock, and a
reader can fire it ad hoc without applying anything else first.

The other form has its own example. A `kind: triggers` document declares clocks and webhooks
for a pipeline defined somewhere else and names it -- the ops team's clock file over a
pipeline another team owns. [triggers/document-nightly.yaml](triggers/document-nightly.yaml)
is that document, and it targets the pipeline in
[triggers/managed-and-manual.yaml](triggers/managed-and-manual.yaml), so the two teach
together: apply the pipeline, then apply its clocks.

## Putting the whole corpus into one instance

`make dev-seeded` boots a `dg dev --seed examples` with everything on this page already
applied, so there is something to look at without applying forty documents by hand. The
instance walks this directory for `dirigent/v1` documents, creates the connections
[connections.yaml](connections.yaml) carries, applies each document with its schedules
paused, and creates what a document carries for its own standalone run before applying it
without that section. The target adds what only the demo wants: the object store
`s3-round-trip.yaml` names, a document pointed at a connection nothing holds, six runs, and
one health check per connection. Then it hands the terminal to `dg dev`; one ctrl-c ends both.

```bash
make dev-seeded | dg format
```

**Seeing failures is the point.** An instance where everything is green teaches nothing about
what a failure looks like, so the seeded one is deliberately mixed:

| What lands | How many | Why |
| --- | --- | --- |
| Pipelines stored | 162 | Every document here that an instance will hold, including the ones that carry their own connections or schemas: the seed creates what they carry and applies the rest, which is the only form an instance stores |
| Documents refused | 18 | Nine in [docker/](docker) and two in [git/](git) name a compose or a build block the seed does not allowlist, some of them also a connection it does not create; four name a connection that does not exist, one of them (`warehouse-nobody-created`) built by the seed on purpose; one names a schema no instance here holds; and two require a pipeline or a target applied after them |
| Schedules | 17, all paused | `--paused` is what stops seventeen clocks starting to fire at somebody who has not looked at them |
| Runs | 3 succeeded, 1 with errors, 2 failed | `hello-world`, `transform/jq-reshape.yaml` and `triggers/cron-windowed.yaml` settle green; `optional-step.yaml` settles `completed_with_errors`, which is a third status rather than a shade of failed; `error-handler.yaml` fails by design, and `s3-round-trip.yaml` cannot reach an object store nobody started |
| Connections | 10 healthy, 4 red | The ten that answer are `playground` and the instance's own playground routes the documents carry for their own standalone runs; `artifacts` points at `127.0.0.1:9000`, `work-db` at a database nobody started, and `orders-topic` and `shop-queue` at the two brokers in `infra/compose.queues.yaml`, where nothing is listening unless you started what their headers document |

The refusals are reported by code with the reason the instance gave, and the seeding carries
on past each one -- a refusal is a thing to look at, not an error to fix.

State lands in `.dirigent/state` under the working directory: the SQLite database and the
artifacts. `dg dev` empties that directory on every start, so each seeding builds a fresh
instance and the key its connections are sealed with is minted per run and thrown away with
them. `SEED_ROOT=/somewhere/else` puts it elsewhere, and `SEED_PORT` moves the instance off
3333.

Re-running is safe, and it starts over: the instance is emptied first, so every apply is a
`created` against a database with nothing in it, nothing accumulates between seedings, and a
schedule you resumed by hand is gone with the rest. That is the trade the target makes for
never answering out of an older schema.

The target is for looking at things by hand. Nothing in `make check` or CI runs it.
