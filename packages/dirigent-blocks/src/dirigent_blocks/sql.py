"""``sql.query`` and ``sql.execute``: read from and write to a database over a ``sql`` connection.

Reading a table and writing a table are the two most common things a pipeline does, and until
these blocks the answer was ``shell.run`` with ``psql`` -- an unsafe block, a credential on a
command line, and a result that arrives as text somebody has to parse.

Both blocks are **ordinary**. They run no command a document supplies and reach nothing but the
database their connection names, which is a narrower grant than ``shell.run``.

Nothing a document writes ever reaches the SQL text. A statement is a constant in the document
and every value is a named bind parameter, so ``${...}`` resolves into ``params`` and a value
that looks like SQL stays a value.

The engine is whatever the connection's URL names. PostgreSQL and SQLite run over an async
driver; DuckDB has none and runs in a worker thread, where it also reads the parquet and csv
files a statement names by binding their storage URIs as parameters.
"""

import asyncio
import json
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

import sqlalchemy
import sqlalchemy.exc
from pydantic import BaseModel, Field, SecretStr, model_validator
from sqlalchemy.engine import URL, Connection, Engine, create_engine, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import TextClause

from dirigent_blocks import subprocess
from dirigent_common import BlockModel, Duration, HealthReport, JsonList, JsonMap, StorageUri, spelled
from dirigent_plugin import (
    BlockFailure,
    ConnectionKind,
    ConnectionRef,
    ErrorClass,
    Operator,
    OperatorSpec,
    RemoteHandle,
    StepContext,
)

#: How many rows are read out of the cursor at a time, inline or on the way to storage.
BATCH = 1000

#: How long a connection check may spend reaching the database and asking it for a one.
CHECK_TIMEOUT_SECONDS = 30.0

#: The backend a URL names when the engine is DuckDB, which has no async driver and is run
#: in a worker thread instead.
DUCKDB: Final = "duckdb"

#: The storage schemes duckdb opens itself, given credentials, rather than through a path.
#: ``s3://`` is the one this configures; the others have no equivalent here yet.
REMOTE_STORAGE: Final = frozenset({"gs", "azure"})

#: What to do about a bucket URI duckdb has no reach to.
REMOTE_REMEDY: Final = "copy it into the run's scratch space with storage.copy first"

#: The scheme duckdb reads and writes through its httpfs extension.
S3: Final = "s3"

#: The extension that gives duckdb ``s3://``. It is loaded, never installed, at run time: a
#: step must not fetch a binary from the internet mid-run, so the image installs it at build
#: time and a bare install does it once by hand.
HTTPFS: Final = "httpfs"

#: The dialects whose sessions can be made read-only, and how each one is told.
READ_ONLY: Final = {
    "postgresql": "SET TRANSACTION READ ONLY",
    "sqlite": "PRAGMA query_only = 1",
}

#: The dialects that can be given a per-statement deadline the server itself enforces.
STATEMENT_TIMEOUT: Final = {"postgresql": "SET LOCAL statement_timeout = {milliseconds}"}

#: The distribution that provides each async driver a URL can name, for the install line an
#: absent one is refused with.
DRIVER_PACKAGE: Final = {
    "aiosqlite": "aiosqlite",
    "asyncpg": "asyncpg",
    "psycopg": "psycopg[binary]",
    "aiomysql": "aiomysql",
    "asyncmy": "asyncmy",
    "aioodbc": "aioodbc",
    "aiooracle": "aiooracle",
    "oracledb": "oracledb",
}

#: What a driver says when the database could not be reached, rather than refusing the request.
UNREACHABLE: Final = (
    "connection refused",
    "could not connect",
    "could not translate host name",
    "name or service not known",
    "connection reset",
    "server closed the connection",
    "timeout expired",
    "too many clients",
    "the database system is starting up",
    "database is locked",
)


