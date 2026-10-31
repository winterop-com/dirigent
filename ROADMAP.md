# Roadmap

What is left to do. The design specification is [docs/design.md](docs/design.md); what
already works is documented in [docs/](docs/index.md).

## Settled

Decisions that still constrain the code. What each one replaced is in the commit that made
it; what it forbids is here, because that is what somebody is liable to undo.

- **The terminal decides the output.** At a terminal a command renders; anywhere else it
  writes NDJSON, one record per line. `--json`, `-o console` and `DIRIGENT_LOG_FORMAT`
  override, and `dg format` renders a kept stream. `dg --version` and `dg secret-key` answer
  with one plain line everywhere, because the value is the whole output.
- **A table is a rendering of a record, keyed by its `kind`.** `dirigent_cli/summaries.py`
  maps a kind to what it draws beneath its line; a kind with no entry renders as its line
  alone, which is what keeps a record from a plugin or a newer dirigent readable. No command
  renders; the formatter does, so the live stream and `dg format` are one path.
- **Verbosity decides which records exist; the output does not.** `dg run -v | dg format` is
  `dg run -v -o console`. Tying detail to the output would make every default run verbose.
- **`kind` is the discriminator, and adding one is compatible.** Removing or repurposing one
  is not. A formatter renders an unrecognised kind rather than failing.
- **A formatter is a name, a version and one render method**, registered through the
  `dirigent.formatters` entry point group. `console` and `compact` are built in.
- **One format language.** `dg format` takes a formatter name, never a template. `jq` selects
  by `kind` over the NDJSON; a template would be a second way to say the same thing.
- **Telemetry is OTLP push and nothing else; there is no `/metrics` and nothing scrapes
  dirigent.** A collector is what a backend scrapes. `infra/compose.otel.yaml` is the worked
  example, and an instrument that only a scrape could serve does not get added.
- **A command's story is stdout and its diagnostics stderr, in one grammar.** `2>/dev/null`
  leaves a clean story and `--json | jq` cannot be polluted. A process is the exception: its
  stdout is its log. A logging event renders as a record, the logger naming the source column
  when no step claims it.
- **The claim locks the attempt then the run; an outcome locks the run then the attempts.**
  Two workers can close that into a deadlock, so both transactions re-read everything they
  decide on and the aborted one is run again. A buffered log is drained before the retry, not
  inside it: draining empties it, and a second run would commit an outcome with no log.
- **Nothing is pruned until an age is set.** Each family has its own, a run is pruned only
  once settled, and a pruned run's artifacts go before its rows -- a row deleted first leaves
  bytes nothing points at. `retention_scratch` is how an instance whose bucket somebody else
  reaps says not to.
- **A row's age is `created_at`, on every table.** Every table carries `created_at`, so
  anything asking how old a row is asks one question. An entity carries `updated_at` besides;
  a journal row, which is written once and never touched again, does not.
- **There is one migration, before 1.0.** The baseline is edited in place, because an amendment
  is where an ALTER behaves differently from the CREATE that would say the same thing, and a
  state an older dirigent wrote is refused at boot rather than migrated. What proves the baseline
  faithful is the two drift tests, on SQLite and PostgreSQL.
- **`common` holds what more than one package needs.** A thing two packages need belongs
  below both. `status_class`, `is_success` and `ErrorClass` are deliberately not there: lift
  a plugin helper when a second adapter pack duplicates it, not before.
- **A reference entry says what a thing is and stops.** Both generators render the first
  paragraph of a description; tuning advice lives in operations, beside the arithmetic.
- **A request's transaction commits before its response is sent.** The exit of a dependency
  that yields runs after the response has gone out, so committing there told a client its
  write had happened before it had: a client reading straight back could miss what it just
  wrote, and a commit that failed did so after a 2xx. `Transactional` commits while the
  response can still become the error instead.
- **A step is exactly one of `block`, `source` or `reply`.** Sources are roots, and in a pipeline
  with sources every other step descends from one: a root beside them would run on every input
  from every source. A step joining two sources' branches says `all_done` or `always`, since
  under `all_success` it could never run. Such a pipeline carries no schedules, because what they
  started would enter no source.
