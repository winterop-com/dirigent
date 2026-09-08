# Docker examples

The `docker.*` family runs containers on the worker, which is why each block needs its id in
`DIRIGENT_ENABLED_UNSAFE_BLOCKS` before an instance will run it, and a daemon the worker can
reach. [docs/docker.md](../../docs/docker.md) is the family's home, and
[docs/security.md](../../docs/security.md) says what mounting the socket grants.

```bash
dg run --local examples/docker/docker-hello.yaml --enable-unsafe docker.run
```

The last two documents on the shelf **fail on purpose**: they are here for what a broken
stack and a failed drive step leave behind, which in both cases is nothing.

## Pipelines

| File | What it teaches |
| --- | --- |
| [docker-hello.yaml](docker-hello.yaml) | One command in one container: the image pulled first, no network, the streams collected. |
| [docker-ticker.yaml](docker-ticker.yaml) | The live log: a container talking while it works, each probe appending what arrived since the last one. |
| [docker-compose-stack.yaml](docker-compose-stack.yaml) | A whole stack: `docker.compose.up` brings it up, a `docker.run` step joins its network, and `docker.compose.down` with `rule: all_done` tears it down on any outcome. |
| [docker-compose-database.yaml](docker-compose-database.yaml) | A database driven for real: `wait: true` turns a healthcheck into a gate, a `psql` container writes and reads rows, and the volumes go with the teardown. |
| [docker-compose-file.yaml](docker-compose-file.yaml) | The other compose form: a file an earlier step wrote into the run's scratch space, named by its scratch-relative path. |
| [docker-compose-profiles-env.yaml](docker-compose-profiles-env.yaml) | Parameters reaching the stack: a variable compose interpolates, and a profile that decides whether the optional service exists. |
| [docker-build-run.yaml](docker-build-run.yaml) | An image built on the worker and run by tag, because a built image lives only in the store of the daemon that built it. |
| [docker-build-push.yaml](docker-build-push.yaml) | Pushing what was built: a `docker` connection holding a registry credential, and the tags and digests that come back. |
| [docker-remote-daemon.yaml](docker-remote-daemon.yaml) | Naming the daemon: a `docker` connection with a host and its client TLS, on every step of one stack's lifecycle. |
| [docker-compose-failing-up.yaml](docker-compose-failing-up.yaml) | A bring-up that fails, and the containers it does not leave behind: the block tears its own half-built project down. |
| [docker-run-failing-teardown.yaml](docker-run-failing-teardown.yaml) | A drive step that fails: the run is failed, the teardown ran anyway, and the daemon holds nothing. |
