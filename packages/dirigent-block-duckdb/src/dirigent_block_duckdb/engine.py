"""The DuckDB engine of the ``sql`` family: the backend whose tables can be files.

DuckDB has no async driver at all: neither its own Python API nor ``duckdb_engine`` speaks the
DBAPI SQLAlchemy's asyncio layer needs, and that layer has no adapter for a synchronous one. So
every call is made from a worker thread, and a deadline that passes interrupts the engine rather
than leaving a statement running behind a step that has already failed.

A statement here reads and writes the parquet and csv files a run holds, by binding their
storage URIs as parameters. The session is held to the run's own directories by duckdb's own
configuration -- ``allowed_directories``, then ``enable_external_access`` off and
``lock_configuration`` on -- so a path written into the SQL reaches no further than a bound one
does. Where a step names an ``s3://`` object, the session is given the ``httpfs`` extension and
the credentials of the connection the ``s3`` scheme is configured from, and that scheme stays
reachable beside the run's directories.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

import duckdb
import sqlalchemy
import sqlalchemy.exc
from pydantic import SecretStr
from sqlalchemy.engine import URL, Connection, Engine, create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import TextClause

from dirigent_block_duckdb.messages import (
    CONNECT_TIMED_OUT,
    NO_HTTPFS,
    NO_STORAGE_CONNECTION,
    PARAMETER_NAMES_STORAGE,
    PARAMETER_OUTSIDE_THE_RUN,
    READ_ONLY_IN_MEMORY,
    READ_ONLY_RUNS_SELECT,
    READ_ONLY_UNPARSED,
    STATEMENT_LOADS_AN_EXTENSION,
    STATEMENT_OUTSIDE_THE_RUN,
)
from dirigent_block_sql.engines import (
    CHECK_TIMEOUT_SECONDS,
    OUTSIDE_A_RUN,
    SqlEngine,
    SqlSession,
    reason,
    under_work,
)
from dirigent_block_sql.sql import SqlConnectionConfig
from dirigent_common import BlockModel, HealthReport, JsonMap
from dirigent_plugin import BlockFailure, ErrorClass, StepContext

#: The storage schemes a parameter naming one is refused for: duckdb would open them itself,
#: and no backend here holds the credentials to give it. ``s3://`` is the one that is wired up.
REMOTE_STORAGE: Final = frozenset({"gs", "azure"})

#: How long a cancelled call is given to return once duckdb is interrupted, before it is left behind.
INTERRUPT_GRACE_SECONDS: Final = 5.0

#: The scheme duckdb reads and writes through its httpfs extension.
S3: Final = "s3"

#: The I/O threads each database a step opens may start; duckdb's own default scales with the
#: host, and every step and every check opens a database of its own.
ASYNC_THREADS: Final = 8

#: The name of the connection's own secret for ``s3://``.
S3_SECRET: Final = "dirigent_s3"

#: The extension that gives duckdb ``s3://``. It is loaded, never installed, at run time: a
#: step must not fetch a binary from the internet mid-run, so the image installs it at build
#: time and a bare install does it once by hand.
HTTPFS: Final = "httpfs"

#: Where a contained session spills a query too large for memory, under the run's work
#: directory. duckdb's own default is beside the database file or in the worker's cwd, and
#: neither is inside the roots the session is held to.
TEMP_DIR: Final = ".duckdb-temp"

#: Where a contained session looks for duckdb secrets, under the run's work directory. The
#: default is the worker's home, which the session may not read, and httpfs reads the secret
#: store on every remote open.
SECRET_DIR: Final = ".duckdb-secrets"

#: What duckdb says when the containment refused the path a statement named.
DENIED_PATH: Final = "file system operations are disabled"

#: What duckdb says when a statement tried to load an extension the session was not opened with.
DENIED_EXTENSION: Final = "loading external extensions is disabled"


class DuckdbEngine(SqlEngine):
    """DuckDB: a worker thread where another engine has an async driver, and files where it has tables."""

    backend: ClassVar[str] = "duckdb"

    def validate(self, settings: SqlConnectionConfig, url: URL) -> None:
        """Refuse ``read_only`` on an in-memory database, which duckdb will not open at all."""
        if settings.read_only and _is_memory(url):
            raise ValueError(READ_ONLY_IN_MEMORY.render())

    def resolve(self, url: URL, ctx: StepContext) -> URL:
        """A duckdb database written as a relative path is a file in the run's work directory."""
        return under_work(url, ctx) if _is_run_relative(url) else url

    def bind(self, params: JsonMap, ctx: StepContext) -> dict[str, Any]:
        """The parameters as duckdb receives them, storage URIs among them made local paths.

        DuckDB reads and writes the files a statement names -- ``read_parquet(:source)``,
        ``COPY ... TO :target`` -- and a document names a file by its storage URI.
        """
        return {
            name: _file(name, value, ctx) if isinstance(value, str) and "://" in value else value
            for name, value in params.items()
        }

    async def check(self, settings: SqlConnectionConfig, url: URL) -> HealthReport:
        """Open the duckdb file in a thread and ask it for a one, which is what a step does too."""
        if _is_run_relative(url):
            return HealthReport(healthy=False, detail=OUTSIDE_A_RUN)
        engine = _engine(settings, url)

        def ask() -> None:
            with engine.connect() as connection:
                connection.execute(sqlalchemy.text("SELECT 1"))

        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                await asyncio.to_thread(ask)
        except (TimeoutError, sqlalchemy.exc.SQLAlchemyError, OSError) as error:
            return HealthReport(healthy=False, detail=reason(error))
        finally:
            await asyncio.to_thread(engine.dispose)
        return HealthReport(healthy=True, detail="duckdb answered")

    def session(
        self,
        settings: SqlConnectionConfig,
        url: URL,
        ctx: StepContext,
        *,
        statements: Sequence[str],
        params: JsonMap,
    ) -> AbstractAsyncContextManager[SqlSession]:
        """One duckdb session, given the ``s3`` scheme where anything this step runs names a bucket."""
        return _Session(settings, url, ctx, s3=addresses_s3(params, statements))


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


