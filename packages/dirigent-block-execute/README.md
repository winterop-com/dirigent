# dirigent-block-execute

The execute block family: everything that runs something on the worker. `shell.run` a command,
`docker.run` a container, `docker.compose.up` and `docker.compose.down` a stack, `docker.build`
an image, and `git.checkout` a working tree.

These are the blocks that declare themselves unsafe, because what they run is the step's own
code rather than a call to a service. The family registers the `docker` and `git` connection
kinds, and carries the shared internals the six have in common: process containment, output
capture, the environment allowlist, and the on-disk credential material a tool has to be
handed. `dg reap` uses the same internals to clear what a run left behind.
