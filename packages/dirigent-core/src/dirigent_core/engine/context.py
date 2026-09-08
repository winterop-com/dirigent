"""The engine's side of the bargain: the StepContext a block is handed.

Log entries are buffered rather than written as they are emitted. The executor flushes the
buffer while the attempt runs, and the outcome transaction writes whatever is left, so a
long step is visible working and its last lines still land with the outcome.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
import sqlalchemy as sa
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import LogLevel
from dirigent_common import JsonMap
from dirigent_core.logging import debug_kept, get_logger
from dirigent_core.models import Connection, Schema
from dirigent_core.secrets import SecretBox
from dirigent_core.storage import AttemptStorage, Storage, work_dir
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, Logger, Runs, StorageBackend

#: What an HTTP connection is assumed to call its fields, so core can build a client for
#: any connection kind without importing the package that contributed it.
BASE_URL_FIELD = "base_url"
VERIFY_TLS_FIELD = "verify_tls"
TIMEOUT_FIELD = "timeout"
BEARER_FIELD = "bearer_token"
API_TOKEN_FIELD = "api_token"
API_TOKEN_SCHEME_FIELD = "api_token_scheme"
BASIC_USER_FIELD = "basic_username"
BASIC_PASSWORD_FIELD = "basic_password"

#: The authorization scheme an ``api_token`` is sent under when the config names none, which
#: is the scheme a DHIS2 personal access token is presented with.
DEFAULT_API_TOKEN_SCHEME = "ApiToken"

DEFAULT_HTTP_TIMEOUT = 30.0

_logger = get_logger("block")


class UnknownConnection(BlockFailure):
    """A block asked for a connection this instance does not have."""

    def __init__(self, ref: str, known: list[str]) -> None:
        """Name the connection and the ones that exist, and refuse to retry."""
        available = ", ".join(sorted(known)) or "none are configured"
        super().__init__(f"no connection coded {ref!r} ({available})", error_class=ErrorClass.REJECTED)


class UnknownSchema(BlockFailure):
    """A block asked for a named schema this instance does not hold."""

    def __init__(self, code: str, known: list[str]) -> None:
        """Name the schema and the ones that exist, and refuse to retry."""
        available = ", ".join(sorted(known)) or "none are held"
        super().__init__(f"no schema coded {code!r} ({available})", error_class=ErrorClass.REJECTED)


class ConnectionRecord(BaseModel):
    """One stored connection, still sealed, as the claim transaction snapshotted it."""

    model_config = ConfigDict(frozen=True)

    code: str
    kind: str
    config: JsonMap
    envelope: bytes | None = None
    key_id: str | None = None


async def load_connections(session: AsyncSession) -> dict[str, ConnectionRecord]:
    """Snapshot every connection for one attempt.

    The whole table is read because ``StepContext.connection`` is synchronous by contract and
    a block may ask for any code at any point in its call.
    """
    rows = await session.execute(sa.select(Connection))
    return {
        row.code: ConnectionRecord(
            code=row.code,
            kind=row.kind,
            config=dict(row.config),
            envelope=row.secret_envelope,
            key_id=row.secret_key_id,
        )
        for row in rows.scalars()
    }


async def load_schemas(session: AsyncSession) -> dict[str, JsonMap]:
    """Snapshot every named schema for one attempt, code to its JSON Schema body.

    The whole table is read for the same reason connections are: ``StepContext.schema`` is
    synchronous by contract, so a block may name any code at any point in its call.
    """
    rows = await session.execute(sa.select(Schema))
    return {row.code: dict(row.body) for row in rows.scalars()}


MAX_MESSAGE_CHARS: Final = 4000


def buffer_full(limit: int) -> str:
    """The one warning a step that logged past its quota gets in place of the rest."""
    return f"this step logged more than {limit} entries; the rest were dropped"


#: One log entry as an insert's parameters: what the buffer holds and what a flush sends.
type LogRow = dict[str, Any]


def log_row(
    *,
    run_id: UUID,
    run_item_id: UUID | None,
    step_attempt_id: UUID | None,
    step_name: str,
    level: LogLevel,
    message: str,
    fields: JsonMap | None,
    created_at: datetime,
) -> LogRow:
    """Spell one entry as an insert's parameters, which a failed flush can send again."""
    return {
        "run_id": run_id,
        "run_item_id": run_item_id,
        "step_attempt_id": step_attempt_id,
        "step_name": step_name,
        "level": level,
        "message": message,
        "fields": fields,
        "created_at": created_at,
    }


#: Severity order, for the keep gate: an entry below the kept level is dropped at record time.
LEVEL_RANK: Final = {LogLevel.DEBUG: 0, LogLevel.INFO: 1, LogLevel.WARNING: 2, LogLevel.ERROR: 3}


