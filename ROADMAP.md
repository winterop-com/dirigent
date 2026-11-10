# Roadmap

What is left to do. The design specification is [docs/design.md](docs/design.md); what
already works is documented in [docs/](docs/index.md).

## Next up

Ordered. Each is one working chunk. Working rules for any session picking these up: read
CLAUDE.md first, commit with conventional messages, every change ships with its test,
`make check` and `make test-postgres` stay green, coverage stays at or above 90,
`mkdocs build --strict` stays clean, and every example stays executable.

1. **Move the frontend onto sokkel-ui.** [sokkel-ui](https://github.com/winterop-com/sokkel-ui)
   is the shared UI library for dirigent, stabbur, Maneki and the dhis2w-fhir UI:
   `@winterop-com/sokkel-ui` and its charts, graph, maps, media and terminal packages. The
   frontend still draws its own: 20 shadcn primitives in `src/components/ui`, `src/components/ds`
   with the `/design` gallery, and the screens built on them. One pattern per PR, every PR pinned
   to the same published library version, and no release cut per PR. Each its own slice:
   - **Install and theme.** The packages are public on GitHub Packages, which asks for a token
     even to read: `GITHUB_TOKEN` with `packages: read` in CI, passed as a build secret to the
     image build `release.yaml` runs, and `gh auth token` on a checkout. The library sets in IBM
     Plex Sans and Plex Mono where dirigent's code face is JetBrains Mono, and has no `dirigent`
     theme; the theme settles both, then the conventions say so.
   - **Primitives, then patterns, then screens.** Swap `components/ui` for the library's, then
     the shapes `components/ds` holds, then each screen: listings onto its tables, forms onto
     its schema form, run and pipeline graphs onto `sokkel-ui-graph`. Every screen it touches gets the `ui-review` pass in both palettes.
   - **Only dirigent's stays here.** `components/ds`, the `/design` gallery and
     `scripts/check_ui_system.py` go once nothing uses them; `docs/ui-conventions.md` keeps the
     conventions about dirigent's own data and points at sokkel-ui for the rest.
   - **A part the library lacks is built in sokkel-ui**, released there, and then used here,
     never drawn in this frontend first.
2. **What the security reviews left open.** Each its own slice:
   - **The units the reviews never reached.** Step deadline arithmetic, gate expansion and the
     lease sweep, retention sweeps, alert queueing, storage blocks across runs, tokens refused by
     header on step paths, and connection fields a reference chooses. In the packs: the
     `analytics_run` probe and retry logic, what the shipped schema gates admit, and a job's end
     of life.
   - **Leads that need a real service to settle.** Which of a data value set's own `dryRun` and
     `strategy` and the step's query DHIS2 obeys, which decides whether a document's body can turn
     a dry run into a write; and a broker message stalling polled sources on PostgreSQL.
3. **dirigent-fhir: what the FHIR pack still lacks.** The pack is published with its own
   [docs site](https://winterop-com.github.io/dirigent-fhir/); what it does not do yet, each its
   own slice:
   - **CQL and measures.** Libraries from storage or as ELM, one patient's compartment as the
     data, terminology for `in`/`memberOf` from a value set carried in the step or a remote FHIR
     terminology server, continuous-variable measures and stratifiers, and a MeasureReport pushed
     through `dirigent-dhis2` into DHIS2 as aggregate data values.
   - **Profiles, IG packages and bindings.** `fhir.validate` is structural, and a profile is
     checked only by the engine's `conformsTo()`, which reads `meta.profile`. Left: a profile
     resolved from a pinned package (`name#version` from the FHIR package registry), a package
     cache, and terminology for bindings. Where generic IG package loading lives is decided then.
   - **A reply for FHIR in.** `fhir-to-dhis2` and `dirigent-integration`'s
     `fhir-subscription-to-dhis2` take `application/fhir+json` at an endpoint, shape it and import
     it, and neither answers its caller with a reply.
   - **The read side** (`/metadata`, reads, searches, history) served by facade routers
     mounted inside the dirigent server, picking only the routers wanted. This needs a routes
     contribution surface, the open question "A server in the mix" below.
   - **What the engine leaves to dhis2w-fhir.** The published `dhis2w-fhir-engine` (1.38.3)
     still requires `dhis2w-client` and `fastapi`, so installing the pack installs them. Reported
     to dhis2w-fhir rather than changed: `MeasureEvaluator.evaluate_population` counts each
     population independently, so a numerator that does not repeat the denominator's criterion
     is overcounted (the pack nests them itself), and its `to_fhir()` omits `period` and the
     population code system; FHIRPath's `1 + 1` answers a Decimal rather than an Integer, and an
     undefined `%name` evaluates to nothing rather than an error; and the R4 models name a subset
     of each resource's elements and are closed, so they cannot validate a resource whole.
4. **`dirigent-full-demo`: one instance with everything, for the tutorials.** `everything` in
   `dirigent-examples` is most of it: one instance with the corpus and the tutorial pipelines
   applied, S3, Kafka, RabbitMQ and a PostgreSQL warehouse in its compose stack, an alert sink,
   the play demo connected, and a `verify.sh` that brings it up and asserts green. Left:
   - `dirigent-contrib`, `dirigent-fhir` and `dirigent-integration`'s shelves as dependencies,
     with their examples applied;
   - the telemetry sink, the OTLP collector of `infra/compose.otel.yaml`, in its stack;
   - a gate in its verify that checks the play demo is healthy before the corpus runs.
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
8. **Another UI and design round.** The owner still sees issues across the screens after the
   0.32 and 0.33 changes. Two independent passes over the live UI, one by Codex and one by Claude
   Design, each against `docs/ui-conventions.md` in both palettes and at phone width, each ending in
   a list of findings with screenshots and a proposed design for what the conventions do not yet
   answer. The owner picks between them where they differ; what is chosen changes the conventions
   first, then the code, and every screen it touches gets the `ui-review` pass. The queued items
   from earlier rounds go into the same pass: graph sizing, the active highlight, a live jq
   preview, and the run's pause buttons.
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
  `requires`, and no packs. The screen filters by contributing plugin and marks each
  requirement met or not; it still wants a "runnable here" filter (every requirement
  installed), and `dg init` offering the shelves as a choice.

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
  `banner.png` keep their names so nothing needs rewiring.

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

- **More of the transform family.** The verb frames and the engines on them are
  [docs/transforms.md](docs/transforms.md); everything below is a new *kind* on that machinery,
  which means a package and no core change. What is left is the tabular half the in-memory
  engines do not reach, still an open design, so these are the thoughts so far rather than a
  decision.

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
