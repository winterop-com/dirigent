# Releases

What changed between versions, and what an upgrade has to know. The newest release is first.
A release is a tag on this repository, the packages on PyPI, and an image at
`ghcr.io/winterop-com/dirigent:<version>`; an instance runs the checkout, the image built from
it, or the published one.

Versions before 0.9.0 were developed in private and are listed here for the record.

**How a release is cut.** Every package in this workspace, `dirigent-dhis2` and
`dirigent-integration` move to the same number together. The notes land here first, at the
top; the bump merges; the merge commit is tagged `vX.Y.Z` and published as a GitHub release
with the same notes. The tag is what publishes: `.github/workflows/release.yaml` builds every
package and uploads it to PyPI through trusted publishing, then builds the image from that
commit and pushes it as `<version>` and `latest`. The two sibling repositories then relock
against the tag and bump.

## 0.9.3

Released 2026-09-09. Every package in the workspace moves to 0.9.3 together.

### Before you upgrade

Nothing in the schema, the wire or the settings changed since 0.9.2.

### Command line

- **`dg init` puts the token in the project's `.env`.** The first admin's token is written
  to `.env` with owner-only permissions, every template's root `.gitignore` covers `.env`,
  and the `local` profile reads it from there: nothing has to be exported before `dg apply`.
- **A profile's `token_env` falls back to the project's `.env`.** Any `DG_*` variable the
  shell does not set is read from the `.env` beside `.dirigent/`; the shell's value wins.
- **`dg init` says where the instance is and how to start it.** The closing text names the
  directory, the second terminal `uv run dg dev --keep-state` needs, and the UI's address.
- **A refused connection to a loopback address says the local instance is not running**, and
  which command starts it.

## 0.9.2

Released 2026-09-09. Every package in the workspace moves to 0.9.2 together.

### Before you upgrade

Nothing in the schema, the wire or the settings changed since 0.9.1.

**The server wheel on PyPI carries the web UI.** The 0.9.0 and 0.9.1 wheels shipped without
the bundle, so `dg dev` from a PyPI install answered that no bundle was built; the release
now puts the bundle where the wheel packages it and refuses a server wheel without it.

### Command line

- **`dg init` refuses a short password before writing anything.** The length is checked where
  the password is resolved, so a refusal leaves no half-made project.
- **`dg init` refuses in plain words.** An init that renders writes one sentence on stderr,
  with any hints under it; `--json` still gets the `error` record.

### Blocks

- **The docker CLI finds its plugins on any host.** `docker.build` and `docker.compose.*` run
  the CLI with the run's directory as its home, and the docker config written there names the
  worker's own `cli-plugins` directory, so `buildx` and `compose` resolve where Docker Desktop
  installs them as well as where a package does.

### Examples

- The sql examples' sqlite connection is `work-db`, named for where it lives.

## 0.9.1

Released 2026-09-09. Every package in the workspace moves to 0.9.1 together.

### Before you upgrade

Nothing in the schema, the wire or the settings changed since 0.9.0.

**The image is built for amd64 and arm64.** One multi-platform manifest per release, on
docker's reusable builder, tagged with the version and `latest`; a scaffolded stack on an
Apple Silicon host no longer runs the image under emulation.

**Every package publishes from its own environment.** The release workflow publishes each
package to PyPI from `pypi-<package>`, which is how PyPI ties a trusted publisher to one
project.

### Blocks

- **A `docker.run` output without a URI scheme lands in the run's work directory**, where
  `docker.build` and `docker.compose.up` read; a URI still goes to storage.

### Documentation

- **Work directory, not scratch.** Every docstring, refusal message, example and page that
  described a tool's path as living in scratch now says the work directory, which is where
  the build context, the compose file, a checkout, a shell's working directory and a relative
  database file resolve.
- **The pack-authoring guide's worked example is a vendor with no domain**, Acme, and the
  DHIS2-shaped examples live with dirigent-dhis2.

## 0.9.0

Released 2026-09-09. The first public release: every package in the workspace moves to 0.9.0
together, the packages are published to PyPI, and the image is
`ghcr.io/winterop-com/dirigent:0.9.0`.

### Before you upgrade

Nothing in the schema, the wire or the settings changed since 0.8.1.

