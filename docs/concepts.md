# Concepts

Dirigent has about a dozen nouns, and every one of them is either a thing you write or a row
the engine keeps. That split is the whole model, so it is worth stating before the
definitions: **a pipeline is a definition, and a run is what happened when the engine
executed one.** Definitions are documents you author, version, and put in git. Runs, and
everything under them, are rows the engine writes as it works -- and because they are rows
rather than a process, a run survives every restart, can be resumed from where it broke, and
is queryable long after the machine that executed it is gone.

Everything below hangs on that. The first half of the vocabulary describes what you write.
The second half describes what the engine writes down about it.

```text
   what you author                     what the engine records
   ---------------                     -----------------------

   Pipeline  (versioned)  ---starts--> Run
     |                                   |
     +-- Step ---------------------------+-- RunItem       (one per fan-out element)
     |     |                             |     |
     |     +-- references a Block        |     +-- StepAttempt   (one per try)
     |                                   |            |
     +-- Trigger (schedule / webhook)    |            +-- ArtifactRef  (the output)
     |
     +-- names a Connection by code (a credential the instance holds)
```

## Pipeline

A coded, versioned definition: a parameter schema, a set of steps, the edges between them,
and a concurrency policy. It is data -- one YAML or JSON document, stored whole as one
immutable JSON value per version.

Editing a pipeline never mutates a version; it creates the next one. Runs pin the version
they started from, which is what makes a run's history readable years later: the definition
it executed is still there, exactly as it was. It also means fixing a broken document does
not fix a run that already started -- that run is still pinned to the version that was broken.

A **code** is how documents address things (`dg run regional-load`): a kebab-case key, unique
per instance, and the only identity a document carries. Beside it a pipeline may carry a
**name**, a free-form human title that nothing ever references, and a **description**, the
long-form text under it. An **id** is a UUID the instance mints and uses internally. A code
travels between instances; an id never does.

A `tags:` list is what the pipeline is for, in the words a grown instance filters by rather
than by name alone. Tags live in the document, so they version and apply like everything else
about a pipeline, and a second apply says what they are now rather than what to add.

```yaml
tags: [acme, nightly]
```

A tag is **normalised at apply**: it is lowercased, and what is left must be letters, digits
and hyphens, start with a letter or digit, and be at most 32 characters. `tags: [Acme]` is
stored as `acme`; `tags: [nightly import]` is refused at validation, at `tags[0]`, with the
tag named and the rule stated. Comparison is exact from then on, so nothing downstream has to
reapply the rule. A document wears at most 16 of them, and says each one once.

Tags **narrow**: `GET /pipelines?tag=acme&tag=nightly`, `dg pipeline list --tag acme --tag
nightly` and two chips on the pipelines screen all list the pipelines wearing *both*, because
"the nightly acme imports" is an intersection. The runs listing takes the same filter through
the run's pipeline -- `GET /runs?tag=nightly&status=failed`, `dg runs list --tag nightly
--status failed` -- and asks what that pipeline wears now: a run pins the version it started
from, never its pipeline's tags, so retagging a pipeline moves its whole history with it.

A `requires:` section is the preflight a document declares: the `blocks` it calls, the
`connections`, `pipelines`, `storage` schemes and `schemas` the instance must hold, and
`workers`, the capability tags a worker must carry before it may claim this pipeline's work.

```yaml
requires:
  blocks: [docker.build]
  workers: [docker]        # only a worker started with --tag docker claims a run of this
