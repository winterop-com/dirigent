# Report documents

A run can write its own account of itself. Declare a `report:` section in a pipeline document
and every run of it renders one markdown document when it settles -- succeeded, failed,
completed with errors, or cancelled -- stored with the run and read back over the API and the
CLI.

The document is the engine's, not a step's. A step cannot run when a run is cancelled or a
worker dies, and those are the runs whose report is worth the most, so the rendering happens
in the transaction that settles the run.

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

## What a template may read

The context is the run's facts, the same ones `dg runs report` summarises.

| Name | What it is |
| --- | --- |
| `run.id` | The run's uuid, as a string |
| `run.status` | `succeeded`, `failed`, `completed_with_errors`, or `cancelled` |
| `run.pipeline` | The pipeline's code |
| `run.error` | Why it ended badly, or a cancellation's reason; null otherwise |
| `run.params` | The parameters the run resolved to |
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

A name the facts do not have renders as empty rather than failing the document. Half a run's
facts are legitimately null depending on how it ended, so a template reading `run.error` on a
run that succeeded prints nothing and carries on.

## The bounds

A template renders in an immutable sandbox with no loader, so it cannot reach an object's
internals, mutate what it was handed, or pull in another template: `include`, `import` and
`extends` all fail. `range` is capped by the sandbox, the text is cut at
`DIRIGENT_REPORT_MAX_SIZE` (1mb) as it is generated rather than after it is built, and the
whole render is bounded by `DIRIGENT_REPORT_RENDER_TIMEOUT` (5s).

Every one of those is a warning, never a failure. A template that overflows, times out, or
reaches for something refused leaves `the run's report was not rendered` in the run's own
timeline, with the reason in the entry's fields, and the run's status is exactly what it
would have been. A report is never worth the run it describes.

## Sending a report somewhere

A page a pipeline writes for somebody else is a step: `report.render` renders text from a
Jinja template over the values it is given and hands that text on, and the step after it is
what sends it anywhere -- a value travels through step outputs, `storage.write` is the only
way one leaves the run and `storage.read` the only way one comes back in.

| Example | Where the page goes |
| --- | --- |
| [recipes/report-to-file.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/recipes/report-to-file.yaml) | A file under the run's scratch prefix, read back and logged with `log.write` |
| [s3/report-to-s3.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/s3/report-to-s3.yaml) | An object in a bucket, its content type stored with it |
| [queues/report-to-kafka.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues/report-to-kafka.yaml) | One keyed record on a Kafka topic |
| [queues/report-to-rabbitmq.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues/report-to-rabbitmq.yaml) | One message on a RabbitMQ queue, through the default exchange |
| [recipes/report-to-webhook.yaml](https://github.com/winterop-com/dirigent/blob/main/packages/dirigent-examples/src/dirigent_examples/shelves/recipes/report-to-webhook.yaml) | A receiver, as one field of a webhook body |

The block's own bounds are its own: `max_size` (1mb by default) cuts the text as it is
generated, and a template that overflows or fails to render fails the step as `rejected`
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

One document per run, rewritten in place when a retry reopens a settled run and it settles
again, so a link an alert already carries keeps resolving. A small document inlines on the
row; a larger one goes to the run's scratch prefix as `report.md` and is swept with the run
once `DIRIGENT_RETENTION_RUNS` is set.

## The same context, in an alert

An alert rule reads these facts too. Its `template` is the subject and its `body` is the body,
both Jinja over this context plus one more name: `report`, the run's rendered report document
when it has one, so a rule can carry the whole page rather than a link to it.

```bash
dg alerts rules create nightly-failed --event run_failed --notifier slack \
  --template '{{ pipeline.code }} failed at {{ step.load.step }}' \
  --body-file alert-body.md.j2
```

A rule with no `template` gets `{{ run.pipeline }} run {{ run.status }}`; a rule with no `body`
gets the run's own facts, one per line. A subject is collapsed to one line and cut at 200
characters, because that is what a subject is. Both templates are compiled when the rule is
created, so a syntax error is refused there; a render that fails when the alert is raised falls
back to the default and leaves a warning in the run's timeline, because an alert is the last
thing standing between a failure and the person who needs to know.

What the channel does with a body: Slack clips it at 3000 characters, and email sends it as
plain text. Markdown in a body reaches Slack as mrkdwn and an inbox as the characters you
wrote.