def s3_secret(config: S3StorageSettings) -> dict[str, str | bool]:
    """The parameters of the duckdb secret that points httpfs at one endpoint with one credential.

    duckdb takes the endpoint as host and port with no scheme, and asks separately whether to
    speak TLS to it, so one ``endpoint_url`` becomes two parameters.
    """
    secret: dict[str, str | bool] = {"REGION": config.region}
    if config.endpoint_url:
        split = urlsplit(config.endpoint_url)
        secret["ENDPOINT"] = split.netloc or split.path
        secret["USE_SSL"] = split.scheme == "https"
    else:
        secret["USE_SSL"] = config.verify_tls
    if config.access_key_id:
        secret["KEY_ID"] = config.access_key_id
    if config.secret_access_key is not None:
        secret["SECRET"] = config.secret_access_key.get_secret_value()
    secret["URL_STYLE"] = "path" if config.path_style else "vhost"
    return secret


def _is_memory(url: URL) -> bool:
    """Whether this URL names a database that lives in the process and nowhere else."""
    return (url.database or ":memory:") == ":memory:"


def _is_run_relative(url: URL) -> bool:
    """Whether this is a duckdb file named by a path relative to the run's work directory."""
    database = url.database or ""
    if _is_memory(url):
        return False
    return bool(database) and not database.startswith("/")


def _engine(settings: SqlConnectionConfig, url: URL) -> Engine:
    """Build the synchronous duckdb engine, opening the file read-only where the connection says so."""
    config: dict[str, Any] = {"async_threads": ASYNC_THREADS}
    return create_engine(
        url,
        poolclass=NullPool,
        connect_args={"config": config, "read_only": True} if settings.read_only else {"config": config},
    )


def _file(name: str, uri: str, ctx: StepContext) -> str:
    """One storage URI as duckdb receives it: a local path, or a bucket URI it opens itself."""
    split = urlsplit(uri)
    if split.scheme in REMOTE_STORAGE:
        raise BlockFailure(
            PARAMETER_NAMES_STORAGE, error_class=ErrorClass.REJECTED, name=repr(name), scheme=split.scheme
        )
    # An s3:// URI is handed over whole: the session loads httpfs and gives duckdb the
    # scheme's own credentials, so duckdb opens the object rather than a path.
    if split.scheme == S3:
        return uri
    if split.scheme != "file":
        return uri
    roots = _readable(ctx)
    path = Path(os.path.normpath(Path(f"{split.netloc}{split.path}").absolute()))
    if not any(_inside(path, root) for root in roots):
        named = ", ".join(str(root) for root in roots)
        raise BlockFailure(
            PARAMETER_OUTSIDE_THE_RUN,
            error_class=ErrorClass.REJECTED,
            name=repr(name),
            uri=uri,
            named=named,
        )
    # A ``COPY ... TO`` names a file duckdb creates but not a directory it creates.
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _inside(path: Path, root: Path) -> bool:
    """Whether a path is under a root both as written and once every symlink is followed."""
    root = Path(os.path.normpath(root))
    return path.is_relative_to(root) and path.resolve().is_relative_to(root.resolve())


def _readable(ctx: StepContext) -> list[Path]:
    """The directories a duckdb parameter may name a file inside.

    The run's work directory always, and its scratch space as well where the artifact root is
    a local one -- which is where a ``file://`` artifact a previous step wrote actually is.
    """
    roots = [ctx.work]
    split = urlsplit(ctx.scratch)
    if split.scheme == "file":
        roots.append(Path(f"{split.netloc}{split.path}").absolute())
    return roots


