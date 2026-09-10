"""Layered configuration: defaults, a YAML file, then DIRIGENT_-prefixed environment variables."""

import json
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from dirigent_common import Duration, EntityName, Size

CONFIG_FILE_ENV = "DIRIGENT_CONFIG_FILE"

#: Connections a worker process needs beyond its in-flight block calls: one for the lease
#: heartbeat, one for the sweeper, one for the alert loop, and one spare so that none of the
#: three ever queues behind a block call. The heartbeat is the one that must never wait.
POOL_HEADROOM = 4

#: Where a local instance keeps its database and its artifacts, relative to the working
#: directory. Everything under it is disposable state, so `dg init` gitignores it.
STATE_DIR = ".dirigent/state"

DEFAULT_CONFIG_PATHS = (
    Path("dirigent.yaml"),
    Path(".dirigent/dirigent.yaml"),
    Path.home() / ".config" / "dirigent" / "dirigent.yaml",
)


def parse_string_list(value: object) -> object:
    """Read a list setting written as either a comma-separated string or a JSON array."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_string_mapping(value: object) -> object:
    """Read a mapping setting written as either comma-separated ``key=value`` pairs or JSON."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError:
            pass
    pairs = [item.strip() for item in text.split(",") if item.strip()]
    return {key.strip(): held.strip() for key, _, held in (pair.partition("=") for pair in pairs)}


def candidate_config_paths() -> list[Path]:
    """List the YAML files that contribute to the effective configuration, most specific last."""
    named = os.environ.get(CONFIG_FILE_ENV)
    if named:
        return [Path(named)]
    return list(reversed(DEFAULT_CONFIG_PATHS))


