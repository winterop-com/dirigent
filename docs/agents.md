# Working with a coding agent

A pipeline is a document and every `dg` command answers in records, which is most of what a
coding agent -- Claude Code, Codex, OpenCode, or any model with a shell -- needs to write
pipelines and check its own work. This page is what to hand it, and what it will find.

## Start it in a project

```bash
uv tool install dirigent-cli
dg init my-pipelines && cd my-pipelines && uv sync
```

`dg init` writes `AGENTS.md` beside the project's `README.md`: the loop below, the MCP tools
that run the same loop when the instance's server is connected, how to read what `dg` answers,
and the rules a document most often gets wrong. `CLAUDE.md` holds one line,
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

The only deletes are `delete_alert_rule` and `delete_schema`, but `apply_document` and
`edit_pipeline` retire what a document stops declaring: a source, with its input journal and its
token, and a schedule the document managed. Runs and pipeline versions stay. `plan_document` and
`edit_pipeline` with `plan_only` list what would go under `sources.removed` and
`triggers.schedules_removed`, and every tool that removes or rewrites carries the destructive
hint, so a client that asks before such a call asks here.

Every answer is bounded, at 48 KB of JSON, so a large one never overflows what an agent can
read. A listing answers 20 rows unless given a `limit`; one whose rows would not fit is cut to the
rows that do, without its `next`, and its `truncated` note names the `limit` that asks for exactly
those. Any other answer too large is cut to the start of its JSON, with a note saying how to ask
for less. A long text -- `export_pipeline`'s document, an example's, a run's report -- is answered
a stretch at a time from `offset`, with `next_offset` while more remains. `run_attempts` shows each
output as its size and opening characters; `get_attempt_output` reads one, or with `path`, a JSON
pointer such as `/rows/0`, one part of it.

`edit_pipeline` changes a stored pipeline without sending the whole document again: it takes the
current version's text exactly as `export_pipeline` answers it, makes each `{old, new}`
replacement in turn, each `old` occurring exactly once, then plans and applies the result. One
edit that misses, or matches more than once, refuses them all and nothing is stored.

Mint the agent a token of its own first; it is shown once:

```bash
dg admin token create agent --user AGENT_USER
```

**Over HTTP, from the instance itself.** Every dirigent server answers MCP over Streamable HTTP
at `/mcp`. Point the client at it and send the token as a header:

```bash
claude mcp add --transport http dirigent https://dirigent.example.org/mcp \
  --header "Authorization: Bearer $DG_TOKEN"
```

The shell expands `$DG_TOKEN` there, so the token itself is what the client stores. To keep it
out of every file, give the project a `.mcp.json` instead, which Claude Code reads from the
project root and expands from the environment it was started with:

```json
{
  "mcpServers": {
    "dirigent": {
      "type": "http",
      "url": "https://dirigent.example.org/mcp",
      "headers": { "Authorization": "Bearer ${DG_TOKEN}" }
    }
  }
}
```

The file holds no secret and can be committed. Start the client with the token in its
environment, for example `DG_TOKEN=$(op read op://Vault/dirigent/credential) claude`; Claude Code
asks once before it uses a server a project's file names.