def _open_s3(connection: Connection, ctx: StepContext) -> None:
    """Give this duckdb connection the ``s3`` scheme, on the instance's own credentials.

    Run in the thread the connection belongs to, before any statement, so a ``read_parquet``
    of an ``s3://`` object opens it rather than looking for a path.
    """
    config = ctx.storage_connection(S3, S3StorageSettings)
    if config is None:
        raise BlockFailure(NO_STORAGE_CONNECTION, error_class=ErrorClass.REJECTED, scheme=S3)
    try:
        connection.execute(sqlalchemy.text(f"LOAD {HTTPFS}"))
    except sqlalchemy.exc.DatabaseError as error:
        raise BlockFailure(NO_HTTPFS, error_class=ErrorClass.REJECTED, extension=HTTPFS, scheme=S3) from error
    # The store is placed before the secret exists; duckdb refuses to move it once it is in use.
    _set(connection, "secret_directory", str(ctx.work / SECRET_DIR))
    secret = s3_secret(config)
    fields = ", ".join(f"{name} :{name.lower()}" for name in secret)
    # Held by this connection alone and in memory only; the values are bound, never spliced.
    connection.execute(
        sqlalchemy.text(f"CREATE SECRET {S3_SECRET} IN connection (TYPE {S3}, {fields})"),
        {name.lower(): value for name, value in secret.items()},
    )
    # These statements autobegin a transaction, and the step opens its own straight after.
    # They configure the session rather than touching data, so ending this one keeps them.
    connection.commit()


def _set(connection: Connection, name: str, value: Any) -> None:
    """One duckdb setting, its value bound rather than spliced into the statement.

    A credential must not become part of a statement, and a path must not be able to end one.
    """
    connection.execute(sqlalchemy.text(f"SET {name} = :value"), {"value": value})


def _contain(connection: Connection, ctx: StepContext, url: URL, *, s3: bool) -> None:
    """Hold this duckdb connection to the run's own directories, whatever a statement names.

    Run in the thread the connection belongs to, after the credentials and before any statement
    the document supplies. The order is the whole mechanism: ``allowed_directories`` only bites
    once ``enable_external_access`` is off, external access cannot be turned back on while the
    database runs, and the lock refuses the ``SET`` that would widen the roots again. With
    external access off duckdb also refuses to load or install any further extension, so the
    scheme this session was opened with is the only one it has.
    """
    roots = [str(root) for root in _readable(ctx)]
    if s3:
        # The scheme duckdb was just given credentials for stays reachable; no other does.
        roots.append(f"{S3}://")
    _set(connection, "allowed_directories", roots)
    database = _database_path(url)
    if database is not None:
        # The file this connection names may sit anywhere, and duckdb writes a log beside it.
        _set(connection, "allowed_paths", [str(database), f"{database}.wal"])
    work = ctx.work
    _set(connection, "temp_directory", str(work / TEMP_DIR))
    if not s3:
        _set(connection, "secret_directory", str(work / SECRET_DIR))
    _set(connection, "enable_external_access", False)
    _set(connection, "lock_configuration", True)
    connection.commit()


def _database_path(url: URL) -> Path | None:
    """The file this duckdb url opens, or nothing where the database lives only in memory."""
    if _is_memory(url) or not url.database:
        return None
    return Path(url.database).absolute()


def _refusal(error: Exception, roots: list[Path]) -> BlockFailure | None:
    """What a statement duckdb's containment refused failed for, or nothing for any other error."""
    text = str(error).lower()
    if DENIED_PATH in text:
        named = ", ".join(str(root) for root in roots)
        return BlockFailure(STATEMENT_OUTSIDE_THE_RUN, error_class=ErrorClass.REJECTED, named=named)
    if DENIED_EXTENSION in text:
        return BlockFailure(STATEMENT_LOADS_AN_EXTENSION, error_class=ErrorClass.REJECTED)
    return None


