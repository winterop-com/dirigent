"""Tests for the sql family, against a SQLite database in the run's work directory."""

import base64
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from dirigent_block_sql import engines
from dirigent_block_sql.sql import (
    SqlConnectionConfig,
    SqlConnectionKind,
    SqlExecuteConfig,
    SqlExecuteOperator,
    SqlExecuteOutput,
    SqlQueryConfig,
    SqlQueryOperator,
    SqlQueryOutput,
    spelled_row,
)
from dirigent_common import SQL_MEDIA_TYPE, JsonMap
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext

#: The database every test in this module builds, relative the way a document writes it.
SQLITE = "sqlite+aiosqlite:///demo.db"


def connect(ctx: FakeContext, *, read_only: bool = False) -> SqlConnectionConfig:
    """Install a sql connection named ``db`` on the fake context and hand it back."""
    settings = SqlConnectionConfig(url=SQLITE, read_only=read_only)
    ctx.connections["db"] = settings
    return settings


async def execute(
    ctx: FakeContext,
    *statements: str,
    timeout: timedelta = timedelta(minutes=5),
    **params: object,
) -> SqlExecuteOutput:
    """Run statements through the real operator, which is also how a fixture builds a table."""
    output = await SqlExecuteOperator().execute(
        SqlExecuteConfig(connection="db", statements=list(statements), params=dict(params), timeout=timeout),
        ctx.as_context(),
    )
    assert isinstance(output, SqlExecuteOutput)
    return output


async def query(
    ctx: FakeContext,
    sql: str,
    *,
    params: JsonMap | None = None,
    max_rows: int = 1000,
    timeout: timedelta = timedelta(minutes=5),
) -> SqlQueryOutput:
    """Run one query through the real operator."""
    output = await SqlQueryOperator().execute(
        SqlQueryConfig(
            connection="db",
            sql=sql,
            params=params or {},
            max_rows=max_rows,
            timeout=timeout,
        ),
        ctx.as_context(),
    )
    assert isinstance(output, SqlQueryOutput)
    return output


@pytest.fixture
async def seeded(local_ctx: FakeContext) -> FakeContext:
    """A context whose work directory holds a two-row table."""
    connect(local_ctx)
    await execute(
        local_ctx,
        "CREATE TABLE reading (id INTEGER PRIMARY KEY, site TEXT NOT NULL, value REAL)",
        "INSERT INTO reading (id, site, value) VALUES (1, 'north', 2.5), (2, 'south', 4.0)",
    )
    return local_ctx


async def test_a_query_binds_its_parameters_rather_than_interpolating_them(seeded: FakeContext) -> None:
    output = await query(seeded, "SELECT id, site FROM reading WHERE site = :site", params={"site": "north"})
    assert output.rows == [{"id": 1, "site": "north"}]
    assert output.columns == ["id", "site"]
    assert output.row_count == 1


async def test_a_parameter_that_reads_as_sql_is_still_only_a_value(seeded: FakeContext) -> None:
    output = await query(
        seeded,
        "SELECT id FROM reading WHERE site = :site",
        params={"site": "north' OR '1'='1"},
    )
    assert output.rows == []


async def test_a_result_past_max_rows_fails_the_step_rather_than_being_truncated(seeded: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await query(seeded, "SELECT * FROM reading", max_rows=1)
    assert "max_rows" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1;\nDROP TABLE reading",
        "SELECT 1; -- a comment\nSELECT 2",
    ],
)
def test_more_than_one_statement_is_refused_when_the_document_is_written(sql: str) -> None:
    with pytest.raises(ValidationError) as raised:
        SqlQueryConfig(connection="db", sql=sql)
    assert "more than one statement" in str(raised.value)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT 1;",
        "SELECT 1; \n  ",
        "SELECT 1; -- nothing but a comment after it",
        "SELECT 1; /* nothing but a comment after it */",
        "SELECT ';' AS semicolon",
        "SELECT 'it''s ; fine' AS quoted",
        'SELECT "a ; column" FROM t',
        "SELECT 1 -- a ; in a comment",
        "SELECT 1 /* a ; in a comment */",
        "SELECT $$ a ; in a dollar quote $$",
        "SELECT $tag$ a ; in a tagged quote $tag$",
    ],
)
def test_one_statement_stays_one_statement_however_it_spells_a_semicolon(sql: str) -> None:
    assert SqlQueryConfig(connection="db", sql=sql).sql == sql


