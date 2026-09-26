# Playground examples

Documents that need something to *happen*, not something to call. `playground.generate` is a
node like any other: it takes an optional `input`, it emits an output, and it works at the
start of a flow, in the middle of one, or as its last step. It reaches nothing -- no
connection, no URL, no network, no file -- so a document here runs offline and runs the same
on every machine.

The knobs are what make it worth having. A fan-out needs a list to walk, a retry needs a step
that fails twice, a gate needs a shape that drifts, and an outputs-to-storage example needs a
payload over the threshold. Each of those is a knob rather than a contrivance:

| Knob | What it does |
| --- | --- |
| `fields` | Which Faker provider fills each output field. Any provider the installed Faker has. |
| `rows`, `locale`, `seed` | How many records, in which locale, from which seed. |
| `page`, `size` | Hand back one page of the records, and say how many pages there are. |
| `drift` | Emit a deliberately wrong shape: `strings`, `missing` or `extra`. |
| `payload` | Filler of a chosen size, to push an output past the inline limit. |
| `delay` | Take that long before answering, for a timeout or a deadline. |
| `fail_until` | Fail that many attempts before succeeding, for a retry. |
| `input` | A value from upstream to work from; absent, the knobs generate one. |

`playground.arrive` is the same generation behind a sensor's shape. Each poke answers "not
yet" until the wait the document configured is over, and the poke that ends it generates a
batch and hands it downstream as `messages`, each with an `offset` and a `value`. It reads
the same six generation knobs -- `fields`, `rows`, `locale`, `seed`, `drift`, `payload` --
and adds two of its own, `after_pokes` and `after`, which decide only when the parking stops.
Nothing has to be standing up for it, so a readiness wait is an offline example at last.

**Everything is seeded.** The same seed gives the same records on every run, which is what
lets a document here assert on what came out. With no seed the node draws one and reports it,
so a surprising answer can still be reproduced.

**The provider names are Faker's.** A reader cannot guess 280 of them, and a list pasted into
a page rots. `uv run faker` prints every provider the installed Faker offers with a sample of
each, and `uv run faker -l no_NO` prints them for one locale.

A document that is teaching HTTP itself -- a request with headers and a query, a status a
client has to handle, a redirect, a delay against a timeout, a body that arrives in pieces --
wants a real HTTP hop instead, and the instance serves one under `/api/v1/playground`. Those
routes generate nothing: a field map is Faker, Faker lives with the blocks, and the server
does not depend on a block package. The routes hand a consumer bytes arriving over time and
the blocks put generated data into a pipeline.

| File | What it demonstrates |
| --- | --- |
| [generated-rows.yaml](generated-rows.yaml) | The lead case: a first step with no input, a field map, a row count and a seed. |
| [retry-that-really-retries.yaml](retry-that-really-retries.yaml) | `fail_until` reads the engine's attempt number, so the step really fails twice and really recovers. |
| [a-gate-catching-drift.yaml](a-gate-catching-drift.yaml) | `drift` makes the shape wrong on demand, so `validate.schema` is seen refusing it. |
| [a-page-at-a-time.yaml](a-page-at-a-time.yaml) | `page`/`size` give a fan-out a real page to walk, and `payload` pushes the output out to storage. |
| [in-the-middle-of-a-flow.yaml](in-the-middle-of-a-flow.yaml) | The node with an `input` from upstream, and again as the document's last step. |
| [waiting-for-a-batch.yaml](waiting-for-a-batch.yaml) | `playground.arrive` parks for a few pokes, then hands over a batch in the shape a consumer reads. |
| [a-stream-to-read.yaml](a-stream-to-read.yaml) | The streaming route: NDJSON arriving over time, the envelope on the first line. Needs a running `dg dev`. |
