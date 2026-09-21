"""Tests for the duckdb engine: the blocks over files, and the run's directories around them."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from dirigent_block_duckdb.engine import HTTPFS, S3StorageSettings, addresses_s3, s3_options
from dirigent_block_sql.sql import (
    SqlConnectionConfig,
    SqlConnectionKind,
    SqlExecuteConfig,
    SqlExecuteOperator,
    SqlExecuteOutput,
    SqlQueryConfig,
    SqlQueryOperator,
    SqlQueryOutput,
)
from dirigent_common import JsonMap
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext


def httpfs_installed() -> bool:
    """Whether this worker can load httpfs, which the s3 path loads and never installs."""
    import duckdb

    try:
        duckdb.connect().execute(f"LOAD {HTTPFS}")
    except duckdb.Error:
        return False
    return True


#: Whether anything reaching a bucket can run here at all. CI installs the extension for the s3 lane.
HAS_HTTPFS = httpfs_installed()


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


#: The database every test in this module builds, relative the way a document writes it.
DATABASE = "duckdb:///demo.duckdb"


def duck(ctx: FakeContext, url: str = DATABASE, *, read_only: bool = False) -> SqlConnectionConfig:
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


async def test_a_plain_path_parameter_outside_the_run_is_refused_by_the_engine(
    ducked: FakeContext, tmp_path: Path
) -> None:
    """A value that is a path rather than a storage URI is held to the same directories."""
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("id\n1\n")
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELECT * FROM read_csv(:source)", params={"source": str(outside)})
    assert "outside the run's own directories" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_path_written_into_the_sql_is_refused_the_same_way(ducked: FakeContext, tmp_path: Path) -> None:
    """The boundary is duckdb's own, so a path spelled out in the statement reaches no further."""
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("id\n1\n")
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, f"SELECT * FROM read_csv('{outside}')")
    assert "outside the run's own directories" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_file_in_the_work_directory_is_read_through_a_path_in_the_sql(ducked: FakeContext) -> None:
    """Containment is the run's directories, not a ban on paths: the run's own files still open."""
    inside = ducked.work / "readings.csv"
    inside.write_text("id,site\n1,north\n2,south\n")
    output = await query(ducked, f"SELECT COUNT(*) AS n FROM read_csv('{inside}')")
    assert output.rows == [{"n": 2}]


async def test_a_statement_cannot_set_its_way_back_out(ducked: FakeContext, tmp_path: Path) -> None:
    """The configuration is locked, so the statement that would widen the roots is refused."""
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("id\n1\n")
    for statement in ("SET enable_external_access = true", "RESET enable_external_access"):
        with pytest.raises(Exception, match="locked"):
            await execute(ducked, statement)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, f"SELECT * FROM read_csv('{outside}')")
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_statement_cannot_load_an_extension(ducked: FakeContext) -> None:
    """A session carries the extensions it was opened with and can be given no others."""
    with pytest.raises(BlockFailure) as raised:
        await execute(ducked, f"LOAD {HTTPFS}")
    assert "extension" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_the_database_the_connection_names_opens_wherever_it_is(local_ctx: FakeContext, tmp_path: Path) -> None:
    """The containment covers what a statement names, not the file the connection itself opens."""
    duck(local_ctx, f"duckdb:///{tmp_path}/warehouse.duckdb")
    await execute(local_ctx, "CREATE TABLE reading (id INTEGER)", "INSERT INTO reading VALUES (1)")
    assert (await query(local_ctx, "SELECT COUNT(*) AS n FROM reading")).rows == [{"n": 1}]


@pytest.mark.skipif(not HAS_HTTPFS, reason="duckdb's httpfs extension is not installed on this worker")
async def test_a_step_that_addresses_a_bucket_keeps_its_reach_to_it(ducked: FakeContext) -> None:
    """The s3 scheme stays open where the step asked for it: the endpoint answers, not the boundary.

    The endpoint is one nothing listens on, so a session that reached the network fails
    connecting and a session that was held back fails on the path instead.
    """
    ducked.connections["bucket"] = S3StorageSettings(
        endpoint_url="http://127.0.0.1:1",
        access_key_id="a-key",
        secret_access_key=SecretStr("a-secret-key"),
        path_style=True,
    )
    ducked.storage_connections["s3"] = "bucket"
    with pytest.raises(Exception) as raised:
        await query(ducked, "SELECT * FROM read_csv(:source)", params={"source": "s3://bucket/readings.csv"})
    assert "127.0.0.1:1" in str(raised.value)


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
