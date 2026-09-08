# Git examples

`git.checkout` puts an existing project into a run. It clones a repository at a ref into the
run's scratch space and reports the commit it landed on, so a `docker.build` names its context,
a `docker.compose.up` names its compose file, and a transform names its files, all by a path
relative to the checkout. [docs/git.md](../../docs/git.md) is the family's home.

It is an **ordinary** block: it writes only under the run's scratch space and reaches only the
remote its connection names, so no id has to be allowlisted to run it.

```bash
dg run --local examples/git/git-checkout-public.yaml
```

The other two documents drive the `docker.*` family off a checkout, so they need a Docker
daemon and the usual allowlist; each says so in its own header.

Every document here carries its `git` connection in a `connections:` section, because a
`--local` run has no instance to hold one. On a server the connection is created once and the
document names it:

```bash
dg connection create git my-project --set url=https://github.com/owner/repo.git
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [git-checkout-public.yaml](git-checkout-public.yaml) | The block on its own: a public remote, a shallow checkout at the default branch, and the commit, ref, target and remote a downstream step reads. |
| [git-checkout-build.yaml](git-checkout-build.yaml) | Starting an existing project: the repository's own Dockerfile built from the checkout, and the image run once to prove it starts. |
| [git-checkout-compose.yaml](git-checkout-compose.yaml) | A stack from somebody else's compose file: the checkout is what puts it where the compose CLI can open it, and the docker family's up/drive/down lifecycle is unchanged. |