**The runtime installs from PyPI.** `uv tool install dirigent-cli` is the whole install. A
project `dg init` writes pins `dirigent-cli==0.9.0` in its `pyproject.toml` with no git
source, and the scaffolded stack's Dockerfile adds a pack with one line,
`RUN uv pip install dirigent-dhis2==0.9.0`. A project scaffolded by 0.8.x still carries the
git source and the secret-mount recipe; both keep working, and a re-scaffold drops them.

**The examples corpus shrank.** The climate shelf and the CHAP preview are gone; a document
that referenced one of their connections is refused at apply with the connection named.

### Publishing

- **A `v*` tag releases.** `.github/workflows/release.yaml` checks the tag against every
  package version, builds the UI bundle and every wheel and sdist, publishes them to PyPI by
  trusted publishing, and pushes the image to GHCR. `make docker-push` stays for a release cut
  by hand.
- **The docs publish on push to `main`** through `.github/workflows/pages.yaml`.
- **What the wheel redistributes is attributed.** `THIRD_PARTY_NOTICES.md` carries the
  notices for the UI bundle's dependencies and fonts, and ships in the server wheel.

## 0.8.1

Released 2026-09-08. Every package in the workspace moves to 0.8.1 together; the image is
republished as `ghcr.io/winterop-com/dirigent:0.8.1`.

### Before you upgrade

Nothing: no schema, wire or setting changed. Two things the 0.8.0 CLI got wrong on the path
`dg init --template compose` opens are fixed, so a stack scaffolded by 0.8.0 is best
re-scaffolded from 0.8.1, or its `Dockerfile` and `compose.yaml` replaced with the new ones.

### Command line

- **`dg auth login` runs under a profile whose token is not set yet.** The scaffolded profile
  reads `DG_TOKEN`, and login is the command that mints it; it no longer refuses on the token
  being absent.
- **The pack recipe in the scaffolded `Dockerfile` builds.** `compose.yaml` declares the build
  secret from `GITHUB_TOKEN` in the shell, the secret mount names the image's uid, git reads the
  token through its environment for that one command, and `uv pip install --no-sources` keeps
  the dirigent packages the image carries. `dirigent-dhis2` declares its own git dependency as
  a direct reference, so it installs into the image with one line.

### Ecosystem

- **A release is tagged and published in every repository.** `dirigent-dhis2` and
  `dirigent-integration` carry the same version, a `vX.Y.Z` tag and a GitHub release beside
  this one.

## 0.8.0

Released 2026-09-08. Every package in the workspace moves to 0.8.0 together, and this is the
first release with a published image.

### Before you upgrade

**The schema did not change.** A 0.7.0 database runs 0.8.0 as it is.

**The image is published, and it is a base.** `ghcr.io/winterop-com/dirigent:0.8.0` and
`:latest` are pushed by `make docker-push` from the tagged commit, stamped with
`org.opencontainers.image.version` and `.revision`. The runtime stage now carries `uv` and
names its venv through `VIRTUAL_ENV`, so a derived image installs a pack with one line:

```dockerfile
FROM ghcr.io/winterop-com/dirigent:0.8.0
RUN uv pip install dirigent-dhis2
```

`infra/compose.yaml` passes `DIRIGENT_VERSION` and `DIRIGENT_REVISION`
as build arguments; a checkout that builds its own image is otherwise unchanged.

### Getting started

- **`dg init DIR --template compose` writes a container deployment.** The five project files,
  a `compose.yaml` that mirrors the stack in this repository and builds this instance's image
  `FROM` the published one at the version of the `dg` that wrote it, a `Dockerfile` with the
  pack recipe commented out, a `.env` with a generated instance key and the first admin's
  password, and a `.gitignore` that keeps it out of git. The instance is the containers: no
  state directory, no local admin, no token. `docker compose up -d`,
  `dg auth login --username admin`, and a document in `pipelines/` lands at boot.
- **Adding a pack is editing that Dockerfile** and `docker compose up --build`.

### Documentation

- **"The image"** in the operations guide: what it carries and how to build on it.
- **"How a release is cut"** on this page: every repository in the ecosystem moves to the
  same number, the tag, the GitHub release, and the image push.

## 0.7.0

