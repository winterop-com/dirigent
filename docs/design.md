# Design

This is the in-repo specification for dirigent, distilled from the design blueprint. It is
authoritative for what the code should do; where the code disagrees with this document, one
of the two is a bug.

## 1. Product shape

Dirigent is a standalone product: an engine, an API, and a UI for building and operating
pipelines. It should be equally at home moving parquet files from S3 through a transform
into some HTTP service as running a health-modelling workflow, because it knows neither
domain. Everything domain-specific enters through plugins.

The mental model borrows the best noun from Airflow and rejects its authoring model:

- **Operators do work.** Call an HTTP API, run a transform, copy between storage backends,
  submit a remote job. An operator either finishes synchronously with an output, or returns
  a remote handle for the engine to probe.
- **Sensors wait for the world.** A file appearing under a storage URI, an endpoint
  reporting ready, a time window opening. Sensors never block a worker: each poke is a
  scheduled, durable poll.
- **Pipelines compose blocks into a DAG** in the UI, stored as data, validated against the
  blocks' published schemas. No Python files to deploy, no drift between "the code" and
  "what runs".

The async submit-then-probe pattern is not an integration detail, it is the engine's core
primitive, because nearly every interesting external system works that way: publish a job,
then probe until it is ready. Each adapter tells the engine how its system probes; the
engine owns when, and what happens on timeout, loss, or failure.

## 2. The five plugin surfaces

One plugin mechanism (pluginkit, with entry-point discovery) serves five surfaces. A plugin
package may contribute to any or all of them. Every contribution publishes Pydantic models,
which the server converts to JSON Schema and serves as a catalog; that catalog is what the
UI renders as forms, so a newly installed plugin surfaces in the pipeline builder with zero
frontend changes.

| Surface | Contract | Built-in examples |
| --- | --- | --- |
| Operators | `spec` (id, group, config/output schemas, idempotency flag) plus `async execute(config, ctx) -> Output \| RemoteHandle`; optional `probe` / `fetch` / `cancel` for async systems | `http.request`, `storage.copy`, `pipeline.run`, `webhook.post`, `shell.run`, `docker.run` |
| Sensors | `spec` plus `async poke(config, ctx) -> Output \| NotYet`; the engine owns interval, deadline, and timeout outcome | `storage.exists`, `http.ready`, `time.window` |
| Storage backends | Scheme registration plus `open_read` / `open_write` / `stat` / `list` / `delete` over URIs, streamed | `file://` in core, `s3://` as the first backend package |
| Notifiers | `config_model` plus `async send(message, config)` | `log`, `webhook`; Slack and email as packages |
| Connection kinds | `config_model` (secret fields marked) plus `async check(config) -> HealthReport` | generic HTTP connection |

Every block an instance actually has, with the config it takes and the output it produces, is
in [the block reference](blocks.md) -- generated from that same catalog, so it cannot drift
from the code.

A block declares the **group** it shelves under, and that is what a catalog is arranged by:
the add-step menu's submenus and the blocks screen's sections are the groups, not the halves
of an id. A spec that names no group takes the id's first half, so a plugin gets a sensible
shelf without saying anything. The built-in pack spends the declaration where the id alone
would mislead: `transform.jq`, `map.jq`, `filter.jq` and `convert.std` are four verbs of one
group, `transform`, and `shell.run`, `docker.run` and `pipeline.run` are `execute`.

pluginkit's role is deliberately narrow: discovery, registration, validation, and lifecycle,
through one synchronous collecting hook, `contribute()`, called once at startup. Everything
at runtime bypasses it. The host builds a block-id index from the contributions and calls
operator and sensor methods directly, gathers health checks itself, and reads config models
straight off the contributed objects.

An "adapter" is nothing special: it is a plugin package contributing a connection kind plus
a family of operators and sensors for one external system. The core never learns the name of
any external product.

### Block semantics, precisely

These definitions are the part that must be right the first time, because pipelines stored
as data reference them forever.

**An operator does work; it changes the world.** `execute` is called at most once per
attempt (a retry is a new attempt, never a re-entry), should submit at most one unit of
remote work, and must never poll inside itself; returning a `RemoteHandle` is how it says
"this continues elsewhere". `probe` must be side-effect-free and safely callable any number
of times from any worker, and must map the remote system's vocabulary honestly, including
"the remote no longer knows this job" as `GONE`. `fetch` runs after a successful probe and is
the place for expensive result retrieval; it is **at-least-once**, because the only thing that
ends an attempt is the transaction recording its outcome, so a worker that dies between
fetching and that commit leaves the attempt to be probed and fetched again -- retrieve a
result, never consume one. A probe may return `meta`, which becomes the handle every later
probe and the eventual fetch receives, so an adapter streaming a remote system's log into the
run has somewhere to record how far it has read; it replaces the handle's metadata rather
than merging into it, and it is **at-least-once** for the same reason `fetch` is, since the
cursor is written by the transaction that parks the attempt -- a probe must tolerate reading
the same ground twice, and the lines it appends may repeat. `cancel` is best-effort and
idempotent. A synchronous operator is simply one whose `execute` always returns an
output: same class, no separate concept.

**A sensor observes the world; it changes nothing.** `poke` is read-only, short (seconds,
never sleeps), and callable an unlimited number of times. Its success value is the
order itself, passed downstream like any output. A poke that raises is an error
(subject to the step's retry policy); returning `NotYet` is not an error and consumes no
retry budget. `NotYet` may carry a `message` and a `progress` like a probe's result, and the
engine keeps the latest of each on the waiting attempt and logs the message when it changes.
It may also carry a `cursor`, an arbitrary JSON map the next poke receives as `ctx.cursor`,
which is where a sensor writes down how far it has read: an offset, a watermark, a last-seen
id. It replaces rather than merges, and it lives only as long as the waiting attempt, because
a poke that succeeds ends the step. Advancing it is at-least-once, exactly as a probe's handle
metadata is: the cursor is written by the transaction that parks the attempt, so a worker that
dies before that commit leaves the older cursor for the next poke, and a poke must tolerate
reading the same ground twice.
Sensors carry their own deadline, and the timeout outcome is configuration:
`on_timeout: fail | skip`. The skip option is load-bearing, because `skipped` is a
first-class terminal state that downstream trigger rules can see.

**Why sensors and async operators stay two concepts on one mechanism.** Both park as
`waiting` and both are probed by whichever worker is free, so the machinery is
identical. The semantics are not: an operator's probe tracks work this run submitted (there
is a handle, failure means the work failed, cancellation can reach the remote), while a
sensor waits for a condition nobody in the run caused (there is no handle, timeout is an
expected outcome, cancellation is purely local). Collapsing them produces optional handles
and conditional timeout semantics threaded through the engine forever.

**A transform is a verb contract with a pluggable engine.** Reshaping data is one operator
shape common enough to deserve a frame rather than a family of unrelated blocks, so a
transform block's id is `<verb>.<kind>`: the verb is the contract and its semantic promise
(`transform` reshapes a whole value, `convert` re-encodes it x to y, `map` is element-wise
and length-preserving, `filter` returns a subset with elements unmodified), and the kind is
the engine that keeps it. The frame owns what every engine shares -- input as an inline value
or a storage URI, the same size bound `http.request` uses, output inlined or streamed to
`save_to`, and an apply-time check -- and an engine supplies only compiling and applying a
program, or declaring and running a codec. Safety is per kind through the gates that already
exist: an engine that evaluates a program without executing code needs no allowlist entry,
while one that runs a language runtime declares `local_execution` and goes behind
`enabled_unsafe_blocks` like `shell.run`. [The transform page](transforms.md) has the whole
of it.

**Storage backends and notifiers are not steps.** Storage is invoked by blocks through
`ctx.storage`; when data movement itself is a pipeline step, that is the `storage.copy`
operator. Notifiers are invoked by alert rules as engine-owned, queued, retried work; when a
notification is genuinely part of a pipeline, that is the `webhook.post` operator on an edge.

**Naming rules.** Operators and sensors share one flat id namespace, and a document never
declares which kind a step is -- it names a block and the engine looks it up. The id is
therefore the only thing that tells a reader whether a step does something or waits for
something, so the two kinds are named differently: **a sensor reads as a condition**
(`storage.exists`, `http.ready`, `time.window`) and **an operator reads as an action**
(`storage.copy`, `http.request`, `shell.run`, `docker.run`, `webhook.post`). An adapter pack
that ignores this makes every document that uses it harder to read, because a step's kind
then has to be looked up in the catalog rather than read off the page. The prefix before the
dot names the system or the surface (`http`, `storage`, `docker`, `acme`), and the segment
after it is the verb or the condition.

**Stability rules.** Block ids are public API: stored pipelines reference them as strings, so
renaming one is a breaking change, and deprecation happens by catalog alias, never by rename.
Config models evolve additively (new fields optional with defaults). Output models are
contracts consumed by downstream parameter references, so removing or retyping a field is
breaking. Anything that cannot follow those rules is a new block id under the next
entry-point group version.

### The contract in code

`dirigent-plugin` is the contract package: small, stable, and the only dirigent package a
third-party block imports. Blocks are generic over two Pydantic models, their config and
their output, using PEP 695 generics.

```python
class ErrorClass(StrEnum):
    TRANSIENT = "transient"  # network, 5xx, timeout: retryable
    REJECTED = "rejected"  # validation, auth, 4xx: never retried
    UNKNOWN = "unknown"  # anything else: retried while the step has budget


class RemoteHandle(BaseModel):
    """Serializable claim on a job submitted to an external system."""

    model_config = ConfigDict(frozen=True)

    block_id: str
    ref: str  # the remote system's own job identifier
    meta: dict[str, str] = Field(default_factory=dict)


class Operator[ConfigT: BaseModel, OutputT: BaseModel](ABC):
    """One unit of work: finish synchronously, or return a RemoteHandle to probe."""

    spec: ClassVar[OperatorSpec]
    config_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, config: ConfigT, ctx: StepContext) -> OutputT | RemoteHandle: ...

    async def probe(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> ProbeResult: ...
    async def fetch(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> OutputT: ...
    async def cancel(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> bool: ...

    def classify_error(self, error: Exception) -> ErrorClass:
        return classify_default(error)


class Sensor[ConfigT: BaseModel, OutputT: BaseModel](ABC):
    """Waits for the world. Each poke is one durable, scheduled probe; it must never block."""

    spec: ClassVar[SensorSpec]  # id, summary, group, default_poll, default_deadline

    @abstractmethod
    async def poke(self, config: ConfigT, ctx: StepContext) -> OutputT | NotYet: ...
```

Every block also has a `check_config(config) -> list[str]`, defaulting to no issues. It is
where a block makes the refusals its published JSON Schema cannot express -- a program that
does not compile, a format pair it has no codec for -- and it runs at apply, against the
step's validated config, with each string reported at that step's config location. A config
still carrying a `${...}` is not known yet and is left to the run.

`StepContext` is the engine's side of the bargain: scoped, audited access to everything a
block may touch, so blocks hold no global state and never construct their own clients. It
carries `run_id`, `attempt`, `started_at`, `cursor`, resolved `params`, a scoped `log`,
`connection(ref, model)`, `http(ref)`, `storage`, `scratch`, and `runs`. `started_at` is
when the attempt first started, unchanged by a later poke or a worker restart, so a wait
measures itself from the attempt rather than from the poke that happens to observe it. `connection` is synchronous by contract, so
the claim transaction snapshots the connection table for the attempt and secrets are opened
here, on the worker path, and nowhere else. `log` entries are buffered and written in the
same commit that records the attempt's outcome, so logs and outcome can never disagree.
An attempt whose call wrote nothing of its own is not silent either: the engine writes one
line as it settles -- `finished` with `duration_ms` and `output_bytes`, or `failed` with
`duration_ms` and the error class -- so a run of nothing but engine-side transforms reads
like a run of shell steps. A block that kept its own account keeps it, and an attempt that
only parked writes nothing at all, which is what keeps a sensor poked once a second from
filling the run with a line per poke.