class SqlConnectionConfig(BlockModel):
    """One database, the sealed password that opens it, and whether it may be written to."""

    url: str = Field(min_length=1)
    """The database as a SQLAlchemy URL, driver included:
    ``postgresql+asyncpg://user@host:5432/db`` or ``sqlite+aiosqlite:///data.db``.

    ``duckdb:///warehouse.duckdb`` and ``duckdb:///:memory:`` name the DuckDB engine, which has
    no async driver and writes none in the URL.

    A URL carrying a password inline is refused: the secret belongs in ``password``, where it
    is encrypted at rest and redacted in every API response, and a plain field is neither.

    A sqlite or duckdb database written as a relative path is relative to the run's work
    directory, which is where a database a pipeline builds for itself belongs. It is local to
    the worker that made it, so a later step reading it must be on the same worker."""

    password: SecretStr | None = None
    """The password, sealed, merged into the URL when a connection is opened and nowhere else."""

    read_only: bool = False
    """Refuse to write through this connection.

    Every session it opens is put in the dialect's own read-only mode -- for duckdb, the file
    itself is opened read-only -- so a statement that writes is refused by the database rather
    than by a check here, and ``sql.execute`` refuses the connection outright. A dialect with
    no read-only mode is refused rather than silently left writable."""

    connect_timeout: Duration = timedelta(seconds=10)
    """How long opening a connection may take before the step fails as a transient error."""

    @model_validator(mode="after")
    def _check_shape(self) -> "SqlConnectionConfig":
        """Refuse a URL that is unparseable, synchronous, or carrying its own password."""
        url = _parse(self.url)
        if url.password is not None:
            raise ValueError(
                "this url carries a password inline, where it would sit unencrypted in a plain "
                "field; take it out of the url and set the sealed password field instead"
            )
        backend = url.get_backend_name()
        if backend != DUCKDB and "+" not in url.drivername:
            raise ValueError(
                f"{url.drivername!r} names no driver, and these blocks speak to a database over an "
                f"async one; write the driver in the url, as in "
                f"{url.drivername}+asyncpg:// or {url.drivername}+aiosqlite://"
            )
        if self.read_only and backend not in READ_ONLY and backend != DUCKDB:
            supported = ", ".join([*sorted(READ_ONLY), DUCKDB])
            raise ValueError(
                f"read_only has no meaning on {backend}: only {supported} can be told to "
                f"refuse writes for the length of a session, and a connection that cannot be "
                f"is not marked as one that is"
            )
        if self.read_only and _is_memory(url):
            raise ValueError(
                "read_only has no meaning on duckdb:///:memory:, which duckdb refuses to open at all: "
                "an in-memory database starts empty and a read-only one can never be filled, so the "
                "connection would open on nothing; name a duckdb file, or drop read_only"
            )
        return self