Released 2026-09-08. Every package in the workspace moves to 0.7.0 together.

### Before you upgrade

**The schema changed.** `users.email` is unique. The baseline migration is edited in place
while nothing has shipped, so a database created before 0.7.0 does not get the constraint from
`dg db upgrade`; either recreate the database or add it by hand:

```sql
ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email);
```

Two accounts that already share an address have to be told apart first.

**A role is named on every account.** `POST /api/v1/users` refuses a body without `role`, the
SDK's `Users.create` requires it, and `dg admin user create NAME --role admin|operator|viewer`
replaces `--admin/--no-admin`. Nothing defaults to admin, operator or viewer any more.

**The wire changed.** `TokenOut` and `IssuedTokenOut` carry `username`. `DELETE /api/v1/tokens/{name}`
revokes only the caller's own tokens of that name; `GET`, `POST` and `DELETE` under
`/api/v1/users/{username}/tokens` are the admin's path over any account.
`POST /api/v1/users/{username}/$reset-password` is new, and `PATCH /api/v1/users/{username}`
takes `email`, validated and cleared with null. The SDK gains `Users.reset_password`,
`Users.tokens`, `Users.create_token` and `Users.revoke_token`.

**Every single read is a record.** `dg pipeline show`, `dg blocks show`, `dg connection show`,
`dg schema show`, `dg trigger-document show`, `dg system info`, `dg runs show`, `dg runs report`
and `dg export --json` no longer print a bare document: each writes one record with a `kind`
and the thing under `fields`, so a `jq` path that read `.run.status` now reads
`.fields.run.status`. `dg schema create`, `dg admin token create`, `dg webhook create` and
`dg webhook rotate-token` write `schema.created`, `token.issued`, `webhook.created` and
`webhook.token_rotated` facts. The record catalogue in `docs/cli.md` lists every kind.

### Accounts

- **An admin resets any account's password**: `dg admin user password NAME`, or the
  `Reset password` button in the account panel. Every session of the account ends; its API tokens
  keep working.
- **A token belongs to an account, and the screen says so.** The tokens table carries an
  `Account` column, a revoked row says `revoked` instead of offering a button that can only fail,
  and the account panel mints a token for that account. `dg admin token create NAME --user U` and
  `dg admin token revoke NAME --user U` do the same from the terminal.
- **Email is validated, unique and editable**, in the create dialog, the account panel,
  `dg admin user create --email`, and `PATCH /users/{username}`.
- **`dg auth status`** is what the server guide names, and `dg auth login` emits the token it
  minted rather than writing it anywhere.

### Documentation

- **The site nav is five sections**: Start here, Using it, Blocks, Running it, The project.

### Roadmap

- Scoped authorization stays an open question: user groups, projects as a scope below the
  instance, and grants inside one. The account model this release closes out is what a scope
  would attach to.

## 0.6.0

Released 2026-09-08. Every package in the workspace moves to 0.6.0 together.

### Before you upgrade

**The schema changed.** `alert_rules` gains a `paused` column. The baseline migration is edited in
place while nothing has shipped, so a database created before 0.6.0 does not get it from `dg db
upgrade`; either recreate the database or add the column by hand:

```sql
ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS paused boolean NOT NULL DEFAULT false;
```

Without it every attempt outcome fails while the engine evaluates alert rules, and runs hang.

**The compose stack keeps artifacts in object storage.** `infra/compose.s3.yaml` is gone: the
`s3` and `s3-bucket` services are part of `infra/compose.yaml`, `DIRIGENT_ARTIFACT_ROOT` on the
stack is the bucket, the `artifacts` volume is replaced by a `work` volume, and the `migrate`
service runs `dg connection ensure` so the `artifacts` connection exists before the first run.
Artifacts written to the old volume are not reachable from the new stack. `file://` stays the
default outside Docker, and a single node on it is legitimate.

**One setting is new.** `work_root` (default `./.dirigent/state/work`) is the worker-local
directory a checkout, a build context, a compose file or a bind mount lives in; `${run.scratch}`
stays on the artifact root, which may be a bucket. A block that needed a `file://` scratch now
works on the work directory instead.

