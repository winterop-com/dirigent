"""Pipeline projects: a uv project of documents, and the scaffolding that creates one."""

import base64
import os
import re
from pathlib import Path
from typing import Any, Final, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dirigent_core.configdocs import example_document, project_document

#: The one file a project hand-edits: where its documents are, and what this instance sets.
PROJECT_FILE: Final = "dirigent.yaml"

#: Every setting, commented out, beside it. Read, never loaded.
EXAMPLE_CONFIG_FILE: Final = "dirigent.example.yaml"
DEFAULT_PIPELINES_DIR: Final = "pipelines"
DOCUMENT_SUFFIXES: Final = (".yaml", ".yml", ".json")


class ProjectError(Exception):
    """A project could not be read or scaffolded."""


class Project(BaseModel):
    """One pipeline project: where its documents are, and which profile they go to."""

    model_config = ConfigDict(frozen=True)

    root: Path
    pipelines: str = DEFAULT_PIPELINES_DIR
    profile: str | None = None
    requires: list[str] = Field(default_factory=list[str])
    """Block ids every document in this project assumes."""

    @property
    def pipelines_dir(self) -> Path:
        """The directory the project's documents live in."""
        return self.root / self.pipelines

    def documents(self) -> list[Path]:
        """List every document in the project, in a stable order."""
        directory = self.pipelines_dir
        if not directory.is_dir():
            raise ProjectError(f"{directory} does not exist; {PROJECT_FILE} points the pipelines directory at it")
        return sorted(path for path in directory.iterdir() if path.suffix in DOCUMENT_SUFFIXES and path.is_file())


