"""``sql.query`` and ``sql.execute``: read from and write to a database over a ``sql`` connection.

Reading a table and writing a table are the two most common things a pipeline does, and until
these blocks the answer was ``shell.run`` with ``psql`` -- an unsafe block, a credential on a
command line, and a result that arrives as text somebody has to parse.

Both blocks are **ordinary**. They run no command a document supplies and reach nothing but the
database their connection names, which is a narrower grant than ``shell.run``.

Nothing a document writes ever reaches the SQL text. A statement is a constant in the document
and every value is a named bind parameter, so ``${...}`` resolves into ``params`` and a value
that looks like SQL stays a value.

The engine is whatever the connection's URL names: any dialect with an async driver is driven
from here, and a backend needing more than a driver is an installed package contributing a
:class:`~dirigent_block_sql.engines.SqlEngine`, which every decision that differs by backend is
asked of.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import Annotated, Any, ClassVar, Final

import sqlalchemy
import sqlalchemy.exc
from pydantic import BaseModel, Field, SecretStr, model_validator
from sqlalchemy.engine import URL, make_url

from dirigent_block_sql.engines import SqlSession, engine_for
from dirigent_block_sql.messages import NO_JSON_SPELLING, READ_ONLY_CONNECTION, TOO_MANY_ROWS
from dirigent_common import (
    SQL_MEDIA_TYPE,
    BlockModel,
    Duration,
    HealthReport,
    JsonList,
    JsonMap,
    spelled,
)
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

#: The dialects that can be given a per-statement deadline the server itself enforces.
STATEMENT_TIMEOUT: Final = {"postgresql": "SET LOCAL statement_timeout = {milliseconds}"}

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

    A backend carried by an engine package writes the driver differently or not at all, and
    that engine is what says so; a URL naming one that is not installed is refused with the
    package to install.

    A URL carrying a password inline is refused: the secret belongs in ``password``, where it
    is encrypted at rest and redacted in every API response, and a plain field is neither.

    A sqlite database written as a relative path is relative to the run's work directory,
    which is where a database a pipeline builds for itself belongs. It is local to the worker
    that made it, so a later step reading it must be on the same worker."""

    password: SecretStr | None = None
    """The password, sealed, merged into the URL when a connection is opened and nowhere else."""

    read_only: bool = False
    """Refuse to write through this connection.

    Every session it opens is put in the dialect's own read-only mode, so a statement that
    writes is refused by the database rather than by a check here, and ``sql.execute`` refuses
    the connection outright. A dialect with no read-only mode is refused rather than silently
    left writable."""

    connect_timeout: Duration = timedelta(seconds=10)
    """How long opening a connection may take before the step fails as a transient error."""

    @model_validator(mode="after")
    def _check_shape(self) -> "SqlConnectionConfig":
        """Refuse a URL that is unparseable, carrying its own password, or one no engine opens."""
        url = _parse(self.url)
        if url.password is not None:
            raise ValueError(
                "this url carries a password inline, where it would sit unencrypted in a plain "
                "field; take it out of the url and set the sealed password field instead"
            )
        engine_for(url).validate(self, url)
        return self


class SqlConnectionKind(ConnectionKind):
    """The connection kind the ``sql.*`` blocks resolve their database through."""

    id: ClassVar[str] = "sql"
    config_model: ClassVar[type[BaseModel]] = SqlConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Ask the URL's own engine to reach the database, which is the smallest proof of reach."""
        settings = SqlConnectionConfig.model_validate(config.model_dump())
        url = _with_password(settings)
        return await engine_for(url).check(settings, url)


