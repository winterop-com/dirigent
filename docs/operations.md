# Operations

Everything dirigent coordinates, it coordinates through PostgreSQL. There is no broker, no
inter-service protocol, and no port on a worker. That is the fact most of this page follows
from: scaling out is adding replicas that point at the same database, leadership is an
advisory lock, and a worker on another machine joins the pool the moment it can reach the
database.

## Deployment shapes

The deployment target is an Ubuntu LTS server, which is what CI builds and runs the compose
stack on; anything with a current Docker or a Python 3.13 runtime works as well.

### One process, no dependencies: `dg dev`

```bash
dg dev
```

SQLite in a file, the API, the scheduler, and a worker in a single asyncio process. Its
database and its artifacts go in `.dirigent/state/` under the working directory, kept
between starts unless `--wipe-state` says otherwise. It migrates, mints a development admin
on an empty instance, emits the token once, and then goes quiet. At a terminal it renders
its lines; under compose or `docker logs` it writes NDJSON, which `dg format` renders back:

```bash
dg dev
```

```text
2026-01-01T18:22:23.069+01:00 [info    ] starting   [process] process=dev api=http://127.0.0.1:3333 docs=http://127.0.0.1:3333/docs admin=dev state=/home/you/my-pipelines/.dirigent/state token=osZDN7zM-DnWPb3rVJHWsxpgkekZylez1MF8E-GpgnI migrated=0001_baseline
2026-01-01T18:22:23.382+01:00 [info    ] ready      [process] process=dev
```

The token is a field on the starting record, so a script takes it without reading the rest:

```bash
export DG_URL=http://127.0.0.1:3333
export DG_TOKEN=$(dg dev | jq -r 'select(.kind == "process" and has("token")) | .token')
```

`dg dev` starts its own logging at WARNING, and `-v` is what asks for the migration lines, the
request log, and the engine's own events. That is a level, not a spelling: the terminal
decides the spelling.

This is for a laptop, an evaluation, or a CI job. It refuses to start on anything but SQLite:
`dg dev` on PostgreSQL is just `dg server`, and pretending otherwise would give two names to
one thing.

Every SQLite transaction opens with `BEGIN IMMEDIATE`, so it takes the one write lock the
file has at its first statement rather than at its first write. SQLite refuses a transaction
that began by reading and then asks to write while another connection is writing -- it fails
that upgrade with "database is locked" the instant it is asked, and no timeout covers it --
and applying a document is exactly that shape: it reads the pipeline and its versions before
it inserts. Taking the lock up front turns the refusal into a wait, and `busy_timeout` is
what bounds it: 15 seconds, which outlasts a fan-out settling forty items while an apply
waits behind it. A transaction still held after that fails rather than hanging forever. The
cost is that reads queue behind writers too, which is what one process on one file is for.

### Four services: server, worker, PostgreSQL, object storage

This is the shape `infra/compose.yaml` at the repository root implements, and the one to start from
in production:

- **PostgreSQL 17**, which is where all coordination lives.
- **`dg server`**, the API, with the scheduler embedded. Needing a fourth service just to get a
  clock is a poor default, and because leadership is an advisory lock, embedding it costs
  nothing when it later moves out.