def kept_level(log_levels: Mapping[str, object] | None, block_id: str) -> LogLevel:
    """Resolve which level a run keeps for one block, from its pattern map.

    Patterns are fnmatch over the block id, and the most specific match wins -- the longest
    pattern, with ``*`` last -- so ``{"*": "info", "dhis2.*": "debug"}`` is one loud family
    in a quiet run. No map, and no matching pattern, keep info and up.
    """
    if not log_levels:
        return LogLevel.INFO
    chosen: tuple[int, LogLevel] | None = None
    for pattern, value in log_levels.items():
        if not fnmatch(block_id, pattern):
            continue
        specificity = len(pattern) if pattern != "*" else -1
        if chosen is None or specificity > chosen[0]:
            chosen = (specificity, LogLevel(str(value)))
    return chosen[1] if chosen is not None else LogLevel.INFO


class BufferedLogger(BaseModel):
    """The scoped log a block writes to: buffered in memory, flushed while the attempt runs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: UUID
    step_name: str
    step_attempt_id: UUID | None = None
    run_item_id: UUID | None = None
    limit: int
    """How many entries this attempt may log before the rest are dropped with one warning."""
    batch: int
    """How many buffered entries set ``full``, which is what wakes the flusher early."""
    keep: LogLevel = LogLevel.INFO
    """The least severe level this run keeps for the block behind this buffer."""
    entries: list[LogRow] = Field(default_factory=list[LogRow])
    recorded: int = 0
    """How many entries this attempt has logged, including the ones already flushed."""
    full: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set when the buffer reaches the size gate, which is what wakes the flusher."""

    def debug(self, message: str, **fields: JsonValue) -> None:
        """Record a debug-level entry."""
        self._record(LogLevel.DEBUG, message, fields)

    def info(self, message: str, **fields: JsonValue) -> None:
        """Record an info-level entry."""
        self._record(LogLevel.INFO, message, fields)

    def warning(self, message: str, **fields: JsonValue) -> None:
        """Record a warning-level entry."""
        self._record(LogLevel.WARNING, message, fields)

    def error(self, message: str, **fields: JsonValue) -> None:
        """Record an error-level entry."""
        self._record(LogLevel.ERROR, message, fields)

    def _record(self, level: LogLevel, message: str, fields: JsonMap) -> None:
        """Buffer one product-telemetry entry and mirror it to the process log."""
        if LEVEL_RANK[level] < LEVEL_RANK[self.keep]:
            return
        if self.recorded > self.limit:
            return
        if self.recorded == self.limit:
            level, message, fields = LogLevel.WARNING, buffer_full(self.limit), {}
        elif len(message) > MAX_MESSAGE_CHARS:
            message = f"{message[:MAX_MESSAGE_CHARS]} [truncated, {len(message)} characters]"
        self.entries.append(
            log_row(
                run_id=self.run_id,
                run_item_id=self.run_item_id,
                step_attempt_id=self.step_attempt_id,
                step_name=self.step_name,
                level=level,
                message=message,
                fields=dict(fields) or None,
                created_at=datetime.now(UTC),
            )
        )
        self.recorded += 1
        if len(self.entries) >= self.batch:
            self.full.set()
        # The mirror renders every line it is given, so the level is checked before the call
        # rather than inside it. The block's own fields are nested rather than spread: a block
        # is free to name one of them `level` or `event`, and spreading those raises a
        # TypeError out of the block's log call.
        if debug_kept():
            _logger.debug(message, log_level=level.value, fields=dict(fields))

    def drain(self) -> list[LogRow]:
        """Take the buffered entries, leaving the logger empty for the next call."""
        taken, self.entries = self.entries, []
        self.full.clear()
        return taken

    def restore(self, entries: list[LogRow]) -> None:
        """Put drained entries back at the front, for the next flush or the outcome."""
        self.entries = entries + self.entries
        if len(self.entries) >= self.batch:
            self.full.set()


