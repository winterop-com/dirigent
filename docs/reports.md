# Report documents

A run can write its own account of itself. Declare a `report:` section in a pipeline document
and every run of it renders one markdown document when it settles -- succeeded, failed,
completed with errors, or cancelled -- stored with the run and read back over the API and the
CLI.

The document is the engine's, not a step's. A step cannot run when a run is cancelled or a
worker dies, and those are the runs whose report is worth the most, so the transaction that
settles the run writes down that it owes its document. The document is rendered and stored as
soon as that transaction has committed -- by the worker that settled the run, or by the server
before it answers a cancel -- never inside it, so no template runs while the run's lock is held. A worker that dies mid-render leaves the document owed, and another takes it over
once the first has held it for `DIRIGENT_REPORT_RENDER_TIMEOUT` and 30 seconds more.

## Asking for one

```yaml
report: {}
```

That is the whole of it: an empty section renders the built-in document. It is a title, the
run's own facts, a table of what each step amounted to, the items that failed when any did,
and the run's error when it has one.

Bring your own instead:

```yaml
report:
  template: |
    # {{ pipeline.code }} on {{ run.window_start | iso }}

    {{ run.status }} in {{ run.duration_ms | duration }}, {{ items_failed }} of
    {{ items_total }} items failed.

    {% for step in steps %}
    - **{{ step.step }}** {{ step.outcome }} after {{ step.attempts }} attempts
    {% endfor %}
```

