# Dirigent architecture model

A C4 model of Dirigent, written as code in [`workspace.dsl`](workspace.dsl) (Structurizr DSL).
It is aimed at the people who run, deploy and extend an instance rather than at people reading
the source; what each package is for, and what may depend on what, is
[`docs/architecture.md`](../docs/architecture.md).

The model is the single source of truth for the diagrams. Edit `workspace.dsl` and the views
regenerate; there are no hand-drawn images to keep in sync.

## The levels

Open them in this order:

1. **L1 - System landscape** (`L1_Landscape`) - the people, Dirigent, the packs in their own
   repositories (`dirigent-dhis2`, and `dirigent-chap` and `dirigent-climate` in
   `dirigent-contrib`), and the outside systems the packs and the built-in blocks reach.
2. **L2 - Containers** (`L2_Dirigent`) - the web UI, the API server, the scheduler, the
   workers, the database, artifact storage, the `dg` CLI and `dirigent-mcp`, and how they talk.
3. **L3 - Components**:
   - `L3_Server` - the API server: routes, auth, event streams, the endpoint intake, the reply
     waiter, and the UI host.
   - `L3_Worker` - the engine and the worker: wake-ups, claim, executor, readiness and run
     status, run creation, recovery and deadline sweeps, polled and held sources, the alert
     dispatcher, the plugin host and the block contract.
4. **Flows** - dynamic views for three journeys:
   - `Flow_AdHocRun` - an ad hoc run of an async block: API, run rows, claim, submit, probe,
     settle.
   - `Flow_EndpointReply` - an endpoint source with a reply: the caller is held, the run
     runs, the reply renders, the caller is answered.
   - `Flow_PolledSource` - a polled storage source: lease, poll, one run per new object,
     cursor.
5. **Deployment**:
   - `Deploy_Compose` - the Docker Compose layout from `infra/compose.yaml`: `postgres`, `s3`,
     the one-shot `migrate`, `server` with the scheduler embedded, `worker`, and the worker's
     own `docker` daemon.
   - `Deploy_Dev` - `dg dev`: one process, SQLite and a `file://` root under
     `.dirigent/state`.

## The parts

| Part | What it is | Key point for operators |
| --- | --- | --- |
| **API server** | `dg server`, FastAPI. | The REST API, the UI bundle, SSE streams and endpoint sources. An endpoint call only checks, records and enqueues; nothing else runs in the request path. |
| **Scheduler** | `dg scheduler`, or embedded in `dg server`. | Leadership is a PostgreSQL advisory lock, so a second scheduler blocks rather than double-fires. Firing a schedule and advancing it commit together. |
| **Worker** | `dg worker`, one or more. | One claim query with `FOR UPDATE SKIP LOCKED`; no dispatcher. Routed by `--tag` against a document's `requires.workers`. Its only inbound dependency is the database. |
| **Database** | PostgreSQL 17; SQLite under `dg dev`. | All coordination. Definitions are JSONB documents, execution state is indexed rows, and `pg_notify` on `dirigent_work`, `dirigent_settled` and `dirigent_sources` wakes waiters sooner than their poll. |
| **Artifact storage** | A `file://` root, or an `s3://` bucket through `dirigent-storage-s3`. | Every worker must reach it: outputs are passed by URI, never by a worker-local path. |
| **Packs** | Python packages discovered through the `dirigent.plugins.v1` entry point. | They run in-process in the worker; installing one is the whole registration. The core never names an external product. |

A few facts the diagrams encode:

- A wake-up is only a hint. Every waiter still reads the database on its own interval, so a
  lost notification costs the poll it replaced.
- A reply is rendered by whichever process settles its last prerequisite, inside the outcome
  transaction, and is answered by the server holding the caller.
- A polled source is leased and committed before its poll does any I/O, and the runs and the
  cursor are written together afterwards, so an input is never skipped.

## Reading the diagrams

In the interactive viewer (`make architecture`) and its PNG export, shape, colour and logo carry
meaning: a cylinder is a datastore, a person shape is a role, packs are green, outside systems
grey, and the PostgreSQL, FastAPI and React logos are fetched from a CDN at render time.

The [docs page](../docs/architecture-model.md) carries fewer of these cues. Cylinders survive,
but colours, person shapes and logos do not, so the diagrams follow the site's light and dark
palettes. Every box is labelled with its type (`[Person]`, `[Software System]`,
`[Container: ...]`, `[Component]`) instead.

## Viewing and editing

From the repository root:

```bash
make architecture            # serves http://localhost:6080
make architecture-validate   # validates workspace.dsl
```

Edit `workspace.dsl` and refresh the browser to see the change.

## Exporting PNGs

```bash
make architecture-export     # needs port 6080 free
```

This renders every view to `architecture/diagrams/<ViewKey>.png`, which is gitignored and never
committed. The target starts a temporary Structurizr instance, drives a headless browser over
each view through Structurizr's diagram scripting API ([`export-diagrams.js`](export-diagrams.js),
run inside the Playwright image), and tears the instance down. The `structurizr/structurizr`
image cannot export images itself.

Visiting every view also fills Structurizr's thumbnail cache under `.structurizr/`, so the
viewer's diagram finder shows thumbnails at once afterwards.

## Publishing into the docs site

```bash
make architecture-export-docs   # -> docs/architecture-model.md
make architecture-check-docs    # fails when that page is stale
```

The first exports every view to Mermaid and rewrites it into native, theme-aware Mermaid with
[`mermaid_to_docs.py`](mermaid_to_docs.py); MkDocs renders it through `pymdownx.superfences`, so
the site build needs no Docker. That page is the committed rendering of the model: regenerate
and commit it whenever `workspace.dsl` changes. CI runs `make architecture-check-docs` on every
pull request, and the export is byte-reproducible, so a diff there means the page is stale.

## Renderer versions

The Structurizr and Playwright images are pinned in the `Makefile` (`STRUCTURIZR_IMAGE`,
`PLAYWRIGHT_IMAGE`). Bump one deliberately and re-export in the same commit. The retired
`structurizr/lite` and `structurizr/cli` images only print a migration notice.

The targets pass `--user` with the host's uid and gid: on Linux the image's own user cannot write
the bind-mounted `architecture/` directory.

## Cleaning up

```bash
make architecture-clean
```

removes `diagrams/`, `exports/`, `node_modules/`, `.structurizr/` and `workspace.json`, all of
which regenerate from `workspace.dsl`.
