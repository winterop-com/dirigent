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
| `steps[]` | `step`, `block`, `outcome`, `attempts`, `depends_on`, `warnings`, `duration_ms`, `error`, `output`, `output_uri` |
| `items[]` | `index`, `key`, `status`, `failing_step`, `error`, for each element of a fan-out |
| `items_total` / `items_failed` | How many elements there were, and how many of them failed |
| `url` | The run in the web UI, the same as `run.url` |

Three filters render a value the way a person reads it:

| Filter | Takes | Renders |
| --- | --- | --- |
| `duration` | milliseconds | `1m30s` |
| `bytes` | bytes | `1.5mb` |
| `iso` | a moment | `2026-01-01T05:00:00+00:00` |

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
