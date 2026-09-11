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

- `operators` -- the blocks that do work and hand a typed output on
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
behind, and the next poke reads the same ground again, so a poke must tolerate that. And it **lives only as long as the waiting attempt** -- a poke
that succeeds ends the step, and nothing carries the cursor past it. Anything a downstream
step needs belongs in the output.

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

Because the seam is one entry point and the contract is one package, a pack is a normal Python
distribution that happens to be discovered. Moving one out of this monorepo into its own repo
is mechanical:

- **What travels with it:** the package (its operators, sensors, and connection kind), and its
  **examples** -- the documents that exercise its blocks belong with the pack, not with
  dirigent, because they are meaningless without it installed. A pack's examples are validated
  in the pack's own CI against the catalog the pack itself contributes.
- **What it depends on:** `dirigent-plugin` and `dirigent-common`, and nothing of
  `dirigent-core`. That is the entire surface an out-of-repo pack targets, and the reason the
  move is low-risk: the dependency points one way, at a small, versioned contract.
- **How it stays compatible:** `dirigent-plugin` is versioned; the pack pins a compatible
  range and `api_version` is the runtime handshake. The pack runs a conformance check against
  the plugin version it targets in its own CI; dirigent keeps a thin smoke job that installs
  the pack and confirms its catalog loads and its examples validate. A breaking change to the
  plugin contract is a major bump with a migration note.

The result is that a new integration is a repository, an entry point, and an install,
developed and tested on its own cadence and wired into any instance the moment it is present.

## Using a pack end to end: the Acme adapter

From an empty directory to a running acme pipeline.

### 1. A project and an instance

```bash
uv init flows && cd flows
uv add dirigent-cli dirigent-acme   # dirigent-cli brings the server, engine and built-in blocks; dirigent-acme is the adapter
uv run dg init                         # scaffolds an instance, a first admin, and an example document
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

On a terminal a missing secret is prompted for; in a script every value arrives via `--set`.

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
