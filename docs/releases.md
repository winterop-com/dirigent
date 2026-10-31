# Releases

What changed between versions, and what an upgrade has to know. The newest release is first.
A release is a tag on this repository, the packages on PyPI, and an image at
`ghcr.io/winterop-com/dirigent:<version>`; an instance runs the checkout, the image built from
it, or the published one.

Versions before 0.9.0 were developed in private and are listed here for the record.

**How a release is cut.** Every package in this workspace, `dirigent-dhis2` and
`dirigent-integration` move to the same number together, and the sibling pins move with the
version: every package requires its dirigent dependencies at `==<version>`, so an installed
set can never mix two releases. The notes land here first, at the top; the bump merges; the
merge commit is tagged `vX.Y.Z` and published as a GitHub release with the same notes. The
tag is what publishes: `.github/workflows/release.yaml` builds every package and uploads it
to PyPI through trusted publishing and, once the `ghcr` environment allows it, builds the image
from that commit and pushes it as `<version>` and `latest`. The two sibling repositories then
relock against the tag and bump.

## Unreleased

**`DIRIGENT_SECRET_KEY` has to be a Fernet key.** A passphrase used to be turned into a key by one
unsalted SHA-256, which made envelopes in a database backup open to offline guessing. It is now
refused when the process starts, and an instance holding a Fernet key from `dg secret-key` has
nothing to do. An instance on a passphrase re-keys one of two ways:

1. **Re-enter the secrets, which is the one that removes the weakness.** Set a new key from
   `dg secret-key` on every process, then re-enter each connection's secret fields and each signed
   source's secret, following [Rotation, honestly](security.md#rotation-honestly). You need those
   secrets from wherever you keep them, since nothing can read them back.
2. **Keep the old key's bytes, to start the instance first.** The Fernet key the passphrase was
   already hashed into opens every existing envelope, so setting it brings the instance up with
   nothing re-entered:

   ```bash
   printf %s "$OLD_PASSPHRASE" | openssl dgst -sha256 -binary | base64 | tr '+/' '-_'
   ```

   This key is exactly as guessable as the passphrase, so treat it as a stopgap until step 1 is
   done.

**The schema changed, and `dg db upgrade` does not carry it.** The baseline migration is edited in
place, so an existing database gets none of `sources.secret_fingerprint`, the `source_signatures`
table or `step_attempts.lease_recoveries` from an upgrade. Recreate the database, or add them by
hand.

**Rotate any credential a wrong-kind connection reference may have exposed.** A step or source
naming a connection of another kind used to write that connection's decrypted secrets into attempts,
run logs, `last_error` and worker logs. It is now refused with `run.connection_wrong_kind`, but the
records already written are not rewritten.

**A signed call carries a timestamp, and its signature is taken once.** The signature is now
HMAC-SHA256 over `X-Dirigent-Timestamp`, a dot, and the raw body, and a timestamp outside
`source_signature_window` (5m by default) is refused.

- A sender that signs only the body, such as GitHub's `X-Hub-Signature-256`, can no longer call a
  signed source directly.
- `webhook.post` with `sign_with` signs the same way, so a receiver outside dirigent has to change.
- A sender retrying a 429 or a 503 has to sign again.

**Settings a project's own files can no longer set, and this one can move your data.** A working
directory's `.env` and `dirigent.yaml` no longer set `database_url`, `artifact_root`, `work_root`,
`storage_connections`, `host`, `ui_dir`, `secret_key_file`, `apply_dir`, `apply_prune`,
`alert_base_url`, the `retention_*` ages or the advisory-lock keys. An instance that relied on one of
them silently moves to its default, including SQLite for `database_url`. Set them in the process
environment, in the file `DIRIGENT_CONFIG_FILE` names, or in `~/.config/dirigent/dirigent.yaml`.
Compose already does. `dg dev`, `dg server` and `dg worker` warn about any that were ignored, and
`dg config show` lists them.

**A compose stack needs two new variables to start.** `POSTGRES_PASSWORD` and `S3_SECRET_KEY` are
required, and `dg init --template compose` generates both. An existing database and bucket keep
their old credentials, so set both to `dirigent`, then rotate.

**A state directory a checkout could have supplied is refused.** `dg dev` and every other command
that opens the database will not use a `.dirigent/state` that is a symlink, belongs to another user,
can be written by others, holds a link directly inside it, or is tracked by git. `--wipe-state` does
not delete through a link and leaves tracked state in place. New state directories are created
`0700`, and a group-writable one from before has to be cleared with `--wipe-state`. These rules
protect a separately installed `dg`: `uv run dg` runs the checkout's own pyproject first.

**A seeded instance no longer starts runs on its own.** `dg dev --seed`, `--seed-installed` and
`make dev-seeded` land polled and held sources (`sensor`, `storage`, `kafka`, `rabbitmq`) paused, the
way they land schedules, and endpoints stay live. `dg source resume PIPELINE CODE`, or Resume on the
Triggers screen, starts one. `dg apply --paused` covers the same sources, and a source the instance
already holds keeps its state.

**`pause_schedules` is now `paused`.** That covers `POST /pipelines/$apply`, `dg.pipelines.apply` and
the MCP `apply_document` tool. The old name is ignored rather than refused, so a script still sending
it gets live schedules and sources: change it.

**Other changes a deployment can notice.**

- Behind a proxy on another host, set `FORWARDED_ALLOW_IPS`. Login limits and the `Secure` cookie
  both read the caller's address and scheme from it.
- A project's profiles file can no longer set `token_cmd`, is ignored unless you own it, and cannot
  send a token from your shell to a non-loopback URL.
- The client refuses an identifier holding `/`, or one that is empty, `.` or `..`, before it sends
  anything.
- A pipeline whose endpoint serves scripted HTML stops working, because every reply is sandboxed,
  and reply headers such as `set-cookie` are refused.
- A connection's credentials go only to its own origin, so a step's absolute URL elsewhere is
  refused.
- `dg dev` creates its admin as `admin` / `admin` on an empty database, and only on a loopback
  address. On any other address it exits 3 while the state is empty or still holds that login, and
  that includes `dg dev` in the published image, which sets `DIRIGENT_HOST=0.0.0.0`.
- The unsafe-block allowlist no longer comes from a working directory's `.env` or `dirigent.yaml`.
  Set it in the process environment or in the file `DIRIGENT_CONFIG_FILE` names. Compose passes
  `.env` as environment, so a compose stack keeps working.
- `dg` reads a project's `.env` literally, so `${VAR}` stays those characters. It ignores a symlinked
  or group-writable `.env` or `.dirigent/profiles.yaml`.
- A `${...}` reference in `sql` or `statements` is refused at apply and when the step starts. Put it
  in `params`.
- A `read_only` DuckDB connection runs only SELECT, so a step writing run files through one needs a
  writable connection.
- `git.checkout` and the docker blocks write credentials to the system temporary directory, which
  has to allow executing a file. A worker with a `noexec` `/tmp` sets `TMPDIR`.
- A step's `Host` beside a connection has to match the connection's origin, so an IP `base_url` with
  a routing `Host` stops working.
- Shell arithmetic is found regardless of quoting, and a literal unclosed `((` or `$[` needs an
  integer reference until it closes.
- `convert.std` also bounds the text YAML aliases add, at 16 MiB, and its limits count across a whole
  stream. Writing CSV refuses more than 10,000 columns or 10 million empty cells.
- An endpoint source holds no database connection while it reads a body, and answers 408 to a body
  not whole within `DIRIGENT_SOURCE_BODY_TIMEOUT` (30s by default). A slow sender with a large
  `max_body` may need that raised.
- An endpoint source decodes a text body only from UTF-8, UTF-16, ASCII, ISO-8859-1 or Windows-1252,
  and answers 415 to any other `charset`.
- `DIRIGENT_SOURCE_INTAKE_RATE_PER_MINUTE` counts per caller address, method and route, so calls from
  one address to one templated route share a count across parameter values.
- A reply that cannot be rendered fails its run with a 422 to the caller. An attempt taken back from
  a worker more than `DIRIGENT_LEASE_RECOVERY_LIMIT` times (5 by default) fails with
  `run.lease_recoveries`.
- A playground stream ends 95 seconds after it arrives, and a process holds at most 32, answering
  others 503.
- A signing secret's fingerprint is keyed by the instance, so its holder can no longer recompute it.
  A row keeps its unkeyed fingerprint until `dg source set-secret` or `dg source rotate-token` next
  replaces it, so an instance with a guessable hand-set secret should set a strong one.
- `DIRIGENT_PACKS` entries have to be pinned as `name==version`, so a bare name, a range or a URL
  fails the build.
- On a loopback bind, `dg dev` answers 421 to any `Host` that is not a loopback name, including
  `*.localhost`, so a proxy in front has to send one.
- Beside a connection, a step cannot set `X-Forwarded-Host`, `Forwarded`, `X-Forwarded-Proto` or
  similar routing headers.
- A body under `/api/v1` or the playground has 30 seconds to arrive, unless the caller's credential
  resolves.
- `/docs` and `/redoc` run bundles pinned to one release and its hash. They use system fonts, and
  `/docs/oauth2-redirect` is gone.
- The playground sets a content type only when all of it is one inert media type, so
  `text/plain; boundary=x` is refused.
- On Linux, `dg worker`, `dg dev`, `dg server` and `dg scheduler` clear their dumpable flag, so a
  same-user command cannot read their environment. They write no core dumps, and a same-user debugger
  or `py-spy` cannot attach.
- A reference in a shell string stays one word through comments and here-documents, and a command
  that cannot be read to its end is refused. It has to be an integer wherever bash evaluates it:
  `[[ -eq ]]`, `let`, `unset`, `declare -i`, indexed array subscripts and `${var:offset}`.
- A reference in a jq program is bound as a variable and keeps its type, so `"5"` no longer compares
  as 5, and `.${params.field}` becomes `.[${params.field}]`. A program that is only a reference is
  refused, and so is a reference in a `report.render` template; use `values`.
- A reference anywhere a block publishes SQL is refused, however deeply nested.
- A document's YAML aliases are bounded before it is built, at every door that reads one, and
  `convert.arrow` refuses a parquet too wide or too sparse for a csv from its footer.
- A connection something uses cannot be deleted, and the refusal names what uses it. That includes
  pipelines, alert rules and storage schemes.
- A token is revoked by its id, so two sharing a name can be told apart: `DELETE /tokens/{id}`,
  `dg admin token revoke ID` and `dg.admin.tokens.revoke(id)`. `DELETE /users/{username}/tokens/{name}`,
  `--user` on revoke and `users.revoke_token` are gone, so a script revoking by name has to change.