```

Everything but `workers` refuses the apply when it is missing, because it cannot be made true
by waiting. `workers` is checked against the live registry and reported, never refused:
workers come and go, and a run whose tags nobody carries queues until one that carries them
registers.

Beside `concurrency`, which decides what may be in flight at once, a document declares a
`priority`: `low`, `normal` (the default) or `high`, which is how far ahead of every other
run the claim takes this one's attempts.

```yaml
concurrency: allow
priority: low            # a nightly bulk job, behind whatever a person is waiting on
```

Priority layers the way parameters do. The document declares the default, a schedule or a
webhook may override it for what it triggers, and an ad hoc run may override it again --
`dg run bulk-load --priority high` is the same pipeline during an incident. Whichever wins is
pinned on the run at creation, so editing the document never reorders a run already in
flight. Nothing is preempted: a `high` run's attempts are claimed before any other's the
moment a slot frees, but an attempt already running is never cancelled to make room.

A claim orders by priority first, then by round-robin fairness between the runs in flight,
then by due time. Fairness numbers every attempt within its run by how many that run has
already been served, so a four-hundred-item fan-out interleaves one attempt at a time with a
two-step run rather than holding every slot until it drains.

Detail: [design.md section 12](design.md#12-defining-pipelines-one-model-two-editors) for the
document format, the code and step-name grammars, and what an apply does.

## Step

One node in a pipeline's DAG. A step names a **block**, gives it config, declares which other
steps it `depends_on` and under what `rule`, and carries the engine-level knobs: retry policy,
timeout, sensor `poll` and `deadline`, an optional `for_each`.

Steps live inside the pipeline document -- they are not rows. Only attempts get rows. Step
names are snake_case, because they are read back inside `${steps.<name>.output.*}` where a
hyphen would look like a minus sign. A step may also carry an optional `name:` for a reader,
but the map key stays the only thing `depends_on` and `${steps....}` can name. A step is an
addressable thing like any other, so it wears the same quartet: the map key is its `code`, the
`name` is the optional title nothing references, and a node of a run's graph carries exactly
those two -- `code`, which every edge and every attempt references, and `name` when the
document gave one.

The knobs that belong to the engine are deliberately step-level rather than buried in a
block's config: `retry`, `timeout`, `poll`, `deadline`, `on_timeout`, `for_each`, `items`,
`continue_on_failure`. They mean the same thing for every block, so they are written in the
same place for every block.

## Block

The collective term for the pluggable things a step can be: **operators** and **sensors**.
A block id is a dotted string like `http.request` or `storage.exists`, and it is public API --
stored pipelines reference block ids as strings forever, so ids are never renamed.

Both kinds share one namespace and a document never says which kind a step is, so the id has
to. A sensor is named as a condition -- `storage.exists`, `http.ready`, `time.window` -- and an
operator as an action -- `storage.copy`, `http.request`, `shell.run`. Reading a document is
how anyone finds out what a pipeline does, so a plugin package that names a sensor as an
action costs every reader of every document that uses it.

Blocks arrive from plugin packages through a single `contribute()` hook, and each publishes
its config and output schemas. Those schemas are the catalog, and the catalog is what
validates a document at apply time and what the UI renders as forms.

Detail: [the block reference](blocks.md) is generated from the live catalog, so it lists what
an instance actually has rather than what the docs remember.

## Operator

A block that **does work**: it changes the world. Call an HTTP API, copy an object between
storage backends, run a container, start another pipeline.

An operator either finishes synchronously with an output, or returns a `RemoteHandle` -- a
serializable claim on a job it submitted somewhere else -- and lets the engine take over the
waiting. `docker.run` is the built-in example of the second kind: it creates and starts a
container, hands back the container id, and never waits.

## Sensor

A block that **waits for the world**: it changes nothing. A file appearing under a storage
URI, an endpoint reporting ready, a wall-clock window opening.

The rule that matters is that a sensor never blocks a worker. Each check is one short,
read-only *poke*; if the condition is not met yet the sensor returns `NotYet`, which is not a
failure and costs no retry budget, and the engine writes down when to look again. A sensor
waiting six hours costs a row with a due time, not six hours of a worker.

A poke that has already read some ground keeps a **cursor**: a small JSON value it returns
with its `NotYet`, and the next poke receives. It is stored by the transaction that parks the
attempt, so it advances at-least-once the way an operator's probe metadata does -- a worker
that dies before that commit leaves the older cursor behind, and the next poke reads the same
ground again. The cursor lives only as long as the waiting attempt; a poke that succeeds ends
the step, and anything a downstream step needs belongs in the output.

Sensors carry their own deadline, and what happens when it expires is configuration:
`on_timeout: fail` or `on_timeout: skip`. `skip` is the interesting one, because `skipped` is a
real terminal outcome that downstream edges can see -- "no drop landed today" is not a failure,
it is a day with nothing to do.

Detail: [design.md section 2](design.md#2-the-five-plugin-surfaces) has the precise contract
for both, and why they stay two concepts on one mechanism.

## Run

One execution of one pipeline version, with resolved parameters and an attributed trigger.

A run's status derives mechanically from its leaves: `succeeded`, `failed`, `cancelled`, or
`completed_with_errors` -- that last one meaning something failed and the pipeline said that
was tolerable. Every run points at whatever started it (a user, a token, a schedule, a
webhook, or another run) through a real foreign key, so "who ran this?" is a join rather than
a free-text field.

## Item

Also called a **RunItem**. When a step declares `for_each`, the run gets one item per element
of that list, each with its own status, its own error, and its own retry.

Fan-out cardinality is fixed when the run is created, not while it executes, which is why
`for_each` may read `params.*`, `item`, and `run.*` but not another step's output. The
practical payoff is that the item grid exists from the moment a run is visible: a run over
five hundred inputs reads as a grid of five hundred outcomes rather than one opaque failure.

The step's `items` policy decides what one bad element means. Under the default, `fail_fast`,
any failed item fails the step. Under `continue`, the step succeeds as long as one item did,
the failures are recorded against their own items, and the run reports
`completed_with_errors`.

## Control flow

There are no conditionals in a dirigent document, and reading one is therefore reading what
it does. Everything a pipeline can express about *shape* is in these five places, and the
gaps below are as load-bearing as the features.

**What is expressible**

- **Branching on an outcome.** Each edge in `depends_on` carries a `rule`: `all_success` (the
  default), `one_failed`, `all_done`, `always`. `one_failed` makes a step an error-handler
  branch; `all_done` makes it cleanup. The failure path is drawn in the graph rather than
  hidden inside a block. See `examples/failure/error-handler.yaml`.
- **Tolerating a failure.** `continue_on_failure: true` on a step means the step failing does
  not fail the run: downstream `all_success` edges are skipped and the run ends
  `completed_with_errors`. See `examples/failure/retries.yaml`.
- **Fan-out with per-item isolation.** `for_each` maps a step over a list, one item per
  element, each with its own status, error, and retry budget; `items: continue` lets one bad
  element through. See `examples/graph/fan-out.yaml`.
- **Fan-in as a list.** A fan-out step's output is the list of its items' outputs, in item
  order, and the step after it runs once and reads the whole batch. Only items that succeeded
  are in that list. See `examples/graph/fan-in.yaml`.
- **Parallelism.** Every step whose prerequisites are met is claimable, so the graph's width
  is the parallelism. What bounds it is worker concurrency, not anything in the document. See
  `examples/graph/parallel-branches.yaml`.
- **Gating on the world.** A sensor holds a branch until a condition is met, with `poll`,
  `deadline`, and `on_timeout: skip` deciding what happens when it never is -- which is how a
  branch is made optional without a conditional. See `examples/sensors/sensor-gate.yaml`.
- **Gating on a shape.** `validate.schema` checks a value against a JSON Schema and passes it
  through when it fits, so a payload from a service you do not control is refused where it
  enters -- naming the path that is wrong -- rather than surfacing as a confusing error in a
  step three edges downstream. A mismatch is `rejected`: the same value fails the same way,
  so it is never retried. See `examples/validate/expects-a-shape.yaml`.

**What is not**

- **No branching on a value.** There are no expressions and no conditionals: `${...}` reads a
  value, it never tests one. A step runs, or it does not, on the *outcome* of its
  prerequisites. Branching on what an upstream step returned means a block that decides, and
  fails or succeeds accordingly. `$${...}` is the escape in any string the resolver reads: it
  yields the literal `${...}` and is never resolved, which is how a compose file, a shell
  command or a template reaches a tool with its own braces intact. The dollars collapse in
  pairs, so `$$${x}` is one literal dollar followed by the resolved `${x}`.
- **No expression in a transform's place.** Reshaping between two steps is a step of its own:
  `transform.jq`, `map.jq`, `filter.jq` and `convert.std` run a program over a value, and they
  need no allowlist because jq opens nothing. What they are not is a way to make the engine
  decide: their output is data a later step reads, never a branch.
- **No reusable step groups.** A document holds one flat `steps` map; there is no macro, no
  include, and no sub-DAG. Composing means `pipeline.run`, which starts a whole other
  pipeline as a step. See `examples/composition/composition-parent.yaml`.

An expression layer is on the roadmap rather than ruled out; the trigger for adding one is a
real pipeline that cannot be written without it.

## Attempt

Also called a **StepAttempt**. One try of one step (or of one item of a fan-out step): its own
row, its own number, its own resolved input, its own logs, its own outcome.

A retry is always a new attempt row, never a re-entry into an old one, which is what makes a
retry auditable rather than a counter. Attempts are `automatic` when the retry policy created
them and `manual` when a person asked, and a manual attempt is never retried automatically --
someone asked for exactly one more try.

Whether an automatic retry happens is decided by the **error class** the block assigned to the
failure: `transient` and `unknown` are retried while budget remains, and `rejected` never is
however much budget is left. That is why a step with
`max_attempts: 3` can still fail on its first attempt: a 4xx, or a config that cannot be
resolved, is `rejected`.

## Connection

A coded credential and settings record of a contributed kind the *instance* holds -- an HTTP
base URL with its auth, an S3 endpoint with its keys. Blocks, storage backends, and notifiers
all reference one by code, and a connection may carry a human `name` and a `description`
beside it.

This is the reason documents are portable. A document says `connection: modelling-api`; it
never says what the password is. The same document applies to staging and to production, and
each instance resolves the code against its own credential. Fields a connection kind declares
as secret are encrypted at rest and redacted in every API response.

An alert channel is one of these too: a `slack` or an `email` connection is what an alert rule
delivers through, minted and sealed exactly like the credential a block uses.

Detail: [operations.md](operations.md#secrets) for the key that encrypts them,
[operations.md](operations.md#notifier-channels) for the channels, and
[security.md](security.md#secrets-lifecycle) for the lifecycle.

### A document that carries its own

A document meant to run on its own -- a published example, a bug reproduction -- has no
instance to resolve a name against. It may carry the connection instead, beside its steps:

```yaml
connections:
  demo:
    kind: http
    config:
      base_url: https://demo.example.org/api
      basic_username: demo
      basic_password: demo
