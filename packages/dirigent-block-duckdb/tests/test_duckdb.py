"""Tests for the duckdb engine: the blocks over files, and the run's directories around them."""

import asyncio
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import duckdb
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Connection

from dirigent_block_duckdb import engine
from dirigent_block_duckdb.engine import HTTPFS, S3StorageSettings, addresses_s3, s3_secret
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
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "INSERT INTO reading VALUES (3, 'east', 1.0)")
    assert raised.value.code == "sql.duckdb.read_only_runs_select"


@pytest.mark.parametrize(
    "statement",
    [
        "COPY (SELECT 'x' AS v) TO '{database}' (FORMAT csv, USE_TMP_FILE false)",
        "EXPLAIN ANALYZE COPY (SELECT 'x' AS v) TO '{database}' (FORMAT csv, USE_TMP_FILE false)",
    ],
    ids=["copy", "explain-analyze"],
)
async def test_a_read_only_duckdb_connection_cannot_overwrite_its_own_file(ducked: FakeContext, statement: str) -> None:
    database = ducked.as_context().work / "demo.duckdb"
    before = database.read_bytes()
    duck(ducked, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, statement.format(database=database))
    assert raised.value.code == "sql.duckdb.read_only_runs_select"
    assert raised.value.error_class is ErrorClass.REJECTED
    assert database.read_bytes() == before


#: A write onto the database file that nothing but its parsed tree shows, in each place duckdb
#: runs one or reads one.
COPIES = "COPY (SELECT 'x' AS v) TO '{database}' (FORMAT csv, USE_TMP_FILE false)"


@pytest.mark.parametrize(
    "statement",
    [
        f"WITH w AS ({COPIES}) SELECT * FROM w",
        f"with w as ({COPIES}) select * from w",
        f"/* a */ WITH /* b */ w /* c */ AS /* d */ ({COPIES}) SELECT * FROM w",
        f"-- a read\nWITH w AS ({COPIES})\nSELECT * FROM w",
        f"WITH w AS MATERIALIZED ({COPIES}) SELECT * FROM w",
        f"WITH w AS NOT MATERIALIZED ({COPIES}) SELECT * FROM w",
        f"(WITH w AS ({COPIES}) SELECT * FROM w)",
        f"WITH a AS (SELECT 1), w AS ({COPIES}) SELECT * FROM w",
        f"WITH w AS ({COPIES}) FROM w",
        f"WITH w AS ({COPIES}) SELECT 1",
        f"WITH w AS ({COPIES}) VALUES (1)",
        f"WITH w AS ({COPIES}) SELECT * FROM w UNION ALL SELECT 1",
        f"WITH w AS ({COPIES}) SELECT 1;",
        f"SELECT * FROM (WITH w AS ({COPIES}) SELECT * FROM w)",
        f"SELECT 1 UNION ALL (WITH w AS ({COPIES}) SELECT * FROM w)",
        f"SUMMARIZE WITH w AS ({COPIES}) SELECT * FROM w",
        f"DESCRIBE WITH w AS ({COPIES}) SELECT * FROM w",
        "WITH w AS (COPY reading TO '{database}' (FORMAT csv)) SELECT 1",
        "WITH w AS (COPY (SELECT 'x' AS v) TO '{database}.wal' (FORMAT csv)) SELECT 1",
    ],
    ids=[
        "with",
        "lower-case",
        "block-comments",
        "line-comment",
        "materialized",
        "not-materialized",
        "parenthesised",
        "second-cte",
        "from-first",
        "unused",
        "values",
        "union",
        "semicolon",
        "subquery",
        "union-branch",
        "summarize",
        "describe",
        "table",
        "wal",
    ],
)
async def test_a_read_only_duckdb_connection_refuses_a_copy_anywhere_in_a_statement(
    ducked: FakeContext, statement: str
) -> None:
    database = ducked.as_context().work / "demo.duckdb"
    before = database.read_bytes()
    duck(ducked, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, statement.format(database=database))
    assert raised.value.code == "sql.duckdb.read_only_runs_select"
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "COPY" in str(raised.value)
    assert database.read_bytes() == before