- **`dg worker`**, which executes. It opens no port and nothing connects to it.
- **An S3-compatible server**, which is where artifacts live. See
  [artifacts belong in object storage](#artifacts-in-object-storage).

Plus a one-shot `migrate` service that runs before the other two: it brings the schema up,
so scaling the server out does not mean N processes racing to migrate the same schema, and
it ensures the connection the artifact root resolves through.

Everything the services share is a database URL, a secret key, and the bucket.

Four overlay files add to that base, each layered with another `-f` and each declaring only
what differs. `make docker-run-all` is every one of them at once:

| File | What it adds |
| --- | --- |
| `infra/compose.brokers.yaml` | Redpanda and RabbitMQ on the stack's network, for the [queue examples](queues.md#on-the-compose-stack). `make docker-run-queues`. |
| `infra/compose.sql.yaml` | A second PostgreSQL, `warehouse`, seeded from `examples/sql/warehouse.sql`, for the [sql examples](sql.md#on-the-compose-stack). `make docker-run-sql`. |
| `infra/compose.otel.yaml` | A collector, Prometheus, Tempo and Grafana, for [telemetry](telemetry.md). `make docker-run-otel`. |
| `infra/compose.sinks.yaml` | Mailpit and an HTTP sink, so an alert's arrival is something to look at. `make docker-run-sinks`. |
| `infra/compose.queues.yaml` | Not an overlay: a standalone project publishing both brokers on the host, which is what the `queues` pytest lane runs against. |

**Pointing at a database compose did not start.** `infra/compose.yaml` honours
`DIRIGENT_DATABASE_URL` when `.env` sets it, and falls back to a URL assembled from
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` when it does not. Setting it moves the
whole stack -- migrate, server, and every worker -- onto the managed instance, because all
three read the same environment block. The driver has to be `asyncpg`, and TLS is a query
parameter:

```bash
DIRIGENT_DATABASE_URL=postgresql+asyncpg://user:password@db.example.com:5432/dirigent?ssl=require
```

The local `postgres` service is still declared and still starts; drop it with
`docker compose --project-directory . -f infra/compose.yaml up --scale postgres=0`.

### Artifacts in object storage

A second worker node needs every worker on the same object storage. A step's output is read by
whichever worker claims the next step, so the artifact root has to be one address that every
process resolves to the same bytes. A shared filesystem is the worse answer: NFS or a cloud
file share gets you there, at the cost of a mount whose locking and consistency you now own,
on every node, before a run can start. A bucket is one URL and a credential.

So the stack keeps artifacts in a bucket out of the box, and there is no artifact volume in
`infra/compose.yaml` at all. What that takes:

- **`DIRIGENT_ARTIFACT_ROOT=s3://<bucket>/artifacts`** on the server and on every worker.
- **`DIRIGENT_STORAGE_CONNECTIONS=s3=<code>`**, which says which connection configures the
  `s3://` scheme. Without it the scheme falls back to the ambient AWS credential chain.
- **The connection itself**, holding the endpoint, the credential and the addressing style. It
  is a database row, and a container has no API token to create one with, so the `migrate`
  service writes it with [`dg connection ensure`](cli.md#dg-connection-ensure) after the
  schema upgrade and before anything else starts. The command is idempotent: it creates the
  row or brings the one it finds to what the environment now says, and seals the secret half
  with the instance key exactly as the API path does.
- **The credentials in the environment and nowhere else.** `S3_ACCESS_KEY` and `S3_SECRET_KEY`
  reach the `migrate` service as environment variables; nothing writes them to a file, an
  image layer, or a document.
- **A healthcheck on the storage service**, so a worker does not start against an endpoint
  that is not answering yet, and **a named volume** (`s3`) for the bundled server, so the
  bucket survives a restart. `docker compose down -v` is what discards it.

The bundled server is a convenience, not a requirement: `DIRIGENT_S3_IMAGE` names the image,
any S3-compatible endpoint serves `s3://`, and pointing `DIRIGENT_ARTIFACT_ROOT` and the
`S3_*` variables at a bucket you already have drops the `s3` and `s3-bucket` services from the
picture entirely.

**Outside Docker, `file://` stays the default and stays legitimate.** `dg dev` and a bare
single-node install write artifacts to a local directory and need no bucket, no connection and
no `DIRIGENT_STORAGE_CONNECTIONS` at all. One node, one filesystem, one process reading what
it wrote: object storage buys nothing there. It is the second node that makes it mandatory.

### Two roots: scratch is shared, work is local {: #scratch-and-work }

A run has two places to put things, and they are not the same place:

| | `DIRIGENT_ARTIFACT_ROOT` | `DIRIGENT_WORK_ROOT` |
| --- | --- | --- |
| What it is | A storage URI prefix | A directory on this worker's disk |
| A run's own | `${run.scratch}`, addressed through storage | the run's work directory, opened as files |
| Who can read it | Every worker | Only the worker that wrote it |
| What goes there | A step's output, a saved payload, a captured stream | A checkout, a build context, a compose file, a bind mount, a duckdb file |

Everything a later step must read goes to scratch, because which worker claims that step is
not knowable in advance. But some things are not bytes a block hands over -- they are
directories a tool opens. `git.checkout` shells out to git, `docker.build` gives buildx a
context path, `docker.compose` gives the CLI a file to read, `docker.run` binds a host
directory into a container, and duckdb opens a file. None of that can be a bucket, whatever
the artifact root says, so those blocks work in the run's work directory instead.

`DIRIGENT_WORK_ROOT` defaults to `./.dirigent/state/work`, beside the default artifact root,
and each run gets `runs/<run id>` under it. On the compose stack it is `/var/lib/dirigent/work`
on a named `work` volume, which the `docker` sidecar mounts **at the same path** -- a bind
mount is resolved on the daemon's filesystem, not the worker's, so the path `docker.run` hands
over has to mean the same directory on both sides.

!!! warning "A work path holds on one worker only"

    A path a step leaves in the work directory is not one another worker can be handed. Two
    steps that pass a directory between them -- check out a repository, then build it -- must
    run on the same worker, which on a single-worker instance they always do and on a
    multi-node one they do not. This is the same caveat the `local_execution` blocks already
    carry; hand a later step a storage URI, not a path, wherever it might be claimed elsewhere.

The work directory is swept on the same policy as the scratch it sits beside: a worker deletes
its own `runs/<id>` once `DIRIGENT_RETENTION_RUNS` has outlived the run, on the retention
interval. The database sweep runs on the scheduler and cannot reach another host's disk, so
each worker sweeps its own.

### Scaling workers

```bash
docker compose --project-directory . -f infra/compose.yaml up --scale worker=3
```

That is the whole scale-out story for execution. A worker needs no configuration to join:
it registers itself, claims with `FOR UPDATE SKIP LOCKED`, and is interchangeable with every
other worker unless a tag makes it otherwise.

**What the claim takes first**, in order: the run's priority, then fairness, then due time.
Fairness is round-robin between runs -- each claim takes every run's next-due attempt before
any run's second -- so one run fanned out over ten thousand items does not hold the queue
against a run created after it. Due time breaks the tie inside one run. A `high` run's
attempts therefore go ahead of every other run's the moment a slot frees, and nothing running
is preempted to make room.

**What one worker sustains.** `make load` runs fifty attempts logging five thousand lines
each across two workers at `WORKER_CONCURRENCY=25` against a real PostgreSQL, and prints what
the log path cost as `load` records. On an M-series laptop with the database in a container
beside it, that is 19,000 log rows a second written to the run, a flush transaction of
0.17s at the 95th percentile, and 23 of a worker's 29 pooled connections held at the peak of
the burst with the overflow untouched. The numbers are a measurement of one machine, not a
promise; run it on yours.

**What limits N is database connections, and the arithmetic is worth doing before you find
it.** One process's ceiling on PostgreSQL is
`DIRIGENT_DATABASE_POOL_SIZE + DIRIGENT_DATABASE_MAX_OVERFLOW`, which at the defaults is
`12 + 4 = 16`. That ceiling applies per container, so the load on the database is 16 times
the number of server and worker containers. PostgreSQL's own stock `max_connections` is 100,
which is one server plus five workers with a little room -- and it is a global limit, shared
with anything else pointed at that server, `psql` sessions included.

Three ways past it, in the order to try them:

1. **Lower the pool.** A worker at `DIRIGENT_WORKER_CONCURRENCY=8` needs 12 connections, not
   16. Setting `DIRIGENT_DATABASE_POOL_SIZE=8` and `DIRIGENT_DATABASE_MAX_OVERFLOW=4` on the
   workers takes each container to 12 and gets you eight of them under 100.
2. **Raise `max_connections`** on the database, which costs memory per connection.
3. **Put PgBouncer in front**, in *session* pooling mode. Transaction pooling breaks
   `pg_advisory_lock`, which is how the scheduler holds leadership.

The floor is enforced rather than advised: on anything but SQLite an instance **refuses to
start** when `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW` is less than
`WORKER_CONCURRENCY + 4`, and the message names all three numbers. So raising a worker's
concurrency to 24 means at least 28 connections in that process's pool, which is fewer
workers per database, not more throughput for free. Scaling out with more replicas at the
default concurrency is usually the cheaper direction.

The pool settings are in the shared environment block in `infra/compose.yaml` rather than on each
service, because the number that matters is the total across every container.

### Multi-node

More `dg worker` replicas scale execution linearly, on the same machine or on others. To
isolate the clock, run the server with `--no-scheduler` (or `DIRIGENT_SCHEDULER_ENABLED=false`)
and add a process running `dg scheduler`. Two schedulers by mistake is harmless: leadership is
`pg_try_advisory_lock`, so the second one is told no immediately and stands by, retrying until
the leader's connection dies and the lock is released with it.

Each scheduler holds that lock on a connection of its own, outside the pool, for the process's
lifetime. Count one connection per scheduler on top of the pool arithmetic above.

Four things multi-node needs. Go through them as a checklist before the second node, because
none of the four is checked at start-up -- every one of them fails later, as a run.

**1. One database, reachable by everything.** There is no second store and no broker, so every
server, worker, and scheduler points at the same `DIRIGENT_DATABASE_URL` and needs no other
address. Two dirigent instances must not share one database: the scheduler's advisory lock is
taken on a single key, so they would take leadership from each other and each fire the other's
schedules.

**2. Shared artifact storage, reachable by every worker.** A step's output must be readable by
whichever worker claims the next step, and which worker that is, is not knowable in advance.
That is why `infra/compose.yaml` puts artifacts in a bucket rather than on a volume; see
[artifacts in object storage](#artifacts-in-object-storage). Across machines it is the only
answer: `DIRIGENT_ARTIFACT_ROOT` on `s3://`, never `file://` on local disk, which fails as a
step that cannot find an input the previous step swears it wrote.

**3. The same `DIRIGENT_SECRET_KEY` on every process.** Workers decrypt connection credentials,
so a worker holding a different key cannot open any envelope the instance holds -- not a subset,
none of them. The failure surfaces on the worker path, when a pipeline asks for a credential,
and each envelope carries a short key id so the message names the key that sealed the row
rather than saying decryption failed.

**4. Code parity across workers.** Nothing is pickled or shipped over the wire, so every worker
must have the same dirigent packages and the same plugin packages installed. Each worker
registers the digest of the catalog it built at start-up, and `GET /api/v1/workers` compares
that digest against the server's own, answering `code_matches_server: false` for any worker
running different code. `dg system workers` renders it as the **same code** column, and it is
the field to check after a rolling upgrade or a plugin install: a worker where it is false will
fail a pipeline naming a block it does not have, and nothing else reports that until it
happens. The same response carries `stale`, true once a heartbeat is more than two minutes old
-- in the JSON, not in the table, where the age of the last heartbeat is shown instead.

**Routing by tags** is how a machine that is not interchangeable is addressed. A worker
advertises what it carries with `dg worker --tag docker --tag gpu` (repeatable) or
`DIRIGENT_WORKER_TAGS=docker,gpu` (comma-separated), and both land in its registry row at
registration and on every heartbeat. A document declares what it needs with
`requires.workers: [docker]`, the run pins that list when it is created, and only a worker
carrying every tag on it claims the run's work. A document requiring nothing is claimable by
any worker, tagged or not, so nothing changes for an instance that never sets a tag.

A run whose tags no live worker carries simply queues: `dg apply` says so when it applies the
document, and `dg runs show` and the run screen say which tag the run is waiting for. Start a
worker carrying it and the run is claimed on the next pass.

### Why SQLite is refused for `dg worker` and `dg scheduler`

Both refuse to start on SQLite, with exit code 3 and a message saying so. This is a guardrail
rather than a limitation, and the reasons are specific:

- **The worker's claim query.** On PostgreSQL, work is claimed with `FOR UPDATE SKIP LOCKED`,
  which is what lets N workers pull from one queue without colliding. SQLite has no such
  thing, so the fallback is a plain single-writer claim transaction -- correct if and only if
  exactly one process exists. Two workers on one SQLite file would run the same work twice.
- **The scheduler's leadership.** Leadership is `pg_try_advisory_lock`. SQLite has no advisory
  lock, so `try_lead` is unconditionally true: two schedulers on one SQLite file would both
  believe they are the leader and both fire every schedule.

`dg server` on SQLite is refused for the same reason as the scheduler, because it embeds one --
unless you pass `--no-scheduler`. `dg dev` is the sanctioned single-process mode, and it is
single-process by construction.

Migrations run on both dialects, and SQLite is a first-class test and development target. It
is just not somewhere more than one process may point.

## Standing an instance up from a directory of documents

Between releases the baseline migration can move in place, so a development database
from an older checkout would keep an older schema forever -- alembic sees its one revision
as applied and upgrades nothing. `dg dev --wipe-state` is what to pass after a pull that
moved the schema: a dev state is disposable, and the failure it would otherwise cause is a
wrong answer rather than an error. A released schema only moves forward, and a plain `dg dev`
migrates the instance it finds.

The server applies a directory at boot when one is named. `DIRIGENT_APPLY_DIR` points at
a mounted directory of documents; every boot applies what is new or changed there -- the
digest makes an unchanged document a no-op -- before the scheduler starts firing. One bad
document never stops the boot: it is refused with a warning naming the file and the first
issue, and the rest apply. A document that carries its own `connections:` or its own
`schemas:` is refused by the seed exactly as the API refuses it, with the same sentence: an
instance holds a connection and a schema as its own named resource, so a carried one is for a
`dg run --local` and never for a document a server stores. Several servers booting together
elect one applier on an advisory lock, the same way the scheduler elects a leader.

A directory carries schemas as well as documents. A `.json` file that is a plain JSON Schema
rather than a `dirigent/v1` document is stored the way `dg schema create` stores it, and stored
before the pipelines, so a document whose `requires.schemas` names one applies in the same boot.
A prune never touches a schema.

`DIRIGENT_APPLY_PRUNE=true` adds the reconcile half: a pipeline the directory applied
earlier and no longer holds is deactivated, never deleted, so its history survives and a
mistake is one `dg pipeline activate` from undone. Pruning only ever touches pipelines
whose current version came from a directory apply -- one authored in the UI or applied by
hand is never pruned, however absent -- and a boot that discovered zero documents refuses
to prune at all, because an empty mount is an accident, not an instruction. The same
reconcile runs by hand as `dg apply --prune` inside a project, and
`dg apply --dry-run --prune` prints exactly what the next boot would do.

**Pipeline documents are applied before triggers documents**, whatever the paths sort as, so
a directory that carries both converges in one pass: a `kind: triggers` document is refused
while the pipeline it names is absent, and applying the pipeline first is what makes it
present. A triggers document the directory no longer holds is *deleted* rather than
deactivated -- it has no history worth keeping -- and the delete takes the schedules and
webhooks it declared with it, never the pipeline's own inline ones and never a hand-made row.
The same narrowing applies: only a triggers document a directory apply wrote is ever pruned.

Standing an instance up by hand is still one command for the whole directory:

```bash
dg apply --paused
```

The flag is what makes a bulk apply safe on an instance nobody is watching yet. A document
that carries a `triggers:` section is a live clock the moment it is stored, so applying
twenty of them at once can put twenty firings into a queue before anybody has looked at the
first. `--paused` creates the schedules that apply mints already paused: the row is inserted
paused rather than paused a moment later, so there is no window in which a due schedule is
live. `dg schedule resume PIPELINE NAME` starts each one when you mean it to.

It reaches only what the apply creates. A schedule the instance already holds is operational
state -- an operator paused it, or resumed it, and an apply has no business overruling either
-- so re-applying without the flag never re-pauses one somebody resumed, and re-applying with
it never pauses one already running. That is what lets the same `dg apply --paused` sit in a
promotion script and be run on every merge.

## Ports

| Port | What |
| --- | --- |
| 3333 | The dirigent API server (`DIRIGENT_PORT`), and what `dg dev` binds |
| 3334 | The local documentation site, `make docs` |

3334 is deliberately adjacent to 3333 rather than mkdocs' default of 8000, so the docs and the
instance sit next to each other and neither collides with whatever else is on 8000.

## The web UI

The UI is a single-page bundle built into the server wheel, so there is no second process, no
second port, and no CORS: the browser talks to the same origin it loaded the page from.

The server mounts it in three pieces.

| Path | What is served | Cached |
| --- | --- | --- |
| `/assets/*` | vite's content-hashed files, from `dirigent_server/static/assets` | `public, max-age=31536000, immutable` |
| `/config.json` | `{"api_prefix", "version"}`, so the bundle need not hardcode a prefix an instance can move | `no-cache` |
| everything else a GET or HEAD reaches | `index.html`, because the UI routes on clean paths and `/runs/<id>` is a route inside the bundle rather than a file | `no-cache` |

Precedence is unchanged by any of it: an API route is matched first, then a real file, and the
shell is the last resort. `/health`, `/hooks/{token}`, `/docs`, `/openapi.json` and everything
under the API prefix are never answered with the shell, so a `fetch` that asks for something
that is not there still gets a problem document rather than HTML. A write to a client route is
not a navigation and is refused rather than served.

A bundle built while the server runs is served without a restart: the shell and the asset
tree are read per request, so `make ui` lands under a running `dg dev`, and the moment a
rebuild leaves empty answers the same refusal rather than an error.

**`DIRIGENT_UI_ENABLED=false`** -- or `--no-ui` on `dg server` and `dg dev`, which is the
same switch for one invocation -- leaves the process an API and nothing else: no `/`, no
`/assets`, no `/config.json`. Nothing about the API changes either way.

**With the UI enabled and no bundle built**, the API serves normally and `/` answers `503`
with one sentence naming `make ui`. That is the honest status: the UI is configured on and
unavailable, and a blank `200` page would say the opposite to a browser and to whatever is
watching. Use the probes under `/health` to decide whether the instance is up; `/` is the UI's
answer, not the instance's.

**Building the bundle.** `make ui` builds it into `packages/dirigent-server/src/dirigent_server/static/`,
which is where the wheel picks it up and where an installed server looks first. A checkout that
has vite's dev output at `packages/dirigent-server/frontend/dist` is served from there instead,
so the dev loop needs no reinstall. `make ui-wheel` builds the wheel and fails unless
`dirigent_server/static/index.html` is inside it -- run it in the release job, because a wheel
that quietly lost the bundle looks exactly like a wheel that has one until someone opens a
browser.

The container image builds the bundle in its own stage and copies it to
`dirigent_server/static/`, so it carries the UI whatever the working tree the build ran from
holds; `.dockerignore` keeps a host `dist/` or `static/` out of the build context.

Note that `DIRIGENT_HOST` defaults to `127.0.0.1`, not `0.0.0.0`. In a container you almost
certainly want `DIRIGENT_HOST=0.0.0.0` with the port published by the runtime, which is what
the image does.

## Configuration reference

Settings come from four layers, most specific winning: explicit arguments, then `DIRIGENT_`
environment variables, then a `.env` file, then a YAML file, then the defaults below.

The YAML file is `$DIRIGENT_CONFIG_FILE` if that is set; otherwise `dirigent.yaml`,
`.dirigent/dirigent.yaml`, and `~/.config/dirigent/dirigent.yaml` are all read, with the
nearest one winning. A leftover `dirigent.toml` sitting where the YAML now belongs is refused
by name rather than silently ignored.

Every setting below is written as its environment variable. In YAML, drop the prefix and
lowercase it: `DIRIGENT_LOG_FORMAT=json` is `log_format: json`.

Two spellings are accepted for the collection settings, because the obvious one and the
generated one are different. `DIRIGENT_ENABLED_UNSAFE_BLOCKS=shell.run,docker.run` is what a
person types; a JSON array works too, and so does an ordinary list in `dirigent.yaml`. The same
applies to `DIRIGENT_WORKER_TAGS`, and `DIRIGENT_STORAGE_CONNECTIONS=s3=archive` is the
mapping equivalent.

Check what an instance actually resolved with `dg config show`.

### `docker.run` on a containerized worker

The stack ships the worker a daemon of its own. `infra/compose.yaml` starts a `docker:dind`
sidecar serving `tcp://docker:2376` with TLS, and the worker alone carries `DOCKER_HOST`,
`DOCKER_TLS_VERIFY=1` and `DOCKER_CERT_PATH=/certs/client` pointing at it. A pipeline's
containers are the sidecar's; **no host socket is mounted anywhere**. The sidecar is
`privileged`, which docker-in-docker requires, and it mounts the same `artifacts` volume at
`/var/lib/dirigent/artifacts` as the worker, because a bind mount `docker.run` asks for is
resolved on the daemon's filesystem rather than the worker's.

That worker carries `DIRIGENT_WORKER_TAGS: docker`, so a document declaring
`requires.workers: [docker]` routes to it and to nothing else in the stack.

The `docker.*` blocks are still `local_execution`, so name them in
`DIRIGENT_ENABLED_UNSAFE_BLOCKS` before a step will run.

**Stacks a run left up are reaped.** A worker with a docker CLI on its PATH runs a pass every
`DIRIGENT_DOCKER_REAP_INTERVAL` that takes down compose projects whose run is terminal or no
longer held, once the project is older than `DIRIGENT_DOCKER_REAP_GRACE`. `dg docker reap` is
the same pass on demand, `--dry-run` says what it would take down. Full behaviour is in
[the orphan reaper](docker.md#the-orphan-reaper).

Mounting the host's `/var/run/docker.sock` into the worker is the discouraged alternative: it
**grants that container root on the host** — anything that can talk to the daemon can start a
privileged container. Do it only for a worker you trust with the machine, or keep container
steps on a dedicated worker outside the stack (`dg worker --tag docker` on the host, with the
pipeline declaring `requires.workers: [docker]` to route to it).

### The image

`infra/Dockerfile` builds the one image every role runs: `dg server`, `dg worker` and
`dg scheduler` are the same image with a different command. A release pushes it as
`ghcr.io/winterop-com/dirigent:<version>` and `ghcr.io/winterop-com/dirigent:latest`, stamped
with `org.opencontainers.image.version` and `.revision`.

**Building on it.** The image is a base. `uv` is on its PATH, `VIRTUAL_ENV` names the venv at
`/app/.venv`, git is installed, and the stage ends as the `dirigent` user, which owns the venv.
A pack, or anything else a deployment adds, is one more layer:

```dockerfile
FROM ghcr.io/winterop-com/dirigent:<version>
RUN uv pip install dirigent-<pack>
```

`dg init --template compose` writes exactly this: a `Dockerfile` that is `FROM` the published
image with the pack line commented out, and a compose stack that builds and runs it.

**What the image carries beside the daemon.** `infra/Dockerfile` installs `docker-ce-cli`
with the **compose** and **buildx** plugins, which is what `docker.compose.up`,
`docker.compose.down` and `docker.build` shell out to, and `git` with `openssh-client`, which
is what `git.checkout` shells out to and, for an `ssh://` remote, what git runs in turn.

### Deployment identity

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_ENVIRONMENT` | `local` | Which deployment this instance believes it is. One of `local`, `staging`, or `prod`, and anything else is refused. Reported as `deployment.environment` on telemetry. |
| `DIRIGENT_CONFIG_FILE` | unset | Names the YAML configuration file explicitly, instead of searching the three default locations. |

!!! note

    Every setting, its default and its description are generated from the settings model on
    the [settings reference](settings.md) page, and `dg init` writes the same list as a
    commented `dirigent.example.yaml` beside the project's own `dirigent.yaml`. The tables
    below carry the operational detail that does not belong in a field description.

### Database

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_DATABASE_URL` | `sqlite+aiosqlite:///./.dirigent/state/dirigent.db` | SQLAlchemy async URL. The default is relative to the working directory, and its directory is created on start. PostgreSQL is `postgresql+asyncpg://...`. A URL starting with `sqlite` puts the instance in single-process mode. |
| `DIRIGENT_DATABASE_ECHO` | `false` | Echo every emitted SQL statement to the process log. Debugging only. |
| `DIRIGENT_DATABASE_POOL_SIZE` | `12` | Connection pool size; ignored by SQLite. Sized against `WORKER_CONCURRENCY`, not picked for elegance -- see the refusal below. |
| `DIRIGENT_DATABASE_MAX_OVERFLOW` | `4` | Connections the pool may open beyond the pool size under a burst. The ceiling one process imposes is pool size plus overflow, and that number has to be multipliable by the replica count without passing the database's own limit. |
| `DIRIGENT_DATABASE_POOL_TIMEOUT` | `30s` | How long a checkout waits for a free connection before failing loudly. |
| `DIRIGENT_DATABASE_POOL_RECYCLE` | `30m` | Recycle a pooled connection older than this; unset disables recycling. |

On anything but SQLite, an instance **refuses to start** when
`DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW` is less than `WORKER_CONCURRENCY + 4`. That is
not tidiness. A worker running N block calls at once needs a connection per outcome
transaction, and the heartbeat, the sweeper, and the alert loop each need one too. When the
pool cannot cover them, the heartbeat is the loop that loses -- it is the shortest and the
least persistent -- so leases expire under load, the sweeper reclaims live attempts, and
non-idempotent work runs twice. The failure looks like a mysterious duplicate rather than pool
exhaustion, which is exactly why it is refused up front.

### HTTP server

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_HOST` | `127.0.0.1` | Address the API server binds. Set to `0.0.0.0` in a container. |
| `DIRIGENT_PORT` | `3333` | Port the API server binds. |
| `DIRIGENT_API_PREFIX` | `/api/v1` | Mount point of the versioned REST API. Normalised to be rooted and free of a trailing slash. `/hooks/{token}` is not under it. |
| `DIRIGENT_UI_ENABLED` | `true` | Whether the server serves the bundled web UI beside the API. `--ui/--no-ui` on `dg server` and `dg dev` is the flag form. See [the web UI](#the-web-ui). |

### Logging

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_LOG_LEVEL` | `INFO` | Process log level: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. This is the *process* log; product telemetry is the `log_entries` table. A CLI `-v` / `--debug` flag wins over it. |
| `DIRIGENT_LOG_FORMAT` | the terminal decides | How a command spells its output and its logs: `console` renders, `json` writes records. Unset, a terminal renders and anything else gets records, the process commands included. |

### Storage and artifacts

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_ARTIFACT_ROOT` | `file://./.dirigent/state/artifacts` | Default storage backend URI prefix for run scratch space and artifacts. The `file://` backend refuses to address anything outside this root. The default is relative to the working directory, beside the default SQLite database. |
| `DIRIGENT_WORK_ROOT` | `./.dirigent/state/work` | Directory on this worker's own filesystem for what a tool opens as files rather than through storage: a checkout, a build context, a compose file, a bind mount, a duckdb database. A path, not a URI, and never shared between workers. See [scratch and work](#scratch-and-work). |
| `DIRIGENT_STORAGE_CONNECTIONS` | empty | Which connection configures each storage scheme, by code, as `scheme=connection`. `s3=archive` lets one instance hold several `s3` connections and still say which one `s3://` addresses. A scheme with no entry keeps whatever its package contributed it with, which for `s3://` is the ambient AWS credential chain. |
| `DIRIGENT_INLINE_ARTIFACT_MAX` | `16kb` | Outputs at or below this serialized size are inlined into the artifact row; larger ones are streamed to the run's scratch prefix. Note this governs the artifact copy only -- the attempt row keeps the output whole either way. |
| `DIRIGENT_INLINE_CAPTURE` | `8kb` | How much of a captured stream a block may inline in its output: what `shell.run` and `docker.run` put in `stdout` and `stderr`, and what their `stdout_truncated` / `stderr_truncated` fields report on. Raise it for a chatty job; the whole stream is written to the run's scratch either way, and `stdout_uri` and `stderr_uri` address all of it. |

Any S3-compatible endpoint serves `s3://`. The endpoint, credentials and addressing style
live on the connection, so nothing above it knows which server answers: AWS S3, a provider's
object store, or one you run. `infra/compose.yaml` starts one and bootstraps its connection so
the stack is complete out of the box; see
[artifacts in object storage](#artifacts-in-object-storage).

### Secrets

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_SECRET_KEY` | unset | The envelope key for connection secrets and webhook signing secrets. Required before any secret can be stored or read. A Fernet key is used as-is; anything else is hashed into one. |
| `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD` | unset | Creates the first admin unattended when the server starts against a database with no accounts. One-way: it does nothing once any account exists, so leaving it set on every deploy cannot reset a live instance's password. |

### Workers

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_WORKER_CONCURRENCY` | `8` | How many block calls one worker runs at a time. Keep the database pool above it; see above. |
| `DIRIGENT_WORKER_TAGS` | empty | Capability tags this worker advertises to the claim query, comma-separated. The claim routes on them: only a worker carrying every tag in a run's `requires.workers` claims that run's work. `dg worker --tag` is the flag form. See [routing by tags](#multi-node). |
| `DIRIGENT_WORKER_NAME` | hostname plus pid | Registry name of this worker. Constrained like every entity code, because the registry is a listing an operator reads. |
| `DIRIGENT_LEASE` | `60s` | How long a claimed attempt's lease is valid before the sweeper may reclaim it. |
| `DIRIGENT_HEARTBEAT` | `15s` | How often a worker refreshes the leases it holds and its registry row. |
| `DIRIGENT_CLAIM_IDLE` | `500ms` | How long a worker waits before asking for work again when the queue is empty. |
| `DIRIGENT_SWEEP_INTERVAL` | `30s` | How often a worker runs the crash-recovery sweeper over expired leases. This is also the cadence the queue-depth and `waiting` gauges are sampled on. |
| `DIRIGENT_STUCK_RUN` | `1h` | A running run with no attempt progress for this long is flagged as stuck, which is what raises a `run_stuck` alert. |
| `DIRIGENT_STALE_WORKER` | `15m` | A worker registry row whose last heartbeat is older than this is deleted by the sweeper, not marked stopped -- a worker's name carries its process id, so the process it described can never come back under that name. Fifteen minutes is sixty beats at the default heartbeat, and the margin has to survive a paused container: deleting the row of a worker that is merely slow removes it from the inventory while it is still claiming work. Reaping the registry does not touch the work such a worker held; expired leases are reclaimed by the lease sweeper on a much shorter clock. |
| `DIRIGENT_LOST_JOB_MAX_GONE` | `3` | Consecutive `GONE` probes before the lost-job policy fails a waiting attempt, rather than letting it hang forever on a remote that forgot the job. |
| `DIRIGENT_ENABLED_UNSAFE_BLOCKS` | empty | Block ids permitted to execute code on a worker, comma-separated. Empty means none. See [security](security.md#local-execution-and-the-unsafe-block-allowlist). |
| `DIRIGENT_DOCKER_REAP_INTERVAL` | `5m` | How often a worker with a docker CLI on its PATH looks for compose stacks whose run has ended. A humane duration; `0` turns the pass off, and a worker that can reach no daemon runs no loop at all. See [the orphan reaper](docker.md#the-orphan-reaper). |
| `DIRIGENT_DOCKER_REAP_GRACE` | `10m` | How old a compose project must be before a pass will consider it. A project's age is its newest container's, so a stack still being brought up is young however long its first container has been running. |

### Scheduler

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_SCHEDULER_ENABLED` | `true` | Whether `dg server` embeds the scheduler. `dg server --no-scheduler` is the flag form. |
| `DIRIGENT_SCHEDULER_TICK` | `5s` | How often the leader asks the database which schedules are due. |
| `DIRIGENT_SCHEDULER_MISFIRE_GRACE` | `5m` | How late a firing may be before it counts as a misfire: fire once, recompute from now, no catchup storm. Inside the grace the clock advances from the slot it owed instead, which means `next_fire_at` can legitimately be in the past. |
| `DIRIGENT_SCHEDULER_LOCK_KEY` | `1684632167` | The PostgreSQL advisory-lock key leadership is taken on. Change it only if two independent dirigent instances share one database, which is not a supported arrangement. |

### Alerting and notifications

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_NOTIFICATION_MAX_ATTEMPTS` | `5` | How many times a notification delivery is retried before it is recorded as failed. |
| `DIRIGENT_NOTIFICATION_BACKOFF` | `30s` | The delay after a notification's first failed delivery; later ones double from it. |
| `DIRIGENT_NOTIFICATION_LEASE` | `60s` | How long a claimed notification's lease is valid before another worker may take it. |
| `DIRIGENT_ALERT_BASE_URL` | unset | The externally reachable base URL, so an alert can link back to the run it is about. Set it on the **workers** too, not only the server: the alert context is built by whichever worker settles the run, so a server-only setting means every alert links to nowhere. |
| `DIRIGENT_REPORT_MAX_SIZE` | `1mb` | A run's report document larger than this is dropped with a warning in the run's log. The cap is enforced as the text is generated, so a runaway template stops at it rather than after it has built the whole document. |
| `DIRIGENT_REPORT_RENDER_TIMEOUT` | `5s` | How long a report template may take to render before it is dropped with a warning. Rendering happens on the worker that settles the run, inside the transaction that settles it. |

### Webhook intake and login

| Setting | Default | What it means |
| --- | --- | --- |
| `DIRIGENT_WEBHOOK_MAX_PAYLOAD` | `1mb` | The largest body the webhook intake will read. Reading stops one byte past it rather than buffering an unbounded body in order to measure it. |
| `DIRIGENT_WEBHOOK_INTAKE_RATE_PER_MINUTE` | `120` | How fast one *offered* token may deliver, checked before anything is looked up. A real webhook's own `rate_limit_per_minute` applies on top, which is why the default here is the looser of the two. Per process, so behind N replicas the effective limit is N times this. |
| `DIRIGENT_LOGIN_RATE_PER_MINUTE` | `10` | Login attempts allowed per minute, per address *and* per username. Argon2id is deliberately expensive and login is unauthenticated, so without a limit anyone on the network can turn a few hundred requests a second into the whole instance's CPU. |

## Database and migrations

Migrations are Alembic, and they run on both PostgreSQL and SQLite.

```bash
dg db upgrade          # migrate to head
dg db current          # which revision this database is at
dg db history          # every revision, newest first
```

**Who runs them.** Only `dg dev` migrates automatically, on every start; its starting record
names the revision it moved to, when something moved. `dg server`,
`dg worker`, and `dg scheduler` do not: they expect a schema that is already current. This is
deliberate -- scaling the server out should not mean N processes racing to migrate one schema
-- so a deployment needs a migration step of its own. In `infra/compose.yaml` that is a one-shot
`migrate` service the server and worker both depend on completing.

**When to run them.** Before starting the new version's processes, on every upgrade that ships
a new revision. `dg db current` against a database that has never been migrated says so and
tells you to run `dg db upgrade`.

**PostgreSQL versus SQLite.** The schema is one set of migrations with dialect variants where
the two genuinely differ: JSON columns are `JSONB` on PostgreSQL and `JSON` elsewhere, enums
are stored as checked `VARCHAR` by value so neither dialect needs an enum type migrated, and
timestamps go through a type decorator that normalises to UTC on the way in and re-attaches it
on the way out, because SQLite has no timezone concept and would otherwise hand back naive
datetimes to an engine that compares due times constantly.

SQLite is a real target for development, tests, and `dg dev`, not a degraded mode -- but see
[why it is refused for multi-process roles](#why-sqlite-is-refused-for-dg-worker-and-dg-scheduler).
There is no supported migration path from a SQLite instance to a PostgreSQL one.

## Backup and restore

**The database is the system of record.** Definitions, every version of them, all run history,
connections and their sealed secrets, tokens, schedules, webhooks, and log entries are all
rows. A consistent dump of the PostgreSQL database is a complete backup of everything except
artifact bytes.

```bash
pg_dump --format=custom dirigent > dirigent.dump
```

**Two things live outside it.**

- **`DIRIGENT_SECRET_KEY`.** Back it up somewhere that is *not* beside the database dump. A
  backup containing both the sealed envelopes and the key that opens them is not an encrypted
  backup. Without the key, a restored database has connections whose secrets can never be
  read, and there is no way to recover them other than re-entering the credentials.
- **The artifact store.** Whatever `DIRIGENT_ARTIFACT_ROOT` points at: a directory for
  `file://`, a bucket for `s3://`. It holds each run's scratch prefix
  (`<artifact-root>/runs/<run-id>/...`) and any step output too large to inline. Back it up
  with the tool that fits the backend -- a filesystem snapshot, or the object store's own
  versioning and replication.

**Restore** is the database, then the artifact store, then the key in the environment. Bring
the schema to head with `dg db upgrade` before starting the server, in case the backup predates
the running version.

**A note on what a restore means for in-flight work.** Because there is no in-memory scheduler
state anywhere, a restored database resumes: attempts that were `queued` are claimed again,
attempts that were `waiting` are probed again, and leases that were held by workers that
no longer exist expire and are swept. Restoring an old snapshot, however, replays work that
already happened -- a schedule whose `next_fire_at` is in the past will fire, and a step whose
outcome was not in the snapshot will run again. That is correct behaviour for a crash and
surprising behaviour for a rollback, so treat a point-in-time restore of a live instance as an
event that needs a plan, not as an undo button.

## Health checks

There are two kinds, and they answer different questions. The **HTTP probes** are what an
orchestrator outside the container asks. The **`dg health` commands** are what a container's
own `HEALTHCHECK` runs, from inside, against its own process.

### The HTTP probes

Two endpoints, both unauthenticated:

- **`GET /health`** is liveness. It touches no dependency at all and answers
  `{"status": "ok", "version": "..."}`. It says the process is running and can serve
  requests, and nothing more. Use it for a restart probe.
- **`GET /health/ready`** is readiness. It runs every registered check concurrently and returns
  the worst status across them, plus each check's own result:

```json
{"status": "healthy", "checks": {"database": {"status": "healthy", "detail": null}}}
```

  Each check reports `healthy`, `degraded`, or `unhealthy`. `degraded` still passes readiness;
  `unhealthy` answers **503**. A check that raises is turned into `unhealthy` with the
  exception's type and message as the detail, so a broken check can never take the probe down
  with it.

**What is actually checked today: the database, and only the database.** The registry is built
to grow -- the scheduler's advisory lock, the default storage backend, and a per-connection
fan-out are all intended entries -- but as of now `/health/ready` runs one `SELECT 1`. Do not
read a green readiness probe as "storage is reachable" or "the scheduler is leading".

Point your orchestrator's readiness probe at `/health/ready` and its liveness probe at
`/health`. The dependency between services should be on readiness, because a server that
cannot reach the database is not somewhere to send an apply.

Every response the server sends, error or not, carries an `X-Dirigent-Version` header. That is
what lets a client say "that is not a dirigent instance" rather than "HTTP 404" when it has
been pointed at the wrong port -- at, for instance, the documentation site on 3334.

### `dg health`

Process-side, in the sense `dg db upgrade` is: it needs no token, reads the configured
database directly, and asks a server only over plain HTTP. It writes one `check` record per
check plus a closing `health` verdict, like every other command, and exits `0` or `1`.

Bare, it answers "is my instance OK?" for **the instance this shell resolves**: the
configured database, every worker that instance has, its schedules, and the server -- the one
`DG_URL`, `--url` or the profile names, or this host's own loopback when nothing is named. On
an operator's laptop pointed at a real deployment that is the whole deployment; inside a
container it is the container's own environment. A machine with no instance at all says so in
one line rather than reporting the absence of everything, part by part:

```console
$ dg health
no database at .dirigent/state/dirigent.db [check] check=database status=absent probe=readiness
there is no instance here: no database at .dirigent/state/dirigent.db, and no server was named [health] checked=1 ...
```

And a deployment that is up reads as one:

```console
$ dg health
the database at postgresql://dirigent:***@postgres:5432/dirigent answers, schema 0001_baseline [check] ...
3 of 3 workers beating [check] check=worker status=healthy probe=readiness
2 schedules waiting, none overdue [check] check=scheduler status=healthy probe=readiness
the server at 127.0.0.1:3333 is ready [check] check=server status=healthy probe=readiness
everything checked is healthy [health] checked=4 healthy=4 absent=0 unhealthy=0
```

| Command | What it does | What that proves |
| --- | --- | --- |
| `dg health` | Every check below, for the instance this shell resolves | The instance is working, from wherever you are standing. A part that is simply not there is `absent` and does not fail the command |
| `dg health database` | Reads the alembic stamp | The database answers *and* holds the schema this code expects. A database nobody has migrated answers `SELECT 1` and has no tables; one left behind by a half-finished upgrade is missing a column. Both are `unhealthy`, with the `dg db upgrade` that fixes them. A SQLite file that is not there is `absent`, and looking does not create it |
| `dg health worker` | Reads the worker registry for this hostname and passes if a worker that claims to be alive has beaten within six heartbeats | The worker process in this container is alive, its heartbeat loop is turning, and it can still write the database -- which is a worker's only dependency. A worker opens no port, so its heartbeat is the only honest signal there is. The bare form asks the same question of every worker the instance has, because from a laptop the workers that matter are all of them |
| `dg health scheduler` | Reads the unpaused schedules and compares the earliest `next_fire_at` against the misfire grace | Schedules are firing on time. Leadership is a session-scoped advisory lock no other process can see, so what gets checked is the work: a schedule later than `DIRIGENT_SCHEDULER_MISFIRE_GRACE` means nothing is ticking, whichever process was meant to be doing it |
| `dg health server` | An HTTP `GET .../health/ready` against the named server, or `127.0.0.1:$DIRIGENT_PORT` when none is named, with a five-second timeout | The server is accepting connections *and* every registered check passes. A server that has stopped answering the socket is only visible from the socket, which is why this is a request and not a database query |

**`absent` is not `unhealthy`.** A worker that shut down cleanly wrote `stopped` and is
history, not a fault; a database file that was never created is a machine with no instance,
not a broken one. The bare form reports what is absent and fails only on what is present and
broken -- so a stopped `dg dev` instance reads as "an instance's database is here, and nothing
is running against it", exit `0`. Starting it again runs that database, unless
`--wipe-state` says otherwise. Naming a component is the assertion that it should be there:
`dg health worker` on a host with no live worker exits `1`. Point a container's `HEALTHCHECK`
at the named form, always -- `infra/compose.yaml`'s two healthchecks are `dg health server`
and `dg health worker`.

**Liveness and readiness are different questions.** `dg health server` asks readiness;
`dg health server --liveness` asks `GET /health`, which touches no dependency. A process that
answers liveness and fails readiness is up and cannot reach its database -- which is the case
anyone actually cares about, and the one a bare "is it up" cannot tell you.

`dg health worker` matches on hostname rather than on worker name, because a worker names
itself hostname-plus-pid and the check runs in a different process with a different pid.
Inside a container the hostname is the container id, and exactly one worker writes under it.
Running two workers in one container makes the check answer about whichever one is freshest.

The tolerance is six missed beats, expressed as a multiple of `DIRIGENT_HEARTBEAT`
rather than as a fixed number of seconds, so raising the heartbeat interval widens the
tolerance with it. At the default 15 seconds that is 90 seconds of silence before a worker
container is called unhealthy.

Note what none of it covers. `dg health server` inherits the readiness probe's blind spots
exactly -- a green answer means the database replied to `SELECT 1`, not that storage is
reachable. `dg health worker` says a worker is heartbeating, not that it is making progress: a
worker whose every block call is failing heartbeats perfectly. `dg health scheduler` says
schedules are not late, which on an instance with no schedules is free. For progress, watch
runs, not health.

## Process logs

One structlog chain, configured by the process entry points (`dg server`, `dg worker`,
`dg dev`, `dg scheduler`) and by nothing else -- no library module configures logging at import
time. The stdlib bridge means uvicorn, SQLAlchemy, alembic, and httpx2 records render through
the same processors as dirigent's own events and end up in the same shape.

**Where they go.** `dg dev`, `dg server`, `dg worker` and `dg scheduler` write their logs to
**stdout**, because for a process that stream is the log: NDJSON under a collector, rendered
lines at a terminal. Everything else -- the
commands a person types -- writes its logs to **stderr**, leaving stdout for the answer. There
is no log file, no rotation, and no setting that names a path: collect them the way your
runtime collects a container's output.

| Setting | Default | Effect |
| --- | --- | --- |
| `DIRIGENT_LOG_FORMAT` | the terminal decides | How a command spells its output and its logs: `console` renders coloured, aligned lines, `json` emits one record per line. Unset, a terminal renders and a pipe or a container's log gets records, the four process commands included |
| `DIRIGENT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. A CLI `-v` (INFO), `--debug` (DEBUG), or `--debug-all` (DEBUG, uncapped) wins over it |

At DEBUG, three libraries are floored at INFO -- `aiosqlite`, `asyncio`, and `httpcore2` --
because they log once per cursor operation or socket read and would bury everything else.
`dg --debug-all` lifts the floor, and sets the level, when you actually want the firehose.

**Credential-bearing paths are scrubbed.** A `POST /hooks/<token>` delivery carries its whole
credential in the URL path, and uvicorn's access log formats that path verbatim. A filter
rewrites the segment to `/hooks/{token}` before the record is emitted, keeping the line but not
the secret. The intake endpoint's own logging records `hash_token(token)[:8]` instead.

### Process logs are not run logs

Two channels, deliberately separate, and confusing them is the most common way an operator
looks in the wrong place.

| | Process logs | Run log entries |
| --- | --- | --- |
| What they are | What a process says about itself | Product telemetry the engine writes about a run |
| Where they live | stderr | The `log_entries` table |
| Who writes them | Every process, plus every bridged library | A block calling `ctx.log`, and the engine around it |
| How they are read | `docker compose logs`, your collector | `dg runs logs RUN_ID`, `GET /api/v1/runs/{id}/$logs` |
| Retained | However long your collector keeps them | `retention_logs`, or forever when it is unset |
| Who may read them | Whoever can read the host | Any authenticated principal |

Every attempt leaves a run log entry, whatever it ran. A block that logs its own account --
`shell.run` printing what the command wrote, `http.request` naming the call -- is left to it,
and an attempt whose call said nothing gets one line from the engine as it settles: `finished`
with `duration_ms` and `output_bytes`, or `failed` with `duration_ms` and the error class the
failure was given. The sentence a person reads is still on the attempt, so the line does not
repeat it. An attempt that only parked between pokes writes nothing, which is why an hour-long
sensor is one line rather than thirty-six hundred.

A block that runs a process on the worker -- `shell.run`, `docker.compose.up` and
`docker.compose.down`, `docker.build` -- puts each stream's first lines into the run log as
the process prints them, so a long command is visible working rather than silent until it
exits. The last lines follow when it ends, with a line saying how many are between the two,
and the whole of both streams is the `stdout_uri` and `stderr_uri` artifacts. `docker.run` is
the exception: a parked container's logs reach the run at each probe of it. Whatever a step
logs reaches the run itself within `log_flush_interval`, one second by default, and sooner
when it logs faster than that, so the run screen and `dg run --watch` show the lines while the
step is still running. One attempt may write `log_entries_per_attempt` of them, a thousand by
default; past that the rest are dropped and the attempt gets one warning saying so.

When a worker claims an attempt it binds `run_id`, `run_item_id`, `step`, `attempt`, `block`,
and `worker` into structlog contextvars, so every process-log line emitted underneath that
block call carries run context and can be correlated with the run. `ctx.log` entries are also
mirrored into the process log at debug level, which is what lets a terminal watching `dg dev`
see them without a second query -- but the row in `log_entries` is the copy an operator reads,
and the only one that survives.

## What to monitor

**There is no metrics endpoint.** Dirigent exposes no `/metrics`, and nothing scrapes it: the
OpenTelemetry instruments it defines are pushed to an OTLP collector when one is configured,
and are no-ops when one is not. Do not go looking for a Prometheus endpoint to point at.

So the signals below are given twice: as the API or command that exposes each one today, and
as the OTel instrument that carries it when an exporter is configured. Every instrument named
there is recorded on the worker path, so the `OTEL_*` variables have to reach the worker
containers and not only the server. See [telemetry](telemetry.md).

| Signal | Read it with | Instrument, when exporting |
| --- | --- | --- |
| Worker heartbeat freshness | `dg system workers`, whose **last seen** column is the age of each heartbeat; `--json` adds the `stale` flag, true past two minutes of silence. Inside a container, `dg health worker` | `dirigent.worker.heartbeat_age`, by `dirigent.worker`. Every sweeper reports every worker, so take the max by worker |
| Workers alive at all | `dg system info`: `workers_live`. Zero live workers means nothing will pick work up, and no probe reports it | none |
| Queue depth | Nothing exposes the count of claimable attempts. `dg runs list --status queued` is the nearest proxy -- runs that have started nothing yet -- and a growing number there with live workers means the pool is behind | `dirigent.queue.depth` |
| Work parked, not running | `dg runs show RUN_ID`, per run: attempts in `waiting`. There is no instance-wide count | `dirigent.waiting` |
| Stuck runs | An alert rule on the `run_stuck` event, raised when a running run has made no attempt progress for `DIRIGENT_STUCK_RUN` (default one hour). The same detection logs `run has not progressed` at WARNING with the run id, so a log-based alert works too. Both are done by the worker's sweeper, so neither happens with no worker running | none |
| Failed runs | `dg runs list --status failed --since 1h`, or an alert rule on `run_failed` | `dirigent.runs`, by `dirigent.run.status` |
| Step failures by block | `dg runs list` then `dg runs show`, per run | `dirigent.steps`, by `dirigent.step.status` and `dirigent.block` |
| Step and block-call duration | `dg runs report RUN_ID`; `dg runs profile RUN_ID` for where one run's wall clock went | `dirigent.step.duration`, `dirigent.block.duration` |
| Readiness | `GET /health/ready`, unauthenticated. 503 means a check reported unhealthy | none |
| Database connections | `SELECT count(*) FROM pg_stat_activity WHERE datname = 'dirigent'`, against the ceiling in [scaling workers](#scaling-workers). A pool checkout that waits past `DIRIGENT_DATABASE_POOL_TIMEOUT` raises in the process log | none |
| Alert delivery itself | `dg alerts queue`, which shows what is pending, sent, or failed. A notifier that has quietly stopped delivering is otherwise invisible, because the thing that would tell you is the notifier | none |
| Schedules firing late | `dg schedule firings PIPELINE SCHEDULE`, whose rows carry the slot each firing owed against the moment it happened. Nothing reports the backlog as a number | `dirigent.scheduler.lag`. A standby scheduler reports zero, so take the max |

**Alert rules are the closest thing to paging that exists in the product.** A rule binds an
event -- `run_failed`, `run_completed_with_errors`, `run_succeeded`, `run_stuck` -- at a scope
to a notifier, and delivery goes through a queued, leased, retried path a worker owns. If you
have one thing configured on a real instance, make it a `run_failed` rule with a throttle.

`infra/compose.otel.yaml` is a collector, Prometheus, Tempo and a Grafana with these signals
already on a dashboard; see [telemetry](telemetry.md#bring-it-up-in-an-afternoon).

**What has no signal at all**, and is worth knowing you are blind to: scheduler leadership
(nothing reports which process holds the lock), artifact-store reachability, connection health
other than by asking for it with `dg connection check` (`dg system info` repeats what the last
check said), and table growth
under an absent retention policy. The last one is the one that eventually hurts; a retention
policy is off until you set one, so see [retention](#retention).

## Why was that run slow

`dg runs profile RUN_ID` breaks one run into where its wall clock went. It walks back from the
step that finished last through whichever upstream held it up -- the chain that decided the run
-- and splits the time along it three ways: **queued** waiting for a worker, **waiting** parked
on purpose between a sensor's probes or through a retry's backoff, and **running** in a call.
Steps off that chain ran beside it and cost the run nothing.

Which of the three dominates says who to talk to:

- **Queued** is the worker pool. Attempts were claimable and nobody took them up, so the pool is
  behind: see [scaling workers](#scaling-workers), and check `dg system info` for `workers_live`
  before adding any, since zero live workers looks exactly the same from here.
- **Waiting** is the document. A sensor's `poll` and a step's `retry` decide it, and the profile
  writes a warning when a probe cadence is far longer than the work it waited on, or a deadline
  is many times the wait a sensor actually needed.
- **Running** is the work itself, or the service it calls. Nothing about the instance will make
  it shorter.

A fan-out whose elements never overlapped is warned about too: the elements ran one after
another, which is a concurrency limit or a single worker turning a fan-out back into a queue.

## Notifier channels

A rule names a **notifier** and the **connection** it delivers through, and the connection is
an ordinary credential record: minted with `dg connection create`, over `POST /connections`,
or from the web UI's *New connection* dialog, which builds its form from the kind's own
schema. Every field a channel declares secret is encrypted at rest and comes back redacted as
`***` from every read, the same as any other connection.

```bash
dg alerts rules create page-ops --event run_failed --notifier slack --connection ops-slack
```

Four channels ship built in.

| Notifier | Connection kind | What it needs |
| --- | --- | --- |
| `log` | none | Nothing. It writes the alert to the process log, which is what makes alerting work on a fresh install |
| `webhook` | `webhook` | An endpoint to POST the alert to as JSON |
| `slack` | `slack` | An incoming webhook, or a bot token and a channel |
| `email` | `email` | A submission server, a sender, and recipients |

### Webhook

One JSON POST per alert, to any endpoint that can receive one. The connection carries the
address, so a rule delivers to one endpoint per channel rather than to a URL written into the
rule.

```bash
dg connection create webhook ops-endpoint --name "Ops endpoint" \
  --set url=https://ops.example.org/hooks/dirigent \
  --set bearer_token=...
```

| Field | Default | What it means |
| --- | --- | --- |
| `url` | unset | Where the alert is POSTed |
| `bearer_token` | unset | Sent as an `Authorization: Bearer` header. Sealed |
| `headers` | none | Extra headers the receiving system wants, such as a routing key |
| `verify_tls` | `true` | Whether the certificate is verified |
| `timeout` | `15s` | How long the POST may take before the delivery is retried |

The body is the event, the subject, the alert body, the run id, the pipeline, the run's URL
where `DIRIGENT_ALERT_BASE_URL` is set, and the whole template context under `context`.

`dg connection check` sends a HEAD and reports what answered. **That proves the endpoint is
reachable, not that it accepts an alert**: only a POST proves the second, and a check that
posted would deliver a message every time somebody opened the connections screen. Prove one
with `dg alerts test webhook --connection ops-endpoint`.

### Slack

Two forms, and a connection carries exactly one. An **incoming webhook** is the quickest: the
URL names the channel, so it is the whole configuration -- and because anyone holding it can
post to that channel, it is sealed as a credential rather than stored as a setting. A **bot
token** with a channel goes through `chat.postMessage` instead, which is what you want when
one credential serves several channels, or when the workspace manages apps rather than hooks.

```bash
dg connection create slack ops-slack --name "Ops channel" \
  --set webhook_url=https://hooks.slack.com/services/T000/B000/xxxxxxxx

dg connection create slack ops-slack-bot --set bot_token=xoxb-000-xxxx --set 'channel=#ops'
```

| Field | Default | What it means |
| --- | --- | --- |
| `webhook_url` | unset | A Slack incoming webhook. Sealed: it is the address and the credential at once. Not combined with `bot_token` or `channel` |
| `bot_token` | unset | A bot token, presented to `chat.postMessage`. Sealed. Needs `channel` |
| `channel` | unset | Where the bot posts: a channel id such as `C0123456789`, or `#name` |
| `verify_tls` | `true` | Whether the certificate is verified |
| `timeout` | `15s` | How long the call may take before the delivery is retried |

The alert renders as Slack blocks -- a header carrying the subject, a section carrying the
body, a context line with the pipeline in code formatting and the event, and a button to the
run where `DIRIGENT_ALERT_BASE_URL` is set -- with the subject repeated as the plain `text`
fallback, so a notification and a screen reader still say what happened.

`dg connection check` on a bot token calls `auth.test` and reports the workspace it
authenticated to. **On a webhook it reports that it verified nothing**: Slack offers no way to
test an incoming webhook other than posting to it, and a health check that put a message in
the channel every time somebody opened the connections screen would be worse than no check.
Prove one with `dg alerts test slack --connection ops-slack`, which sends a real message
through the same queue.

### Email

One plain-text message per alert, submitted to an SMTP server.

```bash
dg connection create email ops-mail --name "Ops mailbox" \
  --set host=smtp.example.org \
  --set username=dirigent@example.org \
  --set password=... \
  --set from_address=dirigent@example.org \
  --set 'to=["oncall@example.org", "platform-lead@example.org"]'
```

| Field | Default | What it means |
| --- | --- | --- |
| `host` | unset | The submission server |
| `port` | `587` | The submission port: 587 with STARTTLS, 465 with implicit TLS |
| `security` | `starttls` | `starttls`, `tls` for implicit TLS, or `none`. A `starttls` session that is not offered STARTTLS is refused rather than sent in the clear |
| `username` | unset | The submission account, where the server asks for one |
| `password` | unset | Its password. Sealed |
| `from_address` | unset | Who the alert is from |
| `to` | unset | Who it goes to. One message is sent to all of them |
| `subject_prefix` | `[dirigent]` | Written before the subject, so a mail rule can file alerts on sight |
| `timeout` | `15s` | How long the submission may take before the delivery is retried |

The body is the subject, the alert body, and then the pipeline, the event and the run's URL,
as plain text. There is no HTML part: an alert is read in whatever is to hand, including a
pager gateway that strips everything else.

`dg connection check` connects, greets the server, and logs in where there are credentials.
It sends nothing.

**A channel that refuses raises, and the queue owns the retry.** An HTTP error, a Slack
`ok: false`, a refused submission: each is recorded on the notification, retried with backoff
up to `DIRIGENT_NOTIFICATION_MAX_ATTEMPTS`, and visible in the run's own timeline and in
`dg alerts queue`.

### Somewhere to send one

"Configured" and "arrives" are different questions, and only a delivered message answers the
second. `infra/compose.sinks.yaml` is the far end of both non-log channels on a machine of
your own: **Mailpit**, which accepts mail on 1025 and never relays it, and a **webhook sink**
that answers 200 to anything and prints what it received.

```bash
make docker-run-sinks
```

Mailpit's web UI and JSON API are on `http://127.0.0.1:8025`; the sink is on
`http://127.0.0.1:8099`. Neither SMTP nor the sink's own port is published to the host: the
stack reaches both by service name, which is the address the server and worker containers
resolve.

```bash
dg connection create email ops-mail \
  --set host=mailpit --set port=1025 --set security=none \
  --set from_address=dirigent@example.org --set 'to=["oncall@example.org"]'

dg connection create webhook ops-webhook --set url=http://webhook-sink:8080/alerts

dg alerts test email --connection ops-mail
dg alerts test webhook --connection ops-webhook
```

Then read what arrived. Mailpit holds the message and answers for it:

```bash
curl -s http://127.0.0.1:8025/api/v1/messages | jq '.messages[0].Subject'
```

The sink keeps nothing, so its receipt is its own log:

```bash
docker compose --project-directory . -f infra/compose.yaml \
  -f infra/compose.sinks.yaml logs webhook-sink
```

Slack has no local stand-in -- there is no Slack to run on a laptop -- so the way to prove
that channel is a real workspace and a real message. What a bad credential proves is the
other half: `dg alerts test slack --connection ...` against a token Slack refuses records the
refusal on the notification, which is where a real one would be too.

## Retention

Every table a run touches grows with use, and the artifact root accumulates one prefix per
run. **Nothing is pruned until you say how long to keep it**: each family has its own age,
and a family with no age is never swept. That is deliberate -- an orchestrator that quietly
deleted the record of what it ran would be worse than one that fills a disk -- but it does
mean an instance running at a real cadence needs a policy.

| Setting | What it bounds |
| --- | --- |
| `retention_runs` | Settled runs, and by cascade their items, attempts, artifact refs and alerts |
| `retention_logs` | Log entries, for runs too young to be pruned themselves |
| `retention_deliveries` | What arrived at a webhook |
| `retention_firings` | When a schedule fired |
| `retention_notifications` | Alerts already sent |
| `retention_scratch` | Whether a pruned run's artifacts are deleted from storage too |

Ages are humane durations -- `30d`, `12h`, `90m`. A starting point for an instance that runs
often, where logs are the bulk of the growth and the run record is worth keeping longer:

```bash
DIRIGENT_RETENTION_RUNS=90d
DIRIGENT_RETENTION_LOGS=14d
DIRIGENT_RETENTION_DELIVERIES=30d
DIRIGENT_RETENTION_FIRINGS=30d
DIRIGENT_RETENTION_NOTIFICATIONS=30d
```

**A run is only pruned once it has settled.** A run with no `finished_at` is either still
running or is the evidence of something that went wrong, and neither is deleted on an age.

**Pruning a run takes what the database cascades from it** -- its items, attempts, artifact
refs and notifications go in the same statement. A shorter `retention_logs` is therefore a
trim of the runs you are still keeping, not the only thing that deletes a log entry.

**Artifacts go before rows.** A run's scratch prefix is deleted first, and only then its row:
a row deleted first would leave bytes nothing points at and nothing would ever find again. If
storage refuses -- a read-only volume, an expired credential -- that run is left whole, rows
and all, and tried again on the next sweep. Set `retention_scratch=false` where something
else owns the bucket's lifecycle, such as an S3 expiry rule.

### The sweep

The scheduler sweeps every `retention_interval` (default `1h`). It runs there rather than on
a worker because the scheduler is the process there is exactly one of -- every worker sweeping
would have them deleting each other's batches. Deletion is batched at `retention_batch` rows
(default 500) with a commit per batch, so a year's backlog is many short transactions rather
than one that holds locks for minutes, and an interrupted sweep has still made progress.

### Pruning by hand

`dg prune` runs the same sweep directly against the configured database, which is how you
work off a backlog before setting a policy, or prune an instance that runs no scheduler:

```bash
dg prune --runs 90d --logs 14d --dry-run   # what would go
dg prune --runs 90d --logs 14d             # what went
```

An age given on the command line beats the configured one, and a family with neither is not
pruned -- the command never guesses at an age. It writes a `prune` record like everything
else, so `--dry-run` output can be read by `jq` as easily as by a person:

```bash
dg prune --runs 90d --dry-run | jq '.runs'
```

Run it against the database, not the API: `dg prune` reads `DIRIGENT_DATABASE_URL` and needs
no server. In the compose stack that means `docker compose exec worker dg prune ...`.

## Upgrading

1. **Read the [release notes](releases.md)** for schema changes and for anything in the block catalog. Block
   ids are public API and are not renamed, but a new version may add blocks, and a plugin
   package may need updating in step.
2. **Back up the database**, and confirm you have `DIRIGENT_SECRET_KEY` recorded somewhere
   other than that backup.
3. **Stop the writers, or accept a rolling window.** There is no online-migration guarantee, so
   the safe order is: stop workers and the scheduler, migrate, start everything on the new
   version. A worker draining on SIGTERM finishes the calls it is holding before it exits.
4. **Migrate**: `dg db upgrade`, from one process. Confirm with `dg db current`.
5. **Start the new version**, servers first, then workers.
6. **Check.** `GET /health/ready` should be `healthy`; `dg system workers` should show the
   registry filling with the new version, the expected plugin list, and `code_matches_server`
   true on every row; `dg runs list --status failed --since 1h` should be quiet.

Keep every process on the same version. The worker registry records each worker's version,
installed plugins, and catalog digest precisely so that a straggler is visible rather than
mysterious. Old rows do not linger: the sweeper deletes any whose heartbeat is older than
`DIRIGENT_STALE_WORKER`, so a listing after an upgrade settles to what is actually
running.

## Known debt

What you should know before you run this in anger. These are verified against the code, not a
guess at what might be missing.

**No queryable audit trail.** Every run points at what started it, which is real attribution.
Administrative actions -- who created a connection, who revoked a token, who deleted a pipeline
-- are in the process log and nowhere else.

**Health checks cover the database only.** See [health checks](#health-checks). A green
readiness probe does not mean storage is reachable, that the scheduler holds leadership, or
that any connection works.

**No key rotation.** Changing `DIRIGENT_SECRET_KEY` makes every existing envelope unopenable.
See [security](security.md#rotation-honestly).

**Three instance-wide roles.** Admin, operator, viewer, and nothing finer: the role applies to
the whole instance, so any operator can run any pipeline and read any run.
See [security](security.md#what-authorizes).

**Rate limiter buckets are per process.** Both the webhook intake limit and the login limit
live in process memory, so behind N API replicas the effective limit is N times the configured
one. This is a deliberate trade -- the alternative is a database write per refusal, which is
what a caller hammering the endpoint would be trying to cause -- but size your limits knowing
it.

The living version of this list is [ROADMAP.md](https://github.com/winterop-com/dirigent/blob/main/ROADMAP.md)
in the repository, which also carries the open design questions.
