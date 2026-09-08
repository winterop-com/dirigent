# Docker

The `docker.*` family runs containers as pipeline steps. It is three blocks today and is
built to grow:

- [`docker.run`](blocks.md#dockerrun) runs **one container** and lets the engine probe it to
  completion. It speaks the Docker Engine HTTP API over the daemon socket.
- [`docker.compose.up`](blocks.md#dockercomposeup) and
  [`docker.compose.down`](blocks.md#dockercomposedown) run a **whole stack** from a compose
  file. They shell out to the `docker compose` CLI -- only the CLI can orchestrate compose --
  and read the stack's state back over the Engine API.
- [`docker.build`](blocks.md#dockerbuild) builds **an image** from a context with buildx, and
  pushes it where a connection holds a registry credential.

Each block's fields are the generated [block reference](blocks.md); this page is the family:
what they share, how the daemon is reached, and the compose lifecycle that ties `up`, a drive
step, and `down` into one run.

## These are unsafe blocks

Every block here declares `local_execution`, which means the engine refuses to run it unless
the instance names its id in `DIRIGENT_ENABLED_UNSAFE_BLOCKS`. That gate exists because
reaching a Docker daemon is reaching root wherever that daemon runs: anything that can talk to
a daemon can start a privileged container on its host. "Can edit pipelines" must never silently
mean "can run containers on the worker's host".

Enable them per instance, and only for a worker you trust with what its daemon controls:

```bash
dg run --local examples/docker/docker-compose-stack.yaml \
  --enable-unsafe docker.compose.up,docker.compose.down,docker.run
export DIRIGENT_ENABLED_UNSAFE_BLOCKS='["docker.compose.up","docker.compose.down","docker.run"]'
```

## The daemon these blocks reach

A block talks to whatever daemon `DOCKER_HOST` names, resolved the way the docker CLI resolves
it:

| `DOCKER_HOST` | Reached as |
| --- | --- |
| unset | the local unix socket `/var/run/docker.sock` |
| `unix:///path/to.sock` | that unix socket |
| `tcp://host:port` | `http://host:port` |
| `tcp://host:port` with `DOCKER_TLS_VERIFY=1` and `DOCKER_CERT_PATH` | `https://host:port` with the client `ca.pem`/`cert.pem`/`key.pem` |

### The reference shape: a dind sidecar

`infra/compose.yaml` gives the worker its **own** daemon. A `docker:dind` sidecar serves
`tcp://docker:2376` with TLS required, generating its CA, server and client certificates into
`DOCKER_TLS_CERTDIR=/certs`; the worker mounts the client half read-only and carries three
variables, which nothing else in the stack does:

```yaml
DOCKER_HOST: tcp://docker:2376
DOCKER_TLS_VERIFY: "1"
DOCKER_CERT_PATH: /certs/client
```

A pipeline's containers are then the sidecar's, and no host socket is mounted anywhere. The API
blocks read `DOCKER_HOST` through the resolution above; the CLI blocks pass these three to the
`docker` binary they run, so `env_allowlist` never has to name them and a document cannot point
a step at another daemon.

The sidecar runs `privileged: true`, which docker-in-docker requires -- it has no unprivileged
mode that starts containers. It keeps `/var/lib/docker` on a named volume, so an image pulled
once survives a restart.

**One constraint the sidecar imposes:** a bind mount is resolved on the **daemon's** filesystem,
not the worker's. `docker.run` mounts `inputs` and `outputs` from the run's work directory, and
hands the daemon those paths, so the sidecar mounts the same `work` volume at the same
`/var/lib/dirigent/work`. Point a worker at a daemon that cannot see that path and every step
with `inputs` or `outputs` mounts an empty directory.

Mounting the host's `/var/run/docker.sock` into a containerized worker is the **discouraged
fallback**: it works, but it grants that container root on the host. See
[operations](operations.md#dockerrun-on-a-containerized-worker).

The worker image (`infra/Dockerfile`) always ships the docker CLI with the compose and buildx
plugins, so the CLI blocks have something to run.

## The `docker` connection kind

A step that names no connection reaches the daemon the worker's own environment names, which is
the table above and nothing else. A `docker` connection is how a *document* names one instead,
and how a build reaches a registry:

| Field | What it holds |
| --- | --- |
| `host` | The daemon: `tcp://host:2376`, `ssh://user@host`, or `unix:///var/run/docker.sock`. Empty leaves the worker's own environment standing. |
| `tls_ca`, `tls_cert`, `tls_key` | The client TLS triple for a `tcp://` daemon, in PEM form. All three or none. |
| `registry` | The registry a push authenticates to, such as `ghcr.io`. Empty means Docker Hub. |
| `username`, `password` | The registry credential, together or not at all. |

A connection names a daemon, a registry credential, or both, and one that names neither is
refused. `dg connection check` proves whichever it holds: `docker version` against the daemon,
and a `docker login` followed straight by a `docker logout` against the registry, in a config
directory of its own so nothing about it persists.

```bash
dg connection create docker build-daemon \
  --set host=tcp://docker:2376 \
  --set "tls_ca=$(cat /certs/client/ca.pem)" \
  --set "tls_cert=$(cat /certs/client/cert.pem)" \
  --set "tls_key=$(cat /certs/client/key.pem)"
dg connection check build-daemon
```

`tls_key` and `password` are **sealed**: encrypted at rest, redacted in every API response, and
never an argument or an inherited variable. Each reaches the CLI and the Engine API as a 0600
file in a 0700 directory under the run's scratch space -- the TLS triple as `DOCKER_CERT_PATH`,
the login as a `DOCKER_CONFIG` of its own -- and both directories are removed when the step
leaves, on success, on failure and on cancellation.

**Every step of one stack names the same connection.** A stack exists only on the daemon that
was told to create it, so a `docker.compose.up` on one daemon and a `docker.compose.down` on
another tear down nothing. The `up`, the `docker.run` that drives it and the `down` all carry
the same `connection:`, and
[`examples/docker/docker-remote-daemon.yaml`](https://github.com/winterop-com/dirigent/blob/main/examples/docker/docker-remote-daemon.yaml)
is that document.

A connection names the daemon; it does not name the worker. A compose file and a build context
still live on the worker's own filesystem, so a pipeline that names one keeps
`requires.workers: [docker]` beside it exactly as one that does not.

## Files live in the run's work directory

A compose file, a build context and a bind mount are things a tool opens through the
filesystem, so they live in the run's
[work directory](operations.md#scratch-and-work) on the worker's own disk -- whatever the
artifact root is. Within it:

- a compose file is either inline `content` or a path relative to that directory (one an
  upstream `git.checkout` put there). Inline content is written under
  `compose/<step>[/<item>]/attempt-<n>`, so two compose steps of one run, and two items of one
  fan-out, never write over each other's document;
- a build context is a relative directory, with its Dockerfile relative to that.

`docker.run`'s `outputs` puts a file in either place. Each entry maps a name the container
wrote in its output mount to a target: a target carrying a URI scheme is copied to storage,
where it outlives the run, and a target without one is a path relative to the work directory,
which is how one step produces the compose file or the build context the next step opens.
`inputs` is always storage: a URI read into the read-only mount.

On the compose stack the daemon mounts that directory at the same path the worker sees it at,
because a bind is resolved on the daemon's filesystem rather than the worker's. It is local to
one worker, so a step that reads what another step put there must run on the same worker.

v1 targets compose files that reference **pre-built images**. A compose file with `build:`
stanzas needs its build contexts already in the work directory -- getting them there is the
pipeline's job.

## The compose lifecycle

This is the pattern the compose blocks are shaped around, and the reason `up` and `down` are
separate steps rather than one self-contained block:

- **`up` brings the stack up detached, and it persists.** The step returns once the stack is up
  (with `wait: true`, once every service is healthy) and reports the project's services and the
  network they share. The containers keep running for the rest of the run.
- **A later step drives it.** A `docker.run` step joins the compose network by name -- the up
  step reports it as `default_network` (`<project>_default`) -- and reaches the services on it.
- **`down` tears it down, even on failure.** A separate `docker.compose.down` step with
  `rule: all_done` runs whether the drive step passed or failed, so a stack is never left
  running. The engine already evaluates `all_done`; no "finally" primitive is needed.

Both blocks default their **project name** deterministically from the run id, so the `down`
addresses the exact project the `up` created with nothing wired between them, and two runs
never collide. On a **bring-up that does not succeed** -- a non-zero exit, a bring-up that ran
past its deadline, or a step that was cancelled -- the block itself best-effort tears the
half-built project down (`cleanup: true`) before leaving, so containers compose had already
started are never orphaned. A successful `up` is never torn down that way: it persists for the
rest of the run by design.

```yaml
steps:
  stack:
    block: docker.compose.up
    config:
      wait: true
      content: |
        services:
          api:
            image: nginx:alpine

  drive:
    block: docker.run
    depends_on: [stack]
    config:
      image: alpine:3
      network: "${steps.stack.output.default_network}"
      command: wget -qO- http://api/

  teardown:
    block: docker.compose.down
    depends_on: [drive]
    rule: all_done
    config:
      down_volumes: true
```

The full example is
[`examples/docker/docker-compose-stack.yaml`](https://github.com/winterop-com/dirigent/blob/main/examples/docker/docker-compose-stack.yaml).

## Building an image

`docker.build` shells out to `docker buildx build` -- BuildKit, its cache and multi-stage
builds come for free -- and reads the built image's id from an `--iidfile` rather than scraping
the log. The image lands in the **worker's own daemon store**, so a later `docker.run` or
`docker.compose.up` step on the same worker references it by tag.

### Pushing

`push: true` sends every tag the build produced to the registry a `docker` connection names.
It needs that connection: `push` with no `connection` is refused when the document is applied,
and a connection with no `username` and `password` is refused when the step starts. Neither is
a build that quietly produced a local image nobody can reach.

```yaml
build:
  block: docker.build
  config:
    context: context
    tags: ["ghcr.io/owner/app:1.2.3"]
    connection: ghcr
    push: true
```

The step logs in against a `DOCKER_CONFIG` directory of its own under scratch, with the
password on stdin rather than in an argument, pushes each tag with `docker push`, and logs out
again; the directory goes with the step. The worker's own docker config is never written to and
no session survives the step. The output carries `pushed`, the tags that reached the registry,
and `digests`, the digest the registry gave each of them where the CLI reported one -- a tag can
be moved and a digest cannot, so the digest is the only exact name for what was pushed. The
password is scrubbed out of every log line and every failure message.

[`examples/docker/docker-build-push.yaml`](https://github.com/winterop-com/dirigent/blob/main/examples/docker/docker-build-push.yaml)
is the worked document.

## The orphan reaper

`docker.compose.up` names its project `dirigent-<run id>` and compose labels every container of
it `com.docker.compose.project`, so a stack is addressable by the run that created it long after
that run has gone. Usually nothing is left: a `down` step with `rule: all_done` runs on any
outcome, and a failed `up` tears its own half-built project down. What is left over is what none
of that reached -- a worker that died mid-run, a pipeline cancelled between `up` and `down`, a
`down` step that never ran.

A worker sweeps for those on a cadence. Each pass lists the compose projects on its daemon,
reads the run id out of each project's name, and looks that run up:

- a run that is **still active** is never touched, whatever else is true;
- a run that is **terminal**, and a run the instance **no longer holds**, are both orphans;
- a project **younger than the grace** is left alone whatever its run says, because a stack whose
  `up` has only just returned is a stack whose `down` has not been reached yet. A project's age
  is its newest container's.

Each orphan is taken down with `docker compose -p <project> down -v --remove-orphans`, and each
one is one record: `kind: docker_reaped`, carrying the project, the run id and the run's status,
so `dg worker | dg format` shows what went. A project this instance did not create -- anything
whose name is not `dirigent-<32 hex digits>` -- is never listed as a candidate at all.

Two settings govern it:

| Setting | Default | What it does |
| --- | --- | --- |
| `docker_reap_interval` | `5m` | How often a pass runs. Zero turns the reaper off. |
| `docker_reap_grace` | `10m` | How old a project must be before a pass will consider it. |

A worker with no docker CLI on its PATH runs no pass at all, rather than one that fails every
five minutes.

The same pass runs on demand:

```bash
dg docker reap --dry-run | dg format
dg docker reap | dg format
```

`--dry-run` writes the same records and takes nothing down.

**The reaper only sees the daemon the worker sees.** With one dind sidecar per worker that is
exactly the stacks that worker created, which is the deployment this is written for. A worker
pointed at a shared daemon sees every dirigent project on it, including projects other workers
created -- which is correct, since the run lookup is the instance's own, but it means two
instances must not share one daemon.

## One daemon per pipeline

A stack brought up on worker A, or an image built there, is invisible to worker B and its
daemon. Give the docker-capable workers a `docker` tag (`dg worker --tag docker`, or
`DIRIGENT_WORKER_TAGS=docker`) and declare `requires.workers: [docker]` on the pipeline, so
`up`, the steps that drive it, `down`, and any `build` all meet the same daemon.