async def test_a_copy_bound_as_a_parameter_is_refused_all_the_same(ducked: FakeContext) -> None:
    database = ducked.as_context().work / "demo.duckdb"
    before = database.read_bytes()
    duck(ducked, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await query(
            ducked,
            "WITH w AS (COPY (SELECT 'x' AS v) TO :target (FORMAT csv, USE_TMP_FILE false)) SELECT * FROM w",
            params={"target": f"file://{database}"},
        )
    assert raised.value.code == "sql.duckdb.read_only_runs_select"
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "statement",
    [
        "WITH w AS (INSERT INTO reading VALUES (9, 'x', 1.0) RETURNING *) SELECT * FROM w",
        "WITH w AS (UPDATE reading SET id = 9 RETURNING *) SELECT * FROM w",
        "WITH w AS (DELETE FROM reading RETURNING *) SELECT * FROM w",
    ],
    ids=["insert", "update", "delete"],
)
async def test_a_read_only_duckdb_connection_refuses_a_write_inside_a_with(ducked: FakeContext, statement: str) -> None:
    duck(ducked, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, statement)
    assert raised.value.code == "sql.duckdb.read_only_runs_select"


def carried(statement: str) -> str:
    """A statement as ``json_execute_serialized_sql`` takes it: serialized, in a string."""
    tree = duckdb.connect().execute("SELECT json_serialize_sql(?)", [statement]).fetchone()
    assert tree is not None
    return "'" + str(tree[0]).replace("'", "''") + "'"


@pytest.mark.parametrize(
    "shape",
    [
        "FROM json_execute_serialized_sql({carried})",
        "SELECT * FROM json_execute_serialized_sql({carried})",
        "FROM JSON_EXECUTE_SERIALIZED_SQL({carried})",
        'FROM "json_execute_serialized_sql"({carried})',
        "FROM system.main.json_execute_serialized_sql({carried})",
        "SELECT * FROM range(1), json_execute_serialized_sql({carried})",
        "FROM query($$FROM json_execute_serialized_sql({carried})$$)",
        "FROM query($$WITH w AS (COPY (SELECT 1 AS v) TO '{database}' (FORMAT csv)) SELECT * FROM w$$)",
        "FROM query_table('reading')",
    ],
    ids=["from", "select", "upper", "quoted", "qualified", "joined", "query", "query-copy", "query-table"],
)
async def test_a_statement_carried_in_a_string_is_refused_rather_than_run(ducked: FakeContext, shape: str) -> None:
    database = ducked.as_context().work / "demo.duckdb"
    before = database.read_bytes()
    duck(ducked, read_only=True)
    statement = shape.replace(
        "{carried}", carried(f"WITH w AS ({COPIES.format(database=database)}) SELECT * FROM w")
    ).replace("{database}", str(database))
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, statement)
    assert raised.value.code == "sql.duckdb.read_only_runs_select"
    assert database.read_bytes() == before


class AnsweringTree:
    """A connection whose ``json_serialize_sql`` answers with this, or raises it."""

    def __init__(self, answer: Exception | str) -> None:
        """Hold what the serialization answers."""
        self.answer = answer

    def execute(self, *_arguments: object) -> "AnsweringTree":
        return self

    def fetchone(self) -> tuple[str]:
        if isinstance(self.answer, Exception):
            raise self.answer
        return (self.answer,)


@pytest.mark.parametrize(
    "answer",
    [
        duckdb.Error("no such function"),
        '{"error":true,"error_message":"no tree"}',
        '{"error":false,"statements":[]}',
        '{"error":false,"statements":[{},{}]}',
        '{"error":false}',
        '{"statements":[{}]}',
        "[]",
        "not json",
        "[" * 100_000,
    ],
    ids=[
        "raises",
        "error",
        "no-statements",
        "too-many",
        "no-field",
        "no-error-field",
        "a-list",
        "not-json",
        "too-deep",
    ],
)
def test_a_tree_that_cannot_be_had_whole_is_refused_rather_than_run(answer: Exception | str) -> None:
    with pytest.raises(BlockFailure) as raised:
        engine.parsed_tree(AnsweringTree(answer), "SELECT 1", 1)
    assert raised.value.code == "sql.duckdb.read_only_unparsed"
    assert raised.value.error_class is ErrorClass.REJECTED


