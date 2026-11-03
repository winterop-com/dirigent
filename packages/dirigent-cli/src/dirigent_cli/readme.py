"""The README ``dg init`` writes: from the scaffold to a running instance, a pipeline, and an agent.

A README teaches, so each step says why it is done the way it is. It never holds a secret:
every token is read from a command's output into the shell that needs it.
"""

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from dirigent_cli.project import InitChoices

#: Where the instance answers, for the templates that run one on this machine.
LOCAL_URL: Final = "http://127.0.0.1:3333"

#: The starter a README walks through when the project was not opened with one.
EXAMPLE_STARTER: Final = "report-to-file"


HEAD = """\
# __NAME__

A dirigent project: pipelines are YAML documents under `pipelines/`, and an instance runs them.
This README goes from this directory to a running instance you are signed in to, a connection, a
first pipeline checked, run locally, applied and run on the instance, and a coding agent
connected to the instance over MCP.

## Always `uv run dg`

`pyproject.toml` pins the dirigent version this project was made with, and `uv run dg` runs
exactly that one, from this project's own environment. A bare `dg` is whatever happens to be on
your `PATH`, often an older `uv tool install`, and an older dirigent writes a state the pinned one
refuses. A `dg` recent enough to check refuses to run here when it is not the pinned one, and says
so (`cli.version_mismatch`); `uv tool upgrade dirigent-cli` brings a global one that far. Every
command below is `uv run dg`; `uv sync` installs the pinned version first.

```bash
uv sync
uv run dg --version
```

## What is here

| File | What it is |
| --- | --- |
| `pyproject.toml`, `uv.lock` | The pinned dirigent__PACKS_ROW__ |
| `dirigent.yaml` | The project's settings; `dirigent.example.yaml` lists every setting and its default |
| `.dirigent/profiles.yaml` | Where `uv run dg` finds the instance: the `local` profile, `__URL__` |
| `pipelines/` | The pipeline documents, kept in git |
| `AGENTS.md`, `CLAUDE.md` | What a coding agent reads first |
__FILES_ROWS__"""

LOCAL_START = """\
## 1. Start the instance

`dg init` already made the instance: its database is `.dirigent/state/`, its first admin is
`__ADMIN__`, and `.env` holds that admin's token and the key connection secrets are sealed with.
The `local` profile reads the token from `.env`, so every `uv run dg` here is signed in already.

Start it in a terminal of its own and leave it running:

```bash
uv run dg dev
```

Open __URL__ and sign in as __SIGN_IN__.
The state survives a restart; Ctrl-C stops the instance.

To start from nothing, `uv run dg dev --wipe-state` deletes `.dirigent/state/` first. That takes
the admin and the token `dg init` made with it: the empty state is seeded with `admin` / `admin`,
and the `starting` line prints a new token once. Put it where the old one was, as `DG_TOKEN=` in
`.env`, or export it in your shell.
"""

DOCUMENTS_START = """\
## 1. Start an instance, or point at one

This project holds documents and no instance. Either run one here, or address one somebody else
runs.

**Here, to try it.** In a terminal of its own, left running:

```bash
uv run dg dev
```

Its database and artifacts land in `.dirigent/state/`. On an empty state it seeds an admin,
`admin` / `admin`, and its `starting` line carries that admin's token, shown once: copy the
`export DG_TOKEN=...` line it prints into the shell you work in.
Open __URL__ and sign in as **admin / admin**. The state survives a restart; `uv run dg dev --wipe-state` starts from
nothing, and takes every account, token and connection with it. If the token was lost, log in
again; the token goes into this shell only:

```bash
export DG_TOKEN=$(uv run dg auth login --username admin --password admin --json | jq -r 'select(.token).token')
```

**Elsewhere.** Put its address in `.dirigent/profiles.yaml` as the `url` of the `local` profile,
or of a profile of your own, and log in with your own account. At a terminal
`uv run dg auth login --username YOU` asks for the password and prints the `export DG_TOKEN=`
line to paste.

`uv run dg auth status` says which instance the CLI is talking to, and as whom.
"""