class SqlConnectionKind(ConnectionKind):
    """The connection kind the ``sql.*`` blocks resolve their database through."""

    id: ClassVar[str] = "sql"
    config_model: ClassVar[type[BaseModel]] = SqlConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Open a connection and ask for a one, which is the smallest proof of reach and credential."""
        settings = SqlConnectionConfig.model_validate(config.model_dump())
        url = _with_password(settings)
        if _is_run_relative(url):
            return HealthReport(
                healthy=False,
                detail="a scratch-relative database file exists only inside a run, so there is nothing here to check",
            )
        if url.get_backend_name() == DUCKDB:
            return await _duck_check(settings, url)
        try:
            engine = _engine(settings, url)
        except BlockFailure as error:
            return HealthReport(healthy=False, detail=str(error))
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as connection:
                await connection.execute(sqlalchemy.text("SELECT 1"))
        except (TimeoutError, sqlalchemy.exc.SQLAlchemyError, OSError) as error:
            return HealthReport(healthy=False, detail=_reason(error))
        finally:
            await engine.dispose()
        return HealthReport(healthy=True, detail=f"{url.get_backend_name()} answered")


class SqlQueryConfig(BlockModel):
    """One statement, the values bound into it, and where its rows go."""

    connection: ConnectionRef
    """The ``sql`` connection naming the database and holding its password."""

    sql: str = Field(min_length=1)
    """One statement, and one only. A document that needs two writes two steps, or uses
    ``sql.execute``, which is the block that runs several as one transaction."""

    params: JsonMap = Field(default_factory=dict[str, Any])
    """Values bound by name, written ``:name`` in the statement.

    This is where a ``${...}`` reference belongs. A parameter is sent to the database beside
    the statement and never spliced into it, so a value that reads as SQL is still a value.
    Nothing in ``sql`` is substituted, which also means a table or column name cannot come
    from a parameter: only a value can.

    On a duckdb connection a value that is a ``file://`` storage URI inside the run's own
    directories -- its work directory, and its scratch space where that is local -- arrives as
    the path duckdb opens, so ``read_parquet(:source)`` and ``COPY ... TO :target`` name a file
    the run wrote. A URI outside them is refused."""

    max_rows: int = Field(default=1000, ge=1)
    """How many rows may be carried inline in the step's output.

    A result past this fails the step rather than being truncated: half an answer is not a
    smaller answer, and a step acting on it would be acting on something the database never
    said. ``save_to`` streams instead, and is bounded by the storage rather than by this."""

    save_to: StorageUri | None = None
    """A storage URI the rows are streamed to as NDJSON, one JSON object per line.

    Given, the rows are never held whole, the output carries ``saved_to`` and ``row_count``
    instead of ``rows``, and ``max_rows`` does not apply."""

    timeout: Duration = timedelta(minutes=5)
    """How long the statement may run.

    Set as the database's own statement timeout where the dialect has one, and enforced here
    in every case, so a query that hangs ends the step rather than the deadline."""

    @model_validator(mode="after")
    def _check_shape(self) -> "SqlQueryConfig":
        """Refuse a config whose ``sql`` is more than the one statement this block runs."""
        _check_single(self.sql)
        return self


class SqlQueryOutput(BlockModel):
    """What one query returned, or where it was put."""

    rows: JsonList | None = None
    """The rows as objects keyed by column name, or null when they were saved instead."""

    row_count: int
    """How many rows the query returned, inline or saved."""

    columns: list[str]
    """The column names, in the order the query selected them."""

    saved_to: str | None = None
    """Where the NDJSON was written, when ``save_to`` asked for it."""

    duration_ms: int


class SqlQueryOperator(Operator[SqlQueryConfig, SqlQueryOutput]):
    """Runs one statement against a database and reports its rows."""

    spec = OperatorSpec(
        id="sql.query",
        summary="Run one SQL statement and return its rows.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = SqlQueryConfig
    output_model: ClassVar[type[BaseModel]] = SqlQueryOutput

    async def execute(self, config: SqlQueryConfig, ctx: StepContext) -> SqlQueryOutput | RemoteHandle:
        """Open a session, run the statement, and hand the rows on inline or through storage."""
        settings = ctx.connection(config.connection, SqlConnectionConfig)
        params = _bound(config.params, settings, ctx)
        started = time.monotonic()
        rows: JsonList | None = None
        async with _session(settings, ctx, s3=addresses_s3(params, [config.sql])) as connection:
            await _limit(connection, settings, config.timeout)
            # The deadline covers running the statement and reading the rows out of it, because
            # a query that hangs hangs in either.
            async with asyncio.timeout(config.timeout.total_seconds()):
                result = await connection.stream(sqlalchemy.text(config.sql), params)
                columns = list(result.keys())
                if config.save_to:
                    count = await _save(result, config.save_to, ctx)
                else:
                    rows = await _inline(result, config.max_rows)
                    count = len(rows)
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "query ran",
            connection=config.connection,
            row_count=count,
            saved_to=config.save_to,
            duration_ms=duration,
        )
        return SqlQueryOutput(
            rows=rows,
            row_count=count,
            columns=columns,
            saved_to=config.save_to,
            duration_ms=duration,
        )

    def classify_error(self, error: Exception) -> ErrorClass:
        """A database that could not be reached is transient; one that refused the statement is not."""
        return classify(error)


class SqlExecuteConfig(BlockModel):
    """The statements one transaction runs, and the values bound into all of them."""

    connection: ConnectionRef
    """The ``sql`` connection naming the database and holding its password. A connection
    marked ``read_only`` is refused: this block writes."""

    statements: list[str] = Field(min_length=1)
    """The statements, run in order inside one transaction. They all commit or none of them
    does, so a migration, an insert and the index it needs are one step and not three."""

    params: JsonMap = Field(default_factory=dict[str, Any])
    """Values bound by name, written ``:name``, and shared by every statement.

    A statement that names no parameter simply binds none of them. On a duckdb connection a
    ``file://`` storage URI inside the run's own directories arrives as the path duckdb opens."""

    timeout: Duration = timedelta(minutes=5)
    """How long the whole transaction may run.

    Set as the database's own statement timeout where the dialect has one, and enforced here
    in every case, so statements that hang end the step rather than the deadline."""

    @model_validator(mode="after")
    def _check_shape(self) -> "SqlExecuteConfig":
        """Refuse a list whose entries are empty or hold more than one statement each."""
        for index, statement in enumerate(self.statements):
            if not statement.strip():
                raise ValueError(f"statement {index} is empty")
            _check_single(statement)
        return self


class SqlExecuteOutput(BlockModel):
    """What the transaction changed."""

    row_counts: list[int]
    """Rows affected by each statement, in order; ``-1`` where the driver does not say."""

    duration_ms: int