@pytest.mark.parametrize(
    "statement",
    ["SET threads = 1", "ATTACH ':memory:' AS other", "CALL pragma_table_info('reading')", "   ", "-- nothing"],
    ids=["set", "attach", "call", "blank", "comment"],
)
async def test_a_read_only_duckdb_connection_refuses_anything_but_select(ducked: FakeContext, statement: str) -> None:
    duck(ducked, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, statement)
    assert raised.value.code == "sql.duckdb.read_only_runs_select"


async def test_a_read_only_duckdb_connection_refuses_what_it_cannot_parse(ducked: FakeContext) -> None:
    duck(ducked, read_only=True)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELEC 1")
    assert raised.value.code == "sql.duckdb.read_only_unparsed"
    assert raised.value.error_class is ErrorClass.REJECTED


@pytest.mark.parametrize(
    ("statement", "params", "rows"),
    [
        ("SELECT site FROM reading WHERE id = :id AND value > :least", {"id": 1, "least": 1}, [{"site": "north"}]),
        ("SELECT id::text AS id FROM reading WHERE id = :id", {"id": 2}, [{"id": "2"}]),
        ("WITH picked AS (SELECT id FROM reading WHERE id = 1) SELECT id FROM picked", {}, [{"id": 1}]),
        ("FROM reading SELECT id WHERE id = 2", {}, [{"id": 2}]),
        (
            "SELECT 'COPY_QUERY_NODE' AS type, 'query' AS function_name",
            {},
            [{"type": "COPY_QUERY_NODE", "function_name": "query"}],
        ),
        ("SELECT {'type': 'COPY_QUERY_NODE'}.type AS kind", {}, [{"kind": "COPY_QUERY_NODE"}]),
        ("SELECT 1 AS copy_query_node", {}, [{"copy_query_node": 1}]),
        ("SELECT id FROM reading WHERE id = 1 UNION SELECT 7 ORDER BY id", {}, [{"id": 1}, {"id": 7}]),
        ("SELECT id FROM reading WHERE id < 3 EXCEPT SELECT 2", {}, [{"id": 1}]),
        (
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 2) FROM n",
            {},
            [{"x": 1}, {"x": 2}],
        ),
        ("WITH a AS MATERIALIZED (SELECT 3 AS x) SELECT x FROM a", {}, [{"x": 3}]),
        ("SELECT x FROM (WITH a AS (SELECT 4 AS x) SELECT * FROM a)", {}, [{"x": 4}]),
        ("SELECT (SELECT MAX(id) FROM reading) AS top", {}, [{"top": 2}]),
        ("VALUES (5)", {}, [{"col0": 5}]),
        ("SELECT COUNT(*) AS n FROM range(2)", {}, [{"n": 2}]),
        ("SELECT COUNT(*) > 0 AS any FROM duckdb_tables()", {}, [{"any": True}]),
        ("SELECT * FROM (VALUES (1)) t(a), LATERAL (SELECT a + 1 AS b)", {}, [{"a": 1, "b": 2}]),
    ],
    ids=[
        "bound",
        "cast",
        "with",
        "from-first",
        "literal-naming-a-node",
        "struct-naming-a-node",
        "alias-naming-a-node",
        "union",
        "except",
        "recursive",
        "materialized",
        "with-in-a-subquery",
        "scalar-subquery",
        "values",
        "table-function",
        "catalog-function",
        "lateral",
    ],
)
async def test_a_read_only_duckdb_connection_still_runs_every_spelling_of_a_read(
    ducked: FakeContext, statement: str, params: JsonMap, rows: list[JsonMap]
) -> None:
    duck(ducked, read_only=True)
    assert (await query(ducked, statement, params=params)).rows == rows


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