- `/admin` is gone, and a dry run's plan names the sources and schedules an apply would remove.
- `dg dev`'s admin has no display name, and a graph stops fitting at 80% zoom and pans past it.
- Shipped examples were corrected where their behaviour or comments were wrong, and
  `endpoint-payload-to-tracker-event` is now `endpoint-payload-to-data-values`, so re-read one you
  copied from.
- The web UI calls a starter a template. The API, CLI and packs still say `starter`.
- `dg config show` hides the database password, and `dg apply` refuses a pipelines directory or a
  document link outside the project.
- MCP `apply_document` is marked destructive, because applying can remove sources and schedules, and
  a dry run now lists those removals.

**A third security review, and what its fixes change.** Each item below is a fix a deployment or a
document can notice.

- `git.checkout` gives its token only to the connection's own scheme, host and port. A submodule or
  a redirect elsewhere gets none, so a step whose submodule host asks for a credential now fails.
- `shell.run` and `docker.run` find bash's evaluating contexts in more spellings: one-line
  functions, `case` patterns, a redirection before the command, `time -p`, `a=([...])`, `[ -v`,
  `test -v`, `printf -v`, `read` and `declare -n`. A reference there has to be an integer; use
  `argv` for any other value.
- A `read_only` DuckDB connection refuses a write anywhere in a statement, inside a `WITH` too, and
  refuses `query()`, `query_table()` and `json_execute_serialized_sql()` even for a read.
- A `${...}` in `docker.compose.*` `content` is refused at apply and when the step starts. Write
  `$${NAME}` in the file and give the value in `env` under `NAME`. The field shows as a YAML editor.
- `docker.run` fails on an output that is a link or not a regular file, and on a target reached
  through a link. A compose file, env file, build context or Dockerfile a link leads out of the
  work directory is refused.
- `command_path` is gone from `docker.build` and `docker.compose.*`. A step's `env` cannot set
  `PATH`, `HOME`, `XDG_CONFIG_HOME`, `DOCKER_CONFIG`, `DOCKER_CONTEXT`, `DOCKER_HOST`,
  `DOCKER_CERT_PATH`, `DOCKER_TLS`, `DOCKER_TLS_VERIFY`, `BUILDX_CONFIG`, `SSL_CERT_FILE`,
  `SSL_CERT_DIR`, `LD_*` or `DYLD_*`. Name a daemon through a `docker` connection, and wrap docker
  through the worker's own `PATH`.
- `dg auth login`, `dg auth password`, `dg admin user password`, `dg connection create` and
  `dg source set-secret` refuse a server a checkout names off this host, unless it came from `--url`
  or the shell's `DG_URL`.
- A state directory under a path a tracked file spells with another Unicode normalisation or case
  counts as tracked, and is refused.
- A JSON body nested past 128 levels is refused with 400 `source.body_too_deep`, and a stored value
  too deep to check settles its step rather than holding queued work.
- `validate.schema` evaluates off the event loop, and `uniqueItems` costs time in step with the
  array. A backtracking `pattern` can still hold a worker; see [Security](security.md).
- A connection's `bearer_token` or `api_token` holding a control character, or a blank at either
  end, is refused when stored (`secret.not_sendable`). Rows written earlier are not rewritten: rotate
  such a token if an instance held one.
- A held caller whose run fails before a reply is told the run and the step, not what the step said.
  `params.detail` is gone from `source.reply_rejected` and `source.reply_failed`; a reply can still
  carry it with `${steps.<name>.error.message}`.
- The playground reflects at most 8 KiB of a body, with `body_truncated` true and `body_bytes` still
  the whole size.
- An open log tail or event stream ends with `expired` within five seconds of its token being
  revoked or expiring, or its account being deactivated.
- A signed call whose body arrives after its timestamp left the window is refused.
- An endpoint's JSON body holding half a surrogate pair is refused with 400 `source.body_not_json`,
  and every JSON column stores one arriving another way as its escape, so its run stays readable.
- A schedule whose document cannot make a run records a failed firing, and the schedules after it
  still fire. An `interval` past ten years is refused.
- A polled source's `poll` past ten years is refused at apply (`source.poll_too_long`), and one
  source's failure stays on its own row.

## 0.27.1

Released 2026-10-30. Every package in the workspace moves to 0.27.1 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **`dirigent-mcp`: an agent operates an instance over MCP.** A new package, started by an MCP
  client as `uvx dirigent-mcp` over stdio with `DG_URL` and `DG_TOKEN`. Its tools are calls the
  API already answers: read the block catalog and the examples, plan and apply a document, start
  a run (optionally waiting for it) and read its attempts and logs, cancel a run or retry an
  attempt, and list, pause and resume sources and schedules. None of them deletes. With
  `DG_MCP_READ_ONLY=1` it offers only the tools that read. An agent that may apply and run a
  document runs it with every connection the instance holds, so give it a `viewer` token to
  read and an `operator` token, never `admin`, to write; [Working with a coding
  agent](agents.md) says more. The image carries it too.
- **A connection a document carries may say its `name` and `description`.** Both are optional,
  and `dg dev --seed` and `dg run --local` pass them on to the connection they create. Every
  example schema and connection now has both, so the Schemas and Connections screens read as
  titles rather than bare codes, and a schema carried in a document no longer blanks the labels
  of the stored one it shares a code with.
- **`dg validate DIR`.** A directory is read at every depth: each YAML or JSON file that declares
  a `dirigent/` format is checked, as is one that does not parse, and the rest are counted as
  `skipped` in the closing `validated` record.

## 0.27.0

Released 2026-10-30. Every package in the workspace moves to 0.27.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`. Input sources are complete: a pipeline listens
at an endpoint, polls a storage location or a sensor, or holds a queue consumer, and inbound
webhooks and watches are gone in their favour.

**Upgrading.** Two removals and one change of behaviour reach callers and documents:

- **Inbound webhook triggers are removed.** `triggers: webhooks:`, `POST /hooks/{token}`,
  `dg webhook`, the webhook settings (`DIRIGENT_WEBHOOK_MAX_PAYLOAD`,
  `DIRIGENT_WEBHOOK_INTAKE_RATE_PER_MINUTE`, `DIRIGENT_RETENTION_DELIVERIES`) and
  `dg prune --deliveries` are gone. An `endpoint` source takes their place; one taking a signed
  body writes `auth: {kind: hmac}`. The outbound `webhook.post` block and the webhook notifier
  are unchanged.
- **Watches are removed.** `triggers: watches:`, `dg watch`, the watch routes, the
  `watch_backoff` settings and the `watch` trigger kind are gone. A `sensor` source takes their
  place: `source: {kind: sensor, block: kafka.consume, config: {...}}`.
- **An endpoint with a reply holds its caller.** Before, every call was answered 202 at once.
  A caller of a pipeline with a reply node now waits for the reply, up to its timeout.

**The schema changed.** `sources` gains `signing_secret` and `signing_key_id`, and the
`webhook_triggers`, `webhook_deliveries` and `watches` tables are gone. The baseline migration
is edited in place while nothing has shipped, so a database created before 0.27.0 does not get
these from `dg db upgrade`; recreate the database.

- **An endpoint answers with its reply.** A reply node renders the caller's answer from the
  run's outputs: a status, headers, a content type, and a body or `body_from` a stored file.
  The caller is held for the longest timeout among the replies its input can reach, under the
  instance's cap. A run that can no longer reply is answered 422 when a step on the replying
  path refused the input as `rejected`, 502 otherwise, and 504 when the timeout passes first;
  the run carries on. One batched waiter per server process is woken by the run's commit. The
  journal records `replied` and `timed_out`. `source_max_waiting_per_source` (64) keeps one slow
  pipeline from taking every seat (`source.waiting_share`).
- **A pack contributes a source kind.** `Contribution.sources` takes `ReceivedSource`,
  `PolledSource` and `HeldSource` kinds through pluginkit; dirigent itself claims `endpoint`,
  `storage` and `sensor`. `dirigent_testing.receive_request` and `FakeReceiveContext` test a
  received kind without a server.
- **The Triggers screen lists sources.** Each source with its pipeline, what it listens to, its
  state and what is in flight; its panel reads the source's inputs and rotates its credential.
- **A worker polls the polled sources.** Every worker polls the sources that are due under a
  lease. A poll is all or nothing: its inputs become runs and its cursor moves in one
  transaction, or none of it does and the source backs off (`starting`, `failing`).
  `concurrency: skip` is refused beside a polled or held source.
- **The `storage` source.** Each object that lands under a prefix or matches a glob becomes one
  run. An object is known by its URI, so one copied in still carrying an old date is found and
  one re-copied with a fresh date is not run twice; `rerun_changed: true` runs an object again
  when its modification time changes.
- **Held sources: Kafka and RabbitMQ consumers.** The queues pack adds `kafka` and `rabbitmq`
  source kinds. A worker holds each consumer under a renewed lease and acknowledges a message
  only once its run is committed, so a message is never lost and may, after a crash, arrive
  twice. `source_held_max` and `source_hold_wait` bound them.
- **Signed endpoints.** `auth: {kind: hmac}` checks an HMAC-SHA256 of the body in
  `X-Dirigent-Signature` (or the `header` it names); the signing secret is created at apply,
  sealed with the instance key, shown once and rotated with `dg source set-secret` or Rotate
  secret in the UI. `dg source call --signing-secret` signs a test call.
- **The `sensor` source.** A worker pokes a sensor block outside any run; each success starts a
  run, and the next wait reads on from where it ended. A sensor opts in with
  `SensorSpec(source=True)`: `kafka.consume` and `playground.arrive` do. A sensor that reads part
  of a run (scratch, work, the runs handle) fails the poll.
- **A nested list in a description is drawn as a list inside its item.**

## 0.26.1

Released 2026-10-29. Every package in the workspace moves to 0.26.1 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The pipeline document's YAML editor checks against the schema again.** Since 0.26.0 the
  Source tab's language worker never started: monaco 0.57 takes a worker where monaco-yaml
  still names one by label, so a document was edited with no schema validation, folding,
  outline or links. monaco-yaml is now handed monaco's own label-based worker helper, the one
  its JSON language uses.
- **Every editor gets its quick fixes, code lenses and inlay hints.** The JSON language loaded
  monaco's editor contributions lazily, after the first editor had built its services, so
  those contributions failed on that editor with `depends on UNKNOWN service` in the console.
  They are now loaded with the editor.
- **The add-step menu's search keeps the focus.** The menu moved the focus to its own list a
  moment after opening, so what was typed next could miss the search box. It stays in the box.
- **The UI lints clean, and a new lint warning fails the gate.** `bun run lint` runs oxlint
  with `--deny-warnings`. The Examples, Pipelines, Runs and Blocks screens no longer republish
  their status line on every render.
- **The follow-stream tests read in one thread.** The server's SSE tests read a frame, move
  the run, and read on, rather than racing a background reader.

## 0.26.0

Released 2026-10-29. Every package in the workspace moves to 0.26.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A pipeline's own SQL could read the instance's S3 secret key.** The duckdb block gave
  httpfs its credential as plain settings, and a setting is readable by any statement on the
  connection: `SELECT current_setting('s3_secret_access_key')` in a document answered the key,
  into the step's output. Every release from 0.9.0 to 0.25.2 is affected. The
  credential is now a duckdb connection secret (`CREATE SECRET ... IN connection`), held by
  that connection alone, in memory, with every value bound, and redacted wherever it is
  listed. An instance where people who should not hold the S3 key can apply documents should
  rotate it after upgrading: a key already read stays valid.
- **duckdb 2.** The duckdb block requires `duckdb>=2.0.0`. duckdb 2 refuses a call on a
  connection still busy with another, so a query that outlives its timeout now waits for the
  interrupted statement to return before the connection is rolled back and closed. A
  statement that ignores the interrupt is left behind after five seconds, the step fails on
  its timeout as before, and the connection closes once the statement returns. Each database
  a step opens bounds its I/O threads at eight; duckdb 2's default scales with the host.
- **A quiet run's stream stays open.** `$logs?follow=sse` and `$events` send a `: ping`
  comment when fifteen seconds pass with nothing sent, so a proxy that closes idle connections
  no longer cuts a tail on a run that is quiet for a long time. An SSE client reads past a
  comment; the UI and `dg` already do.
- **Dependencies.** Every Python and UI dependency is on its newest release: among them
  FastAPI 0.162 (Starlette 1.10), pydantic 2.14, SQLAlchemy 2.1.6, pyarrow 26, ruff 0.17,
  react-router 8, vitest 5, and monaco-editor 0.57. The editor keeps typing on monaco's
  textarea rather than its experimental edit context, and builds monaco-yaml's worker against
  monaco's new module layout.

## 0.25.2

Released 2026-10-27. Every package in the workspace moves to 0.25.2 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The server compresses what it sends.** Every response over 1 KB is gzipped for a client
  that accepts it. An SSE tail, an artifact read as opaque bytes (`application/octet-stream`,
  parquet), and images, fonts and archives are sent as they are.
- **The UI's assets are served from compressed copies built beside them.** The vite build
  writes a `.br` and a `.gz` copy of every compressible file in `assets/`, and the server
  answers a hashed asset with the best one the request's `Accept-Encoding` admits, brotli
  first. Monaco's chunk goes over the wire at 488 KB instead of 2.4 MB, and the main
  stylesheet at 39 KB instead of 178 KB. A bundle built before this release carries no
  copies and is gzipped on the fly instead.

## 0.25.1

Released 2026-10-27. Every package in the workspace moves to 0.25.1 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A connection can name an address that redirects.** `follow_redirects_with_auth` on an
  `http` connection follows `base_url`'s redirects once, without the credential, and sends
  every request to where the base landed, credential and method intact: a cross-host redirect
  no longer drops the credential, and a 302 no longer turns a POST into a GET. The walk stops
  before a redirect deeper under the base on the same host, which is the service sending an
  anonymous caller to its sign-in page. `ctx.http` honours it for any connection kind that
  names the field.
- **`dirigent-dhis2` follows the play demos as they move.** Its `dhis2` connection gains
  `follow_redirects_with_auth` too, and it requires `dhis2w-client>=1.33.1`, whose redirect
  check confirms the play demos. Its shelves, tutorial and connection page name
  `https://play.dhis2.org/2.43` and `https://play.dhis2.org/2.42`, the aliases for the newest
  demo of each major, instead of a pinned `stable-2-4x-y` that is retired when the next patch
  ships. The shelves on a generic `http` connection set `follow_redirects_with_auth: true`.