def test_a_query_publishes_its_statement_as_sql() -> None:
    """A form generated from the schema needs the language named to edit the field as source."""
    published = SqlQueryConfig.model_json_schema()["properties"]["sql"]

    assert published["contentMediaType"] == SQL_MEDIA_TYPE


def test_an_empty_statement_in_a_list_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        SqlExecuteConfig(connection="db", statements=["SELECT 1", "  "])
    assert "statement 1 is empty" in str(raised.value)


def test_a_document_that_lists_no_statement_is_refused() -> None:
    with pytest.raises(ValidationError):
        SqlExecuteConfig(connection="db", statements=[])


async def test_every_statement_runs_in_one_transaction_and_reports_what_it_touched(
    local_ctx: FakeContext,
) -> None:
    connect(local_ctx)
    output = await execute(
        local_ctx,
        "CREATE TABLE site (code TEXT PRIMARY KEY)",
        "INSERT INTO site (code) VALUES (:code)",
        "UPDATE site SET code = :code",
        code="north",
    )
    assert output.row_counts == [-1, 1, 1]
    assert output.duration_ms >= 0
    assert (await query(local_ctx, "SELECT code FROM site")).rows == [{"code": "north"}]


async def test_a_failing_statement_leaves_none_of_the_transaction_behind(local_ctx: FakeContext) -> None:
    connect(local_ctx)
    await execute(local_ctx, "CREATE TABLE site (code TEXT PRIMARY KEY)")
    with pytest.raises(Exception, match="UNIQUE constraint failed"):
        await execute(
            local_ctx,
            "INSERT INTO site (code) VALUES ('north')",
            "INSERT INTO site (code) VALUES ('north')",
        )
    assert (await query(local_ctx, "SELECT code FROM site")).rows == []