class Settings(BaseSettings):
    """The effective instance configuration, shared by the server, the workers, and the CLI."""

    model_config = SettingsConfigDict(
        env_prefix="DIRIGENT_",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
        # Each field's docstring becomes its description, which is what the generated
        # reference and the scaffolded example file are written from.
        use_attribute_docstrings=True,
    )

    environment: Literal["local", "staging", "prod"] = "local"
    """Which deployment this instance believes it is, reported on telemetry."""

    database_url: str = f"sqlite+aiosqlite:///./{STATE_DIR}/dirigent.db"
    """Where the instance's own state lives, as a SQLAlchemy async URL.

    A URL starting with ``sqlite`` puts the instance in single-process mode: one process may
    hold it, which is what ``dg dev`` runs. PostgreSQL is ``postgresql+asyncpg://...``, and
    is what more than one worker requires. The default is relative to the working directory,
    and its directory is created on start."""

    database_echo: bool = False
    """Echo every SQL statement to the process log. Debugging only; it is very loud."""

    database_pool_size: int = Field(default=12, ge=1)
    """How many database connections one process keeps open. Ignored by SQLite.

    It moves with ``worker_concurrency``: every executing attempt wants a session, and so do
    the lease heartbeat, the sweeper and the alert loop. An instance refuses to start where
    the pool cannot cover them, because the loop that loses is the heartbeat, and an expired
    lease means the sweeper reclaims a live attempt and non-idempotent work runs twice."""

    database_max_overflow: int = Field(default=4, ge=0)
    """Connections the pool may open beyond ``database_pool_size`` under a burst."""

    database_pool_timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """How long a checkout waits for a free connection before failing loudly."""

    database_pool_recycle: Duration | None = timedelta(minutes=30)
    """Recycle a pooled connection older than this; unset disables recycling."""

    host: str = "127.0.0.1"
    """The address the API server binds. A container needs ``0.0.0.0`` to be reachable."""

    port: int = Field(default=3333, ge=1, le=65535)
    """The port the API server binds."""

    api_prefix: str = "/api/v1"
    """Where the versioned REST API is mounted. ``/hooks/{token}`` is not under it.

    A client has to be told the same thing, through a profile's ``api_prefix`` or the SDK's
    argument of that name: an instance that moves its API and tells nobody is one its own
    CLI cannot reach.
    """

    ui_enabled: bool = True
    """Whether the server serves the bundled web UI beside the API.

    Off, the process is the API and nothing else: no ``/``, no ``/assets``, no
    ``/config.json``. On with no bundle built, ``/`` answers a refusal naming how to build
    one, and every API route is unaffected either way.
    """

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    """How loud the process log is. This is the process log; a run's own telemetry is the
    ``log_entries`` table, and a CLI ``-v`` or ``--debug`` flag wins over this."""

    log_format: Literal["console", "json"] = "console"
    """How a command spells a log line: ``console`` for a person, ``json`` for a collector.

    The four process commands write NDJSON whatever this says.
    """

    artifact_root: str = f"file://./{STATE_DIR}/artifacts"
    """Default storage backend URI prefix for run scratch space and artifacts."""

    work_root: str = f"./{STATE_DIR}/work"
    """Directory on this worker's own filesystem where a run's local working files go.

    A path, not a URI, and never shared: a checkout, a build context, a compose file and a
    bind mount are things a tool opens through the filesystem, so they cannot live in the
    bucket the artifact root addresses. What a step leaves here is reachable only by the
    worker that wrote it."""

    storage_connections: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict[str, str])
    """Which connection configures each storage scheme, as ``scheme -> connection code``.

    A scheme with no entry keeps whatever its package contributed it with, which for ``s3://``
    is the ambient AWS credential chain."""

    inline_artifact_max: Size = Field(default=16384, ge=0)
    """Outputs at or below this serialized size are stored inline instead of as a file."""

    inline_capture: Size = Field(default=8192, ge=0)
    """How much of a captured stream a block may inline in its output.

    A chatty job is worth raising this for; the whole stream is in storage either way."""

    secret_key: SecretStr | None = None
    """Envelope key for connection secrets; required before any secret is stored."""

    worker_concurrency: int = Field(default=8, ge=1)
    """How many step attempts one worker process executes at once.

    Attempts, not runs and not pipelines: eight steps of one run, one step each from eight
    runs, or any mix. A waiting attempt holds no slot -- a sensor between pokes, or an
    operator whose remote job is still running, is a parked row with a due time, and its
    probe occupies a slot only while it runs -- so one worker at 8 can have hundreds of runs
    in flight. This bounds simultaneously executing work and nothing else.

    It is one of three separate limits, which are easy to confuse: this bounds one worker, a
    pipeline's own ``concurrency`` policy bounds overlapping runs of that pipeline, and
    running more workers multiplies this one. Nothing bounds an instance's total runs, by
    design. Raise it together with ``database_pool_size``: every executing attempt wants a
    session, and a pool smaller than the concurrency starves the lease heartbeat."""

    worker_tags: Annotated[list[str], NoDecode] = Field(default_factory=list[str])
    """Capability tags a worker advertises to the claim query."""

    worker_name: EntityName | None = None
    """Registry name of this worker; defaults to hostname plus process id."""

    lease: Duration = Field(default=timedelta(seconds=60), ge=timedelta(seconds=5))
    """How long a claimed attempt's lease is valid before the sweeper may reclaim it."""

    heartbeat: Duration = Field(default=timedelta(seconds=15), ge=timedelta(seconds=1))
    """How often a worker refreshes the leases it holds and its registry row."""

    claim_idle: Duration = Field(default=timedelta(milliseconds=500), gt=timedelta(0))
    """How long a worker waits before asking for work again when the queue is empty."""

    log_flush_interval: Duration = Field(default=timedelta(seconds=1), gt=timedelta(0))
    """How often a running attempt's buffered log entries are written to the run.

    A step's lines reach the run screen and ``dg run --watch`` within this rather than at the
    moment the step ends, so a ten-minute command is visible working. A step that logs faster
    than the interval flushes sooner, when its buffer fills."""

    log_entries_per_attempt: int = Field(default=1000, ge=1)
    """How many entries one attempt may log before the rest are dropped with one warning."""

    log_flush_batch: int = Field(default=100, ge=1)
    """How many buffered entries write themselves without waiting for the flush interval.

    A wider batch sends fewer, larger transactions and makes a chatty step's lines wait
    longer to become visible."""

    sweep_interval: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """How often a worker runs the crash-recovery sweeper over expired leases."""

    stuck_run: Duration = Field(default=timedelta(hours=1), gt=timedelta(0))
    """A running run with no attempt progress for this long is flagged as stuck."""

    stale_worker: Duration = Field(default=timedelta(minutes=15), gt=timedelta(0))
    """A worker whose registry row is older than this has that row reaped by the sweeper."""

    docker_reap_interval: Duration = timedelta(minutes=5)
    """How often a docker-capable worker looks for compose stacks whose run has ended.

    Zero turns the reaper off, which is what a worker with no daemon wants."""

    docker_reap_grace: Duration = timedelta(minutes=10)
    """How old a compose project must be before the reaper will consider it at all.

    A project's age is its newest container's, so a stack still being built up is young."""

    retention_runs: Duration | None = None
    """How long a settled run is kept, with its items, attempts, artifacts and alerts."""

    retention_logs: Duration | None = None
    """How long a log entry is kept, for runs too young to be pruned themselves."""

    retention_deliveries: Duration | None = None
    """How long a webhook delivery is kept."""

    retention_firings: Duration | None = None
    """How long a schedule firing is kept."""

    retention_notifications: Duration | None = None
    """How long an alert that was sent is kept, for runs too young to be pruned themselves."""

    retention_scratch: bool = True
    """Whether pruning a run also deletes its artifacts from storage."""

    retention_interval: Duration = timedelta(hours=1)
    """How often the scheduler sweeps whatever the retention ages have outlived."""

    retention_batch: int = Field(default=500, ge=1)
    """How many rows of one family a single sweep deletes before committing."""

    lost_job_max_gone: int = Field(default=3, ge=1)
    """Consecutive GONE probes before the lost-job policy fails a waiting attempt."""

    enabled_unsafe_blocks: Annotated[list[str], NoDecode] = Field(default_factory=list[str])
    """Block ids permitted to execute code on a worker; empty means none."""

    scheduler_enabled: bool = True
    """Whether `dg server` embeds the scheduler rather than leaving it to its own process."""

    scheduler_tick: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    """How often the leader asks the database which schedules are due."""

    scheduler_misfire_grace: Duration = timedelta(minutes=5)
    """How late a firing may be before it counts as a misfire: fire once, advance, no catchup storm."""

    scheduler_lock_key: int = Field(default=0x64_69_72_67)
    """The advisory-lock key leadership is taken on; only PostgreSQL has one to take."""

    apply_dir: Path | None = None
    """A directory of pipeline documents the server applies at boot; unset applies nothing."""

    apply_prune: bool = False
    """Whether the boot apply also deactivates directory-provenance pipelines absent from it."""

    apply_lock_key: int = Field(default=0x64_69_72_61)
    """The advisory-lock key the boot apply is serialised on, distinct from the scheduler's."""

    notification_max_attempts: int = Field(default=5, ge=1)
    """How many times a notification delivery is retried before it is recorded as failed."""

    notification_backoff: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The delay after a notification's first failed delivery; later ones double from it."""

    notification_lease: Duration = Field(default=timedelta(seconds=60), ge=timedelta(seconds=5))
    """How long a claimed notification's lease is valid before another worker may take it."""

    webhook_max_payload: Size = Field(default=1_048_576, ge=1)
    """The largest body the webhook intake will read; reading stops one byte past it."""

    webhook_intake_rate_per_minute: int = Field(default=120, ge=1)
    """How fast one *offered* token may deliver, before anything is looked up.

    A real webhook's own ``rate_limit_per_minute`` applies on top of this."""

    login_rate_per_minute: int = Field(default=10, ge=1)
    """How many login attempts one address, and one username, get a minute.

    The login route is unauthenticated and verifying a password costs Argon2id at 64 MiB, so
    without this limit a flood of requests exhausts the instance's memory and CPU. It is
    counted per address *and* per username, covering both a flood and credential stuffing."""

    alert_base_url: str | None = None
    """The externally reachable base URL, so an alert can link back to the run it is about."""

    report_max_size: Size = Field(default=1 * 1024 * 1024, ge=1)
    """A run's report document larger than this is dropped with a warning in the run's log."""

    report_render_timeout: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    """How long a report template may take to render before it is dropped with a warning."""

    @field_validator("worker_tags", "enabled_unsafe_blocks", mode="before")
    @classmethod
    def _read_list(cls, value: object) -> object:
        """Accept a comma-separated string for a list setting."""
        return parse_string_list(value)

    @field_validator("storage_connections", mode="before")
    @classmethod
    def _read_mapping(cls, value: object) -> object:
        """Accept a comma-separated ``key=value`` string for a mapping setting."""
        return parse_string_mapping(value)

    @field_validator("api_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        """Keep the API prefix rooted and free of a trailing slash."""
        prefix = "/" + value.strip("/")
        return prefix.rstrip("/") or "/"

    @model_validator(mode="after")
    def _pool_covers_concurrency(self) -> "Settings":
        """Refuse a pool too small for the concurrency it has to carry.

        A worker running ``worker_concurrency`` block calls at once needs a connection per
        outcome transaction, and the heartbeat, the sweeper and the alert loop each need one
        too. When the pool cannot cover them the heartbeat is the loop that loses, so leases
        expire under load, the sweeper reclaims live attempts, and non-idempotent work runs
        twice. The failure surfaces as a duplicate rather than as pool exhaustion.
        """
        if self.is_sqlite:
            return self
        ceiling = self.database_pool_size + self.database_max_overflow
        needed = self.worker_concurrency + POOL_HEADROOM
        if ceiling < needed:
            raise ValueError(
                f"database_pool_size ({self.database_pool_size}) plus database_max_overflow "
                f"({self.database_max_overflow}) is {ceiling} connections, and a worker at "
                f"worker_concurrency={self.worker_concurrency} needs at least {needed} "
                f"(one per in-flight call, plus {POOL_HEADROOM} for the heartbeat, the sweeper "
                "and the alert loop). Raise the pool or lower the concurrency."
            )
        return self

    @property
    def is_sqlite(self) -> bool:
        """Report whether this instance runs on SQLite, where multi-process modes are refused."""
        return self.database_url.startswith("sqlite")

    @property
    def sqlite_path(self) -> Path | None:
        """The file a SQLite URL addresses, or None on PostgreSQL or an in-memory database."""
        if not self.is_sqlite:
            return None
        target = self.database_url.partition("///")[2].split("?", 1)[0]
        if not target or target.startswith(":memory:"):
            return None
        return Path(target)

    @property
    def sync_database_url(self) -> str:
        """Render the database URL with a synchronous driver, which Alembic uses offline."""
        return self.database_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order the layers: explicit arguments, then environment, then the YAML file."""
        yaml_settings = YamlConfigSettingsSource(settings_cls, yaml_file=candidate_config_paths())
        return (init_settings, env_settings, dotenv_settings, yaml_settings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, resolved once."""
    return Settings()


def reset_settings_cache() -> None:
    """Forget the cached settings, so a test or a CLI flag can re-resolve them."""
    get_settings.cache_clear()


def redacted_url(settings: Settings) -> str:
    """Render the database URL without its password, for anything a person reads."""
    url = settings.database_url
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