A document with no `report:` section renders nothing at all. The template is a
[Jinja](https://jinja.palletsprojects.com/) template, compiled when the document is applied,
so a syntax error is refused at `report.template` rather than at the first settlement.

Or take a step's text as it is:

```yaml
report: {from: summary}

steps:
  summary:
    block: report.render
    config:
      template: "# {{ title }}"
      values: {title: Weekly}
```

`from` names a step whose output carries a `text` string -- a `report.render` step, or any
block whose output schema declares one -- and that text, rendered no further, is the run's
document. It takes no template, and a section with both is refused. Plan and validate refuse a
`from` naming no step, a source or a reply, or a block whose output has no `text`; a step that
did not succeed, or handed on no text, leaves a warning in the run's timeline and no document,
as a template that fails does.

`report.render` alone does not set the run's report: its text is the step's output, and the
Report tab draws what `report:` renders. Plan and `dg validate` warn about a `report.render`
step in a document with no `report:` section and name the `report: {from: <step>}` that would
make it the run's report, and a run of one offers the step's text on its Report tab beside the
summary.

## What plan and validate check in a template

A name the facts do not have renders empty, so a typo is silent at the run. Plan and
`dg validate` read the names a template reaches for and warn, as
`document.template_name_unknown`, about any its context does not have: an unknown top-level
name, a field of `run` or `pipeline` that is not one, `step.<name>` for a step the document
does not declare, and `params.<name>` for a parameter its schema does not list. A
`report.render` template is checked against the keys of its literal `values`. A read of
`step.<name>.output.<field>` whose block publishes a closed output schema without that field
is warned about as `document.output_field_unknown`, naming the fields the output does have;
a read into an open value, a mapping or a list is not judged. A warning never refuses the
document, and the render stays as lenient as it was.

## What a template may read

The context is the run's facts, the same ones `dg runs report` summarises.

| Name | What it is |
| --- | --- |
| `run.id` | The run's uuid, as a string |
| `run.status` | `succeeded`, `failed`, `completed_with_errors`, or `cancelled` |
| `run.pipeline` | The pipeline's code |
| `run.error` | Why it ended badly: for a run that failed or completed with errors, what failed, the same line as an alert's `error`; a cancellation's reason; null otherwise |
| `run.error_code` / `run.error_params` | The dotted code of that refusal and the specifics it rendered, when it has them |
| `run.failed_step` | The first step that failed, for a run that failed or completed with errors; null otherwise |
| `params` | The parameters the run resolved to, defaults filled in, so `{{ params.period }}` reads one |
| `run.params` | The same parameters, under the run |
| `run.trigger` | The trigger's label, or its kind when it has no label |
| `run.started_at` / `run.finished_at` | ISO 8601 moments, or null |
| `run.duration_ms` | Milliseconds from start to finish, or null |
| `run.window_start` / `run.window_end` | The data window, for a run that has one |
| `run.trace_id` | The trace this run is one span of, for a jump into the traces |
| `run.url` | The run in the web UI, when `DIRIGENT_ALERT_BASE_URL` is set |
| `run.report_url` | Where this document is read, once it is stored |
| `pipeline.code` / `pipeline.name` / `pipeline.version` | The pipeline version the run pinned |
| `steps[]` | `step`, `block`, `outcome`, `attempts`, `depends_on`, `warnings`, `duration_ms`, `error`, `output`, `output_uri`, `output_bytes`, in the order a person watched them |
| `step.<name>` | The same facts by name, so `step.summary.output.value` reads one hop without walking the list |
| `items[]` | `index`, `key`, `status`, `failing_step`, `error`, for each element of a fan-out |
| `items_total` / `items_failed` | How many elements there were, and how many of them failed |
| `url` | The run in the web UI, the same as `run.url` |
| `rendered_at` | When the text was rendered: the moment the run settled, or the moment a route was asked |

Three filters render a value the way a person reads it:

| Filter | Takes | Renders |
| --- | --- | --- |
| `duration` | milliseconds | `1m30s` |
| `bytes` | bytes | `1.5mb` |
| `iso` | a moment | `2026-01-01T05:00:00+00:00` |

`output` is the step's last attempt's value, and `output_bytes` is how large that value was
stored -- the artifact row's size where the attempt has one, else the length of the canonical
JSON -- so `{{ step.load.output_bytes | bytes }}` reads `1.5mb`. Both are null for a step that
never ran, which is why a template guards on the step before reading into it.

A value prints the way JSON reads it rather than the way Python does: a list or an object as
its compact JSON, a boolean as `true` or `false`, and null as nothing. `{{ step.fetch.output |
tojson(indent=2) }}` prints the same value indented, for a block a person reads.

A name the facts do not have renders as empty rather than failing the document. Half a run's
facts are legitimately null depending on how it ended, so a template reading `run.error` on a
run that succeeded prints nothing and carries on.

## The bounds

A template renders in an immutable sandbox with no loader, so it cannot reach an object's
internals, mutate what it was handed, or pull in another template: `include`, `import` and
`extends` all fail. The text is cut at `DIRIGENT_REPORT_MAX_SIZE` (1mb) as it is generated
rather than after it is built, and the render runs off the event loop and stops itself when it
reaches any of these limits, which every template -- a report, an alert's subject and body,
`report.render` -- renders under:

| Limit | What reaches it |
| --- | --- |
| Time: `DIRIGENT_REPORT_RENDER_TIMEOUT` (5s) for a run's report and an alert, 5s for `report.render` | A render still going when the time is up |
| 1,000,000 steps | Loop passes, calls and filters together: three nested `range(1000)` loops are a billion, and stop |
| 100,000 items in one `range` | `range(1000000)` |
| One value: 1,048,576 characters or items, or the text cap when that is larger | `'x' * 10000000`, a `~` or `+` that keeps doubling, `center(10000000)`, a `replace`, `join` or `indent` that would build past it, a list that would print past it |
| All values together: 32 times the one-value limit | Building many large values in a loop |
| One number: 4,096 bits | `3 ** 30000000`, a product of two huge numbers |
| A width from the arguments | `'%*d' % (n, x)` and `'{:{w}}'.format(...)`: write the width into the format |
| `sum` adds numbers | `sum(start=[])` to flatten lists |

`lipsum` is not there. Nothing in a template is computed when it is compiled -- an operator or a
filter runs at render, under these limits -- so applying a document costs no more than reading
its templates.

Every one of those is a warning, never a failure. A template that overflows, times out, or
reaches for something refused leaves `the run's report was not rendered` in the run's own
timeline, with the reason in the entry's fields, and the run's status is exactly what it
would have been. A report is never worth the run it describes.

## Sending a report somewhere

A page a pipeline writes for somebody else is a step: `report.render` renders text from a
Jinja template over the values it is given and hands that text on as its output's `text`,
`content_type` and `text_bytes`. It saves nothing itself, so the step after it is what sends
the page anywhere -- `storage.write`, `kafka.produce`, `rabbitmq.publish` or `webhook.post`,
each reading `${steps.<render>.output.text}`.

A value reaches the template through `values`, under a name the template reads. A `${...}` in
`template` itself is refused when the document is applied and when the step starts, because text a
value put there would be template source. `$${...}` stays the literal text `${...}`.

| Example | Where the page goes |
| --- | --- |
| [recipes/report-to-file.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/recipes/report-to-file.yaml) | A file under the run's scratch prefix, read back and logged with `log.write` |
| [s3/report-to-s3.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/s3/report-to-s3.yaml) | An object in a bucket, its content type stored with it |
| [queues/report-to-kafka.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues/report-to-kafka.yaml) | One keyed record on a Kafka topic |
| [queues/report-to-rabbitmq.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues/report-to-rabbitmq.yaml) | One message on a RabbitMQ queue, through the default exchange |
| [recipes/report-to-webhook.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/recipes/report-to-webhook.yaml) | A receiver, as one field of a webhook body |

The block's own bounds are its own: `max_size` (1mb by default) cuts the text as it is
generated, the render is held to [the same limits](#the-bounds) with 5s of time, a step
`timeout` stops a render in flight, and a template that overflows, reaches a limit or fails to
render fails the step as `rejected`
rather than leaving a warning -- a step that was asked for a page and produced none has
produced nothing for the step below it.

## Reading one

```bash
dg runs report RUN_ID --markdown
```

The document is written as-is, so it pipes into a file or a ticket. The command says so when
the run rendered none. Under `--json`, or into a pipe, it is one `run.report_document` record
carrying the whole document.

Over the API the document is a run-level artifact: `step_name` null, content type
`text/markdown`.

```text
GET /api/v1/runs/{id}/artifacts     # what the run wrote down, the report among it
GET /api/v1/artifacts/{id}          # one artifact's content, in its own content type
```

An alert about the run names it too. `run.report_url` is the artifact route, filled in when
`DIRIGENT_ALERT_BASE_URL` tells the instance its own address and the run rendered a document.
The alerts a run's settling raises wait for its document to be stored, so they carry the link
and, for a rule with a template, the document itself; a document that did not render releases
them without one.

One document per run, rewritten in place when a retry reopens a settled run and it settles
again, so a link an alert already carries keeps resolving. A small document inlines on the
row; a larger one goes to the run's scratch prefix as `report.md` and is swept with the run
once `DIRIGENT_RETENTION_RUNS` is set.

## The same context, in an alert

An alert rule reads these facts too. Its `template` is the subject and its `body` is the body,
both Jinja over this context plus the names that say where a failing run went wrong. These are
every name an alert template is given:

| Name | What it is |
| --- | --- |
| `run` | The run: `id`, `status`, `pipeline`, `error`, `error_code`, `error_params`, `failed_step`, `params`, `trigger`, `started_at`, `finished_at`, `duration_ms`, `window_start`, `window_end`, `trace_id`, `url`, `report_url`, as in the table above |
| `pipeline` | `code`, `name` and `version` of the pipeline version the run pinned |
| `params` | The parameters the run resolved to |
| `steps` / `step` | Each step's facts in order, and the same by name. A step's `output` is there when it is no larger than `DIRIGENT_INLINE_ARTIFACT_MAX` (16384 bytes), the size the engine stores inline; a larger one is null, named by its `output_uri` and `output_bytes` |
| `items` / `items_total` / `items_failed` | The fan-out elements, how many there were, and how many failed |
| `url` | The run in the web UI, the same as `run.url` |
| `rendered_at` | When the alert was raised |
| `failing_step` | The first step that failed, for a run that failed or completed with errors; null otherwise. The same as `run.failed_step` |
| `failing_item` | The key of the first fan-out element that failed in that step, when an element failed |
| `error` | What failed, on one line and cut at 300 characters: the element's refusal, else the step's, else the run's own. For a block that raised something it did not explain, it is what the block raised. It is read from the attempt as stored, already scrubbed of the step's secrets. The same as `run.error` |
| `error_code` | The dotted code of that refusal, when it has one. The same as `run.error_code` |
| `report` | The run's rendered report document when it has one, so a rule can carry the whole page rather than a link to it |

A rule whose `template` or `body` reads a name outside this table, or a field of `run` or
`pipeline` that is not one, is still created or changed, and the answer carries a
`warnings` entry for each such name, as `alert.template_name_unknown`, listing what is
given instead. The rule's reads carry the same `warnings`, so a rule written before the check
says so too.

```bash
dg alerts rules create nightly-failed --event run_failed --connection ops-slack \
  --template '{{ pipeline.code }} failed at {{ failing_step }}' \
  --body-file alert-body.md.j2
```

A rule with no `template` gets `{{ run.pipeline }} run {{ run.status }}`. A rule with no `body`
gets a few short lines: how the run ended, with the failing step, the element and the error,
then who triggered it and how long it ran, the parameters as JSON when it had any, the data
window, when it started and finished, and the link to the run -- or its id, when
`DIRIGENT_ALERT_BASE_URL` is unset.

```text
Failed at step slow: RuntimeError: Illegal header value b'Bearer ***'
Triggered by agent (token mcp-trial), ran for 1s22ms.
Params: {"delay": "1s"}
Started 2026-11-03T11:16:57.851899+00:00, finished 2026-11-03T11:16:58.873724+00:00.
Run: https://dirigent.example.org/runs/01a1a120-...
```

A subject is collapsed to one line and cut at 200 characters, because that is what a subject is. Both templates are compiled when the rule is
created, so a syntax error is refused there. They render when the alert is delivered, on the
worker that delivers it and under [the same limits](#the-bounds) as a report, never in the
transaction that settles the run: the notification carries the facts as they were when the run
settled, and the report document until it renders. The facts are read only for a rule that is
due to raise, so a run whose rules already spoke, or are inside their throttle, pays for none. A render that fails or reaches a limit falls
back to the default and leaves a warning in the run's timeline, because an alert is the last
thing standing between a failure and the person who needs to know. Until it is delivered, a
queued notification lists the default subject. `dg alerts test` renders the same way, at
delivery, and sends text that does not render as it was typed. An alert is never paid for
by the run it reports on: whatever fails while one is being written down is logged and the
alert is dropped, and the outcome that raised it stays settled.

What the channel does with a body: Slack clips it at 3000 characters, and email sends it as
plain text. Markdown in a body reaches Slack as mrkdwn and an inbox as the characters you
wrote.
