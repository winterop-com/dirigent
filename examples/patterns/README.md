# Engine patterns

One engine behaviour per file, named for what it shows. Where the other shelves are organised
by what a pipeline is *for* -- moving data, reshaping it, waiting for it -- this one is
organised by what the engine *does*: the edge conditions, the retry policy, the two clocks, the
item policies, the trigger declarations, the concurrency policies, and the reference language.

Every document here runs for real. The HTTP ones call [Postman Echo](https://postman-echo.com),
a public request-and-response service, so nothing has to be stood up first; the rest are
offline. None of them needs `--enable-unsafe`: no file on this shelf runs code on the worker.

Each header says what the pipeline demonstrates end to end, what each hop hands on, what to
change, and **what outcome to expect** -- because several of these fail on purpose, and a file
whose lesson is a failure has to say so before you run it.

## Trigger rules

The edge condition on `depends_on`. Each of these fails a step deliberately, with
`/status/500`, so the rule has something to react to.

| File | What it shows | Ends as |
| --- | --- | --- |
| [rule-all-success.yaml](rule-all-success.yaml) | The default: a failure skips everything below it | `failed` |
| [rule-all-done.yaml](rule-all-done.yaml) | Cleanup that runs whichever way the branch went | `failed` |
| [rule-one-failed.yaml](rule-one-failed.yaml) | The handler branch, and the success branch it excludes | `failed` |
| [rule-always.yaml](rule-always.yaml) | The widest edge, and the ordering it still respects | `failed` |

## Retries

Whether a failed attempt earns another one, and how long it waits first.

| File | What it shows | Ends as |
| --- | --- | --- |
| [retry-exponential-backoff.yaml](retry-exponential-backoff.yaml) | The five fields, and the 1s, 2s, 4s they compute | `failed` |
| [retry-with-jitter.yaml](retry-with-jitter.yaml) | Why four items that failed together must not retry together | `completed_with_errors` |
| [retry-budget-exhausted.yaml](retry-budget-exhausted.yaml) | A budget spent in full on a hopeless failure | `failed` |
| [retry-only-transient.yaml](retry-only-transient.yaml) | The same policy on a 500 and a 404: three attempts and one | `completed_with_errors` |

## Timeouts and deadlines

Three clocks that stop a step, and they are not interchangeable.

| File | What it shows | Ends as |
| --- | --- | --- |
| [timeout-fails-the-step.yaml](timeout-fails-the-step.yaml) | `timeout` bounds one block call, and expires as transient | `failed` |
| [timeout-skips-the-step.yaml](timeout-skips-the-step.yaml) | `on_timeout: skip` turns an expired deadline into a quiet day | `succeeded` |
| [deadline-on-a-sensor.yaml](deadline-on-a-sensor.yaml) | `poll`, `deadline` and the default `on_timeout: fail` | `failed` |
| [poll-cadence.yaml](poll-cadence.yaml) | The same wait polled two ways, with the overshoot measured | `succeeded` |

## Fan-out

One step definition, many run items.

| File | What it shows | Ends as |
| --- | --- | --- |
| [fan-out-literal-list.yaml](fan-out-literal-list.yaml) | `for_each` written out in the document | `succeeded` |
| [fan-out-from-params.yaml](fan-out-from-params.yaml) | Width supplied by the caller, and the schema that guards it | `succeeded` |
| [fan-out-fail-fast.yaml](fan-out-fail-fast.yaml) | The default item policy: one bad element sinks the batch | `failed` |
| [fan-out-continue.yaml](fan-out-continue.yaml) | `items: continue`, and the failed item that is *absent* downstream | `completed_with_errors` |
| [fan-out-then-join.yaml](fan-out-then-join.yaml) | The join, which is just a step with no `for_each` of its own | `succeeded` |
| [fan-out-nested-objects.yaml](fan-out-nested-objects.yaml) | Elements that are objects, and `${item.limits.max_ms}` | `succeeded` |

## Parameters

| File | What it shows | Ends as |
| --- | --- | --- |
| [params-every-type.yaml](params-every-type.yaml) | Every type and keyword, and why `format` needs a gate to assert | `succeeded` |
| [params-validation-refuses.yaml](params-validation-refuses.yaml) | What a bad run request is answered with, before a run exists | `succeeded` |

## Triggers

What starts a run on its own. The declarations travel with the document; the operational state
stays on the instance.

| File | What it shows | Ends as |
| --- | --- | --- |
| [schedule-cron-timezone.yaml](schedule-cron-timezone.yaml) | Five columns, and the named zone that decides what they mean | `succeeded` |
| [schedule-interval.yaml](schedule-interval.yaml) | A cadence rather than a calendar, and the misfire grace | `succeeded` |
| [schedule-at-once.yaml](schedule-at-once.yaml) | One instant, anchored in the zone the schedule declares | `succeeded` |
| [schedule-window-half-open.yaml](schedule-window-half-open.yaml) | `${run.window.*}`, half-open; needs `--window` | `succeeded` |
| [webhook-mapping-nested-payload.yaml](webhook-mapping-nested-payload.yaml) | JSONPaths onto parameters, and the parameter left unreachable | `succeeded` |
| [webhook-signed.yaml](webhook-signed.yaml) | Outbound HMAC with `sign_with`, and where each secret lives | `succeeded` |

## Concurrency

What a second trigger does while a run is still going. Each header spells that out; a single
local run has nothing to collide with, so the policies are exercised against a server.

| File | What a second trigger does | Ends as |
| --- | --- | --- |
| [concurrency-skip.yaml](concurrency-skip.yaml) | No run is created at all | `succeeded` |
| [concurrency-queue.yaml](concurrency-queue.yaml) | The run is created and held, with its parameters frozen | `succeeded` |
| [concurrency-replace.yaml](concurrency-replace.yaml) | The run in flight is cancelled, remotes told | `succeeded` |

## Composition

`pipeline.run`, and the four questions a call answers. All of them need the child, which a
local run is handed with `--also-apply examples/patterns/pipeline-run-child.yaml`.

| File | What it shows | Ends as |
| --- | --- | --- |
| [pipeline-run-child.yaml](pipeline-run-child.yaml) | The called pipeline, which knows nothing about parents | `succeeded` |
| [pipeline-run-wait.yaml](pipeline-run-wait.yaml) | `wait: true`: a parked row, not a held worker | `succeeded` |
| [pipeline-run-fire-and-forget.yaml](pipeline-run-fire-and-forget.yaml) | `wait: false`: a fork, and the run id that is the whole handoff | `succeeded` |
| [pipeline-run-strict.yaml](pipeline-run-strict.yaml) | `strict`, and the third status it is about | `failed` |
| [pipeline-run-with-params.yaml](pipeline-run-with-params.yaml) | A fan-out of children, checked against the child's schema | `succeeded` |

## The rest of the engine

| File | What it shows | Ends as |
| --- | --- | --- |
| [step-names-and-keys.yaml](step-names-and-keys.yaml) | The map key addresses; `name` describes and identifies nothing | `succeeded` |
| [outputs-inline-vs-storage.yaml](outputs-inline-vs-storage.yaml) | The 16KB inline threshold, and `save_to` as the document's own choice | `succeeded` |
| [references-cheat-sheet.yaml](references-cheat-sheet.yaml) | Every `${...}` form, each used once; needs `--window` | `succeeded` |
| [sensor-http-ready.yaml](sensor-http-ready.yaml) | A 503 as "not yet" rather than as an error | `succeeded` |
| [sensor-storage-exists.yaml](sensor-storage-exists.yaml) | A glob, a size floor, and a drop that actually lands | `succeeded` |
| [log-levels.yaml](log-levels.yaml) | `--log-level PATTERN=LEVEL`, a run setting rather than a document one | `succeeded` |
| [priority-layered.yaml](priority-layered.yaml) | `priority` on the document, on a schedule, and on one ad hoc run | `succeeded` |
| [connections-referenced-vs-carried.yaml](connections-referenced-vs-carried.yaml) | Named, carried, and absolute; needs `--connections` | `succeeded` |

## Running them

Most take no flags at all:

```bash
dg run --local examples/patterns/rule-one-failed.yaml
```

Four need something handed to them, because what they demonstrate is exactly the thing a bare
local run does not have:

```bash
dg run --local examples/patterns/references-cheat-sheet.yaml --window 2026-06-01..2026-06-02
dg run --local examples/patterns/schedule-window-half-open.yaml --window 2026-06-01..2026-06-02
dg run --local examples/patterns/connections-referenced-vs-carried.yaml \
  --connections examples/connections.yaml
dg run --local examples/patterns/pipeline-run-wait.yaml \
  --also-apply examples/patterns/pipeline-run-child.yaml
```

Run the two without their flag once, on purpose: a run with no window refuses
`${run.window.start}` by name rather than resolving it to an empty string, which is the whole
argument for the reference language raising instead of defaulting.
