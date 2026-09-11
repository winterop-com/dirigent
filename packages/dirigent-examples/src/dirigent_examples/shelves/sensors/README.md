# Sensor examples

Steps that wait for the world instead of doing something to it: each poke is one cheap,
read-only question, the run holds no worker slot between pokes, and `deadline` with
`on_timeout` says what a day without an answer means.

```bash
dg run --local examples/sensors/time-window.yaml --enable-unsafe shell.run
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [sensor-gate.yaml](sensor-gate.yaml) | `storage.exists` gating a load: wait for today's drop, and skip the day if it never lands. |
| [time-window.yaml](time-window.yaml) | The clock as a condition: hold until the local time is inside a window, in the window's own zone. |
