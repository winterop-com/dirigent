# The playground

Two things an instance gives a document that needs something to happen instead of a service
to call: a **node** that generates data and behaviour in the run itself, and a handful of
**HTTP routes** the instance serves to itself. Both are always on, both are ours, and neither
needs a network.

## Which one to reach for

**The node, `playground.generate`, is for a document that needs something to happen.** A
fan-out that needs a list to walk, a retry that needs a step that fails twice, a gate that
needs a shape that drifts, a storage example that needs a payload over the threshold. No
connection, no URL, no network, and it works at the start of a flow, in the middle of one, or
as its last step.

**The routes are for a document that is teaching HTTP itself.** A request with headers and a
query, a status a client has to handle, a redirect, a delay against a timeout. Those
documents want a real HTTP hop, and now they have one they own.

A document that wants rows should reach for the node. A document that wants to show
`http.request` doing something should reach for the routes.

## The node

One block, `playground.generate`, contributed by the `block-base` family. It takes an
optional `input` and produces an output, so it is an ordinary node in the graph.

```yaml
steps:
  people:
    block: playground.generate
    config:
      rows: 5
      seed: 42
      fields:
        who: name
        where: city
        when: date_this_decade
```

```json
{
  "records": [{"who": "Brian Yang", "where": "Lake Joshuabury", "when": "2024-04-21"}],
  "rows": 5, "seed": 42, "locale": "en_US",
  "fields": {"who": "name", "where": "city", "when": "date_this_decade"},
  "drift": "none", "page": null, "size": null, "pages": null,
  "delay_ms": 0, "attempt": 1, "fail_until": 0,
  "payload": null, "payload_bytes": null, "input_rows": null
}
```

Every knob comes back on the output, resolved: what the step actually ran with, after
defaults and after a seed was drawn. A reader looking at a middle node in the UI can see
which knobs produced what they are looking at.

### The knobs

| Knob | Default | What it does |
| --- | --- | --- |
| `fields` | `name`, `email`, `city` | Which Faker provider fills each output field. |
| `rows` | `1` | How many records exist. Ignored when an `input` is supplied. |
| `locale` | `en_US` | The Faker locale the providers generate in. |
| `seed` | drawn | Makes the records reproducible; the output always says which seed was used. |
| `drift` | `none` | Emit a deliberately wrong shape: `strings`, `missing` or `extra`. |
| `page`, `size` | unset | Hand back one page of the records, and say how many pages there are. |
| `payload` | unset | Filler of a chosen size, as `32kb`, beside the records. |
| `delay` | `0s` | Take that long before answering. At most 30 seconds. |
| `fail_until` | `0` | Fail that many attempts before succeeding. |
| `input` | unset | A value from upstream to work from. |

Every one of them defaults to something quiet, so a step with no config at all generates one
row and answers at once, and a document only sets the knob it is teaching.

### All of Faker, through the field map

`fields` maps an output field name to the Faker provider that fills it. Every provider the
installed Faker offers is reachable, and nothing has to be added here for a new one to work:

```yaml
      fields:
        who: name
        where: city
        what: catch_phrase
        # A provider that takes arguments is written as an object.
        score:
          provider: pyint
          args:
            min_value: 0
            max_value: 100
```

**Finding a provider.** A reader cannot guess 280 names, and a list pasted into this page
would rot. Ask the installed Faker instead, which is the one the node uses:

```console
$ uv run faker             # every provider, with a sample of each
$ uv run faker -l no_NO    # the same, for one locale
$ uv run faker pyint 1 6   # one provider, with its arguments
```

**What a provider name may be.** A field map is a string from a document selecting an
attribute on a library object, so it is bounded: the node builds the set of names the
installed Faker actually offers, from the provider objects themselves, and refuses anything
outside it. Nothing beginning with an underscore is ever in the set, and Faker's own plumbing
-- `seed`, `seed_instance`, `add_provider`, `format` and the rest -- is excluded by name. An
unknown provider is a `rejected` failure that names what was not found.

**A `Decimal` comes back as a string**, because it keeps its precision. A field a schema
reads as a number wants `pyfloat` or `pyint`.

### A seed, always

Anything that varies takes a seed, and the answer says which seed produced it. Give one and
the records are identical on every run and every machine, which is what lets an example
assert on them. Give none and the node draws one and reports it, so a surprising answer can
still be reproduced by sending that number back.

The `payload` filler is a fixed repeating pattern rather than generated, so a payload of a
given size is the same bytes every time and has no seed to report.

### What an `input` does

`input` is the field every transform names for the same idea, and it means the same thing
here, except that it is optional: the node is often a document's first step and has only its
knobs to work from.

| `input` | `fields` named | What happens |
| --- | --- | --- |
| absent | either | The knobs generate `rows` records. |
| a list | no | Each element is a record, unchanged. |
| a list | yes | Each element gains the generated fields. |
| an object or a scalar | either | One record. A scalar arrives under `value`. |

**A supplied input decides how many records there are, and `rows` is ignored.** This is the
case a reader hits first: `rows: 10` against a list of three gives three records, and the
output reports `rows: 3` and `input_rows: 3` so the truth is on the record rather than in
this page. `drift`, `page`, `size` and `payload` all apply to a supplied input exactly as they
apply to a generated one.

### Drift

`drift` makes the shape wrong on purpose, so a schema gate can be seen catching it. Each one
breaks a different kind of rule:

| `drift` | What changes | What refuses it |
| --- | --- | --- |
| `strings` | Every number and boolean becomes a string. | A schema with `"type": "number"`. |
| `missing` | The field map's first field is left out. | A schema with `required`. |
| `extra` | A field called `drifted` is added. | A schema with `additionalProperties: false`. |

### The three positions

The node is designed to sit anywhere in a document, and
[`examples/playground/`](https://github.com/winterop-com/dirigent/tree/main/examples/playground)
shows all three:

- **At the start**, with no `input` and no upstream: the lead case, and the reason `input` is
  optional at all.
- **In the middle**, taking a value from an earlier step and handing one to a later one.
- **At the end**, as the document's last step. It requires nothing downstream, and its output
  is an account of what happened: the records, the seed, and every knob.

## The routes

The instance serves these to itself under `/api/v1/playground`. They need **no credential**:
a pipeline step calling its own instance's playground must not need a token, and there is
nothing here to protect -- no database session is opened, no instance data is read, and
nothing is remembered between requests.

They are in the OpenAPI document with everything else, under the `playground` tag.

### One envelope

Every route answers the same shape. `kind` names the answer, `request` holds what arrived
verbatim, and every other key is what the route decided:

```json
{
  "kind": "request",
  "request": {
    "method": "GET",
    "url": "http://127.0.0.1:3333/api/v1/playground/request?station=bergen",
    "path": "/api/v1/playground/request",
    "args": {"station": "bergen"},
    "headers": {"host": "127.0.0.1:3333", "accept": "*/*"},
    "body": null,
    "body_kind": "none",
    "body_bytes": 0,
    "content_type": null
  },
  "status": 200
}
```

**Reflection is a property of every route, not one route's job.** A chosen status comes back
beside the arguments that chose it; a redirect comes back beside the hop count that caused
it. `request.args` is what was sent, as strings; the keys beside `request` are what was used,
typed and defaulted.

**A body appears exactly once.** `body_kind` says how it was read -- `json`, `form`, `text`
or `none` -- and `content_type` says what it arrived under. There is no second copy of a JSON
body under another name.

**A credential is never reflected.** `authorization`, `cookie` and `proxy-authorization` come
back as `<redacted>`: an origin that reflected a session cookie would hand it to any script
on that origin, which is exactly what `httponly` exists to prevent.

### The routes

Every route takes `status` (the status to answer with, 100 to 599) and `delay` (how long to
take first, as `250ms` or `2s`, at most 30 seconds).

| Route | Methods | What it does |
| --- | --- | --- |
| `/playground/request` | GET, POST, PUT, PATCH, DELETE | Reflects, and nothing else. |
| `/playground/redirect` | GET | Issues a redirect, or a chain of them. |
| `/playground/unreliable` | GET | Answers a failing status until a given attempt. |
| `/playground/response-headers` | GET | Sets the query's pairs as response headers. |
| `/playground/auth` | GET | Requires a credential, and refuses a call without one. |

**`/playground/request`** is the degenerate case: it adds nothing of its own. One path serves
all five methods, so there is no wrong method to answer.

```console
$ curl 'http://127.0.0.1:3333/api/v1/playground/request?station=bergen&status=503'
```

**`/playground/redirect`** takes `hops` (up to 10, default 1), `status` (301, 302, 303, 307
or 308) and `to`. Each hop points at the next, and the last points at the destination, which
is `/playground/request` unless `to` names another path. `to` is a **path on this instance
and never an absolute URL**: an open redirect is a phishing tool wearing the instance's own
domain, and there is nothing to teach that needs one.

**`/playground/unreliable`** takes `attempt` (which attempt the caller says this is) and
`fail_until`, and answers `status` (default 503) while `attempt <= fail_until`, then 200. The
window is driven by the attempt the caller names because the playground remembers nothing
between requests, and an answer that depended on what it remembered could not be reproduced.
A document teaching a retry usually wants the node's `fail_until` instead, which reads the
engine's own attempt number.

**`/playground/response-headers`** sets every query argument as a response header, including
`content-type`. `status` and `delay` are read as knobs and never set as headers. A header
that would plant a cookie, open this origin to another site, or weaken what a browser
enforces here is refused with a 422: `set-cookie`, `strict-transport-security`,
`content-security-policy`, `x-frame-options` and the hop-by-hop headers.

**`/playground/auth`** accepts the basic pair `playground` / `playground`, or the bearer token
`playground-token`. Both are public constants printed here on purpose: they guard nothing and
unlock nothing but this route's 200. Without one it answers 401 with
`WWW-Authenticate: Basic realm="playground"`.

### Statuses that carry no body

A 204, a 304 and the 1xx range cannot carry a body, so a call that asks for one of them gets
the status and no reflection. Every other status carries the envelope.

### Reaching it from a pipeline

A step on the instance's own playground needs the instance's base URL and nothing else:

```yaml
steps:
  call:
    block: http.request
    config:
      url: http://127.0.0.1:3333/api/v1/playground/request
      method: GET
      query:
        station: bergen
```

A worker on the same host reaches `http://127.0.0.1:<port>`; a worker in a container reaches
the service name the compose network gives the API. Nothing about the call is special --
there is no token, no connection and no header.

## Turning it off

`DIRIGENT_PLAYGROUND_ENABLED=false`, or `playground_enabled: false` in the configuration
file. Off means the routes **are not mounted**: every playground path answers 404 and none of
them is in the OpenAPI document. The node is unaffected, because a block is not a route; an
instance that does not want it leaves it out of the documents it applies.

The routes are unauthenticated by design. An instance on a public address that has no use for
them should turn them off.