def find_project(start: Path | None = None) -> Project | None:
    """Find the project the working directory is inside, by walking up to the filesystem root."""
    here = (start or Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return load_project(candidate)
    return None


def load_project(path: Path) -> Project:
    """Read one ``dirigent.yaml``."""
    try:
        loaded: object = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ProjectError(f"{path} could not be read: {error}") from error
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ProjectError(f"{path} should hold a mapping of project settings")
    raw = cast("dict[str, Any]", loaded)
    section = raw.get("project") if isinstance(raw.get("project"), dict) else raw
    body = cast("dict[str, Any]", section)
    pipelines = body.get("pipelines")
    profile = body.get("profile")
    requires = body.get("requires")
    return Project(
        root=path.parent,
        pipelines=pipelines if isinstance(pipelines, str) else DEFAULT_PIPELINES_DIR,
        profile=profile if isinstance(profile, str) else None,
        requires=[str(item) for item in cast("list[object]", requires)] if isinstance(requires, list) else [],
    )


PROJECT_TEMPLATE = """\
# A dirigent pipeline project: a working set of documents, not a source of truth.
# The server is where definitions actually live; `dg apply` puts these there.

project:
  pipelines: pipelines
  profile: local

  # Block ids every document here assumes. `dg apply` checks these against the target
  # instance's catalog first, and fails with a complete list of what is missing.
  requires: []
"""

PROFILES_TEMPLATE = """\
# Client-side addressing only: which server, and how to get a token for it.
# Never a database URL -- a CLI that could reach the database would bypass
# authentication, attribution, and validation entirely.

default: local

profiles:
  local:
    url: http://127.0.0.1:3333
    token_env: DG_TOKEN

  # staging:
  #   url: https://dirigent-staging.example.org
  #   token_env: DG_STAGING_TOKEN
  #
  # prod:
  #   url: https://dirigent.example.org
  #   token_cmd: pass show dirigent/prod
"""

STATE_IGNORE_TEMPLATE = """\
# A local instance's database and artifacts. Disposable, and never shared.
# profiles.yaml beside this stays committable: it is addressing, not state.
state/
"""

WORKFLOW_TEMPLATE = """\
name: dirigent

on:
  push:
    branches: [main]
  pull_request:

jobs:
  apply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6

      # The runtime pyproject.toml pins, not whatever is newest on the index.
      - name: Install the project
        run: uv sync

      # On a pull request this is the whole-project diff and nothing is written.
      - name: Plan
        if: github.event_name == 'pull_request'
        run: uv run dg apply --dry-run
        env:
          DG_URL: ${{ secrets.DG_URL }}
          DG_TOKEN: ${{ secrets.DG_TOKEN }}

      - name: Apply
        if: github.event_name == 'push'
        run: uv run dg apply
        env:
          DG_URL: ${{ secrets.DG_URL }}
          DG_TOKEN: ${{ secrets.DG_TOKEN }}
"""

EXAMPLE_TEMPLATE = """\
# The smallest thing dirigent can run: one step, one block, no parameters.
#
# value.const emits its configured value and touches nothing, so this runs with nothing
# on the unsafe allowlist:
#
#   dg apply
#   dg run hello-world --watch

format: dirigent/v1
kind: pipeline
code: hello-world
name: Hello world
description: Emit a greeting, and nothing else.

steps:
  greet:
    block: value.const
    config:
      value: "hello from dirigent"
"""


class Service(BaseModel):
    """One optional service of the container stack, as the form and the flag name it."""

    model_config = ConfigDict(frozen=True)

    code: str
    title: str
    what: str


#: The services a stack may add beside PostgreSQL, migrate, server and worker. S3 is on
#: unless switched off: object storage is part of the base stack.
SERVICES: Final = (
    Service(code="s3", title="Object storage (S3)", what="artifacts on a bucket; off means a volume"),
    Service(code="docker", title="Docker daemon for the workers", what="the docker.* blocks, a dind sidecar"),
    Service(code="kafka", title="Kafka", what="a broker the queue sensors wait on"),
    Service(code="rabbitmq", title="RabbitMQ", what="a broker the queue sensors wait on"),
)

DEFAULT_SERVICES: Final = ("s3",)

#: The example each service brings into `pipelines/`, so a stack with the service has one
#: document that uses it the day it is made.
SERVICE_EXAMPLES: Final = {
    "s3": (
        "s3-hello.yaml",
        """\
# A greeting written to the stack's own bucket and read back, through the s3:// scheme.
#
# There is no S3 block: storage.write puts text in an object, storage.copy moves bytes between
# schemes, and the stack's `migrate` service bootstraps the `artifacts` connection that serves
# s3://. The bucket comes from the URI, so this one is the stack's:
#
#   dg run s3-hello --watch

format: dirigent/v1
kind: pipeline
code: s3-hello
name: Hello, object storage
description: Write a greeting to the bucket and copy it back, through s3://.

requires:
  blocks:
    - storage.write
    - storage.copy
  connections:
    - artifacts
  storage:
    - s3

steps:
  greet:
    block: storage.write
    config:
      target: "${run.scratch}/hello.txt"
      text: "hello from object storage"

  upload:
    block: storage.copy
    depends_on: [greet]
    config:
      source: "${steps.greet.output.uri}"
      target: "s3://dirigent/hello/${run.id}.txt"

  download:
    block: storage.copy
    depends_on: [upload]
    config:
      source: "s3://dirigent/hello/${run.id}.txt"
      target: "${run.scratch}/hello-back.txt"
""",
    ),
    "docker": (
        "docker-hello.yaml",
        """\
# A command run in a container on the workers' own daemon, the `docker` service.
#
# docker.run is on the stack's allowlist (DIRIGENT_ENABLED_UNSAFE_BLOCKS in .env) because the
# daemon it reaches is the sidecar, never the host's. The image is pulled first, gets no
# network, and is capped in memory and processes:
#
#   dg run docker-hello --watch

format: dirigent/v1
kind: pipeline
code: docker-hello
name: Hello from a container
description: Run a command in a container, with no network and the image pulled first.

requires:
  blocks:
    - docker.run
  workers:
    - docker

steps:
  greet:
    block: docker.run
    deadline: 5m
    config:
      image: alpine:3
      pull: true
      network: none
      argv: [echo, "hello from a container"]
      memory: 64mb
      pids_limit: 64
""",
    ),
    "kafka": (
        "kafka-hello.yaml",
        """\
# Three records published to the stack's Kafka broker and read back off the topic.
#
# The `migrate` service bootstraps the `kafka` connection and the `kafka-topic` service
# creates the `hello` topic, so nothing has to be arranged first:
#
#   dg run kafka-hello --watch

format: dirigent/v1
kind: pipeline
code: kafka-hello
name: Hello, Kafka
description: Publish records to a topic and consume the same batch back.

requires:
  blocks:
    - kafka.produce
    - kafka.consume
  connections:
    - kafka

steps:
  publish:
    block: kafka.produce
    config:
      connection: kafka
      topic: hello
      records:
        - {greeting: hello, n: 1}
        - {greeting: hello, n: 2}
        - {greeting: hello, n: 3}
      timeout: 30s

  consume:
    block: kafka.consume
    depends_on: [publish]
    poll: 5s
    deadline: 5m
    config:
      connection: kafka
      topic: hello
      start: earliest
      min_messages: 3
      max_messages: 50
      poll_timeout: 5s
      value_format: json
""",
    ),
    "rabbitmq": (
        "rabbitmq-hello.yaml",
        """\
# A run that waits for a message on the stack's RabbitMQ queue, then hands the batch on.
#
# The `migrate` service bootstraps the `rabbitmq` connection and the `rabbitmq-queue`
# service declares the `hello` queue. Publish something to it from the management UI at
# http://127.0.0.1:15672 (dirigent / dirigent), and the run that is waiting takes it:
#
#   dg run rabbitmq-hello --watch

format: dirigent/v1
kind: pipeline
code: rabbitmq-hello
name: Hello, RabbitMQ
description: Wait for a message on a queue and hand the batch on.

requires:
  blocks:
    - rabbitmq.consume
  connections:
    - rabbitmq

steps:
  wait:
    block: rabbitmq.consume
    poll: 10s
    deadline: 1h
    on_timeout: skip
    config:
      connection: rabbitmq
      queue: hello
      min_messages: 1
      max_messages: 50
      poll_timeout: 5s
      ack: on_success
      value_format: json
""",
    ),
}


class Pack(BaseModel):
    """One published pack the form and the flag can add to a project."""

    model_config = ConfigDict(frozen=True)

    name: str
    what: str


#: The packs on PyPI at this version.
PACKS: Final = (Pack(name="dirigent-dhis2", what="DHIS2 blocks and connection kinds"),)


#: How a project runs: one process here on SQLite, a container stack, or documents against an
#: instance somebody else runs.
TEMPLATES: Final = ("local", "compose", "documents")

COMPOSE_TEMPLATE_NAME: Final = "compose"


class InitChoices(BaseModel):
    """Everything ``dg init`` decides, from the form or from the flags, before it writes."""

    model_config = ConfigDict(frozen=True)

    template: str = "local"
    services: tuple[str, ...] = DEFAULT_SERVICES
    workflow: bool = False
    packs: tuple[str, ...] = ()
    admin: str = "admin"
    password: str = ""

    @property
    def stack(self) -> bool:
        """Whether the instance is the containers."""
        return self.template == COMPOSE_TEMPLATE_NAME

    @property
    def instance(self) -> bool:
        """Whether an instance is initialised here, in ``.dirigent/state``."""
        return self.template == "local"

    def has(self, service: str) -> bool:
        """Whether the stack carries a service."""
        return self.stack and service in self.services


def check_choices(choices: InitChoices) -> None:
    """Refuse a choice that does not exist, before anything is written or asked for."""
    if choices.template not in TEMPLATES:
        raise ProjectError(f"no template named {choices.template!r}; the templates are local, compose and documents")
    known = {service.code for service in SERVICES}
    for service in choices.services:
        if service not in known:
            raise ProjectError(f"no service named {service!r}; the services are {', '.join(sorted(known))}")
    packs = {pack.name for pack in PACKS}
    for pack in choices.packs:
        if pack not in packs:
            raise ProjectError(f"no pack named {pack!r}; the packs are {', '.join(sorted(packs))}")
    if choices.services != DEFAULT_SERVICES and not choices.stack:
        raise ProjectError("--service applies to the compose template alone; the other two run no stack")


COMPOSE_HEAD = """\
name: dirigent

x-dirigent: &dirigent
  build:
    context: .
    dockerfile: Dockerfile
    args:
      DIRIGENT_IMAGE: ${DIRIGENT_IMAGE:-ghcr.io/winterop-com/dirigent:__VERSION__}
  image: dirigent-instance:local
  restart: unless-stopped
  environment: &dirigent-env
    DIRIGENT_DATABASE_URL: ${DIRIGENT_DATABASE_URL:-postgresql+asyncpg://${POSTGRES_USER:-dirigent}:${POSTGRES_PASSWORD:-dirigent}@postgres:5432/${POSTGRES_DB:-dirigent}}
    DIRIGENT_CONFIG_FILE: /etc/dirigent/dirigent.yaml
    DIRIGENT_SECRET_KEY: ${DIRIGENT_SECRET_KEY:?set DIRIGENT_SECRET_KEY in .env}
    DIRIGENT_ENVIRONMENT: ${DIRIGENT_ENVIRONMENT:-prod}
    DIRIGENT_LOG_LEVEL: ${DIRIGENT_LOG_LEVEL:-INFO}
    DIRIGENT_LOG_FORMAT: json
__ARTIFACTS__    # What a tool opens through the filesystem -- a checkout, a build context, a compose
    # file, a bind mount -- rather than through storage. The daemon mounts it at the same
    # path, so a bind docker.run hands over means the same directory on both sides.
    DIRIGENT_WORK_ROOT: /var/lib/dirigent/work
    DIRIGENT_ENABLED_UNSAFE_BLOCKS: ${DIRIGENT_ENABLED_UNSAFE_BLOCKS:-}
    # Pool plus overflow must stay above DIRIGENT_WORKER_CONCURRENCY, which the instance
    # enforces at start-up.
    DIRIGENT_DATABASE_POOL_SIZE: ${DIRIGENT_DATABASE_POOL_SIZE:-12}
    DIRIGENT_DATABASE_MAX_OVERFLOW: ${DIRIGENT_DATABASE_MAX_OVERFLOW:-4}
    # The alert context is built by whichever worker settles the run, so this belongs on
    # every service.
    DIRIGENT_ALERT_BASE_URL: ${DIRIGENT_ALERT_BASE_URL:-http://localhost:3333}
    # Engine spans and metrics are recorded on the worker, so these belong on every service.
    OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_EXPORTER_OTLP_ENDPOINT:-}
    OTEL_SERVICE_NAME: ${OTEL_SERVICE_NAME:-dirigent}
  volumes:
    - ./dirigent.yaml:/etc/dirigent/dirigent.yaml:ro
  depends_on:
    postgres:
      condition: service_healthy
    migrate:
      condition: service_completed_successfully
__DEPENDS_S3__
services:
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-dirigent}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dirigent}
      POSTGRES_DB: ${POSTGRES_DB:-dirigent}
    volumes:
      - postgres:/var/lib/postgresql/data
    healthcheck:
      # -d and -U are both given: without them pg_isready answers about the wrong database
      # and reports ready while the one dirigent uses is still being created on first start.
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-dirigent} -d ${POSTGRES_DB:-dirigent}"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 10s
    ports:
      # Bound to loopback: the stack reaches postgres over the compose network, and the
      # mapping exists only so a person on the host can inspect the database.
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"

"""

COMPOSE_ARTIFACTS_S3 = """\
    # `migrate` puts the connection this resolves through in place before anything runs.
    DIRIGENT_ARTIFACT_ROOT: s3://${S3_BUCKET:-dirigent}/artifacts
    DIRIGENT_STORAGE_CONNECTIONS: s3=${S3_CONNECTION:-artifacts}
"""

COMPOSE_ARTIFACTS_VOLUME = """\
    # A volume the server and the worker share; object storage is the `s3` service, which
    # this stack was scaffolded without.
    DIRIGENT_ARTIFACT_ROOT: file:///var/lib/dirigent/artifacts
"""

COMPOSE_DEPENDS_S3 = """\
    s3-bucket:
      condition: service_completed_successfully
"""

COMPOSE_MIGRATE = """\
  # Brings the schema forward__MIGRATE_WHAT__
  migrate:
    <<: *dirigent
    restart: "no"
    entrypoint: ["/bin/sh", "-ec"]
    command:
      - |
        dg db upgrade
__MIGRATE_S3____MIGRATE_BROKERS__    environment:
      <<: *dirigent-env
__MIGRATE_ENV__    depends_on:
      postgres:
        condition: service_healthy

"""

COMPOSE_MIGRATE_S3_WHAT = """, and ensures the connection the artifact root resolves
  # through. That is a row, and a container has no API token, so `dg connection ensure`
  # writes it process-side and seals its secret half with the instance key, exactly as the
  # API would. Re-running the stack brings the row to whatever the environment now says."""

COMPOSE_MIGRATE_KAFKA = """\
        dg connection ensure kafka kafka \\
          --name "Kafka" \\
          --description "The stack's own broker." \\
          --set bootstrap_servers='["kafka:9092"]'
"""

COMPOSE_MIGRATE_RABBITMQ = """\
        dg connection ensure rabbitmq rabbitmq \\
          --name "RabbitMQ" \\
          --description "The stack's own broker." \\
          --set url="amqp://$$RABBITMQ_USER@rabbitmq:5672/" \\
          --set password="$$RABBITMQ_PASSWORD"
"""

COMPOSE_MIGRATE_ENV_RABBITMQ = """\
      RABBITMQ_USER: ${RABBITMQ_USER:-dirigent}
      RABBITMQ_PASSWORD: ${RABBITMQ_PASSWORD:-dirigent}
"""

COMPOSE_MIGRATE_S3 = """\
        dg connection ensure s3 "$$S3_CONNECTION" \\
          --name "Artifact storage" \\
          --description "The bucket every worker on this stack reads and writes artifacts in." \\
          --set endpoint_url="http://s3:9000" \\
          --set bucket="$$S3_BUCKET" \\
          --set access_key_id="$$S3_ACCESS_KEY" \\
          --set secret_access_key="$$S3_SECRET_KEY" \\
          --set path_style=true
"""

COMPOSE_MIGRATE_ENV_S3 = """\
      # The credentials reach the command as environment, never as a file or an image layer.
      S3_CONNECTION: ${S3_CONNECTION:-artifacts}
      S3_BUCKET: ${S3_BUCKET:-dirigent}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY:-dirigent}
      S3_SECRET_KEY: ${S3_SECRET_KEY:-dirigent}
"""

COMPOSE_S3 = """\
  # Artifact storage. The endpoint the connection names is the one containers resolve, not
  # the one a shell on the host does: `localhost` inside a container is the container.
  s3:
    image: ${DIRIGENT_S3_IMAGE:-rustfs/rustfs:1.0.0-rc.4}
    restart: unless-stopped
    environment:
      RUSTFS_ACCESS_KEY: ${S3_ACCESS_KEY:-dirigent}
      RUSTFS_SECRET_KEY: ${S3_SECRET_KEY:-dirigent}
    volumes:
      - s3:/data
    ports:
      - "${S3_PORT:-9010}:9000"
    healthcheck:
      # An unauthenticated request answers 403 rather than 200, and that is a serving
      # endpoint answering: -f would call it a failure, so only the connection is asserted.
      test: ["CMD-SHELL", "curl -s -o /dev/null http://127.0.0.1:9000/"]
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 5s

  # The bucket has to exist before a run writes to it, and nothing else creates it.
  s3-bucket:
    image: minio/mc:RELEASE.2025-04-16T18-13-26Z
    depends_on:
      s3:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-ec"]
    command:
      - |
        mc alias set fs http://s3:9000 "$$S3_ACCESS_KEY" "$$S3_SECRET_KEY"
        mc mb --ignore-existing "fs/$$S3_BUCKET"
    environment:
      S3_ACCESS_KEY: ${S3_ACCESS_KEY:-dirigent}
      S3_SECRET_KEY: ${S3_SECRET_KEY:-dirigent}
      S3_BUCKET: ${S3_BUCKET:-dirigent}

"""

COMPOSE_SERVER = """\
  server:
    <<: *dirigent
    command: ["server"]
    environment:
      <<: *dirigent-env
      DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD: ${DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD:-}
      DIRIGENT_SCHEDULER_ENABLED: ${DIRIGENT_SCHEDULER_ENABLED:-true}
      # A document in `pipelines/` lands at boot, and `dg apply` sends one now.
      DIRIGENT_APPLY_DIR: ${DIRIGENT_APPLY_DIR:-/etc/dirigent/pipelines}
      DIRIGENT_APPLY_PRUNE: ${DIRIGENT_APPLY_PRUNE:-false}
    # A list under the anchor is replaced, not merged, so the shared mount is respelled here.
    volumes:
      - ./dirigent.yaml:/etc/dirigent/dirigent.yaml:ro
      - ./pipelines:/etc/dirigent/pipelines:ro
__ARTIFACTS_MOUNT__    ports:
      - "${DIRIGENT_PORT:-3333}:3333"
    healthcheck:
      test: ["CMD", "dg", "health", "server"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

"""

COMPOSE_ARTIFACTS_MOUNT = """\
      - artifacts:/var/lib/dirigent/artifacts
"""

COMPOSE_DOCKER = """\
  # The daemon the `docker.*` blocks drive. It is the worker's own, so a pipeline's
  # containers are never the host's, and no host socket is mounted anywhere in this stack.
  docker:
    image: docker:28-dind@sha256:2a232a42256f70d78e3cc5d2b5d6b3276710a0de0596c145f627ecfae90282ac
    restart: unless-stopped
    # docker-in-docker needs the full capability set to run its own daemon; there is no
    # unprivileged mode that starts containers.
    privileged: true
    environment:
      # The entrypoint generates the CA, the server certificate and the client certificate
      # under this directory and serves tcp://0.0.0.0:2376 with TLS required.
      DOCKER_TLS_CERTDIR: /certs
    volumes:
      - docker-certs:/certs/client
      - docker-data:/var/lib/docker
      # A bind mount is resolved on the daemon's filesystem, not the worker's, so a path
      # docker.run hands over must mean the same directory here as it does in the worker.
      - work:/var/lib/dirigent/work
    healthcheck:
      test: ["CMD-SHELL", "docker -H unix:///var/run/docker.sock version >/dev/null 2>&1"]
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 10s

"""

COMPOSE_KAFKA = """\
  # Redpanda speaks the Kafka protocol and needs no ZooKeeper, so one container is a cluster.
  # It advertises its compose name, so the workers reach it and a producer on the host runs
  # inside the network: `docker compose exec kafka rpk topic produce ...`.
  kafka:
    image: ${DIRIGENT_KAFKA_IMAGE:-redpandadata/redpanda:v24.2.18}
    restart: unless-stopped
    command:
      - redpanda
      - start
      - --mode=dev-container
      - --smp=1
      - --node-id=0
      - --check=false
      - --kafka-addr=PLAINTEXT://0.0.0.0:9092
      - --advertise-kafka-addr=PLAINTEXT://kafka:9092
      # A topic a producer invented is a typo that reads as a working pipeline, so a document
      # naming a topic nobody created is refused instead.
      - --set
      - redpanda.auto_create_topics_enabled=false
    volumes:
      - kafka:/var/lib/redpanda/data
    healthcheck:
      test: ["CMD-SHELL", "rpk cluster health | grep -q 'Healthy:.*true'"]
      interval: 2s
      timeout: 5s
      retries: 30

  # The topic the hello example publishes to has to exist: the broker refuses to invent one.
  kafka-topic:
    image: ${DIRIGENT_KAFKA_IMAGE:-redpandadata/redpanda:v24.2.18}
    depends_on:
      kafka:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-ec"]
    command:
      - |
        rpk topic create hello --brokers kafka:9092 || rpk topic describe hello --brokers kafka:9092 >/dev/null

"""

COMPOSE_RABBITMQ = """\
  rabbitmq:
    image: ${DIRIGENT_RABBITMQ_IMAGE:-rabbitmq:3-management-alpine}
    restart: unless-stopped
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER:-dirigent}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD:-dirigent}
    volumes:
      - rabbitmq:/var/lib/rabbitmq
    ports:
      # The management UI, which is how a person watches a queue drain.
      - "127.0.0.1:${RABBITMQ_UI_PORT:-15672}:15672"
    healthcheck:
      test: ["CMD-SHELL", "rabbitmq-diagnostics -q ping"]
      interval: 2s
      timeout: 5s
      retries: 30

  # The queue the hello example waits on has to exist: the block declares nothing.
  rabbitmq-queue:
    image: ${DIRIGENT_RABBITMQ_IMAGE:-rabbitmq:3-management-alpine}
    depends_on:
      rabbitmq:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-ec"]
    command:
      - |
        rabbitmqadmin --host rabbitmq --username "$$RABBITMQ_USER" --password "$$RABBITMQ_PASSWORD" \\
          declare queue name=hello durable=true
    environment:
      RABBITMQ_USER: ${RABBITMQ_USER:-dirigent}
      RABBITMQ_PASSWORD: ${RABBITMQ_PASSWORD:-dirigent}

"""

COMPOSE_WORKER = """\
  worker:
    <<: *dirigent
    command: ["worker"]
    environment:
      <<: *dirigent-env
      DIRIGENT_WORKER_CONCURRENCY: ${DIRIGENT_WORKER_CONCURRENCY:-8}
__WORKER_DOCKER_ENV__    volumes:
      - ./dirigent.yaml:/etc/dirigent/dirigent.yaml:ro
      - ./pipelines:/etc/dirigent/pipelines:ro
__ARTIFACTS_MOUNT____WORKER_DOCKER_VOLUMES__      # The worker's own working files, at the path every service names.
      - work:/var/lib/dirigent/work
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
__WORKER_DEPENDS__    stop_grace_period: 60s
    healthcheck:
      test: ["CMD", "dg", "health", "worker"]
      interval: 15s
      timeout: 10s
      retries: 3
      start_period: 30s

"""

COMPOSE_WORKER_DOCKER_ENV = """\
      # This worker reaches a daemon, so it claims work from a document declaring
      # `requires.workers: [docker]`.
      DIRIGENT_WORKER_TAGS: docker
      # The sidecar daemon, read the same way by the API blocks and by the docker CLI the
      # compose and build blocks shell out to. Only the worker gets these.
      DOCKER_HOST: tcp://docker:2376
      DOCKER_TLS_VERIFY: "1"
      DOCKER_CERT_PATH: /certs/client
"""

COMPOSE_WORKER_DOCKER_VOLUMES = """\
      - docker-certs:/certs/client:ro
"""

COMPOSE_DEPENDS = {
    "s3": "      s3-bucket:\n        condition: service_completed_successfully\n",
    "docker": "      docker:\n        condition: service_healthy\n",
    "kafka": "      kafka-topic:\n        condition: service_completed_successfully\n",
    "rabbitmq": "      rabbitmq-queue:\n        condition: service_completed_successfully\n",
}

COMPOSE_VOLUMES = {
    "artifacts": "  artifacts:\n",
    "s3": "  s3:\n",
    "docker": "  docker-certs:\n  docker-data:\n",
    "kafka": "  kafka:\n",
    "rabbitmq": "  rabbitmq:\n",
}


def compose_document(choices: InitChoices, version: str) -> str:
    """Assemble the stack for the services chosen: the base, plus a fragment per service."""
    s3 = choices.has("s3")
    docker = choices.has("docker")
    artifacts_mount = "" if s3 else COMPOSE_ARTIFACTS_MOUNT
    parts = [
        COMPOSE_HEAD.replace("__ARTIFACTS__", COMPOSE_ARTIFACTS_S3 if s3 else COMPOSE_ARTIFACTS_VOLUME).replace(
            "__DEPENDS_S3__", COMPOSE_DEPENDS_S3 if s3 else ""
        ),
        COMPOSE_MIGRATE.replace("__MIGRATE_WHAT__", COMPOSE_MIGRATE_S3_WHAT if s3 else ".")
        .replace("__MIGRATE_S3__", COMPOSE_MIGRATE_S3 if s3 else "")
        .replace(
            "__MIGRATE_BROKERS__",
            (COMPOSE_MIGRATE_KAFKA if choices.has("kafka") else "")
            + (COMPOSE_MIGRATE_RABBITMQ if choices.has("rabbitmq") else ""),
        )
        .replace(
            "__MIGRATE_ENV__",
            (COMPOSE_MIGRATE_ENV_S3 if s3 else "") + (COMPOSE_MIGRATE_ENV_RABBITMQ if choices.has("rabbitmq") else ""),
        ),
        COMPOSE_S3 if s3 else "",
        COMPOSE_SERVER.replace("__ARTIFACTS_MOUNT__", artifacts_mount),
        COMPOSE_DOCKER if docker else "",
        COMPOSE_KAFKA if choices.has("kafka") else "",
        COMPOSE_RABBITMQ if choices.has("rabbitmq") else "",
        COMPOSE_WORKER.replace("__WORKER_DOCKER_ENV__", COMPOSE_WORKER_DOCKER_ENV if docker else "")
        .replace("__ARTIFACTS_MOUNT__", artifacts_mount)
        .replace("__WORKER_DOCKER_VOLUMES__", COMPOSE_WORKER_DOCKER_VOLUMES if docker else "")
        .replace("__WORKER_DEPENDS__", "".join(COMPOSE_DEPENDS[code] for code in choices.services)),
        "volumes:\n  postgres:\n"
        + ("" if s3 else COMPOSE_VOLUMES["artifacts"])
        + "  # The worker's own working files. Not shared with the server: nothing it does opens one.\n  work:\n"
        + "".join(COMPOSE_VOLUMES[code] for code in choices.services),
    ]
    return "".join(parts).replace("__VERSION__", version)


ENV_HEAD = """\
# Fills in ${...} in compose.yaml. Dirigent's own settings are in dirigent.yaml.

# Losing this means losing every stored connection secret. Changing it does not re-encrypt
# what is already stored.
DIRIGENT_SECRET_KEY=__SECRET_KEY__

# One-way: it does nothing the moment any account exists, so leaving it set on every deploy
# cannot reset a live instance's password.
DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD=__PASSWORD__

POSTGRES_USER=dirigent
POSTGRES_PASSWORD=dirigent
POSTGRES_DB=dirigent
POSTGRES_PORT=5432

DIRIGENT_ENVIRONMENT=prod
DIRIGENT_PORT=3333
DIRIGENT_LOG_LEVEL=INFO

DIRIGENT_ALERT_BASE_URL=http://localhost:3333

DIRIGENT_WORKER_CONCURRENCY=8

# Pool size plus max overflow must be at least DIRIGENT_WORKER_CONCURRENCY plus 4: one
# connection per in-flight block call, plus the lease heartbeat, the sweeper, the alert loop
# and a spare. The instance refuses to start on a configuration where that cannot hold, so
# raising the concurrency means raising these too.
DIRIGENT_DATABASE_POOL_SIZE=12
DIRIGENT_DATABASE_MAX_OVERFLOW=4

DIRIGENT_SCHEDULER_ENABLED=true

"""

ENV_S3 = """\
# The `migrate` service writes the connection S3_CONNECTION names from S3_ACCESS_KEY and
# S3_SECRET_KEY, so the credentials live here and nowhere else; change one and the next `up`
# brings the row to it.
S3_ACCESS_KEY=dirigent
S3_SECRET_KEY=dirigent
S3_BUCKET=dirigent
S3_CONNECTION=artifacts

# Where the bundled S3 server is published for a person on the host; the stack itself reaches
# it as http://s3:9000.
S3_PORT=9010
DIRIGENT_S3_IMAGE=rustfs/rustfs:1.0.0-rc.4

"""

ENV_KAFKA = """\
DIRIGENT_KAFKA_IMAGE=redpandadata/redpanda:v24.2.18

"""

ENV_RABBITMQ = """\
RABBITMQ_USER=dirigent
RABBITMQ_PASSWORD=dirigent
RABBITMQ_UI_PORT=15672
DIRIGENT_RABBITMQ_IMAGE=rabbitmq:3-management-alpine

"""

ENV_UNSAFE_DOCKER = """\
# Comma-separated block ids, empty for none. Listing one means whoever can edit a pipeline
# can run code on a worker. The docker.* blocks reach the dind sidecar this stack starts.
#
#   DIRIGENT_ENABLED_UNSAFE_BLOCKS=shell.run,docker.run,docker.compose.up,docker.compose.down
DIRIGENT_ENABLED_UNSAFE_BLOCKS=docker.run
"""

ENV_UNSAFE = """\
# Comma-separated block ids, empty for none. Listing one means whoever can edit a pipeline
# can run code on a worker.
#
#   DIRIGENT_ENABLED_UNSAFE_BLOCKS=shell.run
DIRIGENT_ENABLED_UNSAFE_BLOCKS=
"""

ENV_TAIL = """\

# The published image the Dockerfile beside this builds on.
DIRIGENT_IMAGE=ghcr.io/winterop-com/dirigent:__VERSION__
"""


def env_document(choices: InitChoices, version: str, key: str) -> str:
    """Assemble the ``.env`` for the services chosen."""
    return (
        (
            ENV_HEAD
            + (ENV_S3 if choices.has("s3") else "")
            + (ENV_KAFKA if choices.has("kafka") else "")
            + (ENV_RABBITMQ if choices.has("rabbitmq") else "")
            + (ENV_UNSAFE_DOCKER if choices.has("docker") else ENV_UNSAFE)
            + ENV_TAIL
        )
        .replace("__SECRET_KEY__", key)
        .replace("__PASSWORD__", choices.password)
        .replace("__VERSION__", version)
    )


DOCKERFILE_TEMPLATE = """\
# This instance's image: the published dirigent, plus whatever is added below.
ARG DIRIGENT_IMAGE=ghcr.io/winterop-com/dirigent:__VERSION__
FROM ${DIRIGENT_IMAGE}

# A pack is a Python package; install it here and run `docker compose up --build`.
__PACKS__"""


def dockerfile_document(choices: InitChoices, version: str) -> str:
    """The image this stack builds, with each chosen pack installed into it."""
    lines = "".join(f"RUN uv pip install {pack}=={version}\n" for pack in choices.packs)
    return DOCKERFILE_TEMPLATE.replace(
        "__PACKS__", lines or f"# RUN uv pip install dirigent-dhis2=={version}\n"
    ).replace("__VERSION__", version)


def pyproject_document(name: str, choices: InitChoices, version: str) -> str:
    """The uv project pinning the runtime, and each chosen pack beside it."""
    packs = "".join(f'    "{pack}=={version}",\n' for pack in choices.packs)
    return PYPROJECT_TEMPLATE.replace("__NAME__", name).replace("__VERSION__", version).replace("__PACKS__", packs)


ROOT_IGNORE_TEMPLATE = """\
# The environment uv sync builds from pyproject.toml.
.venv/
__pycache__/

# This instance's token, or the stack's key and first password. Never shared.
.env
"""

TOKEN_ENV_TEMPLATE = """\
# The token dg init minted for this instance's first admin. The local profile in
# .dirigent/profiles.yaml reads it from here when the shell does not export it.
DG_TOKEN=__TOKEN__
"""

PYPROJECT_TEMPLATE = """\
[project]
name = "__NAME__"
version = "0.1.0"
description = "A dirigent project: pipeline documents, and the runtime that runs them."
requires-python = ">=3.13"
dependencies = [
    "dirigent-cli==__VERSION__",
__PACKS__]
"""

README_TEMPLATE = """\
# __NAME__

A dirigent project. `pipelines/` holds the pipeline documents and `dirigent.yaml` the
project's settings.

`pyproject.toml` pins the dirigent runtime, so the `dg` this project runs on is that pinned
one and `uv run` is how it is reached.

## Run

```bash
__RUN__
```
"""

#: The commands a scaffolded project's README opens with, per template.
README_RUN: Final = {
    "local": (
        "uv sync",
        "uv run dg dev",
        "uv run dg apply",
        "uv run dg run hello-world --watch",
    ),
    "documents": (
        "uv sync",
        "uv run dg apply --dry-run",
        "uv run dg apply",
        "uv run dg run hello-world --watch",
    ),
    "compose": (
        "uv sync",
        "docker compose up -d",
        "uv run dg auth login --username admin",
        "uv run dg run hello-world --watch",
    ),
}


class Scaffolded(BaseModel):
    """What a scaffold wrote, and what it found already there and left alone."""

    model_config = ConfigDict(frozen=True)

    files: list[Path] = Field(default_factory=list[Path])
    skipped: list[Path] = Field(default_factory=list[Path])


def project_name(directory: Path) -> str:
    """Turn a target directory's name into a project name uv and PEP 621 accept."""
    slug = re.sub(r"[^a-z0-9]+", "-", directory.resolve().name.lower()).strip("-")
    return slug or "dirigent-project"


def scaffold(directory: Path, choices: InitChoices, *, version: str = "0.0.0") -> Scaffolded:
    """Create a uv project: pyproject, the project file, a pipelines directory, and an example."""
    check_choices(choices)
    written: list[Path] = []
    skipped: list[Path] = []
    directory.mkdir(parents=True, exist_ok=True)
    written.append(_write(directory / PROJECT_FILE, PROJECT_TEMPLATE + "\n" + project_document()))
    written.append(_write(directory / DEFAULT_PIPELINES_DIR / "hello-world.yaml", EXAMPLE_TEMPLATE))
    if choices.stack:
        for code in choices.services:
            filename, document = SERVICE_EXAMPLES[code]
            written.append(_write(directory / DEFAULT_PIPELINES_DIR / filename, document))
    written.append(_write(directory / ".dirigent" / "profiles.yaml", PROFILES_TEMPLATE))
    written.append(_write(directory / ".dirigent" / ".gitignore", STATE_IGNORE_TEMPLATE))
    written.append(_write(directory / EXAMPLE_CONFIG_FILE, example_document()))
    name = project_name(directory)
    _record(directory / "pyproject.toml", pyproject_document(name, choices, version), written, skipped)
    readme = README_TEMPLATE.replace("__NAME__", name).replace("__RUN__", "\n".join(README_RUN[choices.template]))
    _record(directory / "README.md", readme, written, skipped)
    _merge_ignore(directory / ".gitignore", ROOT_IGNORE_TEMPLATE, written, skipped)
    if choices.workflow:
        written.append(_write(directory / ".github" / "workflows" / "dirigent.yml", WORKFLOW_TEMPLATE))
    if choices.stack:
        written.append(_write(directory / "compose.yaml", compose_document(choices, version)))
        written.append(_write(directory / "Dockerfile", dockerfile_document(choices, version)))
        written.append(_write(directory / ".env", env_document(choices, version, _an_instance_key()), mode=0o600))
    return Scaffolded(files=written, skipped=skipped)


def write_token_env(directory: Path, token: str) -> Path:
    """Write the ``.env`` holding a new instance's token, readable by its owner alone."""
    return _write(directory / ".env", TOKEN_ENV_TEMPLATE.replace("__TOKEN__", token), mode=0o600)


def _record(path: Path, content: str, written: list[Path], skipped: list[Path]) -> None:
    """Write a file a project may already have of its own, leaving any existing one alone."""
    if path.exists():
        skipped.append(path)
        return
    written.append(_write(path, content))


def _merge_ignore(path: Path, content: str, written: list[Path], skipped: list[Path]) -> None:
    """Write the root ignore, or add to an existing one only the lines it does not have."""
    if not path.exists():
        written.append(_write(path, content))
        return
    current = path.read_text()
    present = set(current.splitlines())
    missing = [line for line in content.splitlines() if line and not line.startswith("#") and line not in present]
    if not missing:
        skipped.append(path)
        return
    separator = "" if current.endswith("\n") or not current else "\n"
    path.write_text(current + separator + "\n".join(missing) + "\n")
    written.append(path)


def _an_instance_key() -> str:
    """Generate the key the stack seals connection secrets with."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _write(path: Path, content: str, *, mode: int | None = None) -> Path:
    """Write one scaffolded file, refusing to overwrite one that is already there."""
    if path.exists():
        raise ProjectError(f"{path} already exists; dg init never overwrites")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode is not None:
        path.chmod(mode)
    return path
