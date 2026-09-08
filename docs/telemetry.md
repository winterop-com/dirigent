# OpenTelemetry

Dirigent is instrumented with the OpenTelemetry API and ships **no SDK behaviour until an
exporter is configured**. This page is what is actually emitted, from which process, under
which environment -- because "instrumented" on its own tells an operator nothing about what
will arrive in their collector.

For the operator question one level up -- what to watch, and with which command -- see
[what to monitor](operations.md#what-to-monitor).

## Off by default, precisely

`opentelemetry-api` is a hard dependency and is always imported. Without an SDK installed on
the providers, `trace.get_tracer` and `metrics.get_meter` return the API's own no-op
implementations: a span is a function call that allocates nothing and goes nowhere, and a
counter's `add` returns immediately. That is what "no-op" means here; there is no flag being
checked and no branch being taken.

**Unconfigured means exactly this:** none of the five environment variables below names a
destination, or `OTEL_SDK_DISABLED=true` is set. In that state `configure_telemetry` returns
without building a provider, and the module-level tracer and meter stay the API's no-ops for
the life of the process.

## What turns it on

The standard `OTEL_*` environment, and no dirigent setting. The SDK is wired up when any one
of these is set to something other than empty, `none`, or `None`:

```text
OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
OTEL_TRACES_EXPORTER
OTEL_METRICS_EXPORTER
```

`OTEL_SDK_DISABLED=true` overrides all five. The empty / `none` values are the specification's
own way of saying "explicitly off", which is why they are treated as absent rather than as a
malformed exporter name.

Making this a deployment decision rather than a setting is the point: there is no code path
and no configuration file entry that turns telemetry on, so it cannot be on in one environment
and off in another by accident of which `dirigent.yaml` was baked into an image.

| Variable | Read by | Effect |
| --- | --- | --- |
| `OTEL_TRACES_EXPORTER` | dirigent | `console` uses the SDK's `ConsoleSpanExporter`; unset or anything else uses the OTLP-over-HTTP span exporter; empty or `none` means no span exporter at all |
| `OTEL_METRICS_EXPORTER` | dirigent | The same three choices, for metrics |
| `OTEL_SERVICE_NAME` | dirigent | The `service.name` resource attribute. Defaults to `dirigent` |
| `OTEL_SDK_DISABLED` | dirigent | `true` means the SDK is never installed |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | the OTLP exporter | Where to send both signals. The exporter appends `/v1/traces` and `/v1/metrics` |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | the OTLP exporter | The traces endpoint, used whole -- no path is appended |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | the OTLP exporter | The metrics endpoint, used whole |
| `OTEL_EXPORTER_OTLP_HEADERS` | the OTLP exporter | Headers on every export, as `key=value,key=value`. This is where a vendor's API key goes |
| `OTEL_EXPORTER_OTLP_TIMEOUT`, `OTEL_EXPORTER_OTLP_COMPRESSION`, `OTEL_EXPORTER_OTLP_CERTIFICATE` | the OTLP exporter | Export timeout, compression, and the CA bundle for a TLS endpoint |
| `OTEL_RESOURCE_ATTRIBUTES` | the SDK's resource detector | Extra resource attributes, merged under the three dirigent sets |
| `OTEL_BSP_*` | the SDK's batch span processor | Batch size, queue size, and export interval |

Only the first four are read by dirigent's own code. The rest are read by the OpenTelemetry
SDK and the OTLP exporter directly, out of the process environment, exactly as they would be
in any other Python service -- dirigent neither forwards them nor overrides them.

`OTEL_EXPORTER_OTLP_PROTOCOL` is the exception worth naming, because setting it does nothing:
dirigent imports the OTLP-over-HTTP exporter class by name, so the protocol is always
`http/protobuf`. There is no gRPC path. Point the endpoint at a collector's 4318, not its 4317.

**The one dirigent setting that feeds telemetry** is `DIRIGENT_ENVIRONMENT`, which becomes the
`deployment.environment` resource attribute. The other resource attributes are
`service.name`, `service.version` -- the installed `dirigent-core` version -- and
`service.instance.id`, which is `<hostname>-<pid>` unless `OTEL_RESOURCE_ATTRIBUTES` already
names one. Two workers on one host are otherwise one series in a metrics backend, and neither
of them is right.

**The exporter package is an optional extra**, except in the image built here.
`opentelemetry-exporter-otlp-proto-http` is not in the base install; it arrives with
`dirigent-core[otlp]`, which `infra/Dockerfile` installs. The exporter class is imported by
name at configuration time rather than with an import statement, which is what keeps it out of
the base install entirely. `console` on either exporter needs no extra and is the fastest way
to prove the wiring before a collector exists.

**Failing to configure telemetry is a warning, never a failed start.** A missing extra, an
unreachable endpoint, a malformed header -- the process logs `telemetry could not be
configured` with the error and carries on serving. Check for that line rather than assuming a
silent collector means a silent instance.

## Which processes actually export

This is the part worth reading before you plan a dashboard.

Each process installs the SDK for itself, from the same environment.

| Process | Installs the SDK | Therefore exports |
| --- | --- | --- |
| `dg server` | yes, in the application factory | HTTP request spans, and the `run` span of every run an API call or a webhook delivery creates -- the embedded scheduler's firings included |
| `dg dev` | yes -- it builds the same application | everything on this page: HTTP spans, `run` spans, step and block spans, every metric |
| `dg worker` | yes, at start-up | step and block spans, every metric |
| `dg scheduler` | yes, at start-up | the `run` span of every run a firing creates; the tick itself opens no span |

Every metric on this page, and both engine spans, are recorded on the worker path, so a
deployment that scales workers out and forgets to give them the exporter environment is a
deployment with no dirigent metrics at all. The `OTEL_*` variables belong on every service,
which is why `infra/compose.yaml` sets them on the shared environment rather than on the server.

## Spans

Four span shapes are opened at run time.

| Span name | Kind | Opened by | Attributes |
| --- | --- | --- | --- |
| `<METHOD> <path>`, renamed to `<METHOD> <route template>` once routed | `SERVER` | the server, one per HTTP request | `http.request.method`, `url.path`, `http.route`, `http.response.status_code` |
| `run <pipeline>` | `PRODUCER` | whoever creates the run: an API request, a schedule firing, a parent step | `dirigent.pipeline`, `dirigent.run.trigger`, `dirigent.run.id` |
| `step <name>` | `CONSUMER` | the worker, one per step attempt, from claim to settled outcome | `dirigent.run.id`, `dirigent.step`, `dirigent.block`, `dirigent.attempt` |
| `<block>.<call>` | `CLIENT` | the worker, one per block call, as a child of the step span | `dirigent.block`, `dirigent.block.call`, which is `execute`, `probe`, `fetch`, or `cancel` |

A failing attempt marks its `step` span with an `ERROR` status carrying the block's own failure
message; an exception is recorded on the span as well. An HTTP response of 500 or worse marks
its request span `ERROR` with the status.

**A run is one trace.** The `run` span is the root every attempt of that run hangs from,
however many workers claim them and however long after. What joins them is not a process:
the run's trace context is written to its row when the run is created, and a worker opens
each attempt span under the context it reads back. So a run triggered by an API call reads as
one trace from the request, through the run, to every step and every block call it made.

**The `run` span covers creating the run, not running it.** A run outlives the process that
started it, so the span ends when the rows are written while its children end minutes or hours
later. A trace viewer draws that as children extending past their parent. How long the run
itself took is not a metric here at all: it is the run's own `duration_ms`, on the run record
and in `dg runs report`.

**Notifier delivery is not a span**, despite reading like one: an alert's path from a settled
run to a delivered message is visible in `dg alerts queue` and in the process log.

**Request paths are redacted before they become span names.** A delivery to
`POST /hooks/<token>` carries its whole credential in the path, and a span name travels to
every trace viewer an organisation has, so the segment becomes `/hooks/{token}` before it is
used as a name or as the `url.path` attribute. Once the request has been routed, the name is
upgraded to the route template, which is both safer still and the cardinality the semantic
conventions ask for.

**FastAPI is instrumented by a middleware dirigent owns**, not by
`opentelemetry-instrumentation-fastapi`. That is a deliberate trade: the official package
brings in an instrumentation chain the server does not otherwise need, and one middleware
wrapping the call in a span is a few lines that stay a no-op when nothing is configured. The
consequence is that you get the request span and its four attributes, and none of the extras
that package adds. **SQLAlchemy is not instrumented at all** -- there are no database spans,
so a slow request shows as a slow request and not as the query inside it. Use
`DIRIGENT_DATABASE_ECHO=true` or the database's own statement logging for that.

## Metrics

Nine instruments, all under the `dirigent` instrumentation scope. Read the previous section
first: every one of them is recorded on the worker path, except `scheduler.lag`, so the
exporter environment has to reach the worker processes and not only the server.

The **aggregate** column is the part a dashboard gets wrong. Every process reports the same
instrument, and what that means differs per instrument, so the column says how to add the
series up rather than leaving it to a guess.

| Instrument | Kind | Unit | Attributes | Aggregate | What it counts |
| --- | --- | --- | --- | --- | --- |
| `dirigent.runs` | counter | 1 | `dirigent.run.status`, `dirigent.pipeline` | sum | One increment per run reaching a terminal status |
| `dirigent.steps` | counter | 1 | `dirigent.step.status`, `dirigent.block` | sum | One increment per step attempt settling |
| `dirigent.step.duration` | histogram | s | `dirigent.step.status`, `dirigent.block` | sum the buckets | How long a step attempt took |
| `dirigent.block.duration` | histogram | s | `dirigent.block`, `dirigent.block.call` | sum the buckets | How long one block call took, by which of the four calls it was |
| `dirigent.queue.depth` | observable gauge | 1 | none | **max** | Attempts in `queued`, as this process last counted them |
| `dirigent.waiting` | observable gauge | 1 | none | **max** | Attempts in `waiting`: parked, not on a worker, as this process last counted them |
| `dirigent.worker.in_flight` | observable gauge | 1 | `dirigent.worker` | **sum by worker** | Block calls this worker is running right now |
| `dirigent.scheduler.lag` | observable gauge | s | none | **max** | Seconds between the oldest due schedule's due time and the tick that fired it |
| `dirigent.worker.heartbeat_age` | observable gauge | s | `dirigent.worker` | **max by worker** | Seconds since each registered worker last reported in |

**Read the two counters as counters.** In Prometheus, `increase(dirigent_runs_total[$__range])`
takes a series' first sample as its baseline, so every run a worker settled before that worker's
series was first scraped is missing from the answer -- a freshly started fleet undercounts by
most of what it has done. Read the cumulative total, or a `rate`, which is honest about a series
that has only just appeared.

The five gauges are process-local values the engine updates as it works, read by observable
callbacks when the SDK collects. `queue.depth`, `waiting` and `heartbeat_age` are refreshed by
the sweeper, on `DIRIGENT_SWEEP_INTERVAL` (default 30), rather than queried at collection time:
the claim query is the engine's hot path and telemetry has no business adding a count to it. So
they are as fresh as the last sweep, and they are per process -- every worker reports the queue
depth it last saw, which is the whole queue, so **do not sum `queue.depth` across workers**.
`worker.in_flight` is genuinely per worker and does sum. It carries `dirigent.worker`, the
worker's registered name -- the one `dg system workers` lists and `heartbeat_age` is keyed by --
so one worker reads under one name on every panel. A process with no worker in it, a bare
`dg server` or `dg scheduler`, reports the instrument not at all rather than a zero under no
name.

`scheduler.lag` is refreshed by the scheduler's own tick, from the first row `claim_due`
returns, and is zero when nothing was due. A scheduler standing by behind the advisory lock
never ticks, so it reports zero forever: **max**, never an average.

`worker.heartbeat_age` carries one observation per registered row that is not `stopped`, and
every sweeping worker reports the whole registry. So one worker has as many series as there are
sweepers, and the reading you want is the maximum over `dirigent.worker`. Past two minutes the
row is presumed gone (`registry.STALE_AFTER`); past `DIRIGENT_STALE_WORKER` (default 15
minutes) the sweeper deletes it and the series stops rather than climbing.

**Both duration histograms carry their own bucket edges**, in seconds: 5ms, 10ms, 25ms, 50ms,
100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s, 30s, 60s, 5m, 15m. They are advisory, so a view or a
collector may override them, and the SDK's own defaults start at 0, 5, 10 -- which would put
a 40ms step and a four-second one in one bucket and make every quantile a ceiling.

## The trace context on a run

A run row carries a `traceparent` column: the W3C trace context of the run's own `run` span,
written when the run is created, and the only thing that joins a run to the work its workers
do later. A worker reads it back to open each attempt span under it. It is null when there is
no valid span in context, which is what "no exporter configured" looks like.

Where that trace begins follows from where the run was created:

| How the run started | The `run` span's parent | The trace |
| --- | --- | --- |
| `dg run`, or `POST /pipelines/{code}/$run` | the request span | the trace of that HTTP request |
| A webhook delivery to `POST /hooks/{token}` | the request span | the trace of that delivery |
| A schedule firing | nothing -- the scheduler's tick opens no span | a trace of its own, rooted at the `run` span |
| `pipeline.run` starting a child pipeline | the parent step's attempt span | the parent run's trace, so a child run is a subtree of it |

The trace id is read out of the traceparent and surfaced in three places:

- `GET /api/v1/runs` and `GET /api/v1/runs/{id}` -- the `trace_id` field of the run object.
- `dg runs show RUN_ID` -- the `trace` row of the summary, rendered as `-` when it is null.
- `dg runs show RUN_ID --json` and `dg runs list --json`, off the run object the server sent.

**How an operator uses it.** Take the value, paste it into your backend's trace-id search --
`trace:<id>` in Jaeger, the trace lookup in Grafana Tempo, a `trace.id` filter in whatever you
run -- and you land on the whole run: the call that asked for it, every step attempt, every
block call each one made. The workers have to have the exporter environment too, or the trace
is the request and the run span alone.

With no exporter configured there is no trace to link to, and the column stays **null** rather
than holding the all-zero ids a no-op span reports. A null `trace_id` therefore means "telemetry
was off when this run was created", not "the trace was lost".

## Bring it up in an afternoon

`infra/compose.otel.yaml` is a working stack rather than a snippet: an OpenTelemetry collector,
Prometheus, Tempo, and a Grafana that provisions both datasources and a dashboard called
**Dirigent** from files in `infra/otel/`.

```bash
make docker-run-otel
```

or, spelled out, the base stack plus the overlay:

```bash
docker compose --project-directory . \
  -f infra/compose.yaml -f infra/compose.otel.yaml up --build -d --wait
```

Grafana is on <http://127.0.0.1:3300>; 3333 is the server and 3334 the docs. Nothing else in
the overlay publishes a port. Give the dashboard something to draw:

```bash
dg run hello-world
```

**To land on one run's trace**, take its trace id and search for it in Tempo:

```bash
dg runs show RUN_ID --json | jq -r .fields.run.trace_id
```

The dashboard's **Run id** box does the same thing from the other end: paste the run id and the
*One run's spans* panel lists every span carrying it -- the run span and each step attempt --
whichever process opened them. Any trace id in either trace panel opens the whole tree: the
request, the run, every step attempt and every block call, in one waterfall.
[infra/otel/README.md](https://github.com/winterop-com/dirigent/blob/main/infra/otel/README.md)
is what each container is for, and how to point the collector at a vendor instead.

## Wiring your own collector

An OTLP collector on the same compose network, receiving over HTTP on 4318.

**Wire the environment.** Add to the shared block in `infra/compose.yaml`, which is where the
server and the workers both read from:

```yaml
x-dirigent: &dirigent
  environment: &dirigent-env
    # ... the existing DIRIGENT_* settings ...
    OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_EXPORTER_OTLP_ENDPOINT:-http://collector:4318}
    OTEL_SERVICE_NAME: ${OTEL_SERVICE_NAME:-dirigent}
    OTEL_TRACES_EXPORTER: otlp
    OTEL_METRICS_EXPORTER: otlp
```

`DIRIGENT_ENVIRONMENT` is already in that block, and becomes `deployment.environment` on every
span and every metric. For a vendor endpoint that wants a key:

```yaml
    OTEL_EXPORTER_OTLP_HEADERS: "api-key=${OTEL_API_KEY}"
```

Without the exporter package installed -- which the image built here has, and a `pip install
dirigent-core` does not -- a configured endpoint produces one warning line,
`telemetry could not be configured`, and a process that otherwise runs normally.

To check the wiring before a collector exists, set `OTEL_TRACES_EXPORTER=console` and run
`dg dev`: every span prints to the process log as JSON, no extra and no endpoint needed. That
is also the only single-process way to see the step and block spans, for the reason in
[which processes actually export](#which-processes-actually-export).
