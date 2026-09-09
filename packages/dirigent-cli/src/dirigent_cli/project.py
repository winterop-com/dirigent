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

      - name: Install dirigent
        run: pipx install dirigent-cli

      # On a pull request this is the whole-project diff and nothing is written.
      - name: Plan
        if: github.event_name == 'pull_request'
        run: dg apply --dry-run
        env:
          DG_URL: ${{ secrets.DG_URL }}
          DG_TOKEN: ${{ secrets.DG_TOKEN }}

      - name: Apply
        if: github.event_name == 'push'
        run: dg apply
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


COMPOSE_TEMPLATE = """\
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
    # `migrate` puts the connection this resolves through in place before anything runs.
    DIRIGENT_ARTIFACT_ROOT: s3://${S3_BUCKET:-dirigent}/artifacts
    DIRIGENT_STORAGE_CONNECTIONS: s3=${S3_CONNECTION:-artifacts}
    # What a tool opens through the filesystem -- a checkout, a build context, a compose
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
    s3-bucket:
      condition: service_completed_successfully

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

  # Brings the schema forward, and ensures the connection the artifact root resolves
  # through. That is a row, and a container has no API token, so `dg connection ensure`
  # writes it process-side and seals its secret half with the instance key, exactly as the
  # API would. Re-running the stack brings the row to whatever the environment now says.
  migrate:
    <<: *dirigent
    restart: "no"
    entrypoint: ["/bin/sh", "-ec"]
    command:
      - |
        dg db upgrade
        dg connection ensure s3 "$$S3_CONNECTION" \\
          --name "Artifact storage" \\
          --description "The bucket every worker on this stack reads and writes artifacts in." \\
          --set endpoint_url="http://s3:9000" \\
          --set bucket="$$S3_BUCKET" \\
          --set access_key_id="$$S3_ACCESS_KEY" \\
          --set secret_access_key="$$S3_SECRET_KEY" \\
          --set path_style=true
    environment:
      <<: *dirigent-env
      # The credentials reach the command as environment, never as a file or an image layer.
      S3_CONNECTION: ${S3_CONNECTION:-artifacts}
      S3_BUCKET: ${S3_BUCKET:-dirigent}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY:-dirigent}
      S3_SECRET_KEY: ${S3_SECRET_KEY:-dirigent}
    depends_on:
      postgres:
        condition: service_healthy

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
    ports:
      - "${DIRIGENT_PORT:-3333}:3333"
    healthcheck:
      test: ["CMD", "dg", "health", "server"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

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

  worker:
    <<: *dirigent
    command: ["worker"]
    environment:
      <<: *dirigent-env
      DIRIGENT_WORKER_CONCURRENCY: ${DIRIGENT_WORKER_CONCURRENCY:-8}
      # This worker reaches a daemon, so it claims work from a document declaring
      # `requires.workers: [docker]`.
      DIRIGENT_WORKER_TAGS: docker
      # The sidecar daemon, read the same way by the API blocks and by the docker CLI the
      # compose and build blocks shell out to. Only the worker gets these.
      DOCKER_HOST: tcp://docker:2376
      DOCKER_TLS_VERIFY: "1"
      DOCKER_CERT_PATH: /certs/client
    volumes:
      - ./dirigent.yaml:/etc/dirigent/dirigent.yaml:ro
      - ./pipelines:/etc/dirigent/pipelines:ro
      - docker-certs:/certs/client:ro
      # The same volume the daemon mounts, at the same path.
      - work:/var/lib/dirigent/work
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
      s3-bucket:
        condition: service_completed_successfully
      docker:
        condition: service_healthy
    stop_grace_period: 60s
    healthcheck:
      test: ["CMD", "dg", "health", "worker"]
      interval: 15s
      timeout: 10s
      retries: 3
      start_period: 30s

volumes:
  postgres:
  s3:
  # The worker's own working files. Not shared with the server: nothing it does opens one.
  work:
  docker-certs:
  docker-data:
"""

ENV_TEMPLATE = """\
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

# Comma-separated block ids, empty for none. Listing one means whoever can edit a pipeline
# can run code on a worker. The docker.* blocks reach the dind sidecar this stack starts.
#
#   DIRIGENT_ENABLED_UNSAFE_BLOCKS=shell.run,docker.run,docker.compose.up,docker.compose.down
DIRIGENT_ENABLED_UNSAFE_BLOCKS=

# The published image the Dockerfile beside this builds on.
DIRIGENT_IMAGE=ghcr.io/winterop-com/dirigent:__VERSION__
"""