- **`dirigent-integration`'s shelves name the aliases,** and a rehearsal points an alias at
  each targeted version's demo.

## 0.25.0

Released 2026-10-27. Every package in the workspace moves to 0.25.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **`dg validate` checks every step's config offline.** Without `--server`, each step's block
  and config are checked against the blocks installed beside `dg`, so a misspelled config key
  is a `document.step_config_invalid` problem and an unknown block a
  `document.step_block_missing` one, at once rather than at the apply. Connections and other
  pipelines a document names are still checked only with `--server` or at the apply. The
  `validation` record's `checked` reads `document and installed blocks` offline and
  `document and catalog` with `--server`.
- **Upgrade note.** A document using a block that is not installed beside the `dg` validating
  it now fails offline. Install the pack, or validate with `--server` against the instance
  that has it. Anything matching on `checked="document, offline"` reads the new value.
- **The installed catalog reads without a server.** `dg blocks list --local` and
  `dg blocks show BLOCK --local` read the blocks installed beside `dg`, and an unknown one is
  refused as `cli.no_such_block`. `dg pipeline schema [-f FILE]` writes the whole document
  format with every installed block's config as one Draft 2020-12 JSON Schema, as a
  `pipeline.schema` record or into a file an editor's `yaml-language-server` comment names.
- **A project carries notes for a coding agent.** `dg init` writes `AGENTS.md` -- the loop of
  finding a starting point, validating, running locally and applying, how to read the records
  `dg` answers with, and the rules a document most often gets wrong -- and a `CLAUDE.md` of one
  line, `@AGENTS.md`. A project that has either keeps its own. `dg init --agents` writes the two
  alone into a project made before.
- **The docs teach working with a coding agent,** on a new page under Start here, and the
  site serves `llms.txt` at its root, naming every page with what it covers.

## 0.24.0

Released 2026-10-26. Every package in the workspace moves to 0.24.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **An endpoint source takes calls.** A pipeline whose first node is `source: {kind:
  endpoint, path: ...}` is called at that route under `/endpoints` (`DIRIGENT_ENDPOINT_PREFIX`),
  and each call becomes a run entered at the source, the request as its input; the caller is
  answered 202 with the run and where to read it. Unless the source writes `auth: {kind:
  public}`, the caller presents the token the apply minted for it as `Authorization: Bearer`.
  The token is shown once, in the apply's result; `dg apply` prints it, and an apply that
  creates a source in CI writes it into the CI log, so rotate a token first shown there. A
  call is checked in one order -- the instance's rate for the path, the route (404, 405), the
  token (401), the source's own `rate` (429), the source and its pipeline taking input (503),
  the content type (415), `max_body` (413), the parse (400), `max_in_flight` (503) -- and
  nothing before the source's own rate writes a row. A reply node still renders into the run
  and is not yet sent to the caller; a held caller answered by the reply comes next.
- **Every source has a row.** An apply reconciles one per source node by its step code: the
  declaration follows the current version, while whether it is paused, its token and its
  counts survive. A route is one source's on the whole instance, and an apply claiming one
  another pipeline answers is refused. A source is `listening`, `backlogged`, `draining` or
  `paused`. The API lists them (`/sources`, `/pipelines/{code}/sources`), pauses, resumes and
  rotates them, and reads every input that reached one and what it became; `dg source list |
  show | pause | resume | rotate-token | inputs | call` does the same from a shell, `call`
  presenting the source's own token rather than the CLI's. `retention_inputs` and
  `dg prune --inputs` bound the record of inputs.
- **A source kind declares its limits.** `ReceivedSource` gains `auth()` and `rate()`, and
  `Source` gains `max_in_flight()`, each with a default; the endpoint's rate model is
  `dirigent_plugin.sources.SourceRate`.
- **A pipeline starts at a source and answers through a reply, run by hand.** A step is a
  block, a `source` or a `reply`. A run of a pipeline with sources enters at one of them, by
  hand with `dg run --input` or from the source's `sample`; a reply is rendered by the server
  once the steps it answers from have settled, and neither is ever claimed by a worker. See
  `examples/sources/`.
- **An adopting step's items no longer wait for the whole grid.** A step mapping over
  another fan-out's grid (`for_each: ${steps.A.items}`) used to start only once every item of
  A had settled. When A runs under `items: continue`, the step's rule is `all_success`, and
  it reads nothing of the grid but its own match (`${steps.A.item.output}`), each of its items
  now starts as soon as its own match settles, and over a late grid the step's grid is written
  as soon as A's is. `fail_fast` grids, other rules, and a step reading A's whole `output`
  keep the old timing. The run detail's DAG nodes carry `item_wise_parent`, the run screen's
  graph says `item by item after <parent>`, and `dg validate --explain` marks such a step.
- **Upgrade note.** A pipeline already using `items: continue` on a fan-out another step
  adopts changes timing: the adopter's items run alongside the parent's, so the systems they
  write to see them earlier and concurrently. Write `items: fail_fast` on the parent, or read
  its `output`, to keep the old order.
- **Seeding takes a corpus whole.** `dg dev --seed-installed` and `--seed` apply a corpus's
  connection files and standalone JSON Schema files before its documents, and apply a refused
  document again while a later pass still stores something, so a document naming what a later
  one supplies goes in.
- **A local run reports every state a step passed through,** in order, and reports the end of
  the run on its commit rather than its next poll.
- **`dirigent-dhis2` targets DHIS2 2.42 and 2.43, with 2.43 the default.** The examples, the
  tutorial and the connection page move to `stable-2-43-2` and hold on 2.42 alike. Every
  exported value carries its own period, org unit and attribute option combo on both versions,
  copied from the set where 2.43 writes them once. An export answered with an empty body fails
  as `dhis2.export.empty_answer` instead of succeeding with nothing, and a 2.43 conflict keeps
  its code and its position. The pack requires `dhis2w-client>=1.33.0`.
- **`dirigent-integration`'s nightly run follows the play demos the public list names** and
  rehearses an export and a dry-run import against the newest stable demo of 2.42 and of 2.43.

## 0.23.4