**The wire changed.** `AttemptOut` carries `created_at`, `available_at`, `deadline_at`,
`heartbeat_at` and `poke_count`. `AlertRuleOut` carries `paused` and `connection`;
`PATCH /api/v1/alert-rules/{code}` takes `AlertRuleUpdate`. `NotificationOut` carries `rule`,
`connection`, `max_attempts`, `run_pipeline` and `run_started_at`; `GET /notifications/{id}` and
`POST /notifications/{id}/$retry` are new. `webhook` is a connection kind.

**Every command writes a record.** `dg version`, `dg config show`, `dg db`, `dg validate`,
`dg auth login`, `dg init` and every mutation that only drew a sentence before now write NDJSON
by default, and a refusal is written to standard output as an `error` record in both spellings.
`token.revoked` names the token by `code`, not `token`. `-p` addresses an array element:
`-p regions[0]=east`, `-p regions[]=north`; a bare `regions.0` is refused naming the bracket form.

**Two dependencies are new.** `dirigent-blocks` requires `pyyaml`; the worker image installs
DuckDB's `httpfs` extension at build time, and a bare worker that reads a bucket through DuckDB
runs `INSTALL httpfs` once.

**A plugin author's context grew.** `ctx.work` is the run's local work directory and
`ctx.storage_connection(scheme, model)` answers which connection serves a storage scheme.

### Alerting

- **The alerting screen says where an alert goes and whether it arrived.** A channel strip shows
  every notifier with its connection and last health check; the rules table shows event, scope,
  channel, throttle and state; choosing a rule opens its panel with Pause, Send a test and Delete;
  a New rule dialog creates one from the screen; the notifications table filters by status and
  notifier and names a run by pipeline and start time; a notification's panel carries the attempt
  count, the last refusal and Retry now.
- **Send a test picks a notifier from the installed kinds and a connection of that kind**, and
  stays open while the row moves through queued, sending and sent or failed.
- **Any rule can be paused from the screen**, and the pause survives a re-apply of its document.
- **Somewhere for email and webhook to land**: `infra/compose.sinks.yaml` adds Mailpit and an HTTP
  sink on the stack's network, `make docker-run-sinks`, and every channel was proven end to end.
  Proving it fixed six blockers: there was no `webhook` connection kind, a `#channel` value read
  as a YAML comment, an unset optional secret refused the whole command, an empty bearer token
  built an illegal header, deleting a referenced connection answered 500, and `dg connection
  check` wrote nothing in records mode.
- `dg alerts rules pause|resume CODE` and `dg alerts retry NOTIFICATION`.

### Storage

- **Object storage is always on the compose stack**, bootstrapped by `migrate` through the new
  `dg connection ensure KIND CODE --set k=v`, which writes the row directly and idempotently, sealing
  secrets as the API does.
- **Scratch and work are two places.** Shared intermediates go to the artifact root; a checkout,
  a build context, a compose file or a bind mount goes to the worker's `work_root`, and each
  worker sweeps its own work directories on the retention interval.
- **DuckDB reads and writes the bucket** through httpfs with the credentials of the connection
  bound to the `s3` scheme, so `${run.scratch}/readings.parquet` on a bucket root opens directly.
- `examples/s3/*` name the stack's `artifacts` connection, so the same documents seed on the stack
  and under `dg dev`.

### Blocks

- **DuckDB is the second engine of the `sql` family**, driven through a worker thread with a real
  interrupt on cancel; optional extra `dirigent-blocks[duckdb]`, shipped in the image.
- **YAML and XML on `convert.std`**, thirteen pairs in all; attributes map to `@name`, repeated
  tags to lists, a DOCTYPE is refused in both directions, and XML streams without a DOM.
- **`kafka.produce`** sends records to a topic with bounded in-flight sends and reports
  `sent_bytes`.
- A Kafka sensor keeps its place across pokes; `git.checkout` streams its clone.

### Runs

- **`dg runs show` says where each step's time went**: queued, running and waiting per attempt,
  with one definition shared by the CLI and the run screen.
- **`dg runs profile RUN`** emits the critical path, the split along it, and warnings the
  timestamps prove: a probe cadence longer than the work, a deadline far above the observed wait,
  a fan-out that ran serially.
- The step tab shows queued and waiting, folded away when they merely repeat the step's duration.

### Command line

