# Git

The `git.*` family puts an existing project into a run. It is one block today:

- [`git.checkout`](blocks.md#gitcheckout) clones a repository at a ref into the run's work
  directory and reports the commit it landed on.

Nothing else could do that. `storage.copy` moves one object at a time, the compose and build
blocks read only what is already in the work directory, and `shell.run` with a `git clone` is
an unsafe
block on a worker that happens to have git and a network. With a checkout, a downstream
[`docker.compose.up`](blocks.md#dockercomposeup) names its compose file, a
[`docker.build`](blocks.md#dockerbuild) names its context, and a transform names its files, all
relative to one directory.

The block's fields are the generated [block reference](blocks.md); this page is the family: the
connection kind that holds the remote, what happens to a credential, and what the block does
not do.

## This is an ordinary block

`git.checkout` does **not** declare `local_execution`, so no instance has to allowlist it. That
is a claim about the grant, not a convenience: the block writes only under the run's work
directory and reaches only the remote its connection names. It runs no command a document supplies,
inherits no worker environment a document names, and has no way to reach the host beyond git's
own network call. "Can edit pipelines" therefore does not become "can run code on the worker",
which is the boundary the unsafe allowlist exists to hold.

It still needs the worker to have `git` on its `PATH`, and `ssh` too for an ssh remote. The
worker image (`infra/Dockerfile`) installs both; a worker without them fails the step with a
sentence saying so rather than a stack trace.

## The `git` connection kind

A checkout step names a connection and never a URL. The connection carries the remote and, for
a private repository, the credential that reaches it -- sealed like every other connection
secret, encrypted at rest and redacted in every API response. Moving a pipeline from a fork to
the real repository is then an edit to one connection and to no pipeline.

There are three forms, and a connection is exactly one of them:

| Form | Fields | For |
| --- | --- | --- |
| public | `url` | A repository anyone can clone. Nothing is sealed because nothing needs to be. |
| token | `url`, `token`, optionally `username` | A personal, deploy or app token over `https://`. `username` defaults to `x-access-token`, which GitHub and GitLab both accept for a token. |
| ssh key | `url`, `ssh_key`, optionally `known_hosts` | A deploy key over `ssh://` (or the scp-like `git@host:owner/repo.git`). The key is an OpenSSH private key with no passphrase: nothing here can answer a prompt. |

A token on an ssh remote and a key on an https one are both refused when the connection is
written, because neither could ever work. So are two credentials at once.

```bash
dg connection create git my-project --set url=https://github.com/owner/repo.git
dg connection create git private-repo \
  --set url=https://github.com/owner/private.git --set token=ghp_...
dg connection check private-repo
```

A check lists the remote's branches, which is the smallest thing that proves both reach and
credential. A `--local` run has no instance to hold a connection, so a document run that way
carries one in its own `connections:` section -- which is what the
[examples](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/git) do.

## What happens to the credential

A credential reaches git, and reaches nothing else. In one paragraph:

**Never in argv.** Every process on the host can read another's command line, so nothing
secret is ever an argument. A token is written into a directory of its own under the run's
work directory, created `0700`, holding two `0600` files and a `0700` `GIT_ASKPASS` helper that
`cat`s the right one when git asks for a username or a password -- so the token is not in the
environment either, only in a file that one process may read. An ssh key is a `0600` file in
the same directory, named by `GIT_SSH_COMMAND`, with `IdentitiesOnly=yes` and `BatchMode=yes`
so ssh uses that key and never prompts. **Never in the checkout.** The remote is handed to git
with any userinfo stripped, and that stripped URL is what the clone writes into `.git/config`
and what the block reports as `remote`: a later reader of the run's work directory finds no
credential there. **Never in the log.** The token, the key, and the key's path are all scrubbed
out of every log line and every failure message the step produces, replaced by `***`.
**Never past the step.** The private directory is removed when the step leaves,
whether it succeeded, failed, or was cancelled.

Host keys follow the same shape. With `known_hosts` on the connection, they are written
alongside and `StrictHostKeyChecking=yes` pins the host to them. Without, the block uses
`accept-new`, which trusts the first key it sees -- fine for a host you already reach a hundred
other ways, and worth pinning for anything else.

## Where a checkout lands

A checkout is a directory a tool opens, not bytes in storage, so it lands in the run's
[work directory](operations.md#scratch-and-work) on the worker's own filesystem -- whatever
the artifact root is. That directory is local to the worker that made it: a step reading the
checkout must run on the same worker, which on a single-worker instance it always does.

`target` is a path inside that directory -- never absolute, never climbing out -- and left
unset it is the step's own name. So a step named `source` puts the working tree at `source/`,
and the output reports `source` as the path a downstream block names:

```yaml
steps:
  source:
    block: git.checkout
    config:
      connection: my-project
      ref: v2.1.0
      target: source

  build:
    block: docker.build
    depends_on: [source]
    config:
      context: source
      tags: ["myapp:${steps.source.output.commit}"]
```

On the reference stack this is what makes a checkout visible to the docker family at all. The
worker's daemon is a `docker:dind` sidecar, and it mounts the same `work` volume at the same
path as the worker, so a directory the checkout wrote is a directory the daemon can read.
A bind mount is resolved on the *daemon's* filesystem: point a worker at a daemon that cannot
see the work root and a build context under it is an empty directory. See
[docker.md](docker.md#the-daemon-these-blocks-reach).

## Refs, depth and submodules

`ref` takes a branch, a tag, or a full 40-character commit sha, and unset takes the remote's
default branch. A branch or a tag is what `clone --branch` resolves; a sha is not in the ref
namespace at all, so the block creates the repository, fetches that one commit, and detaches
the working tree onto it. Either way the output's `commit` is the full sha, which is the only
exact name for what was checked out -- a branch moves and a tag can be moved.

`depth` is `1` by default: the one commit the ref points at and none of its history, which is
what a build wants and a fraction of the bytes. `depth: 0` fetches the whole history, which a
step that reads the log or runs `git describe` needs. `submodules: true` checks out submodules
recursively, at the same depth.

A checkout is **idempotent**. A second run into the same target, at the same commit, costs one
ref listing and reports the same commit rather than cloning again; anything else -- a different
ref, a directory holding something that is not that checkout -- replaces the target.

Git's own output reaches the run log as it prints, so a long clone is visible working rather
than silent until it exits, and the whole of each stream is an artifact the output names as
`stdout_uri` and `stderr_uri`.

## The limits

- **Read only.** There is no `git.push`, no commit, no tag, no branch creation. A pipeline
  reads a repository; it does not write one. That waits until something needs it.
- **One remote.** A connection is one repository. A pipeline that needs three checks out three
  times, into three targets.
- **No passphrase on a key.** Nothing in a run can answer a prompt, so a deploy key is
  generated without one.
- **One worker.** A checkout on worker A is invisible to worker B. Give the docker-capable
  workers a `docker` tag (`dg worker --tag docker`) and declare `requires.workers: [docker]`,
  so a pipeline that checks out and then builds lands on one of them, the same constraint the
  `docker.*` family has.
