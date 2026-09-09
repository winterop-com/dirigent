# Conventions

The choices this codebase makes that a reader does not expect, and why they are choices
rather than accidents. The binding rules live in `CLAUDE.md` at the repo root; this page is
the human tour of the ones worth understanding before you read much code. `docs/ui-conventions.md`
is the same thing for the web UI.

## Documentation lives with the value, and tooling reads it

Two comment notations here are not comments to the next editor -- they are data other code
reads.

A **field docstring** is a string literal on the line *after* a pydantic field:

```python
class S3StorageConfig(BlockModel):
    region: str = "us-east-1"
    """The region signed into every request."""
```

`BlockModel` sets `use_attribute_docstrings=True`, so pydantic lifts that string into the
field's JSON Schema `description`. From there the one sentence travels to the block catalog,
the generated `blocks.md` table, and the config form the UI generates -- so a block author
writes user-facing documentation once, beside the field, and every surface renders it. A
string *before* the field, or a `#` comment, is invisible to all of it. Position is the
mechanism, not taste: the field docstring comes after the field the way a function's comes
after its `def`.

A docstring is written in reStructuredText and every reader renders markdown, so the two meet
at the catalog boundary: `dirigent_common.docstrings.as_markdown` rewrites RST inline literals
as markdown inline code on every `description` in a contributed model's schema. Write code in
double backticks and it arrives as inline code everywhere.

A **constant docstring** is a comment beginning `#:` on the line before a module constant:

```python
#: How far into the container's log a probe has read.
LOGS_SINCE = "logs_since"
```

Same idea for a bare `NAME = value` where a following string would not read cleanly: `#:`
attaches documentation autodoc can pick up. A plain `#` documents nothing.

## Code comments say only what the code cannot

A comment states what a thing does, or a constraint the code cannot show -- nothing else. If
a sentence still reads sensibly with "we chose this because" in front of it, it is rationale,
and rationale belongs in the commit message or the roadmap, never in a file. No history, no
pointing at other files, no restating the next line in prose. Examples are the one exception:
they teach, so an example step may say why it is configured as it is.

## `kind`, never `type`

The discriminator dirigent owns is always `kind` -- record kinds, block kinds, connection
kinds. `type` is kept only where an external standard or the language fixes the word: JSON
Schema, MIME content types, SQLAlchemy column types, Python's `type()`.

## Every addressable thing carries the same four fields

`id`, `code`, `name`, `description`, each with one job. `id` is the uuid a machine holds
(a UUIDv7, time-ordered). `code` is the addressable key -- constrained, unique, and what a
URL, a document and every reference carry. `name` is an optional human title with no identity
semantics at all: nothing is ever referenced by it, and two rows may share one. `description`
is long-form and markdown-capable. A screen renders the quartet one way everywhere: the title
is the `name` if there is one and the `code` otherwise, the `code` is always on screen in
mono and never drawn twice, and the `description` is the body. A user's `username` is their
code; a step's map key is its own.

## A custom `format` string is how a field declares dirigent meaning

JSON Schema's `format` keyword carries strings the standard does not define, and dirigent
uses that for two jobs.

For **discovery**: a storage-URI field is typed `StorageUri`, which publishes
`format: storage-uri`. At apply, the engine finds every storage field across every block by
that marker -- without knowing any block's field names -- and checks the URI's scheme against
what the instance's backends claim, so a scheme no backend serves fails at apply rather than
at the first write.

For **assertion**: dirigent ships base formats (`ulid`, `uuid4`, `uuid7`, `md5`, `sha256`,
`base64`, ...) on top of the standard ones, so a schema writing `format: uuid7` rejects a v4.
Both are the same mechanism -- a non-standard `format` string -- pointed at discovery in one
case and value-checking in the other. See [jq](jq.md)'s companion, the JSON Schema guide, for
the format-versus-pattern rule. JSON Schema itself is targeted at Draft 2020-12 throughout.

## `models` are ORM, `schemas` cross a boundary

`models.py` holds SQLAlchemy classes and nothing else. A `schemas` module holds pydantic
types that cross a boundary -- request, response, wire, configuration shapes -- and the
package that owns a boundary owns its schemas, so the server imports its wire types from the
client rather than redefining them. A pydantic type used by one module only is not a schema:
it stays with the code that uses it, because there pydantic is standing in for a dataclass. A
block's config and output models stay with the block, where a plugin author expects them.