```

`dg run --local` seeds these into its throwaway instance, so the document runs with nothing to
set up first. `--connections FILE` replaces one by code, which is how the same document is
pointed at your own instance without editing it.

A document carries its JSON Schemas the same way, in a top-level `schemas:` section keyed by
code, and a `validate.schema` gate names one of them by `schema`. `dg run --local` seeds these
too, and `--schema FILE` replaces one by code; a carried schema needs no `requires.schemas`
entry, because it satisfies its own reference.

**A server refuses to apply a document that carries a connection or a schema.** An applied
document is stored, versioned, exported and diffed, and a credential -- or a shape every version
would then repeat -- would be in all four. Carry a connection only where the credential is
already public and the document has to stand alone; anywhere else the instance holds it and
`dg connection create` makes it. A shared instance likewise holds its schemas, applied once with
`dg schema create` and named in `requires.schemas`.

## Trigger

What starts a run. Three kinds:

- **Ad hoc** -- `dg run`, the API, or the UI. Always available, always parameterized.
- **A schedule** -- cron, a fixed interval, or a single instant, each with its own timezone and
  its own parameter overrides. Several per pipeline is the normal case: nightly against
  staging and weekly against production is two schedules on one pipeline, not two pipelines.
- **A webhook** -- `POST /hooks/{token}`, with a token that is the whole credential, optional
  HMAC over the raw body, a rate limit, and a small declarative mapping from the JSON payload
  to run parameters.

Each carries a `code` unique within its pipeline, plus the same optional `name` and
`description` a pipeline has. A schedule and a webhook may each pin a `priority` on the runs
they start, overriding the pipeline's.

A webhook's `params_from_payload` is checked where it is declared, not where it fires: every
path parses as `$` followed by dotted, non-empty segments, every mapped name is a parameter
the pipeline declares, and every required parameter without a default is mapped. All the
problems are reported at once. The mapped *values* are not checked here -- they exist only
once a delivery arrives, and are validated then.

Schedules and webhooks can be declared in the document's `triggers:` section, in which case an
apply materialises them and marks them *managed*. One created by hand with `dg schedule
create` is not managed, and an apply that does not mention it leaves it alone.

A `kind: triggers` document is the third owner. It names one pipeline and declares clocks and
webhooks for it, which is how an operations team keeps a clock file over a pipeline another
team defines:

```yaml
format: dirigent/v1
kind: triggers
code: document-nightly            # this document's own key, unique among triggers documents
name: Nightly batch clocks        # optional
pipeline: managed-and-manual      # the pipeline these fire, defined in its own file
triggers:
  schedules:
    - code: ops-nightly
      cron: "0 4 * * *"
      timezone: Europe/Oslo
      params: {day: "2026-01-01", environment: production}
  webhooks:
    - code: ops-manual-kick
      params_from_payload:
        day: "$.run.date"
        environment: "$.run.environment"