class EngineStepContext:
    """The concrete StepContext the engine hands a block for exactly one call."""

    def __init__(
        self,
        *,
        run_id: UUID,
        step: str,
        run_item_id: UUID | None,
        attempt: int,
        started_at: datetime,
        inline_capture: int,
        params: JsonMap,
        log: BufferedLogger,
        storage: Storage,
        scratch: str,
        work_root: str,
        connections: dict[str, ConnectionRecord],
        connection_models: dict[str, type[BaseModel]],
        secrets: SecretBox,
        runs: Runs,
        format_checker: FormatChecker,
        storage_connections: Mapping[str, str] | None = None,
        schemas: dict[str, JsonMap] | None = None,
        cursor: JsonMap | None = None,
    ) -> None:
        """Bind the context to one attempt's scope."""
        self.run_id: UUID = run_id
        self.step: str = step
        self.run_item_id: UUID | None = run_item_id
        self.attempt: int = attempt
        self.started_at: datetime = started_at
        self.inline_capture: int = inline_capture
        self.cursor: JsonMap | None = cursor
        self.params: Mapping[str, JsonValue] = params
        self.log: Logger = log
        self._buffer = log
        self._storage = storage
        self._scratch = scratch
        self._work_root = work_root
        self._connections = connections
        self._connection_models = connection_models
        self._schemas = schemas or {}
        self._secrets = secrets
        self._runs = runs
        self._format_checker = format_checker
        self._storage_connections = dict(storage_connections or {})
        self._bound_storage: AttemptStorage | None = None

    @property
    def storage(self) -> AttemptStorage:
        """Access URI-addressed storage across every registered scheme.

        A scheme configured from a coded connection is bound on first use, on the worker path,
        where connection secrets are opened and nowhere else.
        """
        if self._bound_storage is None:
            self._bound_storage = self._storage.bound_by(self._configure_backend)
        return self._bound_storage

    def _configure_backend(self, scheme: str, backend: StorageBackend) -> StorageBackend:
        """Bind one scheme to the connection this instance configures it from, if it names one."""
        ref = self._storage_connections.get(scheme)
        if ref is None:
            return backend
        return backend.configured(self.connection(ref, backend.config_model))

    @property
    def scratch(self) -> str:
        """Return the run-scoped URI prefix for intermediate artifacts."""
        return self._scratch

    @property
    def work(self) -> Path:
        """Return the run's directory on this worker's own filesystem, made on first read.

        Absolute whatever the setting said: a child process is given both a working directory
        and the paths it is to touch, and a relative one would be resolved twice.
        """
        directory = work_dir(self._work_root, self.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def runs(self) -> Runs:
        """Start, observe, and cancel runs on this instance, attributed to the calling run."""
        return self._runs

    def connection[C: BaseModel](self, ref: ConnectionRef, model: type[C]) -> C:
        """Resolve a connection by code, opened and validated against the block's own model."""
        record = self._connections.get(ref)
        if record is None:
            raise UnknownConnection(ref, list(self._connections))
        return self._secrets.decrypt_config(model, record.config, record.envelope, key_id=record.key_id)

    def storage_connection[C: BaseModel](self, scheme: str, model: type[C]) -> C | None:
        """Resolve the connection this instance configures a storage scheme from, or None."""
        ref = self._storage_connections.get(scheme)
        return None if ref is None else self.connection(ref, model)

    def schema(self, code: str) -> JsonMap:
        """Resolve a named JSON Schema by code, as the claim transaction snapshotted it."""
        body = self._schemas.get(code)
        if body is None:
            raise UnknownSchema(code, list(self._schemas))
        return body

    def format_checker(self) -> FormatChecker:
        """The instance's assembled checker: base formats plus every contributed one."""
        return self._format_checker

    def http(self, ref: ConnectionRef) -> httpx2.AsyncClient:
        """Build an HTTP client for a connection read by code, already carrying its settings."""
        record = self._connections.get(ref)
        if record is None:
            raise UnknownConnection(ref, list(self._connections))
        model = self._connection_models.get(record.kind)
        if model is None:
            raise BlockFailure(
                f"connection {ref!r} has kind {record.kind!r}, which no installed plugin contributes",
                error_class=ErrorClass.REJECTED,
            )
        return build_http_client(self.connection(ref, model))


def build_http_client(config: BaseModel) -> httpx2.AsyncClient:
    """Build a client from any connection config that names the standard HTTP fields.

    The fields are read structurally, so a config that names none of them gets a bare client.

    A credential is read from one of two fields. ``bearer_token`` is sent as
    ``Authorization: Bearer``; ``api_token`` is sent under the scheme the config's
    ``api_token_scheme`` names, and ``ApiToken`` when it names none, because that is what a
    DHIS2 personal access token needs. ``bearer_token`` wins if a config carries both.
    ``basic_username`` and ``basic_password`` become the client's auth, which httpx applies
    per request, so basic credentials beside a token win over the header.
    """
    base_url = _text(config, BASE_URL_FIELD) or ""
    configured = getattr(config, TIMEOUT_FIELD, None)
    timeout = configured.total_seconds() if isinstance(configured, timedelta) else DEFAULT_HTTP_TIMEOUT
    verify = getattr(config, VERIFY_TLS_FIELD, True)
    headers: dict[str, str] = {}
    bearer = _text(config, BEARER_FIELD)
    api_token = _text(config, API_TOKEN_FIELD)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    elif api_token:
        scheme = _text(config, API_TOKEN_SCHEME_FIELD) or DEFAULT_API_TOKEN_SCHEME
        headers["Authorization"] = f"{scheme} {api_token}"
    auth: httpx2.Auth | None = None
    user = _text(config, BASIC_USER_FIELD)
    password = _text(config, BASIC_PASSWORD_FIELD)
    if user:
        auth = httpx2.BasicAuth(user, password or "")
    return httpx2.AsyncClient(
        base_url=base_url,
        headers=headers,
        auth=auth,
        verify=bool(verify),
        timeout=timeout,
    )


def _text(config: BaseModel, name: str) -> str | None:
    """Read a field that may be a plain string, a secret, or absent."""
    value: Any = getattr(config, name, None)
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)