A wire schema is named for what it carries: `<Name>In` and `<Name>Out` for an entity's
request and response, `<Name>Update` for a PATCH body, `<Name>Detail` for the superset one
read answers with, `<Verb>Request` for an action's body, and an answer named for what it is
(`ApplyResult`, `RunAccepted`). Enums, nested components and singleton reads carry no suffix.

## A measured quantity and a configured one are spelled differently

A measured timing in emitted data is `duration_ms`, an integer of milliseconds; a measured
size is `<thing>_bytes`, an integer of bytes. A *configured* duration is a humane `Duration`
(`15m`, `48h`), and a configured size is a humane `Size` (`16KB`) -- the type says the unit,
so a configured size carries no `_bytes` suffix. The reader always knows whether a number is
a machine's measurement or a person's setting.

## Every command speaks NDJSON, and the terminal decides who hears it

A command writes one record per line to stdout -- no banner, no table, no colour -- whenever
stdout is not a terminal: a pipe, a container's log, an agent's shell and CI all read records
without asking. At a terminal the same records are rendered, the way `dg format` renders
them. `--json` asks for records on a terminal, `-o console` for the rendering into a pipe,
and `DIRIGENT_LOG_FORMAT` names either once. Every record carries a `kind`, which is what a
formatter dispatches on and what `jq` selects by, and it carries what its rendering needs, so
no renderer reads the run a second time. A table is a rendering of a record, and it lives in
the formatter, never in the command. There is no exception: `dg dev` at a terminal renders
its lines, and `dg init` in a pipe writes records.

### Giving a command a record

A command states each fact it has once, by calling `emit_fact(kind, message=..., **what it
carries)`. The `kind` names the fact rather than the entity it happened to -- `schedule.paused`,
`pipeline.deleted`, `db.upgraded` -- because the entity's own name is already a listing kind
whose row rides under `fields`, and a reader that dispatches on `kind` must be able to tell a
row from a change. The `message` is the verb in one word, and the fields are what the rendering
needs and nothing else: the identity quartet where the fact has an entity, the value that
changed, and for a check the list of problems it found. A refusal the CLI itself decided on is
`refuse(...)`, which writes the same `error` record the server's own problem shape becomes. No
command calls `console.print`: `emit_fact` writes NDJSON or hands the record to the formatter,
and which of the two happens is the invocation's business.

The rendering is the formatter's. A fact that fits one line needs nothing more -- the console
line already carries the message and every field. A fact that does not fit a line carries the
bulk in a field named in `summaries.BULKY`, so it stays off the line, and gets an entry in
`summaries.RENDERERS` keyed by its `kind` that draws it: `version` draws a table of packages,
`validation` draws the problems and the document's graph. A kind with no entry renders as its
line, which is why a record from a newer dirigent still reads. The test asserts on records --
`only(stdout, "schedule.paused")["code"]`, `refusal(stdout)["problems"]` -- and never on the
drawing; the few tests that cover a rendering call the formatter directly, in
`test_formatters.py`, with colour set explicitly rather than taken from the terminal.

## Plugins are pluginkit, and files end in `.yaml`

Any extension point -- blocks, connection kinds, storage backends, notifiers, format checkers
-- is built on `pluginkit` through `dirigent-plugin`, never a hand-rolled registry. And a
YAML file this project owns ends in `.yaml`, never `.yml`; a file a tool insists on naming,
like `mkdocs.yml`, keeps the name the tool expects.

## The test lanes, and the one that never gates

The fast lane (`make test`) runs on SQLite and is what every change is held to. Beside it are
lanes a marker keeps out of the default selection, each run on demand: `postgres` for what
only a real PostgreSQL proves, `s3` for a real object store, `docker` for a real daemon,
`queues` for real brokers, and `e2e` for the product driven the way a person drives it. CI
runs each of them as a job of its own.

`load` is the exception that never runs in the gate. `make load` fans a run out over fifty
attempts logging five thousand lines each, against a real PostgreSQL, and writes what the log
path cost -- rows a second, flush sizes and durations, how long a line takes to become
visible, connections held, and what the settled reads cost -- as `load` records on stdout.
It is a measurement, not a threshold: it is run on purpose, by a person, and read.