async def test_execute_is_refused_on_a_read_only_connection(local_ctx: FakeContext) -> None:
    connect(local_ctx)
    await execute(local_ctx, "CREATE TABLE site (code TEXT PRIMARY KEY)")
    connect(local_ctx, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await execute(local_ctx, "INSERT INTO site (code) VALUES ('north')")
    assert "read_only" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_write_through_a_read_only_query_is_refused_by_the_database(local_ctx: FakeContext) -> None:
    connect(local_ctx)
    await execute(local_ctx, "CREATE TABLE site (code TEXT PRIMARY KEY)")
    connect(local_ctx, read_only=True)
    with pytest.raises(Exception, match="readonly|read-only|read only"):
        await query(local_ctx, "INSERT INTO site (code) VALUES ('north')")


async def test_a_read_only_connection_still_reads(seeded: FakeContext) -> None:
    connect(seeded, read_only=True)
    assert (await query(seeded, "SELECT COUNT(*) AS n FROM reading")).rows == [{"n": 2}]


async def test_a_read_only_statement_that_fails_closes_the_connection_and_the_engine(
    local_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The autouse guard in the root conftest fails this test if the connection is left open."""
    disposed: list[AsyncEngine] = []
    dispose = AsyncEngine.dispose

    async def recorded(engine: AsyncEngine, close: bool = True) -> None:
        disposed.append(engine)
        await dispose(engine, close)

    monkeypatch.setattr(AsyncEngine, "dispose", recorded)
    monkeypatch.setitem(engines.READ_ONLY, "sqlite", "PRAGMA no such pragma")
    connect(local_ctx, read_only=True)
    with pytest.raises(Exception, match="syntax error"):
        await query(local_ctx, "SELECT 1")
    assert len(disposed) == 1, "the engine behind the session that never opened was disposed"


async def test_bytes_reach_a_document_in_the_house_json_spelling(local_ctx: FakeContext) -> None:
    connect(local_ctx)
    await execute(local_ctx, "CREATE TABLE odd (payload BLOB)")
    await execute(local_ctx, "INSERT INTO odd (payload) VALUES (:payload)", payload=b"\x00\x01\x02")
    output = await query(local_ctx, "SELECT payload FROM odd")
    assert output.rows == [{"payload": base64.b64encode(b"\x00\x01\x02").decode()}]


async def test_a_column_with_no_json_spelling_names_itself(local_ctx: FakeContext) -> None:
    connect(local_ctx)
    with pytest.raises(BlockFailure) as raised:
        spelled_row(SimpleNamespace(_mapping={"unspellable": object()}))
    assert "no JSON spelling" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_query_that_outlives_its_timeout_ends_the_step(seeded: FakeContext) -> None:
    slow = (
        "WITH RECURSIVE counted(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM counted WHERE n < 3000000) "
        "SELECT COUNT(*) AS n FROM counted"
    )
    with pytest.raises(TimeoutError):
        await query(seeded, slow, timeout=timedelta(milliseconds=50))


async def test_a_transaction_that_outlives_its_timeout_ends_the_step(seeded: FakeContext) -> None:
    slow = (
        "CREATE TABLE counted AS WITH RECURSIVE series(n) AS "
        "(SELECT 1 UNION ALL SELECT n + 1 FROM series WHERE n < 3000000) SELECT n FROM series"
    )
    with pytest.raises(TimeoutError):
        await execute(seeded, slow, timeout=timedelta(milliseconds=50))


async def test_a_url_carrying_its_password_inline_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        SqlConnectionConfig(url="postgresql+asyncpg://user:secret@host/db")
    assert "sealed password field" in str(raised.value)


async def test_a_synchronous_url_is_refused_because_these_blocks_speak_async() -> None:
    with pytest.raises(ValidationError) as raised:
        SqlConnectionConfig(url="postgresql://user@host/db")
    assert "names no driver" in str(raised.value)


def test_a_url_that_is_not_a_url_says_so() -> None:
    with pytest.raises(ValidationError) as raised:
        SqlConnectionConfig(url="not a database at all")
    assert "is not a database url" in str(raised.value)


def test_read_only_is_refused_on_a_dialect_that_cannot_be_told_to_refuse_writes() -> None:
    with pytest.raises(ValidationError) as raised:
        SqlConnectionConfig(url="mysql+aiomysql://user@host/db", read_only=True)
    assert "read_only has no meaning" in str(raised.value)


def test_the_password_is_sealed_and_never_rendered() -> None:
    settings = SqlConnectionConfig(url="postgresql+asyncpg://user@host/db", password=SecretStr("hunter2"))
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in settings.model_dump_json()
    assert settings.password is not None
    assert settings.password.get_secret_value() == "hunter2"


def test_the_connection_kind_seals_the_password_and_nothing_else() -> None:
    fields = SqlConnectionKind.config_model.model_fields
    assert fields["password"].annotation is not str
    assert SqlConnectionKind.id == "sql"


async def test_a_check_opens_the_database_and_asks_it_for_a_one(tmp_path: Path) -> None:
    report = await SqlConnectionKind().check(SqlConnectionConfig(url=f"sqlite+aiosqlite:///{tmp_path}/check.db"))
    assert report.healthy
    assert "sqlite" in (report.detail or "")


async def test_a_check_of_a_database_that_is_not_there_is_red() -> None:
    report = await SqlConnectionKind().check(
        SqlConnectionConfig(url="postgresql+asyncpg://nobody@127.0.0.1:1/nothing", connect_timeout=timedelta(seconds=2))
    )
    assert not report.healthy
    assert report.detail


async def test_a_check_says_a_run_relative_database_cannot_be_checked_outside_a_run() -> None:
    report = await SqlConnectionKind().check(SqlConnectionConfig(url=SQLITE))
    assert not report.healthy
    assert "only inside a run" in (report.detail or "")


async def test_a_driver_that_is_not_installed_names_the_package_to_install(local_ctx: FakeContext) -> None:
    local_ctx.connections["db"] = SqlConnectionConfig(url="mysql+aiomysql://user@host/db")
    with pytest.raises(BlockFailure) as raised:
        await query(local_ctx, "SELECT 1")
    assert "aiomysql" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_run_relative_database_lands_in_the_work_directory(ctx: FakeContext) -> None:
    """A database a pipeline builds for itself is a file, so a bucket artifact root is no obstacle."""
    ctx.connections["db"] = SqlConnectionConfig(url=SQLITE)
    ctx.scratch_uri = "s3://bucket/runs/one"
    await query(ctx, "SELECT 1")
    assert list(ctx.work.rglob("*.db")), "the database was made under the run's work directory"