- **Neither a source nor a reply is retried.** Running an input again is a new run. A reply
  settles once, rendered by the server when the steps it answers from have settled, and no worker
  claims it, so a reply costs no queue hop.
- **Nothing before an endpoint source's own bucket writes a journal row or spends from it.** A
  caller without the token or the secret, or in a loop, cannot cause writes; those are counted in
  telemetry instead. The one write ahead of the bucket is the record of a signature taken, which
  only a caller holding the secret causes. An endpoint takes no files: a caller with a file posts
  a URI and the pipeline fetches it.
- **A source kind is hosted one of three ways, and its contract says which.** The server receives
  it, with no connection and no secret in reach while a request becomes an input; a worker polls
  it; or a worker holds it open through a lease. A pack contributes a kind through
  `Contribution.sources`, and never a fourth way of being hosted.

## Next up

Ordered. Each is one working chunk. Working rules for any session picking these up: read
CLAUDE.md first, commit with conventional messages, every change ships with its test,
`make check` and `make test-postgres` stay green, coverage stays at or above 90,
`mkdocs build --strict` stays clean, and every example stays executable.

1. **A full UI redesign.** The fonts, the corners and many of the components are not good enough,
   and the screens say less about a pipeline than they should. The order is fixed: Codex first,
   for directions; then a Claude Design canvas, to choose among them and work the choice out;
   then `docs/ui-conventions.md`, which stays binding and changes before the code does; then the
   code across every screen, reviewed with the `ui-review` skill in both palettes. What it has to
   settle:
   - **The type.** The faces, their sizes and weights, and where mono is used.
   - **Corners.** The 1/2/2 radius ladder reads as square, which is not what was wanted, so the
     radius is open again.
   - **The components that read weakest.** Which ones is listed as part of the directions.
   - **The pipelines list and its panel show what a pipeline does,** a graph first.
   - **Examples are separated from a person's own pipelines.**
   - **No column that says nothing.**

   Where it stands: Codex drafted three directions as live HTML with real data, in
   `redesign-directions/` beside this repository (A operator console, B flow first, C quiet
   document), with a board of five corner ladders on the same components. None is chosen yet, and
   nothing in `docs/ui-conventions.md` or the code has changed for it. The choice comes next, then
   the chosen direction on a canvas, then the conventions, then the code.
2. **What the third security review left open.** The review and the sibling packs' first reviews
   are fixed and merged; these are what they did not settle, each its own slice:
   - **A backtracking `pattern` in `validate.schema` holds a worker.** Python's `re` keeps the
     interpreter's lock, so a thread does not help; it takes a killable process or a regex engine
     without backtracking. `unevaluatedItems` and `unevaluatedProperties` stay quadratic, about a
     minute of thread time at the 1 MiB cap.
   - **A run-wide storage quota.** The packs now bound each answer, but many answers under the
     bound still fill storage, and only the engine can count a run's total.
   - **The two ten-year bounds,** `LONGEST_POLL` and `LONGEST_INTERVAL`, are one rule written
     twice and want one constant.
   - **The units the reviews never reached.** Step deadline arithmetic, gate expansion and the
     lease sweep, attempt reads at the depth limit, retention sweeps, alert queueing,
     `dg pipeline new` writing to a name the instance chooses, storage blocks across runs, tokens
     refused by header on step paths, and connection fields a reference chooses. In the packs: the
     `analytics_run` probe and retry logic, what the shipped schema gates admit, a credential a
     service echoes back, a job's end of life, and `capture`'s unbounded read of an error answer.
   - **Leads that need a real service to settle.** Which of a data value set's own `dryRun` and
     `strategy` and the step's query DHIS2 obeys, which decides whether a document's body can turn
     a dry run into a write; a broker message stalling polled sources on PostgreSQL; a checked-out
     symlink redirecting a run-relative SQLite file.
   - **The parallel-sleep CLI test is flaky.** It expects the three roots queued in the order
     written, and a loaded runner queues them in another.
