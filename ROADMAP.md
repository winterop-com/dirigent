# Roadmap

What is left to do. The design specification is [docs/design.md](docs/design.md); what
already works is documented in [docs/](docs/index.md).

## The CLI output work

**Decided, and it supersedes anything below that says otherwise: a command emits NDJSON and
nothing else unless it is asked for a rendering.** `dg dev`, `dg server`, `dg worker` and `dg scheduler` write structured
records to stdout at every verbosity, with no banner, no `ready` line, no table, no colour
and no rendering to choose between. Everything the banner used to say is a field on a
`process` record. Reading them is `dg dev | dg format`, which is the same answer for
a container's logs, a file from last week, or a colleague's paste. The process then has one
encoder and no branching on who might be watching, and the formatter is the only place that
knows how a line should look.

Commands write it too. `dg run`, `dg runs`, `dg pipeline` and the rest emit records, and
`-o console` is how one invocation asks for the rendering instead -- which is the same
rendering `dg format` gives the pipe.

### Settled

Decisions that still constrain the code. What each one replaced is in the commit that made
it; what it forbids is here, because that is what somebody is liable to undo.

- **Every command writes NDJSON, and `dg init` is the only exception.** A command emits
  records unless `-o console` or `DIRIGENT_LOG_FORMAT` asks for the rendering. `dg init` is
  run once by a person setting a machine up and renders unless asked for records.
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
- **There is one migration.** Nothing has shipped, so the history has no consumer, and an
  amendment is where an ALTER behaves differently from the CREATE that would say the same
  thing. What proves the baseline faithful is the two drift tests, on SQLite and PostgreSQL.
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

### Decided, not yet built

Take these in order; each is a chunk on its own.

- **Two images, two audiences.** The core image built here stays slim: the workspace, the
  web UI, the docker CLI, and no adapter pack. `dirigent-integration` ships the
  batteries-included image, `dirigent-full`, built from its manifest and lock with every
  official pack, which is the only assembly whose git sources resolve before PyPI. What is
  left here is the hook on the core image: a build argument naming extra distributions,
  installed into the venv after the workspace sync, so a deployment adds two packs to the
  stock image without a second repository. It lands with 1.0, because a pack installed by
  name resolves only once the packages are on PyPI. `dg init --with <pack>` is the same
  convenience for a project on a machine, and lands after.


## Next up

Ordered. Each is one working chunk. Working rules for any session picking these up: read
CLAUDE.md first, commit signed with conventional messages, every change ships with its test,
`make check` and
`make test-postgres` stay green, coverage stays at or above 90, `mkdocs build --strict`
stays clean, and every example stays executable.

1. **M4 adapter packs.** The first adapter pack has moved out to its own repository, owning
   its blocks, examples and tests and self-testing against `dirigent-plugin`'s main;
   `dirigent-integration` assembles the whole set and proves it composes. Every further pack
   takes the same shape: its own repository, its own examples, wired through a connection
   kind, with a client written fresh or wrapping a stable one. Still open for the program:
   generalising `dirigent-integration`'s dev-dep filter beyond one pack's client prefix.
2. **M5 hardening.** Log batching under load.
3. **Post-M5.** Split dirigent-blocks into family packages (dirigent-block-http,
   dirigent-block-storage, ...) under an umbrella. Invisible to stored pipelines, because
   documents bind to block ids rather than packages.

## Open questions

- **Whether `dg health` belongs under `dg system`.** `dg system info` asks a server over the
  API; `dg health` probes the local process without a token. Two planes, which is why they
  are two commands -- but one place to look is worth something. Either fold health into
  `dg system` and let it dispatch on whether a server was named, or keep them apart and make
  each say in its help what the other is for.

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

## Wanted

- **Restoring both halves of the state.** The database is the system of record, but artifact
  bytes are not in it, so a restore from `pg_dump` alone leaves artifact references pointing
  at objects that are gone. The backup section says the database is complete "except artifact
  bytes"; that caveat deserves a procedure. Wanted: what to back up for each storage backend,
  a restore sequence covering both halves, and what to expect when they disagree -- a run
  whose artifacts are missing should fail readably rather than confusingly.
