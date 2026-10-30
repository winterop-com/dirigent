"""Layered configuration: defaults, a YAML file, a ``.env``, then DIRIGENT_-prefixed variables."""

import ctypes
import io
import json
import logging
import os
import stat
import sys
from collections.abc import Mapping
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from pydantic_settings.sources.utils import parse_env_vars

from dirigent_common import Duration, EntityName, Size
from dirigent_core.messages import POOL_TOO_SMALL, SECRET_KEY_FILE_UNREADABLE, SECRET_KEY_TWICE

logger = logging.getLogger(__name__)

CONFIG_FILE_ENV = "DIRIGENT_CONFIG_FILE"

SECRET_KEY_ENV = "DIRIGENT_SECRET_KEY"

#: The ``prctl`` option that sets whether a process is dumpable, from ``linux/prctl.h``.
PR_SET_DUMPABLE = 4

#: The project file that carries an instance's own variables, read from the working
#: directory. A command run elsewhere does not see it. None reads no such file.
ENV_FILE: str | None = ".env"

#: Connections a worker process needs beyond its in-flight block calls: one for the lease
#: heartbeat, one for the sweeper, one for the alert loop, and one spare so that none of the
#: three ever queues behind a block call. The heartbeat is the one that must never wait.
POOL_HEADROOM = 4

#: Where a local instance keeps its database and its artifacts, relative to the working
#: directory. Everything under it is disposable state, so `dg init` gitignores it.
STATE_DIR = ".dirigent/state"

#: Relative to the working directory, so these files travel with a checkout.
PROJECT_CONFIG_PATHS = (
    Path("dirigent.yaml"),
    Path(".dirigent/dirigent.yaml"),
)

USER_CONFIG_PATH = Path.home() / ".config" / "dirigent" / "dirigent.yaml"

#: Settings a project's own files may not set: the working directory's `.env` and YAML skip them.
HOST_ONLY_SETTINGS = frozenset({"enabled_unsafe_blocks"})


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


def host_config_paths() -> list[Path]:
    """List the YAML files that speak for the host: the one the environment names, or the user's."""
    named = os.environ.get(CONFIG_FILE_ENV)
    return [Path(named)] if named else [USER_CONFIG_PATH]


def project_config_paths() -> list[Path]:
    """List the YAML files in the working directory that apply, most specific last."""
    return [] if os.environ.get(CONFIG_FILE_ENV) else list(reversed(PROJECT_CONFIG_PATHS))


def read_project_file(path: Path) -> str | None:
    """Read a file a project supplies, or answer none unless it may be trusted as the project's own.

    Neither the file nor its directory may be a symbolic link, and the file must be a regular
    one this user owns that neither group nor others may write. Every check is made on the
    opened descriptor, so the file read is the file checked.
    """
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, encoding="utf-8") as opened:
            status = os.fstat(opened.fileno())
            if not stat.S_ISREG(status.st_mode):
                return None
            if status.st_uid != os.getuid() or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return None
            return opened.read()
    except (OSError, UnicodeDecodeError):
        return None


class _ProjectDotEnv(DotEnvSettingsSource):
    """A project's ``.env``: a file ``read_project_file`` accepts, with ``${VAR}`` left as text."""

    def _read_env_file(self, file_path: Path) -> Mapping[str, str | None]:
        """Read one file without following a link and without consulting the environment."""
        text = read_project_file(file_path)
        if text is None:
            return {}
        values = dotenv_values(stream=io.StringIO(text), interpolate=False)
        return parse_env_vars(values, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str)


class _ProjectLayer(PydanticBaseSettingsSource):
    """One settings layer read from a project's files, with the host-only settings taken out."""

    def __init__(self, layer: PydanticBaseSettingsSource) -> None:
        super().__init__(layer.settings_cls)
        self._layer = layer

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """Answer for one field the way the wrapped layer does."""
        return self._layer.get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        """Read the wrapped layer, without the settings it may not set."""
        return {name: value for name, value in self._layer().items() if name not in HOST_ONLY_SETTINGS}