3. **dirigent-fhir: FHIR as a system of its own.** A general FHIR pack, not a DHIS2 one: a
   pipeline that pulls from one FHIR server and pushes to another, neither of them DHIS2, is as
   much its purpose as feeding DHIS2. It depends on the FHIR engine only, and carries no DHIS2
   dependency. Between steps a resource or a Bundle is plain FHIR JSON, as a data value set is
   in the dhis2 pack, so `transform.jq`, references and storage work on it unchanged; inside a
   block the engine's R4 models type what they cover (an `OperationOutcome` read into a step
   failure, a transaction `Bundle` built), and a resource they do not model passes through as
   JSON. Stages, each its own slice:
   - **A `fhir` connection kind and the REST blocks.** Read, a search that follows
     `Bundle.link[next]` under a page cap or hands its pages to a fan-out, create, update, and
     transaction/batch. Writes are idempotent by FHIR's own means: conditional create
     (`ifNoneExist`) and conditional update on `identifier`, never on the source server's ids,
     and a transaction rewrites references between the resources it carries as `urn:uuid`
     entries. An `OperationOutcome` is classified the way the dhis2 pack classifies an import
     conflict, and the health check reads `/metadata`. The first flagship is FHIR to FHIR on a
     schedule against a public test server (`hapi.fhir.org/baseR4`).
   - **FHIRPath on the verb frames:** `transform.fhirpath`, `map.fhirpath`, `filter.fhirpath`,
     the mapping between two servers' profiles being where FHIRPath earns its place over jq.
   - **CQL and measures.** `fhir.cql` evaluates a library over the resources a step produced
     (a Bundle, a search, one patient's compartment), with libraries resolved from the
     document, from storage, or as ELM; `fhir.measure` runs a Measure and answers with a
     MeasureReport, which a pipeline then pushes to another FHIR server or, through
     `dirigent-dhis2`, into DHIS2 as aggregate data values. Terminology for `in`/`memberOf`
     comes from a value set carried in the step or from a remote FHIR terminology server.
   - **Validation, profiles and IG packages:** structural validation first, then a profile
     resolved from a pinned package (`name#version` from the FHIR package registry), a
     package cache, and terminology for bindings.
   - **FHIR in through an endpoint source:** `application/fhir+json` taken, shaped, imported into DHIS2 by the dhis2 pack, and answered with a reply, in
     `dirigent-integration`'s `shelves/fhir/` with a standalone `fhir-to-dhis2` walkthrough.
     Converting a QuestionnaireResponse into DHIS2 uses `dhis2w-fhir` and belongs in
     `dirigent-dhis2`, not here.
   - **The read side** (`/metadata`, reads, searches, history) served by facade routers
     mounted inside the dirigent server, picking only the routers wanted. This needs a routes
     contribution surface, the open question "A server in the mix" below.

   **What dhis2w-fhir already has, and what to release outside dhis2w.** Most of the engine
   this pack needs exists in the `dhis2w-fhir` repository's `dhis2w-fhir-engine`, with no
   DHIS2 in it: FHIRPath, CQL and ELM evaluators, each run against its conformance suite;
   measure evaluation by the conventional population definitions; data sources over memory, a
   Bundle and one patient's Bundle; CQL library resolvers over files, memory and a composite;
   a terminology service, in memory or against a remote FHIR server; UCUM unit conversion; and
   closed, frozen R4 models for about twenty resource types that reproduce the wire document
   key for key. Recommended:
   - Release the engine under a name that carries no `dhis2w`, so a FHIR user with no DHIS2
     finds and trusts it, and have `dhis2w-fhir` depend on it as `dirigent-fhir` does. The
     DHIS2-bound packages stay where they are: IG generation from DHIS2 metadata
     (`dhis2w-fhir`) and the facade that projects DHIS2 and captures QuestionnaireResponses
     into it (`dhis2w-fhir-serve`).
   - Add the FHIR REST client neither has as a generic package beside the engine: search
     paging, conditional create and update, transaction bundles with `urn:uuid` references,
     `OperationOutcome` parsing, and `/metadata` reading. `dirigent-fhir`'s REST blocks are a
     thin layer over it, and `dhis2w-fhir-serve` reuses it wherever it talks FHIR outward.
   - Keep the R4 models hand-written and growing by need rather than generating all of R4;
     a resource without a model is carried as JSON, so the list never gates a pipeline.
   - Generic IG package loading (registry fetch, cache, `name#version`) is new work: the
     package reader `dhis2w-fhir` has is for its own organisation-unit registry. It belongs
     beside the engine too, since validation in both repositories needs it.
   The pack depends on these by package name, not by repository.
4. **`dirigent-full-demo`: one instance with everything, for the tutorials.** A `dg init` project
   in the workspace, beside `dirigent-examples`. It is one instance that has it all:
   - every package and pack as dependencies, `dirigent-integration`'s shelves included;
   - every service the corpus teaches with, running in its compose stack: object storage
     (S3), Kafka and RabbitMQ, PostgreSQL, the warehouse, and the telemetry and alert
     sinks;
   - a `dhis2` connection to the play demo, with a gate in its verify that checks the demo
     is healthy;
   - every example applied and runnable, the sources shelf included;
   - a `verify.sh` that brings it up from nothing, applies, runs the corpus and asserts
     green, the way the example repos do.
   It is a demo, not a product install; a real instance still installs only what it uses.
5. **A DHIS2 app for dirigent, shipped with dirigent-dhis2.** DHIS2 people want to see and run
   their pipelines from inside DHIS2: an App Platform app, installed through App Management,
   listing the pipelines that touch this DHIS2 instance, their runs and logs, and the sources
   waiting for input, with run, pause and rerun where the user may. It belongs to
   `dirigent-dhis2`, not here, and it reuses this repository's design system rather than
   re-drawing it. Most of the work is identity, and it has to be settled before any screen:
   - *Who the caller is.* A DHIS2 app runs on the DHIS2 origin with the DHIS2 session; dirigent
     has its own users, roles and tokens. The candidates are DHIS2's Route API (2.41+) holding a
     dirigent token server-side and proxying under `/api/routes/<id>/run`, which keeps the token
     out of the browser but makes every DHIS2 user who may use the route the same dirigent
     principal; dirigent trusting a DHIS2 session it verifies against that instance's
     `/api/me`, mapping DHIS2 users or groups onto dirigent roles; or OIDC with DHIS2, or the
     identity provider both already use, as the issuer. It meets the open question on
     authentication beyond tokens.
   - *What a DHIS2 user may see.* Roles alone are too coarse when one dirigent serves several
     DHIS2 instances: a pipeline needs to say which instance, or which DHIS2 user groups, it
     belongs to, and listings and actions filter on that.
   - *Embedding.* The security headers deny framing (`frame-ancestors 'none'`), and the API
     takes no cross-origin calls. The app either talks only through a DHIS2 route, which needs
     neither, or dirigent gains a configured list of DHIS2 origins it allows, for framing and
     for CORS.
   - *Where it ships.* A built app zip as a release asset of `dirigent-dhis2`, versioned with
     the pack, with the App Hub as a later option.
6. **More packs.** An outside system goes in the one `dirigent-contrib` package, beside Chap and
   the open climate service, rather than in a package or a repository of its own. Only a system
   big enough to carry its own repository takes one, as `dirigent-dhis2` does, with its own
   examples and tests, self-testing against `dirigent-plugin`'s main and assembled by
   `dirigent-integration`. Either way a pack is wired through a connection kind, with a client
   written fresh or wrapping a stable one.
7. **AI blocks: local models and hosted APIs, both first-class.** A pipeline step that asks a
   model, whose answer is data a later step can read rather than prose. Local is the starting
   point, so an AI step runs in `dg run --local` with nothing in the cloud; a hosted API sits
   behind the same blocks, and a document moves between them by changing the connection.
   - **What is decided.** Local and hosted share one set of blocks, with local first. Providers
     are connection kinds, each holding its endpoint and sealed key: the OpenAI wire shape first,
     since most hosted and local servers speak it, and Anthropic beside it. Every call is recorded
     like an HTTP call (model, tokens, `duration_ms`), and an answer is validated before it counts.
   - **`ai.complete`, `ai.classify` and `ai.embed` for models that generate.** A prompt, optional
     context from upstream outputs, and a JSON Schema the answer must fit. The local start is
     LiquidAI's LFM3 family: `text` (LFM3-1.7B, with tool calling), `vision` (LFM3-VL-2B, images
     in), `omni` (LFM3-Omni-2B, images, video and audio in, text or speech out) and `audio`
     (LFM3-Audio-2B, speech in, speech or text out), as GGUF and as MLX.
   - **`ai.decide` for the d1 decision models,** a block of its own because d1 does not generate
     and chat routes refuse it. Given a situation (text, JSON, images, and audio for d1-Omni) and
     named questions, d1 answers all of them in one forward pass, in milliseconds, with calibrated
     probabilities: `noul` (P(yes)), `choice` and `score`. The MLX builds add multi-choice,
     extracted `text`, `number` and `date` with a span and P(found), number estimates with an
     interval, and boxes. llama-server answers d1 at `/v1/systemone`. It fits gates and branching
     because a probability can be compared against a threshold, and since a document has no
     branching on a value, the comparison belongs in the block: it decides, and fails or succeeds
     accordingly, and `one_failed` takes the other edge.
   - **What is open.** Whether dirigent talks to `lfm3`'s API as a connection or directly to
     llama-server. `lfm3` is a playground rather than a product: one binary serving a JSON API, an
     OpenAI-compatible API and an MCP server over llama-server (GGUF) and mlx-vlm (MLX). Going
     direct leaves the MLX-only d1 answers behind, because mlx-vlm's server refuses d1 and the
     bridge serving it is `lfm3`'s own. Also open: who starts and stops a local model's process,
     how a question's threshold is written on `ai.decide`, and which LFM3 uses beyond text get a
     block (speech, transcription, images in). The likely home is a pack rather than a built-in,
     so an instance that runs no model carries nothing for it: by the naming rule a block family
     is `dirigent-block-ai`, outside the `dirigent-blocks` umbrella. Whether it lives in this
     repository or in `dirigent-contrib` is open too.

