# JSON Schema

A schema is a named picture of a payload: the shape a read is expected to return, written down
once so a pipeline can be refused the moment the payload moves out from under it. Dirigent holds
schemas as a first-class resource -- create, list, show, delete -- and validates every one as a
[JSON Schema, Draft 2020-12](https://json-schema.org/draft/2020-12) when you store it. This page
is that language, taught on the shapes a pipeline actually reads.

A schema is **locally authored**. It is the picture *you* hold of the payload, not something
fetched or introspected from the source. That is the whole point: the source cannot tell you it
changed, so you say what you expect, and dirigent tells you when the two stop matching.

## A schema is applied on its own

A pipeline document carries a pipeline. A schema is not part of one -- it is applied by itself,
the way a connection is:

```bash
dg schema create schemas/acme-sites.json   # from a file
dg schema create -                               # from stdin
dg schema list
dg schema show acme-sites
dg schema delete acme-sites
```

A schema reads its own identity from its keywords, so there is nothing else to pass:

| Keyword | Becomes | If absent |
| --- | --- | --- |
| `$id` | the `code` the schema is addressed by | the file's stem (`acme-sites.json` -> `acme-sites`) |
| `title` | the `name` shown beside the code | the schema has no name, and the code is its title |
| `description` | the body | the schema has no body |

`code` is the only piece with identity: it is constrained (lowercase, digits, hyphens), unique on
the instance, and what every reference uses. `title` and `description` are free text. A `$id` that
is a full URI is accepted, and its last path segment is taken as the code.

## The shape of a shape

Every example below describes the same read, `GET /api/sites.json?fields=id,name,elevation`,
whose payload is an object wrapping a list:

```json
{"sites": [
  {"id": "NO-BRGN-01", "name": "Bergen Florida", "elevation": 12},
  {"id": "NO-TRMS-02", "name": "Tromso Holt",    "elevation": 21}
]}
```

The smallest schema that says anything is a `type`:

```json
{"type": "object"}
```

That accepts the payload above and rejects a list or a string. `type` is the first question a
schema asks of a value, and the seven answers are `object`, `array`, `string`, `number`,
`integer`, `boolean`, and `null`.

## Objects: properties, required, and the closed door

`properties` names the fields of an object and gives each its own schema. `required` lists the
ones that must be present:

```json
{
  "type": "object",
  "required": ["sites"],
  "properties": {
    "sites": {"type": "array"}
  }
}
```

A field named in `properties` is described but not demanded -- absence is fine, a wrong type is
not. `required` is the separate question of presence. A field that is present but not named in
`properties` is, by default, **allowed and unchecked**: JSON Schema is open by default, so extra
keys pass silently.

Say `additionalProperties: false` to close that door -- to reject any field you did not name:

```json
{
  "type": "object",
  "required": ["sites"],
  "properties": {"sites": {"type": "array"}},
  "additionalProperties": false
}
```

Now `{"sites": [], "pager": {}}` is refused, because `pager` was not named. This is the
difference between "the fields I need are here" and "these are the only fields there are." A read
that pins a payload usually wants the closed door on the objects it fully understands, and the open
door where the source may add fields you do not care about.

## Arrays and the shape of an element

`items` gives one schema that every element of an array must satisfy. Nest it into the field to
describe the list's contents:

```json
{
  "type": "object",
  "required": ["sites"],
  "properties": {
    "sites": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "elevation"],
        "properties": {
          "id":        {"type": "string"},
          "name":      {"type": "string"},
          "elevation": {"type": "integer", "minimum": -500}
        }
      }
    }
  }
}
```

This is the whole `acme-sites` example. It accepts the payload at the top of the page and
rejects each of these, each for one reason:

- `{"sites": [{"id": "x", "name": "Bergen Florida"}]}` -- the element is missing `elevation`.
- `{"sites": [{"id": "x", "name": "Bergen Florida", "elevation": -900}]}` -- `elevation` is below `minimum`.
- `{"sites": [{"id": 42, "name": "Bergen Florida", "elevation": 12}]}` -- `id` is a number, not a string.

`minItems` and `maxItems` bound the length; `uniqueItems: true` forbids duplicate elements.

## Numbers and strings: pinning the value, not just the type

A `string` takes `minLength`, `maxLength`, and `pattern` -- a regular expression the whole string is
tested against. An Acme site id is a two-letter country code, a four-letter site code, and a
two-digit index:

```json
{"type": "string", "pattern": "^[A-Z]{2}-[A-Z]{4}-[0-9]{2}$"}
```

That accepts `"NO-BRGN-01"` and rejects `"too-short"` and `"has a space here!!"`. A `number` or
`integer` takes `minimum`, `maximum`, and the exclusive pair `exclusiveMinimum` / `exclusiveMaximum`.

## enum: the value is one of a known set

`enum` lists the values a field may take. The Acme service's `measure` is a fixed vocabulary,
and a payload carrying a word that is not in it is exactly the drift a schema exists to catch:

```json
{
  "type": "string",
  "enum": ["TEMPERATURE", "PRECIPITATION", "WIND_SPEED", "WIND_DIRECTION", "HUMIDITY", "PRESSURE"]
}
```

`"TEMPERATURE"` passes; `"WINDCHILL"` is refused. `enum` works on any type -- `"enum": [1, 2, 3]`
or `"enum": [true, false]` -- and `const` is the one-value case, `"const": "HOURLY"`.

## Reuse: $defs and $ref

When a shape appears twice, name it once under `$defs` and point at it with `$ref`. A site id is
the same three parts wherever it appears, so it is written once:

```json
{
  "type": "object",
  "required": ["sites"],
  "properties": {
    "sites": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"$ref": "#/$defs/site_id"}}
      }
    }
  },
  "$defs": {
    "site_id": {"type": "string", "pattern": "^[A-Z]{2}-[A-Z]{4}-[0-9]{2}$"}
  }
}
```

`#/$defs/site_id` is a JSON Pointer into this document: `#` is the root, and the path walks to
the named subschema. A `$ref` may point anywhere in the document, and a `$def` may `$ref` another,
so a shape composes out of named parts.

## format: the string that is really a date, or a site id

`format` annotates a string with the *kind* of string it is -- a date, a UUID, an email. In JSON
Schema, `format` is an annotation by default and asserts nothing; a validator only checks it when it
is handed a format checker. **Dirigent's engine always hands its validator a checker**, so a
`format` you write is enforced. Alongside the standard formats (`date-time`, `date`, `time`,
`email`, `uri`, `ipv4`, `ipv6`, `hostname`, `regex`, and the rest), dirigent registers the ones its
own data speaks:

| Format | A string that is | Example |
| --- | --- | --- |
| `ulid` | a Crockford base-32 ULID, 26 chars | `01ARZ3NDEKTSV4RRFFQ69G5FAV` |
| `uuid4` | a random UUID (version 4) | `f47ac10b-58cc-4372-a567-0e02b2c3d479` |
| `uuid7` | a time-ordered UUID (version 7) | `018f6d8e-1a2b-7c3d-8e4f-0123456789ab` |
| `md5` | a 32-character hex digest | `d41d8cd98f00b204e9800998ecf8427e` |
| `sha1` | a 40-character hex digest | ... |
| `sha256` | a 64-character hex digest | ... |
| `sha512` | a 128-character hex digest | ... |
| `base64` | standard base-64, decodable | `aGVsbG8=` |

So a record's `observed_at` is pinned as a real timestamp, not just any string:

```json
{"type": "string", "format": "date-time"}
```

`"2026-01-01T09:30:00Z"` passes; `"last Tuesday"` is refused. A format only ever narrows a
`string`: a value of the wrong type is caught by `type`, and `format` speaks only once the value is
already a string.

A pack adds its own formats the same way it adds blocks: a `Contribution` carries a `formats`
map of name to checker, and every format an installed pack contributes joins the ones above in
the checker the engine hands its validator. So a `dirigent-acme` pack contributes
`acme-site-id` and `acme-period`, and a schema that writes `format: acme-site-id`
asserts wherever that pack is installed. This keeps a schema portable: a `format` no installed
pack contributes stays a passing annotation -- the value is valid, just unchecked -- so the same
schema asserts on an instance that has the pack and passes on one that does not. A pack that
does this for a real system is
[dirigent-dhis2](https://github.com/winterop-com/dirigent-dhis2).

## Where a schema is enforced

Storing a schema validates the *schema* -- that it is itself a legal Draft 2020-12 document. A
schema validates a *payload* at a `validate.schema` gate, which passes a value through when it
fits and fails the run at the boundary when it does not. A gate never writes a shape inline: its
`schema` is a `code`, and the code resolves one of two ways.

The code names a schema the instance holds, applied on its own the way a pipeline's connection is
created rather than carried:

```yaml
check:
  block: validate.schema
  depends_on: [fetch]
  config:
    input: ${steps.fetch.output.body}
    schema: acme-sites
```

Because a named schema is a resource with a `code`, a document that references one declares it,
and applying that document on an instance that does not hold the schema is refused by the same
`requires` preflight that guards blocks and connections:

```yaml
requires:
  schemas: [acme-sites]
```

Or the document carries the shape itself, in a top-level `schemas:` section keyed by code -- the
same section, and the same rules, as the top-level `connections:` a document can carry:

```yaml
schemas:
  site-record:
    type: object
    required: [sites]
    properties:
      sites: { type: array }

steps:
  check:
    block: validate.schema
    depends_on: [fetch]
    config:
      input: ${steps.fetch.output.body}
      schema: site-record
```

A carried schema resolves the gate's code before any instance-held one, so a document that
carries every shape it names runs on its own; it needs no `requires.schemas` entry, because it
satisfies its own reference. Its body is checked to be a valid schema when the document is
applied, the way the parameter schema is. A server refuses a document that carries a schema,
exactly as it refuses one that carries a connection -- storing it would put the shape in every
version of the pipeline -- so the carried form is for a standalone or `--local` run, and a shared
instance holds its schemas as their own resource. A document applied into a local run with
`--also-apply` keeps the schemas it carries too, so a child started through `pipeline.run`
resolves its own gates. A `dg run --local` run holds no instance schema until one is handed
to it:

```bash
dg run --local --schema examples/schemas/ou-record.json \
  examples/validate/the-shape-is-wrong.yaml
```

A pipeline's own `params` schema is the other place a payload is validated: the parameters of
every run, whoever asked for it -- the API, the CLI, a schedule's pins, a backfill, a mapped
webhook payload -- are checked against it before the run is created, and against the same
assembled checker a gate uses. So a parameter declared `format: date` refuses `2026-13-40` at
the door rather than carrying it into the first step, and a parameter declared
`format: acme-site-id` asserts on an instance where that pack is installed and passes on
one where it is not.

## The reference shelf

Draft 2020-12 is the full language; the working set, by what a keyword is doing:

| Doing | Keywords |
| --- | --- |
| Naming the kind | `type` (`object`, `array`, `string`, `number`, `integer`, `boolean`, `null`) |
| Objects | `properties`, `required`, `additionalProperties`, `patternProperties`, `propertyNames`, `minProperties`, `maxProperties` |
| Arrays | `items`, `prefixItems`, `contains`, `minItems`, `maxItems`, `uniqueItems` |
| Numbers | `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf` |
| Strings | `minLength`, `maxLength`, `pattern`, `format` |
| A fixed value | `enum`, `const` |
| Combining | `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else` |
| Reuse | `$defs`, `$ref` (a JSON Pointer, `#/$defs/name`) |
| Identity | `$id` (-> code), `title` (-> name), `description` (-> body), `$schema`, `$comment` |

[`examples/schemas/`](https://github.com/winterop-com/dirigent/tree/main/examples/schemas) and
[`examples/validate/`](https://github.com/winterop-com/dirigent/tree/main/examples/validate) are
this language exercised end to end: a schema applied with `dg schema create` and no pipeline in
sight, a document that carries the same shape itself, and a payload refused at the gate.
