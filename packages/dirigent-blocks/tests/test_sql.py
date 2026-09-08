"""Tests for the sql family, against a SQLite and a duckdb file in the run's work directory."""

import base64
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks.sql import (
    S3StorageSettings,
    SqlConnectionConfig,
    SqlConnectionKind,
    SqlExecuteConfig,
    SqlExecuteOperator,
    SqlExecuteOutput,
    SqlQueryConfig,
    SqlQueryOperator,
    SqlQueryOutput,
    addresses_s3,
    s3_options,
    spelled_row,
)
from dirigent_common import JsonMap
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
    save_to: str | None = None,
    timeout: timedelta = timedelta(minutes=5),
) -> SqlQueryOutput:
    """Run one query through the real operator."""
    output = await SqlQueryOperator().execute(
        SqlQueryConfig(
            connection="db",
            sql=sql,
            params=params or {},
            max_rows=max_rows,
            save_to=save_to,
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
    assert output.saved_to is None


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


async def test_saving_streams_the_rows_as_ndjson_and_carries_no_rows_inline(seeded: FakeContext) -> None:
    uri = f"{seeded.scratch}/rows.ndjson"
    output = await query(seeded, "SELECT id, site FROM reading ORDER BY id", save_to=uri, max_rows=1)
    assert output.rows is None
    assert output.row_count == 2
    assert output.saved_to == uri
    lines = _read(seeded, uri).splitlines()
    assert [json.loads(line) for line in lines] == [{"id": 1, "site": "north"}, {"id": 2, "site": "south"}]


async def test_a_saved_result_ignores_max_rows(seeded: FakeContext) -> None:
    output = await query(seeded, "SELECT * FROM reading", save_to=f"{seeded.scratch}/all.ndjson", max_rows=1)
    assert output.row_count == 2


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


def _read(ctx: FakeContext, uri: str) -> str:
    """Read back what the step wrote, through the same storage the block used."""
    return ctx.storage.path_for(uri).read_text()


#: The duckdb database the engine's tests build, relative the way a document writes it.
DUCKDB = "duckdb:///demo.duckdb"


def duck(ctx: FakeContext, url: str = DUCKDB, *, read_only: bool = False) -> SqlConnectionConfig:
    """Install a duckdb connection named ``db`` on the fake context and hand it back."""
    settings = SqlConnectionConfig(url=url, read_only=read_only)
    ctx.connections["db"] = settings
    return settings


@pytest.fixture
async def ducked(local_ctx: FakeContext) -> FakeContext:
    """A context whose work directory holds a duckdb file with a two-row table."""
    duck(local_ctx)
    await execute(
        local_ctx,
        "CREATE TABLE reading (id INTEGER, site TEXT, value DOUBLE)",
        "INSERT INTO reading VALUES (1, 'north', 2.5), (2, 'south', 4.0)",
    )
    return local_ctx


async def test_duckdb_runs_a_query_with_its_parameters_bound(ducked: FakeContext) -> None:
    output = await query(ducked, "SELECT id, site FROM reading WHERE site = :site", params={"site": "north"})
    assert output.rows == [{"id": 1, "site": "north"}]
    assert output.columns == ["id", "site"]
    assert output.row_count == 1


async def test_duckdb_in_memory_needs_no_file_at_all(local_ctx: FakeContext) -> None:
    duck(local_ctx, "duckdb:///:memory:")
    output = await query(local_ctx, "SELECT :n * 2 AS doubled", params={"n": 21})
    assert output.rows == [{"doubled": 42}]


async def test_duckdb_saves_a_result_to_storage_as_ndjson(ducked: FakeContext) -> None:
    uri = f"{ducked.scratch}/reading.ndjson"
    output = await query(ducked, "SELECT id, site FROM reading ORDER BY id", save_to=uri, max_rows=1)
    assert output.rows is None
    assert output.row_count == 2
    assert output.saved_to == uri
    assert [json.loads(line) for line in _read(ducked, uri).splitlines()] == [
        {"id": 1, "site": "north"},
        {"id": 2, "site": "south"},
    ]


async def test_a_read_only_duckdb_connection_reads_and_refuses_to_write(ducked: FakeContext) -> None:
    duck(ducked, read_only=True)
    assert (await query(ducked, "SELECT COUNT(*) AS n FROM reading")).rows == [{"n": 2}]
    with pytest.raises(Exception, match="read-only|read only"):
        await query(ducked, "INSERT INTO reading VALUES (3, 'east', 1.0)")


def test_a_read_only_duckdb_in_memory_connection_is_refused_when_it_is_written() -> None:
    with pytest.raises(ValidationError) as raised:
        SqlConnectionConfig(url="duckdb:///:memory:", read_only=True)
    assert "refuses to open" in str(raised.value)


async def test_duckdb_writes_a_parquet_artifact_and_reads_it_back_through_a_storage_uri(
    ducked: FakeContext,
) -> None:
    target = f"{ducked.scratch}/reading.parquet"
    await execute(
        ducked,
        "COPY (SELECT id, site, value FROM reading ORDER BY id) TO :target (FORMAT parquet)",
        target=target,
    )
    assert ducked.storage.path_for(target).exists()
    duck(ducked, "duckdb:///:memory:")
    output = await query(
        ducked,
        "SELECT site, value FROM read_parquet(:source) WHERE id = :id",
        params={"source": target, "id": 1},
    )
    assert output.rows == [{"site": "north", "value": 2.5}]


async def test_duckdb_reads_a_csv_through_a_storage_uri(ducked: FakeContext) -> None:
    target = f"{ducked.scratch}/reading.csv"
    await execute(
        ducked, "COPY (SELECT id, site FROM reading ORDER BY id) TO :target (FORMAT csv, HEADER)", target=target
    )
    output = await query(ducked, "SELECT COUNT(*) AS n FROM read_csv_auto(:source)", params={"source": target})
    assert output.rows == [{"n": 2}]


async def test_a_file_outside_the_run_is_refused_rather_than_read(ducked: FakeContext, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.parquet"
    outside.write_bytes(b"")
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELECT * FROM read_parquet(:source)", params={"source": f"file://{outside}"})
    assert "outside this run's own directories" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_bucket_uri_with_no_connection_bound_to_the_scheme_is_refused(ducked: FakeContext) -> None:
    """The engine opens s3:// itself, and it needs the scheme's endpoint and credential to do it."""
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELECT * FROM read_parquet(:source)", params={"source": "s3://bucket/reading.parquet"})
    assert "DIRIGENT_STORAGE_CONNECTIONS" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_gs_uri_still_says_to_copy_the_file_into_the_run_first(ducked: FakeContext) -> None:
    """Only s3:// is wired to duckdb; the others are still copied in by the document."""
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELECT * FROM read_parquet(:source)", params={"source": "gs://bucket/reading.parquet"})
    assert "storage.copy" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


def test_a_statement_naming_a_bucket_is_seen_as_well_as_a_parameter() -> None:
    """A literal s3:// in the sql needs the extension just as much as a bound one does."""
    assert addresses_s3({}, ["COPY t TO 's3://bucket/out.csv'"])
    assert addresses_s3({"source": "s3://bucket/in.parquet"}, ["SELECT 1"])
    assert not addresses_s3({"floor": -10}, ["SELECT 1"])


def test_the_endpoint_becomes_a_host_and_a_tls_answer() -> None:
    """The engine takes the endpoint without a scheme and asks separately whether to use TLS."""
    plain = dict(s3_options(S3StorageSettings(endpoint_url="http://s3:9000", path_style=True)))
    assert plain["s3_endpoint"] == "s3:9000"
    assert plain["s3_use_ssl"] is False
    assert plain["s3_url_style"] == "path"

    secure = dict(s3_options(S3StorageSettings(endpoint_url="https://s3.example.org")))
    assert secure["s3_endpoint"] == "s3.example.org"
    assert secure["s3_use_ssl"] is True
    assert secure["s3_url_style"] == "vhost"


def test_aws_itself_needs_no_endpoint_and_keeps_the_region() -> None:
    options = dict(s3_options(S3StorageSettings(region="eu-north-1")))
    assert "s3_endpoint" not in options
    assert options["s3_region"] == "eu-north-1"


def test_a_credential_reaches_duckdb_and_never_the_statement() -> None:
    """The secret is one of the values SET binds, so it is never part of a statement's text."""
    options = s3_options(S3StorageSettings(access_key_id="a-key", secret_access_key=SecretStr("a-secret-key")))
    assert ("s3_access_key_id", "a-key") in options
    assert ("s3_secret_access_key", "a-secret-key") in options


async def test_a_duckdb_query_that_outlives_its_timeout_ends_the_step(ducked: FakeContext) -> None:
    with pytest.raises(TimeoutError):
        await query(
            ducked,
            "SELECT COUNT(*) AS n FROM range(100000000000) WHERE random() < 0.5",
            timeout=timedelta(milliseconds=100),
        )


async def test_a_check_opens_the_duckdb_file_and_asks_it_for_a_one(tmp_path: Path) -> None:
    report = await SqlConnectionKind().check(SqlConnectionConfig(url=f"duckdb:///{tmp_path}/check.duckdb"))
    assert report.healthy
    assert "duckdb" in (report.detail or "")


async def test_a_check_of_a_read_only_duckdb_file_that_is_not_there_is_red(tmp_path: Path) -> None:
    report = await SqlConnectionKind().check(
        SqlConnectionConfig(url=f"duckdb:///{tmp_path}/absent.duckdb", read_only=True)
    )
    assert not report.healthy
    assert report.detail