- **Importance, which is not urgency.** A pipeline can matter enormously and still be content
  to run at three in the morning behind everything else. Priority answers when work is
  claimed; nothing today says how much a pipeline MATTERS, and the two must not be the same
  number -- otherwise a critical nightly job either takes slots it does not need, or its
  failure is as quiet as a scratch pipeline's. Wanted: a declared importance on the pipeline,
  independent of priority, that the rest of the system reads -- alert rules matching on it so
  a critical failure pages while a routine one logs, the stuck-run detector treating it as an
  incident sooner, a dashboard and the future run list ordering by it, and retention keeping
  its history longest. Start with the field and the alert-rule match; the rest can follow it.

- **What an artifact is.** Today an artifact is exactly one thing: a step's structured
  output, kept inline when small and written to `outputs/<attempt-id>.json` when not, with a
  digest, a size, and links to run, attempt and step. The files a block actually writes are
  not artifacts: `http.request --save_to`, `shell.run`'s captured streams and
  `storage.copy`'s target are storage URIs mentioned inside an output, with no row of their
  own. So the thing a person most wants -- the fetched payload, the command's stdout -- is
  untracked, while the small JSON that merely names it is tracked. Three consequences:
  `dg artifact` has no subcommands, so nothing can be listed or downloaded; retention cannot
  clean up files it holds no reference to; and a run cannot answer what it produced.
  Which way to close it is genuinely open. Either a block DECLARES a URI as an output and the
  engine tracks, lists, retains and serves it -- which makes downloads, retention and the
  future run view work from one concept -- or artifacts stay strictly the step's return value
  and files remain incidental, which is simpler and leaves the gap. Decide it against a real
  pipeline rather than in advance, and revisit if the answer turns out to be that everything
  lives in object storage anyway, where a URI and a bucket policy may be all the tracking
  anyone needs.

- **A portable way to address durable storage.** A document's only storage anchor is
  `${run.scratch}`, which is run-scoped and swept by retention. Writing something meant to
  outlive its run has no portable form: `file://kept/x.json` puts `kept` in the URI's host
  position and `file:///kept/x.json` is absolute, and both resolve outside the artifact root
  and are refused. Only an absolute path naming the instance's own root works, which a
  portable document cannot contain. Wanted: a root-relative reference (`${artifacts}/...`, or
  a documented root-relative URI form) so "fetch it and keep it" is expressible. Until then
  the answer is an `s3://` URI through the connection the compose stack already bootstraps.

- **A TUI for watching a run.** A scrolling stream is the wrong shape for a DAG: it cannot
  show a step updating in place, a fan-out's item grid, or logs beside structure. Wanted: a
  Textual app over `dirigent-client` -- the run's graph with live per-step state, items,
  attempts, and a log pane -- reachable as `dg watch` or `dg runs show --tui`. It is pure
  Python on the SDK with no frontend build, and the run screen the web UI ships is the
  information design to follow. A `rich.Live` in-place display for `--watch` is the smaller
  version of the same idea if the full app is too much.

- **Provisioning, in the order we are likely to want it.** `infra/` holds the compose stack
  and the Dockerfile; nothing yet installs dirigent on a machine. Started thinking 2026-09-07.
  The destination is not known in advance -- a rented Ubuntu box at Hetzner or Linode, a
  system container on a box that runs other things, a VM somewhere else -- so the shape is
  "apply this service to this host", and the host is whatever the inventory names.
  - **Ansible** first, and probably the only one needed, under `infra/ansible/`. One play,
    `dirigent`, that takes any Ubuntu LTS host in the inventory to a running instance: a
    user, the Docker engine, ufw with 22 and 443 only, the compose stack as the reference
    deployment (PostgreSQL, object storage, migrate, server, worker, scheduler), the `.env`
    rendered at play time from a secret store and never committed, a reverse proxy
    holding TLS on 443 with its own certificate renewal, nightly `pg_dump` to a second bucket,
    and `dg health` as the last task. An `upgrade` play pulls, runs `migrate`, restarts the
    server and then the workers, which already drain on SIGTERM. A `worker` play puts only the
    worker and its docker sidecar on a second host, pointed at the first host's PostgreSQL and
    bucket over a private network, which is why object storage is always on the stack.
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
    launch an Ubuntu LTS image, run the play, `dg health`, run a handful of examples through the
    instance, run the play a second time and require zero changes, run the `upgrade` play from
    the previous tagged release to the current one, destroy the container; that is `make
    provision-test` and it runs before the play's PR merges. The slow lane is the same script
    against a throwaway box created by the provider play and destroyed at the end, run by hand
    before a release. Each host shape (VM with Docker, Incus with nested Docker, LXD without
    Docker) is its own lane, because the failure modes are different, and the LXD lane is the
    one expected to be red first.
  - **Terraform** only if machines start being created rather than handed to us and the
    provider collections stop being enough.
  - **Kubernetes** last, and preferably never: the engine has no need of it -- coordination is
    PostgreSQL, workers are stateless and scale by running more -- so a chart would exist to
    satisfy someone else's platform rather than to solve a problem we have. If it becomes
    unavoidable it belongs under `infra/chart/`, and the compose stack stays the reference.

