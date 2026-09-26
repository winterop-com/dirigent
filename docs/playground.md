# The playground

Three things an instance gives a document that needs something to happen instead of a service
to call: a **node** that generates data and behaviour in the run itself, a **sensor** that
makes the run wait for that data the way it waits for a queue, and a handful of **HTTP
routes** the instance serves to itself. All of them are always on, all of them are ours, and
none of them needs a network.

## Which one to reach for

**The node, `playground.generate`, is for a document that needs something to happen.** A
fan-out that needs a list to walk, a retry that needs a step that fails twice, a gate that
needs a shape that drifts, a storage example that needs a payload over the threshold. No
connection, no URL, no network, and it works at the start of a flow, in the middle of one, or
as its last step.

**The sensor, `playground.arrive`, is for a document that needs to wait for something.** A
readiness poke, a batch that turns up after a while, a step that has to be seen parking before
it is seen working. It is the node's generation behind a sensor's shape, so a document can
watch a pipeline tick without a broker, an endpoint or a file to poke.

**The routes are for a document that is teaching HTTP itself.** A request with headers and a
query, a status a client has to handle, a redirect, a delay against a timeout, a body that
arrives in pieces. Those documents want a real HTTP hop, and now they have one they own.

A document that wants rows should reach for the node. A document that wants to be seen waiting
should reach for the sensor. A document that wants to show `http.request` doing something
should reach for the routes.

**The routes generate nothing, and that is deliberate rather than an omission.** A field map is
Faker, Faker lives in the block family that contributes `playground.generate`, and
`dirigent-server` does not depend on a block package: blocks are a plugin surface, contributed
through pluginkit and run on workers, and a server-only install in a split deployment must not
have to carry the built-in block set to serve an API. So the split is along what each surface
is for -- the routes hand a consumer bytes arriving over time, and the blocks put generated
data into a pipeline, which is where the field map belongs.

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

### "Do it once, do it ten times"

`rows: 10` is one step run whose one output holds ten records. Ten *separate* units of work is
a different thing, and the engine already has a word for it: `for_each` on the step, which
fixes the cardinality when the run is created and gives each element its own attempt, its own
retry budget and its own row in the grid.

```yaml
steps:
  # One unit of work, ten records in its output.
  batch:
    block: playground.generate
    config:
      rows: 10

  # Ten units of work, each generating its own records.
  one_each:
    block: playground.generate
    for_each: ${params.stations}
    config:
      rows: 1
      fields:
        station: city
```

So there is no `mode` knob and there will not be one. "Do it once" is `rows: 1`, "do it ten
times" is `for_each`, and a knob that renamed either would put a block-local spelling beside
an engine semantic that is uniform across every block -- the same reason `poll`, `deadline`
and `retry` live on the step and never inside a block's config.

Streaming *through* the DAG is a third thing again, and it is not a knob on this node: a step
is the unit, and a step's unit is its whole output. The sensor below is the shape that works
on today's engine, and it is where a document that wants to watch a pipeline tick should go.

## The sensor

One block, `playground.arrive`, contributed by the same family. It is a **sensor**, so the
engine pokes it on a cadence instead of running it once: each poke is one cheap, read-only
question, the run holds no worker slot between pokes, and `poll`, `deadline` and `on_timeout`
are the step's own engine semantics exactly as they are for `storage.exists` or
`kafka.consume`.

The question it answers is "has the batch arrived yet". It answers no for as many pokes -- or
for as long -- as the document asks, and then one poke generates the batch and hands it
downstream.

```yaml
steps:
  wait_for_batch:
    block: playground.arrive
    poll: 1s
    deadline: 1m
    config:
      after_pokes: 2
      rows: 4
      seed: 42
      fields:
        station: city
        reading: pyfloat
```

```json
{
  "messages": [
    {"offset": 0, "value": {"station": "East Donald", "reading": 409.37}, "timestamp": "..."}
  ],
  "count": 4, "pokes": 3, "waited_ms": 2038,
  "seed": 42, "locale": "en_US",
  "fields": {"station": "city", "reading": "pyfloat"},
  "drift": "none", "payload": null, "payload_bytes": null
}
```

### The knobs

The six **generation** knobs are the node's, and they mean the same thing here: `fields`,
`rows`, `locale`, `seed`, `drift` and `payload`. `rows` is how many messages the batch holds.
A field map moved from one block to the other is unchanged, and the same seed gives the same
records on both.

Two knobs are the sensor's own, and they decide only when the parking stops:

| Knob | Default | What it does |
| --- | --- | --- |
| `after_pokes` | `1` | How many pokes park before the batch arrives. `0` lets the first poke carry it. |
| `after` | `0s` | How long the wait lasts, measured from when the attempt started. |