Released 2026-10-22. Every package in the workspace moves to 0.23.4 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The image trusts no compromised eMudhra intermediate.** The private keys of eight eMudhra
  intermediate CAs are recoverable from their certificates
  (https://emudhra.we-have-a-problem.com/). httpx2 trusts the system store, which in the image
  is Debian's `ca-certificates`, and the 0.23.3 image carried `20250419~deb12u1`, which still
  trusts them: a container answered 200 from the incident's test hosts. The runtime base moves
  to a `python:3.13-slim-bookworm` that carries `20250419~deb12u2`, and the 0.23.4 image refuses
  them. An instance on the 0.23.3 image should move to 0.23.4. certifi moves to 2026.10.19 in
  the lock, for the dev tooling that reads it.
- **An analytics run joins the job already running.** `dhis2.analytics_run` in `dirigent-dhis2`
  asks the instance first whether an analytics tables job is running, and follows that one
  rather than submitting a second; `join_running: false` always submits, and so does a user the
  instance refuses the job listing. The output's new `joined` says which happened. A joined job
  runs with the options it was started with, not the step's.
- **An export with children no longer writes every value onto its parent.** With `children`,
  `dhis2.data_value_set_export` answered with DHIS2's document-level `orgUnit` still set to the
  org unit it was asked for, and an import applies that field to every value in place of the
  value's own: the body, imported again, wrote each descendant's values onto the parent. The
  body now leaves it out, and each value keeps its own. A step that read `body.orgUnit` from an
  export with children finds nothing there; the org unit it asked for is its own config. A body
  exported with children before 0.23.4 and kept in storage still carries the field.
- **The DHIS2 examples point at `stable-2-42-7`.** `stable-2-42-6` is gone from
  play.im.dhis2.org, so the examples and tutorial in `dirigent-dhis2` and the pipelines in
  `dirigent-integration` move again. The integration's nightly run now asks every play demo an
  example names for its system info and fails on any that no longer answers, so the next
  retirement is caught the night it happens.

## 0.23.3

Released 2026-10-07. Every package in the workspace moves to 0.23.3 together, and so do
`dirigent-dhis2` and `dirigent-integration`. Nothing in this repository changes; the release
exists for the two siblings.

- **The DHIS2 examples point at a play demo that answers.** `stable-2-43-1` is gone from
  play.im.dhis2.org and `stable-2-43-2` lists no organisation units, so the example pipelines
  `dirigent-dhis2` ships in its wheel, its tutorial, and the pipelines in
  `dirigent-integration` move to `stable-2-42-6`. On 2.42.6 a rehearsed import reports what it
  would import as well as update, since the demo does not hold the values 2.43.1 did; a dry
  run still writes nothing.

## 0.23.2

Released 2026-10-07. Every package in the workspace moves to 0.23.2 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **SQLAlchemy 2.1.** `dirigent-core` and `dirigent-block-sql` require `sqlalchemy>=2.1.3`, so
  an environment holding SQLAlchemy 2.0 beside dirigent no longer resolves. Nothing about the
  schema or the queries changes; the claim, the run report and the drift check are typed to
  2.1's generic `Select` and `Table`.
- **A request is one span, dirigent's.** FastAPI 0.142 instruments itself whenever a tracer
  provider is installed, which put a second server span between dirigent's request span and the
  run it created, and would have added exporters from the environment and logged exception
  messages beside `configure_telemetry`. The server turns FastAPI's own telemetry off, and
  `dirigent-server` requires `fastapi>=0.142.2`.
- **The dependencies move.** FastAPI 0.142, Starlette 1.7, Uvicorn 0.54, OpenTelemetry 1.45,
  cryptography 50.0.2 and DuckDB 1.5.6 among the Python ones; React Flow 12.12, Vite 8.3.3 and
  oxlint 1.87 in the UI.
- **The dashboard's chart ends when its runs were read.** It took the hour of every render, so
  the axis could move under rows that had not been read again; it now takes the moment the
  day's runs answered.
- **`dirigent-dhis2` reads DHIS2 2.44.** It requires `dhis2w-client>=1.31.1`, a release
  that recognises a 2.44 instance, as a preview, rather than refusing it as unsupported.

## 0.23.1

Released 2026-10-01. Every package in the workspace moves to 0.23.1 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The pipelines naming a stored schema are a count that opens.** They were a list under the
  Schema label, so a schema ten pipelines named pushed Save and Delete off the screen; the row
  above the body now states the number at every count and the names are one press away. The body
  pane is shorter for it, and the window still draws the whole shape.

## 0.23.0

Released 2026-10-01. Every package in the workspace moves to 0.23.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A run holds the shapes it started with.** When a run is created it reads the body of every
  schema its document names and keeps those bodies on the run, the way it keeps its resolved
  parameters, its priority and its worker tags. Every attempt, every later step and every retry
  check against those bodies rather than the table, so an edit reaches the next run of a pipeline
  naming the code and never one already under way. A `${...}` in a step's `schema` is refused when
  the document is applied: a code that is not a code until the run is under way is one nothing else
  can see either, neither the `requires` preflight nor the dependants a delete is refused for.
- **A schema in use is not changed blind.** Deleting a schema a current pipeline names is refused;
  editing one never is, because a code is fixed once minted and refusing the edit would freeze an
  in-use schema for good. The dependants are read from the documents themselves, which already
  declare them, so nothing has to be kept in step.
- **A stored schema is corrected where it is read.** The Schemas screen edits name, description and
  body; the apply dialog's `differs` row offers the same correction in place; and `dg schema update`
  does it from a shell, taking a body the way `create` does. A label given empty is cleared and one
  left out is left alone -- which `dg` could not express before, so seeding quietly wiped the title
  and description of every schema it replaced.
- **A missing connection is minted in the row that says so.** The apply dialog's offer opens the
  connection form under the row rather than sending the reader to another screen and losing the
  document they had typed.
- **A label says only what is known.** Messages that asserted what the code could not tell --
  that a password was unchanged when the request never answered, that parameters were a JSON object
  at the moment they were not -- now say what is true. Every counted sentence carries both its forms,
  so nothing renders "1 items"; every noun the CLI and the UI both say is held to one word by a test;
  and a lane fails documentation that quotes a label the catalogue no longer has.
- **A form is not hidden under its own cap.** Three dialogs capped an inner block and hid the form
  inside it, two of them standing taller than the window with nothing to scroll. A surface caps and
  its body scrolls; only a read-only preview takes a height of its own, and that height belongs to
  the block rather than its callers.
- **An unread catalog is not an empty one.** The step menu answered "No block matches that." while
  it was still reading the catalog, so a reader who typed quickly was told the block they wanted did
  not exist and their Enter placed nothing.

## 0.22.0

Released 2026-09-29. Every package in the workspace moves to 0.22.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **Every word the UI says has a code.** `lib/labels.ts` holds them all, one nested object
  whose path is the code, built the way `dirigent_common.messages` is built: a catalogue per
  area, a duplicate refused by the compiler rather than at import, and a sentence with a value
  in it written as a function with named parameters. A translation is a second table,
  `const nb: typeof LABELS`, and the compiler fails a missing code, a stray one, or a sentence
  taking different parameters. `scripts/check_ui_labels.py` runs in `make static` and fails a
  user-visible literal outside the catalogue, or a label nothing reads.
- **A refusal renders in the language of the surface that draws it.** The wire carries the code
  and the params; each surface renders its own sentence. The browser reads `detail` only as the
  fallback for a code it does not know. `RunOut`, `ItemOut`, `StepReport`, `RunReport`,
  `LogEntryOut`, `AlertMessage` and `RunSnapshot` carry what a renderer needs, and a log entry
  holds its code in a column rather than inside `fields`.
- **A pack contributes the wording its codes are rendered from.** `labels` is the seventh
  `Contribution` surface, a list of catalogues gathered by the host and served from
  `GET /labels`, so a pack's refusal reaches a browser in the browser's language. The nine
  in-tree families contribute 152 codes. The field defaults to empty, so a pack that does not
  set it loads unchanged.
- **A refusal a person reads is written for that person.** An uncaught block error no longer
  reaches the run view as a Python class name: the sentence says the block failed and points at
  the step's log, which carries what it raised. Six messages that told a browser user to type a
  command say what is wrong instead, and a test walking every catalogue fails a new one.
  Eleven cancellations that were bare English now carry codes.
- **One word per concept.** A schedule's firing was spelled nine ways, `queued` four; a column
  and the fact beside it disagreed on case in seven places. Each is one entry now, with its
  surface forms under it. `test_shared_words.py` fails the CLI and the UI drifting apart on a
  word they both say.
- **A pack can check its own wording.** `dirigent_testing.check_pack_messages` reports a refusal
  raised under no code, a message nothing reads, and a code two catalogues both define. It is
  opted into with one line, like the package's other assertions.
- **The mono face is JetBrains Mono**, self-hosted, with the same advance as what it replaces.
- **One inset per surface.** 16px, stated once and spent everywhere; a listing row that fills
  the panel takes it back when pressed again; a dialog draws one control that dismisses it.

## 0.21.0

Released 2026-09-27. Every package in the workspace moves to 0.21.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A watch keeps a sensor waiting.** A third trigger beside schedules and webhooks, declared
  under `triggers: watches:` in a pipeline document or a `kind: triggers` document. A watch
  keeps exactly one run of its pipeline waiting on one root sensor step; when that step
  succeeds, the same transaction arms the next run, and the run that succeeded carries on
  downstream. Runs overlap by design: one batch is being transformed while the next is being
  waited for. A run that ends without its sensor succeeding re-arms from the last good point
  after a backoff that doubles from `watch_backoff` to `watch_backoff_max`. Apply refuses a
  watch on a step that is unknown, not a root, fans out, is not a sensor, or sits in a
  `replace` pipeline, and a later version that would break one.
- **The cursor belongs to the watch.** A sensor's success can say where it left off:
  `Sensor.resume_cursor(output)`, with a default of none, so every existing sensor starts each
  run fresh as before. The watch stores what it returns and seeds the next run with it, which
  the block reads through `ctx.cursor`. `kafka.consume` continues its offsets across runs with
  no consumer group, and `playground.arrive` numbers each batch on from the last. Pausing
  keeps the cursor, and resuming arms a run from it. `dirigent-testing` gains `carry_cursor`,
  which hands a sensor's next poke what the engine would.
- **`dg watch`** lists, shows, pauses and resumes watches, writing `watch`, `watch.paused` and
  `watch.resumed` records; the API has the same four routes under
  `/pipelines/{code}/triggers/watches`. `dg dev --seed`, `dg apply --paused` and
  `dg run --local` create watches paused, so a demo or a single local run is never competing
  with one.
- **The Triggers screen lists watches** beside schedules and webhooks, with their state,
  cursor, failures and last error, and so do the pipelines listing and the pipeline tab.
- **Two documents teach it**: `triggers/watch-a-sensor.yaml` over `playground.arrive`, runnable
  with no network, and `queues/kafka-watch-then-transform.yaml` over a real topic.
- **The New connection form suggests the playground** as its example code, not a service the
  corpus has left.

## 0.20.0

Released 2026-09-26. Every package in the workspace moves to 0.20.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The corpus runs on its own instance.** Every example and every page of the documentation
  is off postman-echo.com. A document that needed something to happen -- a list to fan out
  over, a step that fails twice, a delay against a timeout, a payload over the storage
  threshold -- now says so with the `playground.generate` node, so it runs offline and under
  `dg run --local` with no connection and no URL. A document that is teaching `http.request`
  itself still makes a real call, to this instance's own playground. The basics tutorial is
  rewritten and re-shot on it.
- **A step that waits, with nothing to wait for.** `playground.arrive` parks for a number of
  pokes or a length of time and then yields a batch, so a readiness wait can be taught and
  verified with no service to poll. Its output is the shape a queue consumer answers with,
  so a document that later reads a real topic changes very little.
- **A stream to test a consumer against.** `/api/v1/playground/stream` writes newline-delimited
  JSON: an envelope, then a message every interval, then a closing line, so a reader can tell
  an ending from a dropped connection.
- **A failure can say what kind it is.** `fail_as` beside `fail_until` names the class the
  induced failure carries, so the difference between a transient failure that spends the
  retry budget and a rejected one that spends none can be taught offline, on three steps
  under one policy. Before this, a document could only get a rejected failure from a live
  HTTP call or by naming a Faker provider that does not exist.
- **An unknown provider names a command that exists.** The refusal for a Faker provider the
  installed library does not have pointed at a route that was never served.

## 0.19.0

Released 2026-09-26. Every package in the workspace moves to 0.19.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The playground: an instance answers its own test requests.** Five paths under
  `/api/v1/playground/`, unauthenticated and off by one setting, that reflect what they were
  called with and answer the way a document needs them to: a request echoed back whole, a
  chosen status, a redirect that stays on this instance, an endpoint that fails a set number
  of attempts before succeeding, and one that sets the response headers you name. Every
  answer carries the request that produced it under one key, and the resolved knobs beside
  it, so what was sent and what was used are both on screen.
- **A node that makes data, anywhere in a flow.** `playground.generate` takes a field map
  naming the Faker provider that fills each field, so every provider the installed Faker
  offers is reachable in every locale, reproducible under a seed the answer always reports.
  It also fails on demand, delays, drifts its own shape, pages, and pads its payload, so a
  retry example really retries, a gate is really seen catching drift, and an outputs-to-
  storage example really crosses the threshold. It works with no input as a document's first
  step, with an input from upstream in the middle, and as the last step.
- **A shelf of five documents** that teach exactly those cases, runnable with no network.

## 0.18.4

Released 2026-09-25. Every package in the workspace moves to 0.18.4 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A title reads whole.** In a listing that puts a title beside a description, the title
  column has first claim on the width and the description takes what is left; 0.18.3 split
  the two evenly and cut titles short on the Schemas listing and the dashboard.
- **One corner for the window button.** Every pane that opens in a window puts the button at
  the bottom right, where the scrollbars meet and no text is; the read-only window for
  produced data had its own corner.
- **Highlight the current line.** A preference under Settings, General, off unless asked,
  that every editor follows as it is switched.
- **A search box does not repeat the heading above it.** Every listing's search says
  `Search`; a picker still says what a match is made on, since nothing else does.
- **A card draws no label for a cell that said nothing.** A schema with no description no
  longer wears an empty `Description` on a phone, and the same holds on every listing.
- **The dashboard's Health card fits its width at 1024.** Nothing on it scrolls sideways.

## 0.18.3

Released 2026-09-25. Every package in the workspace moves to 0.18.3 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **The bucket is made by the image itself.** `dg storage ensure` creates the artifact bucket
  the instance's storage root names, idempotently, and the compose stack's `migrate` service
  runs it after the schema and the connection. The `mc` sidecar is gone from the stack and
  from what `dg init` writes: the image it pulled no longer exists on any registry, and a
  one-line job never needed a third-party tool image.
- **A listing follows the width it was given.** A table turns into cards when its own box
  cannot hold its columns, not when the window is narrow, and a column holds either a value
  that declares its floor or text that takes what is left and truncates. Every listing is a
  table at 1024 with nothing scrolling sideways; cards remain beside an open panel and on a
  phone.
- **A menu is floored at its control and capped at the screen.** A picker's popup grows to its
  longest row, never past the viewport's gutters, so a long row reads whole at phone width.
- **A connection kind declares its mark.** A pack sets `mark` on its `ConnectionKind`, one
  SVG path on the 24-unit grid, monochrome; the catalog carries it and every screen that
  names the kind draws it. The check at registration and in the conformance kit refuses
  anything that is not path data.
- **The graph's layout engine is its own chunk and its own thread.** elk loads when a canvas
  first asks for a layout and runs in a worker; the graph chunk drops from 1615 kB to 183 kB.
- **Screens.** A new docs page with nine pictures of an instance running the three showcase
  pipelines, click-to-enlarge on every docs picture, and `make docs-shots` to re-shoot them.
  The showcase shelf holds the three documents, all runnable locally.

## 0.18.2

Released 2026-09-23. Every package in the workspace moves to 0.18.2 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A kind has one glyph, drawn wherever a kind is named.** The connections listing, the
  connection page, the New connection kind rows, the editor's reference row and the home's
  health rows carry the same mark the alerting screen's chips wear, decided in one place, so a
  kind added there appears everywhere at once.
- **`dg alerts test` names one target, like a rule.** `--connection <code>`, or none to
  deliver through the process log; the sender follows from the connection's kind.
- **`make refresh` starts over.** Caches, every compose stack with its volumes and the local
  image, the venv, `node_modules`, `dist` and the served bundle go, then the venv and the UI
  are rebuilt. It refuses to run while something listens on the dev port.

## 0.18.1

Released 2026-09-22. Every package in the workspace moves to 0.18.1 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

- **A pipeline declares how much it matters.** `importance: routine | normal | critical` on the
  document, default `normal`, mirrored on the pipeline and shown as a mark on a critical one.
  It is not priority: priority says when work is claimed, importance says who is told when it
  fails. An alert rule may name the least importance a pipeline must have, so one rule pages
  critical pipelines while another logs everything.
- **An alert rule names one target.** A rule delivers through a connection, or through the
  process log when it names none; the sender follows from the connection's kind and a rule
  naming a connection no notifier delivers through is refused. `--notifier` is gone from
  `dg alerts rules create`, and the rule dialog has one picker, Deliver through.
- **`dg validate --explain` says what a document will cost before it runs.** Per step the
  fan-out cardinality, the attempts and the worst-case retry wait, the timeout, deadline and
  poll; over the document the attempts at most and the longest deadline chain, with a warning
  for a cardinality nothing can know before the run. One record, `validation.shape`.
- **A check that cannot verify says so.** A connection check has three outcomes now: healthy,
  failing, and not verified, which is what a Slack incoming webhook answers because it can only
  be proved by posting. `dg connection check` exits 0 on it, and every listing and the home
  health rows say "not verified" instead of green.
- **A state an older dirigent wrote is refused at boot.** Before 1.0 the schema is edited in
  place, so a state file from an earlier version lacks columns the code reads. `dg dev`,
  `dg server`, `dg worker` and `dg scheduler` now refuse it with one record,
  `database.schema_stale`, naming the first difference and the two ways out, instead of failing
  every query.
- **The alerting screen's channels are chips.** A glyph for the kind, the connection code and a
  dot in three colours: green delivers, red failed, grey for not set up, never checked or not
  verified. The rest is in the tooltip. On a phone the strip folds to one dot per channel.
- **The connections listing is one line per row.** The code and its kind, a dot and one word
  for health, how long ago it was checked, and a button to check now. What a connection is
  pointed at and what its check said are read on its own page and in the tooltip; nothing
  scrolls sideways at 1024.
- **One vocabulary across the alerting screen.** An event reads the same in the listing, the
  rule panel and `dg alerts rules list`; an unthrottled rule says `none`; a rule's target wears
  the kind's glyph beside the code, as a chip does; a connection's health says the same word
  on the strip and in the listing.
- **Small screens.** The palette button is a search glyph below the breakpoint, since a chord
  means nothing without a keyboard; the login form stands under the brand strip instead of
  centring in what is left; a segmented control that does not fit wraps to two rows.
- **For pack authors.** `HealthReport.healthy` is `bool | None`, `None` meaning the check ran
  and could not decide. `dirigent-testing` ships `no_connection_outlives_its_loop`, an opt-in
  fixture that fails a test leaving a database connection open; one line in a conftest adopts
  it. A read-only session whose read-only statement fails now closes what it opened, and a bare
  `alembic upgrade` opens SQLite the way the engine does.

## 0.18.0

Released 2026-09-22. Every package in the workspace moves to 0.18.0 together, and so do
`dirigent-dhis2` and `dirigent-integration`.

This is the base release. 0.17.0 to 0.17.2 carried one change spread over three tags, because
PyPI lets three new projects wait at a time: the built-in pack became nine `dirigent-block-*`
packages and they reached PyPI three per release. 0.18.0 is the first version since with every
package published at one number and nothing in flight. Start here: `uv tool install
dirigent-cli`, or the image at `ghcr.io/winterop-com/dirigent:0.18.0`.

- **`${artifacts}` names the instance's durable storage root.** A document had one storage
  anchor, `${run.scratch}`, and retention sweeps it with the run. `${artifacts}/<path>` is the
  other: kept until somebody deletes it, whatever scheme serves the root, so a document that
  keeps something carries a location that works on any instance. The recipe
  `storage-keep-past-the-run` writes once to each anchor so the difference shows in one run.
- **A lost artifact object refuses by name.** A database restored without its artifact store
  has rows naming objects that are gone. Every read path now answers
  `artifacts.object_missing` with the URI, the run and the attempt, and the remedy, instead of
  an empty body or a stack trace. The backup section of the operations guide is a procedure
  for both halves: the dump, the artifact copy, the order, the restore, and what to do when the
  two disagree.
- **`log_format` is a setting.** `DIRIGENT_LOG_FORMAT` is the environment spelling of a
  setting that a project's `.env` and `dirigent.yaml` also carry; the output decision reads
  it through the same layers as every other setting. Flags win over the setting, the setting
  wins over the terminal, and the default is unset so the terminal decides.
- **The finger rule reaches every control a phone shows.** Below the breakpoint the 42px
  minimum reached the primitives and nothing else: filters, the instance menu, the drawer's
  entries and the `API` chip stood at 24 to 36px. It now reaches every trigger and every link
  drawn as a control, and the UI conventions say what it does not reach.
- **A docker connection speaks the schemes the worker speaks.** `tcp://` with TLS and
  `unix://`. An `ssh://` host was accepted and then silently ran containers on the worker's own
  daemon; it is refused now, at the connection and in a worker's `DOCKER_HOST` alike, with
  `execute.not_a_daemon_scheme`.
- **The scaffolded workflow is `dirigent.yaml`.** `dg init --workflow` wrote `.yml`; YAML files
  dirigent owns end in `.yaml`. `dg runs list --limit` says its default in its help.
- **The documentation reads true.** Every page was read against the code it describes and
  fixed where it was stale or oddly put: package names, install lines, command spellings, the
  problem document's shape, the reference grammar, the hello-world start off a PyPI install.
  The block reference names every field. A broken anchor fails the strict docs build.

## 0.17.3

Released 2026-09-21. Every package in the workspace moves to 0.17.3 together.

- **A copy names what the original carried.** A document may carry the connections and
  schemas it needs to run alone under `dg run --local`, and a copy made from it, by
  `dg pipeline new`, `dg init --pipeline` or the Examples screen, drops those sections and
  names their codes under `requires` instead, so the copy applies to an instance as it is.
  Carrying no longer disqualifies a starter, and the preflight names the real connection kind.
  The conformance kit a pack runs accepts a step's connection whether the document carries it
  or requires it. The dhis2 pack's separate starters shelf is gone; its starters are the
  documents themselves.
- **The source pane holds the text it was handed.** Opening the editor from a starter or a
  file keeps the document's own text, comments included, until a structural edit; a typed
  comment survives its parse too.
- **A fetched result is committed before the outcome that settles it.** A worker that dies
  between fetching a remote step's result and recording the outcome settles from the committed
  result instead of fetching again. `fetch` is still at-least-once, and a repeat is now rare.
- **A captured stream comes through the context.** `ctx.capture(name)` names the storage
  object under the run's scratch and hands the block a sink and the URI; `shell.run`,
  `docker.run`, the compose and build blocks and `git.checkout` no longer name storage
  themselves. Output fields are unchanged; a capture's URI no longer ends in `.txt`.
- **What a finger lands on is 42px tall.** One token, `--spacing-finger`, sizes every control
  below the breakpoint, the dialog's Cancel included, which the old rule missed.

## 0.17.2

Released 2026-09-21. Every package in the workspace moves to 0.17.2 together.

- **Every block family is on PyPI.** `dirigent-block-duckdb`, `-jq` and `-parquet` publish
  with this tag, completing the nine. `pip install dirigent-cli` resolves again, and
  `uv tool upgrade dirigent-cli` moves an installed tool. Nothing else changed.

## 0.17.1

Released 2026-09-21. Every package in the workspace moves to 0.17.1 together.

- **Three more block families are on PyPI.** `dirigent-block-storage`, `-execute` and
  `-queues` publish with this tag. `-duckdb`, `-jq` and `-parquet` follow in 0.17.2, after
  which `pip install dirigent-cli` resolves again. Nothing else changed.

## 0.17.0

Released 2026-09-21. Every package in the workspace moves to 0.17.0 together.

- **The built-in pack is nine packages.** `dirigent-blocks` is now an umbrella over
  `dirigent-block-base`, `-http`, `-storage`, `-execute`, `-sql`, `-duckdb`, `-jq`, `-queues`
  and `-parquet`, each a plugin of its own, so a worker carries the dependencies of what it
  runs. A block package is named for what it brings: a family when it brings no dependency,
  the engine or codec when it does. `dirigent-parquet` is `dirigent-block-parquet`. Every
  block id, group and connection kind is unchanged; a stored pipeline notices nothing. The
  catalogue's `plugin` field names the family (`block-http`) where it said `builtin`.
- **Three of the nine are on PyPI with this release.** `dirigent-block-base`, `-http` and
  `-sql` publish now; the other six follow in 0.17.1 and 0.17.2, three per release, and until
  then `pip install dirigent-cli` does not resolve. The image at
  `ghcr.io/winterop-com/dirigent:0.17.0` carries all nine and is the way to run this version.
- **SQL engines are packages.** `dirigent-block-sql` keeps the `sql` connection kind,
  `sql.query`, `sql.execute` and the generic async SQLAlchemy path, and gains the `SqlEngine`
  contract, contributed under the `dirigent.sql.engines.v1` entry-point group. DuckDB is
  `dirigent-block-duckdb`; the `duckdb` extra is gone, and a URL naming an engine that is not
  installed is refused with the install line.
- **Every refusal carries a code.** A block failure, a domain error, the problem document, a
  CLI refusal, a health check and a client error each carry a stable dotted `code` and the
  `params` its text was rendered from, beside the English `message`. `Problem.problems` is a
  list of issues (`code`, `message`, `params`, `location`) rather than strings; attempts,
  runs and run items carry `error_code`. A pack raises `BlockFailure(MESSAGE, **params)` from
  its own catalogue under its name. The text a person reads is unchanged.
- **Out-of-process transform engines speak one protocol.** `dirigent-plugin` gains
  `ProgramRunner` and `RunnerEngine`: a pool of runner processes, `compile` / `run` / `forget`
  over JSON lines, and kill on cancel. The jq engine is the first runner, and a step's program
  now crosses the pipe once rather than once per element.
- **`dg health` lives under `dg system`.** `dg system health` and its named forms
  `database | worker | scheduler | server` replace `dg health`; the compose healthchecks and
  the scaffolded stack say `dg system health server` and `worker`.
- **One handler renders every domain error.** Every refusal the core raises carries its HTTP
  status, and the server renders it as the problem document in one place; the per-endpoint
  translation is gone.
- **A write names what the object is.** `Storage.open_write` takes a `content_type`, the S3
  backend records it on the object, and `storage.read` gets it back.
- **Packs by build argument.** `docker build --build-arg DIRIGENT_PACKS="dirigent-dhis2"`
  installs packs into the stock image without a Dockerfile of its own.
- **The ASGI factory is documented.** `dirigent_server.create_app` and `dirigent_cli.main:build_app`
  are named in the server page with granian and hypercorn examples.
- Also: every engine a test or a failed boot opens is disposed; the small-screen drawer asks
  for focus until it lands; the M5 milestone is marked complete and the roadmap says what is
  left.

## 0.16.7

Released 2026-09-20. Every package in the workspace moves to 0.16.7 together.

- **A field that names a thing shows the thing.** A block's config schema now says when a
  string holds the code of a connection or a schema: `ConnectionRef` and the new `SchemaRef`
  in `dirigent-plugin` publish `x-dirigent-ref`, and both stay plain strings to every
  validator. Under such a field the step panel draws one shut row: a schema the document
  carries opens to its body and says so, one the instance holds opens to its body and links
  to its screen, a connection reads its kind and its last check and links to its screen, and
  a code nothing holds is one muted line. `validate.schema` and `http.request` adopt the
  aliases; every other built-in connection field already carried `ConnectionRef`. A pack
  that types its connection fields `ConnectionRef` gets the row for free.
- **A chosen schema or connection is an address.** `/schemas/<code>` and
  `/connections/<code>` open that screen on the row with its panel filled, and choosing a
  row writes its code into the URL, the way Pipelines already works.
- **The schema editor knows what it holds.** The New schema dialog edits against the JSON
  Schema 2020-12 meta-schema: keywords complete as they are typed and a value the draft does
  not take is marked where it was written. Nothing is fetched; the meta-schema ships with the
  bundle. The editor gains its suggest controller, so document panes complete against the
  instance's document schema too.

## 0.16.6

Released 2026-09-19. Every package in the workspace moves to 0.16.6 together.

- **A project's `.env` is a settings layer.** Every command run in a project directory reads
  `DIRIGENT_*` settings from its `.env`, after the environment and before `dirigent.yaml`, the
  way the `local` profile already read `DG_TOKEN` from it. `dg init --template local` writes
  `DIRIGENT_SECRET_KEY` there beside the token, so a new project starts with the key its
  instance seals connection secrets with and a restart keeps it; the export step is gone from
  the getting-started page and the basics tutorial. A stack's `.env` is still the file compose
  reads, and the containers get it as environment.

## 0.16.5

Released 2026-09-19. Every package in the workspace moves to 0.16.5 together.

- **`dg connection create` asks only what it has to.** At a terminal it prompted for every
  secret field left unset, optional ones included, so a documented one-liner stopped at
  `api_token:` until Enter. It now prompts for a secret only when the kind requires it, or for
  every secret when no `--set` was given at all; `--json` still refuses a missing required one.
- **An empty secret is not a credential.** `--set api_token=` was an empty secret that a kind's
  validator read as chosen and a listing showed as `***`. The CLI drops an empty secret at
  `--set`, and every write path, the API's create and update included, stores an empty
  optional secret as unset and refuses an empty required one.
- **A table's title never folds.** The run header's title wrapped to the widest row, so a
  36-character run id broke after 35 columns whenever the pipeline name was short. A title now
  sits on its own line above every table.
- **`dg dev` dies with the process that started it.** A wrapper killed with SIGKILL forwards
  nothing, and the instance lived on to claim later runs against the same state. `dg dev`
  watches the pid that started it and shuts down the way SIGTERM does when that parent is gone.

## 0.16.4

Released 2026-09-18. Every package in the workspace moves to 0.16.4 together.

- **The step panel reads the config first.** What a step does is its block's config, so the
  panel opens on that form, folded the way every generated form is: required fields and the
  ones the document sets in front, the rest behind "N more fields". The engine's half sits under
  it as five groups, Waits for, Fan-out, Timing, Retry and Rule, each one row saying what would
  run, the document's values in body ink and the defaults in muted, and each opening in place.
  The display name comes last.
- **A map of scalars is a key/value table.** `query`, `headers`, `env`, `build_args` and every
  other map of strings, numbers or booleans is edited as rows of key and value rather than as
  JSON in a textarea, in the step panel, the run dialog, triggers and connections alike. A cell
  takes the narrowest shape the map allows, a duplicate key is marked where it stands, and a
  reference standing for the whole map is drawn as the reference.
- **A string option is drawn bare.** A select showed `"GET"` while its hint said `default GET`;
  a string option now wears no quotes, and only a number, a boolean or null keeps its JSON
  spelling.

## 0.16.3

Released 2026-09-17. Every package in the workspace moves to 0.16.3 together.

### Before you upgrade

**A pack with a shell-string field takes a new base.** A config that marks a field with
`ShellString` now derives from `dirigent_plugin.ShellVariables`, which is where the engine
hands the block the values it substituted out of the string; a config that does not is refused
at claim time. The built-in `shell.run` and `docker.run` already do. A transform engine may
override `Engine.offload` to say how its programs run off the event loop; the default is a
thread.

### Fixed

- **A substituted value never reaches the shell.** Every `${...}` in a shell string becomes a
  variable the engine sets in the command's environment, one word wherever the author put it,
  so a webhook payload cannot become a program however the reference was quoted. Inside the
  author's single quotes the command reads the variable's name, which the shell keeps literal.
- **`git.checkout` stays inside the run's work directory.** A target that leads through a
  symlink, or lands outside the work directory once resolved, is refused before anything is
  inspected, cleared or cloned; a symlinked target is unlinked rather than followed.
- **An alert that fails to render cannot undo settled work.** A template that raises while
  rendering falls back to the default subject or body with a timeline entry, and raising alerts
  is a savepoint inside the settle transaction, so nothing on the alert side rolls back a
  finished attempt.
- **`rabbitmq.consume` acknowledges after it has read.** Under `on_success` the whole batch is
  decoded first; an unreadable body requeues every delivery and names which one.
- **A transform runs off the event loop.** The frames hand each step's engine call to
  `offload`, and jq programs run in a pooled process that the step's timeout or cancellation
  ends, so a long program no longer starves the worker's heartbeat.
- **A held run is always released.** Promoting a queued run takes the pipeline lock creation
  takes, and cancel takes the pipeline lock before the run's, so a run created while its
  predecessor settles can no longer be stranded.
- **A run's log entries commit in order.** A log flush holds the run's lock while it writes, so
  a stream paging by id cannot skip an entry that committed late.

## 0.16.2

Released 2026-09-17. Every package in the workspace moves to 0.16.2 together.

- **The basics, a two-part tutorial.** A new page under Start here walks the first three moves
  against Postman Echo, slowly: one HTTP request, a JSON Schema gate on the answer, and a send
  built from the validated value, with a refusal and a transient retry in between, every
  command run for real and the UI shown along the way. The second half, the same three moves
  against DHIS2, is in the `dirigent-dhis2` documentation. Both pages are also printed to a
  PDF that the published site carries.
- **The installed set can no longer mix two releases.** Every package requires its dirigent
  siblings at `==<version>`, so `uv tool upgrade dirigent-cli` moves every package and a guard
  test fails the fast lane if a bump leaves one behind. 0.16.1's `dg` crashed on import when
  the tool was upgraded by name alone, because only the CLI moved.
- **A watched run's queued step carries its own moment.** `dg run --watch` against a server
  stamped every `queued` record with a year-1 sentinel that rendered as `0001-01-01` with a
  local-mean-time offset; the record now carries the attempt's `created_at`. The run listing
  and the dashboard's feed of failed runs also answer a failed run's `error` with what its
  failed step said, where the column was empty before.

## 0.16.1

Released 2026-09-17. Every package in the workspace moves to 0.16.1 together.

- **`dg secret-key` generates the envelope key.** It writes a `DIRIGENT_SECRET_KEY` and
  nothing else, on one plain line at a terminal and in a pipe alike, so
  `DIRIGENT_SECRET_KEY=$(dg secret-key)` works in a shell and in a `.env`. It is the second
  plain-line command beside `dg --version`; every other command still writes records in a
  pipe. The README, `.env.example` and the docs name it where they used to show a python
  one-liner, and `dg init`, `dg run --local` and the dev seed mint their keys through the
  same generator.
- **HTTP 429 is transient.** `status_class` in the http blocks and the plugin's default
  classifier treated every 4xx as rejected, so a rate-limited step was never retried. A 429
  now sits beside 5xx; every other 4xx stays rejected.

## 0.16.0

Released 2026-09-16. Every package in the workspace moves to 0.16.0 together.

### Before you upgrade

**The bundled S3 server listens on loopback.** The compose stack, and the one `dg init`
writes, publish `S3_PORT` on `127.0.0.1` only. The stack itself still reaches the server as
`http://s3:9000`; a person on another host who inspected the bucket through the published
port now tunnels to it instead.

### Fixed

- **A duckdb session is held to the run's own directories by duckdb itself.** A path written
  straight into the `sql` of `sql.query` or `sql.execute`, such as `read_csv('/etc/hostname')`,
  reached past the boundary that only a `file://` parameter was checked against. The session
  now opens with the run's work directory and local scratch space as its `allowed_directories`,
  turns `enable_external_access` off and locks the configuration, so a literal path outside
  the run, a `COPY ... TO` outside it, a `SET` that would widen the roots and a `LOAD` of a
  further extension are all refused. The `s3://` scheme stays reachable for a step that names
  a bucket, on the storage connection's credentials as before.
- **A claim is fenced by its own token, not the worker's name.** A worker whose lease the
  sweeper took could reclaim the same attempt under the same name, and the abandoned call's
  outcome, remote handle or heartbeat then passed the fence and landed on the live claim.
  Every claim of a step attempt and of a notification now mints a `lease_token`; the outcome,
  the handle, the heartbeat and the lease renewal are refused unless the row still carries
  the token they were claimed with.
- **Artifact downloads, run reports and retention read storage through the configured
  connection.** The server's artifact route, the report writer and the prune sweep opened the
  `s3` scheme with no endpoint and no credentials, because only a step's context bound
  `DIRIGENT_STORAGE_CONNECTIONS`; on the compose stack an artifact could not be downloaded, a
  large report not kept, and scratch not pruned. Each of them now binds the instance's
  storage connections for the call.
- **`make docker-push` proves the image with `dg --version`.** The smoke check still ran the
  removed `dg version` command, so the push stopped before either tag went out.
- **The compose test suite needs no Docker daemon.** One `docker.compose.up` test left the
  daemon status read real; it now runs against the fake daemon like its siblings.

## 0.15.2

Released 2026-09-12. Every package in the workspace moves to 0.15.2 together.

- **`dg apply` names the file it refuses.** Each document is checked before the server sees
  it, and a refusal carries the path: a file that holds a `dg` record (what a redirect of a
  command in a pipe keeps, since a pipe carries records) is named as such together with the
  ways to get the document, a missing `format` names the file, and so does an unreadable or
  non-mapping file.
- **`dg examples show CODE -f FILE`** writes the document whatever stdout is, as the record
  `example.written`. The documentation's `> pipelines/mine.yaml` redirect, which kept a record
  and not the document, is gone.
- **`dg export -f` writes the file in a pipe.** It emitted the record and never wrote the
  file when stdout was not a terminal; the record now also carries the `path`.

## 0.15.1

Released 2026-09-12. Every package in the workspace moves to 0.15.1 together.

- **`dirigent-plugin` imports on Python 3.14.** 0.15.0 imported `Traversable` from
  `importlib.abc`, which Python 3.14 no longer carries, so the package could not be imported
  there and `dirigent-dhis2` could not follow. The name comes from `importlib.resources.abc`.

## 0.15.0

Released 2026-09-12. Every package in the workspace moves to 0.15.0 together, and the workspace
gains one: `dirigent-examples`.

### Before you upgrade

**`dg init` writes no hello pipelines.** The hello-world and the per-service hello documents
that `dg init` used to write from string constants are gone. A new project starts from a
starter instead: `dg init --pipeline <starter>` (repeatable), the same choice in the init form,
or `dg pipeline new <starter>` inside the project. With none chosen, `pipelines/` is created
empty and the closing line points at `dg examples list`.

**The examples corpus moved inside a package.** The documents live at
`packages/dirigent-examples/src/dirigent_examples/shelves/`; the repository root `examples/` is
a symlink to it, so `dg run --local examples/...` and every documented path keep working, and
links into the corpus on GitHub now name the package path.

**The compose stack pulls `mc` from quay.io.** MinIO's Docker Hub repositories are gone; the
`s3-bucket` service in `infra/compose.yaml` and in the stack `dg init` writes uses
`quay.io/minio/mc` at the same pinned tag.

### Examples and starters

- **The corpus is a plugin contribution.** A third extension point, `examples()`, beside
  `contribute()` and `formatters()`, returns the directories a distribution's shelves live in.
  The host walks them once, on first use, never at a worker's startup, and attributes every
  document to the plugin that shipped it. The core corpus ships as `dirigent-examples`, a
  distribution `dirigent-server` and `dirigent-cli` depend on, so every instance and every `dg`
  has it installed; `dirigent-dhis2` and `dirigent-integration` ship their shelves the same way.
- **A starter is an example that opted in.** The tag vocabulary gains `starter` in the
  behaviour group. A document earns it by being a real multi-step flow on a real source with
  nothing carried; 21 core documents carry it in this release. Copying a starter copies the
  source text verbatim, rewriting only the `code:` line and dropping `starter` from `tags:`, so
  the teaching comments survive and no template language appears; the copy's `requires` is the
  to-do.
- **Surfaces.** `GET /examples` (filters `tag`, `shelf`, `plugin`, `starter`) and
  `GET /examples/{code}` with the source; `dg examples list [--tag T] [--shelf S] [--plugin P]
  [--starter]` and `dg examples show <code>`; `dg pipeline new <starter> [--code X] [--dir D]`,
  which refuses a document that is not a starter and never overwrites; `dg init --pipeline`;
  `dg dev --seed-installed`, seeding every installed corpus with no path named.
- **The Examples screen.** A new screen beside Blocks lists the instance's corpus as the
  quartet with tags, plugin, a Starter mark and the requirements checked against the instance:
  which connections and schemas exist, which blocks are installed. A row opens the shipped
  document read-only with its requirements item by item and, for a starter, **Use as starter**.
  The New pipeline menu and the editor's empty state gain **From a starter**, a searchable
  picker grouped by plugin and shelf; choosing one opens the editor on the copy with the unmet
  requirements shown. Each block on the Blocks page says how many examples use it and links to
  them.

## 0.14.1

Released 2026-09-11. Every package in the workspace moves to 0.14.1 together.

Nothing in dirigent changed since 0.14.0. The number exists so that `dirigent-dhis2` 0.14.1 can
ship in lockstep: its `dhis2.data_value_set_import` block lost `source_uri`, the last field on
which a pack block read storage for a value on its own. A document that imported from a stored
object now composes `storage.read` into the import's `data_values`, as the pack's
import-from-storage example does.

## 0.14.0

Released 2026-09-11. Every package in the workspace moves to 0.14.0 together.

### Fan-out

- **A fan-out may adopt an upstream fan-out's grid.** `for_each: "${steps.A.items}"` on a step
  maps it over the items step A fans over, with the same index and the same `${item}`, fixed
  when the run is created like every grid. Inside it `${steps.A.item.output}` is A's matching
  item's output, not the batch. A must be in the step's own `depends_on`, and an adopting step
  may not carry `rule: one_failed`. Under `items: continue`, an item whose partner did not
  succeed is skipped rather than failed, and the step's own `items` policy governs its own
  failures. `steps.A.output` stays the positional list of the items that succeeded.
  `patterns/fan-out-item-wise.yaml` writes one file per region and lists what landed.

### The editor

- **A step opens on what it needs.** The step form lists the fields a block requires first, then
  the optional ones the document sets, then one link, `N more fields`, that opens the rest in
  place. Required labels are in body ink, optional ones muted.
- **A program's window is the whole screen**, with a reference for the language beside the
  editor: jq idioms and a link to the manual, the runtime's rules for SQL and shell, what a
  Jinja template may read. A field's `contentMediaType` picks the reference.
- **An alert rule's body is written in the dialog** and, with the subject, edited in the
  rule's panel; a template the server refuses shows its message in place.

### Blocks and the CLI

- `rabbitmq.publish` refuses a message nothing takes: the publish is mandatory, and a routing
  key no queue answers to fails the step instead of vanishing.
- `dg dev --seed DIR` applies every document under a directory once the API is up, schedules
  paused, creating the connections and schemas a document carries rather than refusing it;
  `make dev-seeded` uses it and now stores the whole corpus. `DIRIGENT_UI_DIR` names a built
  bundle for a server installed from git.

### Tooling

- The frontend gate (oxfmt, oxlint, vitest) runs in CI's browser lane. The e2e specs are
  formatted like the rest.

Nothing in the settings changed since 0.13.0 beyond `DIRIGENT_UI_DIR`.

## 0.13.0

Released 2026-09-11. Every package in the workspace moves to 0.13.0 together.

### Before you upgrade

**A value moves through step outputs; storage has two doors.** A block no longer reads or
writes storage for a value on its own. `storage.read` brings an object in as a value, decoding
it by content type (an override, else what the backend recorded, else the extension), and
`storage.write` puts a value or text out under a URI with a content type. The fields that let a
block do this itself are gone, with no aliases: `input_uri`, `save_to` and `max_input` on
`transform.jq`, `map.jq` and `filter.jq` (whose output is now `value` alone); `body_from`,
`save_to`, `text` and `form` on `http.request`, whose one `body` is sent as-is when it is a
string and as JSON otherwise, and whose response is now `status`, `headers`, `body`,
`body_bytes` and `duration_ms` (`json_body`, `text`, `body_uri` and `sent_bytes` are gone);
`records_from` on `kafka.produce`; `save_to` and `saved_to` on `sql.query`. The converters keep
their URIs, since a parquet or arrow file is an object and not a value, under the names
`source` and `target`, and no longer take an inline `input`. A document that used any of these
is rewritten to compose; every example in the corpus was. The capture URIs on `shell.run` and
`docker.run` are untouched.

**An alert rule's subject is a Jinja template.** `${run.pipeline} run ${run.status}` is now
`{{ run.pipeline }} run {{ run.status }}`. A rule written in the old grammar is not migrated
and must be rewritten. A template that does not compile is refused when the rule is created or
patched, naming the field and the line; a render that fails at raise time falls back to the
default with a warning in the run's timeline; an undefined name renders empty. Rules gain a
`body`, also Jinja, over the same facts plus `report`, the run's report document when it has
one: `--body` and `--body-file` on `dg alerts rules create`, and PATCH can change `template`,
`body` and `paused`.

### The run's report

- **A run renders a report document when it settles.** A document may declare `report:`;
  `report: {}` renders the built-in template, `report.template` an own Jinja one, refused at
  apply when it does not compile. The engine renders it in the transaction that settles the
  run, before its alerts are raised, and again when a run is cancelled, so the runs whose
  report matters most have one. The document is a run-level artifact, inline when small and
  under the run's scratch otherwise, rewritten in place when a retry resettles the run. A
  render that fails, exceeds `report_max_size` (1MB) or `report_render_timeout` (5s) leaves a
  WARNING in the run's log and never fails the run.
- **The template context** is the run's facts: `run.*` (the alert namespace plus the window
  and trace), `pipeline`, `steps` in order and `step` by name, each with its outcome,
  attempts, duration, warnings, error, last output and its size, `items`, totals, `url` and
  `rendered_at`; filters `duration`, `bytes` and `iso`. `docs/reports.md` is the reference.
