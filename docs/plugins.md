# Plugins

Everything dirigent discovers and contributes is a plugin: blocks, connection kinds, storage
backends, notifiers, and the format checkers a schema asserts against. There is one framework
for all of it -- `pluginkit` -- and one seam between a pack and a running instance: a Python
entry point. A pack lives in its own repository, is installed into an instance's environment,
and is wired in by that entry point alone. Install is the whole of configuration.

`dirigent-plugin` is the contract a pack builds against. The worked example throughout this page
is `dirigent-acme`, a pack for an imaginary vendor, Acme: it contributes an `acme`
connection kind, the `acme.*` blocks that speak to it, and the `acme-site-id` format.

## The seam is one entry point

A pack declares a single entry point under the `dirigent.plugins.v1` group, pointing at its
plugin object:

```toml
# the pack's pyproject.toml
[project.entry-points."dirigent.plugins.v1"]
acme = "dirigent_acme:plugin"
```

That object exposes one `@extension`-marked method returning a `Contribution`:

```python
from dirigent_plugin import Contribution, extension


class AcmePlugin:
    @extension
    def contribute(self) -> Contribution:
        return Contribution(
            operators=[AcmeSitesOperator(), AcmeOrdersOperator(), ...],
            sensors=[AcmeOrderShippedSensor()],
            connection_kinds=[AcmeConnectionKind()],
            formats={"acme-site-id": is_site_id},
        )


plugin = AcmePlugin()
```

At startup the host (`dirigent_core.plugins.load_plugin_host`, built on pluginkit's
`PluginManager`) scans the `dirigent.plugins.v1` group, finds every installed distribution
that declares one, calls each `contribute()`, and merges the results into one catalog. The
scan happens **once**; after that dispatch is direct. Two packs claiming the same block id is
a startup error, not last-one-wins -- a block id is public API that stored pipelines reference
by string forever.

So adding a pack to any instance is:

```bash
uv add dirigent-acme
```

into the same environment, then a restart. It appears in `dg blocks` and as a connection kind
with no change to dirigent, no config file, and no registry to edit. Uninstall and it is gone.

## What a pack contributes

`contribute()` returns one `Contribution` spanning the surfaces the host knows:

- `operators` -- the blocks that do work and hand a typed output on,
  [a transform engine](transforms.md#writing-an-engine) among them
- `sensors` -- blocks that hold a run open until a condition is met
- `connection_kinds` -- how an external system is described and authenticated, with a health
  check
- `storage_backends` -- a scheme a `<scheme>://` URI writes bytes to
- `notifiers` -- where an alert is sent
- `formats` -- a JSON Schema format checker by name, so a schema that writes `format: <name>`
  asserts wherever the pack is installed and stays a passing annotation where it is not

A `Contribution` carries an `api_version`: a pack written against a different revision of the
contract is refused at load, cleanly, rather than half-working. The host merges every pack's
contribution and rejects id collisions across all surfaces.

### A pack writes RST, and the catalog serves markdown

A block's user-facing documentation is its field docstrings, which are Python docstrings and
so are written in reStructuredText. Every reader of the catalog -- the UI's block panel and
step form, `dg blocks show`, and the generated [block reference](blocks.md) -- renders
markdown. `dirigent_common.docstrings.as_markdown` is where the two meet, applied once at the
catalog boundary: `dirigent_core.plugins.json_schema` walks the schema a contributed model
publishes and rewrites every `description` on the way out.

```python
class CheckoutConfig(BlockModel):
    ref: str = "main"
    """The branch, tag or commit to check out. ``HEAD`` is not a ref."""
```

The catalog serves that description with `HEAD` in single backticks. So a pack author writes
RST inline literals -- double backticks -- and gets markdown inline code everywhere. That
rewrite is the whole of the translation: inline literals and nothing else, so RST that has no
markdown equivalent reaches a reader unchanged. A description is one or two plain sentences
with code in double backticks.

### A config field that names another thing says so

A block whose config takes the code of a connection or of a schema types that field
`ConnectionRef` or `SchemaRef` rather than `str`:

```python
class CheckoutConfig(BlockModel):
    connection: ConnectionRef
    """The ``git`` connection naming the remote and holding its credential."""
```

Both are `str` to every validator, and both publish `x-dirigent-ref` in the schema the catalog
serves. What reads it is the step form: a field typed either way is drawn with the thing it names
under it -- the connection's settings and health, or the schema's body -- and a link to that
thing's own screen.

### A refusal a block makes carries a code

A block never refuses with a free string. Every refusal it can make is a catalogued
`Message`: a stable dotted code, and one English template with named params. A pack keeps
them in a `messages.py` of its own, under a `Catalogue` named for the pack:

```python
from dirigent_common import Catalogue

ACME = Catalogue("acme")

NO_CREDENTIAL = ACME.define(
    "no_credential",
    "connection {connection} has no api_key, and {url} accepts none without one",
)

REJECTED = ACME.define("rejected", "{method} {url} answered {status}: {detail}")
```

`BlockFailure` takes the message and the params it renders, beside the classification the
engine retries on:

```python
raise BlockFailure(
    REJECTED,
    error_class=ErrorClass.REJECTED,
    method=config.method,
    url=request_url(config),
    status=response.status_code,
    detail=body.get("message", ""),
)
```

`check_config` answers with issues built the same way, from the same catalogue:

```python
def check_config(self, config: BaseModel) -> list[Issue]:
    if not isinstance(config, AcmePushConfig) or config.batch_size <= MAX_BATCH:
        return []
    return [Issue.of(BATCH_TOO_LARGE, asked=config.batch_size, maximum=MAX_BATCH)]
```

The attempt row, the run event and the problem document all carry the code and the params
beside the rendered sentence, so an operator can select one refusal out of a stream with
`jq 'select(.error_code == "acme.rejected")'` however the English is later reworded. A pack's
prefix is its pack name, and it owns everything under it. A param never carries a secret: the
connection's code names it, its credential does not appear.

### A stream a block captures comes through the context

A block that runs something which prints -- a process, a container, a remote job -- never
names a storage URI of its own. It asks the context for a capture, writes the stream through
it as it arrives, and puts the URI it is handed in its output:

```python
printed = 0
async with ctx.capture("stdout") as sink:
    async for chunk in job.stdout():
        printed += await sink.write(chunk)
return AcmeRunOutput(stdout_uri=sink.uri, stdout_bytes=printed)
```

The engine names the object under the run's scratch prefix, after the step, the fan-out item
and the attempt, so a retry never writes over what the attempt before it printed. The name
is what distinguishes one stream from another inside a step: `"stdout"` and `"stderr"`, or
`f"{command}-stdout"` where a block runs several. `content_type` defaults to `text/plain`.

How much of a stream a block may also inline in its output is `ctx.inline_capture`, in bytes.
Inline the head, count the whole, say whether the two disagree, and leave the rest to the URI:
a step that prints a gigabyte must be a file in storage, never a gigabyte in the worker.

### A sensor keeps its place in a cursor

A sensor's `poke` runs once and returns: either the observation, which ends the step, or
`NotYet`, which parks the attempt until the next poke is due. A sensor that reads a stream
needs somewhere to write down how far it has read, and that is the cursor.

```python
class QueueDepth(Sensor[QueueDepthConfig, QueueDepthOutput]):
    spec = SensorSpec(id="demo.queue_depth", summary="Wait for messages on a queue.")
    config_model: ClassVar[type[BaseModel]] = QueueDepthConfig
    output_model: ClassVar[type[BaseModel]] = QueueDepthOutput

    async def poke(self, config: QueueDepthConfig, ctx: StepContext) -> QueueDepthOutput | NotYet:
        # None on the first poke, and whatever the last committed NotYet returned after that.
        seen = int((ctx.cursor or {}).get("offset", 0))
        messages = await read_from(config.queue, since=seen)
        if not messages:
            return NotYet(message=f"nothing past offset {seen}")
        if len(messages) < config.min_messages:
            # Keep the ground already covered, so the next poke does not read it again.
            return NotYet(cursor={"offset": seen + len(messages)}, next_poll_in=config.poll_every)
        return QueueDepthOutput(messages=messages, count=len(messages))
```

Three rules make a cursor safe to rely on. It **replaces** rather than merges, so everything
worth keeping is copied forward into each `NotYet`, and omitting it leaves the stored one as
it is. It is **stored by the transaction that parks the attempt**, which makes advancing
at-least-once: a worker that dies between the read and that commit leaves the older cursor
behind, and the next poke reads the same ground again, so a poke must tolerate that. And it
**lives only as long as the waiting attempt** -- a poke that succeeds ends the step, and
nothing carries the cursor past it. Anything a downstream step needs belongs in the output.

## A formatter is a second extension point

`dg format` renders a stream, and the formatter it dispatches on is contributed through a
second entry point group and a second collecting extension point:

```toml
# the pack's pyproject.toml
[project.entry-points."dirigent.formatters"]
shouty = "my_package:plugin"
```

```python
from typing import Any

from dirigent_common import Formatter
from dirigent_plugin import extension


class Shouty:
    name = "shouty"
    version = "1"

    def render(self, record: dict[str, Any]) -> str:
        return str(record.get("message", "")).upper()


class ShoutyPlugin:
    @extension
    def formatters(self) -> list[Formatter]:
        return [Shouty()]


plugin = ShoutyPlugin()
```

The CLI owns this manager. It scans the `dirigent.formatters` group once, calls each
`formatters()`, and indexes every formatter returned by its `name`. That name is what
`dg format <name>` dispatches on, so two packages claiming one -- or a package claiming the
built-in `console` or `compact` -- is refused at startup, the way two packs claiming one block
id are. The `Formatter` protocol lives in `dirigent_common`: a name, a version, and one
`render` method, so a package ships a formatter without depending on the CLI or on the block
contract. A formatter renders a record kind it has never heard of rather than failing.

## Example shelves are a third extension point

A distribution may carry example documents, and the host reads them through a third
collecting extension point on the same `dirigent.plugins.v1` group. `examples()` answers with
the directories the shelves live in, as `importlib.resources` traversables or plain paths:

```python
from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from dirigent_plugin import extension


class ExamplesPlugin:
    @extension
    def examples(self) -> Sequence[Traversable]:
        return [files("my_package") / "shelves"]


plugin = ExamplesPlugin()
```

A plugin implements whichever of the three points it has something to say through; a
distribution that only carries documents implements `examples()` and no `contribute()` at all.
The host walks each directory recursively on the first call and never at startup, so a worker
pays nothing for a corpus it will not read. A file that parses as a `dirigent/v1` document
becomes one catalogue entry -- its code, name, description, tags, `requires`, the shelf it
sits on, and its text -- and anything else on the shelf is passed over with a warning naming
the plugin and the file. Two plugins may carry one code; one plugin carrying it twice keeps
the first. The core corpus ships this way, as `dirigent-examples`.

What the host reads is what every surface serves: `GET /api/v1/examples` and
`GET /api/v1/examples/{code}`, `dg examples list` and `dg examples show`, and
`dg pipeline new` for a document wearing the `starter` tag. A pack's shelves therefore reach
a person the moment the pack is installed, with nothing to register beyond this hook.

**The starter rule.** A document earns `starter` by being a real multi-step flow on a real
source -- a public endpoint, or a service a connection names -- and it carries its own
`connections:` and `schemas:` so that `dg run --local` runs it alone. `dg pipeline new <code>`
copies its text verbatim into `pipelines/`, rewrites the `code:` line, drops `starter` from
the tags, and moves each carried section into `requires:`, so the copy names the connections
and schemas to create first instead of carrying them.

## A SQL engine is a fourth extension point

The `sql` family drives any backend a SQLAlchemy async driver reaches. A backend that needs
more than a driver -- DuckDB, whose databases are files and which has no async driver at all
-- is a package of its own, under a group the family scans for itself:

```toml
# the pack's pyproject.toml
[project.entry-points."dirigent.sql.engines.v1"]
duckdb = "dirigent_block_duckdb:plugin"
```

An engine subclasses `SqlEngine` from `dirigent_block_sql.engines`, claims the one backend a
URL names it by, and answers five questions: `validate` refuses a connection it cannot open,
`resolve` says where a database written as a relative path lands, `bind` says what a parameter
becomes before the database sees it, `check` reaches the database for `dg connection check`,
and `session` opens what a step runs its statements in. [Adding an
engine](sql.md#adding-an-engine) is that contract in full, and `dirigent-block-duckdb` is the
worked example. Nothing in `sql.query` or `sql.execute` changes for a new backend.

## How a pack connects systems together

The surfaces are the vocabulary; the connecting happens in a pipeline. A **connection kind**
plus the **blocks** that speak it bring one external system into reach. From there, packs
compose without knowing about each other: every block reads `${steps.<name>.output...}` and
writes a typed output, so an `acme` export can feed a `convert` transform, feed an `s3` write,
feed an `http.request` post -- three packs meeting only through the run's data plane and the
shared step context.

The **connection registry** is the seam to each system. A step names a connection by code; the
connection holds the base URL and the credential. The same document points at staging or
production by swapping the connection, not the pipeline. dirigent reaches out to the systems
its connections name; nothing registers inbound. "Connecting things" is therefore: install the
packs that bring the systems, then wire their blocks in a DAG through connections and `${...}`
references.

### What `ctx.http` reads from a connection

`ctx.http(ref)` builds a client for a connection of any kind, so it reads a config's fields by
name rather than by model:

| Field | What the client does with it |
| --- | --- |
| `base_url` | The root every request path resolves against |
| `bearer_token` | Sent as `Authorization: Bearer <token>` |
| `api_token` | Sent as `Authorization: ApiToken <token>`, the scheme a personal access token usually needs |
| `api_token_scheme` | The scheme `api_token` is sent under instead of `ApiToken` |
| `basic_username`, `basic_password` | The client's HTTP basic auth |
| `verify_tls` | Whether certificates are verified |
| `timeout` | The timeout applied to every request |

`bearer_token` wins over `api_token` when a config carries both, and basic credentials win over
either, because httpx applies auth per request and the token is a client header. A connection
kind that names none of these fields still gets a client, with no base URL and no credential.

## A pack in its own repository

`dg blocks new <name>` writes a pack to start from: `dirigent-<name>`, with a
`pyproject.toml` declaring the entry point, a plugin object, one operator, and a test that
registers the pack through a plugin manager and calls that operator. `uv sync && uv run
pytest` inside it passes from the first minute, so the first edit is a block rather than
wiring.

**What a pack is called** says what it contributes: `dirigent-<system>` for an adapter pack
(`dirigent-dhis2`), `dirigent-block-<family or engine>` for blocks (`dirigent-block-parquet`,
`dirigent-block-duckdb`), `dirigent-storage-<backend>` (`dirigent-storage-s3`), and
`dirigent-notify-<channel>` for a channel. A runtime package is `dirigent-<role>` -- `core`,
`server`, `cli`, `client`, `common`, `plugin`, `testing` -- and `dirigent-blocks` is the
umbrella over the built-in `dirigent-block-*` families.

Because the seam is one entry point and the contract is one package, a pack is a normal Python
distribution that happens to be discovered. Moving one out of this monorepo into its own repo
is mechanical:

- **What travels with it:** the package (its operators, sensors, and connection kind), and its
  **examples** -- the documents that exercise its blocks belong with the pack, not with
  dirigent, because they are meaningless without it installed. A pack's examples are validated
  in the pack's own CI against the catalog the pack itself contributes.
- **What it depends on:** `dirigent-common` and `dirigent-plugin`, and nothing of
  `dirigent-core`; `dirigent-testing` in its dev group, for the fixtures and the conformance
  kit. All three come from PyPI pinned to one exact version (`dirigent-plugin==<version>`),
  the version of the runtime the pack releases against. That is the entire surface an
  out-of-repo pack targets, and the reason the move is low-risk: the dependency points one
  way, at a small, versioned contract.
- **How it checks itself:** `dirigent-testing` carries the conformance kit, and neither half
  of it imports `dirigent-core`. `assert_contribution_conforms(contribution)` checks the
  blocks a contribution provides are well-formed. `check_pack_examples(contribution,
  directory)` checks each of the pack's own documents: that it is a `dirigent/v1` pipeline
  coded after its file, that every block it names is one the pack contributes, that each
  config fits that block's published schema, and that a connection a step names is one the
  document accounts for -- carried in its own `connections:`, so the document runs alone under
  `dg run --local`, or listed under `requires.connections`. Both answer with a list of
  human-readable issues, and an empty list means it passed.
- **How it stays compatible:** `api_version` on the `Contribution` is the runtime handshake,
  and a pack written against another revision is refused at load rather than half-working.
  Before 1.0 the contract changes directly: a dirigent release is a pack release at the same
  version, and `dirigent-integration` assembles every pack and runs everyone's tests against
  the new tips before a release is called done.

The result is that a new integration is a repository, an entry point, and an install,
developed and tested on its own cadence and wired into any instance the moment it is present.

## Using a pack end to end: the Acme adapter

From an empty directory to a running acme pipeline.

### 1. A project and an instance

```bash
uv init flows && cd flows
uv add dirigent-cli dirigent-acme   # the runtime, the built-in blocks and the server, plus the pack
uv run dg init                      # scaffolds an instance, a first admin, and an example document
```

`uv add dirigent-acme` is the whole of installing the adapter: the entry point it declares is
what the instance discovers at startup, so `dg blocks` lists the `acme.*` blocks and `acme`
appears as a connection kind, with nothing registered by hand. A pack added to an instance
that is already running is picked up on the next restart.

### 2. A connection

The credential lives in one connection, created once; documents name it by code and never
carry it:

```bash
uv run dg connection create acme acme-prod \
  --set base_url=https://api.acme.example/v2 \
  --set basic_username=ops --set basic_password=district
# or a personal access token instead of basic auth:
#   --set api_token=<PAT>
uv run dg connection check acme-prod     # confirms the credential and reports the server version
```

At a terminal a required field the command was not given is prompted for, and a bare
`dg connection create acme acme-prod` offers every secret the kind declares; in a script every
value arrives via `--set`, and an empty one (`--set api_token=`) leaves the field unset.

### 3. Schemas to validate against (optional)

To catch a change in the service's payload at the boundary, hold the expected shape as a schema
and gate on it (see [JSON Schema](json-schema.md)):

```bash
uv run dg schema create schemas/acme-sites.json
```

### 4. A pipeline

A document that reads the site list, checks its shape, and exports a day of orders to
storage, naming the connection by code:

```yaml
format: dirigent/v1
kind: pipeline
code: nightly-export
requires:
  blocks: [acme.sites, validate.schema, acme.orders]
  schemas: [acme-sites]
steps:
  sites:
    block: acme.sites
    config:
      connection: acme-prod
      region: nordics
      fields: id,name,elevation
  check:
    block: validate.schema
    depends_on: [sites]
    config:
      input: ${steps.sites.output.value}
      schema: acme-sites
  export:
    block: acme.orders
    depends_on: [check]
    config:
      connection: acme-prod
      site: NO-BRGN-01
      period: 2026-01
      measure: TEMPERATURE
  store:
    block: storage.write
    depends_on: [export]
    config:
      target: "${run.scratch}/orders.json"
      value: ${steps.export.output.orders}
```

Apply it, then run it:

```bash
uv run dg apply nightly-export.yaml
uv run dg run nightly-export --watch
```

### Standalone, with no server

A document that carries its own `connections:` block runs on its own, which is how a pack's own
examples work. They live with the pack in the pack's own repository; from a checkout of it:

```bash
uv run dg run --local examples/acme-orders.yaml
```

A real pack built exactly this way is
[dirigent-dhis2](https://github.com/winterop-com/dirigent-dhis2).
