# The telemetry overlay

Dirigent pushes OTLP and is never scraped, so watching it needs somewhere for it to push to.
This directory is that somewhere: four containers, one command, and a dashboard that already
has the queries on it. [docs/telemetry.md](../../docs/telemetry.md) is the instrument's home.

The **collector** is the only thing dirigent talks to; it fans metrics out to Prometheus and
traces out to Tempo. **Prometheus** scrapes the collector, and nothing else. **Tempo** stores
traces on a local volume, single-binary, with no retention plan worth the name. **Grafana**
reads both, comes up with anonymous admin, and provisions its datasources and the `Dirigent`
dashboard from files in this directory.

## The one command

```bash
make docker-run-otel
```

or, spelled out, the base stack plus this overlay:

```bash
docker compose --project-directory . \
  -f infra/compose.yaml -f infra/compose.otel.yaml up --build -d --wait
```

Grafana is on <http://127.0.0.1:3300> -- 3333 is the server and 3334 the docs -- and no other
service publishes a port. Open **Dashboards -> Dirigent**, then give it something to draw:

```bash
dg run hello-world
```

Runs by terminal status fills in first. **Recent run traces** is the panel to click: a row is
one trace, and opening its id draws the whole tree -- the request, the run, every step attempt
and every block call -- as one waterfall. Paste a run id into the **Run id** box at the top and
**One run's spans** lists that run's own spans, whichever process opened them.

## Which gauges sum and which do not

A metric that every process reports is not a metric you may add up.

| Instrument | How to aggregate | Why |
| --- | --- | --- |
| `dirigent.queue.depth`, `dirigent.waiting` | `max` | Every worker reports the whole queue, so a sum multiplies it by the worker count |
| `dirigent.worker.in_flight` | `sum by (dirigent_worker)` | Each worker reports only its own calls, under its registered name |
| `dirigent.scheduler.lag` | `max` | A scheduler standing by reports zero, and would drag an average down |
| `dirigent.worker.heartbeat_age` | `max by (dirigent_worker)` | Every sweeper reports every worker, so one worker has as many series as there are sweepers |
| `dirigent.runs`, `dirigent.steps` | the counter itself, or `rate` | `increase()` takes a series' first sample as its baseline, so counting a window this way loses every run a worker settled before that worker's series was first scraped |

The dashboard's panels already do this. A query you add should too.

## Pointing at a vendor instead

Two changes, both in `collector.yaml`. Add the vendor's exporter beside the two here:

```yaml
exporters:
  otlphttp/vendor:
    endpoint: https://otlp.example.com
    headers:
      api-key: ${env:VENDOR_API_KEY}
```

then name it in the pipelines that should go there. Keeping the existing exporter beside it
sends both, which is how a migration is done without a window where nothing is watched.

To skip the collector entirely, drop this overlay and set `OTEL_EXPORTER_OTLP_ENDPOINT` and
`OTEL_EXPORTER_OTLP_HEADERS` on the services in `infra/compose.yaml`: the image ships the OTLP
exporter, and the protocol is http/protobuf, so point at the vendor's 4318.
