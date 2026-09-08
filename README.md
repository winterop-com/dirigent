![dirigent](docs/assets/banner.png)

# dirigent

A generic pipeline orchestrator. Pipelines are data, composed from pluggable building blocks
(operators, sensors, storage backends, notifiers) and executed as a DAG on a durable
Postgres-backed engine.

Dirigent knows nothing about any particular system. Integrations arrive as plugin packages,
and the block catalog they contribute is what the UI renders as forms, so installing a plugin
extends the product without a frontend release.

It borrows the best noun from Airflow and rejects its authoring model:

- **Operators do work.** Call an HTTP API, run a transform, copy between storage backends,
  submit a remote job. An operator either finishes synchronously with an output, or returns a
  remote handle for the engine to probe.
- **Sensors wait for the world.** A file appearing at a URI, an endpoint reporting ready, a
  time window opening. Sensors never block a worker: each poke is a scheduled, durable poll.
- **Pipelines compose blocks into a DAG**, stored as data and validated against the blocks'
  published schemas. No Python files to deploy, no drift between "the code" and "what runs".

The async submit-then-probe pattern is the engine's core primitive, not an integration
detail, because nearly every interesting external system works that way: publish a job, then
probe until it is ready. Each block tells the engine how its system probes; the engine owns
when, and what happens on timeout, loss, or failure.

## Quickstart

The fastest way to see it work needs no server, no database, and no Docker:

```bash
uv tool install dirigent-cli
dg run --local examples/hello-world.yaml
```

That applies the document and runs it in a throwaway SQLite instance in a temporary
directory, streams what each step does, and deletes the database afterwards. It is the same
apply, the same engine, and the same worker loop a real instance uses.

Then the real loop, in one process on one SQLite file:

```bash
dg dev | dg format
# the starting record carries a token, minted once; in another terminal:
export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...

dg init my-pipelines && cd my-pipelines
dg apply --dry-run                      # the whole-project plan
dg apply
dg run hello-world --watch
dg runs logs $(dg runs list --json | jq -r '.[0].id')
```

`dg dev` is the zero-dependency mode: one process, one SQLite file, an embedded worker, and a
development admin it creates for you. It starts from an empty `.dirigent/state` every time,
because that SQLite file is a development artifact and a stale schema answers strangely;
`--keep-state` keeps it. `dg server` and `dg worker` are the split processes for
a real deployment; `dg worker` refuses to start on SQLite, because its claim fallback is only
correct with exactly one process.

If something is not doing what you expect, `-v` shows the engine's own events and the API
calls the CLI makes, and `-vv` shows everything (with the per-statement libraries capped so it
stays readable; `--debug-all` lifts even that).

Two settings matter before a pipeline touches anything real:

```bash
# Connection secrets are encrypted at rest, so the key must exist before one is stored.
export DIRIGENT_SECRET_KEY="$(uv run python -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

# Blocks that execute code on a worker are refused unless their id is allowlisted.
export DIRIGENT_ENABLED_UNSAFE_BLOCKS='["shell.run"]'
```

Configuration layers, most specific first: `DIRIGENT_`-prefixed environment variables, then a
YAML file (`DIRIGENT_CONFIG_FILE`, `./dirigent.yaml`, `.dirigent/dirigent.yaml`, or
`~/.config/dirigent/dirigent.yaml`), then defaults. Everything a person hand-writes for
dirigent is YAML -- documents, this file, the CLI's profiles -- so there is one syntax to
know. To run against PostgreSQL:

```bash
export DIRIGENT_DATABASE_URL="postgresql+asyncpg://dirigent:dirigent@localhost/dirigent"
dg db upgrade
dg admin user create admin --role admin
```