- **Every command writes a record**, with the recipe in `docs/conventions.md` under "Giving a
  command a record"; the CLI tests assert on records, and the few rendering tests call the
  formatter directly.
- **Formatters are a pluginkit extension point**: a package contributes a `Formatter` and `dg`
  finds it.
- **`-p` addresses an array element.**

### Telemetry and infrastructure

- The Grafana dashboard names every worker and carries a fleet table; runs by terminal status is
  a cumulative sum, so it never undercounts a new series.
- `infra/compose.brokers.yaml` and `infra/compose.sql.yaml` overlays; the warehouse seed lives at
  `examples/sql/warehouse.sql`.
- The Pipelines list keeps the name column ahead of tags at every width.

### Roadmap

- Provisioning is written down: one Ansible play that applies dirigent to any host in the
  inventory, machine creation as an optional per-provider play, Incus with nested Docker and LXD
  without it, and a fresh-host test lane per host shape.
- Tags as things, tag groups and a vocabulary are an open question; `dg validate --explain` is the
  remaining want of the slow-pipeline entry.

## 0.5.0

Released 2026-09-07. Every package in the workspace moves to 0.5.0 together.

### Before you upgrade

**The schema did not change.** A 0.4.0 database carries forward as it is.

**Three settings are new**, all defaulted, so nothing needs setting to upgrade:

| Setting | Default | What it decides |
| --- | --- | --- |
| `log_flush_interval` | `1s` | How often a running step's buffered log reaches the run |
| `log_flush_batch` | `100` | How many buffered entries flush without waiting for the interval |
| `log_entries_per_attempt` | `1000` | How many entries one attempt may log before the rest are dropped with one warning |

**The published JSON Schema spells durations humanely.** A duration is a `string` with
`format: humane-duration`, its default reads `5m` rather than `PT5M`, and the `gt`, `ge`, `lt`
and `le` bounds no longer appear. A consumer of the block catalog or the settings schema that
parsed ISO 8601 durations must read the humane grammar instead.

**Two block outputs and one argv changed.** `git.checkout` answers `stdout_uri` and
`stderr_uri` beside the commit; the compose blocks pass `--project-name` where they passed `-p`.
A block author calling `capture.log_stream` hands it the `Drained` ends rather than two byte
strings.

**One example moved.** `examples/open-data/reliefweb-country-updates.yaml` is gone and
`examples/open-data/gdacs-disaster-updates.yaml` teaches its lesson on a keyless source.

### Engine and blocks

- **A process's output reaches the run as it prints.** The first lines of `shell.run`,
  `docker.build`, `docker.compose.up`, `docker.compose.down` and now `git.checkout` land in
  the run log with their own timestamps while the process runs; the tail lands at the end
  without repeating, the whole stream is the artifact, and a secret handed to the process never
  reaches a line. `docker.run` keeps its per-probe cadence.
- **A step's log is flushed while the attempt runs**, every `log_flush_interval` and at
  `log_flush_batch` entries, each flush its own transaction with ordering kept and no duplicates
  on a failed attempt. The buffer holds plain rows, so a log call costs about a microsecond
  where it cost seven. Measured on the new load lane: 23,600 rows a second, flush p95 30ms,
  a line visible within 0.28s at p95.
- **A Kafka sensor keeps its place.** Starting at `latest`, a poke that finds an empty topic
  records where it stood, and in a consumer group a parked poke carries its positions in the
  cursor, so a message arriving between pokes is read by the next one; a capped batch no longer
  skips the records it fetched but did not read.
- **Every block on the subprocess helper gets an absolute working directory**, so a checkout, a
  shell command, a compose stack or a bind mount works under `dg dev`'s relative artifact root.
- **The plugin host collects through pluginkit's attributed caller.** Contributions come back
  named for the plugin that made them through `collect_with_plugins`, the hand-rolled marker
  walk is gone, and the tested path is the running path.
- **Durations are published humanely** in the catalog and the settings reference, under a
  format of our own, `humane-duration`.

### Telemetry

- **A compose overlay you can look at**: `infra/compose.otel.yaml` brings up an OTLP
  collector, Prometheus, Tempo and Grafana with a provisioned dashboard, runs by status, step
  duration by block, queue depth, waiting, in flight by worker, scheduler lag, worker heartbeat
  age, and a run's spans found by its id. `make docker-run-otel`; Grafana on `127.0.0.1:3300`.