## Open questions

- **Scoped authorization.** Three instance-wide roles are the whole model: a viewer reads,
  an operator may define, run and schedule every pipeline, and an admin hands out authority.
  There is no way to let a team run its own pipelines and nobody else's, or to bind a
  connection to the pipelines that may use it. Wanted: a scope below the instance -- a
  pipeline, a connection, and probably a grouping of both such as a project -- and grants
  that pair a principal with a role inside a scope, enforced at the same route boundaries
  the instance roles are enforced at today. To decide before building: whether the scope is
  a project that owns pipelines and connections, or tags on each; whether a token carries
  grants of its own or borrows its owner's; and how a document applied from git names the
  scope it lands in. The multi-tenancy question below is the same question one size larger.

- **Expression language.** The reference syntax is deliberately references-only. The
  trigger for adding a JMESPath-class expression layer is a real pipeline that cannot be
  expressed; none has appeared yet.
- **Tags as things, and tag groups.** A tag is a bare word today: any document may write any
  word, and the filter menu is the union of every word ever written. The example corpus keeps a
  vocabulary of shelf, block family and behaviour words by convention and by a README paragraph,
  which is all the format offers -- nothing refuses a document that writes a word outside it,
  and nothing tells a reader which group a chip belongs to. Wanted: a tag as an addressable
  thing with the quartet (`code`, `name`, `description`, and room for a translation of the
  name), created on first use or declared ahead, so the menu can say what a word means; a group
  a tag belongs to (family, behaviour, shelf), so the filter menu and a row's chips read as
  facets rather than one alphabet; and an instance setting that refuses a tag no declaration
  names, for the instances that want a vocabulary. The listing filters, the chips and
  `requires.tags` stay as they are; a tag object is what they point at.