DOCKERFILE_TEMPLATE = """\
# This instance's image: the published dirigent, plus whatever is added below.
ARG DIRIGENT_IMAGE=ghcr.io/winterop-com/dirigent:__VERSION__
FROM ${DIRIGENT_IMAGE}

# A pack is a Python package; install it here and run `docker compose up --build`.
# RUN uv pip install dirigent-dhis2==__VERSION__
"""

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
version = "0.0.0"
description = "A dirigent project: pipeline documents, and the runtime that runs them."
requires-python = ">=3.13"
dependencies = [
    "dirigent-cli==__VERSION__",
]
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
    "basic": (
        "uv sync",
        "uv run dg dev",
        "uv run dg apply",
        "uv run dg run hello-world --watch",
    ),
    "ci": (
        "uv sync",
        "uv run dg dev",
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


#: The templates dg init can scaffold from.
TEMPLATES: Final = ("basic", "ci", "compose")

#: The template whose instance is a container stack rather than a state directory.
COMPOSE_TEMPLATE_NAME: Final = "compose"


def check_template(template: str) -> None:
    """Refuse a template that does not exist, before anything is written or asked for."""
    if template not in TEMPLATES:
        raise ProjectError(f"no template named {template!r}; the built-in templates are basic, ci and compose")


class Scaffolded(BaseModel):
    """What a scaffold wrote, and what it found already there and left alone."""

    model_config = ConfigDict(frozen=True)

    files: list[Path] = Field(default_factory=list[Path])
    skipped: list[Path] = Field(default_factory=list[Path])


def project_name(directory: Path) -> str:
    """Turn a target directory's name into a project name uv and PEP 621 accept."""
    slug = re.sub(r"[^a-z0-9]+", "-", directory.resolve().name.lower()).strip("-")
    return slug or "dirigent-project"


def scaffold(
    directory: Path,
    *,
    template: str = "basic",
    version: str = "0.0.0",
    password: str = "",
) -> Scaffolded:
    """Create a uv project: pyproject, the project file, a pipelines directory, and an example."""
    check_template(template)
    written: list[Path] = []
    skipped: list[Path] = []
    directory.mkdir(parents=True, exist_ok=True)
    written.append(_write(directory / PROJECT_FILE, PROJECT_TEMPLATE + "\n" + project_document()))
    written.append(_write(directory / DEFAULT_PIPELINES_DIR / "hello-world.yaml", EXAMPLE_TEMPLATE))
    written.append(_write(directory / ".dirigent" / "profiles.yaml", PROFILES_TEMPLATE))
    written.append(_write(directory / ".dirigent" / ".gitignore", STATE_IGNORE_TEMPLATE))
    written.append(_write(directory / EXAMPLE_CONFIG_FILE, example_document()))
    name = project_name(directory)
    pyproject = PYPROJECT_TEMPLATE.replace("__NAME__", name).replace("__VERSION__", version)
    _record(directory / "pyproject.toml", pyproject, written, skipped)
    readme = README_TEMPLATE.replace("__NAME__", name).replace("__RUN__", "\n".join(README_RUN[template]))
    _record(directory / "README.md", readme, written, skipped)
    _merge_ignore(directory / ".gitignore", ROOT_IGNORE_TEMPLATE, written, skipped)
    if template == "ci":
        written.append(_write(directory / ".github" / "workflows" / "dirigent.yml", WORKFLOW_TEMPLATE))
    if template == COMPOSE_TEMPLATE_NAME:
        written.append(_write(directory / "compose.yaml", COMPOSE_TEMPLATE.replace("__VERSION__", version)))
        written.append(_write(directory / "Dockerfile", DOCKERFILE_TEMPLATE.replace("__VERSION__", version)))
        environment = (
            ENV_TEMPLATE.replace("__SECRET_KEY__", _an_instance_key())
            .replace("__PASSWORD__", password)
            .replace("__VERSION__", version)
        )
        written.append(_write(directory / ".env", environment, mode=0o600))
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
