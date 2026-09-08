# Driving dirigent from Python

`dirigent-client` is the typed async SDK. It is the same package the CLI runs on, and it owns
the request and response schemas the server imports, so a shape the client parses is the shape
the server writes -- there is one definition of each, and it cannot drift.

```bash
uv add dirigent-client        # or: uv pip install dirigent-client
```

The package depends on `httpx2`, `pydantic`, `pyyaml`, and `dirigent-common`, and on nothing
else in the workspace. Installing it does not install the engine or the server.

## The four lines

```python
from datetime import timedelta

from dirigent_client import Dirigent

async with Dirigent(url=DG_URL, token=DG_TOKEN) as dg:
    plan = await dg.pipelines.apply(document, dry_run=True)
    run = await dg.pipelines.run("daily-climate-load", params={"day": "2026-08-29"})
    final = await dg.runs.wait(run.run_id, timeout=timedelta(hours=2))
    async for entry in dg.runs.follow_logs(run.run_id):
        print(entry.message)
```

`document` is whatever you have: a parsed mapping, a `Path`, or the YAML text itself.

## Authenticating

Every route under `/api/v1` requires a principal. For a program, that is an API token:

```python
import os

from dirigent_client import Dirigent

dg = Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"])
```

Mint the token with `dg admin token create ci` or `await dg.admin.tokens.create("ci")`; it is
shown once. An admin mints one for somebody else with
`await dg.admin.users.create_token("ci-bot", "ci")`. See [the token lifecycle](security.md#token-lifecycle).

A browser has a second option -- `dg.auth.login(username, password)` sets an http-only
`dirigent_session` cookie, good for fourteen days. It exists for the UI. A program should hold
a token: it can be named, listed, and revoked by name, and a run it starts is attributed to
the token as well as to the user. When both a header and a cookie are present, the header wins.

The client takes a URL and a token and nothing else. Profiles, `DG_URL`, `DG_TOKEN`, and
`~/.config/dirigent/profiles.yaml` are the CLI's business; a program decides for itself where
its credentials come from.

## The accessors

One per API resource, and the method names are the CLI's verbs.

| Accessor | What it reaches |
| --- | --- |
| `dg.pipelines` | `list`, `get`, `apply`, `prune`, `versions`, `export`, `validate`, `activate`, `deactivate`, `delete`, `run`, `backfill` |
| `dg.runs` | `list`, `get`, `items`, `attempts`, `cancel`, `retry`, `logs`, `report`, `wait`, `follow_logs`, `events` |
| `dg.schedules` | `list`, `get`, `create`, `update`, `pause`, `resume`, `firings`, `delete` |
| `dg.webhooks` | `list`, `get`, `create`, `rotate_token`, `enable`, `disable`, `deliveries`, `delete` |
| `dg.trigger_documents` | `list`, `get`, `delete` |
| `dg.alerts` | `rules`, `create_rule`, `delete_rule`, `test`, `notifications` |
| `dg.connections` | `list`, `get`, `create`, `update`, `delete`, `check` |
| `dg.schemas` | `list`, `get`, `create`, `update`, `delete` |
| `dg.blocks` | `catalog`, `get` |
| `dg.workers` | `list` |
| `dg.system` | `info`, `health`, `ready` |
| `dg.auth` | `login`, `logout`, `whoami`, `change_password` |
| `dg.admin` | `users.list`, `users.create`, `users.update`, `users.deactivate`, `users.activate`, `tokens.list`, `tokens.create`, `tokens.revoke` |

Anything addressable is addressed by its `code`, which is the first positional argument
wherever one is taken: `dg.pipelines.get("daily-load")`,
`dg.connections.create("modelling-api", kind="http", ...)`,
`dg.schedules.create("daily-load", "nightly", ...)`. The human `name` and the `description`
are keyword arguments on every `create` and `update` that has them, and `apply` takes
`code=` to register a document under a code other than its own.

Every one of them returns a pydantic model from `dirigent_client`: `PipelineOut`, `RunDetail`,
`ApplyResult`, `Catalog`, and so on. They are importable from the top level, and
`model_dump(mode="json")` renders any of them back into the JSON the server sent.

## Pages

Every listing answers a `Page`: `items`, and a `next` cursor that is `None` at the end.

```python
page = await dg.runs.list(limit=100)
while True:
    for run in page.items:
        print(run.id, run.status.value)
    if page.next is None:
        break
    page = await dg.runs.list(limit=100, after=page.next)
```

`after` is opaque -- pass back what `next` gave you and nothing else. `limit` runs from 1 to
500 and defaults to 50. Selection is keyset rather than offset, so a run started between two
pages neither pushes a row off the end nor arrives twice.

## Applying and running

`apply` takes a whole `dirigent/v1` document and either reports a plan or commits a version:

```python
result = await dg.pipelines.apply("pipelines/daily-load.yaml", dry_run=True)
if not result.plan.ok:
    for issue in result.plan.issues:
        print(f"{issue.location}: {issue.message}")
```

**A document this instance cannot run comes back as a `200` with `action == "invalid"`, not as
a refusal**, because the plan is the answer. `result.plan.ok` is the check; the other three
actions are `create`, `update`, and `unchanged`. `unchanged` means the digest matched and
nothing was written, which is what makes applying a whole repository on every merge idempotent.

Starting a run has a second non-error outcome:

```python
accepted = await dg.pipelines.run("daily-load", params={"day": "2026-08-29"})
if accepted.run_id is None:
    print(accepted.detail)  # the concurrency policy declined a second concurrent run
```

`runs.wait` polls until the run reaches a status nothing will move it out of, widening the
interval while the run has nothing to say, and raises `WaitTimeout` when the budget runs out.
It never cancels the run; `runs.cancel` is a separate decision.

## Error handling

Every refusal is a `DirigentError` carrying `status`, `url`, and the parsed `problem`:

| Exception | When |
| --- | --- |
| `Unauthorized` | 401: no credential, or one this instance does not accept |
| `Forbidden` | 403: the credential is valid and does not permit this |
| `NotFound` | 404: this instance holds no such thing |
| `Conflict` | 409: the current state does not allow it |
| `ValidationFailed` | 422: the content was refused, field by field, in `problems` |
| `RateLimited` | 429: refused for now; `retry_after` when the server said how long |
| `ServerError` | 5xx: the instance failed; its own log has the detail |
| `TransportError` | Nothing answered at that URL |
| `NotDirigent` | Something answered, and it was not a dirigent instance |
| `WaitTimeout` | `runs.wait` gave up; the run was left alone |

```python
from dirigent_client import NotFound, ValidationFailed

try:
    await dg.pipelines.run("daily-load", params=params)
except ValidationFailed as refusal:
    for problem in refusal.problems:
        print(problem)
except NotFound as refusal:
    print(refusal.message)
```

`NotDirigent` is worth handling separately: nothing is wrong with the request, the URL is
pointing at the wrong thing. The client decides it by the absence of `X-Dirigent-Version`,
which a dirigent instance puts on every response, errors included.

Retries are automatic and narrow: a transport failure or a 5xx is retried with exponential
backoff, and only for idempotent methods. A `POST` or a `PATCH` is never repeated, because it
may have taken effect before the connection broke, and a repeat would mean a second run, a
second token, a second account.

## Streaming logs

```python
async for entry in dg.runs.follow_logs(run_id, step="load"):
    print(f"{entry.level.value:<7} {entry.step_name or '-':<12} {entry.message}")
```

The tail is server-sent events, and the server closes one two ways. `end` means the run is
terminal and there is nothing more to read. `expired` means the stream reached the server's
wall-clock limit with the run still going: the client reopens it from the id of the last entry
it yielded and keeps going, so following a run for a day is the same call as following one for
a minute. A stream that closes saying neither was cut -- a proxy's idle timeout, a restarted
server -- and is reopened the same way, which is why a reconnection neither loses a line nor
repeats one. `reconnects=` bounds how many cut streams and transport failures it will absorb;
an expiry is not one of them, and an entry delivered restores the budget in full.

For a page rather than a stream, `runs.logs` takes `after`, `limit`, and `step`, and answers
the same `Page` every other listing does. `next` is null when there was nothing past this page,
which is the only end condition: a run still being written to will have more later.

## Following a whole run

```python
async for event in dg.runs.events(run_id):
    match event:
        case AttemptEvent():
            print(f"{event.step_name} {event.item or '':<10} {event.status.value}")
        case LogEntryOut():
            print(f"  {event.message}")
        case RunOut():
            print(f"run {event.status.value}")
```

`runs.events` is one stream carrying three things in the order they happened: an `AttemptEvent`
for every state an attempt reaches, a `LogEntryOut` for every line, and one `RunOut` when the
run settles, which is the last thing sent before `end`. `expired` and a cut stream are reopened
here exactly as they are for a log tail. Every attempt is replayed in its current state when
the stream opens and again after a reconnection, so a consumer keys on what it has already seen
rather than on how many times it read it; the log cursor resumes where it left off, so a line
is never repeated. An `AttemptEvent` is an `AttemptOut` plus `item`, the element a fan-out
attempt ran for, so nothing has to read the run's item grid to label a line.

## A CI gate

Apply a document and run it, exiting non-zero when the run does not succeed:

```python
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from dirigent_client import Dirigent, PlanAction, RunStatus, WaitTimeout


async def gate(document: Path) -> int:
    """Apply, run, wait, and report; the return value is the job's exit code."""
    async with Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"]) as dg:
        applied = await dg.pipelines.apply(document)
        if applied.plan.action is PlanAction.INVALID:
            for issue in applied.plan.issues:
                print(f"::error::{issue}")
            return 1

        accepted = await dg.pipelines.run(applied.plan.code)
        if accepted.run_id is None:
            print(f"::warning::not started: {accepted.detail}")
            return 0

        try:
            run = await dg.runs.wait(accepted.run_id, timeout=timedelta(hours=2))
        except WaitTimeout as timed_out:
            print(f"::error::{timed_out.message}")
            return 1

        for step in (await dg.runs.report(run.id)).steps:
            print(f"  {step.outcome:<10} {step.step:<24} {step.error or ''}")
        if run.status is RunStatus.SUCCEEDED:
            return 0
        print(f"::error::run {run.id} {run.status.value}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(gate(Path(sys.argv[1]))))
```

```yaml
- run: uv run python ci_gate.py pipelines/daily-load.yaml
  env:
    DG_URL: ${{ vars.DG_URL }}
    DG_TOKEN: ${{ secrets.DG_TOKEN }}
```

Note the two outcomes that are not failures: a `skipped` run means the pipeline's concurrency
policy declined to start a second one, and `completed_with_errors` means a step failed inside
a `continue`-ruled branch. Deciding which of those a build should fail on is the gate's job,
not the API's.

`RunStatus.COMPLETED_WITH_ERRORS` is deliberately not in the accepted set above. The CLI makes
the same distinction with `--strict`.

## More worked examples

`examples/python/` holds six runnable scripts -- apply-and-run, log following, filtering,
connections, error handling, and the CI gate -- each a single file with the command that runs
it in its header. They are executed against a real instance in CI, so they cannot rot.

## Synchronous callers

The SDK is async. There is no second set of synchronous methods, because that would mean two
definitions of every signature to keep in step. What there is instead is a bridge:

```python
from dirigent_client import BlockingDirigent

with BlockingDirigent(url=DG_URL, token=DG_TOKEN) as dg:
    pipelines = dg.call(dg.pipelines.list())
    for entry in dg.iterate(dg.runs.follow_logs(run_id)):
        print(entry.message)
```

`call` runs one of the async accessors' coroutines on a private event loop in a background
thread and hands back the result; `iterate` does the same for an async iterator. The
accessors are the same objects, so nothing is duplicated. This is what `dg` itself uses.

## Testing a block

`dirigent-testing` is the other package written for people outside this repository. It is a
pytest plugin, so installing it is the whole setup -- the fixtures arrive by entry point and
no conftest has to re-export anything.

```bash
uv add --dev dirigent-testing
```

```python
from dirigent_testing import call_block


async def test_it_greets(block_ctx):
    output = await call_block(Greet(), {"name": "ada"}, block_ctx)

    assert output.greeting == "hello ada"
    assert block_ctx.log.messages() == ["greeting"]
```

`call_block` validates the config against the block's own `config_model` first, the way the
engine does, and then makes the block's first call: an operator's `execute` or a sensor's
`poke`. `block_ctx` is a `FakeContext` -- a recording logger, real storage over a temporary
directory, an HTTP client built on a handler the test installs, and an in-memory runs facade.
`defaults_only_environment` is the fixture that takes `DIRIGENT_*`, `DG_*` and `OTEL_*` out of
one test's environment; request it from your own conftest to run a suite against defaults.

A block's contract has one more method worth testing directly. `check_config(config)` returns
the extra refusals the block makes at apply, beyond what its schema already says -- a program
that does not compile, a format pair it cannot convert between -- as a list of strings. It
defaults to returning nothing, so a block that has no such refusals implements nothing. The
instance calls it while applying a document, against the step's validated config, and shows
each string as an issue at `steps.<name>.config`, which is why it is worth an assertion of
its own:

```python
def test_it_refuses_a_program_it_cannot_compile():
    config = Recase.config_model.model_validate({"input": "ada", "program": "sideways"})

    assert Recase().check_config(config) == ["'sideways' is not a case: write upper or lower"]
```

The transform frames build on exactly this, and [the transform page](transforms.md) is where
writing an engine is taught.

## The REST API is still there

Nothing about the SDK closes off plain HTTP. `/api/v1` is the stable surface, `/openapi.json`
is its complete reference and is unauthenticated, and `/docs` renders it. Every operation
carries a stable `operation_id` -- `applyPipeline`, `runPipeline`, `getRun`, `getRunLogs` --
so a generated client does not rename everything when an unrelated route is added:

```bash
curl -sO "$DG_URL/openapi.json"
uvx openapi-python-client generate --path openapi.json
```

Two things worth knowing if you go that way. Every error response has one shape:

```json
{
  "status": 422,
  "title": "Unprocessable Content",
  "detail": "params.day: Input should be a valid string",
  "problems": ["params.day: Input should be a valid string"],
  "instance": "/api/v1/pipelines/daily-load/$run"
}
```

And a `$` in a path is deliberate: `$apply`, `$run`, `$logs`, `$cancel`, `$check` are actions
rather than resources, and the sigil is what keeps them from ever colliding with a code. It
needs no escaping in a URL.

Every list endpoint takes `limit` and `after`, and answers the same `{"items": [...], "next":
...}` envelope. `limit` runs from 1 to 500 and defaults to 50, except `GET /runs/{id}/$logs`,
which defaults to 200. There is no offset and no total on any of them: selection is keyset,
and `after` carries back the opaque cursor the previous page's `next` gave out. A cursor that
does not parse is a 422. See [known debt](operations.md#known-debt).
