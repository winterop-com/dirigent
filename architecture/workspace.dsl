workspace "Dirigent" "Architecture model for Dirigent, a generic pipeline orchestrator: an API server, a scheduler and workers coordinated through one database, with every domain entering through packs." {

    !identifiers hierarchical

    model {
        !impliedRelationships true

        # --- People -------------------------------------------------------
        author = person "Pipeline author" "Writes pipeline documents in YAML or the builder, applies them, and starts and reads runs."
        operator = person "Operator / admin" "Runs the processes, holds connections, users, tokens and schedules, and watches health and alerts."
        agent = person "AI agent" "A coding agent operating an instance through dirigent-mcp, bounded by the role of its token."

        # --- Packs (own repositories) ------------------------------------
        dhis2Pack = softwareSystem "dirigent-dhis2" "Adapter pack (winterop-com/dirigent-dhis2): the dhis2 connection kind, DHIS2 formats, and blocks for jobs, imports, metadata, tracker and analytics." {
            tags "Pack"
        }

        contrib = softwareSystem "dirigent-contrib" "Block packs for outside systems (winterop-com/dirigent-contrib), one package per system." {
            tags "Pack"
            chapPack = container "dirigent-chap" "The chap connection kind and blocks for datasets, backtests, predictions, quantiles and the endemic channel." "Python package" {
                tags "Pack"
            }
            climatePack = container "dirigent-climate" "The climate connection kind and blocks for aggregation, batch jobs, exports to DHIS2, and managed datasets." "Python package" {
                tags "Pack"
            }
        }

        # --- External systems --------------------------------------------
        dhis2 = softwareSystem "DHIS2" "Health information system. Source and destination of data values, metadata, tracker data and analytics." {
            tags "External"
        }
        chap = softwareSystem "Chap" "Climate-and-health modelling platform (chap-core). Datasets, backtests and predictions over HTTP." {
            tags "External"
        }
        climate = softwareSystem "Open climate service" "openEO-style climate data service. Aggregates climate data to org units and runs batch jobs." {
            tags "External"
        }
        objectStore = softwareSystem "S3-compatible storage" "Buckets the storage blocks and storage sources read and write. AWS S3, RustFS, MinIO." {
            tags "External"
        }
        brokers = softwareSystem "Kafka / RabbitMQ" "Message brokers. Topics and queues the queues pack consumes from and publishes to." {
            tags "External"
        }
        alertChannels = softwareSystem "Alert channels" "SMTP, Slack and webhook receivers an alert rule delivers through." {
            tags "External"
        }
        httpApis = softwareSystem "HTTP APIs" "Any HTTP service an http.request step reaches, or that calls an endpoint source." {
            tags "External"
        }

        # --- Dirigent ----------------------------------------------------
        dirigent = softwareSystem "Dirigent" "Generic pipeline orchestrator. Pipelines are documents built from pluggable blocks; every run, attempt and due time is a row." {

            ui = container "Web UI" "Pipeline builder, run grid and logs, connections, schedules, sources and alerts. Built from the block catalog." "React SPA" {
                tags "React"
            }

            server = container "API server" "dg server. The REST API, the web UI bundle, SSE streams, and endpoint sources. Embeds the scheduler unless --no-scheduler." "FastAPI / Uvicorn (Python)" {
                tags "FastAPI"
                routes = component "API routes" "/api/v1: pipelines and apply, runs, sources, triggers, connections, alerts, users, workers, system."
                auth = component "Auth" "Session cookie for the UI, bearer token for automation. Viewer, operator and admin roles."
                streams = component "Event streams" "SSE tails of a run's log entries and events, woken by dirigent_settled."
                intake = component "Endpoint intake" "/endpoints: checks a call in a fixed order (route, token, rate, type, size, signature), records the input, creates the run."
                waiter = component "Reply waiter" "One reader per process. Answers each held caller with the first reply to settle, or with the run's failure, or 504 at its deadline."
                uiHost = component "UI host" "Serves the SPA bundle and the shell for its deep links."
            }

            scheduler = container "Scheduler" "dg scheduler, or embedded in dg server. Turns due schedules into run rows. Time, and only time." "asyncio (Python)"

            worker = container "Worker [1..*]" "dg worker. Claims due attempts and calls blocks; polls and holds sources; sweeps leases and deadlines; delivers alerts. Routed by capability tags." "asyncio (Python)" {
                wakeups = component "Wake-ups" "LISTEN on dirigent_work. A commit wakes idle claims instead of the next poll; a lost one costs the poll it replaced."
                claim = component "Claim" "One query: a queued attempt past available_at, or a waiting one past next_poll_at, by priority then fairness. FOR UPDATE SKIP LOCKED, filtered by tags."
                executor = component "Executor" "Calls one block under a per-worker semaphore: execute, probe, fetch or poke. Commits a remote handle the moment it returns."
                state = component "Readiness and run status" "The last statement of every outcome transaction: readies dependents, renders replies, derives the run's status."
                runs = component "Run creation" "Inserts a run, its items and attempt rows in one transaction, under the pipeline's lock. Shared by the API, the scheduler and sources."
                recovery = component "Recovery and deadline sweeps" "Reclaims expired leases (waiting if a handle was committed, else queued), settles overdue deadlines, flags stuck runs, reaps dead workers."
                polled = component "Polled sources" "Leases each due storage or sensor source, polls it with no lock held, makes a run per input and stores the cursor."
                held = component "Held sources" "Keeps kafka and rabbitmq consumers open under a lease. A message is acknowledged only after its run commits."
                alerting = component "Alert dispatcher" "Claims queued notifications and delivers each through its channel, retried like an attempt."
                pluginHost = component "Plugin host" "Discovers packs through pluginkit entry points at startup, then dispatches by block id."
                contract = component "Block contract" "dirigent-plugin: Operator, Sensor, source kinds, notifiers, storage backends, connection kinds and formats."
                builtins = component "Built-in blocks" "dirigent-blocks: http, storage, execute, sql, jq, queues and parquet families, and the alert channels."
                artifacts = component "Storage facade" "Dispatches URIs by scheme. Keeps a small output inline and a large one as a URI."
            }

            cli = container "dg CLI" "Applies documents, starts and watches runs, and starts the server, worker and scheduler processes." "Typer (Python)"

            mcp = container "dirigent-mcp" "MCP server. Every tool is a call the Python client makes; nothing deletes." "MCP over stdio (Python)"

            db = container "Database" "Pipeline versions as JSONB documents; runs, items, attempts, leases and due times as indexed rows; logs; the worker registry." "PostgreSQL 17; SQLite under dg dev" {
                tags "Database" "PostgreSQL"
            }

            storage = container "Artifact storage" "Step outputs too large to inline, and each run's scratch prefix. Never a worker-local path." "file:// or s3:// (dirigent-storage-s3)" {
                tags "Database"
            }
        }

        # --- People ------------------------------------------------------
        author -> dirigent.ui "Builds pipelines, starts and reads runs" "HTTPS"
        author -> dirigent.cli "Applies documents, runs and watches pipelines"
        operator -> dirigent.ui "Manages connections, users, schedules and alerts"
        operator -> dirigent.cli "Starts processes, migrates, checks health"
        agent -> dirigent.mcp "Calls tools" "MCP over stdio"

        # --- Clients to the API server -----------------------------------
        dirigent.ui -> dirigent.server.uiHost "Loads the bundle" "HTTPS"
        dirigent.ui -> dirigent.server.routes "Reads and writes" "HTTP/JSON"
        dirigent.ui -> dirigent.server.streams "Follows logs and events" "SSE"
        dirigent.cli -> dirigent.server.routes "Applies, runs, cancels, retries" "HTTP/JSON (dirigent-client)"
        dirigent.cli -> dirigent.server.streams "Watches a run" "SSE"
        dirigent.cli -> dirigent.db "Migrates the schema, ensures connections" "SQL"
        dirigent.mcp -> dirigent.server.routes "Calls the API with the agent's token" "HTTP/JSON (dirigent-client)"
        httpApis -> dirigent.server.intake "Calls an endpoint source" "HTTPS POST /endpoints/..."

        # --- API server components ---------------------------------------
        dirigent.server.routes -> dirigent.server.auth "Authenticates every call"
        dirigent.server.routes -> dirigent.db "Reads and writes definitions; creates ad hoc runs" "SQL, JSONB"
        dirigent.server.routes -> dirigent.storage "Streams artifacts" "file:// or s3://"
        dirigent.server.streams -> dirigent.db "Tails log entries; LISTEN dirigent_settled" "SQL, LISTEN"
        dirigent.server.intake -> dirigent.db "Records the input, creates the run; LISTEN dirigent_sources for routes" "SQL, LISTEN"
        dirigent.server.intake -> dirigent.server.waiter "Holds the caller when a reply can answer"
        dirigent.server.waiter -> dirigent.db "Reads rendered replies; LISTEN dirigent_settled" "SQL, LISTEN"
        dirigent.server.waiter -> dirigent.storage "Streams a body_from reply" "file:// or s3://"

        # --- Scheduler ---------------------------------------------------
        dirigent.scheduler -> dirigent.db "Holds the leader lock; claims due schedules and inserts their runs" "pg_advisory_lock, FOR UPDATE SKIP LOCKED"

        # --- Worker components -------------------------------------------
        dirigent.worker.wakeups -> dirigent.db "LISTEN dirigent_work" "pg_notify"
        dirigent.worker.wakeups -> dirigent.worker.claim "Wakes"
        dirigent.worker.claim -> dirigent.db "Claims attempt rows" "FOR UPDATE SKIP LOCKED"
        dirigent.worker.claim -> dirigent.worker.executor "Hands over the claimed attempt"
        dirigent.worker.executor -> dirigent.worker.pluginHost "Resolves the block by id"
        dirigent.worker.executor -> dirigent.db "Commits handles, heartbeats the lease, writes logs" "SQL, JSONB"
        dirigent.worker.executor -> dirigent.worker.artifacts "Persists the output"
        dirigent.worker.executor -> dirigent.worker.state "Records the outcome"
        dirigent.worker.state -> dirigent.db "Settles the attempt, readies dependents; NOTIFY dirigent_work, dirigent_settled" "SQL, pg_notify"
        dirigent.worker.artifacts -> dirigent.storage "Writes and reads outputs" "file:// or s3://"
        dirigent.worker.recovery -> dirigent.db "Sweeps leases, deadlines, stuck runs, dead workers" "SQL"
        dirigent.worker.polled -> dirigent.db "Leases due sources; stores the cursor" "SQL"
        dirigent.worker.polled -> dirigent.worker.pluginHost "Polls the source kind"
        dirigent.worker.polled -> dirigent.worker.runs "Makes a run per input"
        dirigent.worker.held -> dirigent.db "Leases held sources" "SQL"
        dirigent.worker.held -> dirigent.worker.pluginHost "Opens the consumer"
        dirigent.worker.held -> dirigent.worker.runs "Makes a run per message"
        dirigent.worker.runs -> dirigent.db "Inserts run, item and attempt rows; NOTIFY dirigent_work" "SQL, JSONB, pg_notify"
        dirigent.worker.alerting -> dirigent.db "Claims queued notifications" "SQL"
        dirigent.worker.alerting -> dirigent.worker.pluginHost "Resolves the notifier"
        dirigent.worker.pluginHost -> dirigent.worker.contract "Indexes contributions by id"
        dirigent.worker.pluginHost -> dirigent.worker.builtins "Calls built-in blocks"
        dirigent.worker.pluginHost -> dhis2Pack "Calls pack blocks" "in-process, entry point dirigent.plugins.v1"
        dirigent.worker.pluginHost -> contrib.chapPack "Calls pack blocks" "in-process, entry point dirigent.plugins.v1"
        dirigent.worker.pluginHost -> contrib.climatePack "Calls pack blocks" "in-process, entry point dirigent.plugins.v1"
        dirigent.worker.builtins -> httpApis "http.request, webhook.post" "HTTPS"
        dirigent.worker.builtins -> objectStore "storage blocks, storage sources" "S3 API"
        dirigent.worker.builtins -> brokers "Consumes and publishes" "Kafka, AMQP"
        dirigent.worker.builtins -> alertChannels "Delivers alerts" "SMTP, HTTPS"

        # --- Packs -------------------------------------------------------
        dhis2Pack -> dirigent.worker.contract "Implements"
        contrib.chapPack -> dirigent.worker.contract "Implements"
        contrib.climatePack -> dirigent.worker.contract "Implements"
        dhis2Pack -> dhis2 "Reads and writes" "DHIS2 Web API"
        contrib.chapPack -> chap "Imports data, runs backtests and predictions" "HTTP/JSON"
        contrib.climatePack -> climate "Aggregates, runs batch jobs" "HTTP/JSON"
        climate -> dhis2 "Delivers saved exports" "DHIS2 Web API"

        # --- Deployment: Docker Compose (infra/compose.yaml) -------------
        compose = deploymentEnvironment "Docker Compose" {
            host = deploymentNode "Docker host" "infra/compose.yaml. Overlays add brokers, a warehouse, telemetry and alert sinks." "Docker Compose" {
                postgres = deploymentNode "postgres" "Loopback-only port 5432." "postgres:17-alpine" {
                    containerInstance dirigent.db
                }
                s3 = deploymentNode "s3" "The artifact bucket. Loopback-only port 9010." "rustfs/rustfs" {
                    containerInstance dirigent.storage
                }
                migrate = deploymentNode "migrate" "One-shot: dg db upgrade, dg connection ensure, dg storage ensure." "dirigent:local" {
                    containerInstance dirigent.cli
                }
                serverNode = deploymentNode "server" "Port 3333. Scheduler embedded by default." "dirigent:local" {
                    containerInstance dirigent.server
                    containerInstance dirigent.scheduler
                }
                workerNode = deploymentNode "worker" "Tag docker, concurrency 8. Packs from DIRIGENT_PACKS are in the image." "dirigent:local" {
                    containerInstance dirigent.worker
                }
                docker = deploymentNode "docker" "The worker's own daemon; no host socket is mounted." "docker:28-dind" {
                    dockerd = infrastructureNode "Docker daemon" "Runs what docker.*, compose and build steps start." "TLS on tcp://docker:2376"
                }
            }
            host.workerNode -> host.docker.dockerd "Starts containers" "Docker API over TLS"
        }

        # --- Deployment: dg dev ------------------------------------------
        dev = deploymentEnvironment "dg dev" {
            laptop = deploymentNode "Developer machine" "" "macOS or Linux" {
                process = deploymentNode "dg dev" "API, UI, scheduler and worker in one asyncio process." "Python" {
                    containerInstance dirigent.server
                    containerInstance dirigent.scheduler
                    containerInstance dirigent.worker
                }
                state = deploymentNode ".dirigent/state" "Kept between starts and migrated forward." "SQLite file and file:// root" {
                    containerInstance dirigent.db
                    containerInstance dirigent.storage
                }
            }
        }
    }

    views {
        systemLandscape "L1_Landscape" "Level 1 - System landscape. The people, Dirigent, the packs, and the systems the packs and blocks reach." {
            include *
            autolayout lr
        }

        container dirigent "L2_Dirigent" "Level 2 - Containers inside Dirigent and how they talk. The systems a worker's blocks reach are on L1." {
            include *
            exclude dhis2Pack contrib objectStore brokers alertChannels
            autolayout tb
        }

        component dirigent.server "L3_Server" "Level 3 - API server components." {
            include *
            autolayout tb
        }

        component dirigent.worker "L3_Worker" "Level 3 - Engine and worker components." {
            include *
            autolayout tb
        }

        dynamic dirigent "Flow_AdHocRun" "Flow - an ad hoc run of an async block: create, claim, submit, probe, settle." {
            author -> dirigent.cli "dg run CODE --watch"
            dirigent.cli -> dirigent.server "POST /api/v1/pipelines/{code}/$run"
            dirigent.server -> dirigent.db "Insert run and attempt rows; NOTIFY dirigent_work on commit"
            dirigent.worker -> dirigent.db "Wake and claim the queued attempt FOR UPDATE SKIP LOCKED"
            dirigent.worker -> httpApis "execute: submit the job, get a remote handle"
            dirigent.worker -> dirigent.db "Commit the handle; park as waiting with next_poll_at"
            dirigent.worker -> httpApis "probe when due, until terminal; then fetch"
            dirigent.worker -> dirigent.storage "Write the output as an artifact"
            dirigent.worker -> dirigent.db "Settle, ready dependents, derive run status; NOTIFY dirigent_settled"
            dirigent.cli -> dirigent.server "GET the run's events (SSE) until it settles"
            autolayout lr
        }

        dynamic dirigent "Flow_EndpointReply" "Flow - an endpoint source with a reply: the caller is held until the reply settles." {
            httpApis -> dirigent.server "POST /endpoints/greet/Bergen with the source's token"
            dirigent.server -> dirigent.db "Check in order, record the input, create the run with the source settled"
            dirigent.worker -> dirigent.db "Claim and run each step"
            dirigent.worker -> dirigent.db "Last prerequisite settles; the walk renders the reply; NOTIFY dirigent_settled"
            dirigent.server -> dirigent.db "Reply waiter wakes and reads the rendered reply"
            dirigent.server -> httpApis "Answer the held caller with the reply's status, headers and body"
            autolayout lr
        }

        dynamic dirigent "Flow_PolledSource" "Flow - a polled storage source: lease, poll, one run per new object, cursor." {
            dirigent.worker -> dirigent.db "Lease the due source and commit before any I/O"
            dirigent.worker -> objectStore "List the prefix; objects not in the cursor are new"
            dirigent.worker -> dirigent.db "Under the pipeline lock: one run per object, store the cursor, next poll one cadence later"
            dirigent.worker -> dirigent.db "Any worker claims the new runs' attempts"
            autolayout lr
        }

        deployment dirigent compose "Deploy_Compose" "Deployment - Docker Compose. One image, three roles; the worker drives its own docker-in-docker daemon." {
            include *
            autolayout lr
        }

        deployment dirigent dev "Deploy_Dev" "Deployment - dg dev. One process and no dependencies, on SQLite." {
            include *
            autolayout lr
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Pack" {
                background #2e7d6b
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Component" {
                background #85bbf0
                color #000000
            }
            element "Database" {
                shape Cylinder
                background #438dd5
                color #ffffff
            }
            element "PostgreSQL" {
                icon https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg
            }
            element "FastAPI" {
                icon https://cdn.jsdelivr.net/gh/devicons/devicon/icons/fastapi/fastapi-original.svg
            }
            element "React" {
                icon https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg
            }
        }
    }
}
