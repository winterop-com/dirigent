# A server, start to finish

One sequence, run in order, from nothing to a pipeline running on a real instance. Every
alternative is [below the line](#alternatives) rather than inside it.

What this builds is the shape to run in production: PostgreSQL, the API with the scheduler
embedded, and a worker, from one image. If you want a single process on your own machine
instead, that is [`dg init` and `dg dev`](getting-started.md), and it needs none of this.

## Before you start

- Docker with Compose v2, and a clone of this repository. Everything below runs from its
  root, because the stack is built from this source.
- On a host that will not carry the source, `dg init DIR --template compose` writes the same
  stack against `ghcr.io/winterop-com/dirigent`, and there is nothing to clone.
- `dg` on your path, to talk to the instance once it is up: installed as in
  [getting started](getting-started.md), `uv sync` in the clone and `uv run dg`, or the one
  inside the image, `docker compose exec server dg ...`.

## 1. Write the environment file

```bash
cp .env.example .env
```

Two values in it have no safe default.

**`DIRIGENT_SECRET_KEY`** encrypts connection secrets and webhook signing secrets:

```bash
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Losing this key loses every stored connection secret, and changing it does not re-encrypt
what is already stored. Back it up somewhere that is not beside the database backup.

**`DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`** is the password the first admin gets. Set it to
something you choose; the account is created on the first start and named `admin`.

## 2. Bring the stack up

```bash
docker compose --project-directory . -f infra/compose.yaml up --build
```

That runs `postgres`, an `s3` server with a one-shot `s3-bucket` job that creates its bucket,
a one-shot `migrate` the rest wait on, `server`, and `worker`. Add `-d` to put them in the
background. `make docker-run` is the same command.

!!! note "Why not `docker compose up`"

    The compose files live in `infra/`, so a bare `docker compose up` from the root finds no
    configuration at all. Use the long form above, or `make docker-run`.

The server is on port 3333. In another terminal:

```bash
curl -fsS http://localhost:3333/health && echo ok
```

## 3. Point `dg` at it

```bash
export DG_URL=http://localhost:3333
dg auth login --username admin
```

`dg auth login` asks for the password from step 1, mints a token, and stores it. That token
is what every command below authenticates with.

## 4. Apply a pipeline and run it

```bash
dg apply examples/hello-world.yaml
dg run hello-world --watch
```

`--watch` streams the run and exits with its outcome.

The first apply will refuse: `shell.run` executes code on a worker, and an instance allows no
such block until it is told to, by name. Set it in `.env` -- a comma-separated list, not a
JSON array -- and recreate the two services that read it:

```bash
DIRIGENT_ENABLED_UNSAFE_BLOCKS=shell.run
```

```bash
docker compose --project-directory . -f infra/compose.yaml up -d --force-recreate server worker
```

## 5. See what the instance holds

```bash
dg pipeline list
dg runs list
dg trigger-document list
```

All three render at a terminal and write NDJSON into a pipe; `--json` asks for the records at
a terminal, and `dg format` reads a stream that was kept.

The last one is the instance's triggers documents -- the `kind: triggers` documents that
declare schedules and webhooks for a pipeline defined elsewhere. Three routes serve them:

| Route | What it answers |
| --- | --- |
| `GET /api/v1/trigger-documents` | Every triggers document, in code order, with the pipeline each fires |
| `GET /api/v1/trigger-documents/{code}` | One of them, the document itself, and the schedule and webhook codes it owns |
| `DELETE /api/v1/trigger-documents/{code}` | Removes it and every row it declared; the pipeline and its own triggers stay |

Reading either is a viewer's; the delete is an operator's.

That is the whole line. The instance is real: it survives a restart, more than one person can
use it, and one more worker is a `--scale` away.

## Alternatives

Each of these replaces one step above. None of them is needed to get to the end of the line.

### A database compose did not start

`.env` builds the database URL from `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`.
Setting `DIRIGENT_DATABASE_URL` instead moves migrate, server and every worker onto a managed
instance, because all three read the same environment block. The driver has to be `asyncpg`,
and TLS is a query parameter:

```bash
DIRIGENT_DATABASE_URL=postgresql+asyncpg://user:password@db.example.com:5432/dirigent?ssl=require
```

The local `postgres` service still starts; drop it with `--scale postgres=0`.

### The published image

Every release is pushed to `ghcr.io/winterop-com/dirigent:<version>`, so a host that will not
carry the source pulls instead of building.

The stack in this checkout builds its own image; the one `dg init --template compose` writes
pulls the published one, pinned to the version of the `dg` that wrote it. That directory is a
uv project, so `uv sync` once and then `uv run dg auth login --username admin` against the
stack it starts.

### The first admin, by hand

Leave `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD` empty and create the account yourself:

```bash
docker compose --project-directory . -f infra/compose.yaml exec server dg admin user create ada --role admin
```

This runs against the database rather than the API, and it has to: the first account must
exist before anything can authenticate to the endpoint that would create it. Run it somewhere
that can reach the database and has the configuration the server has.

### Tokens for scripts

A session belongs to a terminal. A script gets a token:

```bash
dg admin token create ci
export DG_TOKEN=...
```

The secret is shown once. `DG_TOKEN` beats a profile's token, and `dg auth status` says which
principal is in use.

### More workers

```bash
docker compose --project-directory . -f infra/compose.yaml up --scale worker=3
```

What limits that number is the database connection pool; the arithmetic is in
[scaling workers](operations.md#scaling-workers).

### Artifacts in S3

The stack keeps artifacts in a bucket, not on a volume, because every worker has to read what
any other worker wrote. `infra/compose.yaml` starts an S3-compatible server --
`DIRIGENT_S3_IMAGE`, RustFS by default -- creates the bucket, points the artifact root at
`s3://dirigent/artifacts`, and has the `migrate` service write the `artifacts` connection the
`s3://` scheme resolves through. Nothing is left to do by hand:

```bash
dg connection show artifacts
```

`S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` and `S3_CONNECTION` in `.env` are what that row
is built from; change one and the next `up` brings the row to it. Point them at a bucket you
already have and the bundled `s3` service is not needed. The endpoint the connection carries
is the one the server and worker resolve, not the one your shell does: `localhost` inside a
container is the container. Why it is shaped this way is in
[artifacts in object storage](operations.md#artifacts-in-object-storage), and the settings are
in [storage and artifacts](operations.md#storage-and-artifacts).

### Brokers for the queue examples

`infra/compose.brokers.yaml` adds a Redpanda and a RabbitMQ on the stack's network, which is
what [`examples/queues/`](queues.md#on-the-compose-stack) needs to run here. Only the RabbitMQ
management UI is published to the host; the brokers themselves are reached by service name:

```bash
make docker-run-queues
dg connection create kafka orders-topic --set bootstrap_servers='["redpanda:9092"]'
dg connection create rabbitmq shop-queue \
  --set url=amqp://dirigent@rabbitmq:5672/ --set password=dirigent
```

### A warehouse for the sql examples

`infra/compose.sql.yaml` adds a second PostgreSQL as a warehouse. It is nothing to do with
dirigent's database and is never queried by a pipeline; this is the one
[`examples/sql/`](sql.md#on-the-compose-stack) reads:

```bash
make docker-run-sql
dg connection create sql warehouse-read \
  --set url=postgresql+asyncpg://reader@warehouse:5432/warehouse \
  --set password=$WAREHOUSE_READER_PASSWORD --set read_only=true
```

### Somewhere to watch it

`infra/compose.otel.yaml` adds an OpenTelemetry collector, Prometheus, Tempo and a Grafana,
points every service's `OTEL_*` at the collector, and provisions a dashboard called
**Dirigent**. Grafana is on <http://127.0.0.1:3300>; nothing else in the overlay publishes a
port. What each panel reads, and which gauges may be summed, is in
[telemetry](telemetry.md#bring-it-up-in-an-afternoon):

```bash
make docker-run-otel
```

`make docker-run-all` layers every overlay at once.

## What to read next

- [Operations](operations.md) for backup, health checks, retention and upgrading.
- [Security](security.md) for what the roles can do and how secrets are held.
- [The tutorial](tutorial.md) for a pipeline worth running on this.
