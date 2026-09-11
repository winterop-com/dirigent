# Execute examples

A shell step that runs code on the worker, which is why it needs its entry in
`DIRIGENT_ENABLED_UNSAFE_BLOCKS` before an instance will run it. The container family --
`docker.run`, `docker.compose.*` and `docker.build` -- now lives on its own shelf,
[docker/](../docker).

```bash
dg run --local examples/execute/long-log.yaml --enable-unsafe shell.run
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [long-log.yaml](long-log.yaml) | A step that logs enough to scroll, for exercising the terminal pane rather than reading about it. |