COMPOSE_START = """\
## 1. Start the instance

The instance is a container stack: `compose.yaml` runs PostgreSQL, a migration, the server and a
worker, on the image the `Dockerfile` builds__PACKS_IMAGE__.
`.env` holds the generated secrets and the first admin's password; it is never committed.

```bash
docker compose up -d --build
docker compose ps
```

Open http://localhost:3333 and sign in as `admin`, with the password `.env` holds as
`DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`. Then give this shell a token: at a terminal this asks for
that password and prints an `export DG_TOKEN=...` line to paste.

```bash
uv run dg auth login --username admin
uv run dg auth status
```

`docker compose down` stops the stack and keeps its data; `docker compose down -v` deletes the
volumes too, and with them every account, run and connection.
"""

CONNECTIONS = """\
## 2. A connection

A pipeline never holds a secret. It names a connection by its code, and the connection holds the
address and the credential, sealed on the instance. Create one per system you want to reach:

```bash
uv run dg connection create http httpbin --name "httpbin" --set base_url=https://httpbin.org
uv run dg connection list
uv run dg connection check httpbin
```

`--set` gives fields on the command line. Leave a secret out of `--set` and a terminal asks for it
without echoing it, which keeps it out of your shell history; with no `--set` at all the command
asks for everything the kind needs. Some kinds authenticate one of several ways, a token or a
username and password: there `uv run dg connection create` asks which (`authenticate with`) and
then for each field of that choice. In a script it refuses instead, naming each choice and the
`--set` fields it takes. The Connections screen in the UI shows each kind's fields too.
__PACK_CONNECTIONS__"""

PACK_CONNECTIONS_HEAD = """
### Connections for the packs you chose

| Pack | Kind | Needs | Credential |
| --- | --- | --- | --- |
"""

PACK_CONNECTION_ROWS: Final = {
    "dirigent-dhis2": (
        "| `dirigent-dhis2` | `dhis2` | `base_url`, the instance root, such as "
        "`https://dhis2.example.org` | One of `api_token`, or `basic_username` and `basic_password` |"
    ),
    "dirigent-fhir": (
        "| `dirigent-fhir` | `fhir` | `base_url`, the FHIR R4 base, such as `https://hapi.fhir.org/baseR4` | "
        "None for an open server; `bearer_token`, or `basic_username` and `basic_password` |"
    ),
    "dirigent-contrib": (
        "| `dirigent-contrib` | `chap` | `base_url`, a Chap server, such as `http://localhost:8000` | "
        "`api_token` where the server wants one |\n"
        "| `dirigent-contrib` | `climate` | `base_url`, an open climate service, such as "
        "`https://climate-demo.dhis2.org/ocs` | `credential` where a proxy in front wants one |"
    ),
}

PACK_CONNECTION_EXAMPLES: Final = {
    "dirigent-dhis2": "uv run dg connection create dhis2 dhis2 --set base_url=https://dhis2.example.org",
    "dirigent-fhir": "uv run dg connection create fhir fhir --set base_url=https://hapi.fhir.org/baseR4",
    "dirigent-contrib": "uv run dg connection create climate climate --set base_url=https://climate-demo.dhis2.org/ocs",
}

PIPELINE = """\
## 3. A first pipeline

Start from a starter rather than an empty file: each one is a working document, run by
dirigent's own tests.

```bash
uv run dg examples list --local --starter
uv run dg pipeline new __STARTER__
```

The first lists the documents a project may copy; the second copies one into
`pipelines/__STARTER__.yaml`, as a pipeline of this project's own.

`pipeline new` prints what the copy needs on the instance before it applies, such as the
connections it names; create those first (step 2).

Check it offline, then run it in a throwaway instance that is deleted afterwards. Neither touches
the instance you started:

```bash
uv run dg validate pipelines/__STARTER__.yaml
uv run dg run --local pipelines/__STARTER__.yaml -v
```

Then apply the project to the instance and run it there, where it stays, with its runs and logs
on the Runs screen:

```bash
uv run dg apply --dry-run
uv run dg apply
uv run dg run __STARTER__ --watch
```

`--dry-run` is the whole-project plan, what an apply would change, and writes nothing.
"""