class SqlExecuteOperator(Operator[SqlExecuteConfig, SqlExecuteOutput]):
    """Runs several statements against a database as one transaction."""

    spec = OperatorSpec(
        id="sql.execute",
        summary="Run SQL statements against a database in one transaction.",
        idempotent=False,
    )
    config_model: ClassVar[type[BaseModel]] = SqlExecuteConfig
    output_model: ClassVar[type[BaseModel]] = SqlExecuteOutput

    async def execute(self, config: SqlExecuteConfig, ctx: StepContext) -> SqlExecuteOutput | RemoteHandle:
        """Run every statement in one transaction and report what each of them touched."""
        settings = ctx.connection(config.connection, SqlConnectionConfig)
        if settings.read_only:
            raise BlockFailure(
                f"connection {config.connection!r} is read_only, and sql.execute writes; "
                f"read it with sql.query, or point this step at a connection that may write",
                error_class=ErrorClass.REJECTED,
            )
        params = _bound(config.params, settings, ctx)
        started = time.monotonic()
        counts: list[int] = []
        s3 = addresses_s3(params, config.statements)
        async with _session(settings, ctx, s3=s3) as connection, connection.begin():
            await _limit(connection, settings, config.timeout)
            # The deadline covers every statement together, because the transaction is what
            # the step commits or loses.
            async with asyncio.timeout(config.timeout.total_seconds()):
                for statement in config.statements:
                    result = await connection.execute(sqlalchemy.text(statement), params)
                    counts.append(result.rowcount)
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "statements ran",
            connection=config.connection,
            statements=len(config.statements),
            row_counts=list(counts),
            duration_ms=duration,
        )
        return SqlExecuteOutput(row_counts=counts, duration_ms=duration)

    def classify_error(self, error: Exception) -> ErrorClass:
        """A database that could not be reached is transient; one that refused a statement is not."""
        return classify(error)


def _parse(url: str) -> URL:
    """Read a SQLAlchemy URL, saying what is wrong with one that is not."""
    try:
        return make_url(url)
    except sqlalchemy.exc.ArgumentError as error:
        raise ValueError(f"{url!r} is not a database url: {error}") from error


def _is_memory(url: URL) -> bool:
    """Whether this URL names a database that lives in the process and nowhere else."""
    return url.get_backend_name() == DUCKDB and (url.database or ":memory:") == ":memory:"


def _is_run_relative(url: URL) -> bool:
    """Whether this is a file database named by a path relative to the run's work directory."""
    database = url.database or ""
    if url.get_backend_name() not in {"sqlite", DUCKDB} or _is_memory(url):
        return False
    return bool(database) and not database.startswith("/")


def _with_password(settings: SqlConnectionConfig) -> URL:
    """The URL with the sealed password merged in, which is the only place the two meet."""
    url = _parse(settings.url)
    if settings.password is None:
        return url
    return url.set(password=settings.password.get_secret_value())


def _resolved(settings: SqlConnectionConfig, ctx: StepContext) -> URL:
    """The URL a step connects with: the password merged in, and a sqlite path made absolute."""
    url = _with_password(settings)
    if not _is_run_relative(url):
        return url
    database = subprocess.local_root(ctx) / str(url.database)
    database.parent.mkdir(parents=True, exist_ok=True)
    return url.set(database=str(database))


def _engine(settings: SqlConnectionConfig, url: URL) -> AsyncEngine:
    """Build the engine one step uses, naming the package to install when the driver is absent.

    ``NullPool`` because a step opens one connection and the worker process may run the next
    step against a different database entirely; a pool would outlive what it serves.
    """
    try:
        return create_async_engine(url, poolclass=NullPool)
    except (ModuleNotFoundError, sqlalchemy.exc.NoSuchModuleError) as error:
        driver = url.drivername.partition("+")[2]
        package = DRIVER_PACKAGE.get(driver, driver)
        raise BlockFailure(
            f"the {driver!r} driver this url names is not installed on the worker; add the {package!r} "
            f"package to the image, or use a driver that ships with it "
            f"({', '.join(['asyncpg', 'aiosqlite'])})",
            error_class=ErrorClass.REJECTED,
        ) from error


def _duck_engine(settings: SqlConnectionConfig, url: URL) -> Engine:
    """Build the synchronous duckdb engine, opening the file read-only where the connection says so.

    DuckDB has no async driver at all: neither its own Python API nor ``duckdb_engine`` speaks
    the DBAPI SQLAlchemy's asyncio layer needs, and that layer has no adapter for a synchronous
    one. The engine is therefore an ordinary synchronous engine, and every call on it is made
    from a worker thread.
    """
    try:
        return create_engine(
            url,
            poolclass=NullPool,
            connect_args={"read_only": True} if settings.read_only else {},
        )
    except (ModuleNotFoundError, sqlalchemy.exc.NoSuchModuleError) as error:
        raise BlockFailure(
            "duckdb is not installed on the worker, and this url names it; install "
            "dirigent-blocks[duckdb], which carries the engine and its SQLAlchemy dialect",
            error_class=ErrorClass.REJECTED,
        ) from error