- **Two instruments are new**, `dirigent.scheduler.lag` and `dirigent.worker.heartbeat_age`,
  and every process names itself with `service.instance.id` so two workers never collide.
- **The duration histograms carry their own bucket edges**, from 5ms to 15 minutes, so a
  sub-second step reads as what it took.

### Infrastructure

- **Overlays for brokers and a warehouse**: `infra/compose.brokers.yaml` puts Redpanda and
  RabbitMQ on the stack's network and `infra/compose.sql.yaml` adds a seeded PostgreSQL
  warehouse with reader and writer roles, each header carrying the connection commands.
  `make docker-run-queues`, `docker-run-sql`, `docker-run-all`.
- **A load lane**: `make load` measures the log path against a real PostgreSQL, fifty chatty
  attempts on two workers, and prints one `load` record per number. It never runs in the gate.

### Web UI

- **The Settings dialog is settled**: three groups, no gloss under a heading or a row, About
  folded into Server, the palette chosen from swatch cards, a password changed inline.
- **A new schedule or webhook is easier to declare right.** The pipeline is a picker with its
  code beside its name; the clock is a segmented choice with the next three firings read from
  a new `POST /api/v1/schedules/$preview`; the timezone is a picker with its offset; priority
  is a field defaulting to the pipeline's; the pinned parameters are the pipeline's own form
  with a JSON toggle; a webhook's payload mapping is one JSONPath per declared parameter and its
  secret can be generated in place.
- **An ad hoc run can be given its window.** The Run dialog carries Start and End, required
  when the document reads `run.window`, optional behind a link otherwise; Re-run carries the
  window of the run it repeats; the run header reads a window as its two instants.
- **A code window wears the same hues as the block beside it.**

### Command line

- **`dg run --local --root DIR`** keeps a local run's instance in a directory across runs, so
  a marker-file pattern can be rehearsed day by day from the CLI.

### Examples and documentation

- The open-data shelf teaches the daily dedup on GDACS, and its README says which documents
  were proven end to end and which stop at a credential.
- The example corpus writes each tag one way (`schedule`, `sensor`), and the roadmap carries
  tags as things, with groups and a vocabulary, as an open question.
- `docs/telemetry.md` gains "Bring it up in an afternoon"; `docs/queues.md`, `docs/sql.md` and
  `docs/server.md` name the overlays; `docs/operations.md` states what one worker sustains.

## 0.4.0

Released 2026-09-06. Every package in the workspace moves to 0.4.0 together.

### Before you upgrade

**The schema did not change.** A 0.3.0 database carries forward as it is.

**Twelve settings are renamed.** Each loses its `_seconds` suffix and takes a humane duration
(`30s`, `5m`) in place of a number, and the `DIRIGENT_*` environment name follows the field. A
value under an old name is refused at start.

| 0.3.0 | 0.4.0 |
| --- | --- |
| `claim_idle_seconds` | `claim_idle` |
| `database_pool_recycle_seconds` | `database_pool_recycle`; unset disables recycling, where `-1` used to |
| `database_pool_timeout_seconds` | `database_pool_timeout` |
| `heartbeat_seconds` | `heartbeat` |
| `lease_seconds` | `lease` |
| `notification_backoff_seconds` | `notification_backoff` |
| `notification_lease_seconds` | `notification_lease` |
| `scheduler_misfire_grace_seconds` | `scheduler_misfire_grace` |
| `scheduler_tick_seconds` | `scheduler_tick` |
| `stale_worker_seconds` | `stale_worker` |
| `stuck_run_seconds` | `stuck_run` |
| `sweep_interval_seconds` | `sweep_interval` |

**Block and connection config fields are renamed the same way**, and a document carrying an old
name is refused at validation: `timeout_seconds` becomes `timeout` on `shell.run`, `docker.build`,
`git.checkout`, `docker.compose.up`, `docker.compose.down`, the webhook, Slack and email notifiers,
an `http.request` target and the shared http connection; `api_timeout_seconds` becomes
`api_timeout` on the compose blocks and `docker.run`; `pull_timeout_seconds` becomes
`pull_timeout` on `docker.run`. Every example under `examples/` is already rewritten.