AGENT = """\
## 4. A coding agent over MCP

The instance serves MCP at `/mcp`: an agent there finds blocks and examples, checks a document,
applies it, runs it, and reads runs and logs, as an account of its own. Give it an `operator`
account, which may apply and run pipelines but cannot manage accounts, tokens or connections, so
creating connections stays with you. A `viewer` account gets only the reading tools.

__AGENT_ACCOUNT__

Mint the agent a token, into this shell only. An admin token in `DG_TOKEN` is what mints it:

```bash
export DG_MCP_TOKEN=$(uv run dg admin token create mcp --user agent --json | jq -r 'select(.token).token')
echo ${#DG_MCP_TOKEN}     # 43; 0 means the create failed: run it without | jq to see why
```

Then give the project a `.mcp.json` beside `pyproject.toml`. It holds no secret, since Claude Code
expands `${DG_MCP_TOKEN}` from the environment it is started with, so it can be committed:

```json
{
  "mcpServers": {
    "dirigent": {
      "type": "http",
      "url": "__MCP_URL__",
      "headers": { "Authorization": "Bearer ${DG_MCP_TOKEN}" }
    }
  }
}
```

Start Claude Code from this directory, in the shell that holds `DG_MCP_TOKEN`:

```bash
claude
```

Approve the `dirigent` server once when asked, and `/mcp` lists it as connected with its tools.
`AGENTS.md` tells the agent how to work here. Everything it does is attributed to `agent` on the
instance.
"""

AGENT_ACCOUNT_LOCAL = """\
`dg admin user create` writes the account straight to this instance's database, so it needs no
token. It asks for a password twice, of at least 8 characters; the agent never uses it, since it
authenticates with the token below.

```bash
uv run dg admin user create agent --role operator
```"""

AGENT_ACCOUNT_COMPOSE = """\
`dg admin user create` writes the account straight to the instance's database, so it runs inside
the stack, where that database is. It asks for a password twice, of at least 8 characters; the
agent never uses it, since it authenticates with the token below.

```bash
docker compose exec server dg admin user create agent --role operator
```"""

AGENT_ACCOUNT_DOCUMENTS = """\
On an instance started here with `uv run dg dev`, `dg admin user create` writes the account
straight to its database, so it needs no token. It asks for a password twice, one of
at least 8 characters; the agent never uses it, since it authenticates with the token below. On
an instance somebody else runs, an admin creates the account on the Users screen instead.

```bash
uv run dg admin user create agent --role operator
```"""

TROUBLE_HEAD = """\
## When something goes wrong

| What you see | What it is, and what to do |
| --- | --- |
"""

#: What goes wrong on every template, and what to do about it.
TROUBLE: Final = (
    (
        "`cli.version_mismatch`",
        "A `dg` other than the pinned one ran. Use `uv run dg`; `uv sync` installs the pinned one",
    ),
    (
        "401 from a command",
        "`DG_TOKEN` is empty, revoked, or from an instance whose state was wiped. Log in again (step 1)",
    ),
    (
        "401 from an MCP tool, or `/mcp` not connected",
        "`DG_MCP_TOKEN` was empty when `claude` started (`echo ${#DG_MCP_TOKEN}`), or the agent account "
        "went with a wipe. Redo step 4",
    ),
    (
        "`uv run dg` cannot find the instance",
        "`.dirigent/profiles.yaml` is missing: `git checkout -- .dirigent` brings it back, or write one "
        "with a `local` profile at `__URL__`",
    ),
    (
        "`cli.connection_needs_a_credential`",
        "The kind needs a credential and none was given. The refusal names each choice and its `--set` fields",
    ),
    (
        "`connection_config_invalid`",
        "A field is missing or wrong. The Connections screen shows the kind's fields",
    ),
)

#: What goes wrong with an instance run here by `dg dev`.
TROUBLE_LOCAL: Final = (
    (
        "`admin` / `admin` is refused, or the first line names another admin",
        "An older global `dg` made the state. Stop it, then `uv run dg dev --wipe-state`",
    ),
    (
        "`database.schema_stale` at start",
        "The state was written by another dirigent version. `uv run dg dev --wipe-state` starts from nothing",
    ),
    (
        "`address already in use`",
        "Another instance holds port 3333. `lsof -nP -iTCP:3333 -sTCP:LISTEN` names it; stop it, or "
        "`uv run dg dev --port 3334` and change the profile's `url` to match",
    ),
)