class _Session:
    """One duckdb connection, opened in a worker thread and closed there too."""

    def __init__(self, settings: SqlConnectionConfig, url: URL, ctx: StepContext, *, s3: bool = False) -> None:
        """Hold what opening this step's duckdb file needs."""
        self.settings = settings
        self.ctx = ctx
        self.s3 = s3
        self.url = url
        self.engine = _engine(settings, url)
        self.connection: _Threaded | None = None

    async def __aenter__(self) -> "_Threaded":
        """Open the file, read-only where the connection said so, and hold the session to that."""
        try:
            async with asyncio.timeout(self.settings.connect_timeout.total_seconds()):
                opened = await asyncio.to_thread(self.engine.connect)
        except TimeoutError as error:
            await asyncio.to_thread(self.engine.dispose)
            raise BlockFailure(
                CONNECT_TIMED_OUT, error_class=ErrorClass.TRANSIENT, timeout=self.settings.connect_timeout
            ) from error
        except BaseException:
            await asyncio.to_thread(self.engine.dispose)
            raise
        try:
            if self.s3:
                await asyncio.to_thread(_open_s3, opened, self.ctx)
            await asyncio.to_thread(_contain, opened, self.ctx, self.url, s3=self.s3)
        except BaseException:
            await asyncio.to_thread(opened.close)
            await asyncio.to_thread(self.engine.dispose)
            raise
        self.connection = _Threaded(opened, _readable(self.ctx), read_only=self.settings.read_only)
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

    A read-only open covers the attached catalog and not file output, and ``COPY`` can name
    the open database's own path, so a read-only session runs nothing that does not parse as
    ``SELECT``. ``EXPLAIN`` is not one: ``EXPLAIN ANALYZE COPY`` runs the copy.
    """

    def __init__(self, connection: Connection, roots: list[Path], *, read_only: bool = False) -> None:
        """Hold the connection, the interrupt handle, the roots it is held to, and whether it only reads."""
        self.connection = connection
        self.raw: Any = connection.connection.driver_connection
        self.roots = roots
        self.read_only = read_only
        self.abandoned: asyncio.Future[Any] | None = None

    async def execute(self, statement: TextClause, parameters: dict[str, Any] | None = None, /) -> Any:
        """Run one statement and hand back its result, rowcount included."""

        def run() -> Any:
            self._hold_to_reads(statement)
            return self.connection.execute(statement, parameters)

        return await self._call(run)

    async def stream(self, statement: TextClause, parameters: dict[str, Any] | None = None, /) -> "_ThreadedRows":
        """Run one statement and hand back a cursor read a batch at a time."""
        cursor = self.connection.execution_options(stream_results=True)

        def run() -> Any:
            self._hold_to_reads(statement)
            return cursor.execute(statement, parameters)

        result = await self._call(run)
        return _ThreadedRows(result, self._call)

    def _hold_to_reads(self, statement: TextClause) -> None:
        """Refuse on a read-only session anything but SELECT, parsing the text duckdb would be handed."""
        if not self.read_only:
            return
        compiled = str(statement.compile(dialect=self.connection.dialect))
        try:
            parsed = self.raw.extract_statements(compiled)
        except duckdb.Error as error:
            raise BlockFailure(READ_ONLY_UNPARSED, error_class=ErrorClass.REJECTED, detail=str(error)) from error
        kinds = [one.type for one in parsed]
        if not kinds or any(kind is not duckdb.StatementType.SELECT for kind in kinds):
            named = ", ".join(sorted({kind.name for kind in kinds})) or "empty"
            raise BlockFailure(READ_ONLY_RUNS_SELECT, error_class=ErrorClass.REJECTED, kinds=named)

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[None]:
        """One transaction, committed when the block leaves cleanly and rolled back otherwise."""
        transaction = await self._call(self.connection.begin)
        try:
            yield
        except BaseException:
            if not self.busy:
                await asyncio.to_thread(transaction.rollback)
            raise
        await asyncio.to_thread(transaction.commit)

    @property
    def busy(self) -> bool:
        """Whether a call left behind is still running, which every other call would be refused for."""
        return self.abandoned is not None and not self.abandoned.done()

    async def close(self) -> None:
        """Close the connection in a thread, or once a call left behind has returned."""
        if not self.busy:
            await asyncio.to_thread(self.connection.close)
            return
        assert self.abandoned is not None
        loop = asyncio.get_running_loop()

        def close_after(call: asyncio.Future[Any]) -> None:
            call.exception()
            loop.run_in_executor(None, self.connection.close)

        self.abandoned.add_done_callback(close_after)

    async def _call[T](self, work: Callable[[], T]) -> T:
        """Run one blocking call in a thread, interrupting duckdb when the wait is cancelled.

        A cancelled wait holds on until the interrupted call has returned: the connection refuses
        any other call while one is still running, and the rollback that follows is one. A call
        that has not returned within the grace is left behind, and the connection closes after it.
        """
        pending = asyncio.ensure_future(asyncio.to_thread(work))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            self.raw.interrupt()
            await asyncio.wait({pending}, timeout=INTERRUPT_GRACE_SECONDS)
            if pending.done():
                pending.exception()
            else:
                self.abandoned = pending
            raise
        except sqlalchemy.exc.DatabaseError as error:
            refusal = _refusal(error, self.roots)
            if refusal is None:
                raise
            raise refusal from error


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
