# Working with a coding agent

A pipeline is a document and every `dg` command answers in records, which is most of what a
coding agent -- Claude Code, Codex, OpenCode, or any model with a shell -- needs to write
pipelines and check its own work. This page is what to hand it, and what it will find.

## Start it in a project

```bash
uv tool install dirigent-cli
dg init my-pipelines && cd my-pipelines && uv sync
```

`dg init` writes `AGENTS.md` beside the project's `README.md`: the loop below, how to read what
`dg` answers, and the rules a document most often gets wrong. `CLAUDE.md` holds one line,
`@AGENTS.md`, so Claude Code reads the same notes every other agent reads. A project that
already has either file keeps its own.

A project made before `dg init` wrote them gets the notes with `uv run dg init --agents`, which
writes the two files alone and leaves everything else, and any of the two the project already
has, as it is.

Start the agent in that directory and say what you want, in your own words:

```text
Write a pipeline that fetches today's readings from the playground, keeps the stations
above 30 degrees, and writes them to storage as CSV. Check it with dg before you stop.
```

## The loop it works in

Every command goes through `uv run dg`, the version the project pins, and none of it needs a
server.

| Step | Command | What it gives the agent |
| --- | --- | --- |
| Find a starting point | `uv run dg examples list --local`, `uv run dg examples show CODE --local` | Every document the installed plugins ship, each one run by dirigent's own tests |
| Copy one | `uv run dg pipeline new STARTER` | The starter in `pipelines/`, its teaching comments intact |
| Look up a block | `uv run dg blocks list --local`, `uv run dg blocks show BLOCK --local` | Every block's config and output schemas |
| Get the whole shape | `uv run dg pipeline schema -f .dirigent/document.schema.json` | One JSON Schema: the format and every installed block's config |
| Check it | `uv run dg validate pipelines/NAME.yaml --explain` | Every problem at once, each with the `location` it is about, and what the work will cost |
| Run it | `uv run dg run --local pipelines/NAME.yaml -v` | A throwaway instance, every step's state and output, and the closing `run` record |

`dg dev` and `dg apply` come after: `dg dev` starts a local instance with its web UI and keeps
running, so start it yourself in a terminal of its own, and the agent applies to it with
`uv run dg apply`.

## Why the answers are easy to read

An agent's shell is never a terminal, so every `dg` command writes NDJSON there, with no
colour, no table and no banner: one JSON record per line, each with a `kind`. The same command
at your terminal renders, and `dg format` renders a stream that was kept. See
[records when nothing is watching](cli.md#records-when-nothing-is-watching).

A document that does not validate is a `validation` record whose `problems[]` each carry a
stable `code`, a `message` and the `location` in the document it is about, all of them at once:

```json
{"kind": "validation", "level": "error", "message": "invalid", "code": "hot-stations", "problems": [
  {"code": "document.step_config_invalid", "location": "steps.fetch.config",
   "message": "Additional properties are not allowed ('urll' was unexpected)"}
]}
```

Anything else refused -- by the CLI, by a block's own check, by the server -- is a record of
kind `error` with a `code`, the `params` it was built from, and `problems[]` where there is
more than one thing to say. A model fixes what `location` names and validates again, which
converges in a step or two rather than by guessing at prose.

Offline, `dg validate` checks every step's block and config against the blocks installed
beside `dg`. A connection or another pipeline a document names is checked only by
`dg validate --server` or the apply, since only an instance knows what it holds.

## An editor, or a model, that checks as it writes

`dg pipeline schema -f .dirigent/document.schema.json` writes the format and every installed
block's config as one Draft 2020-12 schema. Name it on a document's first line and any editor
that reads the comment squiggles an unknown key or a missing one where it was typed:

```yaml
# yaml-language-server: $schema=../.dirigent/document.schema.json
format: dirigent/v1
kind: pipeline
code: hot-stations
```

Write it again after installing a plugin; the schema is the blocks installed beside `dg`. A
running instance serves the same schema for its own catalog at `GET /api/v1/schema/document`.

## Over MCP, against a running instance

The loop above writes documents and checks them without a server. To let an agent operate an
instance that is running -- apply a document, start a run, read its logs, pause a source --
give it the MCP server, `dirigent-mcp`. Its tools are calls the API already answers, so what
the agent may do is what its token's role may do.

No tool is a delete, but `apply_document` retires what a document stops declaring: a source, with
its input journal and its token, and a schedule the document managed. Runs and pipeline versions
stay. `plan_document` lists what would go under `sources.removed` and
`triggers.schedules_removed`, and `apply_document` carries the destructive hint, so a client that
asks before such a call asks here.

```bash
dg admin token create agent --user AGENT_USER     # the token is shown once
claude mcp add dirigent -e DG_URL=https://dirigent.example.org -e DG_TOKEN=... -- uvx dirigent-mcp
```

Any MCP client starts it the same way: the command `uvx dirigent-mcp` over stdio, with
`DG_URL` and `DG_TOKEN` in its environment. Keep the token where your other secrets are.

**What applying and running reaches.** An agent that may apply a document and run it may write
a pipeline that runs with any connection the instance holds and sends what it reads anywhere an
enabled block reaches. Text it reads back -- a log line, a source's input -- can try to steer it
there. So choose the role for what the agent is for:

- **To read and diagnose,** give it a `viewer` token and set `DG_MCP_READ_ONLY=1`. The instance
  refuses every write from a viewer, and the server offers only the tools that read.
- **To write and run,** give it an `operator` token, never `admin`, on an instance whose
  connections and enabled blocks you would let it use; a staging instance is the usual place.

The server reaches the instance and nothing else on its host. The `document` of `plan_document`
and `apply_document` is always the document's text: a string naming a local file is refused as
text that is not a document, and the file is not opened.

| Tools | What they do |
| --- | --- |
| `list_blocks`, `get_block`, `list_examples`, `get_example` | The catalog and the shipped examples, to write a document from |
| `plan_document`, `apply_document` | Check a document against the instance, then store it |
| `list_pipelines`, `get_pipeline`, `export_pipeline`, `validate_pipeline` | What the instance holds |
| `run_pipeline`, `list_runs`, `get_run`, `run_attempts`, `run_logs` | Start a run, optionally waiting for it, and read how it went |
| `run_stats` | How the runs of a window went: per day, each pipeline's p50, p95 and max duration, and what failed most |
| `cancel_run`, `retry_attempt`, `rerun_run` | Stop a run, retry one attempt, or run a settled run again with its parameters and source input |
| `list_sources`, `source_inputs`, `pause_source`, `resume_source` | The input sources and what arrived |
| `list_schedules`, `pause_schedule`, `resume_schedule` | The clocks |
| `instance_info` | The instance's version and what it has installed |

## Giving it the documentation

[llms.txt](llms.txt) lists every page of this site with a line on what it covers, in the
format language models look for at a site's root. Point an agent at it when the question is
bigger than a document, or paste the pages it names.

## What to keep from it

- **Secrets.** A connection holds them, created once with `dg connection create`, which prompts
  at a terminal; a document names a connection by its code and never carries a secret. Create
  connections yourself.
- **Blocks that run code on a worker.** `shell.run`, `docker.*` and their kind are refused until
  the instance allowlists them in `enabled_unsafe_blocks`. That allowlist is yours to set.
- **The instance's state.** `.dirigent/state/` and `.env` belong to the local instance.