- **The ASGI server is a choice, not a fixture.** `dg server` calls `uvicorn.run()` on an
  app factory, and uvicorn stays the default for simplicity. Nothing in the code depends on
  it though: the application is plain ASGI, so granian, hypercorn or whatever Rust-backed
  server is worth having by then already work today by pointing at the factory. Two things
  to tidy when this is revisited: uvicorn is a dependency of `dirigent-server`, which only
  DEFINES the app and never runs one, so the dependency belongs in the CLI alone and an
  embedder should not inherit a server choice; and the docs should name the factory so
  running under something else is documented rather than discovered.
  Note what NOT to reach for: gunicorn's prefork model buys nothing here, because capacity
  comes from running more dirigent workers claiming from PostgreSQL, not more web processes.
  More API processes only multiply connection pools against one database; more API capacity
  means more `dg server` containers behind a load balancer.

- **A better logo.** The current mark and banner are placeholders generated early. Rounded
  corners at least, or a different mark entirely; whatever it becomes, it needs the square
  favicon, the README banner, and a dark-background variant, and `docs/assets/logo.png` and
  `banner.png` keep their names so nothing needs rewiring.

- **Markdown reports from templates.** These are one feature. A run's report is currently a
  stub, and an alert rule's message template only interpolates `${run.*}`, so neither can say
  much. Wanted: render text from a Jinja2 template against a run's facts -- its steps, items,
  attempts, outputs and timings -- producing markdown that is stored as an artifact, shown in
  the run view, and usable as an alert body. A `report.render` block would let a pipeline
  emit its own summary as a step, the way the Prefect flows emitted a markdown artifact in a
  `finally` block, which was the operator's real feedback channel.
  The run's own report is engine-owned rather than a step, because a step cannot run when a
  run is cancelled or a worker dies, and those are the cases where a report matters most; the
  engine already holds every fact one needs, and a pipeline names a template rather than
  carrying reporting boilerplate. `report.render` as a block stays useful for a different
  job: a summary of the WORK, mid-pipeline, that a later step sends somewhere.
  The boundary matters: templating renders TEXT and never resolves step config. Config stays
  references-only, deliberately, so a document cannot grow an expression language through a
  side door -- a template is a safe place for loops and conditionals precisely because its
  output is a document a person reads, not a decision the engine acts on. Sandbox it
  accordingly, since a template becomes something a pipeline author can write and an operator
  runs.

- **Reusable step groups.** Blocks are the unit below a pipeline and `pipeline.run` composes
  above it, but a repeated five-step idiom has nowhere to live except duplication or its own
  pipeline. Wanted: a named group of steps a document can include with parameters, without
  becoming a macro language.

- **What a document will cost before it runs.** A document can be checked for whether it is
  valid, never for what it will cost. Wanted: a `dg validate --explain` that reports the shape
  of the work ahead -- the fan-out cardinalities, the deadlines and poll cadences, the retry
  budgets -- before anything executes.