```

It has no steps and writes no pipeline versions. It is applied through the same `dg apply`
and reconciles the same way, but only over the rows it declared: its own apply never touches
the pipeline's inline triggers, the pipeline's apply never touches its, and neither touches a
hand-made one. An empty `triggers:` retires everything it owned. A code already taken on that
pipeline under a different owner is refused at apply, naming the owner, and a `pipeline:` no
instance holds -- or one that is deactivated -- is refused at `pipeline`. A directory apply
orders pipeline documents before triggers documents, so a directory carrying both converges
in one pass.

The instance's triggers documents are read at `GET /api/v1/trigger-documents` and
`GET /api/v1/trigger-documents/{code}`, which names the schedules and webhooks the document
owns, and with `dg trigger-document list` and `dg trigger-document show CODE`. Deleting one --
`DELETE /api/v1/trigger-documents/{code}` or `dg trigger-document delete CODE` -- takes its
rows with it and leaves the pipeline, its inline triggers, and every hand-made row alone.
Deleting the pipeline takes its triggers documents, which are meaningless without it.

Detail: [design.md section 8](design.md#8-triggers) for the misfire policy, the webhook
security model, and exactly what an apply does and does not touch.

## Artifact

Also called an **ArtifactRef**: the durable record of a step's output. It carries the content
type, the byte size, and a digest, plus either the value inlined into the row or a URI into
pluggable storage.

The rule underneath it is that nothing ever passes a worker-local filesystem path between
steps. A step's output has to be readable by whichever worker claims the next step, possibly
on another machine, possibly days later on a manual retry -- so it is a URI or it is a value,
never a path.

Each run also gets a scratch prefix (`<artifact-root>/runs/<run-id>/...`) for intermediate
files. A pruned run takes its scratch with it; see [retention](operations.md#retention).

Detail: [design.md section 10](design.md#10-storage).

## Two more worth knowing

**Trigger rule.** The condition on an edge, deliberately using Airflow's names and meanings:
`all_success` (the default), `all_done`, `one_failed`, `always`. This is how error handling is
expressed -- an error branch is an ordinary step behind a `one_failed` edge, drawn in the DAG
rather than coded inside a block. A prerequisite that failed makes an `all_success` edge
unsatisfiable forever, so its dependent is skipped rather than left pending.

**Concurrency policy.** Per pipeline: `allow`, `skip`, `queue`, or `replace`. It decides what
happens when a run is asked for while one is already in flight.

The full glossary, including the engine-internal terms (`waiting`, lease,
lost-job policy) and a column mapping every name onto its Airflow and Prefect equivalent, is
[design.md section 17](design.md#17-vocabulary).