Both are floors, so the batch arrives on the first poke that has cleared them both. Set
neither and the default is one park and then the batch, which is the smallest thing that shows
a step waiting. The step's `deadline` still ends the wait either way; the sensor's own defaults
are a 2s poll and a 10 minute deadline.

### What one poke answers

A poke answers one of two things, and neither is a failure:

- **`NotYet`**, while the wait lasts. It carries the poke count forward in the **cursor**, the
  remaining time as `next_poll_in` when `after` is what is holding it back, a progress fraction
  read off whichever floor is furthest from being cleared, and a message -- `poke 1 of 3`, or
  `1400ms of the wait left` -- that shows on the waiting attempt.
- **The batch**, on the poke that clears both floors. Nothing is generated before that poke, so
  a park costs a comparison and not a field map.

**The poke count lives in the cursor and nowhere else**, which is what makes the wait durable
across a worker restart. A cursor is at-least-once: a worker that dies between a park and the
transaction that commits it leaves the older count for the next poke to read, so the sensor
parks one poke longer rather than arriving early.

### The consume shape

The output is shaped the way a queue consumer's is on purpose. `messages` with an `offset` and
a `value` each, and `count` beside them, is what `kafka.consume` hands downstream, so a
document written against the playground reads almost unchanged against a real topic once there
is one to point it at.

What it does not have is what the playground has nothing to put in: no topic, no partition, no
key, no headers, and no broker offsets to commit. `timestamp` is when the batch arrived.

### A readiness wait, offline

`http.ready` needs a live endpoint to poke, so a document teaching a readiness wait could not
be an offline example and could not be verified by `dg run --local`. `playground.arrive`
answers "not yet, ask again" against no broker, no URL and no file, so that document can exist
now:
[`examples/playground/waiting-for-a-batch.yaml`](https://github.com/winterop-com/dirigent/tree/main/examples/playground/waiting-for-a-batch.yaml).

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
| `/playground/stream` | GET | Sends a stream of messages instead of one body. |

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

### A body that arrives in pieces

**`/playground/stream`** is the one route whose answer does not arrive whole, for a consumer
that has to be tested against bytes that turn up over time rather than a body that is already
there. It takes `messages` (up to 100, default 5), `every` (the gap before each message, up to
10s, default `1s`) and `payload` (filler of a chosen size on every message, the same filler the
node's `payload` returns at the same size).

It is **NDJSON**, `application/x-ndjson`: one JSON record per line, each carrying a `kind`,
which is the shape everything this project emits already has. Server-sent events were the other
candidate and were not chosen -- `event:` would be a second framing vocabulary beside the `kind`
this project already dispatches on, and the consumers that meet this route are `curl | jq -c`, a
client library and `http.request`, none of which speaks `EventSource`. The instance's own SSE
lives on `/runs/{id}/$logs` and `/runs/{id}/$events`, where the consumer *is* a browser.

**The envelope goes out once, on the first line.** A stream has one set of headers and many
bodies, so the request facts cannot ride on every message the way they ride on every other
playground answer. The first line is the envelope, the lines after it carry only what changes,
and the last line says the stream ended -- which is how a reader tells an ending from a cut
connection.

```console
$ curl -N 'http://127.0.0.1:3333/api/v1/playground/stream?messages=3&every=100ms'
{"kind":"stream","request":{...},"messages":3,"gap_ms":100,"payload_bytes":null}
{"kind":"stream.message","offset":0,"sent_at":"...","elapsed_ms":101,"payload":null}
{"kind":"stream.message","offset":1,"sent_at":"...","elapsed_ms":202,"payload":null}
{"kind":"stream.message","offset":2,"sent_at":"...","elapsed_ms":303,"payload":null}
{"kind":"stream.closed","messages":3,"duration_ms":303}
```

The messages carry no generated records, for the reason at the top of this page: a field map is
Faker and the server does not depend on a block package. `playground.arrive` is where generated
data arrives over time inside a pipeline.

The count and the gap multiply, so each one being inside its own bound is not enough: a stream
that would hold the connection open longer than 60 seconds is refused with a 422. The route
also sets `cache-control: no-cache` and `x-accel-buffering: no`, because a stream a proxy holds
until it is whole is not a stream.

**Inside a DAG a step reads the whole of it.** `http.request` reads a bounded body and hands it
on, so a step waits for the last line and then gets all of them at once, as text -- NDJSON is
not JSON. The lines are still the value, and `transform.jq` splits them:
[`examples/playground/a-stream-to-read.yaml`](https://github.com/winterop-com/dirigent/tree/main/examples/playground/a-stream-to-read.yaml).

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
