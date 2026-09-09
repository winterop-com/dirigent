# Getting started

From nothing to a working instance. This page stands on its own: follow it top to bottom and
you will have run a pipeline locally, run one against a real instance, and then stood up the
three-service production shape with an admin account and a token. Nothing here assumes you
have read anything else.

## Install

Dirigent is a set of Python packages. The command line is `dirigent`, with `dg` as the short
alias, and it is both the operator's remote for a running instance and the process entry point
a container runs.

```bash
uv tool install dirigent-cli
dg version
```

That tool-installed `dg` is what runs `dg init`. A project it scaffolds is a uv project that
pins its own dirigent, so inside one the pinned runtime is reached as `uv run dg` and the tool
`dg` is only ever the scaffolder.

Two other ways to have `dg`: `uv sync` in a clone and `uv run dg`, or the one inside the
published image, `docker compose exec server dg ...`, which needs nothing on the host.

That answers with one NDJSON record naming every installed package, which is what every
command writes unasked; `dg version -o console` draws it as a table instead.

That gives you the CLI, the engine, the built-in blocks, and the server, because they are
dependencies of the CLI package. You need Python 3.13 and [uv](https://docs.astral.sh/uv/).

**From source**, which is what a contributor does:

```bash
git clone https://github.com/winterop-com/dirigent
cd dirigent
make install          # uv sync --all-packages
uv run dg version
```

Every `dg` below becomes `uv run dg` in a source checkout. `make check` is the read-only gate
CI runs -- ruff, mypy, pyright, and the fast test lane.

## The zero-setup smoke test

The fastest way to see it work needs no server, no database, and no Docker:

```bash
dg run --local examples/hello-world.yaml
```

```text
  queued          greet (value.const)
  succeeded       greet (value.const)    value=hello from dirigent

succeeded  run 01a04d45-6737-70b7-9d19-0e9dc750c24a
```

`--local` applies and runs the document in a throwaway SQLite instance in a temporary
directory, streams what each step does, and deletes the database on the way out. It is the
same apply, the same engine, and the same worker loop a real instance uses -- a local run that
executed differently would prove nothing.

Nothing was granted for this: `value.const` only emits its configured value. A block that
executes code on the worker -- `shell.run`, `docker.run` -- is refused unless allowlisted by
block id, and `--enable-unsafe shell.run` is the one-command version of that grant;
[the allowlist](security.md#local-execution-and-the-unsafe-block-allowlist) is where
that begins. Most blocks need nothing.

The exit code is the run's outcome, so this works in CI directly. See
[exit codes](cli.md#watching-a-run) for what each one means.

## A laptop instance: `dg dev`

```bash
dg dev | dg format
```

One asyncio process containing four things:

- the **API**, on `http://127.0.0.1:3333`, with its OpenAPI viewer at `/docs`,
- the **web UI**, served at `/` by the same process, from the bundle in the installed package
  or the one `make ui` builds in a checkout,
- the **scheduler**, which turns clock time into runs,
- one **worker**, which claims and executes,
- a **SQLite file**, `.dirigent/state/dirigent.db`, which is where all of it coordinates.

Everything an instance keeps locally -- that database, and the artifacts its runs write --
lives under `.dirigent/state/`, created on start. That path is relative to the directory you
start `dg dev` in, so starting it somewhere else is a **different instance**: its own
database, its own runs, none of the history you had. The record it writes on start says which
one you got.

**Its account is `dev`, with the password `dirigent-dev`.** `dg dev` creates that admin on an
empty database, together with an API token named `dev` whose secret the starting record carries
once. Both are fixtures of a throwaway instance rather than credentials, which is why they are
fixed and written here. The compose stack is the other shape: its first admin is `admin`, with
the password `.env` sets in `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`, and nothing about it is fixed.

**`dg dev` runs the instance that is in that directory.** An instance `dg init` made, or one
an earlier start left, keeps its accounts, its runs and its artifacts; the schema is migrated
forward on every start. `--wipe-state` is how you ask to begin from nothing, and it says so in
one record when it deletes something:

```bash
dg dev --wipe-state
```

Only a directory dirigent named itself is ever removed. Point `database_url` somewhere else
and the wipe is refused rather than guessed at, because the files beside that database are
not dirigent's to delete.

Like every dirigent process it writes NDJSON, so `dg format` is what renders it. The starting
record says where its state is, what it bound, the admin it made, and the token, **once**; then
it stays quiet until something happens. Detail is what `-v` is for:

```text
2026-01-01T18:22:23.069+01:00 [info    ] starting   [process] process=dev api=http://127.0.0.1:3333 docs=http://127.0.0.1:3333/docs admin=dev state=/home/you/my-pipelines/.dirigent/state token=osZDN7zM-DnWPb3rVJHWsxpgkekZylez1MF8E-GpgnI migrated=0001_baseline
2026-01-01T18:22:23.382+01:00 [info    ] ready      [process] process=dev
```

Leave it running. In a second terminal, tell the CLI which instance to talk to and how to
authenticate to it, using the `api` and `token` off that record:

```bash
export DG_URL=http://127.0.0.1:3333
export DG_TOKEN=osZDN7zM-DnWPb3rVJHWsxpgkekZylez1MF8E-GpgnI
```

`jq` takes the token straight off the stream if you would rather not copy it by hand:

```bash
dg dev | jq -r 'select(.kind == "process" and has("token")) | .token'
```

`dg dev` refuses to start on anything but SQLite. On PostgreSQL it would be `dg server` with
extra steps, and giving one thing two names helps nobody.

## The first real run

```bash
dg init my-pipelines --password "the one you will use"
cd my-pipelines
uv sync
uv run dg dev                    # in a second terminal, in this directory; it keeps running
```

```bash
uv run dg apply                  # back in the first terminal, in this directory
uv run dg run hello-world --watch
```

`dg init` initialises an instance and the documents that address it: it creates
`.dirigent/state/`, migrates the schema, creates the first admin, and mints it one token. The
token goes into the project's `.env`, readable by you alone and kept out of git, and the
`local` profile in `.dirigent/profiles.yaml` reads it from there whenever the shell does not
export `DG_TOKEN` -- so nothing has to be pasted. `uv sync` builds the project's environment
from the `pyproject.toml` it wrote, which pins the dirigent that scaffolded it -- so every
`uv run dg` below is that runtime rather than whatever is on the path.
`dg dev` then runs what it made, and serves the UI at `http://127.0.0.1:3333`. Never
`--wipe-state` here: it would empty the directory `dg init` just filled and mint a development
admin of its own, leaving the token in `.env` addressing an account that no longer exists.
`dg init --template documents` stops after the documents, which is what to use when the
instance is somebody else's server. At a terminal, `dg init hello` with no flags opens one
form that asks all of this: where it runs, the stack's services, packs, a workflow, and the
first admin.

It scaffolds `dirigent.yaml`, which says where documents live and holds the few settings a
project is likely to change; `dirigent.example.yaml`, every setting there is with its default
and description, commented out and never loaded; `.dirigent/profiles.yaml`, saying which
server to talk to; `pipelines/hello-world.yaml`, a working example; `.dirigent/.gitignore`,
which keeps `.dirigent/state/` out of the repository while the profiles beside it stay
committable; `pyproject.toml`, which pins the dirigent runtime the project runs on; a
`README.md` with the commands for the template; and a root `.gitignore` for `.venv/` and
`__pycache__/`. A directory that already has a `pyproject.toml` or a `README.md` keeps its
own: `dg init` says which files it left alone, and adding `dirigent-cli` to that
`pyproject.toml` is then yours to do.

## The first server

```bash
dg init my-instance --template compose --password "the one you will use"
cd my-instance
uv sync
docker compose up -d
uv run dg auth login --username admin
```

`--template compose` writes the same documents plus `compose.yaml`, a `Dockerfile`, a `.env`
holding a generated `DIRIGENT_SECRET_KEY` and the password given here, and a root
`.gitignore` keeping that `.env` out of the repository. The stack it describes is PostgreSQL, the API with
the scheduler embedded, object storage for artifacts and a worker, all running the image that
`Dockerfile` builds on `ghcr.io/winterop-com/dirigent`, pinned to the version of the `dg` that
wrote the file. `--service docker` adds the workers' own daemon, `--service kafka` and
`--service rabbitmq` a broker, each with a hello example in `pipelines/`; `--pack dirigent-dhis2`
installs the pack into the image. Adding one later is a line in that `Dockerfile` and
`docker compose up --build`.

Nothing is initialised on this machine: no state directory, no migration and no token, because
the instance is the containers. The first admin is `admin`, created from
`DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD` in that `.env` the first time the server comes up, and
`uv run dg auth login` mints the token from it. `dg dev` is not part of this: it is the single-process
instance, and this is a server. Everything in `pipelines/` is applied at boot, and `dg apply`
sends one now.

`dg apply` sends every document in the project to the instance, which stores each as an
immutable version. It is idempotent: a document whose digest matches the stored one is
unchanged, so applying the whole repository on every merge does not accumulate a version per
commit. `dg apply --dry-run` prints the plan without writing.

`dg run hello-world --watch` starts a run and streams its step transitions and block output
until it settles, then exits with the run's outcome.

That is the whole loop. The same instance is a web UI at `http://127.0.0.1:3333`, where the
account you just made logs in and the run you just started is on screen.
[The tutorial](tutorial.md) builds a realistic pipeline through it -- a sensor, a fan-out, an
error branch -- and breaks it on purpose.

## The real thing: three services

!!! tip "The whole sequence, in order, is [A server](server.md)"

    That page runs from an empty directory to a pipeline running on the compose stack with
    no branches in the way. What follows here is the same ground with the alternatives left
    in, which is useful once you know what you are choosing between.


`infra/compose.yaml` at the repository root is the shape to start from in production. Four services,
three of them long-lived:

| Service | What it is | Why it is separate |
| --- | --- | --- |
| `postgres` | PostgreSQL 17 | All coordination lives here. There is no broker and no second store |
| `migrate` | A one-shot `dg db upgrade` that the other two wait on | Scaling the server out must not mean N processes racing to migrate one schema |
| `server` | `dg server`: the API, with the scheduler embedded | Needing a fourth service just to get a clock is a poor default. Leadership is an advisory lock, so embedding it costs nothing when it later moves out |
| `worker` | `dg worker`: claims due work, executes it, probes what is waiting | Execution scales independently of the API. A worker opens no port and nothing connects to it |

All four are built from one image in which `dg server`, `dg worker`, and `dg scheduler` are the
same code with different entry points. Everything the services share is a database URL and a
secret key.

### Configure it

```bash
cp .env.example .env
```

Two values in `.env` have no safe default.

**`DIRIGENT_SECRET_KEY`** is the envelope key that connection secrets and webhook signing
secrets are encrypted with. Generate one:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

A well-formed Fernet key is used as-is. Anything else -- a passphrase you typed -- is hashed
into a valid key rather than refused, so a human-typed value yields a working instance; prefer
the generated one. **Losing this key means losing every stored connection secret**, and there
is no rotation tooling, so back it up somewhere that is not beside the database backup.

**`DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`** creates the first admin account. It is optional; see
[first admin](#the-first-admin) for the alternative.

Then:

```bash
docker compose --project-directory . -f infra/compose.yaml up --build
```

The server publishes 3333. Point the CLI at it:

```bash
export DG_URL=http://localhost:3333
```

To scale execution, `docker compose --project-directory . -f infra/compose.yaml up --scale worker=3`. What limits that number is the
database connection pool, and the arithmetic is in
[scaling workers](operations.md#scaling-workers).

## The first admin

Nothing can authenticate before an account exists, so account creation has a path that does not
go through the API. There are two.

**Unattended, for a container.** Set `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD` in `.env` before the
first `docker compose --project-directory . -f infra/compose.yaml up`. When the server starts against a database with no accounts, it
creates an admin named `admin` with that password, and nothing else. It is one-way: it does
nothing
the moment any account exists, so leaving it set on every deploy cannot reset a live instance's
password.

**By hand.**

```bash
dg admin user create ada --role admin
```

**`dg admin user create` runs against the database, not the API.** Like `dg db upgrade`, it
opens `DIRIGENT_DATABASE_URL` directly. It has to: the first account on a fresh instance must
exist before anything can authenticate to the endpoint that would create it. So run it
somewhere that can reach the database and has the same configuration the server has --
`docker compose --project-directory . -f infra/compose.yaml exec server dg admin user create ada --role admin` in the compose stack.

`--role` is required, on the command line and on `POST /api/v1/users` alike: there is no
default, so nothing makes an admin by leaving a field out.

## The first token

An account is a password, and the CLI is a script's client rather than a browser, so the thing
you actually carry around is a token.

```bash
dg auth login --username ada
dg admin token create ci
```

`dg auth login` verifies the password against the API and then mints an API token named
`cli-<username>`, which it writes as a `token.issued` record; through `dg format`, or with
`-o console`, that is the export line to paste. `dg admin token create NAME` mints one under
a name you choose, which is what a CI job should hold.

**The secret prints exactly once.** The instance stores only a SHA-256 of it plus the first
eight characters, so that a listing can tell two tokens apart without holding either. There is
no way to recover a token you did not write down -- mint another and revoke the old one.

```bash
dg admin token list                # name, prefix, created, last used, revoked
dg admin token revoke ci
```

`last_used_at` is what answers "is anything still presenting this?" before you revoke it. It is
accurate to the minute rather than to the request.

Both `dg auth login` and `dg admin token create` are admin-only, because minting a credential
is.

Once a script rather than a person is holding that token, add `--json`. It is valid on every
command: a listing or a show answers with the server's own response, and a streaming command --
`dg run --watch`, `dg run --local`, `dg runs logs --follow` -- answers with NDJSON, one event
object per line as things happen. Nothing but JSON reaches stdout, and a command that would
have prompted for a value fails with a problem object instead of blocking on a pipe.

```bash
dg run --local ./daily-load.yaml --json | jq -r 'select(.kind == "log") | .message'
```

The record kinds and their fields are in [the command line](cli.md#machine-output-the-default).

## Pointing the CLI at an instance

Two ways, and the second is the one to settle on.

**Environment variables**, which is what `dg dev` puts on its starting record and what a CI job sets:

```bash
export DG_URL=https://dirigent.example.org
export DG_TOKEN=...
dg auth status                     # says which server, and who you are
```

**Profiles**, which are durable. A profile names a server and how to obtain a token for it, in
`.dirigent/profiles.yaml` beside your pipelines or `~/.config/dirigent/profiles.yaml` for the
whole machine. A token can be inline, read from an environment variable, or produced by any
command -- `pass show dirigent/prod`, say -- so a production token never has to sit in a file.
`cd`-ing into a pipeline repository then points the CLI at that repository's server with no
flag to remember, and `dg --profile prod ...` switches deliberately. The full syntax and the
precedence rules are in [the command line](cli.md#profiles).

## Ports

| Port | What |
| --- | --- |
| 3333 | The dirigent API server (`DIRIGENT_PORT`), and what `dg dev` binds |
| 3334 | The documentation site `make docs` serves on a contributor's machine |

3334 is a local convenience only, adjacent to 3333 rather than mkdocs' default of 8000 so the
docs and an instance sit next to each other. It is no part of a deployment, and nothing in
`infra/compose.yaml` or the image mentions it.

Note that `DIRIGENT_HOST` defaults to `127.0.0.1`, not `0.0.0.0`. In a container you want
`0.0.0.0` with the port published by the runtime, which is what the image already sets.

## It did not work

The four things a first-timer actually hits.

**"cannot reach ..." or "does not look like a dirigent instance".** The CLI is pointed at the
wrong place, or nothing is listening.

```bash
dg auth status                     # which URL, from which source, and whether it authenticates
curl -sI http://localhost:3333/health | grep -i x-dirigent-version
```

Every response a dirigent server sends carries `X-Dirigent-Version`. If that header is absent,
something else is on that port -- most often the documentation site on 3334, or a stale tunnel.

**401, or "no token".** `DG_TOKEN` is unset, or the token was revoked, or it belongs to a
different instance.

```bash
dg auth status                     # who you are, and via what
dg admin token list                # from an account that still works
```

A token is not transferable between instances: its hash lives in that instance's database.

**A run is created but never starts.** Nothing is claiming work.

```bash
dg system workers                  # is anything registered, and is it stale?
dg system info                     # workers_live, and every connection's health
docker compose logs worker
```

Zero live workers is the common case, and no health probe reports it -- a server with no
workers is perfectly ready, it just never executes anything. On PostgreSQL, check the worker
container actually started: `dg worker` refuses SQLite outright, with exit code 3 and a message
saying why.

**"executes code on the worker and is disabled".** `shell.run` and `docker.run`
execute code on a worker and are refused unless the instance names their id in
`DIRIGENT_ENABLED_UNSAFE_BLOCKS`. For one local run, `--enable-unsafe shell.run`. For an
instance, set the variable on the **workers** as well as the server, because the gate is
enforced both when the run is created and again when a worker claims the step. See
[the allowlist](security.md#local-execution-and-the-unsafe-block-allowlist).

**The instance refuses to start, naming the pool.** A message about
`database_pool_size` plus `database_max_overflow` against `worker_concurrency` means the
connection pool cannot cover the concurrency configured on top of it. Raise the pool or lower
the concurrency; the reasoning is in [scaling workers](operations.md#scaling-workers).

For anything else, `-v` shows the engine's own events and the API calls the CLI makes, and
`-vv` shows everything:

```bash
dg -v run hello-world --watch
```

## Where to go next

- **[Tutorial](tutorial.md)** -- one realistic pipeline end to end, broken on purpose.
- **[Concepts](concepts.md)** -- pipeline, step, block, run, item, attempt, connection, trigger.
- **[The command line](cli.md)** -- profiles, projects, parameters, the whole command tree.
- **[Operations](operations.md)** -- every setting, scaling, backups, health checks, monitoring.
- **[Security](security.md)** -- the threat model, and the secrets lifecycle.

## Licence

Dirigent is source-available under a proprietary licence: the source may be read, and any
other use -- running, copying, modifying or distributing it -- requires written permission
from the copyright holder.