async def _duck_check(settings: SqlConnectionConfig, url: URL) -> HealthReport:
    """Open the duckdb file in a thread and ask it for a one, which is what a step does too."""
    try:
        engine = _duck_engine(settings, url)
    except BlockFailure as error:
        return HealthReport(healthy=False, detail=str(error))

    def ask() -> None:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))

    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await asyncio.to_thread(ask)
    except (TimeoutError, sqlalchemy.exc.SQLAlchemyError, OSError) as error:
        return HealthReport(healthy=False, detail=_reason(error))
    finally:
        await asyncio.to_thread(engine.dispose)
    return HealthReport(healthy=True, detail="duckdb answered")


def _bound(params: JsonMap, settings: SqlConnectionConfig, ctx: StepContext) -> dict[str, Any]:
    """The parameters as the database receives them, storage URIs among them made local paths.

    DuckDB reads and writes files the statement names -- ``read_parquet(:source)``,
    ``COPY ... TO :target`` -- and a document names a file by its storage URI. Only a duckdb
    connection has anything to open, so only its parameters are resolved.
    """
    values = dict(params)
    if _parse(settings.url).get_backend_name() != DUCKDB:
        return values
    return {
        name: _file(name, value, ctx) if isinstance(value, str) and "://" in value else value
        for name, value in values.items()
    }


def _file(name: str, uri: str, ctx: StepContext) -> str:
    """One storage URI as duckdb receives it: a local path, or a bucket URI it opens itself."""
    split = urlsplit(uri)
    if split.scheme in REMOTE_STORAGE:
        raise BlockFailure(
            f"parameter {name!r} names {split.scheme}:// storage, and duckdb reads a file through the "
            f"worker's own filesystem here; {REMOTE_REMEDY}",
            error_class=ErrorClass.REJECTED,
        )
    # An s3:// URI is handed over whole: the session loads httpfs and gives duckdb the
    # scheme's own credentials, so duckdb opens the object rather than a path.
    if split.scheme == S3:
        return uri
    if split.scheme != "file":
        return uri
    roots = _readable(ctx)
    path = Path(f"{split.netloc}{split.path}").absolute()
    if not any(path.is_relative_to(root) for root in roots):
        named = ", ".join(str(root) for root in roots)
        raise BlockFailure(
            f"parameter {name!r} names {uri}, which is outside this run's own directories ({named}); a "
            f"query reads and writes the files of the run it belongs to",
            error_class=ErrorClass.REJECTED,
        )
    # A ``COPY ... TO`` names a file duckdb creates but not a directory it creates.
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _readable(ctx: StepContext) -> list[Path]:
    """The directories a duckdb parameter may name a file inside.

    The run's work directory always, and its scratch space as well where the artifact root is
    a local one -- which is where a ``file://`` artifact a previous step wrote actually is.
    """
    roots = [subprocess.local_root(ctx)]
    split = urlsplit(ctx.scratch)
    if split.scheme == "file":
        roots.append(Path(f"{split.netloc}{split.path}").absolute())
    return roots


class S3StorageSettings(BlockModel):
    """What the ``s3`` storage connection carries, as duckdb needs to be told it.

    The field names are the ``s3`` connection kind's own, so the row the instance already
    holds for ``storage_connections`` validates against this without a second connection.
    """

    endpoint_url: str | None = None
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: SecretStr | None = None
    path_style: bool = False
    verify_tls: bool = True
    bucket: str | None = None


def addresses_s3(values: dict[str, Any], statements: Sequence[str]) -> bool:
    """Whether anything this step runs names an ``s3://`` object, in a value or in the sql."""
    prefix = f"{S3}://"
    if any(isinstance(value, str) and value.startswith(prefix) for value in values.values()):
        return True
    return any(prefix in statement for statement in statements)