`runs` is the newest member and the only one that reaches back into the instance itself:

```python
class Runs(Protocol):
    """Scoped access to this instance's own runs, for a block that composes pipelines."""

    async def start(self, pipeline: str, params: Mapping[str, JsonValue], *, max_depth: int) -> StartedRun: ...
    async def snapshot(self, run_id: RunId) -> RunSnapshot | None: ...
    async def cancel(self, run_id: RunId, *, reason: str) -> bool: ...
```

It exists because `pipeline.run` needs exactly three things and no more, and because the
alternative was worse: a block calling its own instance over HTTP would need a credential to
it, which is a credential in a document or a bootstrapping problem in every deployment. Three
methods on the context is a smaller surface than an API token that can do everything.

The engine's implementation goes through the same `create_run` and `cancel_run` the API and
the scheduler go through, in one of two transaction shapes. `execute` and `probe` run outside
any transaction, so the facade opens and commits its own -- a child run that is not committed
is a child run no worker will ever see. Cancellation runs inside one, so the facade joins it,
and a parent and the child it was waiting on settle together or not at all.

Every run started this way is attributed with the `pipeline` trigger kind and the id of the
run whose step started it, which makes the chain a foreign key rather than a counter kept on
the side. The depth guard reads that chain, so it cannot disagree with the runs it describes.

A plugin package assembles its blocks into one `Contribution` and exposes it through the
`dirigent.plugins.v1` entry-point group:

```python
class AcmePlugin:
    @extension
    def contribute(self) -> Contribution:
        return Contribution(
            api_version=1,
            connection_kinds=[AcmeConnectionKind()],
            operators=[AcmeOrdersOperator(), AcmeSitesOperator()],
        )


plugin = AcmePlugin()

# [project.entry-points."dirigent.plugins.v1"]
# acme = "dirigent_acme:plugin"
```

## 3. Stack and workspace

Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, httpx2 (the
Pydantic-stewarded continuation of httpx) outbound, cronsim for cron parsing, Typer plus
rich for the CLI, structlog for process logs, pydantic-settings with YAML-plus-env
layering. Frontend: Bun, Vite, React 19, TypeScript, Tailwind v4,
shadcn, built into the server wheel and served same-origin. Tooling: uv, ruff, mypy and
pyright strict, pytest with asyncio-auto and httpx2's own MockTransport, mkdocs-material.

**Databases.** PostgreSQL 17 (asyncpg) is the production database; SQLite (aiosqlite) is
first-class for tests and single-process local runs, not a degraded afterthought but not
pretending to be Postgres either. The engine touches three Postgres-isms, each with a clean
SQLite fallback that is only valid when exactly one process exists: `FOR UPDATE SKIP LOCKED`
claims become a plain single-writer claim transaction, advisory-lock leadership becomes a
no-op, and JSONB becomes SQLite JSON. The guardrail is enforced, not documented: on SQLite
only the all-in-one standalone mode starts, and separate worker or scheduler processes
refuse. Migrations run on both dialects.

**Platforms.** Linux and macOS first-class; Windows is not a target. `dg dev` on SQLite must
work natively on a Mac with no Docker.

The workspace:

```text
dirigent/
  pyproject.toml           # workspace root: shared ruff/mypy/pytest config, no [project]
  packages/
    dirigent-common/       # value types and shared schemas; depends on nothing of dirigent's
    dirigent-plugin/       # the block contract: markers, specs, base models (tiny, stable)
    dirigent-client/       # the API contract: wire schemas, and the async Python SDK
    dirigent-core/         # engine: schema, queue, DAG walker, scheduler, plugin host
    dirigent-blocks/       # built-in generic operators and sensors
    dirigent-server/       # FastAPI app, auth, SSE, webhook endpoints
      frontend/            # the web UI, built into the server wheel
    dirigent-cli/          # `dirigent` / `dg`
    dirigent-storage-s3/   # the s3:// storage backend package
    dirigent-parquet/      # the format pack: convert.arrow on pyarrow
    dirigent-testing/      # test doubles and pytest fixtures for writing blocks
```

Two of these are contracts, and both must stay small and stable because other people write
against them. `dirigent-plugin` is what a third-party block package imports. `dirigent-client`
is what a program driving an instance imports, and it owns the pydantic schema of every
request and response the REST API speaks: the server imports them from there rather than
declaring its own, so a shape has exactly one definition and the two cannot drift. It depends
on `dirigent-plugin`, `httpx2`, and `pydantic`, and on nothing else in the workspace, so
installing the SDK does not install the engine. Everything else can churn.

**Package taxonomy.** Distribution names say what a package contributes, so `pip list` reads as
an inventory of what an instance can do:

| Prefix | Contributes | Example |
| --- | --- | --- |
| `dirigent-block-*` | Operators and sensors that need no credential of their own | `dirigent-block-parquet` |
| `dirigent-storage-*` | A storage backend, registering a URI scheme | `dirigent-storage-s3` |
| `dirigent-notify-*` | A notifier channel | `dirigent-notify-slack` |
| `dirigent-<system>` | An adapter pack: one connection kind plus the blocks for one external system | `dirigent-acme` |
| `dirigent-<format>` | A format pack: a codec whose dependency the standard library does not carry | `dirigent-parquet` |

The two contract packages sit outside that scheme, because neither contributes anything to an
instance: `dirigent-plugin` is what a block author writes against, and `dirigent-client` is
what a program driving an instance writes against.

The built-in blocks ship as one `dirigent-blocks` package for now, because five generic blocks
split four ways is packaging for its own sake. The split into families happens after M5, when
there is enough to split and the families are load-bearing rather than aspirational.

**One protocol note.** `ByteSink` is the write end of a storage stream: `async write(data) ->
int`, and nothing else. It is deliberately not a file object, because a backend that has to
implement `seek`, `tell`, and `truncate` to satisfy a protocol is a backend nobody writes. A
write becomes visible only when it finishes -- the local backend stages beside the target and
renames on close -- so a reader never sees a half-written object.

## 4. Architecture

Three process roles from one codebase and one image: the **API server** (REST, UI, SSE,
webhook intake), the **scheduler** (leader-elected by a Postgres advisory lock), and
**N workers**. All coordination is PostgreSQL; all integration traffic is outbound through
plugin blocks. Inbound is only the API surface itself, including webhook intake, which does
nothing but validate, map, and enqueue.

Deployment shapes, all correct because leadership is an advisory lock and all coordination is
the database:

- **Local / evaluation.** One process, zero dependencies: `dg dev` runs API, UI, scheduler,
  and worker in a single asyncio process on SQLite. Its state is `.dirigent/state`, kept
  between starts and migrated forward; `dg dev --wipe-state` empties it first, for a checkout
  whose baseline migration moved in place. Only a directory dirigent named itself goes.
- **Typical production.** Three services: Postgres, `dg server` (API plus embedded
  scheduler), and one `dg worker` -- which is what `infra/compose.yaml` at the repository root is.
  The scheduler is embedded by default because needing a fourth service just to get a clock
  is a poor default, and because leadership being an advisory lock means embedding it costs
  nothing when it later moves out.
- **Scaled out.** More `dg worker` replicas scale execution linearly; `dg server
  --no-scheduler` plus a dedicated `dg scheduler` isolates scheduling. Two schedulers by
  mistake is harmless, because the second blocks on the advisory lock.
- **Multi-node.** A worker's only inbound dependency is Postgres, so `dg worker` on another
  machine joins the pool the moment it can reach the database. No inter-node protocol, no
  open ports on workers, no membership system.

Multi-node requires four things, worth knowing before you need them: code parity enforced by
a worker-registry handshake (nothing is pickled or shipped over the wire); shared storage, so
artifacts live on a backend every node reaches; secrets key distribution, because workers
decrypt connection credentials; and routing by tags rather than topology
(`dg worker --tag docker`, a document declaring `requires.workers`, the claim query filtering).

**Telemetry** has two deliberately separate channels. Product telemetry is the `log_entries`
table and run timings: operator-facing, queryable, rendered in the UI. `retention_logs` is
what bounds it, and nothing is pruned until an age is set.
Process logs go through one structlog chain configured in `dirigent-core`: shared processors
(contextvars merge, level, ISO-UTC timestamp), a console or JSON renderer chosen by
`log_format`, and the stdlib `ProcessorFormatter` bridge so uvicorn, SQLAlchemy, and httpx
records render identically. Only process entry points (`dg server`, `dg worker`, `dg dev`,
`dg scheduler`) call `configure_logging`; no library module configures logging at import
time. The worker binds `run_id`, `run_item_id`, `step`, `attempt`, and `worker` into
structlog contextvars when it claims an attempt, so every line under a block call carries run
context, and `ctx.log` entries are mirrored to the process log at debug level so a terminal
watching `dg dev` sees them.

What a run's own log *keeps* is the run's decision, block by block. A block logs at a level
through `ctx.log` and stays unaware of any policy; the run carries a map of block-id pattern
to level (`{"*": "debug"}`, `{"acme.*": "debug"}`), the most specific matching pattern wins,
and an entry below the kept level is dropped where it is recorded. A run that asks for
nothing keeps info and up, so debug is something a run asks for -- `dg run NAME --log-level
debug`, the same flag on `dg schedule create` for the pipeline that only misbehaves at 3am
(the schedule copies its map onto every run it fires, backfills included), and the run
dialog's log control are three front-ends to that one field on the run.

OpenTelemetry is designed in from M1 but off by default: a span
per HTTP request, a span per step attempt, and a child span per block call underneath it --
each submit, probe, fetch, and cancel -- plus counters for runs and steps by terminal status,
duration histograms for a step attempt and a block call, and observable gauges for queue
depth, `waiting`, and a worker's in-flight calls. The exact surface, and which
processes actually export it, is on [the telemetry page](telemetry.md).

"Off by default" is precise rather than aspirational. `opentelemetry-api` is always installed
and always imported; without an SDK its providers are the API's own no-ops, so `dg dev` pays a
function call per span and nothing else. The SDK is wired up only when the standard `OTEL_*`
environment says where to send data, which makes turning telemetry on a deployment decision and
never a code change, and the OTLP exporter is an optional extra (`dirigent-core[otlp]`) so the
package that speaks the wire protocol is not in the base install. A run records the trace id it
was created under, so the UI can deep-link one run to whatever collector is running; with no
exporter there is no trace to link to and the column stays null rather than holding an all-zero
id. The two levels an operator watches -- queue depth and `waiting` count -- are sampled
on the sweeper's cadence rather than on the claim path, because the claim query is the engine's
hot path and telemetry has no business adding a count to it. Telemetry failing to configure is
a warning, never a failed start.

## 5. Data model

Three clusters, with the boundary visible in the schema layout itself. All timestamps are
`timestamptz`.

- **Definitions are documents.** Each pipeline version is one immutable JSONB value, the
  serialized Pydantic definition model that the API, the YAML format, and the engine share.
  Definitions are read and written whole, so normalizing steps and edges into their own
  tables would buy nothing and cost a mapping layer plus painful versioning; a new version is
  simply a new row.