- **Multi-tenancy.** Single team assumed; workspace/project grouping would need schema
  room before it gets expensive. Not currently planned.
- **Per-URI storage connection selection.** `storage_connections` maps scheme to one
  connection instance-wide, so a pipeline cannot address two S3 endpoints. The natural
  fix is per-URI selection, which is a format change; deferred until needed.
- **OIDC/SSO.** JWTs enter at the federation boundary only (validate IdP tokens,
  realistically Keycloak, then issue dirigent's own opaque credential). Internal tokens
  stay opaque; the rationale is in docs/security.md.

- **A server in the mix.** Everything dirigent runs today is a step that starts, does its work
  and ends, and everything it talks to is somewhere else. Two things a person might mean by
  "add a FastAPI server" are worth deciding between. One is a pack contributing HTTP routes
  and a screen to the dirigent server itself through pluginkit -- a new surface beside
  blocks and connection kinds, the server mounting a pack's router under `/api/v1/<pack>` --
  which raises who authenticates those routes and how they appear in the OpenAPI document.
  Endpoint sources answer the narrower case, a pipeline answering a path, and dirigent-fhir's
  read side is the first concrete user of the wider one. The other is a pipeline whose
  step is a long-lived service: an app a run starts, health-checks with `http.ready`, uses for
  the rest of the run, and tears down, the shape `docker.compose.up` and `.down` already give a
  compose stack, but for a process the worker owns. To decide first: which of the two is
  wanted, since they share a word and nothing else.

- **What input sources still leave open.** An `Idempotency-Key` header de-duplicating a caller's
  retries into one run; authentication beyond tokens, which waits on the OIDC question above; and
  whether a public endpoint needs an instance-wide switch before any pipeline may declare one.

- **`starter` or `template`.** The web UI calls a copyable document a template, and the API, the
  CLI and the packs still say `starter`: the `starter` tag and field, `dg examples list --starter`,
  `dg pipeline new <starter>`. Whether to rename them to match, given that `dg init --template`
  already means which kind of project to scaffold.

- **Whether the worker and its Docker daemon need their own host.** The dind sidecar shares a
  network with the worker alone, so the database and the bucket have no name a container can
  resolve, but the route to their addresses stays open on Docker Desktop, as
  [measured here](docs/docker.md#the-reference-shape-a-dind-sidecar). To decide: whether the
  reference deployment moves them to a host of their own rather than only recommending it.

## Wanted

- **What else importance should reach.** The field is declared and the alert rules match on
  it, so a critical failure pages while a routine one logs. Three readers are still missing,
  and each is a slice of its own: the stuck-run detector treating a critical run as an
  incident sooner than an hour, the dashboards and the run list putting the critical work in
  front, and retention keeping a critical pipeline's history longest where it is instance-wide
  today.

- **What an artifact is.** Today an artifact is exactly one thing: a step's structured
  output, kept inline when small and written to `outputs/<attempt-id>.json` when not, with a
  digest, a size, and links to run, attempt and step. The files a block actually writes are
  not artifacts: `shell.run`'s captured streams and `storage.copy`'s target are storage URIs
  mentioned inside an output, with no row of their own. So the thing a person most wants --
  the fetched payload, the command's stdout -- is untracked, while the small JSON that merely
  names it is tracked. Three consequences: the API lists and serves only the small JSON, and
  there is no `dg artifact` command at all; retention cannot clean up files it holds no
  reference to; and a run cannot answer what it produced.
  Which way to close it is genuinely open. Either a block DECLARES a URI as an output and the
  engine tracks, lists, retains and serves it -- which makes downloads, retention and the
  run view work from one concept -- or artifacts stay strictly the step's return value
  and files remain incidental, which is simpler and leaves the gap. Decide it against a real
  pipeline rather than in advance, and revisit if the answer turns out to be that everything
  lives in object storage anyway, where a URI and a bucket policy may be all the tracking
  anyone needs.

- **The Examples screen for a slim install.** `dirigent-integration` is published
  as the cross-boundary shelves alone: its only runtime dependency is `dirigent-plugin`, and
  the assembly the control center tests is a dependency group that never reaches PyPI. So
  `uv add dirigent-integration` adds 24 documents that each name the packs they need under
  `requires`, and no packs. The screen then wants a "runnable here" filter (every requirement
  installed), a filter by contributing plugin, and `dg init` offering the shelves as a choice.

- **A TUI for watching a run.** A scrolling stream is the wrong shape for a DAG: it cannot
  show a step updating in place, a fan-out's item grid, or logs beside structure. Wanted: a
  Textual app over `dirigent-client` -- the run's graph with live per-step state, items,
  attempts, and a log pane -- reachable as `dg runs show --tui`. It is pure
  Python on the SDK with no frontend build, and the run screen the web UI ships is the
  information design to follow. A `rich.Live` in-place display for `--watch` is the smaller
  version of the same idea if the full app is too much.

- **Provisioning, in the order we are likely to want it.** `infra/` holds the compose stack
  and the Dockerfile; nothing yet installs dirigent on a machine.
  The destination is not known in advance -- a rented Ubuntu box at Hetzner or Linode, a
  system container on a box that runs other things, a VM somewhere else -- so the shape is
  "apply this service to this host", and the host is whatever the inventory names.
  - **Ansible** first, and probably the only one needed, under `infra/ansible/`. One play,
    `dirigent`, that takes any Ubuntu LTS host in the inventory to a running instance: a
    user, the Docker engine, ufw with 22 and 443 only, the compose stack as the reference
    deployment (PostgreSQL, object storage, migrate, server, worker, scheduler), the `.env`
    rendered at play time from a secret store and never committed, a reverse proxy
    holding TLS on 443 with its own certificate renewal, nightly `pg_dump` to a second bucket,
    and `dg system health` as the last task. An `upgrade` play pulls, runs `migrate`, restarts
    the server and then the workers, which already drain on SIGTERM. A `worker` play puts only
    the worker and its docker sidecar on a second host, pointed at the first host's PostgreSQL
    and bucket over a private network, which is why object storage is always on the stack.
    Creating the machine is a separate, optional play per provider (`hetzner.hcloud`,
    `linode.cloud`) that ends by adding the host to the inventory; the `dirigent` play never
    knows which provider it is on.
  - **Incus and LXD** are hosts, not a second tool: the same play targets a system container.
    Incus runs nested Docker fine (`security.nesting`), so the container is just another host.
    LXD has recurring network trouble under nested Docker, so on LXD the play should offer the
    no-Docker shape instead: the wheel installed with `uv`, the processes under systemd units,
    PostgreSQL and object storage as sibling containers. That shape loses the `docker.*`
    blocks, and the play says so and sets `enabled_unsafe_blocks` accordingly.
  - **It needs a lot of testing, and the testing is the larger half.** A play is proven only
    on a host that did not exist a minute earlier. The fast lane is a local Incus container:
    launch an Ubuntu LTS image, run the play, `dg system health`, run a handful of examples
    through the instance, run the play a second time and require zero changes, run the
    `upgrade` play from the previous tagged release to the current one, destroy the container;
    that is `make provision-test` and it runs before the play's PR merges. The slow lane is
    the same script against a throwaway box created by the provider play and destroyed at the
    end, run by hand before a release. Each host shape (VM with Docker, Incus with nested
    Docker, LXD without Docker) is its own lane, because the failure modes are different, and
    the LXD lane is the one expected to be red first.
  - **Terraform** only if machines start being created rather than handed to us and the
    provider collections stop being enough.
  - **Kubernetes** last, and preferably never: the engine has no need of it -- coordination is
    PostgreSQL, workers are stateless and scale by running more -- so a chart would exist to
    satisfy someone else's platform rather than to solve a problem we have. If it becomes
    unavoidable it belongs under `infra/chart/`, and the compose stack stays the reference.

- **A better logo.** The current mark and banner are placeholders generated early. Rounded
  corners at least, or a different mark entirely; whatever it becomes, it needs the square
  favicon, the README banner, and a dark-background variant, and `docs/assets/logo.png` and
  `banner.png` keep their names so nothing needs rewiring. It may fold into the UI redesign.

- **Reusable step groups.** Blocks are the unit below a pipeline and `pipeline.run` composes
  above it, but a repeated five-step idiom has nowhere to live except duplication or its own
  pipeline. Wanted: a named group of steps a document can include with parameters, without
  becoming a macro language.

- **A service layer, the servicekit way.** An endpoint still reads and renders every row
  itself: the same lookup-or-404 helper and the same `render` repeated resource after
  resource. Servicekit spent its convention time here and the shape holds: a generic
  repository (data access), a manager carrying the business logic with In-to-Out conversion
  and lifecycle hooks, and a CRUD router built from the pair. Wanted for the plain CRUD
  resources -- users, connections, schedules, alert rules -- and it has to answer
  what servicekit did not have to: per-route principals (`AdminDep` beside `PrincipalDep`),
  named `operation_id`s, and the `$verb` actions that sit beside the CRUD, which a generic
  router must carry rather than fight. Runs, apply, and the streams stay hand-written: they
  are the product, not plumbing.

- **Stored pipeline layout, as research.** The canvas auto-flows a DAG with elk and a reader
  can now drag nodes, but what they drag lives in their browser alone: the pipeline itself
  stores no positions, so a layout carefully arranged on one machine is unknown to the next.
  Whether it should is genuinely open -- a stored layout is one more thing an apply must
  reconcile, positions in the document dirty every diff with pixel noise, and elk plus a
  local override may simply be enough. Research, not a commitment: where positions would
  live if anywhere (document metadata, a sidecar the server stores per pipeline, or nowhere),
  who wins when the document changes shape under a stored layout, and whether better flow
  algorithms close the gap without storing anything.

## Blocks wanted

Block families we expect to want. Each is a package that ships on its own, and none
requires touching the engine. None is near-term.

- **A transform family.** The groundwork is done: four verb frames in
  `dirigent_plugin.transforms` -- `transform`, `map`, `filter`, `convert` -- with the promise
  each one makes enforced by its frame rather than trusted to an engine, and four engines
  shipping on them (`transform.jq`, `map.jq`, `filter.jq`, `convert.std`). Everything below
  is a new *kind* on machinery that exists, which means a package and no core change.
  `docs/transforms.md` is the page, and `examples/transform/` holds the worked documents.
  What is left is the tabular half the in-memory engines deliberately do not reach, still an
  open design, so these are the thoughts so far rather than a decision.

  Split it into families that ship separately, so no part waits on the rest:
  - **Codecs.** More formats on `convert`, each a pair the engine declares and the frame
    refuses where it is not supported, so a new one touches nothing else. A codec that costs
    nothing but the standard library joins `convert.std` in `dirigent-block-base`; one with a
    dependency of its own is a package named for the format it brings,
    `dirigent-block-<format>`, so an instance pays for the formats it reads.
  - **Other engines for the verbs that exist.** A `js` kind on bun and a docker-backed kind
    are the obvious two. An engine is a package named for the engine it brings,
    `dirigent-block-<engine>` -- `-js` on bun, `-docker` -- contributing its
    `transform.<kind>`, `map.<kind>` and `filter.<kind>` blocks through `contribute()`, so a
    worker installs the engines it runs and carries neither the others' dependencies nor
    their blocks in its catalog. One that evaluates programs out of process speaks the runner
    protocol in `docs/transforms.md` rather than inventing a second one. An engine that runs
    a language runtime sets `local_execution` and goes behind `enabled_unsafe_blocks` like
    `shell.run`, and a docker one rides the docker gating. A typed `filter.predicates` is one
    possible kind among peers, not the design.
  - **A runtime block.** `bun.run` or similar, executing a script directly on the worker.
    Markedly faster than a container for small work, which matters when a transform sits
    between two steps, and it wants the same allowlist gate as `shell.run`. Both this and
    `docker.run` are wanted: the container gives isolation and any language, the direct
    runtime gives speed.
  The boundary to keep: in-memory transforms are for records you can hold -- API payloads,
  a few thousand rows -- not a data-engineering framework. Past that line the answer is SQL
  over files or a container, and saying so early avoids a half-built pandas.

- **The datastores we actually use, as engines of the `sql.*` family.** ClickHouse first,
  Apache Doris after it, `dirigent-block-clickhouse` and `dirigent-block-doris`, each on the
  engine contract -- the backend it claims, what a valid connection to it is, how a parameter
  is bound and a session made read-only -- so a document written against SQLite or DuckDB
  moves to a warehouse by changing the connection. Where an engine has a bulk path the family
  lacks, such as ClickHouse's insert of a parquet artifact, that is one more verb on the same
  blocks. None of this is near-term.