class Settings(BaseSettings):
    """The effective instance configuration, shared by the server, the workers, and the CLI."""

    model_config = SettingsConfigDict(
        env_prefix="DIRIGENT_",
        env_nested_delimiter="__",
        # A project's .env carries DG_TOKEN and a stack's own variables beside the settings,
        # and none of those name a field here.
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

    playground_enabled: bool = True
    """Whether the instance serves the playground beside the API.

    The playground is a handful of unauthenticated routes under the API that generate data
    and behaviour for examples and tests: they open no database session, read no instance
    data, and remember nothing. Off, none of them is mounted and every playground path
    answers 404. An instance on a public address that has no use for them turns them off.
    """

    ui_dir: Path | None = None
    """A built web UI bundle to serve, instead of the one installed with the server.

    A server installed from a git checkout carries no bundle of its own; this names the
    ``dist`` directory a checkout's ``make ui`` produced. A directory with no ``index.html``
    serves nothing, as an absent bundle does.
    """

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    """How loud the process log is. This is the process log; a run's own telemetry is the
    ``log_entries`` table, and a CLI ``-v`` or ``--debug`` flag wins over this."""

    log_format: Literal["console", "json"] | None = None
    """How a command spells its output and its logs: ``console`` renders, ``json`` writes records.

    Unset, the terminal decides: a terminal gets the rendering, and a pipe, a container's log,
    an agent's shell and CI get NDJSON, ``dg dev`` and ``dg server`` included. A command's
    ``--json`` or ``-o console`` wins over it.
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

    secret_key_file: Path | None = None
    """A file holding the envelope key, in place of ``secret_key``; setting both is refused.

    Read once at start-up, its surrounding whitespace dropped. The key is then never in the
    process's environment, which is what ``/proc/<pid>/environ`` shows."""

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

    lease_recovery_limit: int = Field(default=5, ge=0)
    """How many times one attempt may be taken back from a worker and run again before it fails."""

    heartbeat: Duration = Field(default=timedelta(seconds=15), ge=timedelta(seconds=1))
    """How often a worker refreshes the leases it holds and its registry row."""

    claim_idle: Duration = Field(default=timedelta(milliseconds=500), gt=timedelta(0))
    """How long an idle worker waits before asking for work again when nothing wakes it.

    A commit that queues work wakes an idle worker at once, so this is what a lost wake-up
    costs rather than the latency a run sees."""

    log_flush_interval: Duration = Field(default=timedelta(seconds=1), gt=timedelta(0))
    """How often a running attempt's buffered log entries are written to the run.

    A step's lines reach the run screen and ``dg run --watch`` within this rather than at the
    moment the step ends, so a ten-minute command is visible working. A step that logs faster
    than the interval flushes sooner, when its buffer fills."""

    fan_out_max_items: int = Field(default=10000, ge=1)
    """How many items one fan-out grid may expand into; a run that would be wider is refused.

    A grid fixed at creation over it refuses the run. One read from a step's output is
    expanded when that step has settled, so there the gate fails as ``rejected`` instead."""

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
    """A worker whose last heartbeat is older than this has its registry row reaped by the sweeper."""

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

    retention_inputs: Duration | None = None
    """How long the record of an input that reached a source is kept."""

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
    """Block ids permitted to execute code on a worker; empty means none. A `.env` or YAML file
    in the working directory cannot set this."""

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

    endpoint_prefix: str = "/endpoints"
    """Where endpoint sources are served, outside the versioned API.

    A proxy in front of an instance publishes this prefix and ``/hooks`` and keeps
    ``/api/v1`` inside, so a source's route is public without the API being so."""

    source_max_body: Size = Field(default=1_048_576, ge=1)
    """The largest body any endpoint reads, whatever its own ``max_body`` says; reading stops one byte past it."""

    source_body_timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """How long an endpoint waits for a whole body before it answers 408; no database connection is held meanwhile."""

    source_intake_rate_per_minute: int = Field(default=600, ge=1)
    """How fast one address's calls to one method and route are taken, before any source is read.

    A source's own ``rate`` applies on top of this."""

    source_signature_window: Duration = Field(default=timedelta(minutes=5), gt=timedelta(0))
    """How far a signed call's ``X-Dirigent-Timestamp`` may stand from this server's clock, either way.

    A signature is taken once inside it, and a call signed outside it is refused."""

    source_reply_max: Duration = Field(default=timedelta(seconds=60), gt=timedelta(0))
    """The longest a caller is held for a reply, whatever a reply node's ``timeout`` says."""

    source_max_waiting: int = Field(default=256, ge=1)
    """How many callers one server process holds open for their replies at once.

    A call past it is answered 503 before its run is created."""

    source_max_waiting_per_source: int = Field(default=64, ge=1)
    """How many of those callers one source may hold, so one slow pipeline cannot take every seat.

    A call past it is answered 503 before its run is created."""

    source_reply_poll: Duration = Field(default=timedelta(milliseconds=50), gt=timedelta(0))
    """The least time between two reads of the replies one server process's held callers wait for."""

    source_poll_tick: Duration = Field(default=timedelta(seconds=5), gt=timedelta(0))
    """How often a worker looks for polled sources that are due."""

    source_poll_lease: Duration = Field(default=timedelta(minutes=5), gt=timedelta(0))
    """How long a worker holds a worker-hosted source without renewing; another may take it once this passes."""

    source_poll_batch: int = Field(default=100, ge=1)
    """The most inputs one poll may hand over, before the source's own ``max_in_flight``."""

    source_held_max: int = Field(default=16, ge=1)
    """How many held sources, such as queue consumers, one worker keeps open at once."""

    source_hold_wait: Duration = Field(default=timedelta(seconds=1), gt=timedelta(0))
    """How long a held source's consumer waits for a message before the worker checks on it."""

    source_backoff: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """How long a polled source waits after a failed poll; later failures double it."""

    source_backoff_max: Duration = Field(default=timedelta(minutes=30), gt=timedelta(0))
    """The longest a polled source backs off, however many polls in a row have failed."""

    login_rate_per_minute: int = Field(default=10, ge=1)
    """How many login attempts one username gets a minute from one address.

    Counted per address, so a caller elsewhere cannot lock an account out of login."""

    login_address_rate_per_minute: int = Field(default=60, ge=1)
    """How many login attempts one address gets a minute, across every username.

    The login route is unauthenticated and verifying a password costs Argon2id at 64 MiB, so
    without this limit a flood of requests exhausts the instance's memory and CPU."""

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

    @field_validator("api_prefix", "endpoint_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        """Keep a prefix rooted and free of a trailing slash."""
        prefix = "/" + value.strip("/")
        return prefix.rstrip("/") or "/"

    @model_validator(mode="before")
    @classmethod
    def _read_secret_key_file(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Put the key a named file holds where ``secret_key`` is read from, refusing two sources."""
        named = data.get("secret_key_file")
        if not named:
            return data
        if data.get("secret_key"):
            raise ValueError(SECRET_KEY_TWICE.render())
        try:
            key = Path(named).expanduser().read_text().strip()
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(SECRET_KEY_FILE_UNREADABLE.render(path=str(named), detail=str(error))) from error
        if not key:
            raise ValueError(SECRET_KEY_FILE_UNREADABLE.render(path=str(named), detail="it is empty"))
        return {**data, "secret_key": key}

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
                POOL_TOO_SMALL.render(
                    size=self.database_pool_size,
                    overflow=self.database_max_overflow,
                    ceiling=ceiling,
                    concurrency=self.worker_concurrency,
                    needed=needed,
                    headroom=POOL_HEADROOM,
                )
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
        """Order the layers: explicit arguments, the environment, the ``.env``, then the YAML files."""
        project_yaml = YamlConfigSettingsSource(settings_cls, yaml_file=project_config_paths())
        host_yaml = YamlConfigSettingsSource(settings_cls, yaml_file=host_config_paths())
        project_env = _ProjectDotEnv(settings_cls, env_file=ENV_FILE)
        return (init_settings, env_settings, _ProjectLayer(project_env), _ProjectLayer(project_yaml), host_yaml)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, resolved once."""
    return Settings()


def reset_settings_cache() -> None:
    """Forget the cached settings, so a test or a CLI flag can re-resolve them."""
    get_settings.cache_clear()


def drop_secret_key_variable() -> None:
    """Take the envelope key out of ``os.environ``, for a process whose settings already hold it.

    What a child inherits by default and what a library reads from ``os.environ`` stop finding
    it. The kernel keeps the environment a process started with, in ``/proc/<pid>/environ``,
    which :func:`keep_same_user_out` closes on Linux.
    """
    os.environ.pop(SECRET_KEY_ENV, None)


def keep_same_user_out() -> None:
    """Stop another process of this user reading this one through ``/proc`` or attaching to it.

    On Linux this clears the process's dumpable flag. ``/proc/<pid>/environ``, ``mem``, ``maps``
    and ``fd`` stop opening for a process of the same user, ptrace refuses it, and this process
    writes no core dump. This process keeps ``/proc/self/fd``, and loses its own ``environ`` and
    ``mem``. A child gets the flag back for itself when it executes a program. It does nothing
    on any other platform.
    """
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        logger.warning(
            "could not clear the dumpable flag, so a process of this user can read this one through /proc: %s",
            os.strerror(ctypes.get_errno()),
        )


def redacted_url(settings: Settings) -> str:
    """Render the database URL without its password, for anything a person reads."""
    url = settings.database_url
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