class SqlQueryConfig(BlockModel):
    """One statement, and the values bound into it."""

    connection: ConnectionRef
    """The ``sql`` connection naming the database and holding its password."""

    sql: Annotated[str, Field(min_length=1, json_schema_extra={"contentMediaType": SQL_MEDIA_TYPE})]
    """One statement, and one only. A document that needs two writes two steps, or uses
    ``sql.execute``, which is the block that runs several as one transaction."""

    params: JsonMap = Field(default_factory=dict[str, Any])
    """Values bound by name, written ``:name`` in the statement.

    This is where a ``${...}`` reference belongs. A parameter is sent to the database beside
    the statement and never spliced into it, so a value that reads as SQL is still a value.
    Nothing in ``sql`` is substituted, which also means a table or column name cannot come
    from a parameter: only a value can.

    An engine whose tables can be files is handed a storage URI as the file it opens, within
    the run's own directories; every other engine is handed the value as it was written."""

    max_rows: int = Field(default=1000, ge=1)
    """How many rows may be carried inline in the step's output.

    A result past this fails the step rather than being truncated: half an answer is not a
    smaller answer, and a step acting on it would be acting on something the database never
    said. Rows that belong in a file are handed to ``storage.write``."""

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
    """What one query returned."""

    rows: JsonList
    """The rows as objects keyed by column name, which a later step reads or writes out."""

    row_count: int
    """How many rows the query returned."""

    columns: list[str]
    """The column names, in the order the query selected them."""

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
        """Open a session, run the statement, and hand the rows on as the step's output."""
        settings = ctx.connection(config.connection, SqlConnectionConfig)
        url = _resolved(settings, ctx)
        engine = engine_for(url)
        params = engine.bind(config.params, ctx)
        started = time.monotonic()
        async with engine.session(settings, url, ctx, statements=[config.sql], params=params) as session:
            await _limit(session, settings, config.timeout)
            # The deadline covers running the statement and reading the rows out of it, because
            # a query that hangs hangs in either.
            async with asyncio.timeout(config.timeout.total_seconds()):
                result = await session.stream(sqlalchemy.text(config.sql), params)
                columns = list(result.keys())
                rows = await _inline(result, config.max_rows)
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "query ran",
            connection=config.connection,
            row_count=len(rows),
            duration_ms=duration,
        )
        return SqlQueryOutput(
            rows=rows,
            row_count=len(rows),
            columns=columns,
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

    A statement that names no parameter simply binds none of them. An engine whose tables can
    be files is handed a storage URI as the file it opens, within the run's own directories."""

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
                READ_ONLY_CONNECTION, error_class=ErrorClass.REJECTED, connection=repr(config.connection)
            )
        url = _resolved(settings, ctx)
        engine = engine_for(url)
        params = engine.bind(config.params, ctx)
        started = time.monotonic()
        counts: list[int] = []
        opened = engine.session(settings, url, ctx, statements=config.statements, params=params)
        async with opened as session, session.begin():
            await _limit(session, settings, config.timeout)
            # The deadline covers every statement together, because the transaction is what
            # the step commits or loses.
            async with asyncio.timeout(config.timeout.total_seconds()):
                for statement in config.statements:
                    result = await session.execute(sqlalchemy.text(statement), params)
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


def _with_password(settings: SqlConnectionConfig) -> URL:
    """The URL with the sealed password merged in, which is the only place the two meet."""
    url = _parse(settings.url)
    if settings.password is None:
        return url
    return url.set(password=settings.password.get_secret_value())


def _resolved(settings: SqlConnectionConfig, ctx: StepContext) -> URL:
    """The URL a step connects with: the password merged in, and a file of the run made absolute."""
    url = _with_password(settings)
    return engine_for(url).resolve(url, ctx)


async def _limit(session: SqlSession, settings: SqlConnectionConfig, timeout: timedelta) -> None:
    """Ask the database to enforce the statement deadline itself, where the dialect has one."""
    template = STATEMENT_TIMEOUT.get(_parse(settings.url).get_backend_name())
    if template is None:
        return
    await session.execute(sqlalchemy.text(template.format(milliseconds=round(timeout.total_seconds() * 1000))))


async def _inline(result: Any, max_rows: int) -> JsonList:
    """Read the rows into the output, refusing a result the step said it would not hold."""
    rows: JsonList = []
    async for batch in _batches(result):
        rows.extend(spelled_row(one) for one in batch)
        if len(rows) > max_rows:
            raise BlockFailure(TOO_MANY_ROWS, error_class=ErrorClass.REJECTED, maximum=max_rows)
    return rows


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
        raise BlockFailure(NO_JSON_SPELLING, error_class=ErrorClass.REJECTED, detail=str(error)) from error


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