- **Read it anywhere.** `GET /runs/{id}/artifacts` lists a run's artifacts and
  `GET /artifacts/{id}` serves one; `dg runs report --markdown` prints the document; the run
  view has a Report tab with a maximize-to-window control and a download link, and the Output
  tab's artifacts are now downloadable.
- **`report.render` renders text mid-pipeline** and passes it on as output, so a later step
  can send it anywhere: `storage.write` to a file or a bucket, `kafka.produce`,
  `rabbitmq.publish`, `webhook.post`. Five examples show one sink each.

### Blocks

- New: `storage.read`, `storage.write`, `log.write` (one line in the run's log, the value
  passed through), `rabbitmq.publish`, `report.render`.
- `sql.query`'s statement is a program (`application/sql`), so the editor opens it in Monaco.

### The editor

- The Report pane edits a document's report template in Monaco with Jinja colouring, or
  chooses the built-in template or none.
- Program fields are coloured: a jq grammar (Monaco ships none), and SQL through Monaco's own.
  Every program and JSON field opens in a large window, with the button at the pane's corner
  where it covers no text.
- Fixed: a Monaco pane kept the palette being left when appearance was switched.

### Tooling

- The frontend is formatted with oxfmt, pinned, in the house style; `make ui-fmt` formats and
  `make ui-lint` checks.