Nothing is installed beside the agent, and each request acts as the token it presents: two
agents with two tokens are two callers, and a `viewer` token is offered only the tools that read.
There is no OAuth sign-in to go through; a client that supports custom headers on an HTTP server
connects with the token as above. `DIRIGENT_MCP_ENABLED=false` turns `/mcp` off. See
[MCP at `/mcp`](security.md#mcp-at-mcp) for how it is guarded.

**Over stdio, as a local command.** The same tools run as a process the client starts, with the
instance and the token in its environment:

```bash
claude mcp add dirigent -e DG_URL=https://dirigent.example.org -e DG_TOKEN=... -- uvx dirigent-mcp
```

Any MCP client starts it the same way: the command `uvx dirigent-mcp`, with `DG_URL` and
`DG_TOKEN` in its environment. Keep the token where your other secrets are.

**Over HTTP, as a server of your own.** `--transport http` serves the same tools at `/mcp` in front
of a remote instance, for a client that speaks only HTTP or an instance that turned `/mcp` off. It
holds no token: each caller presents its own as a bearer token, which the server checks with the
instance and forwards on every call, and `DG_TOKEN` is never used for them.

```bash
DG_URL=https://dirigent.example.org uvx dirigent-mcp --transport http --port 3334
claude mcp add --transport http dirigent http://127.0.0.1:3334/mcp \
  --header "Authorization: Bearer $DG_TOKEN"
```

It listens on `127.0.0.1` and answers only to a loopback `Host`, and refuses a request another
origin's page caused. An address other machines can reach, such as `--host 0.0.0.0`, is refused
unless `--allow-remote` is given, and is then served with a warning: put TLS in front of it,
since every request carries a token. `DG_MCP_READ_ONLY=1` offers every caller what a viewer is
offered.

**What applying and running reaches.** An agent that may apply a document and run it may write
a pipeline that runs with any connection the instance holds and sends what it reads anywhere an
enabled block reaches. Text it reads back -- a log line, a source's input -- can try to steer it
there. So choose the role for what the agent is for:

- **To read and diagnose,** give it a `viewer` token. The instance refuses every write from a
  viewer, and `/mcp` offers it only the tools that read; over stdio, set `DG_MCP_READ_ONLY=1` for
  the same.
- **To write and run,** give it an `operator` token, never `admin`, on an instance whose
  connections and enabled blocks you would let it use; a staging instance is the usual place.

The server reaches the instance and nothing else on its host. The `document` of `plan_document`
and `apply_document` is always the document's text: a string naming a local file is refused as
text that is not a document, and the file is not opened.

| Tools | What they do |
| --- | --- |
| `list_blocks`, `get_block`, `list_examples`, `get_example` | The catalog and the shipped examples, to write a document from; a listed example is its code, name, shelf, tags and blocks, and `get_example` reads its document |
| `plan_document`, `apply_document` | Check a document against the instance, then store it |
| `edit_pipeline` | Change a stored pipeline by exact replacements in its exported text, then plan it, and apply it unless `plan_only` |
| `list_pipelines`, `get_pipeline`, `export_pipeline`, `validate_pipeline` | What the instance holds |
| `run_pipeline`, `list_runs`, `get_run`, `run_attempts`, `run_logs` | Start a run, optionally waiting for it, and read how it went; `get_run` says how a source's input arrived (`via`) and what the run stored (`stored_bytes`) |
| `get_attempt_output` | One attempt's output, inline or from storage, or the part a JSON pointer names |
| `get_run_report` | The markdown report document a run rendered when it settled, and whether it rendered one |
| `get_run_profile` | Where a run's wall clock went: the critical path, and its queued, running and waiting time |
| `run_stats` | How the runs of a window went: per day, each pipeline's p50, p95 and max duration, and what failed most |
| `runs_by_pipeline` | Each pipeline's runs in a window: the newest, how many per state, its last 10 runs, and the median duration, for the first `limit` (20) pipelines with `more` counting the rest |
| `cancel_run`, `pause_run`, `resume_run`, `retry_attempt`, `rerun_run` | Stop a run, pause or resume one, retry one attempt, or run a settled run again with its parameters and source input |
| `list_sources`, `get_source`, `source_inputs`, `pause_source`, `resume_source` | The input sources and what arrived; `get_source` gives an endpoint's full URL and how a caller authenticates, never its token |
| `rotate_source_token` | Mint an endpoint source a new token or signing secret, shown once, shutting out every caller of the old one |
| `list_connections`, `get_connection`, `check_connection` | The connections a document can name, every secret redacted, and whether one's system answers (admin only) |
| `create_connection` | Create a connection with its settings alone, awaiting the secrets an admin supplies, and answer which they are and the `dg connection set-secret` command that sets them (operator or admin) |
| `list_schemas`, `get_schema` | The named JSON Schemas a document can reference |
| `create_schema`, `update_schema`, `delete_schema` | Store, rewrite or remove a named schema (admin only); one a pipeline references is not removed |
| `list_alert_rules`, `get_alert_rule` | What alerts on what, and where it sends |
| `create_alert_rule`, `update_alert_rule`, `pause_alert_rule`, `resume_alert_rule`, `delete_alert_rule` | Declare an alert rule, change what it says or where it sends, hold or release its deliveries, remove it |
| `list_alert_deliveries` | The alert queue, newest first, narrowed to a run or a `status`, as `dg alerts queue` shows it |
| `list_schedules`, `pause_schedule`, `resume_schedule` | The clocks |
| `list_schedule_firings` | What a schedule actually did, newest first, including the firings it skipped |
| `instance_info`, `whoami` | The instance's version and what it has installed, and who the calls act as |

A `viewer` is offered the reading tools alone; an `operator` every tool but `check_connection`
and the three that write a schema, which the API allows only an admin.

Alert rules are created through these tools, `dg alerts rules` and the API, not declared in a
pipeline document: a rule's code is the instance's, not a pipeline's, a `global` rule watches
every pipeline rather than one, and removing a rule removes the deliveries it raised.

Every tool carries the MCP hints a client asks by: `readOnlyHint` on every read,
`destructiveHint` on what removes or rewrites -- `apply_document`, `edit_pipeline`, `cancel_run`,
`rotate_source_token`, the deletes and the updates -- `idempotentHint` where asking twice does no
more than asking once, and `openWorldHint` on what starts a run or reaches a connection's system.

Two resources hold what a document is written against, read from the instance so they match
what it has installed: `dirigent://schema/document`, the JSON Schema of the format with every
block's config in it, and `dirigent://blocks`, the block catalogue, with
`dirigent://blocks/{block_id}` for one block's config and output schemas.

## Giving it the documentation

[llms.txt](llms.txt) lists every page of this site with a line on what it covers, in the
format language models look for at a site's root. Point an agent at it when the question is
bigger than a document, or paste the pages it names.

## What to keep from it

- **Secrets.** A connection holds them, and a document names a connection by its code and never
  carries a secret. A secret given to an agent lands in its transcript, so it never handles one.
  With an operator token its `create_connection` stores a connection's settings alone and refuses
  a secret field by name. A connection that cannot work without a secret then awaits it, used by
  nothing and refused by a check, until an admin sets it with `dg connection set-secret CODE`, which prompts at a
  terminal without echoing, or by editing it on the Connections screen. `dg connection create`
  makes a whole one yourself, as an admin.
- **Blocks that run code on a worker.** `shell.run`, `docker.*` and their kind are refused until
  the instance allowlists them in `enabled_unsafe_blocks`. That allowlist is yours to set.
- **The instance's state.** `.dirigent/state/` and `.env` belong to the local instance.