def s3_options(config: S3StorageSettings) -> list[tuple[str, str | bool]]:
    """The duckdb settings that point httpfs at one endpoint with one credential.

    duckdb takes the endpoint as host and port with no scheme, and asks separately whether to
    speak TLS to it, so one ``endpoint_url`` becomes two settings.
    """
    options: list[tuple[str, str | bool]] = [("s3_region", config.region)]
    if config.endpoint_url:
        split = urlsplit(config.endpoint_url)
        options.append(("s3_endpoint", split.netloc or split.path))
        options.append(("s3_use_ssl", split.scheme == "https"))
    else:
        options.append(("s3_use_ssl", config.verify_tls))
    if config.access_key_id:
        options.append(("s3_access_key_id", config.access_key_id))
    if config.secret_access_key is not None:
        options.append(("s3_secret_access_key", config.secret_access_key.get_secret_value()))
    options.append(("s3_url_style", "path" if config.path_style else "vhost"))
    return options


def _session(settings: SqlConnectionConfig, ctx: StepContext, *, s3: bool = False) -> "_Session | _DuckSession":
    """The session this connection's engine is driven through."""
    if _parse(settings.url).get_backend_name() == DUCKDB:
        return _DuckSession(settings, ctx, s3=s3)
    return _Session(settings, ctx)


class _Session:
    """One connection, opened under the connection's timeout and read-only where it says so."""

    def __init__(self, settings: SqlConnectionConfig, ctx: StepContext) -> None:
        """Hold what opening this step's connection needs."""
        self.settings = settings
        self.url = _resolved(settings, ctx)
        self.engine = _engine(settings, self.url)
        self.connection: AsyncConnection | None = None

    async def __aenter__(self) -> AsyncConnection:
        """Open the connection and put it in the mode the connection kind asked for."""
        try:
            async with asyncio.timeout(self.settings.connect_timeout.total_seconds()):
                self.connection = await self.engine.connect()
        except TimeoutError as error:
            await self.engine.dispose()
            raise BlockFailure(
                f"the database did not answer within {self.settings.connect_timeout}",
                error_class=ErrorClass.TRANSIENT,
            ) from error
        except BaseException:
            await self.engine.dispose()
            raise
        if self.settings.read_only:
            await self.connection.execute(sqlalchemy.text(READ_ONLY[self.url.get_backend_name()]))
        return self.connection

    async def __aexit__(self, *_error: object) -> None:
        """Close the connection and the engine behind it, however the step left."""
        if self.connection is not None:
            await self.connection.close()
        await self.engine.dispose()


def _open_s3(connection: Connection, ctx: StepContext) -> None:
    """Give this duckdb connection the ``s3`` scheme, on the instance's own credentials.

    Run in the thread the connection belongs to, before any statement, so a ``read_parquet``
    of an ``s3://`` object opens it rather than looking for a path.
    """
    config = ctx.storage_connection(S3, S3StorageSettings)
    if config is None:
        raise BlockFailure(
            f"this statement names {S3}:// storage and no connection is bound to the {S3} scheme, so "
            f"duckdb has no endpoint or credential to open it with; set DIRIGENT_STORAGE_CONNECTIONS",
            error_class=ErrorClass.REJECTED,
        )
    try:
        connection.execute(sqlalchemy.text(f"LOAD {HTTPFS}"))
    except sqlalchemy.exc.DatabaseError as error:
        raise BlockFailure(
            f"duckdb could not load its {HTTPFS} extension, which is what reads {S3}:// here; install "
            f"it once on this worker with duckdb -c 'INSTALL {HTTPFS}'",
            error_class=ErrorClass.REJECTED,
        ) from error
    for name, value in s3_options(config):
        # The value is bound, never spliced: a secret must not become part of a statement.
        connection.execute(sqlalchemy.text(f"SET {name} = :value"), {"value": value})
    # These statements autobegin a transaction, and the step opens its own straight after.
    # They configure the session rather than touching data, so ending this one keeps them.
    connection.commit()


class _DuckSession:
    """One duckdb connection, opened in a worker thread and closed there too."""

    def __init__(self, settings: SqlConnectionConfig, ctx: StepContext, *, s3: bool = False) -> None:
        """Hold what opening this step's duckdb file needs."""
        self.settings = settings
        self.ctx = ctx
        self.s3 = s3
        self.url = _resolved(settings, ctx)
        self.engine = _duck_engine(settings, self.url)
        self.connection: _Threaded | None = None

    async def __aenter__(self) -> "_Threaded":
        """Open the file, read-only where the connection said so, which duckdb enforces itself."""
        try:
            async with asyncio.timeout(self.settings.connect_timeout.total_seconds()):
                opened = await asyncio.to_thread(self.engine.connect)
        except TimeoutError as error:
            await asyncio.to_thread(self.engine.dispose)
            raise BlockFailure(
                f"the database did not answer within {self.settings.connect_timeout}",
                error_class=ErrorClass.TRANSIENT,
            ) from error
        except BaseException:
            await asyncio.to_thread(self.engine.dispose)
            raise
        try:
            if self.s3:
                await asyncio.to_thread(_open_s3, opened, self.ctx)
        except BaseException:
            await asyncio.to_thread(opened.close)
            await asyncio.to_thread(self.engine.dispose)
            raise
        self.connection = _Threaded(opened)
        return self.connection

    async def __aexit__(self, *_error: object) -> None:
        """Close the connection and the engine behind it, however the step left."""
        if self.connection is not None:
            await self.connection.close()
        await asyncio.to_thread(self.engine.dispose)


