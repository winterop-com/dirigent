FROM oven/bun:1.4-alpine@sha256:d888c0ae6c86d7866ff10c5aafdd9077b36aee6455b33dd270fb93c0dd5cef6f AS frontend

WORKDIR /frontend

COPY packages/dirigent-server/frontend/package.json packages/dirigent-server/frontend/bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

# playwright.config.ts is here because tsconfig.e2e.json is a reference of the root project
# that `tsc -b` builds, and a reference with no inputs at all is an error; the specs it also
# names stay out of the image.
COPY packages/dirigent-server/frontend/tsconfig.json \
     packages/dirigent-server/frontend/tsconfig.app.json \
     packages/dirigent-server/frontend/tsconfig.node.json \
     packages/dirigent-server/frontend/tsconfig.e2e.json \
     packages/dirigent-server/frontend/vite.config.ts \
     packages/dirigent-server/frontend/vitest.config.ts \
     packages/dirigent-server/frontend/playwright.config.ts \
     packages/dirigent-server/frontend/index.html \
     ./
COPY packages/dirigent-server/frontend/public/ public/
COPY packages/dirigent-server/frontend/src/ src/
RUN bun run build


FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Every member's pyproject.toml is here because a uv workspace resolves its members
# together; no source, so a code change does not re-resolve the dependency graph.
COPY pyproject.toml uv.lock ./
COPY packages/dirigent-common/pyproject.toml packages/dirigent-common/
COPY packages/dirigent-plugin/pyproject.toml packages/dirigent-plugin/
COPY packages/dirigent-client/pyproject.toml packages/dirigent-client/
COPY packages/dirigent-core/pyproject.toml packages/dirigent-core/
COPY packages/dirigent-parquet/pyproject.toml packages/dirigent-parquet/
COPY packages/dirigent-blocks/pyproject.toml packages/dirigent-blocks/
COPY packages/dirigent-server/pyproject.toml packages/dirigent-server/
COPY packages/dirigent-cli/pyproject.toml packages/dirigent-cli/
COPY packages/dirigent-storage-s3/pyproject.toml packages/dirigent-storage-s3/
COPY packages/dirigent-testing/pyproject.toml packages/dirigent-testing/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-packages --locked --no-dev --extra otlp --extra duckdb --no-install-workspace

COPY packages/ packages/
COPY README.md ./

# The bundle goes where the wheel carries it, so the installed dirigent-server serves the UI
# from its own package directory rather than from a checkout that is not in this image.
COPY --from=frontend /frontend/dist/ packages/dirigent-server/src/dirigent_server/static/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-packages --locked --no-dev --extra otlp --extra duckdb


FROM python:3.13-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca AS runtime

# What an image built FROM this one may rely on: uv on PATH, the venv at /app/.venv named by
# VIRTUAL_ENV so `uv pip install <package>` lands in it, git for a git+https source, and the
# dirigent user, which owns the venv and is the user this stage ends as.
ARG DIRIGENT_VERSION=local
ARG DIRIGENT_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/winterop-com/dirigent" \
      org.opencontainers.image.title="dirigent" \
      org.opencontainers.image.version="${DIRIGENT_VERSION}" \
      org.opencontainers.image.revision="${DIRIGENT_REVISION}"
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# The docker CLI, compose and buildx plugins, so the docker.compose.* and docker.build blocks
# have something to shell out to. The daemon itself is never in this image: these speak to a
# daemon named by DOCKER_HOST -- ideally the worker's own (a dind sidecar over tcp+TLS). Mounting
# the host's /var/run/docker.sock is the discouraged fallback; it grants this container root on
# the host (see docs/operations.md). ca-certificates stays for TLS to a tcp daemon.
#
# git and openssh-client are here for git.checkout, which shells out to git and, for an ssh
# remote, to the ssh binary git runs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce-cli docker-compose-plugin docker-buildx-plugin git openssh-client \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# The uid is fixed so a mounted artifact volume has predictable ownership across hosts.
RUN groupadd --gid 1000 dirigent \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin dirigent

ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DIRIGENT_HOST=0.0.0.0 \
    DIRIGENT_PORT=3333 \
    DIRIGENT_LOG_FORMAT=json \
    DIRIGENT_ARTIFACT_ROOT=file:///var/lib/dirigent/artifacts \
    DIRIGENT_WORK_ROOT=/var/lib/dirigent/work

WORKDIR /app
COPY --from=builder --chown=dirigent:dirigent /app /app

# Without this a worker fails at the first step of the first run rather than at start.
RUN mkdir -p /var/lib/dirigent/artifacts /var/lib/dirigent/work \
    && chown -R dirigent:dirigent /var/lib/dirigent

USER dirigent

# duckdb's httpfs extension, which is what gives sql.query and sql.execute s3:// . It is
# installed here, as the user that will run it -- duckdb resolves an extension from the
# running user's own home -- so a step LOADs it rather than fetching a binary mid-run.
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL httpfs')"

EXPOSE 3333

ENTRYPOINT ["dg"]
CMD ["server"]