**Every CLI listing is a record stream.** `dg pipelines list`, `dg runs list`, `dg schedules`,
`dg users` and every other listing emit one NDJSON record per row, with a `kind` and the row
under `fields`, where 0.3.0 printed one indented JSON array; a single read prints one compact
line. A script that parsed the array reads lines now, and `jq` selects `.fields.<name>`.

### Documents and the apply directory

- **A directory apply stores the schemas it finds.** A plain JSON Schema file beside the
  documents (`examples/schemas/*.json` on the compose stack) is stored first, the way
  `dg schema create` stores it, so a pipeline whose `requires.schemas` names one converges in
  the same pass. Prune never touches a schema.

### Blocks

- **`sql.execute` carries a `timeout`**, default `5m`, with the same contract as `sql.query`: a
  statement timeout inside the transaction and a deadline on the worker.
- **Block summaries render as markdown** in the catalog, the same way field descriptions do.

### Engine and server

- **Every SQLite transaction opens immediate**, with a 15s busy timeout, so `dg dev` no longer
  answers 500 "database is locked" when a worker claims while a document is applied.
- **The run stream sends a run frame on every state change**, so a run screen's status moves to
  `running` the moment a worker claims it rather than when it settles.
- **A refused write says one sentence.** A role that may not do something is told
  `not permitted for your role`, and nothing more.
- **Block descriptions render as markdown** everywhere the catalog is read: the docstrings are
  reStructuredText and are rewritten once at the catalog boundary.

### Web UI

- **Every screen is usable on a phone.** Below 768px the sidebar is a drawer, listings are cards,
  the breadcrumb shows its leaf with the trail on hover, toolbars fold secondary actions into a
  menu, dialogs are full-height sheets, and the editor is read-only with its panel as a bottom
  sheet. Listings stay cards up to 1024px, where the column beside the rail is a phone's width.
  Every tap target is at least 40px.
- **The login door lays its graph out to the pane**: the drawing fits the width first, rows
  stretch by at most a third, and the pane itself grows with the window to 1056px, where the
  graph reaches its largest scale. The head node wears the completed-with-errors status token,
  the eyebrow is set in the accent, the form is centred in its column, and the lockup is one
  size from tablet up. The seam between the two panes is a drag handle, drawn as nothing
  until a pointer or a focus ring finds it, bounded by the pane's limits, kept per browser, and
  reset by a double-click.
- **A viewer sees what a viewer may do**: every verb a viewer's role refuses is shut on screen
  rather than refused after the click, and a refusal that does arrive is stated beside the form
  or the row that asked.
- **Listings and the run screen** say what a count counts, close a filter menu on its choice,
  draw no id suffix anywhere, and state empty cells as nothing rather than as a dash. A run is
  named by when it started; a trigger row is two fixed lines; the run dialog is titled `Run`
  over the pipeline's name; a run's two durations are the queue wait and the work.
- **The radius ladder** is 4px for a chip, 6px for a control or a card and 8px for a panel.
- A picked file opens its editor on the source pane; a new document opens on the step tab.

### Command line

- **`--priority`** on `dg schedule create` and `dg webhook create`, the same word the document
  and the API take.
- The `dg dev` account is stated in the docs: `dev` with the password `dirigent-dev`, beside the
  compose stack's `admin` from `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`.

### Documentation

Every page was brought level with what shipped in 0.3.0: the CLI's streaming record table names
the kinds the CLI emits, the triggers document has a worked example, the compose worker's tag and
the reaper settings are on the operations page, and the roadmap carries only what is still ahead.

## 0.3.0

Released 2026-09-06. Every package in the workspace moves to 0.3.0 together.

### Before you upgrade

**The schema changed.** There is still one migration, edited in place, so a database created
by 0.2.0 is not carried forward by alembic: recreate it, or apply the new columns and table by
hand. The additions are one table, `trigger_documents`, and these columns:

