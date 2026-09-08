# Claude Code Instructions

## Git Commits

- Use conventional commits format (feat:, fix:, docs:, chore:, refactor:, etc.)
- No attribution or co-authored-by lines
- Keep commit messages concise and descriptive
- Do all work on a dedicated branch, and link every working branch to a pull request.
- Open every pull request as a draft; mark it ready only when explicitly asked.

## Sibling repositories

- `dirigent-dhis2` (a pack) and `dirigent-integration` (the control center that assembles every
  pack and runs everyone's tests) live in their own repositories beside this one, and both
  install this repository's packages from git at `main`.
- A change here that touches a contract they consume is not done until it is reflected there:
  the plugin and testing API, the wire schemas, the CLI's flags and record kinds, a block id or
  connection kind, and the version number. Grep both checkouts before closing the change.
- A release here is a release there. `dirigent-dhis2` relocks its dirigent packages at the
  tagged commit and moves to the same version; `dirigent-integration` moves to the same version
  and its `make test` is run against the new tips before the release is called done. Its lock
  is never committed; it resolves `main` fresh. Each of the three then gets the same `vX.Y.Z`
  tag and a GitHub release; here the tag is what publishes the packages to PyPI and the image
  to ghcr, through `.github/workflows/release.yaml`.
- A pack that is installed into the image declares every dependency it needs in `dependencies`,
  never only in `tool.uv.sources`.
- Run their gates with `env -u VIRTUAL_ENV`, or uv may resync this repository's venv against
  theirs.

## Compatibility

- Before 1.0, contracts change directly: do not add compatibility aliases, migrations,
  fallbacks, deprecation paths, or dual-read support unless explicitly asked.

## Dependencies

- `pluginkit` is _the_ framework for any kind of plugin. A new extension point -- blocks,
  connection kinds, storage backends, notifiers, format checkers, anything discovered and
  contributed -- is built on pluginkit, not on a hand-rolled registry, entry-point scan, or
  bespoke discovery. `dirigent-plugin` wraps it; extend that.

## Style

- No emojis ever in any output or files

## Naming

- A discriminator we own is `kind`, never `type`: record kinds, block kinds, connection
  kinds. Keep `type` only where an external standard or the language fixes the term, such as
  JSON Schema, MIME content types, SQLAlchemy column types, and Python's `type()`.
- Every addressable thing carries the same four fields, and each one has a single job.
  `id` is the uuid a machine holds. `code` is the addressable key: constrained, unique, and
  what appears in a URL, a document, and every reference. `name` is an optional human title,
  free-form and with no identity semantics at all -- nothing may ever be referenced by it,
  and two rows may share one. `description` is long-form and markdown-capable.
- A screen renders that quartet one way, everywhere: the title is the `name` if there is one
  and the `code` otherwise, the `code` is always on screen in mono and never drawn twice, and
  the `description` is the body. `username` is a user's code, and a step's map key is its own.
- `models` means database/ORM classes. Only SQLAlchemy models live in `models.py`.
- `schemas` means pydantic types that cross a boundary: request, response, wire, and
  configuration shapes. They go in `schemas.py` or a `schemas/` package, and the package
  that owns a boundary owns its schemas -- the server imports its wire types from the
  client rather than defining its own.
- A pydantic type used by one module only is not a schema. It stays with the code that
  uses it, because pydantic here is standing in for dataclasses. A block's config and
  output models stay with the block, where a plugin author expects them.
- A wire schema is named for what it carries. An entity's request and response shapes are
  `<Name>In` and `<Name>Out`, a PATCH body is `<Name>Update`, and the superset a single read
  answers with is `<Name>Detail`. An action's body is `<Verb>Request`, and its answer is
  named for what it is: `ApplyResult`, `RunAccepted`. Enums, nested components and singleton
  reads carry no suffix.
- A measured timing in emitted data is `duration_ms`, an integer of milliseconds.
- A configured duration is a humane `Duration` value, not a number of seconds.
- A measured size in emitted data is `<thing>_bytes`, an integer of bytes.
- A configured size is a humane `Size` value, and carries no `_bytes` suffix: the type says
  the unit, and the value may be written `16KB`.
- A pack is named `dirigent-<system or format>` (`dirigent-dhis2`, `dirigent-parquet`,
  `dirigent-storage-s3`) and a runtime package `dirigent-<role>` (`core`, `server`, `cli`,
  `client`, `common`, `plugin`, `testing`). `dirigent-blocks` is the built-in pack.
- YAML files we own end in `.yaml`, never `.yml`. A file a tool insists on naming for us,
  such as `mkdocs.yml`, keeps the name that tool expects.

## Output

- Every command writes NDJSON to stdout by default: one record per line, no banner, no
  table, no colour. That is `dg run` and `dg runs` as much as `dg dev`, `dg server`,
  `dg worker` and `dg scheduler`. A person reads any of them by piping through
  `dg format`, and `-o console` is how one invocation asks for the rendering instead.
- `dg init` is the exception, because it is run once by a person setting a machine up and
  never in a pipe: it renders unless records were asked for.
- Every record carries a `kind`, which is what a formatter dispatches on and what `jq`
  selects by. A formatter renders an unrecognised kind rather than failing.
- A record carries what its rendering needs, so no renderer reads the run a second time.
  A table is a rendering of a record, keyed by its `kind`, and it lives in the formatter --
  never in the command that emitted it.
- An agent's shell is never a terminal, so colour, width and anything behind `isatty()`
  differ there from a person's terminal. `FORCE_COLOR=1 uv run pytest` makes that
  difference visible without one.
- A test asserts on records, never on rendered text. Rendering depends on the terminal;
  records do not. The few tests covering a formatter call it directly, with colour set
  explicitly rather than taken from the environment.

## UI work

- `docs/ui-conventions.md` is the design system and it is binding: every UI change is built
  to it, and reviewed against it with the `ui-review` skill (live browser, changed screens,
  both palettes) before its PR merges. A convention that proves wrong is changed in that file
  first, then in the code.
- The frontend e2e suite and the dev server serve `frontend/dist`: run `bun run build` before
  any e2e run or live review, or you are testing a stale bundle.

## Git hygiene

- Never `git add -A`. Stage named paths. The automated browser writes `.playwright-mcp/` into
  the repo root during sessions and screenshots stray easily; check `git status` before every
  commit that follows a browser session.

## Comments

- Say what the thing does, or the constraint the code cannot show. Nothing else.
- Delete any sentence that still reads sensibly prefixed with "we chose this because".
  Rationale belongs in a commit message or the roadmap, never in a file.
- No history, no pointing at other files, no restating the code in prose.
- Examples are the exception: they teach, so a step may say why it is configured as it is.
