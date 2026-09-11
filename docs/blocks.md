<!-- Generated from the installed block catalog by dirigent_core.blockdocs. Do not edit. -->

# Block reference

Every block an instance has, with the config it takes and the output it produces. This page is
generated from the live catalog -- the same one `GET /blocks` serves, the same one the UI
builds forms from -- so it cannot drift from the code: a field added to a block either shows
up here or fails the build.

What a block is, and the contract behind these tables, is in
[the design document](design.md#2-the-five-plugin-surfaces). The short version:

- An **operator** does work. It either finishes and returns its output, or hands back a
  handle for the engine to probe, which is how a step waits for an hour without holding a
  worker for an hour.
- A **sensor** waits for the world. Each poke is one short, read-only observation, and "not
  yet" is the expected answer rather than a failure. `poll`, `deadline`, and `on_timeout` are
  step-level engine semantics, uniform across every sensor and never buried in a block's own
  config.

**Group** is the shelf a block declares for itself, and what every catalog is arranged by: the
four transform verbs are one `transform` group, and `shell.run`, `docker.run` and
`pipeline.run` are `execute`. A block that declares none takes the first half of its id.

Two properties are worth reading before a block is used:

- **Idempotent** says whether re-running the block after an unclear failure is safe. The
  engine spends the step's retry budget either way, so this is what to read before writing
  `max_attempts` above 1.
- **Local execution** says the block runs code on the worker. The engine refuses such a block
  unless the instance names it in `DIRIGENT_ENABLED_UNSAFE_BLOCKS`, because "can edit
  pipelines" must never quietly mean "can run code on workers".

| Block | Kind | Group | Summary | Contributed by |
| --- | --- | --- | --- | --- |
| [`convert.arrow`](#convertarrow) | operator | transform | Convert between parquet and the text formats. | `parquet` |
| [`convert.std`](#convertstd) | operator | transform | Convert between json, ndjson, csv, yaml and xml. | `builtin` |
| [`docker.build`](#dockerbuild) | operator | execute | Build a container image on the worker. | `builtin` |
| [`docker.compose.down`](#dockercomposedown) | operator | execute | Tear a compose stack down on the worker. | `builtin` |
| [`docker.compose.up`](#dockercomposeup) | operator | execute | Bring a compose stack up on the worker. | `builtin` |
| [`docker.run`](#dockerrun) | operator | execute | Run a container on the worker. | `builtin` |
| [`filter.jq`](#filterjq) | operator | transform | Keep the elements of a list a jq program answers true for. | `builtin` |
| [`git.checkout`](#gitcheckout) | operator | git | Check a repository out into the run's work directory. | `builtin` |
| [`http.ready`](#httpready) | sensor | http | Wait for an HTTP endpoint to report ready. | `builtin` |
| [`http.request`](#httprequest) | operator | http | Call an HTTP endpoint. | `builtin` |
| [`kafka.consume`](#kafkaconsume) | sensor | kafka | Wait for messages on a Kafka topic. | `builtin` |
| [`kafka.produce`](#kafkaproduce) | operator | kafka | Publish records to a Kafka topic. | `builtin` |
| [`log.write`](#logwrite) | operator | log | Write a line to the run's log. | `builtin` |
| [`map.jq`](#mapjq) | operator | transform | Replace every element of a list with what a jq program makes of it. | `builtin` |
| [`pipeline.run`](#pipelinerun) | operator | execute | Run another pipeline on this instance. | `builtin` |
| [`rabbitmq.consume`](#rabbitmqconsume) | sensor | rabbitmq | Wait for messages on a RabbitMQ queue. | `builtin` |
| [`rabbitmq.publish`](#rabbitmqpublish) | operator | rabbitmq | Publish one message to an exchange. | `builtin` |
| [`report.render`](#reportrender) | operator | report | Render text from a Jinja template. | `builtin` |
| [`shell.run`](#shellrun) | operator | execute | Run a command on the worker. | `builtin` |
| [`sql.execute`](#sqlexecute) | operator | sql | Run SQL statements against a database in one transaction. | `builtin` |
| [`sql.query`](#sqlquery) | operator | sql | Run one SQL statement and return its rows. | `builtin` |
| [`storage.copy`](#storagecopy) | operator | storage | Copy an object from one URI to another. | `builtin` |
| [`storage.exists`](#storageexists) | sensor | storage | Wait for an object to appear at a URI. | `builtin` |
| [`storage.read`](#storageread) | operator | storage | Read an object from a storage URI as a value. | `builtin` |
| [`storage.write`](#storagewrite) | operator | storage | Write a value or text to a storage URI. | `builtin` |
| [`time.sleep`](#timesleep) | sensor | time | Wait a fixed duration. | `builtin` |
| [`time.window`](#timewindow) | sensor | time | Wait until the local clock is inside a time window. | `builtin` |
| [`transform.jq`](#transformjq) | operator | transform | Reshape a value with a jq program. | `builtin` |
| [`validate.schema`](#validateschema) | operator | validate | Validate a value against a JSON Schema. | `builtin` |
| [`value.const`](#valueconst) | operator | value | Emit a fixed value. | `builtin` |
| [`webhook.post`](#webhookpost) | operator | webhook | POST a JSON body, optionally HMAC-signed. | `builtin` |

## Operators

### `convert.arrow`

Convert between parquet and the text formats.

Contributed by `parquet`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string (storage-uri)` | yes |  | The URI the bytes to re-encode are read from. |
| `target` | `string (storage-uri)` | yes |  | The URI the re-encoded bytes are written to, replacing whatever is there. |
| `from` | `string` | yes |  | The format the source is in, named as the engine names it. |
| `to` | `string` | yes |  | The format to produce. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes |  | -- |
| `target` | `string` | yes |  | -- |
| `bytes_written` | `integer` | yes |  | -- |

### `convert.std`

Convert between json, ndjson, csv, yaml and xml.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string (storage-uri)` | yes |  | The URI the bytes to re-encode are read from. |
| `target` | `string (storage-uri)` | yes |  | The URI the re-encoded bytes are written to, replacing whatever is there. |
| `from` | `string` | yes |  | The format the source is in, named as the engine names it. |
| `to` | `string` | yes |  | The format to produce. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes |  | -- |
| `target` | `string` | yes |  | -- |
| `bytes_written` | `integer` | yes |  | -- |

### `docker.build`

Build a container image on the worker.

Contributed by `builtin`. Not idempotent. **Runs code on the worker**, so the instance must allowlist its id.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `context` | `string` | yes |  | The build context, as a directory inside the run's work directory; never absolute, never climbing out. |
| `dockerfile` | `string` |  | `"Dockerfile"` | The Dockerfile, as a path relative to the context. |
| `tags` | `string[]` |  |  | Tags to give the built image (`--tag`); a later step references the image by one of them. |
| `build_args` | `object of string` |  |  | Build arguments the Dockerfile reads (`--build-arg`). |
| `target` | `string or null` |  | `null` | The stage to stop at in a multi-stage build (`--target`). |
| `platform` | `string or null` |  | `null` | The platform to build for, such as `linux/amd64` (`--platform`). |
| `pull` | `boolean` |  | `false` | Always attempt to pull a newer version of the base image (`--pull`). |
| `no_cache` | `boolean` |  | `false` | Build every layer from scratch, ignoring the cache (`--no-cache`). |
| `push` | `boolean` |  | `false` | Push every tag the build produced to the registry the connection names. |
| `connection` | `string or null` |  | `null` | A `docker` connection naming the daemon to build on, the registry to push to, or both. |
| `env` | `object of string` |  |  | Variables set for the CLI itself, such as BuildKit's own toggles. |
| `env_allowlist` | `string[]` |  |  | Worker environment variables the CLI is allowed to inherit; never the instance's `DIRIGENT_*`. |
| `command_path` | `string[]` |  |  | The CLI to invoke, for a host that wraps buildx. |
| `timeout` | `string (humane-duration)` |  | `"30m"` | The overall deadline on the build, after which it is killed as transient. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `image_id` | `string` | yes |  | The built image's id, read from the `--iidfile` the daemon wrote, not scraped from the log. |
| `tags` | `string[]` |  |  | The tags the image was given, by which a later step on the same worker references it. |
| `size_bytes` | `integer` |  | `0` | The image's size on disk, from the daemon; zero when it could not be read. |
| `pushed` | `string[]` |  |  | The tags that reached the registry, empty when the step pushed nothing. |
| `digests` | `object of string` |  |  | The registry's digest for each pushed tag, for the tags the CLI reported one for. |
| `build_log_uri` | `string` | yes |  | Where the whole of the build log (buildx's progress on stderr) was written. |
| `stdout_uri` | `string` | yes |  | Where the whole of the CLI's stdout was written. |

### `docker.compose.down`

Tear a compose stack down on the worker.

Contributed by `builtin`. Not idempotent. **Runs code on the worker**, so the instance must allowlist its id.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `project_name` | `string or null` |  | `null` | The compose project (`-p`). Defaults to the same deterministic name `up` derives from |
| `file` | `string or null` |  | `null` | A compose file, only if the CLI needs `-f` to resolve the project; a project tears down |
| `content` | `string or null` |  | `null` | A compose file inline, written to the run's work directory, for the same reason as `file`. |
| `profiles` | `string[]` |  |  | Compose profiles to activate, only meaningful alongside a `file`. |
| `env_files` | `string[]` |  |  | Env files for compose to read, as paths inside the run's work directory (`--env-file`). |
| `env` | `object of string` |  |  | Variables set for the CLI itself, such as those a compose file interpolates. |
| `env_allowlist` | `string[]` |  |  | Worker environment variables the CLI is allowed to inherit; never the instance's `DIRIGENT_*`. |
| `down_volumes` | `boolean` |  | `false` | Also remove the named volumes the stack declared (`-v`). |
| `down_timeout` | `string (humane-duration)` |  | `"10s"` | How long to wait for a container to stop before killing it (`--timeout`). |
| `down_remove_images` | `"none" or "local" or "all"` |  | `"none"` | Which images to remove: `none`, `local` (only untagged), or `all` (`--rmi`). |
| `remove_orphans` | `boolean` |  | `true` | Remove containers for services no longer in the compose file (`--remove-orphans`). |
| `connection` | `string or null` |  | `null` | A `docker` connection naming the daemon this stack runs on. |
| `command_path` | `string[]` |  |  | The CLI to invoke, for a host that spells it `docker-compose` or wraps it. |
| `timeout` | `string (humane-duration)` |  | `"10m"` | The overall deadline on the CLI invocation, after which it is killed as transient. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `project` | `string` | yes |  | The compose project torn down. |
| `torn_down` | `boolean` |  | `true` | Always true: the step returns only once the stack is down. |
| `stdout_uri` | `string` | yes |  | Where the whole of the CLI's stdout was written. |
| `stderr_uri` | `string` | yes |  | Where the whole of the CLI's stderr was written. |

### `docker.compose.up`

Bring a compose stack up on the worker.

Contributed by `builtin`. Not idempotent. **Runs code on the worker**, so the instance must allowlist its id.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `file` | `string or null` |  | `null` | The compose file, as a path inside the run's work directory; never absolute, never climbing out. |
| `content` | `string or null` |  | `null` | The compose file inline, written into the run's work directory before the CLI runs. |
| `project_name` | `string or null` |  | `null` | The compose project (`-p`). Defaults to a deterministic name derived from the run id, |
| `profiles` | `string[]` |  |  | Compose profiles to activate (`--profile`). |
| `env_files` | `string[]` |  |  | Env files for compose to read, as paths inside the run's work directory (`--env-file`). |
| `env` | `object of string` |  |  | Variables set for the CLI itself, such as those a compose file interpolates. |
| `env_allowlist` | `string[]` |  |  | Worker environment variables the CLI is allowed to inherit. |
| `wait` | `boolean` |  | `false` | Wait until every service is running and healthy before the step returns (`--wait`). |
| `wait_timeout` | `string (humane-duration)` |  | `"5m"` | How long `--wait` may wait before it gives up. |
| `remove_orphans` | `boolean` |  | `true` | Remove containers for services no longer in the compose file (`--remove-orphans`). |
| `pull` | `"always" or "missing" or "never"` |  | `"missing"` | When to pull images: `missing` pulls only what is absent, the compose default. |
| `cleanup` | `boolean` |  | `true` | On a bring-up that does not succeed, best-effort `down` the same project before leaving. |
| `command_path` | `string[]` |  |  | The CLI to invoke, for a host that spells it `docker-compose` or wraps it. |
| `connection` | `string or null` |  | `null` | A `docker` connection naming the daemon this stack runs on. |
| `socket_path` | `string or null` |  | `null` | The daemon socket the status read speaks to, when neither the default nor `DOCKER_HOST` is right. |
| `api_timeout` | `string (humane-duration)` |  | `"1m"` | How long one call to the daemon for the status read may take. |
| `timeout` | `string (humane-duration)` |  | `"10m"` | The overall deadline on the CLI invocation, after which it is killed as transient. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `project` | `string` | yes |  | The compose project brought up. |
| `services` | `object[]` |  |  | Every service's container, from the Engine API. |
| `networks` | `string[]` |  |  | The docker networks the project's containers are attached to, by the names the daemon knows. |
| `default_network` | `string` | yes |  | The project's default network, which a downstream `docker.run` names to join the stack. |
| `up` | `boolean` |  | `true` | Always true: the step returns only once the stack is up. |
| `compose_file` | `string` | yes |  | The compose file the CLI was given, as a path inside the run's work directory. |
| `stdout_uri` | `string` | yes |  | Where the whole of the CLI's stdout was written. |
| `stderr_uri` | `string` | yes |  | Where the whole of the CLI's stderr was written. |

### `docker.run`

Run a container on the worker.

Contributed by `builtin`. Not idempotent. **Runs code on the worker**, so the instance must allowlist its id. Polls every 2s unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `image` | `string` | yes |  | The image reference, tag included; `latest` is assumed when none is given. |
| `argv` | `string[]` |  |  | The command as an argument vector, which replaces the image's `CMD`. |
| `command` | `string or null` |  | `null` | The command as a shell string, run through `/bin/sh -c` inside the container. |
| `workdir` | `string or null` |  | `null` | The working directory inside the container, overriding the image's own. |
| `env` | `object of string` |  |  | Variables set explicitly for this container. |
| `env_allowlist` | `string[]` |  |  | Worker environment variables this container is allowed to inherit. |
| `inputs` | `object of string` |  |  | Files to stage into the read-only input mount, as `name inside the mount -> storage URI`. |
| `outputs` | `object of string` |  |  | Files the container writes to the output mount, as `name inside the mount -> target`. |
| `inputs_path` | `string` |  | `"/dirigent/inputs"` | Where the staged inputs appear inside the container. |
| `outputs_path` | `string` |  | `"/dirigent/outputs"` | Where the container is expected to write its declared outputs. |
| `network` | `string` |  | `"none"` | The daemon's network mode. It defaults to `none`: an image the pipeline named should not reach the worker's network, or anything the worker can reach, unless the step says so. |
| `pull` | `boolean` |  | `false` | Pull the image before creating the container, rather than requiring it to be present. |
| `memory` | `string or integer or null` |  | `null` | A hard memory limit, such as `64mb`; the container is OOM-killed rather than the worker. |
| `cpus` | `number or null` |  | `null` | A CPU quota expressed the way `docker run --cpus` expresses it. |
| `nano_cpus` | `integer or null` |  | `null` | The same quota expressed the way the daemon counts it, for a config that prefers exactness. |
| `pids_limit` | `integer or null` |  | `null` | A cap on how many processes the container may create. |
| `connection` | `string or null` |  | `null` | A `docker` connection naming the daemon this container runs on. |
| `socket_path` | `string or null` |  | `null` | The daemon socket, when neither the default nor `DOCKER_HOST` is right. |
| `api_timeout` | `string (humane-duration)` |  | `"1m"` | How long one call to the daemon may take. This is not the container's runtime: the container runs under the step's deadline, which the engine owns and this block never waits on. |
| `pull_timeout` | `string (humane-duration)` |  | `"10m"` | How long a pull may take, which is a different order of magnitude from an API call. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `exit_code` | `integer` | yes |  | -- |
| `stdout` | `string` | yes |  | The head of what the container printed, cut at the instance's inline capture size. |
| `stderr` | `string` | yes |  | The head of what the container printed to stderr, cut the same way. |
| `stdout_uri` | `string` | yes |  | Where the whole of stdout was written; never truncated, whatever the field above holds. |
| `stderr_uri` | `string` | yes |  | Where the whole of stderr was written; never truncated either. |
| `stdout_bytes` | `integer` | yes |  | How much the container printed to stdout altogether, inlined or not. |
| `stderr_bytes` | `integer` | yes |  | How much it printed to stderr altogether. |
| `stdout_truncated` | `boolean` | yes |  | Whether `stdout` above is short of the stream. Only the inline copy is ever cut. |
| `stderr_truncated` | `boolean` | yes |  | Whether `stderr` above is short of the stream, which is an independent question. |
| `container_id` | `string` | yes |  | -- |
| `image` | `string` | yes |  | -- |
| `outputs` | `object of string` |  |  | Where each declared output was written, by the name the config gave it: the storage URI, or the path relative to the run's work directory it landed at. |

### `filter.jq`

Keep the elements of a list a jq program answers true for.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `input` | `any` | yes |  | The value to work on, written inline or referenced from an earlier step's output. |
| `program` | `string` | yes |  | The jq program this step runs. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` |  | `null` | The reshaped value, which a later step reads or hands to `storage.write`. |

### `git.checkout`

Check a repository out into the run's work directory.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `git` connection naming the remote and holding its credential. |
| `ref` | `string or null` |  | `null` | The branch, tag or full commit sha to land on. Unset takes the remote's default branch. |
| `target` | `string` |  | `""` | The directory the checkout lands in, inside the run's work directory; never absolute, never climbing out. Empty takes the step's own name, so a step named `checkout` writes `checkout/` and a downstream `docker.build` names `checkout` as its context. |
| `depth` | `integer` |  | `1` | How many commits of history to fetch. `1` is a shallow checkout of the ref alone, which is what a build wants; `0` fetches the whole history, which a step reading the log or describing a tag needs. |
| `submodules` | `boolean` |  | `false` | Also check out the repository's submodules, recursively. |
| `timeout` | `string (humane-duration)` |  | `"10m"` | The deadline on each git invocation, after which it is killed as transient. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `commit` | `string` | yes |  | The full sha the checkout landed on, which is the only exact name for what was built. |
| `ref` | `string` | yes |  | The ref that was asked for, or the default branch the clone landed on when none was. |
| `target` | `string` | yes |  | The checkout's directory, relative to the run's work directory, as a downstream block names it. |
| `remote` | `string` | yes |  | The remote it came from, with any credential stripped. |
| `stdout_uri` | `string` |  | `""` | Where the whole of the fetching command's stdout was written; empty when the checkout was already standing and nothing was fetched. |
| `stderr_uri` | `string` |  | `""` | Where the whole of the fetching command's stderr was written, which is where git prints what it is doing; empty when the checkout was already standing and nothing was fetched. |

### `http.request`

Call an HTTP endpoint.

Contributed by `builtin`. Not idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string or null` |  | `null` | The code of the connection whose base URL, auth, TLS, and timeout apply. |
| `url` | `string or null` |  | `null` | An absolute URL, for the case where no connection is configured. |
| `path` | `string` |  | `"/"` | The path resolved against the connection's base URL. |
| `timeout` | `string (humane-duration) or null` |  | `null` | Overrides the connection's timeout for this call alone. |
| `follow_redirects` | `boolean` |  | `false` | Whether a 3xx is followed rather than returned as the answer. |
| `method` | `"GET" or "POST" or "PUT" or "PATCH" or "DELETE" or "HEAD" or "OPTIONS"` |  | `"GET"` | -- |
| `query` | `object of string or integer or number or boolean` |  |  | -- |
| `headers` | `object of string` |  |  | -- |
| `body` | `any or null` |  | `null` | What the request sends, usually a reference to what an earlier step produced. |
| `content_type` | `string or null` |  | `null` | The content type the body is sent with, overriding the default for what it carries. |
| `success_status` | `integer[]` |  |  | Status codes that count as success; empty means any 2xx. |
| `max_response` | `string or integer` |  | `"32mb"` | How much of a response is read into memory. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `integer` | yes |  | -- |
| `headers` | `object of string` | yes |  | -- |
| `body` | `any` |  | `null` | What the service answered: the parsed document when it is JSON, else the text. |
| `body_bytes` | `integer` | yes |  | How many bytes the answer was. |
| `duration_ms` | `integer` | yes |  | -- |

### `kafka.produce`

Publish records to a Kafka topic.

Contributed by `builtin`. Not idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `kafka` connection naming the cluster and holding its credential. |
| `topic` | `string` | yes |  | The topic to publish to, which must already exist. |
| `records` | `any[]` | yes |  | The records to publish, written inline or referenced from an earlier step's output. |
| `key` | `string or null` |  | `null` | The name of a field of each record's value whose content becomes the message key. |
| `acks` | `"all" or "1" or "0"` |  | `"all"` | How many replicas must hold a record before it counts as published. |
| `timeout` | `string (humane-duration)` |  | `"30s"` | How long the whole publish may take, such as `30s`, counted from the first send to the last acknowledgement. How the records are batched inside it is the client's own. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `produced` | `integer` | yes |  | How many records the broker acknowledged. |
| `topic` | `string` | yes |  | -- |
| `offsets` | `object of integer` | yes |  | The offset of the last record written to each partition, keyed by partition number as a string. A partition this publish did not write to is not in the map. |
| `duration_ms` | `integer` | yes |  | -- |
| `sent_bytes` | `integer` | yes |  | How many bytes of keys and values were handed to the client. |

### `log.write`

Write a line to the run's log.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `message` | `string` | yes |  | The line the run's log carries. |
| `level` | `"debug" or "info" or "warning" or "error"` |  | `"info"` | Which level the entry is written at, which is what a log filter selects on. |
| `value` | `any` |  | `null` | A value recorded as a field of the entry, and passed on as this step's output. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` |  | `null` | -- |

### `map.jq`

Replace every element of a list with what a jq program makes of it.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `input` | `any` | yes |  | The value to work on, written inline or referenced from an earlier step's output. |
| `program` | `string` | yes |  | The jq program this step runs. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` |  | `null` | The reshaped value, which a later step reads or hands to `storage.write`. |

### `pipeline.run`

Run another pipeline on this instance.

Contributed by `builtin`. Not idempotent. Polls every 5s unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `pipeline` | `string` | yes |  | The code of the pipeline to run, on this same instance. |
| `params` | `object` |  |  | The child's parameters, validated against *its* schema when the step executes. |
| `wait` | `boolean` |  | `true` | Whether the step waits for the child to finish, or reports it started and moves on. |
| `strict` | `boolean` |  | `false` | Whether a child that finished `completed_with_errors` fails this step. |
| `max_depth` | `integer` |  | `5` | How many pipelines deep the chain reaching this run may already be. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `pipeline` | `string` | yes |  | -- |
| `run_id` | `string or null` |  | `null` | The child run, or None when its concurrency policy meant no run was created. |
| `status` | `string` | yes |  | The child's run status, `started` when this step did not wait, or `skipped`. |

### `rabbitmq.publish`

Publish one message to an exchange.

Contributed by `builtin`. Not idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `rabbitmq` connection naming the broker and holding its password. |
| `exchange` | `string` |  | `""` | The exchange to publish to; empty is the default exchange, where a routing key is a queue. |
| `routing_key` | `string` | yes |  | What the broker routes the message by, which on the default exchange is a queue name. |
| `message` | `any` | yes |  | The body: a string is sent as UTF-8 text, anything else as canonical JSON. |
| `content_type` | `string or null` |  | `null` | What the body is, sent with the message. |
| `persistent` | `boolean` |  | `true` | Whether the broker writes the message to disk, so a durable queue keeps it across a restart. |
| `timeout` | `string (humane-duration)` |  | `"30s"` | How long the whole publish may take, such as `30s`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `published` | `integer` | yes |  | How many messages the broker took, which is one. |
| `message_bytes` | `integer` | yes |  | -- |

### `report.render`

Render text from a Jinja template.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `template` | `string` | yes |  | The Jinja template, rendered against `values`. |
| `values` | `object` |  |  | What the template sees, each key a name in it. |
| `content_type` | `string` |  | `"text/markdown"` | What the rendered text is, passed on for a sink to record. |
| `max_size` | `string or integer` |  | `"1mb"` | How much text this step will build, such as `256kb`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `text` | `string` | yes |  | -- |
| `content_type` | `string` | yes |  | -- |
| `text_bytes` | `integer` | yes |  | -- |

### `shell.run`

Run a command on the worker.

Contributed by `builtin`. Not idempotent. **Runs code on the worker**, so the instance must allowlist its id.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `argv` | `string[]` |  |  | The command as an argument vector, which does not involve a shell. |
| `command` | `string or null` |  | `null` | The command as a shell string, for when a pipe or a redirect is the point. |
| `cwd` | `string or null` |  | `null` | A directory relative to the run's work directory; never an absolute path. |
| `env` | `object of string` |  |  | Variables set explicitly for this command. |
| `env_allowlist` | `string[]` |  |  | Worker environment variables this command is allowed to inherit. |
| `timeout` | `string (humane-duration)` |  | `"5m"` | How long the process may run before it is killed as a transient failure. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `exit_code` | `integer` | yes |  | -- |
| `stdout` | `string` | yes |  | The head of what the command printed, cut at the instance's inline capture size. |
| `stderr` | `string` | yes |  | The head of what the command printed to stderr, cut the same way. |
| `stdout_uri` | `string` | yes |  | Where the whole of stdout was written; never truncated, whatever the field above holds. |
| `stderr_uri` | `string` | yes |  | Where the whole of stderr was written; never truncated either. |
| `stdout_bytes` | `integer` | yes |  | How much the command printed to stdout altogether, inlined or not. |
| `stderr_bytes` | `integer` | yes |  | How much it printed to stderr altogether. |
| `stdout_truncated` | `boolean` | yes |  | Whether `stdout` above is short of the stream. Only the inline copy is ever cut. |
| `stderr_truncated` | `boolean` | yes |  | Whether `stderr` above is short of the stream, which is an independent question. |

### `sql.execute`

Run SQL statements against a database in one transaction.

Contributed by `builtin`. Not idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `sql` connection naming the database and holding its password. A connection marked `read_only` is refused: this block writes. |
| `statements` | `string[]` | yes |  | The statements, run in order inside one transaction. They all commit or none of them does, so a migration, an insert and the index it needs are one step and not three. |
| `params` | `object` |  |  | Values bound by name, written `:name`, and shared by every statement. |
| `timeout` | `string (humane-duration)` |  | `"5m"` | How long the whole transaction may run. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `row_counts` | `integer[]` | yes |  | Rows affected by each statement, in order; `-1` where the driver does not say. |
| `duration_ms` | `integer` | yes |  | -- |

### `sql.query`

Run one SQL statement and return its rows.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `sql` connection naming the database and holding its password. |
| `sql` | `string` | yes |  | One statement, and one only. A document that needs two writes two steps, or uses `sql.execute`, which is the block that runs several as one transaction. |
| `params` | `object` |  |  | Values bound by name, written `:name` in the statement. |
| `max_rows` | `integer` |  | `1000` | How many rows may be carried inline in the step's output. |
| `timeout` | `string (humane-duration)` |  | `"5m"` | How long the statement may run. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `rows` | `any[]` | yes |  | The rows as objects keyed by column name, which a later step reads or writes out. |
| `row_count` | `integer` | yes |  | How many rows the query returned. |
| `columns` | `string[]` | yes |  | The column names, in the order the query selected them. |
| `duration_ms` | `integer` | yes |  | -- |

### `storage.copy`

Copy an object from one URI to another.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string (storage-uri)` | yes |  | -- |
| `target` | `string (storage-uri)` | yes |  | -- |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes |  | -- |
| `target` | `string` | yes |  | -- |
| `bytes_copied` | `integer` | yes |  | -- |

### `storage.read`

Read an object from a storage URI as a value.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source` | `string (storage-uri)` | yes |  | The URI the object is read from. |
| `content_type` | `string or null` |  | `null` | What to read the object as, overriding what the backend and the extension say. |
| `max_size` | `string or integer` |  | `"1mb"` | How much of an object this step will hold, such as `8mb`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `content_type` | `string` | yes |  | -- |
| `text` | `string or null` |  | `null` | -- |
| `value` | `any or null` |  | `null` | -- |
| `bytes_read` | `integer` | yes |  | -- |

### `storage.write`

Write a value or text to a storage URI.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `target` | `string (storage-uri)` | yes |  | The URI the object is written to, replacing whatever is there. |
| `text` | `string or null` |  | `null` | A string written as UTF-8, for a report, a csv, or any document that is already text. |
| `value` | `any or null` |  | `null` | A value written as canonical JSON, for what an earlier step produced as structure. |
| `content_type` | `string or null` |  | `null` | What the object is, recorded where the backend can record it. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `uri` | `string` | yes |  | -- |
| `bytes_written` | `integer` | yes |  | -- |
| `content_type` | `string` | yes |  | -- |

### `transform.jq`

Reshape a value with a jq program.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `input` | `any` | yes |  | The value to work on, written inline or referenced from an earlier step's output. |
| `program` | `string` | yes |  | The jq program this step runs. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` |  | `null` | The reshaped value, which a later step reads or hands to `storage.write`. |

### `validate.schema`

Validate a value against a JSON Schema.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `input` | `any` |  | `null` | The value to check, normally a `${steps....}` reference to what an upstream step produced. An explicit null is a value like any other and is checked as one. |
| `schema` | `string` | yes |  | The code of the schema the value must satisfy: one the instance holds, or one the document carries in its top-level `schemas` section. The named schema was validated when it was stored or applied, so nothing rechecks it here; a code no instance holds fails the run at the gate. The Python attribute is renamed only to dodge a pydantic clash; a document writes `schema`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` |  | `null` | The validated input, unchanged. The gate is also a waypoint: reference `${steps.<gate>.output.value}` and every step past it provably received the shape. |

### `value.const`

Emit a fixed value.

Contributed by `builtin`. Idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` | yes |  | The value this step emits, exactly as written. An explicit null is a value; leaving the field out is a step that declares nothing, and is refused. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `value` | `any` |  | `null` | The declared value, unchanged. |

### `webhook.post`

POST a JSON body, optionally HMAC-signed.

Contributed by `builtin`. Not idempotent.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string or null` |  | `null` | The code of the connection whose base URL, auth, TLS, and timeout apply. |
| `url` | `string or null` |  | `null` | An absolute URL, for the case where no connection is configured. |
| `path` | `string` |  | `"/"` | The path resolved against the connection's base URL. |
| `timeout` | `string (humane-duration) or null` |  | `null` | Overrides the connection's timeout for this call alone. |
| `follow_redirects` | `boolean` |  | `false` | Whether a 3xx is followed rather than returned as the answer. |
| `body` | `any` |  |  | The JSON payload, usually built from upstream outputs with `${steps...}` references. |
| `headers` | `object of string` |  |  | Extra headers the receiver wants, such as a routing key. |
| `max_response` | `string or integer` |  | `"1mb"` | How much of the receiver's answer is read, before the step is failed instead. |
| `sign_with` | `string or null` |  | `null` | The connection whose `hmac_secret` signs the body; unset means the POST is unsigned. |
| `success_status` | `integer[]` |  |  | Status codes that count as delivered; empty means any 2xx. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `integer` | yes |  | -- |
| `signed` | `boolean` | yes |  | -- |
| `duration_ms` | `integer` | yes |  | -- |
| `json_body` | `any or null` |  | `null` | -- |
| `text` | `string or null` |  | `null` | -- |

## Sensors

### `http.ready`

Wait for an HTTP endpoint to report ready.

Contributed by `builtin`. Not idempotent. Polls every 1m unless the step says otherwise. Gives up after 24h unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string or null` |  | `null` | The code of the connection whose base URL, auth, TLS, and timeout apply. |
| `url` | `string or null` |  | `null` | An absolute URL, for the case where no connection is configured. |
| `path` | `string` |  | `"/"` | The path resolved against the connection's base URL. |
| `timeout` | `string (humane-duration) or null` |  | `null` | Overrides the connection's timeout for this call alone. |
| `follow_redirects` | `boolean` |  | `false` | Whether a 3xx is followed rather than returned as the answer. |
| `expect_status` | `integer[]` |  |  | Status codes that mean ready; empty means any 2xx. |
| `contains` | `string or null` |  | `null` | Optional body matcher; readiness also requires the response to contain this text. |
| `max_response` | `string or integer` |  | `"1mb"` | How much of the answer is read while looking for `contains`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `integer` | yes |  | -- |
| `duration_ms` | `integer` | yes |  | -- |
| `matched` | `boolean` | yes |  | -- |

### `kafka.consume`

Wait for messages on a Kafka topic.

Contributed by `builtin`. Not idempotent. Polls every 30s unless the step says otherwise. Gives up after 24h unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `kafka` connection naming the cluster and holding its credential. |
| `topic` | `string` | yes |  | The topic to read. |
| `group_id` | `string or null` |  | `null` | The consumer group to commit through, or unset to track offsets in the cursor alone. |
| `start` | `"latest" or "earliest"` |  | `"latest"` | Where a poke with no cursor begins: at whatever arrives next, or at the oldest record the broker still holds. It applies to the first poke of an attempt only; after that the cursor says where to read from. |
| `min_messages` | `integer` |  | `1` | How many messages a batch needs before the sensor succeeds. Below it the poke parks, keeping the offsets it read so the next poke carries on from there. |
| `max_messages` | `integer` |  | `100` | The most messages one poke takes, which bounds the output a step carries. |
| `poll_timeout` | `string (humane-duration)` |  | `"5s"` | How long one poke waits on the broker before answering with what it has, such as `5s`. |
| `poll_every` | `string (humane-duration) or null` |  | `null` | How long to park between pokes; unset leaves the cadence to the step's own `poll`. |
| `key_format` | `"json" or "text" or "base64"` |  | `"base64"` | How a message key is decoded. `base64` carries any bytes through unharmed, which is what a key that is not text needs. |
| `value_format` | `"json" or "text" or "base64"` |  | `"json"` | How a message value is decoded. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `messages` | `object[]` | yes |  | -- |
| `count` | `integer` | yes |  | -- |
| `cursor` | `object of integer` | yes |  | The offset each partition is read up to, keyed by partition number as a string. |

### `rabbitmq.consume`

Wait for messages on a RabbitMQ queue.

Contributed by `builtin`. Not idempotent. Polls every 30s unless the step says otherwise. Gives up after 24h unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The `rabbitmq` connection naming the broker and holding its password. |
| `queue` | `string` | yes |  | The queue to read. It must already exist: this block declares nothing. |
| `min_messages` | `integer` |  | `1` | How many messages a batch needs before the sensor succeeds. |
| `max_messages` | `integer` |  | `100` | The most messages one poke takes, which bounds the output a step carries. |
| `poll_timeout` | `string (humane-duration)` |  | `"5s"` | How long one poke waits on the broker before answering with what it has, such as `5s`. |
| `poll_every` | `string (humane-duration) or null` |  | `null` | How long to park between pokes; unset leaves the cadence to the step's own `poll`. |
| `ack` | `"on_success" or "always"` |  | `"on_success"` | When a message is acknowledged. |
| `value_format` | `"json" or "text" or "base64"` |  | `"json"` | How a message body is decoded. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `messages` | `object[]` | yes |  | -- |
| `count` | `integer` | yes |  | -- |

### `storage.exists`

Wait for an object to appear at a URI.

Contributed by `builtin`. Not idempotent. Polls every 1m unless the step says otherwise. Gives up after 24h unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `uri` | `string` | yes |  | A URI, which may contain a glob pattern in its final segments. |
| `min_size` | `string or integer` |  | `"0b"` | Ignore an object until it is at least this large, such as `1mb`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `uri` | `string` | yes |  | -- |
| `size` | `integer` | yes |  | -- |
| `modified_at` | `string (date-time)` | yes |  | -- |

### `time.sleep`

Wait a fixed duration.

Contributed by `builtin`. Not idempotent. Polls every 1s unless the step says otherwise. Gives up after 24h unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `for` | `string (humane-duration)` | yes |  | How long to wait, measured from when the attempt started. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `started_at` | `string (date-time)` | yes |  | When the wait began, which is when the attempt started and not when a poke ran. |
| `waited_ms` | `integer` | yes |  | How long the wait actually lasted, which is the configured duration plus poll latency. |

### `time.window`

Wait until the local clock is inside a time window.

Contributed by `builtin`. Not idempotent. Polls every 1m unless the step says otherwise. Gives up after 24h unless the step says otherwise.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `after` | `string (time)` |  | `"00:00:00"` | The local time the window opens. |
| `before` | `string (time)` |  | `"23:59:59"` | The local time it closes; earlier than `after` means the window crosses midnight. |
| `timezone` | `string` |  | `"UTC"` | The IANA zone the window is read in. A window without one is a window in someone's head. |
| `days` | `"mon" or "tue" or "wed" or "thu" or "fri" or "sat" or "sun"[]` |  |  | The days the window opens on; empty means every day. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `entered_at` | `string (date-time)` | yes |  | When the window this poke fell inside opened, not when the poke happened. |
| `timezone` | `string` | yes |  | -- |

## Other surfaces

Blocks are two of the five surfaces a plugin contributes to. The other three are listed here
by id, since a document references them by code and never by id of any other kind.

### Storage schemes

| Scheme | Contributed by |
| --- | --- |
| `s3` | `storage-s3` |

### Notifiers

| Notifier | Contributed by |
| --- | --- |
| `email` | `builtin` |
| `log` | `builtin` |
| `slack` | `builtin` |
| `webhook` | `builtin` |

### Connection kinds

| Connection kind | Contributed by |
| --- | --- |
| `docker` | `builtin` |
| `email` | `builtin` |
| `git` | `builtin` |
| `http` | `builtin` |
| `kafka` | `builtin` |
| `rabbitmq` | `builtin` |
| `s3` | `storage-s3` |
| `slack` | `builtin` |
| `sql` | `builtin` |
| `webhook` | `builtin` |