- **Execution state is relational.** Runs, items, attempts, leases, `next_poll_at`,
  `next_fire_at`: everything the engine claims and filters by lives in indexed columns,
  because the claim query is the hot path.
- **Not files on disk.** A DAG folder would reintroduce exactly the failure classes this
  design excludes: no atomic edits, no transaction linking a definition to the runs created
  from it, replica synchronization, no audit trail.

| Entity | Cluster | Highlights |
| --- | --- | --- |
| `Connection` | definition | A coded credential record of some plugin-provided kind: settings, secrets encrypted at rest, health-checkable. Used by block configs, storage backends, and notifiers alike. |
| `Pipeline` | definition | A code plus immutable versions. Edits insert a new version; runs pin the version they started from, which is what makes run snapshots free. |
| `Step` | definition | Lives inside the pipeline document, not in a table: block reference, config, `depends_on` edges plus trigger rule, retry policy, timeout, optional fan-out expression. Only attempts get rows. |
| `Trigger` | triggers | Ad hoc is implicit; persisted triggers are schedules (cron / interval / one-time, own timezone, own parameters, precomputed `next_fire_at`) and webhooks (token hash, optional HMAC secret, payload-to-parameter mapping). |
| `Run` | execution | Pinned pipeline version, resolved parameters, `triggered_by` as a real reference, a `priority` pinned at creation, and an optional half-open `[window_start, window_end)` naming the logical interval the run covers. Terminal states include `completed_with_errors`. |
| `RunItem` | execution | First-class fan-out: one row per mapped item with its own status and failing-step pointer, so a run over N inputs reads as a grid. |
| `StepAttempt` | execution | One row per attempt: number, kind (automatic / manual), input, output reference, error, remote handle, lease, `available_at`, `next_poll_at`, timings. |
| `ArtifactRef` | execution | The durable record of a step output: content type, size, digest, and either an inlined value or a URI into pluggable storage, never a worker-local path. |
| `AlertRule` | definition | Event, scope (global or pipeline), notifier connection, message template, throttle. |
| `LogEntry` | execution | Append-only, scoped run / item / attempt, batched writes. Bounded by `retention_logs`, which is unset by default. |
| `Worker` | execution | The registry: hostname, version, installed plugins, tags, last seen. Doubles as observability. |

The one migration there is (`0001_baseline`) creates every table and runs on both
PostgreSQL and SQLite. JSON columns are `JSONB` on PostgreSQL and `JSON` elsewhere, declared
once as a dialect variant; enums are stored as checked `VARCHAR` by value, so both dialects
agree and no enum type needs migrating. Timestamps go through a type decorator that
normalises to UTC on the way in and re-attaches it on the way out, because SQLite has no
timezone concept and would otherwise hand back naive datetimes for a schema whose engine
compares due times constantly.

## 6. Execution engine

The engine is two kinds of asyncio loop and a set of tables, and deliberately nothing else.
The foundational rule: **no in-memory scheduler state anywhere.** Every run, step, attempt,
lease, and due-time is a row, so any process can be killed at any moment and the system
resumes from the database. Two invariants carry everything:

1. **One transaction per state transition.** Claiming, recording an outcome, and readying
   dependents are one commit. No broker, so no outbox, no reconciliation bugs.
2. **Readiness as a SQL condition.** A step is claimable when its `depends_on` edges satisfy
   its trigger rule; the "DAG walker" is the last statement of the outcome transaction, not a
   component.

**The scheduler is time, and only time.** It takes `pg_advisory_lock` at startup; whoever
holds the lock is the leader and replicas simply block on it. Each tick selects schedules
with `next_fire_at <= now()` (with `FOR UPDATE SKIP LOCKED`) and, per schedule in a single
transaction, checks the pipeline's concurrency policy, inserts the run and its step-attempt
rows, and writes the next `next_fire_at` computed in the schedule's own timezone. Because
firing and advancing commit together, a crash can neither double-fire nor skip. Ad hoc runs
and webhooks perform the same insert through the API.

**Workers are one claim query.** Each worker loops around a single query that pulls the next
due unit of work (a `queued` attempt whose dependencies are satisfied and whose
`available_at` has passed, or a `waiting` attempt whose `next_poll_at` has passed)
with `FOR UPDATE SKIP LOCKED`, so N workers never collide and need no dispatcher. The claimed
block coroutine runs under a per-worker semaphore. Remote waits cost rows, not coroutines: a
thousand in-flight remote jobs are a thousand `waiting` rows probed as they come due.

Readiness is decided by the outcome transaction that queues an attempt, never by the claim
query, so claiming is a plain indexed lookup rather than a graph walk. The claim also
resolves the step's references against stored upstream outputs and writes the resolved
input. Two ordering rules keep concurrent workers honest: the outcome transaction locks the
run row before it writes anything, so the run's status is derived once rather than by two
workers each seeing the other as still in flight; and because that lock comes before any
write, no transaction ever has to upgrade a share lock it already took through a foreign
key, which is how a pair of workers finishing at once would otherwise deadlock. The claim
also routes: a document declares `requires.workers`, the run pins that list at creation, and
a worker claims only what its own tags cover -- `jsonb` containment on PostgreSQL, a
`json_each` walk on SQLite. A run requiring nothing is claimable by anyone.

**The claim's order is priority, then fairness, then due time.** A run pins a `priority` --
`low`, `normal` or `high` -- resolved at creation from the document, the trigger that fired
it, or the ad hoc request, so a later edit never reorders a run in flight. Fairness is
round-robin between runs: every attempt of a run still in flight is numbered within that run
by due time (`ROW_NUMBER() OVER (PARTITION BY run_id ...)` in a subquery that computes the
ranking and nothing else), and the claim orders by priority rank descending, then
that number, then the due time, then the id. The number counts the attempts already taken, so
a run that has been served falls behind one that has not; numbering only the due rows would
renumber from one after every claim and leave the order exactly as it was. A four-hundred-item
fan-out and a two-step run therefore interleave one attempt at a time rather than the big one
holding every slot until it drains, and a `high` run's attempts are claimed before any
other's the moment a slot frees. Nothing is preempted and no slot is reserved: an attempt
already running is never cancelled for priority, because that means killing work with side
effects nobody can take back.

Every predicate that decides claimability -- the status and due-time test, the run's own
status, the tag routing -- is written on the locked `step_attempts` relation in the outer
select, and the subquery ranks. This is not tidiness: when `SKIP LOCKED` waits out a
concurrent commit it re-checks the row's new version against the outer query's predicates
alone, so a status test living only in the subquery is never re-evaluated and two workers
walk away with the same attempt.

**The step-attempt state machine.**

```text
queued --claim--> running --submit--> waiting --terminal probe--> succeeded
   ^                  |                     |                            failed
   |                  |                     |                            skipped
   +---- retry with backoff (new attempt row, available_at = now + backoff) ----+
```

Operators that finish synchronously skip `waiting` entirely; async operators and all
sensors live in it. Waiting is durable data with a due time, which is why restarts are safe.

**Crash recovery: leases and the submit window.** A claimed attempt holds a lease, a
heartbeat timestamp the worker refreshes while executing. If a worker dies mid-call, the
lease expires and a sweeper reclaims the attempt. Recovery depends on where death struck: if
the `RemoteHandle` was already committed, recovery lands directly in `waiting` and
probing continues; otherwise the attempt re-queues. This is why recording the handle is its
own commit the moment `execute` returns.

It is worth stating exactly what that promises. Recovery reads the handle on the reclaimed
attempt's own row and nothing else, so the guarantee covers **committed remote handles
only**: async work that was submitted and recorded is never submitted twice. A previous
attempt of the same step holds a handle on work that is already settled or cancelled, and
adopting it would land a retry on the outcome it was meant to replace. The guarantee says
nothing about a synchronous operator that changed the world and died before its outcome
commit -- there is no handle for recovery to find, so the attempt re-queues and `execute`
runs again. Non-idempotent synchronous work is protected by the step's retry policy, which
is where a person says how many times the work may run. The mirror-image failure
(the remote forgetting the job) is the **lost-job policy**: a deadline plus
fail-after-N-consecutive-`GONE`-probes turns a vanished remote job into a clean failed step
and an alert, never a hang.

**Automatic retries** are per-step policy: maximum attempts, exponential backoff with jitter,
and which failures qualify, driven by the block's error classification. A `transient` failure
with budget left inserts a new attempt row with `available_at = now() + backoff`; the delay is
data, no worker sleeps. A `rejected` failure fails the step immediately. An `unknown` failure
consumes budget exactly like a `transient` one, because `max_attempts` is what a person writes
down for the failures nobody can explain in advance. Sensor `NotYet` results are not failures
and consume no retry budget. Two remote outcomes classify by the same table: a probe
reporting `FAILED` is `unknown`, because the remote said the work failed and only the block
knows whether repeating it is safe, while exhausting the lost-job budget is `transient`,
because a vanished job is an infrastructure condition a resubmission may survive. A manual
attempt is never automatically retried: an operator asked for exactly one more try.

**Resuming a failed run starts from the failed step, never from scratch.** A run is rows, not
a process: successful steps keep their terminal attempts, and their outputs are persisted
artifact refs in shared storage. Manual retry creates one new attempt of kind `manual` for
the failed step alone, reading the upstream stored output; nothing upstream re-executes. Three
details make this dependable: per-item resume on fan-out (retry exactly the failed items),
URI-passed artifacts (a retry days later on a different worker still sees upstream outputs),
and snapshot-versus-current definition as an explicit choice, never a silent mid-run change.

## 7. Failure semantics, made generic

Exception and retry handling is the part that resists genericity. Dirigent keeps it tractable
by separating four layers, each with a small closed vocabulary, so a pipeline author composes
semantics instead of writing error-handling code:

- **Attempt level: should we try again?** Per-step retry policy over the operator's error
  classification (`transient` / `rejected` / `unknown`). The classification hook lives in the
  block, because only the block knows that a particular API returns a conflict status that
  still means success.
- **Step level: what does this failure mean downstream?** Trigger rules on edges, a minimal
  Airflow-compatible set: `all_success` (default), `all_done`, `one_failed`, `always`.
  Error-handler branches are ordinary steps behind a `one_failed` edge, so cleanup and
  compensation are drawn in the DAG, not coded. A step may be marked
  `continue_on_failure`, and `skipped` is a first-class terminal outcome distinct from
  `failed`. A `continue_on_failure` step that fails reads as succeeded to its dependents, so
  the branch carries on, while the run itself reports `completed_with_errors`. A prerequisite
  that failed or skipped makes an `all_success` edge unsatisfiable forever, so the dependent
  is skipped rather than left pending, and that skip propagates down the branch.
- **Item level: does one bad item sink the batch?** Fan-out steps isolate failures per run
  item by default; the step's item policy says whether any-item-failure fails the step. Under
  `fail_fast` any failed item fails the step; under `continue` the step succeeds as long as
  one item did, the failures are recorded per item, and the run reports
  `completed_with_errors`. A step mapped over an empty list is skipped, because nothing ran.
- **Run level: what do we tell the operator?** Run status derives mechanically from the
  leaves: all succeeded; some failed but tolerated (`completed_with_errors`); a required path
  failed (`failed`); `cancelled`. Alert rules key off exactly these.

With those four layers fixed in the engine, "exception handling" for a new integration
reduces to writing one honest error classifier per block. Everything else is configuration.

## 8. Triggers