For the container deployment instead, `dg init my-instance --template compose` writes the
whole stack -- PostgreSQL, object storage, a server and a worker -- with a generated instance
key and a first admin, ready for `docker compose up -d`. [Running it for
real](#running-it-for-real-three-services) is the same shape from a checkout.

## What it does today

- **The engine.** Claims with `FOR UPDATE SKIP LOCKED` on PostgreSQL, routed by the worker
  tags a run requires and ordered by priority, then round-robin between runs, then due time;
  durable `waiting` probing with a cursor a sensor's poke carries between pokes, trigger
  rules, retry policy, fan-out with per-item status, cancellation, manual retry, and crash
  recovery through leases and a spec hash.
- **The scheduler.** A leader-elected loop on a PostgreSQL advisory lock, with per-schedule
  IANA timezones and a misfire policy that fires once and advances rather than working
  through a backlog. Embedded in `dg server` by default; `dg scheduler` isolates it.
- **Webhook intake.** `POST /hooks/{token}` with server-minted tokens, optional HMAC over
  the raw body, per-token rate limiting, a strict payload-to-parameter mapping, and a
  delivery history that records refusals as carefully as acceptances.
- **Alerting.** Rules binding an event at a scope to a channel, delivered through a queue a
  worker claims, leases, and retries -- so a flaky channel cannot take down a worker or
  silently drop an alert. `log`, `webhook`, `slack` and `email` notifiers ship built in, the
  last two delivering through a connection.
- **Storage.** URI-addressed, with `file://` in core and `s3://` as its own package
  (`dirigent-storage-s3`, any S3-compatible endpoint, streamed and multipart).
- **The web UI.** The server ships it: a pipeline list and a node editor over the same
  document the CLI applies, forms rendered from the block catalog's own schemas, a live run
  view with its DAG, item grid and log stream, and the triggers, connections, schemas and
  alerting screens.
- **The rest.** The plugin host and its served catalog, envelope-encrypted connection
  secrets, the `dirigent/v1` document format with `dg apply` / `dg export`, the authenticated
  REST surface, OpenTelemetry instrumentation, `dg dev` standalone mode on SQLite, and the
  built-in block pack: `http.request` and `http.ready`, `storage.copy` and `storage.exists`,
  `shell.run`, the docker family (`docker.run`, `docker.build`, `docker.compose.up`,
  `docker.compose.down`), `git.checkout`, `sql.query` and `sql.execute`, the queue sensors
  `kafka.consume` and `rabbitmq.consume`, the clock sensors `time.window` and `time.sleep`,
  `validate.schema`, `value.const`, `pipeline.run` and `webhook.post`, plus the transform
  verbs `transform.jq`, `map.jq`, `filter.jq` and `convert.std`.
- **Composition and handoff.** `pipeline.run` starts another pipeline on the same instance
  and waits for it, bounded by a depth guard on the attribution chain; `webhook.post` hands a
  signed payload to another instance, signed the way this one's own intake verifies it; and
  the clock sensors gate a step on time: `time.window` on the wall clock in a named IANA
  timezone, `time.sleep` on a fixed duration, both parked rather than holding a worker.

Every block, with the config it takes and the output it produces, is in
[docs/blocks.md](docs/blocks.md) -- generated from the live catalog, so it cannot go stale.

## What is planned

None of this exists yet, and the order is roughly the order it is wanted in.

- **Adapter packs.** DHIS2 today, more adapters to come, each its own package on the plugin
  contract that already exists. The DHIS2 pack lives in the `winterop-com/dirigent-dhis2`
  repository.
- **The tabular half of the transform family.** More codecs beside `convert.std` and
  `convert.arrow`, an engine that runs a language runtime, and SQL over files: a duckdb-backed
  block reading parquet or CSV from a storage URI.
- **AI and FHIR blocks.** A step that asks a model against a schema its answer must fit, and
  the general half of FHIR: parse, render, validate against a profile, and a `fhir`
  connection kind.
- **Hardening.** Log batching under load, and dashboards for the telemetry already emitted.
- **Scoped authorization.** Three instance-wide roles are the whole model today; there is no
  way to let a team run its own pipelines and nobody else's.
- **Pagination and run detail.** Cursor pagination across runs, versions and histories; today
  it is cursor on run logs only and unbounded elsewhere.

[ROADMAP.md](ROADMAP.md) has the rest, including what has been decided and not yet built.
[docs/design.md](docs/design.md) is the specification, and
[docs/architecture.md](docs/architecture.md) says how the packages fit together.

## Running it for real: three services

`dg init <dir> --template compose` scaffolds this stack into a directory of your own.
`infra/compose.yaml` at the repository root is the same shape -- PostgreSQL, an API
server with the scheduler embedded, and one worker -- built from a single image in which
`dg server`, `dg worker`, and `dg scheduler` are the same code with different entry points.

```bash
cp .env.example .env      # then set DIRIGENT_SECRET_KEY and the bootstrap admin password
docker compose --project-directory . -f infra/compose.yaml up --build

export DG_URL=http://localhost:3333
dg apply examples/triggers/managed-and-manual.yaml
dg schedule list managed-and-manual
```

That worker carries the tag `docker`, so a pipeline whose `requires.workers` names it is
claimed only by a worker that can reach a daemon.

Everything the three services share is a database URL and a secret key. There is no broker,
no inter-service protocol, and no port open on the worker: all coordination is PostgreSQL,
which is what makes `docker compose --project-directory . -f infra/compose.yaml up --scale worker=3` the whole scale-out story, and what
lets a worker on another machine join the pool the moment it can reach the database.

Migrations run as their own one-shot service rather than inside the server's start-up, so
scaling the server out never means N processes racing to migrate one schema. Isolating the
clock is two lines: set `DIRIGENT_SCHEDULER_ENABLED=false` and add a service whose command is
`scheduler`. Leadership is an advisory lock, so a moment with both running is harmless.

## Examples

[`examples/`](examples) holds one runnable document per concept -- a linear chain, a diamond,
fan-out, a sensor gate, retry policy, an error-handler branch, triggers, a scheduled pipeline
with a webhook, the `requires` preflight, and a rich parameter schema. The HTTP ones call a
public echo service, so every one of them runs for real:

```bash
dg run --local examples/graph/linear.yaml -p day=2026-01-01 --enable-unsafe shell.run
dg run --local examples/failure/retries.yaml          # watch the retry policy fire, then give up
```

The `winterop-com/dirigent-dhis2` repository goes further: real pipelines against the public
DHIS2 demo, each carrying the connection it needs so it runs with nothing to set up. They are
what an adapter pack should one day replace, written with generic blocks in the meantime.

A test walks the directory on every CI run -- validation against the real catalog, the
`requires` preflight, and a canonical round trip -- so no example can rot in silence.

## Workspace layout

```text
dirigent/
  pyproject.toml           # workspace root: shared ruff/mypy/pyright/pytest config, no [project]
  packages/
    dirigent-common/       # value types and shared schemas; depends on nothing of dirigent's
    dirigent-plugin/       # the block contract: markers, specs, base classes
    dirigent-client/       # the API contract: wire schemas, and the async Python SDK
    dirigent-core/         # engine, schema, document format, plugin host, storage, auth
    dirigent-blocks/       # built-in generic operators and sensors
    dirigent-server/       # FastAPI app, authentication, the REST surface, and frontend/
    dirigent-cli/          # `dirigent` and the short alias `dg`
    dirigent-storage-s3/   # the s3:// storage backend, registering its own scheme
    dirigent-parquet/      # the parquet format pack: the convert.arrow codec
    dirigent-testing/      # test doubles and pytest fixtures for writing blocks
  examples/                # one runnable dirigent/v1 document per concept, plus python/ scripts
  docs/                    # mkdocs-material site; design.md is the in-repo spec
  infra/                   # compose files and the one image the three process roles share
```

Two of these are contracts other people write against, and both must stay small and stable:
`dirigent-plugin` is what a third-party block package imports, and `dirigent-client` is what a
program driving an instance imports. `dirigent-client` also owns every request and response
schema, and the server imports them from there, so a shape has one definition and the client
and the server cannot drift apart. Everything else can churn.

`dirigent-common` sits below both, holding what more than one package must agree on -- a
duration, a size, an entity code, the shared HTTP connection -- so an SDK need not depend on
the block contract to spell `30s`. [docs/architecture.md](docs/architecture.md) says which package may
depend on which, and a test asserts it.

## Development

```bash
make install        # sync the workspace virtualenv with all dev dependencies
make lint           # mutating: ruff format + ruff check --fix
make static         # read-only gate without the tests: ruff, mypy, pyright, the UI type scale
make check          # the static gate, the UI's, then the tests
make test           # the fast unit lane, on SQLite
make test-postgres  # the concurrency lane, against a real PostgreSQL (needs Docker)
make test-docker    # the docker family, against a real daemon
make test-queues    # the queue sensors, against real Kafka and RabbitMQ brokers
make load           # the load lane: what the log path costs, printed as records; never gates
make coverage       # the unit lane under coverage, gated at 90 percent
make gate           # what CI runs: the static gate, then the tests once under coverage
make ui             # build the web UI bundle the server serves from a checkout
make ui-gate        # the UI's half of `make check`: oxlint, the type checker, vitest
make docs           # serve the documentation site on 127.0.0.1:3334 (dirigent itself is 3333)
make docs-build     # build the site, failing on any warning
```

`make gate` is what CI runs, with the documentation build beside it and separate jobs for the
concurrency, s3, queue, docker, browser and compose lanes. Every
package is type-checked under mypy with `disallow_untyped_defs` and pyright in strict mode.
`docs/blocks.md` and `docs/settings.md` are generated -- `make docs-blocks` and
`make docs-settings` rewrite them from the catalog and the settings model.

Two tests are worth knowing about. The round-trip test asserts that exporting a document,
applying it, and exporting again is byte-identical, which is what keeps the UI and the YAML
two editors of one model. The end-to-end test (marker `e2e`) drives the product the way a
person does: it starts a real `dg dev` on a real port, scaffolds a project with `dg init`,
applies a three-step document over HTTP with a real bearer token, runs it, and reads its logs
back -- all as subprocesses, so nothing can pass by accident of sharing a Python process with
the code under test.

The two test lanes exist because they prove different things. SQLite proves semantics and
runs in seconds; it structurally cannot prove that N workers claiming at once never hand the
same attempt to two of them, so that -- and lease recovery, probe scheduling under
contention, and replay safety -- runs against a real PostgreSQL under the `postgres` marker.

## Status

Pre-1.0. Contracts change between minor versions, directly and without a deprecation path;
[docs/releases.md](docs/releases.md) says what an upgrade has to know.

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. See [LICENSE](LICENSE).

Source-available, not open source: the source may be read, and any other use -- running,
copying, modifying or distributing it -- requires written permission from the copyright
holder. The third-party code the server wheel redistributes, and the licences it carries, are
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