### Examples

- `recipes/http-post-report.yaml` and `recipes/report-built-in.yaml` show the run's report;
  `report-to-file`, `report-to-s3`, `report-to-kafka`, `report-to-rabbitmq` and
  `report-to-webhook` show `report.render` feeding each sink. The vocabulary gains `report`.

Nothing in the settings changed since 0.12.0 beyond the two report settings above.

## 0.12.0

Released 2026-09-10. Every package in the workspace moves to 0.12.0 together.

### Before you upgrade

**`GET /system/info` repeats each connection's last check instead of probing.** Its
`connections` rows carry `last_check_at`, `last_check_healthy` and `last_check_detail`, the
same three fields a connection's own row holds; `connected`, `detail` and `version` are gone,
and a row nothing has checked carries nulls. The read used to open every connection inside
its own transaction, and the UI makes it on every page load: on SQLite each refresh ran every
connect timeout while holding the write lock, and a few refreshes in a row starved the worker,
the scheduler and other requests into "database is locked". A probe happens where it is asked
for, `dg connection check` and the UI's check button, and `dg system info` renders
`last check`, `healthy` and `detail`.

### Fixes

- **A check holds no transaction while its probe is out.** `POST /connections/{code}/$check`
  reads the row, probes, then writes the result in a second transaction, so a system that is
  slow to refuse no longer holds the write lock for the length of its connect timeout.