class _Threaded:
    """A synchronous connection driven from the event loop, one call in one thread at a time.

    A deadline that passes cancels the wait but not the thread, so a call cancelled here
    interrupts duckdb, which is what ends the statement rather than leaving it running behind
    a step that has already failed.
    """

    def __init__(self, connection: Connection) -> None:
        """Hold the connection and the driver handle an interrupt is sent through."""
        self.connection = connection
        self.raw: Any = connection.connection.driver_connection

    async def execute(self, statement: TextClause, params: dict[str, Any]) -> Any:
        """Run one statement and hand back its result, rowcount included."""
        return await self._call(lambda: self.connection.execute(statement, params))

    async def stream(self, statement: TextClause, params: dict[str, Any]) -> "_ThreadedRows":
        """Run one statement and hand back a cursor read a batch at a time."""
        cursor = self.connection.execution_options(stream_results=True)
        result = await self._call(lambda: cursor.execute(statement, params))
        return _ThreadedRows(result, self._call)

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[None]:
        """One transaction, committed when the block leaves cleanly and rolled back otherwise."""
        transaction = await self._call(self.connection.begin)
        try:
            yield
        except BaseException:
            await asyncio.to_thread(transaction.rollback)
            raise
        await asyncio.to_thread(transaction.commit)

    async def close(self) -> None:
        """Close the connection in a thread, as everything else on it is done."""
        await asyncio.to_thread(self.connection.close)

    async def _call[T](self, work: Callable[[], T]) -> T:
        """Run one blocking call in a thread, interrupting duckdb when the wait is cancelled."""
        try:
            return await asyncio.to_thread(work)
        except asyncio.CancelledError:
            self.raw.interrupt()
            raise


class _ThreadedRows:
    """The rows of one synchronous result, fetched a batch at a time in a worker thread."""

    def __init__(self, result: Any, call: Callable[[Callable[[], Any]], Any]) -> None:
        """Hold the cursor and the thread call every fetch goes through."""
        self.result = result
        self.call = call

    def keys(self) -> list[str]:
        """The column names, in the order the statement selected them."""
        return list(self.result.keys())

    async def partitions(self, size: int) -> AsyncIterator[Sequence[Any]]:
        """Read the cursor a batch at a time, the way the async result does."""
        while True:
            batch = await self.call(lambda: self.result.fetchmany(size))
            if not batch:
                return
            yield batch


async def _limit(connection: Any, settings: SqlConnectionConfig, timeout: timedelta) -> None:
    """Ask the database to enforce the statement deadline itself, where the dialect has one."""
    template = STATEMENT_TIMEOUT.get(_parse(settings.url).get_backend_name())
    if template is None:
        return
    await connection.execute(sqlalchemy.text(template.format(milliseconds=round(timeout.total_seconds() * 1000))))


async def _inline(result: Any, max_rows: int) -> JsonList:
    """Read the rows into the output, refusing a result the step said it would not hold."""
    rows: JsonList = []
    async for batch in _batches(result):
        rows.extend(spelled_row(one) for one in batch)
        if len(rows) > max_rows:
            raise BlockFailure(
                f"the query returned more than max_rows ({max_rows}) rows and is not being saved; "
                f"raise max_rows, narrow the query, or give save_to a URI to stream it to",
                error_class=ErrorClass.REJECTED,
            )
    return rows


async def _save(result: Any, uri: str, ctx: StepContext) -> int:
    """Stream the rows to storage as NDJSON and say how many there were.

    A batch at a time, so a result larger than the worker's memory is a file rather than a
    dead worker.
    """
    count = 0
    async with ctx.storage.open_write(uri) as sink:
        async for batch in _batches(result):
            payload = "".join(f"{json.dumps(spelled_row(one), separators=(',', ':'))}\n" for one in batch)
            await sink.write(payload.encode())
            count += len(batch)
    ctx.log.info("rows saved", uri=uri, row_count=count)
    return count


