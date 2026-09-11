# Failure examples

How a run goes wrong on purpose: retries and the budget they spend, a timeout that ends an
attempt, a step allowed to fail without failing the run, and the always-runs cleanup edge.
Seeing these settle red is the point; a corpus where everything is green teaches nothing
about reading a failure.

```bash
dg run --local examples/failure/retries.yaml
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [retries.yaml](retries.yaml) | The retry policy: attempts, backoff, and an error class that says whether trying again could ever help. |
| [retry-budget.yaml](retry-budget.yaml) | The budget behind the policy: an unknown failure (a non-zero exit) is retried too, and a hopeless step spends every attempt before it fails. |
| [step-timeout.yaml](step-timeout.yaml) | A timeout ends the attempt, and the policy decides whether another one starts. |
| [optional-step.yaml](optional-step.yaml) | `completed_with_errors`: a step that may fail without failing the run, and the third status that says so. |
| [error-handler.yaml](error-handler.yaml) | The cleanup edge: alert on failure, and always release the lock, however the load went. |