| Table | Column | What it holds |
| --- | --- | --- |
| `schedules`, `webhook_triggers` | `trigger_document_id` | Which triggers document owns the row, or null for the pipeline's own document or a hand-made row |
| `schedules`, `webhook_triggers` | `priority` | The word a schedule or webhook pins on the runs it starts, or null to take the pipeline's |
| `step_attempts` | `poke_cursor` | Where a sensor's poke has read to, carried between pokes |
| `runs` | `worker_tags` | The tags a worker must carry to claim the run, pinned at creation |
| `runs` | `priority` | `low`, `normal` or `high`, pinned at creation |

**The block catalog grew.** New block ids and connection kinds are listed below; documents that
use them need an instance running 0.3.0, and the worker image now carries `git`,
`openssh-client` and the compose and buildx plugins.

**Two settings are new**, both for the compose-stack reaper: `docker_reap_interval` and
`docker_reap_grace`. Both have defaults and neither needs setting to upgrade.

### Documents

- **A `kind: triggers` document** declares schedules and webhooks for a pipeline defined
  elsewhere. It is applied like a pipeline document, owns the rows it creates, never touches
  the pipeline's inline triggers or a hand-made one, and is listed, read and deleted at
  `/trigger-documents` and with `dg trigger-document`. A directory apply orders pipelines before
  triggers documents.
- **`$${...}` is the escape** for a literal `${...}` in any string the resolver reads.
- **A webhook's `params_from_payload` is checked when it is declared**: every path parses, every
  name is a declared parameter, and every required parameter without a default is mapped.
- **`requires.workers`** names the tags a worker must carry to claim the pipeline's runs.
- **`priority`** on a pipeline, a schedule, a webhook or an ad hoc run, layered like parameters.
- **Tags are lowercased at validation** and must match `[a-z0-9][a-z0-9-]*`. Several tags
  narrow a listing, and the runs listing filters by its pipeline's tags too.

### Engine

- **Claims route by worker tags** and order by priority, then round-robin between runs, then
  due time, so a large fan-out no longer starves a small run and a `high` run goes first the
  moment a slot frees.
- **A sensor's poke keeps a cursor** between pokes, stored with the parked attempt and carried
  at-least-once like an operator's probe.
- **`dg worker --tag`** and `DIRIGENT_WORKER_TAGS` put tags on a worker; the compose stack's
  worker carries `docker`.

### Blocks and connection kinds

- **`git.checkout`** and a `git` connection kind: a repository at a branch, tag or commit into
  the run's scratch space, with a token or an SSH key that never reaches argv or the checkout.
- **`sql.query` and `sql.execute`** and a `sql` connection kind, with parameters bound rather
  than interpolated, a `read_only` mode the database enforces, and large results streamed to
  storage as NDJSON.
- **`kafka.consume` and `rabbitmq.consume`** sensors with their connection kinds, tested
  against real brokers in a new CI lane.
- **A `docker` connection kind** for a remote daemon and a registry credential, `push` on
  `docker.build`, an optional `connection` on every docker block, and a reaper that tears down
  compose stacks a dead run left behind, on the worker and as `dg docker reap`.
- **`http.request` streams a request body from storage** with `body_from`.
- **Slack and email notifiers**, each also a connection kind, so an alert rule delivers through
  a connection created from the CLI, the API or the UI.

### Web UI

- **A new login door**: a lit run graph as the brand, a greeting form with a password reveal, a
  bounded pane that stops growing on wide displays, and the lockup held a fixed distance from
  the graph at any height.
- **Two more palettes**, paper and contrast, beside the default, chosen on the settings
  dialog's Theme pane.
- **A live run's edges carry its data**: an edge animates while its downstream step consumes,
  pulses once as an artifact hands over, and stills when both sides settle; reduced motion
  shows a lit edge instead.
- **Tag chips** filter the pipelines table by click, the filter lives in the address, and the
  runs page carries the same control.
- A run waiting for a worker carrying a tag says so, and a `high` or `low` run wears its
  priority on the run header.

### Examples

Every shelf under `examples/` carries a README. The docker shelf grew to eleven documents that
run for real in CI, and `git/`, `sql/` and `queues/` are new. `examples/triggers/document-nightly.yaml`
is the triggers document taught beside the pipeline it schedules.

## 0.2.0

Released 2026-09-01. The identity quartet (`id`, `code`, `name`, `description`) on every
addressable thing, the M3 web UI, the design system in `docs/ui-conventions.md`, and the
first adapter pack moved out to its own repository.