async def _batches(result: Any) -> AsyncIterator[Sequence[Any]]:
    """Read the cursor a batch at a time, whatever the driver's own chunking is."""
    async for partition in result.partitions(BATCH):
        yield partition


def spelled_row(row: Any) -> JsonMap:
    """One row as an object keyed by column name, every value in its JSON spelling."""
    mapping: dict[str, Any] = dict(row._mapping)
    try:
        return {name: spelled(value) for name, value in mapping.items()}
    except ValueError as error:
        raise BlockFailure(
            f"a column of this result has no JSON spelling: {error}", error_class=ErrorClass.REJECTED
        ) from error


def _check_single(statement: str) -> None:
    """Refuse text holding more than one statement.

    A ``;`` outside a string literal, an identifier, a comment or a dollar-quoted body ends a
    statement, so anything but whitespace and comments after one means there are two. Two
    statements in one field would run outside ``sql.execute``'s transaction, and a document
    that means to run two says so by listing two.
    """
    rest = _after_first_terminator(statement)
    if rest is not None and _stripped(rest):
        raise ValueError(
            "this is more than one statement: a ';' ends the first and there is more after it. "
            "sql.query runs one statement, and sql.execute takes a list, one statement per entry"
        )


def _after_first_terminator(statement: str) -> str | None:
    """The text following the first statement-ending ``;``, or None when there is none."""
    index = 0
    length = len(statement)
    while index < length:
        character = statement[index]
        if character == ";":
            return statement[index + 1 :]
        skipped = _skip(statement, index)
        index = skipped if skipped > index else index + 1
    return None


def _skip(statement: str, index: int) -> int:
    """The index just past whatever quoted or commented run starts here, or ``index`` if none does."""
    character = statement[index]
    if statement.startswith("--", index):
        end = statement.find("\n", index)
        return _length_or(statement, end + 1 if end != -1 else -1)
    if statement.startswith("/*", index):
        end = statement.find("*/", index + 2)
        return _length_or(statement, end + 2 if end != -1 else -1)
    if character in "'\"`":
        return _skip_quoted(statement, index, character)
    if character == "$":
        return _skip_dollar(statement, index)
    return index


def _skip_quoted(statement: str, index: int, quote: str) -> int:
    """Past a quoted run, in which the quote character is doubled to mean itself."""
    cursor = index + 1
    while cursor < len(statement):
        if statement[cursor] == quote:
            if statement.startswith(quote * 2, cursor):
                cursor += 2
                continue
            return cursor + 1
        cursor += 1
    return len(statement)


def _skip_dollar(statement: str, index: int) -> int:
    """Past a ``$tag$ ... $tag$`` body, which is how PostgreSQL writes a function containing ``;``."""
    close = statement.find("$", index + 1)
    if close == -1:
        return index
    tag = statement[index : close + 1]
    if not tag[1:-1].replace("_", "").isalnum() and tag != "$$":
        return index
    end = statement.find(tag, close + 1)
    return _length_or(statement, end + len(tag) if end != -1 else -1)


def _length_or(statement: str, end: int) -> int:
    """An index into the statement, or its end when the run was never closed."""
    return len(statement) if end == -1 else end


def _stripped(text: str) -> str:
    """The text with whitespace and trailing comments removed, so a comment is not a statement."""
    rest = text
    while True:
        rest = rest.strip()
        if rest.startswith("--"):
            _, _, rest = rest.partition("\n")
            continue
        if rest.startswith("/*"):
            _, _, rest = rest.partition("*/")
            continue
        return rest


def classify(error: Exception) -> ErrorClass:
    """A database that could not be reached is transient; one that refused the request is not."""
    if isinstance(error, TimeoutError | sqlalchemy.exc.TimeoutError | sqlalchemy.exc.DisconnectionError):
        return ErrorClass.TRANSIENT
    if isinstance(error, sqlalchemy.exc.DBAPIError):
        if error.connection_invalidated or any(marker in str(error).lower() for marker in UNREACHABLE):
            return ErrorClass.TRANSIENT
        return ErrorClass.REJECTED
    if isinstance(error, sqlalchemy.exc.SQLAlchemyError):
        return ErrorClass.REJECTED
    if isinstance(error, OSError):
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN


def _reason(error: Exception) -> str:
    """The one sentence a health report gives for a database that did not answer."""
    if isinstance(error, TimeoutError):
        return f"no answer within {CHECK_TIMEOUT_SECONDS:.0f}s"
    text = str(getattr(error, "orig", None) or error).strip().splitlines()
    return text[0] if text else type(error).__name__
