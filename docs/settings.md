<!-- Generated from dirigent_core.config.Settings by dirigent_core.configdocs. Do not edit. -->
# Settings reference

Every setting an instance has, its default, and what it does. This page is generated from the
settings model, so it cannot drift from the code: a setting added either shows up here or
fails the build.

Each one is read from three places, most specific first: a `DIRIGENT_`-prefixed environment
variable, the YAML configuration file, then the default below. `dg init` writes a
`dirigent.example.yaml` holding this same list, commented out, beside the working
`dirigent.yaml` -- so the file a person edits stays short and the whole surface is still
one file away.

| Setting | Environment | Default | What it does |
| --- | --- | --- | --- |
| `environment` | `DIRIGENT_ENVIRONMENT` | `"local"` | Which deployment this instance believes it is, reported on telemetry. |
| `database_url` | `DIRIGENT_DATABASE_URL` | `"sqlite+aiosqlite:///./.dirigent/state/dirigent.db"` | Where the instance's own state lives, as a SQLAlchemy async URL. |
| `database_echo` | `DIRIGENT_DATABASE_ECHO` | `false` | Echo every SQL statement to the process log. Debugging only; it is very loud. |
| `database_pool_size` | `DIRIGENT_DATABASE_POOL_SIZE` | `12` | How many database connections one process keeps open. Ignored by SQLite. |
| `database_max_overflow` | `DIRIGENT_DATABASE_MAX_OVERFLOW` | `4` | Connections the pool may open beyond `database_pool_size` under a burst. |
| `database_pool_timeout` | `DIRIGENT_DATABASE_POOL_TIMEOUT` | `"30s"` | How long a checkout waits for a free connection before failing loudly. |
| `database_pool_recycle` | `DIRIGENT_DATABASE_POOL_RECYCLE` | `"30m"` | Recycle a pooled connection older than this; unset disables recycling. |
| `host` | `DIRIGENT_HOST` | `"127.0.0.1"` | The address the API server binds. A container needs `0.0.0.0` to be reachable. |
| `port` | `DIRIGENT_PORT` | `3333` | The port the API server binds. |
| `api_prefix` | `DIRIGENT_API_PREFIX` | `"/api/v1"` | Where the versioned REST API is mounted. `/hooks/{token}` is not under it. |
| `ui_enabled` | `DIRIGENT_UI_ENABLED` | `true` | Whether the server serves the bundled web UI beside the API. |
| `log_level` | `DIRIGENT_LOG_LEVEL` | `"INFO"` | How loud the process log is. This is the process log; a run's own telemetry is the `log_entries` table, and a CLI `-v` or `--debug` flag wins over this. |
| `log_format` | `DIRIGENT_LOG_FORMAT` | `"console"` | How a command spells a log line: `console` for a person, `json` for a collector. |
| `artifact_root` | `DIRIGENT_ARTIFACT_ROOT` | `"file://./.dirigent/state/artifacts"` | Default storage backend URI prefix for run scratch space and artifacts. |
| `work_root` | `DIRIGENT_WORK_ROOT` | `"./.dirigent/state/work"` | Directory on this worker's own filesystem where a run's local working files go. |
| `storage_connections` | `DIRIGENT_STORAGE_CONNECTIONS` | `{}` | Which connection configures each storage scheme, as `scheme -> connection code`. |
| `inline_artifact_max` | `DIRIGENT_INLINE_ARTIFACT_MAX` | `16384` | Outputs at or below this serialized size are stored inline instead of as a file. |
| `inline_capture` | `DIRIGENT_INLINE_CAPTURE` | `8192` | How much of a captured stream a block may inline in its output. |
| `secret_key` | `DIRIGENT_SECRET_KEY` | `null` | Envelope key for connection secrets; required before any secret is stored. |
| `worker_concurrency` | `DIRIGENT_WORKER_CONCURRENCY` | `8` | How many step attempts one worker process executes at once. |
| `worker_tags` | `DIRIGENT_WORKER_TAGS` | `[]` | Capability tags a worker advertises to the claim query. |
| `worker_name` | `DIRIGENT_WORKER_NAME` | `null` | Registry name of this worker; defaults to hostname plus process id. |
| `lease` | `DIRIGENT_LEASE` | `"1m"` | How long a claimed attempt's lease is valid before the sweeper may reclaim it. |
| `heartbeat` | `DIRIGENT_HEARTBEAT` | `"15s"` | How often a worker refreshes the leases it holds and its registry row. |
| `claim_idle` | `DIRIGENT_CLAIM_IDLE` | `"500ms"` | How long a worker waits before asking for work again when the queue is empty. |
| `log_flush_interval` | `DIRIGENT_LOG_FLUSH_INTERVAL` | `"1s"` | How often a running attempt's buffered log entries are written to the run. |
| `log_entries_per_attempt` | `DIRIGENT_LOG_ENTRIES_PER_ATTEMPT` | `1000` | How many entries one attempt may log before the rest are dropped with one warning. |
| `log_flush_batch` | `DIRIGENT_LOG_FLUSH_BATCH` | `100` | How many buffered entries write themselves without waiting for the flush interval. |
| `sweep_interval` | `DIRIGENT_SWEEP_INTERVAL` | `"30s"` | How often a worker runs the crash-recovery sweeper over expired leases. |
| `stuck_run` | `DIRIGENT_STUCK_RUN` | `"1h"` | A running run with no attempt progress for this long is flagged as stuck. |
| `stale_worker` | `DIRIGENT_STALE_WORKER` | `"15m"` | A worker whose registry row is older than this has that row reaped by the sweeper. |
| `docker_reap_interval` | `DIRIGENT_DOCKER_REAP_INTERVAL` | `"5m"` | How often a docker-capable worker looks for compose stacks whose run has ended. |
| `docker_reap_grace` | `DIRIGENT_DOCKER_REAP_GRACE` | `"10m"` | How old a compose project must be before the reaper will consider it at all. |
| `retention_runs` | `DIRIGENT_RETENTION_RUNS` | `null` | How long a settled run is kept, with its items, attempts, artifacts and alerts. |
| `retention_logs` | `DIRIGENT_RETENTION_LOGS` | `null` | How long a log entry is kept, for runs too young to be pruned themselves. |
| `retention_deliveries` | `DIRIGENT_RETENTION_DELIVERIES` | `null` | How long a webhook delivery is kept. |
| `retention_firings` | `DIRIGENT_RETENTION_FIRINGS` | `null` | How long a schedule firing is kept. |
| `retention_notifications` | `DIRIGENT_RETENTION_NOTIFICATIONS` | `null` | How long an alert that was sent is kept, for runs too young to be pruned themselves. |
| `retention_scratch` | `DIRIGENT_RETENTION_SCRATCH` | `true` | Whether pruning a run also deletes its artifacts from storage. |
| `retention_interval` | `DIRIGENT_RETENTION_INTERVAL` | `"1h"` | How often the scheduler sweeps whatever the retention ages have outlived. |
| `retention_batch` | `DIRIGENT_RETENTION_BATCH` | `500` | How many rows of one family a single sweep deletes before committing. |
| `lost_job_max_gone` | `DIRIGENT_LOST_JOB_MAX_GONE` | `3` | Consecutive GONE probes before the lost-job policy fails a waiting attempt. |
| `enabled_unsafe_blocks` | `DIRIGENT_ENABLED_UNSAFE_BLOCKS` | `[]` | Block ids permitted to execute code on a worker; empty means none. |
| `scheduler_enabled` | `DIRIGENT_SCHEDULER_ENABLED` | `true` | Whether `dg server` embeds the scheduler rather than leaving it to its own process. |
| `scheduler_tick` | `DIRIGENT_SCHEDULER_TICK` | `"5s"` | How often the leader asks the database which schedules are due. |
| `scheduler_misfire_grace` | `DIRIGENT_SCHEDULER_MISFIRE_GRACE` | `"5m"` | How late a firing may be before it counts as a misfire: fire once, advance, no catchup storm. |
| `scheduler_lock_key` | `DIRIGENT_SCHEDULER_LOCK_KEY` | `1684632167` | The advisory-lock key leadership is taken on; only PostgreSQL has one to take. |
| `apply_dir` | `DIRIGENT_APPLY_DIR` | `null` | A directory of pipeline documents the server applies at boot; unset applies nothing. |
| `apply_prune` | `DIRIGENT_APPLY_PRUNE` | `false` | Whether the boot apply also deactivates directory-provenance pipelines absent from it. |
| `apply_lock_key` | `DIRIGENT_APPLY_LOCK_KEY` | `1684632161` | The advisory-lock key the boot apply is serialised on, distinct from the scheduler's. |
| `notification_max_attempts` | `DIRIGENT_NOTIFICATION_MAX_ATTEMPTS` | `5` | How many times a notification delivery is retried before it is recorded as failed. |
| `notification_backoff` | `DIRIGENT_NOTIFICATION_BACKOFF` | `"30s"` | The delay after a notification's first failed delivery; later ones double from it. |
| `notification_lease` | `DIRIGENT_NOTIFICATION_LEASE` | `"1m"` | How long a claimed notification's lease is valid before another worker may take it. |
| `webhook_max_payload` | `DIRIGENT_WEBHOOK_MAX_PAYLOAD` | `1048576` | The largest body the webhook intake will read; reading stops one byte past it. |
| `webhook_intake_rate_per_minute` | `DIRIGENT_WEBHOOK_INTAKE_RATE_PER_MINUTE` | `120` | How fast one *offered* token may deliver, before anything is looked up. |
| `login_rate_per_minute` | `DIRIGENT_LOGIN_RATE_PER_MINUTE` | `10` | How many login attempts one address, and one username, get a minute. |
| `alert_base_url` | `DIRIGENT_ALERT_BASE_URL` | `null` | The externally reachable base URL, so an alert can link back to the run it is about. |