#: What goes wrong with the container stack.
TROUBLE_COMPOSE: Final = (
    (
        "`database.schema_stale` in the server's log",
        "The volumes hold a database another dirigent version wrote. `docker compose down -v`, then up again",
    ),
    (
        "`address already in use`",
        "Another process holds port 3333. `lsof -nP -iTCP:3333 -sTCP:LISTEN` names it, or set "
        "`DIRIGENT_PORT` in `.env` and the profile's `url` to match",
    ),
)

TROUBLE_TAIL = """
The documentation is at https://winterop-com.github.io/dirigent/; `uv run dg --help` and
`uv run dg COMMAND --help` describe every command.
"""


def _troubleshooting(choices: "InitChoices") -> str:
    """The table of what goes wrong, the template's own instance first."""
    rows = (*(TROUBLE_COMPOSE if choices.stack else TROUBLE_LOCAL), *TROUBLE)
    return TROUBLE_HEAD + "".join(f"| {seen} | {remedy} |\n" for seen, remedy in rows) + TROUBLE_TAIL


def _sign_in(choices: "InitChoices") -> str:
    """Say who signs in to a local instance, naming the password only when it is the fixed one."""
    if choices.local_password:
        return f"**{choices.admin} / admin**"
    return f"**{choices.admin}**, with the password you gave `dg init`"


def _starter(choices: "InitChoices") -> str:
    """The starter the pipeline step walks through: the project's first one, or a general one."""
    return choices.pipelines[0] if choices.pipelines else EXAMPLE_STARTER


def _pack_connections(choices: "InitChoices") -> str:
    """The table of each chosen pack's connection kinds, with a command to start from."""
    if not choices.packs:
        return ""
    rows = [PACK_CONNECTION_ROWS[pack] for pack in choices.packs if pack in PACK_CONNECTION_ROWS]
    examples = [PACK_CONNECTION_EXAMPLES[pack] for pack in choices.packs if pack in PACK_CONNECTION_EXAMPLES]
    return (
        PACK_CONNECTIONS_HEAD
        + "\n".join(rows)
        + "\n\nEach one asks at a terminal for the credential its kind takes:\n\n```bash\n"
        + "\n".join(examples)
        + "\n```\n"
    )


def readme_document(name: str, choices: "InitChoices") -> str:
    """Assemble the README for one template and the packs chosen."""
    template = choices.template
    start = {"local": LOCAL_START, "compose": COMPOSE_START}.get(template, DOCUMENTS_START)
    account = {"local": AGENT_ACCOUNT_LOCAL, "compose": AGENT_ACCOUNT_COMPOSE}.get(template, AGENT_ACCOUNT_DOCUMENTS)
    files = {
        "local": "| `.dirigent/state/` | The instance's database and artifacts. Never edited, never committed |\n"
        "| `.env` | The first admin's token and the instance key. Never committed |\n",
        "compose": "| `compose.yaml`, `Dockerfile` | The stack, and the image it builds on the published one |\n"
        "| `.env` | The stack's generated secrets and the first admin's password. Never committed |\n",
    }.get(template, "| `.dirigent/state/` | Created by `uv run dg dev`: a local instance. Never committed |\n")
    packs = ", ".join(f"`{pack}`" for pack in choices.packs)
    parts = [
        HEAD.replace("__PACKS_ROW__", f", and {packs}" if packs else "").replace("__FILES_ROWS__", files),
        start.replace("__ADMIN__", choices.admin)
        .replace("__SIGN_IN__", _sign_in(choices))
        .replace("__PACKS_IMAGE__", f", which installs {packs}" if packs else ""),
        CONNECTIONS.replace("__PACK_CONNECTIONS__", _pack_connections(choices)),
        PIPELINE.replace("__STARTER__", _starter(choices)),
        AGENT.replace("__AGENT_ACCOUNT__", account).replace("__MCP_URL__", f"{LOCAL_URL}/mcp"),
        _troubleshooting(choices),
    ]
    return "\n".join(parts).replace("__NAME__", name).replace("__URL__", LOCAL_URL)