- **A Kafka consumer whose start failed is stopped**, which removes the
  `Unclosed AIOKafkaConsumer` line the event loop logged after every refused check or poke.
- **A refused Kafka or RabbitMQ connection is reported once.** The `aiokafka` and `aiormq`
  loggers are floored; the check's row or the step's failure carries the message.
- **`make dev` and `make dev-seeded` start from an empty state.** Both pass `--wipe-state`
  to `dg dev`; `make dev` is new.

Nothing in the schema or the settings changed since 0.11.0.

## 0.11.0

Released 2026-09-09. Every package in the workspace moves to 0.11.0 together.

### Before you upgrade

**The terminal decides the output.** Every command, `dg dev` and `dg server` included, renders
when stdout is a terminal and writes NDJSON when it is not. A pipe, a file, a container's log,
an agent's shell and CI are never terminals, so a script, `docker logs` and a collector see no
change: records, one per line, without asking. What changes is what a person sees: `dg pipeline
list` draws its table, `dg dev` prints its lines, and nothing is piped through `dg format` to
be read. `--json` (or `-o json`) asks for records at a terminal, `-o console` for the rendering
into a pipe, `DIRIGENT_LOG_FORMAT` names either once, and `dg format` reads a stream that was
kept. `dg init` follows the same rule, so in a pipe it writes records. Nothing in the schema,
the wire or the settings changed since 0.10.2.