- **A service layer, the servicekit way.** Today an endpoint does everything itself: it calls
  a core function, catches each domain error it knows about, translates it to a status, and
  renders the row -- the same try/except and the same `render` repeated route after route, and
  a new refusal means touching every endpoint that can meet it. Servicekit spent its
  convention time here and the shape holds: a generic repository (data access), a manager
  carrying the business logic with In-to-Out conversion and lifecycle hooks, a CRUD router
  built from the pair, and ONE app-wide exception handler that maps the domain error
  hierarchy to problem documents, so an endpoint calls and returns and nothing else. Take it
  in two bites, because the first is cheap and pays immediately: give every domain error its
  status (the hierarchy under `AuthError` and friends already exists), register one handler
  that renders any of them as the problem document, and delete the per-endpoint try/except.
  The second bite is the manager/router layering for the plain CRUD resources -- users,
  connections, schedules, webhooks, alert rules -- and has to answer what servicekit did not
  have to: per-route principals (`AdminDep` beside `PrincipalDep`), named `operation_id`s,
  and the `$verb` actions that sit beside the CRUD, which a generic router must carry rather
  than fight. Runs, apply, and the streams stay hand-written: they are the product, not
  plumbing.

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
    refuses where it is not supported, so a new one touches nothing else.
  - **Other engines for the verbs that exist.** A `js` kind on bun and a docker-backed kind
    are the obvious two, and both are plugin packages rather than core work: an engine that
    runs a language runtime sets `local_execution` and goes behind `enabled_unsafe_blocks`
    like `shell.run`, and a docker one rides the docker gating. A typed `filter.predicates`
    is one possible kind among peers, not the design.
  - **A runtime block.** `bun.run` or similar, executing a script directly on the worker.
    Markedly faster than a container for small work, which matters when a transform sits
    between two steps, and it wants the same allowlist gate as `shell.run`. Both this and
    `docker.run` are wanted: the container gives isolation and any language, the direct
    runtime gives speed.
  The boundary to keep: in-memory transforms are for records you can hold -- API payloads,
  a few thousand rows -- not a data-engineering framework. Past that line the answer is SQL
  over files or a container, and saying so early avoids a half-built pandas.

- **FHIR, an important addition.** Likely the most common transform case in practice, and
  only partly generalisable: mapping to and from FHIR resources is regular enough to deserve
  blocks (parse, render, validate against a profile, a `fhir` connection kind for a server's
  base URL and auth, search and read and transaction bundles, and the bundle handling every
  integration rewrites) but each deployment's mapping to its own concepts is not. Wanted: the
  general half as blocks, with the specific half left to a pipeline's own transform steps. Sits
  close to the codecs above and should be designed with them. Not for now, but not far off:
  this and AI are the two additions that matter most.

- **AI, an important addition.** A pipeline step that asks
  a model: an `ai.complete` operator (a prompt, optional context from upstream outputs, a
  JSON Schema the answer must fit so the result is data a later step can read rather than
  prose), an `ai.classify` over the same shape, and an `ai.embed` for the vector datastores
  above. Providers are connection kinds, each holding its endpoint and sealed key: the OpenAI
  wire shape first since most hosted and local servers speak it, Anthropic beside it, and a
  local llama.cpp or mlx runtime as the third, which is what makes an AI step runnable in
  `dg run --local` with nothing in the cloud. Every call is recorded like an HTTP call (model, tokens, duration_ms) and the
  answer is validated against the schema before it counts. Not for now.

- **The datastores we actually use, as engines of the `sql.*` family.** ClickHouse first,
  Apache Doris after it, each an engine the `sql` connection kind accepts (a driver, a URL
  scheme, the dialect's own read-only and parameter-binding rules) rather than a family of its
  own, so a document written against SQLite or DuckDB moves to a warehouse by changing the
  connection. Where an engine has a bulk path the family lacks, such as ClickHouse's insert of
  a parquet artifact, that is one more verb on the same blocks. None of this is near-term.

## Known debt

- **The phone sheet's footer controls are 40px tall.** That is the finger target the UI
  conventions state, and the small-screen brief asked for 44px; whether the rule moves to 44
  is undecided, and if it does the conventions change first and then the one `index.css` block.

- **`fetch` is at-least-once, and no key we hold can make it exactly-once.** A worker that
  fetches a result and then dies before the outcome commits leaves the attempt waiting with
  its handle, so the next claim probes and fetches again. The `idempotency_key` the schema
  carries is no help: it de-duplicates *retries of a step within a run*, which is a person
  clicking twice, and it never leaves this instance. Exactly-once across a boundary we do not
  control is not achievable at all -- it needs the remote and our database in one transaction
  -- so what was left of the debt was a contract that claimed otherwise. `fetch` now says it
  is at-least-once, in the docstring plugin authors read and in the design spec, and
  `test_a_worker_that_dies_after_fetching_fetches_again_and_settles_once` pins the guarantee
  the engine does make: however many times a result is fetched, one attempt settles once.
  What remains is a judgement, not a defect: whether to commit the fetched payload in its own
  transaction before settling, the way a submitted handle is already committed on its own.
  That makes a repeat fetch rare rather than routine -- a replay would find the payload and
  skip straight to settling -- at the cost of one more commit per remote step and a column to
  hold it. Worth doing when a block appears whose fetch is genuinely expensive; not worth it
  for reading logs off a container or downloading a result file, which is every remote block
  we ship, and which a repeat costs almost nothing.
