# Tutorial

This builds one realistic pipeline from nothing, breaks it, diagnoses it from what the
terminal actually prints, fixes it, and then puts it on a schedule with an alert rule behind
it. Every command and every fragment here was run against a real instance; the failure in the
middle is a real mistake, not a planted typo, and the shape of it is worth more than the fix.

Budget about twenty minutes. You need Python and `uv`, and outbound HTTPS -- the pipeline calls
[Postman Echo](https://postman-echo.com), a public request-and-response service, so you do not
have to stand anything up to make the HTTP steps real. Nothing here needs Docker, PostgreSQL,
or the unsafe-block allowlist.

## What we are building

A pipeline called `regional-load`, which is the shape a great many real ones have:

```text
  wait_for_window   a sensor: only load inside the maintenance window
        |
  fetch_manifest    one HTTP call: what are we loading today?
        |
      push          fan-out: one HTTP call per region, tolerating a bad region
        |
  notify_failure    an error branch, drawn in the DAG, on a one_failed edge
```

A gate, a lookup, a fan-out, and an error branch. Four steps, no Python.

## 1. Start an instance

```bash
uv tool install dirigent-cli
dg dev
```

`dg dev` is the standalone mode: SQLite in a file, and the API, the scheduler, and a worker in
one process. At a terminal it renders its lines; in a pipe it writes NDJSON. It
migrates the database, mints a development admin, and emits a token exactly once. Its state
is `.dirigent/state`, kept between starts -- pass `--wipe-state` to begin from nothing:

```text
2026-01-01T18:22:23.069+01:00 [info    ] starting   [process] process=dev api=http://127.0.0.1:3333 docs=http://127.0.0.1:3333/docs admin=dev state=/home/you/dirigent-tutorial/.dirigent/state token=C_8u-blmgbzhoV2nbonBBxnxjZUqRflUIb0Oy81BE-g migrated=0001_baseline
2026-01-01T18:22:23.382+01:00 [info    ] ready      [process] process=dev
```

Leave it running. In a second terminal, take the `api` and `token` off that starting record --
that is how the CLI knows which instance to talk to and how to authenticate to it:

```bash
export DG_URL=http://127.0.0.1:3333
export DG_TOKEN=C_8u-blmgbzhoV2nbonBBxnxjZUqRflUIb0Oy81BE-g
```

## 2. Scaffold a project

```bash
dg init regional
cd regional
```

```text
Created a local project in regional:
  + regional/dirigent.yaml
  + regional/pipelines/hello-world.yaml
  + regional/.dirigent/profiles.yaml
  + regional/.dirigent/.gitignore
  + regional/dirigent.example.yaml
  + regional/pyproject.toml
  + regional/README.md
  + regional/.gitignore

That is a working set of documents, and no instance: nothing is running yet.
  An instance here:  dg dev  (its database and artifacts live in .dirigent/state)
  One that exists:   export DG_URL=... DG_TOKEN=...

Then dg apply --dry-run, and dg apply.
```

`dirigent.yaml` says where the documents live and which profile to use;
`.dirigent/profiles.yaml` says which server that profile means and how to get a token for it
(never a database URL -- a CLI that could reach the database would bypass authentication,
attribution, and validation entirely); `pipelines/hello-world.yaml` is a working example; and
`.dirigent/.gitignore` keeps a local instance's state out of the repository while leaving the
profiles committable. `dirigent.example.yaml` is every setting dirigent has, commented out,
with its default and what it does: it is read, never loaded, and generated from the settings
model so it matches the version installed. `pyproject.toml` pins the dirigent this project
runs on, so `uv sync` here builds its environment and `uv run dg` is that runtime; the
commands below use the `dg` installed in step 1, against the instance it started.

A project is a working set of documents, not the source of truth. The server is where
definitions actually live; `dg apply` puts them there.

Delete the example, since we are writing our own:

```bash
rm pipelines/hello-world.yaml
```

## 3. Write the document

Put this in `pipelines/regional-load.yaml`. It has a mistake in it. Type it as it is; finding
the mistake is the point of the next few sections.

```yaml
format: dirigent/v1
kind: pipeline
code: regional-load
name: Regional load
description: Fetch today's manifest, push it to every region, and shout if a push fails.

params:
  type: object
  required: [day]
  properties:
    day:
      type: string
      format: date
    regions:
      type: array
      default: ["east", "west", "north"]
      items:
        type: string

steps:
  wait_for_window:
    block: time.window
    poll: 5s
    deadline: 30m
    on_timeout: skip
    config:
      after: "00:00:00"
      before: "23:59:59"
      timezone: Europe/Oslo

  fetch_manifest:
    block: http.request
    depends_on: [wait_for_window]
    config:
      url: https://postman-echo.com/get
      method: GET
      query:
        day: "${params.day}"

  push:
    block: http.request
    depends_on: [fetch_manifest]
    for_each: "${params.regions}"
    items: continue
    retry:
      max_attempts: 3
      backoff: 2s
    config:
      url: https://postman-echo.com/post
      method: POST
      body:
        day: "${params.day}"
        region: "${item}"
        manifest: "${steps.fetch_manifest.output.json_body.args.day}"

  notify_failure:
    block: http.request
    depends_on: [push]
    rule: one_failed
    config:
      url: https://postman-echo.com/post
      method: POST
      body:
        text: "the regional load failed for ${params.day}"
```

Worth reading before you run it:

- **`code` is what everything else addresses**, and `name` and `description` are for a
  reader. The code is what appears in `dg run regional-load`, in the REST path, and in another
  document's `requires`; the name is a free-form title that nothing may reference, and the
  description is long-form markdown, rendered as such in the web UI. Leave both out and the
  code carries the whole burden of saying what this is, which is how a slug ends up as a
  sentence.

- **`params` is JSON Schema.** It drives the CLI's parameter builder, the run form the UI
  renders, and the validation a webhook's mapped payload has to satisfy. `day` is required;
  `regions` has a default.

  Note the quotes around the region names. Unquoted, YAML would read `no` as the boolean
  `false`, and `items: {type: string}` would then refuse the default -- a footgun worth
  meeting once, deliberately, rather than at five in the morning.

- **`wait_for_window` is a sensor**, so `poll`, `deadline`, and `on_timeout` apply. These are
  step-level, not part of the block's config, because they are engine semantics and mean the
  same thing for every block. A sensor never holds a worker while it waits: each poke is one
  short check and a due time written to a row.

  `on_timeout: skip` is the load-bearing choice. Outside the window is not a failure, it is a
  time with nothing to do, so the sensor skips -- and because `skipped` is a real terminal
  outcome, the default `all_success` edges skip the branch behind it too.

- **`for_each` on `push` is the fan-out.** One run item per region, each with its own status
  and its own retry. It is expanded when the run is created, which is why it may read
  `params.*`, `item`, and `run.*` but not another step's output: the cardinality has to be
  known before anything executes.

  `items: continue` says a region that refuses does not stop the others. Under the default,
  `fail_fast`, any failed item fails the step.

- **`notify_failure` is the error branch**, and it is an ordinary step behind a `one_failed`
  edge. There is no try/except in this document and none in the engine either. The four edge
  rules -- `all_success` (the default), `all_done`, `one_failed`, `always` -- are the whole
  vocabulary, and a reader can see the failure path by looking at the graph.

- **`${...}` is the whole reference language.** `params.*`, `steps.<name>.output.*`, `item`,
  `run.*`, `trigger.*`. No expressions, no loops, no conditionals -- logic lives in blocks and
  in edge rules, which is what keeps a document reviewable. There is nothing to trim or format
  with either, so a captured stream arrives exactly as the command wrote it: `${steps.x.output.stdout}`
  from an `echo` carries its trailing newline. Where that matters, print without one --
  `printf '%s'` -- rather than trimming at the reference.

- **`$${...}` is the escape**, and it is how a value reaches a tool with its own braces
  intact: a compose file interpolating `$${GREETING}`, a shell command holding `$${HOME}`, a
  template another program renders. It yields the literal `${...}` and is never resolved, so
  the name inside it is never checked against anything. `$$` that no brace follows is left
  alone, which is why a shell command's `$$` still reaches the shell as `$$`; the one case
  worth knowing is `$$${x}`, where the dollars collapse in pairs, so it is a literal `$`
  followed by the resolved `${x}`. Parameter values passed with `-p` or in a run request are
  not resolved at all and carry their braces through as typed, so never write `$${` in one.

## 4. Validate, offline

```bash
dg validate
```

```text
valid    regional-load  (document, offline)
```

`dg validate` needs no server. It checks the envelope, the key grammars, the graph -- that it
is acyclic, that every `depends_on` names a step that exists -- and the syntax of every
reference. That is everything checkable without knowing what blocks the target instance has.

Remember that it said `offline`. It will matter shortly.

## 5. Plan, then apply

```bash
dg apply --dry-run
```

```text
create regional-load  version 1 (/home/you/regional/pipelines/regional-load.yaml)
Nothing was written: this was a dry run.
```

A dry run returns the plan: `create` because no pipeline holds that code yet. On a document
the instance already has, this reads `update` with a summary of what moved, or `unchanged` --
because matching digests mean there is nothing to write. That is what lets a CI job apply the
whole repository on every merge without accumulating a version per commit.

```bash
dg apply
```

```text
create regional-load  version 1 (/home/you/regional/pipelines/regional-load.yaml)
```

The instance now holds `regional-load` at version 1. The apply also ran the checks
`dg validate` could not: that every block id exists in this instance's catalog, that each
step's config validates against that block's published schema, and that every connection a
step names by code is present.

## 6. Run it, and watch it fail

```bash
dg run regional-load -p day=2026-01-15 --watch
```

`--watch` streams step transitions and block output merged by timestamp, so the stream reads as
cause and then effect:

```text
started run 01a04d50-9c18-70f2-a9f8-b0914f5b07fe of regional-load
  queued          wait_for_window (time.window)
                  wait_for_window | the window is open
  succeeded       wait_for_window (time.window)
                  fetch_manifest | http call
  succeeded       fetch_manifest (http.request)
  failed          push (http.request)
                  notify_failure | http call
  succeeded       notify_failure (http.request)
```

Then the summary:

```text
run 01a04d50-9c18-70f2-a9f8-b0914f5b07fe
pipeline      regional-load (version 1)
status        failed
triggered by  dev (token dev)
duration      1.3s
items         0/3
```

The sensor opened, the manifest was fetched, and then `push` failed for all three regions --
`items 0/3`. The `one_failed` edge did its job: `notify_failure` ran, which is the error branch
behaving exactly as drawn.

## 7. Read the diagnosis

When a step fails, `--watch` prints the diagnosis before exiting: the failing step, its block,
the error class the block assigned, the message, and that attempt's log lines. Once per failed
item, so a fan-out tells you whether one region is broken or all of them are:

```text
push failed  http.request, attempt 1, rejected
  ${steps.fetch_manifest.output.json_body.args.day} cannot be resolved: steps.fetch_manifest.output has no 'json_body'
(body, body_bytes, duration_ms, headers, status)
```

There are three things in that line, and each is worth stopping on.

**The mistake.** `http.request` does not produce a field called `json_body`. It produces
`body`, and the error names every field it does produce. Guessing an output field name is
one of the most ordinary mistakes there is, and the reason it survived this far is worth
stating: an output model is a contract, and the contract belongs to the block. `dg blocks show
http.request` is where it is written down:

```text
output
  * status                 integer
  * headers                object
    body                   any (default None)
  * body_bytes             integer
  * duration_ms            integer
```

The same thing, for every installed block, is [the block reference](blocks.md) -- generated
from the live catalog, so it cannot go stale.

**Why validation did not catch it.** `dg validate` said `offline` and it meant it. It checked
that `steps.fetch_manifest` names a real step, because that is in the document. It cannot check
`.output.json_body`, because whether an output has such a field is a fact about the block's
schema, and offline validation has no catalog. Even the server-side apply does not check it: at
apply time nothing has produced an output yet, so the check the engine can honestly make is the
one it makes -- at claim time, when the reference is actually resolved.

**Why it says `attempt 1` when the step allows three.** Because the error class is `rejected`,
not `transient`. Retry is per-step policy over the block's own error classification, and the
three classes mean three different things: `transient` and `unknown` are retried while budget
remains, and `rejected` never is however much budget is left. A
reference that cannot be resolved is not going to resolve better in two seconds, so the budget
is not spent on it. That is the retry policy working, not being ignored.

## 8. Try a retry, and learn what a run is

The instinct is to fix the document and retry the run. Do the retry first, without fixing
anything, because what happens next explains the data model better than any paragraph can.

```bash
dg runs retry 01a04d50-9c18-70f2-a9f8-b0914f5b07fe --step push --failed-items
```

```text
queued attempt 2 of push
queued attempt 2 of push
queued attempt 2 of push
```

Three items, three manual attempts. `--failed-items` retries every failed item of a fan-out;
without it you get one attempt of the last failure, which is what you want when a single region
was the problem.

A few seconds later:

```bash
dg runs show 01a04d50-9c18-70f2-a9f8-b0914f5b07fe
```

```text
run 01a04d50-9c18-70f2-a9f8-b0914f5b07fe
pipeline      regional-load (version 1)
status        failed

steps
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ step            ┃ block        ┃ outcome   ┃ after           ┃ attempts ┃ items ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ wait_for_window │ time.window  │ succeeded │ -               │ 1        │ -     │
│ fetch_manifest  │ http.request │ succeeded │ wait_for_window │ 1        │ -     │
│ push            │ http.request │ failed    │ fetch_manifest  │ 6        │ 0/3   │
│ notify_failure  │ http.request │ succeeded │ push            │ 1        │ -     │
└─────────────────┴──────────────┴───────────┴─────────────────┴──────────┴───────┘
```

Six attempts now, and the same failure. **A run pins the pipeline version it started from, and
that never changes.** This run is version 1 forever, so retrying a step of it re-executes
version 1's definition of that step -- the broken one. Fixing the document creates version 2 and
does nothing at all to this run.

That is the right behaviour, even though it is not what the instinct wanted. A run is a record
of what happened, and silently swapping the definition underneath it would make its history a
lie. It also means retry is the tool for a *transient* failure -- the endpoint was down, the
credential had expired, the disk was full -- and not for a bug in the document. For a bug, you
fix the document and start a new run.

Notice what retry does not do: `wait_for_window` and `fetch_manifest` were not re-executed.
Resuming a failed run starts from the failed step, reading the upstream steps' stored outputs,
because those outputs are durable artifacts rather than something held in a process.

## 9. Fix it, and re-apply

A prefix too many. In `push`:

```yaml
        manifest: "${steps.fetch_manifest.output.body.args.day}"
```

```bash
dg apply
```

```text
update regional-load  version 2 (/home/you/regional/pipelines/regional-load.yaml)
  steps changed: push
```

`update`, version 2, and the plan says which step moved. Versions are immutable and monotonic:
version 1 is still there, still readable, still pinned by the run that used it.

## 10. Run it again

```bash
dg run regional-load -p day=2026-01-15 --watch
```

```text
started run 01a04d50-f29a-7160-93cc-8df15a364242 of regional-load
  queued          wait_for_window (time.window)
                  wait_for_window | the window is open
  succeeded       wait_for_window (time.window)
  running         fetch_manifest (http.request)
                  fetch_manifest | http call
  succeeded       fetch_manifest (http.request)
                  push | http call
  succeeded       push (http.request)
                  push | http call
                  push | http call
  skipped         notify_failure (http.request)
run 01a04d50-f29a-7160-93cc-8df15a364242
pipeline      regional-load (version 2)
status        succeeded
triggered by  dev (token dev)
duration      1.3s
items         3/3

steps
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ step            ┃ block        ┃ outcome   ┃ attempts ┃ duration ┃ error ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ wait_for_window │ time.window  │ succeeded │ 1        │ 0.0s     │ -     │
│ fetch_manifest  │ http.request │ succeeded │ 1        │ 0.3s     │ -     │
│ push            │ http.request │ succeeded │ 3        │ 0.3s     │ -     │
│ notify_failure  │ http.request │ skipped   │ 1        │ -        │ -     │
└─────────────────┴──────────────┴───────────┴──────────┴──────────┴───────┘
```

`items 3/3`, and version 2. Two details in there:

- `push` shows **3 attempts** and succeeded. That is one attempt per run item, not three tries
  of one thing. The three `push | http call` lines are interleaved because the three items ran
  concurrently -- the fan-out is parallel, and the transitions arrive in whatever order they
  finish.
- `notify_failure` is **skipped**, not omitted. Its `one_failed` edge became permanently
  unsatisfiable the moment `push` succeeded, so the engine settled it as skipped rather than
  leaving it pending forever. Every step in the graph reaches a terminal state on every run,
  which is what makes a run's outcome derivable from its leaves.

The exit code is the run's outcome, so this is usable in CI directly: `0` for succeeded, `1`
for failed and cancelled, and `0` with a warning for `completed_with_errors` unless you pass
`--strict`. `--strict` requires `--watch` or `--local`, because those are the two shapes that
wait for an outcome to judge.

`1` is only ever "it ran and the answer was no". A `3` means the invocation never got as far
as running -- the environment was refused, a safety gate said no, or a local run could not be
set up -- which is the distinction a CI job needs in order to decide whether to page anyone.
The four codes are in [the command line](cli.md#watching-a-run).

## 11. Put it on a schedule

```bash
dg schedule create regional-load nightly --cron "0 5 * * *" --tz Europe/Oslo
```

```text
created schedule nightly on regional-load: 0 5 * * * Europe/Oslo
  next firing 2026-08-30 05:00:00
```

```bash
dg schedule list regional-load
```

```text
schedules of regional-load
┏━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ code    ┃ name ┃ clock     ┃ timezone    ┃ paused ┃ next firing         ┃ last fired ┃
┡━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ nightly │ -    │ 0 5 * * * │ Europe/Oslo │ no     │ 2026-08-30 05:00:00 │ -          │
└─────────┴──────┴───────────┴─────────────┴────────┴─────────────────────┴────────────┘
```

Note that this schedule has no `-p day=...`, and it was accepted anyway. It will not work:
`day` is required, so every firing will be refused when it tries to create a run, and land in
the firing history as a failed firing -- readable with `dg schedule firings regional-load
nightly`. For a real nightly run this schedule needs its own parameter override, added with
`-p day=...`. What `dg schedule create` *does* check is the shape of the overrides you do give
it, against the pipeline's own parameter schema, using the same builder `dg run` uses -- so a
typo is refused when the schedule is created rather than discovered at five in the morning.

A schedule carries its own timezone, and several per pipeline is the design rather than a
workaround: nightly against staging and weekly against production is two schedules on one
pipeline.

**The misfire policy** is worth knowing before you rely on this. If the scheduler is down when
a firing is due, what happens depends on how late it is. Less than the grace window (five
minutes by default) and the firing is ordinary, with the clock advancing from the slot it owed
so a cron schedule keeps its own grid. More than the grace and it is a *misfire*: it fires
exactly once and the next firing is computed from now, abandoning every slot that was missed.
A scheduler down over a weekend wakes up, runs the nightly job once, and returns to its grid --
instead of firing it sixty times, which is the catchup storm every operator has been burned by.

**A schedule you created this way is not managed by the document.** An apply that does not
mention it leaves it alone, because deleting someone's schedule as a side effect of an
unrelated edit is the kind of surprise that makes people stop using the document format. To put
it under the document's control instead, declare it in a `triggers:` section and re-apply.

## 12. Add an alert rule

A failed nightly run that nobody hears about is a failed nightly run you find out about from
downstream.

```bash
dg alerts rules create load-failed \
  --event run_failed --notifier log --pipeline regional-load --throttle 15m
```

```text
created alert rule load-failed: run_failed on regional-load
```

```bash
dg alerts rules list
```

```text
alert rules
┏━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┓
┃ code        ┃ name ┃ event      ┃ scope         ┃ notifier ┃ throttle ┃ active ┃ last sent ┃
┡━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━┩
│ load-failed │ -    │ run_failed │ regional-load │ log      │ 15m      │ yes    │ -         │
└─────────────┴──────┴────────────┴───────────────┴──────────┴──────────┴────────┴───────────┘
```

The four events are `run_failed`, `run_completed_with_errors`, `run_succeeded`, and
`run_stuck`. The scope is a pipeline here; leave `--pipeline` off for a global rule.

`log` is the notifier that needs no credential, which is what makes alerting work on a fresh
install. The other three built-ins deliver through a connection a `--connection` names by code:
`webhook`, an outbound JSON POST that reaches anything accepting one; `slack`, through an
incoming webhook or `chat.postMessage`; and `email`, one plain-text message per alert. Try one
end to end with `dg alerts test log`, which sends one message through the real queue, and watch
it with `dg alerts queue`.

Two things the engine guarantees here, both worth trusting. Raising an alert and settling the
run are **one commit**, so a run cannot reach a terminal state without whatever it owes having
been written down -- there is no window in which a run has failed and the alert has not yet
been decided on. And sending is a queue rather than a call, claimed and retried by a worker the
same way a step attempt is, so a notifier that hangs costs a lease and a retry instead of
blocking the transaction that settled the run.

## What you have

- A four-step pipeline with a sensor gate, a fan-out, and an error branch, in one reviewable
  file you can put in git.
- Two immutable versions of it, and two runs -- one pinned to the broken version and one to the
  fixed one, both still fully readable.
- A schedule and an alert rule.
- No Python, no deployment, and no framework in your codebase.

Tear it down by stopping `dg dev`. The next `dg dev` picks the instance up where it was;
`dg dev --wipe-state` empties `.dirigent/state` and starts from nothing.

## Where to go next

- **[Concepts](concepts.md)** puts names on everything you just used, and explains how they
  relate.
- **[The command line](cli.md)** covers profiles, the parameter builder in full, running a
  document with no server at all (`dg run --local`), and the verbosity flags for when
  something is wrong.
- **[The block reference](blocks.md)** is every block your instance has, with the config it
  takes and the output it produces. It is generated from the live catalog.
- **`examples/`** in the repository is one runnable document per concept, walked by a test on
  every CI run so none of them can rot. `graph/fan-out.yaml`, `sensors/sensor-gate.yaml`,
  `failure/error-handler.yaml`, and `failure/retries.yaml` are the ones closest to what you
  just built.
- **[Operations](operations.md)** is the deployment shapes, every setting, and an honest list of
  what is missing -- read the known debt before you run this in anger.
- **[Security](security.md)** is the threat model, the auth boundary, and the unsafe-block
  allowlist you will meet the moment a pipeline needs `shell.run`.
- **[Design](design.md)** is the specification: why the engine is shaped this way, and what
  every rule is defending against.