## 0.10.2

Released 2026-09-09. Every package in the workspace moves to 0.10.2 together.

### Command line

- **`dg init` closes on the one fact that is not obvious.** The paragraph about SQLite and the
  compose stack is gone; what stays is that no secret key is set, so a connection carrying a
  credential cannot be stored until it is. Nothing in the schema, the wire or the settings
  changed since 0.10.1.

## 0.10.1

Released 2026-09-09. Every package in the workspace moves to 0.10.1 together.

### Before you upgrade

**`dg version` is gone; `dg --version` is the way to ask.** It answers with one plain line,
`dg 0.10.1`, the way every CLI answers the flag, and the `version` record with the package
table is no longer written. Nothing in the schema, the wire or the settings changed since 0.10.0.

## 0.10.0

Released 2026-09-09. Every package in the workspace moves to 0.10.0 together.

### Before you upgrade

**`dg init` has three templates, and two flags are gone.** The templates are `local` (an
instance on this machine, on SQLite), `compose` (a container stack) and `documents` (the documents alone).
`basic` and `ci` are gone: `basic` is `local`, and the workflow `ci` wrote is `--workflow` on
any template. `--documents-only` is `--template documents`. Nothing in the schema, the wire or
the settings changed since 0.9.5.

### Command line

- **`dg init` at a terminal is one form.** Where the project runs, which services the stack
  carries, which packs come along, a workflow, and the first admin's username and password
  typed twice, all on one screen, written only on Create. Escape leaves nothing behind. Without
  a terminal, or with `--template`, the flags answer the same questions.
- **The stack's services are chosen.** `--service s3` (on by default; off means artifacts on a
  volume), `--service docker` (the workers' own daemon), `--service kafka` and
  `--service rabbitmq` (a broker, its connection bootstrapped, a `hello` topic or queue
  declared). Each service brings one example into `pipelines/` that uses it.
- **Packs are a flag.** `--pack dirigent-dhis2` pins the pack at this version, in the stack's
  `Dockerfile` or in `pyproject.toml`.
- **A scaffolded project starts at 0.1.0**, not 0.0.0.
- The `project.scaffolded` and `instance.initialised` records carry `services`, `packs` and
  `workflow` beside `template`.

## 0.9.5

Released 2026-09-09. Every package in the workspace moves to 0.9.5 together.

### Before you upgrade

Nothing in the schema, the wire or the settings changed since 0.9.4.

### Command line

- **`dg init` refusing over an existing instance reads as a table.** The sentence is red, and
  each way out is a bold command with what it does dimmed beside it; the `--json` record is
  unchanged.

## 0.9.4

Released 2026-09-09. Every package in the workspace moves to 0.9.4 together.

### Before you upgrade

**`dg dev` keeps `.dirigent/state`.** It runs the instance that is there, the one `dg init`
made or an earlier start left, and migrates it forward. `--wipe-state` deletes the state first
and is now the only way it goes; `--keep-state` is the default and no longer needs saying. A
script that relied on every start beginning from nothing passes `--wipe-state`.

Nothing in the schema, the wire or the settings changed since 0.9.3.

### Command line

- **A plain `dg dev` after `dg init` runs that instance.** Its admin stays, the token in
  `.env` keeps working, and no development admin is minted over it.
- **The init text, the scaffolded README and the hints say `uv run dg dev`.**

### Web UI

- **The login stacks below 1024px.** The brand pane is never drawn under its 560px floor, so
  the graph is never squeezed into a strip; between 1024 and 1280 the pane holds the floor and
  the form column takes the rest.
- **A refused sign-in is a notice below the button that takes no room.** The server's
  sentence is drawn in a critical-edged bar hung under the button, out of the flow, so the
  centred form never moves; it replaces the bare line under the password field.

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
  `Reset password`{ .label } button in the account panel. Every session of the account ends; its API tokens
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