- **Ad hoc.** UI run dialog (a form rendered from the pipeline's parameter schema), CLI, or
  plain API call. Always available, always parameterized.
- **Schedules.** Several per pipeline by design: cron, interval, or one-time, each with its
  own timezone, parameter overrides, and connection pins. The same pipeline hitting staging
  nightly and production weekly is two schedules, not two pipelines.
- **Inbound webhooks.** `POST /hooks/{token}` with a per-trigger token, optional HMAC
  verification, rate limiting, and a declarative payload-to-parameter mapping validated
  against the pipeline's schema. The endpoint validates, maps, enqueues, and returns the run
  id; nothing else executes in the request path.
- **Chaining.** Two sanctioned forms: the `pipeline.run` operator, and the outbound
  `webhook.post` operator or notifier carrying run outputs.

### The misfire policy

A schedule stores its next firing, so a tick is an indexed lookup rather than an evaluation
of every schedule in the instance. That makes one question unavoidable: what should happen
when a firing is claimed *late*, because the scheduler was down, the database was slow, or
the machine was asleep?

The answer is a grace window, `scheduler_misfire_grace` (five minutes by default):

- **Late by less than the grace**, the firing is ordinary. The clock advances from the slot
  it owed, so a cron schedule keeps its own grid rather than drifting by however long the
  tick happened to take.
- **Late by more than the grace**, the firing is a *misfire*. It fires exactly once, and the
  next firing is computed from *now*, abandoning every slot that was missed.

That second rule is the whole point. A scheduler down over a weekend wakes up, runs the
nightly job once, and returns to its grid -- instead of firing it sixty times, which is the
catchup storm every operator has been burned by. Resuming a paused schedule works the same
way and for the same reason: it recomputes from now rather than replaying what went past
while it was paused.

One consequence is worth knowing before anyone writes a monitor on it: **inside the grace,
`next_fire_at` can still be in the past.** A minute-by-minute schedule three minutes late
advances one slot per tick and catches up over the next few ticks, which is what "keeps its
grid" means. Only the misfire path guarantees a next firing in the future.

A one-time schedule whose instant has gone by has no next firing, so it pauses itself rather
than being deleted: the row, its parameters, and its history stay readable.

### The window a firing covers

A schedule says *when a run starts*. A data pipeline usually needs the other question
answered too: *what does this run cover*. The nightly load at 05:00 is meant to read the day
that just closed, not the instant it woke up in, and a run that computed "yesterday" from its
own start time would read a different day depending on how late it was claimed.

So a run may carry a **logical window**, `[window_start, window_end)` -- half-open, so two
consecutive firings tile the timeline without overlapping or leaving a gap. A document reads
it as `${run.window.start}` and `${run.window.end}`, which resolve to ISO 8601 instants.

A schedule-fired run derives its window from the cadence and from the firing's *logical due
time*, never from the moment the tick happened to claim it:

- `window_end` is `scheduled_for`, which is the slot the firing owed. That is the same value
  the misfire policy already works in, so a firing four minutes late still covers its own
  slot rather than sliding four minutes.
- `window_start` is the occurrence before it. For cron that is the previous point on the
  schedule's own grid, evaluated in the schedule's own timezone; for an interval it is
  `scheduled_for` minus the interval.
- A one-time schedule has no cadence and therefore no window.

Because cron runs backwards through the same grid it runs forwards through, in the declared
zone, the window is **wall-clock rather than a fixed number of hours**. A nightly job in
`Europe/Oslo` covers 23 hours across the spring-forward morning and 25 across the fall-back
one, which is the honest answer: those are the days that actually happened.

A webhook-triggered or pipeline-triggered run carries no window. An ad hoc run carries one
only if it was asked for -- `RunRequest` takes `window_start` and `window_end`, both or
neither -- and a run with no window **refuses** `${run.window.start}` the way it refuses any
unknown reference. Resolving it to an empty string would silently widen whatever the step was
about to fetch.

### Backfill

`POST /pipelines/{code}/$backfill` fills the windows a cadence has already gone past. The
body names the schedule whose cadence defines them, a half-open `from`/`to` bounding the
firings to enumerate, optional parameters (the schedule's own pins when omitted), and
`dry_run`.

It enumerates the occurrences inside `[from, to)` -- the lower bound is included and the
upper one is not, so two adjacent backfills tile without overlapping -- and creates one run
per window, **in chronological order**, each carrying the window that firing would have
carried and attributed `triggered_by_kind = backfill`. The answer lists every window and the
run id it became.

Three things it deliberately does not do. It does not touch the schedule's own clock:
`next_fire_at` is where it was, and none of this appears in the firing history, because these
firings never happened. It does not override the pipeline's concurrency policy: a `skip`
pipeline with a run in flight will refuse most of a backfill, and the answer says so per
window rather than pretending. And it will not create more than **200 runs** in one request;
past that it refuses, naming the cap and the count it computed, because the common way to
get a five-million-run backfill is a typo in a year.

An interval schedule has no absolute grid -- its arithmetic is purely relative -- so a
backfill of one is anchored on the `from` it was given. A one-time schedule has no cadence to
enumerate at all, and a backfill of one is refused.

### Webhook security model

`POST /hooks/{token}` is the only unauthenticated write surface the product exposes, so its
rules are worth stating exactly:

- **The token is the credential.** It is minted server-side with full entropy, stored only as
  a SHA-256 with a short prefix beside it, compared in constant time, and shown exactly once
  -- when it is created or rotated. It never appears in a document, in an export, or in a
  listing; there is nowhere in `dirigent/v1` to write one.
- **An unknown token and a disabled webhook answer identically**, so the endpoint is not an
  oracle for probing which tokens exist.
- **HMAC is optional and additive.** A webhook carrying a secret requires
  `X-Dirigent-Signature`, an HMAC-SHA256 over the **raw body** -- the bytes as they arrived,
  not a re-serialization of the parsed JSON, because those are not the same string. The
  `sha256=` prefix several popular senders write is accepted.
- **Rate limiting is a per-token bucket, checked before the body is read**, so a caller in a
  loop costs a dictionary lookup rather than a megabyte of parsing and a database round trip.
  The bucket is in memory and therefore per process: behind N API replicas the effective
  limit is the configured rate times N. That is documented rather than fixed, because the
  alternative -- a row updated on every delivery -- turns a cheap refusal into a database
  write, which is precisely what a caller hammering the endpoint would be trying to cause.
- **The mapping is strict and small.** `params_from_payload` is JSONPath-lite: a leading
  `$.`, dotted keys, and a numeric segment for a list element. No filters, wildcards, or
  slices, for the same reason the reference language has no expressions -- a mapping a
  reviewer cannot evaluate in their head is a mapping nobody can audit. It reads the JSON
  body and nothing else: not headers, not the query string.
- **The mapping is checked when it is declared, and the values it produces when they
  arrive.** Declaring one refuses a path that does not parse, a name the pipeline's parameter
  schema does not declare, and a required parameter without a default that nothing maps -- so
  a webhook that could never fire successfully is caught by the apply rather than by the first
  delivery.
- **What it produces is validated against the pipeline's own parameter schema**, like any
  other run's parameters, so a webhook cannot smuggle configuration past the schema.
- **Every delivery is recorded, refusals included**, with what arrived, what it mapped to,
  and the run or the reason. A refusal is therefore a *returned value* inside the endpoint
  rather than a raised exception: the row explaining why a call was refused is written in the
  same transaction, and an exception escaping would roll back exactly the evidence someone
  debugging their sender needs.

### What an apply does to triggers

A document's `triggers:` section is the declaration, and only the declaration. Applying one
matches by code within the pipeline and creates, redeclares, or retires accordingly.
Operational state is never touched: whether a schedule is paused, when it last fired, what a
webhook's token is, and what has been delivered are facts about *this instance*.

Ownership is explicit rather than inferred, through a `managed` flag. A row a document
declared is managed, and an apply may retire it when the document stops declaring it. A
schedule an operator added with `dg schedule create` is not, and an apply that does not
mention it leaves it alone -- deleting someone's schedule as a side effect of an unrelated
edit is the kind of surprise that makes people stop using the document format.

Two consequences worth knowing. An **unchanged** document still reconciles its triggers, so a
schedule deleted by hand comes back on the next apply; the digest covers the definition, not
the instance, and "apply the repository on every merge" is meant to be a convergence loop.
And an existing webhook **keeps its token** through an apply, because rotating a credential as
a side effect of an unrelated edit would make every edit a breaking change for whoever is
already calling.

An apply may ask for the schedules it **creates** to be created paused, through
`pause_schedules` on the request and `--paused` on the CLI. The flag is a column on the row
being inserted rather than a second write, so there is no instant in which a due schedule is
live and unpaused. It reaches only the schedules that apply mints: one the instance already
holds is operational state, so it is neither re-paused nor resumed by the flag's presence or
absence. That is what makes bringing a whole directory up on a fresh instance safe -- every
clock in it lands stopped -- without making a routine re-apply an instrument that overrides
what an operator decided.

### A triggers document

The `triggers:` section above lives inside the pipeline it fires, and that stays the primary
form: one file is one deployable unit, and its digest versions the clocks with the steps.
What it cannot say is a schedule for a pipeline defined somewhere else -- the operations
team's clock file over a pipeline another team owns. That is a second document kind:

```yaml
format: dirigent/v1
kind: triggers
code: nightly-batch          # this document's own addressable key, unique among these
name: Nightly batch clocks   # optional
description: ...             # optional, markdown
pipeline: nightly-export
triggers:
  schedules: [...]           # exactly the ScheduleSpec a pipeline document declares
  webhooks: [...]            # exactly the WebhookSpec
```

It is applied through the same `$apply`, plans the same four ways by digest, and reconciles
with the same semantics -- an unchanged one still reconciles, so a clock deleted by hand
comes back. It writes no versions: what it says is operational, and the digest is only what
makes an unchanged re-apply cheap. An empty `triggers:` is a valid document, and it retires
everything the document owned.

Three rules decide the rest.

**An absent pipeline is refused.** A triggers document naming a pipeline no instance holds
is INVALID at `pipeline`, and nothing is written; an inactive one is refused the same way.
Parking it pending would leave a clock file that silently does nothing. In a directory apply
pipeline documents go first and triggers documents after, so a directory carrying both
converges in one pass.

**Ownership is a row's owner, recorded.** `managed` keeps its meaning -- a document owns this
row -- and a nullable `trigger_document_id` says *which* document. That makes three owners,
and every reconcile reaches only its own:

| The row's owner | `managed` | `trigger_document_id` | Who may retire it |
| --- | --- | --- | --- |
| Hand, through the API, the CLI, or the UI | false | null | Whoever made it |
| The pipeline's own document | true | null | That pipeline's apply |
| A triggers document | true | that document's id | That document's apply, or deleting it |

A code the pipeline already carries under a different owner is refused at
`triggers.schedules[i].code`, naming the owner, rather than reaching the database and coming
back as an integrity error nobody can read. Deleting a triggers document takes its rows;
deleting the pipeline takes its triggers documents, which are meaningless without it.

**Pinned parameters validate against the target's current version**, at apply, exactly as a
schedule created through the API does -- and again at fire time, so a later pipeline version
that stops accepting the pins turns into a failed firing with the message on the firing row
rather than a silent one.

## 9. Alerting

Alerting is rules times channels, both data. An alert rule binds an event (`run_failed`,
`run_completed_with_errors`, `run_succeeded`, `run_stuck`) at a scope (global or per-pipeline)
to a notifier connection with a message template. Delivery is itself engine work, queued,
retried with backoff, and visible in the run timeline, so a flaky SMTP server cannot take
down a worker or silently drop an alert. Per-rule throttling prevents a flapping pipeline
from paging every minute.

### Delivery semantics

**Raising and settling are one commit.** When a run reaches a terminal status, the same
outcome transaction that settles it inserts the notification rows. A run therefore cannot
reach a terminal state without whatever it owes having been written down -- there is no
window in which a run has failed and the alert has not yet been decided on.

**Sending is a queue, not a call.** A worker claims notifications the way it claims attempts:
`FOR UPDATE SKIP LOCKED`, a lease, a retry with exponential backoff, and a terminal `failed`
status once the budget is gone. Nothing about a channel is on the outcome path, so a notifier
that hangs costs a lease and a retry rather than a blocked transaction. A worker whose lease
expires mid-send has its notification recovered by the same sweeper that recovers attempts.

**A rule says one thing about one run once.** The unique constraint on
`(alert_rule_id, run_id, event)` is the deduplication. It is what lets the sweeper re-detect a
stuck run every thirty seconds for as long as it stays stuck and still page exactly once, and
what makes two workers concluding the same thing harmless. Per-rule throttling is the second,
coarser guard, and it is measured from when a message was *raised* rather than delivered, so a
slow notifier cannot let a burst through the window behind it.

**Both outcomes are visible where someone is looking.** Queuing an alert, delivering it, and
giving up on it all write into the run's own timeline, so "the alert never arrived" is
answerable from the run rather than from a process log on some worker.

**`run_stuck` is the sweeper's.** A running run with no attempt progress for
`stuck_run` is stuck; detection is a query the sweeper already runs, and the alert is
raised from there.

**Templates degrade, they do not fail.** A message template reads `${run.*}` against a
snapshot of the run's facts taken when the alert was raised -- a snapshot, because delivery
happens later and a message describing the run as it is *now* would be misleading. A
reference that names nothing renders verbatim, because an alert is the last thing standing
between a failure and the person who needs to know, and a typo must degrade to an ugly message
rather than to no message. A reference that resolves to **null** renders as empty, which is a
different case entirely: half a run's facts are legitimately null depending on how it ended,
and printing `${run.error}` back at an operator whose run succeeded would be nonsense.

Four notifiers ship built in, so alerting works on a fresh install: `log`, which needs no
credential; `webhook`, an outbound JSON POST that reaches any system that accepts one; `slack`,
through an incoming webhook or `chat.postMessage`; and `email`, one plain-text message per alert
over SMTP. The last two register a connection kind of the same id, so a channel's credential is
minted, sealed and health-checked through the one connection path. A notifier raises on a
refusal rather than swallowing it, because the notification row owns the retry budget -- a
channel that quietly returned on a 500 would turn a recoverable blip into an alert nobody ever
gets.

## 10. Storage

Dirigent standardizes the reference, not the format or the backend:

- **Everything is a URI.** Step inputs and outputs that are not small structured values are
  artifact refs: a scheme, a location, a content type, a size. The engine stores and passes
  references; it never parses contents.
- **Backends register schemes.** A small streamed protocol (`open_read` / `open_write` /
  `stat` / `list` / `delete`). `file://` ships in core; `s3://` is the first backend package.
- **Blocks receive storage handles, not paths.** This is the multi-worker correctness rule:
  nothing ever passes a worker-local filesystem path between steps.
- **Run scratch space.** Each run gets a namespaced prefix
  (`<artifact-root>/runs/<run-id>/...`) on the configured default backend. A pruned run takes
  its prefix with it, and `retention_scratch` is how an instance whose bucket somebody else
  reaps says not to. Until `retention_runs` is set, a prefix survives its run.
- **`file://` is rooted.** The local backend resolves every URI inside the configured
  artifact root and refuses anything outside it, so a stored pipeline cannot turn a copy
  step into an arbitrary-file read. A write becomes visible only once it finished, because
  the bytes are staged beside the target and renamed on close.
- **The cap governs the artifact copy, not the attempt.** Every successful attempt keeps its
  structured output whole in `step_attempts.output`, whatever its size, and that is the column
  reference resolution reads -- so `${steps.<name>.output.*}` never pays a storage round trip
  for any output, small or large. Alongside it an `ArtifactRef` row always records the
  output's content type, byte size, and digest; `inline_artifact_max` decides only where
  *that* row keeps its copy. At or below the cap the value is inlined into the reference row;
  above it the canonical JSON is streamed to the run's scratch prefix and the row holds the
  URI. The consequence worth knowing is that a very large output is stored twice and the
  attempt row carries one of the copies, so the cap does not bound what a run costs the
  database. Bounding that is a block's job: `shell.run` and `docker.run` keep only a tail of a
  stream in their output and put the whole thing behind a URI.
- **A write is all or nothing, whatever the backend.** The mechanism differs and the contract
  does not: `file://` stages beside the target and renames on close, and `s3://` buffers until
  the multipart threshold, uploads parts as they fill, completes on a clean exit, and aborts
  on any exception. A reader never sees a half-written object either way.

### `s3://`, the first backend package

`dirigent-storage-s3` registers through its own `dirigent.plugins.v1` entry point, so an
instance gains the scheme by installing a package and changes nothing in core. It carries an
`s3` connection kind, which is where the deployment-specific parts belong: `endpoint_url` (so
every S3-compatible service works without a code path of its own), `region`,
an access key and a `SecretStr` secret, a path-style addressing toggle, and TLS verification.
Reads are streamed in bounded chunks and writes above 5 MiB become a multipart upload, so
moving a multi-gigabyte object is never resident.

Which connection serves a scheme is instance configuration, not a per-pipeline choice, so
`storage_connections` names it: `DIRIGENT_STORAGE_CONNECTIONS=s3=archive`. One instance may
hold several `s3` connections and still say which one `s3://` addresses. The binding happens
in the step context, on the worker path, where connection secrets are opened and nowhere
else, and lazily per scheme -- a run that never writes an `s3://` URI never resolves the
connection, so renaming it cannot break a pipeline that does not use it. A scheme with no
entry keeps whatever its package contributed it with, which for `s3://` is the ambient AWS
credential chain.

One behavioural difference between the two shipped backends is worth knowing rather than
discovering. An S3 key is one flat string, not a path, so in a listing pattern `*` **crosses
`/`** for `s3://` where it does not for `file://`: `s3://bucket/data/*.csv` matches
`data/2026/01/rows.csv`. That keeps a glob listing consistent with a plain prefix listing,
which already reaches every depth. The bucket always comes from the URI; the connection's
`bucket` field is only what a health check probes.

## 11. HTTP API

```text
POST          /api/v1/auth/login             # the only unauthenticated route under /api/v1
POST          /api/v1/auth/logout            # + GET /auth/me
POST          /api/v1/auth/password          # self-service; keeps this session, revokes the rest
GET/POST      /api/v1/tokens                 # + DELETE /tokens/{name}
GET/POST      /api/v1/users                  # + PATCH, /{username}/$deactivate, /$activate
GET/POST      /api/v1/connections            # + /{code}, PATCH, DELETE, /{code}/$check
GET           /api/v1/blocks                 # catalog: operators, sensors, schemes, notifiers
GET           /api/v1/blocks/{id}            # one block's published schemas
GET           /api/v1/schema/document        # dirigent/v1 composed with this catalog's configs
GET           /api/v1/pipelines              # + /{code}, /{code}/versions
POST          /api/v1/pipelines/$apply       # a whole document; ?dry_run=true returns the plan
                                             # pause_schedules: true mints its new clocks paused
GET           /api/v1/pipelines/{code}/$export        # canonical YAML
POST          /api/v1/pipelines/{code}/$validate      # re-check a stored version
POST          /api/v1/pipelines/{code}/$activate      # + /$deactivate, DELETE ?force=true
POST          /api/v1/pipelines/{code}/$run           # parameters validated against the schema
GET           /api/v1/runs                   # filters: pipeline, status, since
GET           /api/v1/runs/{id}              # run + DAG view model + item and attempt counts
GET           /api/v1/runs/{id}/items        # the fan-out grid, paged in creation order
GET           /api/v1/runs/{id}/attempts     # paged in creation order; filters: step, status
POST          /api/v1/runs/{id}/$cancel
POST          /api/v1/attempts/{id}/$retry   # Idempotency-Key header required
GET           /api/v1/runs/{id}/$logs        # a page like every listing; ?follow=sse tails it
GET           /api/v1/runs/{id}/$events      # the whole run as one SSE stream, for a watcher
GET           /api/v1/runs/{id}/$report      # a summary fit to paste into a ticket
GET           /api/v1/workers                # the registry
GET           /api/v1/system/info            # per-connection fan-out, run concurrently
GET           /health                        # liveness; /health/ready runs the checks
```

A run's detail is the run, its DAG view model, and how many items and attempts the run has;
the grids themselves are the two paged sub-resources, so one response never grows with the
size of a fan-out. The DAG is folded from grouped counts rather than from the rows, which is
what makes the detail one small query however many attempts a run holds. A watcher reads
`$events` instead of any of it.

M2 adds the trigger and alerting surface, plus the one route that is not under `/api/v1`:

```text
GET/POST      /api/v1/pipelines/{code}/triggers/schedules          # + /{schedule}, PATCH, DELETE
POST          /api/v1/pipelines/{code}/triggers/schedules/{s}/$pause   # + /$resume
GET           /api/v1/pipelines/{code}/triggers/schedules/{s}/firings
GET/POST      /api/v1/pipelines/{code}/triggers/webhooks           # + /{webhook}, DELETE
POST          /api/v1/pipelines/{code}/triggers/webhooks/{w}/$rotate-token
POST          /api/v1/pipelines/{code}/triggers/webhooks/{w}/$disable   # + /$enable
GET           /api/v1/pipelines/{code}/triggers/webhooks/{w}/deliveries
GET/POST      /api/v1/alert-rules                                  # + DELETE /{code}
POST          /api/v1/alert-rules/$test                            # one message, real queue
GET           /api/v1/notifications                                # the alert queue
POST          /hooks/{token}                                       # outside /api/v1 auth
```

`/hooks/{token}` is mounted at the application root rather than under the versioned API, and
that is a deliberate structural choice rather than a routing convenience. Authentication under
`/api/v1` is a property of the mount: every route there requires a principal. A webhook has no
principal to present -- its token *is* its credential, and it authenticates as the trigger
rather than as a person. Two authentication models on one mount is how one of them eventually
ends up wrong, so this one gets its own mount and its own rules.

Still to come: `/api/v1/artifacts/{id}`.

Resource paths plus `$verb` for non-CRUD operations; OpenAPI generated by FastAPI, with an
explicit operation id and summary on every operation, because a generated client is only as
readable as the names it is given. The catalog endpoint is the load-bearing one: the UI is a
client of `/blocks`, which is why installing a plugin package extends the product without a
frontend release.

**Pagination.** Every listing answers one envelope, `{"items": [...], "next": <cursor or null>}`,
and takes `limit` (1 to 500, defaulting to 50) and `after`. `after` is whatever the previous
page's `next` said and nothing else: it is opaque, a caller never constructs one, and one that
does not parse is a 422 rather than a 500. Selection is keyset, not offset -- the listing reads
`limit + 1` rows past the cursor in its own order and `next` is the sort key of the last row it
returns -- so a row inserted between two pages is neither skipped nor served twice. The order,
and therefore the cursor, is per listing: `/runs`, the firings, the deliveries and the
notifications go newest first by id; `/pipelines`, `/connections`, the schedules and the
webhooks go by code, `/workers` and `/users` by their own name and username; `/alert-rules`
and `/tokens` by id; a pipeline's versions newest version first; `$logs` by log id, in write
order. Three listings stay bare arrays because
what bounds them is not the database: the block catalog is bounded by the installed code, and a
`$validate` response by the document it checked.

Two shapes are worth calling out. `$apply` takes a whole document rather than a patch, because
the document is the unit a person edits and a version is immutable anyway. And the run detail
serves a DAG view model -- nodes with their current outcome, and edges -- folded from the pinned
definition and the run's attempts by the same function the engine's readiness walk uses, so the
picture and the engine can never disagree.

**A listing row carries what a listing draws.** `/pipelines` answers each row with how many
schedules and how many webhooks fire it, how many of its runs are still in flight, and how its
newest run went -- that run's id, the state it is in, when it started and finished, and the step
its first failed attempt was of when it did not end well. All of it is computed by the read that
returns the page: three correlated counts inside the statement that reads the rows, one windowed
select for the newest run of each pipeline, and one more for the step a bad one failed at. A
screen that asked for these per row would make fifty-one requests of a fifty-row page, and a
screen that left them out would be a listing nobody can act on without opening every row in it.

The SSE log tail is a poll rather than a subscription, deliberately: log entries are rows
written by whichever worker claimed the attempt, possibly on another machine, so there is
nothing in the API process to subscribe to. One indexed query every half second against
`(run_id, id)` is what that index exists for.

`$events` is the same poll, carrying the whole run rather than its log. One stream sends
three kinds of event: an `attempt` for every state an attempt is found in, a `log` for each
entry, and a `run` for every state the run itself is found in -- on connect, and again each
time its status, start, end or error changes -- the last of them terminal and followed by the
`end` sentinel that closes the stream. `end` means the run settled and nothing else: a stream
that reaches the server's wall-clock limit with the run still going closes with `expired`, which
a client reopens from its cursor rather than reading as the end of the story. Each cycle sends
its log entries in ascending id, because that is the position a client resumes from and lines are
buffered per attempt and written when it settles, so two attempts running at once commit
theirs out of timestamp order; a transition is placed ahead of the first entry written no
earlier than it. On connect every attempt is replayed once in
its current state, so a client that joined late reads the same story as one that was there
from the start, minus the states it missed; after that only what changed is sent, measured
against the status, attempt number, finish time and waiting message last reported. That makes
the full-grid read a watcher used to cause per poll a read the server does once per watcher,
and the answer a delta.

Every log frame on either endpoint carries an SSE `id`, which is the log entry's id, and both
endpoints read `Last-Event-ID` as the log cursor when no `after` was given. A browser's own
`EventSource` resends that header when it reconnects, so a dropped connection resumes past the
lines already delivered with nothing repeated and nothing missed. An attempt or run frame
carries no id, because those are replayed on connect by design; a client dedupes the replay by
the attempt's own id, which is the documented contract.

`$logs` and `$events` draw on one per-principal budget of open streams, because what a watcher
costs this instance is the poll loops it holds open. The budget is eight, and the UI rule that
sizes it is **one multiplexed stream per run**: a run's page opens `$events` once and feeds its
log pane, its DAG and its status from that single stream, never one stream per pane. Eight is
then several runs watched at once, not one run watched wastefully.

**Where the request and response schemas live.** In `dirigent-client`, not in the server. The
server imports them, which is what makes "the client parses what the server writes" a property
of the code rather than a thing to keep checking: there is one pydantic model per shape, and
adding a field to a response is the same edit as adding it to what a client can read. The
package is a leaf -- `dirigent-plugin`, `httpx2`, `pydantic` -- so a program that drives an
instance installs the contract and the SDK without installing the engine.

## 12. Defining pipelines: one model, two editors

At the source of truth a pipeline is a Pydantic model, stored whole as one immutable JSON
document per version. YAML and JSON are that same model serialized, so round-tripping is
`model_validate` / `model_dump`, with no mapping layer and no drift. YAML is the canonical
interchange format: exportable, diffable, reviewable in git, and appliable to another
instance.

**The rule that prevents the classic drift:** the UI and the document format are two editors
of the same model. No feature may exist in only one of them, both are validated by the same
code, and a round-trip test (export, apply, export, byte-identical) runs in CI.

```yaml
# daily-climate-load.yaml -- format dirigent/v1; JSON equivalent accepted verbatim
format: dirigent/v1
kind: pipeline
code: daily-climate-load               # the addressable key: URLs, references, apply matching
name: Daily climate load               # optional, human, referenced by nothing
description: |                         # optional, long-form, markdown
  Waits for the day's drop, then pushes it region by region.
tags: [climate, nightly]               # optional; what this is for, in the corpus's own words
concurrency: skip                      # allow | skip | queue | replace
priority: normal                       # low | normal | high; a trigger or a run may override it

params:                                # JSON Schema; drives the run form and webhook mapping
  type: object
  required: [day]
  properties:
    day: { type: string, format: date }
    regions:
      type: array
      items: { type: string }
      default: ["no", "se", "dk"]   # quoted: unquoted `no` is a YAML boolean

steps:
  wait_for_drop:
    block: storage.exists              # a sensor: the step kind comes from the catalog
    config:
      uri: "s3://drops/climate/${params.day}.parquet"
    poll: 5m
    deadline: 6h
    on_timeout: skip                   # no drop today: downstream is skipped, not failed

  push:
    block: http.request
    depends_on: [wait_for_drop]
    for_each: "${params.regions}"      # fan-out: one RunItem per region
    config:
      connection: modelling-api        # a Connection, by code: portable across instances
      method: POST
      path: "/v1/ingest/${item}"
    retry:
      max_attempts: 5
      backoff: 30s
    items: continue                    # one failed region does not stop the others

  notify_failure:
    name: Tell operations              # optional; the map key stays the reference
    block: webhook.post
    depends_on: [push]
    rule: one_failed                   # error-handler branch, drawn in the DAG
    config:
      connection: ops-webhook

triggers:                              # optional, and travels with the document
  schedules:
    - code: nightly
      name: Nightly, Oslo time         # optional here too, and so is description
      cron: "0 5 * * *"
      timezone: Europe/Oslo
  webhooks:
    - code: upstream-publish
      params_from_payload: { day: "$.published.date" }

requires:                              # the preflight a shared document declares
  blocks: [http.request, storage.exists]
  connections: [modelling-api, ops-webhook]
  storage: [s3]                        # named by scheme; a backend must claim each one
  workers: [docker]                    # capability tags a worker must carry to claim this
```

Every construct above is exercised by a runnable document under `examples/`, one concept per
file, walked by a test on every CI run so none of them can rot.

Reading guide for the choices above:

- Steps are a named map; edges are `depends_on` plus `rule`. Acyclicity and
  unknown-reference checks run at apply time, identically for the UI. A step's optional
  `name:` is display only: `depends_on` and `${steps....}` read the map key and nothing else.
- `params` is checked at apply time to be a JSON Schema itself, so `type: objcet` is refused
  with the document rather than at the first run.
- `for_each` is expanded when the run is created, so the item grid exists from the moment a
  run is visible. It may therefore read `params.*`, `item`, and `run.*`, but not another
  step's output; a fan-out whose cardinality depends on upstream work is a later milestone.
- `${...}` is the whole reference language (`params.*`, `steps.<name>.output.*`, `item`,
  `run.scratch`, `run.id`, `run.window.start`, `run.window.end`, `trigger.*`). There are no
  expressions, loops, or conditionals in v1; logic lives in blocks and trigger rules, which is
  what keeps documents reviewable. `$${...}` is the escape: it yields the literal `${...}`,
  is never resolved and is never checked, which is how a compose file or a template reaches
  its tool with its own braces intact.
- The format refuses a key it does not define, at every level: a document, a step, a retry
  policy, a schedule. A `depend_on:` typo would otherwise delete an edge silently, and the
  canonical export -- and therefore the digest and `--dry-run` -- would show nothing.
- Block config is opaque to the format, so a new plugin extends what documents can say
  without touching `dirigent/v1`. Opaque is not unchecked: each block publishes its config
  schema with `additionalProperties: false`, so a stray config key is refused at apply,
  against the block rather than against the format.
- Sensor knobs (`poll`, `deadline`, `on_timeout`) and retry policy are step-level, not buried
  in config: they are engine semantics, uniform across all blocks.

**Tags say what a pipeline is for.** A corpus grows past the point where forty codes in a list
mean anything, and `tags:` is how a document says which handful of them belong together --
`climate`, `transform`, `failure`, whatever vocabulary the people running the instance have
agreed on. A tag is lowercase letters, digits and hyphens, at most 32 characters, unique within
the list, and at most sixteen to a document; the document owns them, so applying replaces the
whole list the way it replaces the name and the description, and nothing edits them anywhere
else. `GET /pipelines?tag=climate&tag=nightly` narrows to the pipelines wearing both, and the
listing screen and `dg pipeline list --tag` are that query. They are labels and not identity:
nothing is ever referenced by a tag, and two pipelines wearing the same one are not related by
it beyond having been called the same thing.

**Key grammars, and why there are two.** Keys are API: they appear in documents, in REST
paths, in the UI, and in every conversation about the system. Two grammars live in
`dirigent-common` as shared validated types, so the server, the engine, the CLI, and any
third-party plugin read one definition:

- `EntityName` is DNS-label kebab-case (`^[a-z](-?[a-z0-9])*$`, at most 63 characters) and
  governs the `code` of every addressable thing an instance holds: pipelines, connections,
  schedules, webhooks, alert rules, workers, profile keys. Dots are excluded because they are
  reserved for block ids, so a code and a block id are never confusable; underscores and
  spaces are excluded because a code travels through URLs. Prose belongs in `name` and
  `description`, never in the code.
- `StepName` is snake_case (`^[a-z][a-z0-9_]*$`) and governs the keys of a `steps` map. Step
  names live inside `${steps.<name>.output.*}`, where a hyphen reads as a minus sign and a dot
  as a path separator, so a kebab-case step name would be ambiguous exactly where it is read.

*(Deviation from the blueprint: the entity pattern is written without the look-ahead the
blueprint sketched. The two accept precisely the same strings, but the pattern is published
in JSON Schema and compiled by pydantic-core's Rust engine, which supports no look-around.)*

**Identity: codes travel, ids never do.** Every addressable thing -- a pipeline, a connection,
a schedule, a webhook, an alert rule -- carries the same four fields, and each has exactly one
job:

- **`id`** is a UUIDv7 the instance mints. It is what foreign keys and webhook token binding
  point at, and it is never exported and never typed by a person.
- **`code`** is the addressable key: an `EntityName`, unique per instance, and the only
  identity a document carries. It is what appears in a REST path, what a
  `connection:` in a step config resolves, what `depends_on` in a `requires` block lists, and
  what `apply` matches on.
- **`name`** is an optional human title, free-form and unconstrained, and it carries no
  identity whatsoever. Nothing resolves it, nothing is unique by it, and no reference may ever
  be written against it. It exists so a listing can read "Daily climate load" instead of
  `daily-climate-load`, and that is all it does.
- **`description`** is optional long-form prose, markdown-capable, and the place where the
  context that does not fit in a title goes.

That split is what lets a code stay short, stable, and mechanical while the words a person
reads stay free to change. Renaming is therefore cheap and recoding is not, which is the right
way round.

Two more identities sit beside them. A **version** is a monotonic integer per pipeline,
immutable, and what runs pin. A **digest** is a content hash of the canonicalized document,
powering the apply plan ("unchanged, nothing to do"), provenance, and drift detection against a
git repo. Deactivating keeps the code and the history, and is the reversible verb; deleting
keeps neither.

**Deleting deletes.** Deleting a pipeline deletes its run history with it -- every run ever
attributed to it, and their items, attempts, log entries and artifact references, along with
the versions, schedules, webhooks and alert rules the definition owns -- in one transaction,
and the code is free again. There is no force flag and nothing is left behind to point at. The
one refusal is about liveness, not history: runs still queued or running refuse the delete with
a 409, because deleting them would strand work a worker holds a lease on. Finish or cancel
them, or deactivate the pipeline instead, which stops it being runnable and keeps everything.

**One rule renders all four.** Wherever any of these appears -- a list row, a detail header, a
node on the canvas -- the title is the `name` when there is one and the `code` when there is
not, and the code is on screen either way: in mono beneath a title that is a name, or as the
title itself, wearing the mono face. It is never drawn twice and never left out, so the string
somebody would paste into a URL is always in the same place. The `description` is the body
beneath, rendered as markdown. A reader who wants the machine key always finds it, and one who
wants the words is never made to decode a slug.

**Durations are humane strings.** `30s`, `5m`, `6h`, `1h30m`, `250ms`, and a bare number of
seconds. ISO 8601 (`PT5M`) is accepted by nothing human and would leak into every diff, so the
format defines its own grammar, parsed to `timedelta` and rendered back deterministically:
`90s` reads back out as `1m30s`, and reading that again yields the same value.

**Sizes are too.** `64mb`, `512kb`, `1.5gb`, `1tb`, and a bare number of bytes. Both unit
families are accepted -- `mb` and `mib` are the same number -- and both are powers of 1024,
which is what an operator means by "64 megabytes of memory" whatever the SI prefix says. The
value is an `int` of bytes everywhere in the code; only the writing and the rendering are
humane. Rendering picks the largest unit that divides the value exactly, so a size is never
written as a decimal and `1.5gb` reads back out as `1536mb`. Both grammars live in
`dirigent-common` beside the key grammars, because a third-party block writes a `Size` or a
`Duration` in its own config model and must not have to depend on the engine to do it.

**The canonical form is a function of the definition alone.** That matters because PostgreSQL's
`jsonb` does not preserve key order: a document stored and read back would otherwise export
differently than it went in, and the round-trip test would be testing the database. Three
rules, each chosen so the canonical order is also the readable one:

- Model fields keep their declaration order, which is the order a human wants.
- Steps are written in topological order, alphabetical within a layer, so a document always
  reads from its roots downward regardless of how it was assembled.
- Maps opaque to the format -- the parameter schema, a step's config, a trigger's parameters --
  get a fixed key order: the well-known schema keys first, then the rest alphabetically.

Fields left at their default are omitted, so a small pipeline exports as a small document. The
digest is the SHA-256 of that canonical YAML, and the CI round-trip test asserts
export-apply-export is byte-identical. *(Two consequences worth knowing: a value written at
its default disappears on export, and YAML comments do not survive a round trip, because they
are not part of the model. `examples/` is hand-written for that reason.)*

**Validation happens in layers.** The envelope, the key grammars, the graph, and the
reference language are checked by the model itself, offline, with no server involved -- which
is what `dg validate` runs. The catalog layer needs an instance: the `requires` preflight, that
every block id exists, that each step's config validates against that block's published schema,
and that every connection a step names by code exists. Every problem is reported at once,
because someone importing a shared document wants one list of what to install. A config full
of `${...}` has not got its values yet, so a value containing a reference is deferred rather
than type-checked, which keeps the rest of the check strict.

**Apply is a plan, then a commit.** Matching is by code: absent means create, present means a
new version, and a matching digest means `unchanged` and nothing written -- so a CI job that
applies the whole repository on every merge does not accumulate a version per commit. A dry run
returns the plan: the action, a diff summary (steps added, removed, changed; whether the
parameter schema, the triggers, or the settings moved), and the validation issues if there are
any. Each version records its provenance: who applied it, from a file, a URL, the API, or the
UI, and the digest.

## 13. Web UI and CLI

The UI is where pipelines are made, so the builder is the centerpiece: compose the DAG,
configure each step in a form rendered from its published schema, declare fan-out, set retry
policy, with live validation against the same schemas the engine enforces. Around it: run
list and run detail with the item grid and an SSE log tail, kind-specific connection forms
with a test button, schedules with their next firing, alerting rules, and a dashboard.
`docs/ui-conventions.md` is the design system the whole of it is built to.

The CLI is Typer plus rich, installed as `dirigent` with `dg` as the short alias. It is both
the operator's remote (a server via `--profile` / `DG_URL` / `DG_TOKEN`) and the process
entry point for containers. Nouns are subcommand groups matching the API resources; the only
top-level verbs are the ones an operator reaches for constantly (`run`, `apply`, `export`,
`validate`) and the process entry points. The terminal decides the output: a person at one reads the
rendering, and a pipe, a container or CI reads NDJSON, one record per line each carrying a
`kind`, with a list or a show writing the server's own response, so a script that parses what
it is given is reading the API. `--json` and `-o console` override the terminal either way.

```text
# processes (container entry points)
dg dev [--wipe-state]                   # standalone: SQLite, API + scheduler + worker
dg server [--no-scheduler]              # API; the scheduler is embedded unless it is isolated
dg worker [--concurrency N]
dg scheduler                            # the clock on its own, when the API is scaled out
dg db upgrade | current | history

# projects and definitions
dg init [DIR] [--template local|compose|documents]
dg apply [file|url|-] [--dry-run] [--as NAME] [--paused]      # no argument in a project: the whole project
dg export NAME [-o FILE] [--version N]
dg validate [file|url] [--server]
dg pipeline list | show | versions | activate | deactivate | delete NAME

# execution
dg run NAME|file|url [-p key=value ...] [-P FILE] [--watch] [--local]
dg runs list | show | cancel | report | logs [--follow] | retry RUN --step NAME

# triggers and alerting
dg schedule create PIPELINE NAME --cron EXPR | --interval DUR | --at WHEN [--tz ZONE] [-p k=v] [-P FILE]
dg schedule list | pause | resume | firings | delete PIPELINE NAME
dg webhook create PIPELINE NAME [--map param='$.path'] [--hmac-secret S] [--rate-limit N]
dg webhook list | rotate-token | deliveries | delete PIPELINE NAME
dg alerts rules list | create NAME --event E --notifier N [--pipeline P] [--throttle DUR] | delete NAME
dg alerts test NOTIFIER [--connection NAME] | dg alerts queue

# catalog, connections, operations
dg blocks list [--kind operator|sensor] | show BLOCK_ID
dg connection list | create KIND NAME --set field=value | show | check | delete NAME
dg system info | dg system workers | dg config show | dg --version
dg auth login | status
dg admin user create | list | password | dg admin token create | list | revoke
```

Two shapes in there are worth explaining. `dg schedule create` builds its `-p` overrides
against the pipeline's own parameter schema, with the same builder `dg run` uses, so a typo is
refused when the schedule is created rather than discovered at five in the morning when it
fires. And `dg alerts test` names the **notifier**, with the connection as an option, because
a credential record does not determine which channel delivers through it -- the same record
can be the target of more than one, and the channel is the thing being tested.

*(Deviation from the blueprint, which sketched `dg alerts test CONNECTION`.)*

A minted webhook token is printed once, with the URL already assembled, and never again: the
instance keeps only its hash. `dg webhook rotate-token` is how a token nobody wrote down is
replaced, and it invalidates the old one immediately.

**Three disjoint configuration planes**, and keeping them apart is the point:

| Plane | Holds | Lives |
| --- | --- | --- |
| Profiles | A server URL, and how to get a token for it | Beside the person: `.dirigent/profiles.yaml` in a project, then `~/.config/dirigent/profiles.yaml` |
| Server settings | `DIRIGENT_DATABASE_URL`, `DIRIGENT_SECRET_KEY`, the artifact root, the unsafe-block allowlist | On the host running the server, the workers, and the scheduler |
| Connections | Third-party credentials | Encrypted inside the server's database |

A profile therefore never holds a database URL, and one that names a database scheme is
refused on sight: a CLI that could reach the database would bypass authentication,
attribution, and validation entirely. The token has three interchangeable mechanisms and no
secret-manager assumption -- inline (`token`), an environment variable (`token_env`), or any
command that prints it (`token_cmd`) -- and precedence is flags, then `DG_*`, then the
selected profile.

**`dg run` takes a code or a document.** Given a code it starts a run of a pipeline the
instance already has. Given a file, a URL, or `-`, it applies the document first, exactly as
`dg apply` would, and then runs it. Given `--local` it does all of that in a throwaway SQLite
instance in a temporary directory, with no server anywhere: the same apply, the same engine,
the same worker loop, deleted afterwards. That is the quick-try and CI story, and the reason
it is the same code path is that a local run that executed differently would prove nothing.
`--connections FILE` supplies the credentials a serverless run has nowhere to read from, and
`--enable-unsafe BLOCK` adds to the allowlist for one command rather than turning the gate
off.

**Parameters are built against the pipeline's own schema.** The CLI reads the schema before it
sends anything, so `-p count=3` is an integer and `-p code=3` is a string when the schema says
so, an enum value is checked, a dotted key addresses a nested leaf (`-p server.tls.verify=false`),
an object or array is given whole and inline, and `-P FILE` takes a payload. Precedence is
defaults, then files, then flags in the order given; objects deep-merge, arrays and scalars
replace, and a bracketed index sets one element in place. A path the schema does not declare is
refused with the location named, which is stricter than JSON Schema on purpose: a pipeline that
lists its parameters has said what a run takes, and `-p dya=...` is a typo rather than a new
parameter. An array element is addressed with brackets and nothing else -- `regions[0]`,
`regions[]` to append, `targets[0].host` to reach through one -- because a dotted `regions.0`
cannot tell the index `0` from an object key named `"0"`. An index past the end is refused with
the gap it would leave named, so a list is built in order or not at all.

**What a run looks like while it happens.** `--watch` and `--local` stream step transitions and
block output merged by timestamp, so the stream reads as cause then effect. A watched run reads
that order off `GET /runs/{id}/$events`, which is where the merge happens; a local run has the
engine in the same process and merges it there. When a step fails,
both print the diagnosis before exiting: the failing step, its block, the error class the block
assigned, the message, and that attempt's log lines. For a local run that is not a nicety --
the database is deleted on the way out, so a failure that is not read out there is a failure
nobody can ever investigate. The exit code is the run's outcome: zero for succeeded, non-zero
for failed and cancelled, and zero with a warning for `completed_with_errors` unless `--strict`.

**Verbosity is a flag, not an environment variable.** The default output is the run, not the
CLI: transitions and block output only. `-v` interleaves the engine's own INFO events and the
API calls the CLI makes; `-vv` is DEBUG, with the libraries that log once per SQL statement or
socket read capped so it stays readable; `--debug-all` lifts even that. Precedence is the flag,
then `DIRIGENT_LOG_LEVEL`, then quiet.

## 14. Security posture

- **Authentication in M1**: session login for the UI, API tokens for automation, a local user
  table, single admin first with schema room for roles. An orchestrator is a credential vault
  with an execute button; it does not ship open.

  Sessions and API tokens are one table, `api_tokens`, because they are one thing: an opaque
  secret that authenticates as a user until it expires or is revoked. Keeping them apart would
  mean two lookup paths, two revocation stories, and two chances to get the comparison wrong.
  The difference is only where the secret is presented -- an `Authorization: Bearer` header or
  an http-only cookie -- and what a run it starts is attributed to. Passwords are Argon2id
  hashes; a token is stored as a SHA-256 of the presented value (it has full entropy, so there
  is nothing to brute-force, and the lookup happens on every request) with a short readable
  prefix beside it so a listing can tell two tokens apart without holding either.

  **Why opaque tokens, not JWTs.** A bearer credential here is a random 32-byte secret whose
  SHA-256 is looked up on every request; it carries no claims and means nothing on its own.
  That costs one indexed lookup per call, and buys three things a signed self-contained token
  cannot give without building them back by hand. Revocation is immediate, because the check
  is a row and setting `revoked_at` ends the credential on the next request rather than at the
  end of some expiry window -- and an orchestrator holds every credential its pipelines use,
  so "revoked now" is the only useful meaning of revoked. Automation credentials are
  long-lived by nature, and a long-lived JWT is precisely the one nobody can take back. And
  the row is the audit trail: a name, a prefix, who minted it, and `last_used_at`, which is
  what answers "is this token still in use, and may I revoke it?". The per-request cost is one
  indexed lookup and nothing else: `last_used_at` is written on a token's first use and then
  only once a minute has passed, so authentication does not turn every read into a row write.
  That is the write amplification handled without going stateless.

  JWTs have a place, and it is the federation boundary rather than the internal format. When
  OIDC/SSO lands, the shape is to validate a token an identity provider signed (realistically
  Keycloak), map its subject onto a local user,
  and then issue dirigent's own opaque credential for everything afterwards. JWT as the
  format two systems agree on, never as the format dirigent authenticates itself with. The
  whole argument, with the token lifecycle around it, is on [the security page](security.md).

  Every route under `/api/v1` requires a principal. The exemptions are deliberate and few: the
  liveness and readiness probes, the OpenAPI document and its viewers, and login itself, which
  cannot require what it hands out. Authentication is a property of the router mount rather
  than something each endpoint remembers.

  First run has to work before anything can authenticate, so account creation has a local path:
  `dg admin user create` runs against the configured database the way `dg db upgrade` does, and
  `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD` creates the first admin unattended in a container. Both
  are one-way: they do nothing once an account exists, so leaving the variable set on every
  deploy cannot reset a live instance's password. `dg dev` mints a development admin and prints
  a token once, because a local loop that made you create an account before you could call
  anything is a loop nobody uses.
- **Secrets encrypted at rest** with envelope encryption and a key from the environment,
  secret fields marked in connection schemas, redacted in every API response by default,
  never in logs or pipeline definitions.
- **Webhook intake hardened**: unguessable per-trigger tokens minted server-side and stored
  only as a hash, optional HMAC verification over the raw body, per-token rate limiting
  checked before the body is read, and a strict payload mapping whose result is validated
  against the pipeline's parameter schema. An unknown token and a disabled webhook answer
  identically, so the endpoint cannot be probed for which tokens once addressed something.
  Section 8 has the whole model.
- **Attribution is a foreign key**: every run points at the user, schedule, webhook, or token
  that started it.
- **Outbound discipline**: timeouts on every call, TLS verification per connection, transport
  retries only for idempotent requests, error classification owned by blocks.
- **Local execution is opt-in**: `shell.run`, `docker.run`, and any block whose spec sets
  `local_execution` are disabled unless the instance allowlists their id in
  `DIRIGENT_ENABLED_UNSAFE_BLOCKS`. `docker.run` deserves its own sentence: reaching the
  Docker socket is equivalent to root on the worker, so allowlisting it is a decision about
  the host and not about a pipeline. Its containers default to `network: none`, because an
  image a stored pipeline named should not reach the worker's network unless the step says
  so. The gate is enforced twice, when a run is created and
  again when a worker claims the step, so tightening the config stops work that was already
  queued. "Can edit pipelines" must not silently mean "can run code on workers". `dg run
  --local --enable-unsafe shell.run` adds to the allowlist for one command; it never turns the
  gate off.

## 15. Lessons carried in

The survey of prior art collapses to a short list of scars this design answers:

- An unauthenticated control plane holding credentials was the loudest failure everywhere.
  Hence auth in M1.
- Hand-rolled broker coordination (outbox, DLX, read-then-act) is where the critical bugs
  lived. Hence Postgres-only transactions.
- Blocking a worker while polling a slow remote wedged queues. Hence the durable `waiting`
  state.
- Passing files between steps by worker-local path failed randomly under multiple workers.
  Hence URI-only artifact passing.
- Batch runs with no per-item status forced a hand-built reporting layer. Hence `RunItem`.
- Singleton-by-convention schedulers and ambient timezones double-fired. Hence advisory locks
  and per-schedule timezones.
- Unbounded log and run tables with no retention story. Hence log batching from day one, and
  a per-family retention age with a scheduled sweep and a `dg prune` command. Every age is
  unset by default: an orchestrator that quietly deleted the record of what it ran would be
  worse than one that fills a disk, so keeping is the default and pruning is a decision.

## 16. Roadmap

- **M0 - Workspace skeleton.** uv workspace, house tooling, CI, the `dirigent-plugin`
  contract package drafted first, the schema baseline, health endpoints. *(Complete.)*
- **M1 - Engine with generic blocks.** Connections, pipelines with DAG edges,
  runs/items/attempts, `SKIP LOCKED` claims, `waiting` probing, retry and trigger-rule
  semantics, cancellation, auth, the `dirigent/v1` document format with `dg apply` / `export`,
  and `dg dev` standalone mode on SQLite. OpenTelemetry instrumentation goes in here,
  exporterless. Proven end-to-end with `http.request`, `http.ready`, `storage.copy`,
  `shell.run`, and `file://`. *(Complete. The end-to-end proof is a test: `dg init`, a
  three-step document, `dg apply` to a running `dg dev`, `dg run --watch`, `dg runs show` and
  `logs`, all as subprocesses against a real port.)*
- **M2 - Triggers, alerting, storage backends.** The scheduler loop with its advisory lock
  and misfire policy, webhook intake with payload mapping, alert rules delivered through a
  retried notification queue with `log` and `webhook` notifiers, `dirigent-storage-s3`, and
  `docker.run` as the first built-in asynchronous operator. Trigger declarations travel in a
  document's `triggers:` section and are materialised on apply, while operational state stays
  in the instance. *(Complete. The proof is a test at each level: the misfire policy and the
  advisory lock against a real PostgreSQL, the whole loop end to end through `dg` against a
  `dg dev` subprocess, and the three-service `infra/compose.yaml` brought up and driven.)*
- **Typed client.** `dirigent-client`: the pydantic schema of every request and response, a
  namespaced async accessor per resource, typed refusals, `runs.wait`, and an SSE log tail
  that reconnects. The server imports the schemas and the CLI runs on the accessors, so the
  contract has one definition. *(Complete. The proof is a test suite against a mock transport
  plus one that drives the real application in process over ASGI, and six runnable scripts in
  `examples/python/` executed against a real instance in CI.)*
- **M3 - UI.** Builder, schema-driven forms, run DAG view with item grid and SSE logs,
  triggers and alerting pages, frontend-in-wheel packaging. *(Complete. The proof is a
  browser suite driving a real `dg dev`, plus `docs/ui-conventions.md`, which the gate
  scripts and the `ui-review` skill check every change against.)*
- **M3 follow-ons.** The editor grows toward the node-editor direction on the design
  boards: typed ports drawing a `${steps.x.output}` reference as a data wire distinct from a
  bare `depends_on` edge.
- **M4 - Adapter packs.** Domain plugin packages with fresh clients and a nightly
  contract-test lane.
- **M5 - Hardening.** Log batching under load, OTel exporter polish and reference
  dashboards, notifier channel packages, operational docs, poll-loop load test.
  Retention landed early, ahead of this milestone.

## 17. Vocabulary

Names are API: they appear in the schema, the REST paths, the UI, and every conversation
about the system, and they are the hardest thing to change later.

| Dirigent | Meaning | Airflow | Prefect |
| --- | --- | --- | --- |
| Pipeline | A coded, versioned definition: steps, edges, parameter schema, concurrency policy. Data, composed in the UI. | DAG (a Python file) | Flow + Deployment |
| Run | One execution of a pipeline version with resolved parameters and an attributed trigger. | DAG Run | Flow run |
| Step | One node in the pipeline's DAG: a block reference plus config, edges, retry policy. | Task | Task |
| StepAttempt | One try of one step: own row, own logs, immutable step snapshot, kind automatic or manual. | Task instance try | Retry counter, not a record |
| RunItem | One element of a fan-out step's mapped input, with its own status and retry. | Mapped task instance | `.map()` subtask |
| Block | Collective term for the pluggable building blocks: operators and sensors. | Operator classes | **Collision:** Prefect "Block" is a typed credential record, which is our Connection |
| Operator | A block that does work; may finish synchronously or return a `RemoteHandle`. | Operator | A task function |
| Sensor | A block that waits for the world, in-DAG, via durable pokes. | Sensor (ours always deferrable) | **Collision:** Dagster "sensor" starts runs, which is our Trigger |
| Connection | Named, encrypted credential and settings record of a contributed kind. | Connection | Block |
| Trigger | What starts runs: ad hoc, Schedule, or Webhook. | Schedule/timetable | Deployment schedules |
| Trigger rule | Edge condition for step readiness. | `trigger_rule` (same values, deliberately) | Control flow in code |
| Concurrency policy | Per pipeline: `allow` / `skip` / `queue` / `replace`. | `max_active_runs` | Concurrency limits |
| ArtifactRef | A step output passed by URI through pluggable storage. | XCom (small values only) | Results and artifacts |

Engine and plugin terms:

| Term | Definition |
| --- | --- |
| DAG | Steps are nodes, `depends_on` edges point from prerequisite to dependent, no path loops back. Parallelism is implicit; acyclicity is validated at save time. |
| Fan-out | A step mapped over a list, producing one `RunItem` per element, isolated for status and retry. The DAG shape stays fixed; only item cardinality is dynamic. |
| RemoteHandle | The frozen, serializable claim on submitted remote work. Committed the moment `execute` returns. |
| Probe / poke | One side-effect-free check of remote work (operator) or a world condition (sensor), scheduled by `next_poll_at`, executed by any free worker. |
| `waiting` | The attempt state of work that is not running on a worker and will be re-examined when `next_poll_at` comes due: an operator's submitted job, or a sensor between pokes. Durable rows, not held workers: the engine's center of gravity. |
| Lease | Heartbeat timestamp on a claimed attempt; expiry means the worker died and the sweeper recovers the attempt. |
| Lost-job policy | Deadline plus fail-after-N-consecutive-`GONE`-probes: a remote system that forgot its job produces a failed step and an alert, never a hang. |
| Error class | Block-assigned failure category driving retry: `rejected` is never retried, and `transient` and `unknown` both spend the step's retry budget. |
| Catalog | The server's merged view of every plugin contribution, served at `/api/v1/blocks` and consumed by the UI to render forms. |
| Contribution | What one plugin adds across the five surfaces, returned by its `contribute()` hook under the `dirigent.plugins.v1` entry-point group. |
| Scratch space | Run-scoped URI prefix on the default storage backend for intermediate artifacts. Swept with the run it belongs to, once `retention_runs` is set. |
| `triggered_by` | Foreign key on every run to the user, schedule, webhook, or token that started it: attribution as data, not free text. |

Naming stance in one line: where an existing term is dominant and means the same thing, reuse
it exactly; where the dominant terms conflict or mislead, pick the boring word and document
the collision here.