async def test_a_read_only_duckdb_connection_reads_a_file_a_step_wrote(ducked: FakeContext) -> None:
    target = f"{ducked.scratch}/reading.parquet"
    await execute(ducked, "COPY (SELECT id FROM reading ORDER BY id) TO :target (FORMAT parquet)", target=target)
    duck(ducked, read_only=True)
    output = await query(ducked, "SELECT COUNT(*) AS n FROM read_parquet(:source)", params={"source": target})
    assert output.rows == [{"n": 2}]


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


async def test_a_file_reached_through_dot_dot_is_refused_before_any_directory_is_made(
    ducked: FakeContext, tmp_path: Path
) -> None:
    escape = "/..".join([""] * (len(ducked.work.parts)))
    target = f"file://{ducked.work}{escape}{tmp_path}/planted/x.csv"
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELECT 1 AS n", params={"target": target})
    assert "outside this run's own directories" in str(raised.value)
    assert not (tmp_path / "planted").exists()


async def test_a_file_reached_through_a_symlink_out_of_the_run_is_refused(ducked: FakeContext, tmp_path: Path) -> None:
    (ducked.work / "link").symlink_to(tmp_path)
    with pytest.raises(BlockFailure) as raised:
        await query(ducked, "SELECT 1 AS n", params={"target": f"file://{ducked.work}/link/planted/x.csv"})
    assert "outside this run's own directories" in str(raised.value)
    assert not (tmp_path / "planted").exists()


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
    plain = s3_secret(S3StorageSettings(endpoint_url="http://s3:9000", path_style=True))
    assert plain["ENDPOINT"] == "s3:9000"
    assert plain["USE_SSL"] is False
    assert plain["URL_STYLE"] == "path"

    secure = s3_secret(S3StorageSettings(endpoint_url="https://s3.example.org"))
    assert secure["ENDPOINT"] == "s3.example.org"
    assert secure["USE_SSL"] is True
    assert secure["URL_STYLE"] == "vhost"


def test_aws_itself_needs_no_endpoint_and_keeps_the_region() -> None:
    secret = s3_secret(S3StorageSettings(region="eu-north-1"))
    assert "ENDPOINT" not in secret
    assert secret["REGION"] == "eu-north-1"


def test_the_credential_is_a_parameter_of_the_secret() -> None:
    """The key and its secret are values the statement binds, so neither is part of its text."""
    secret = s3_secret(S3StorageSettings(access_key_id="a-key", secret_access_key=SecretStr("a-secret-key")))
    assert secret["KEY_ID"] == "a-key"
    assert secret["SECRET"] == "a-secret-key"


async def test_a_result_larger_than_max_rows_is_refused_while_it_streams(ducked: FakeContext) -> None:
    """The refusal arrives mid-stream, and the connection it leaves open still rolls back and closes."""
    with pytest.raises(BlockFailure) as refused:
        await query(ducked, "SELECT range AS n FROM range(500000)", max_rows=10)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "max_rows" in str(refused.value)


async def test_every_database_a_step_opens_bounds_its_io_threads(ducked: FakeContext) -> None:
    output = await query(ducked, "SELECT current_setting('async_threads') AS threads")
    assert output.rows == [{"threads": engine.ASYNC_THREADS}]


async def test_a_duckdb_query_that_outlives_its_timeout_ends_the_step(ducked: FakeContext) -> None:
    with pytest.raises(TimeoutError):
        await query(
            ducked,
            "SELECT COUNT(*) AS n FROM range(100000000000) WHERE random() < 0.5",
            timeout=timedelta(milliseconds=100),
        )


async def test_a_call_that_ignores_the_interrupt_is_left_behind_and_closes_the_connection_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine, "INTERRUPT_GRACE_SECONDS", 0.05)
    release = threading.Event()
    closed = threading.Event()
    connection = SimpleNamespace(
        connection=SimpleNamespace(driver_connection=SimpleNamespace(interrupt=lambda: None)),
        close=closed.set,
    )
    threaded = engine._Threaded(cast(Connection, connection), [])  # pyright: ignore[reportPrivateUsage] - the connection under test

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await threaded._call(release.wait)  # pyright: ignore[reportPrivateUsage] - the call under test
    assert threaded.busy
    await threaded.close()
    assert not closed.is_set()

    release.set()
    assert await asyncio.to_thread(closed.wait, 5)


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
