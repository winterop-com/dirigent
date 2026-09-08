"""DuckDB over object storage, against a real S3-compatible server.

``sql.query`` and ``sql.execute`` open an ``s3://`` object through duckdb's httpfs extension,
on the credentials the ``s3`` scheme is configured from -- so an instance whose artifact root
is a bucket runs a document that reads and writes parquet without a local copy anywhere.
"""

from typing import Any

import pytest
from pydantic import SecretStr

from dirigent_blocks.sql import (
    S3StorageSettings,
    SqlConnectionConfig,
    SqlExecuteConfig,
    SqlExecuteOperator,
    SqlQueryConfig,
    SqlQueryOperator,
    SqlQueryOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_storage_s3 import S3StorageConfig
from dirigent_testing import FakeContext, FakeStorage
from s3server import ACCESS_KEY, BUCKET, SECRET_KEY

pytestmark = pytest.mark.s3

#: The code the compose stack bootstraps for its own bucket, and the scheme it serves.
CONNECTION = "artifacts"
SCHEME = "s3"


@pytest.fixture
def ctx(tmp_path: Any, s3_server: str, config: S3StorageConfig) -> FakeContext:
    """A step whose scratch is the bucket, with the s3 scheme bound the way an instance binds it.

    ``config`` is requested for its side effect: it is what creates the test bucket.
    """
    context = FakeContext(FakeStorage(tmp_path), f"s3://{BUCKET}/artifacts/runs/one", work=tmp_path / "work")
    context.connections[CONNECTION] = S3StorageSettings(
        endpoint_url=s3_server,
        access_key_id=ACCESS_KEY,
        secret_access_key=SecretStr(SECRET_KEY),
        path_style=True,
        bucket=BUCKET,
    )
    context.connections["analysis"] = SqlConnectionConfig(url="duckdb:///:memory:")
    context.storage_connections[SCHEME] = CONNECTION
    return context


async def write(ctx: FakeContext, *statements: str, params: dict[str, Any] | None = None) -> None:
    """Run statements through sql.execute the way a document's step does."""
    config = SqlExecuteConfig(connection="analysis", statements=list(statements), params=params or {})
    await SqlExecuteOperator().execute(config, ctx.as_context())


async def read(ctx: FakeContext, sql: str, params: dict[str, Any] | None = None) -> SqlQueryOutput:
    """Run one query through sql.query the way a document's step does."""
    output = await SqlQueryOperator().execute(
        SqlQueryConfig(connection="analysis", sql=sql, params=params or {}), ctx.as_context()
    )
    assert isinstance(output, SqlQueryOutput)
    return output


async def test_duckdb_writes_a_parquet_to_the_bucket_and_reads_it_back(ctx: FakeContext) -> None:
    """The whole seam: COPY ... TO an s3:// object, then read_parquet of the object just written."""
    target = f"{ctx.scratch}/readings.parquet"
    await write(
        ctx,
        "CREATE TABLE reading (station TEXT, region TEXT, celsius DOUBLE)",
        "INSERT INTO reading VALUES ('st-1','east',4.5), ('st-2','east',6.1), ('st-3','west',1.2)",
        "COPY (SELECT * FROM reading) TO :target (FORMAT parquet)",
        params={"target": target},
    )

    output = await read(
        ctx,
        "SELECT region, COUNT(*) AS stations FROM read_parquet(:source) GROUP BY region ORDER BY region",
        params={"source": target},
    )

    assert output.rows == [{"region": "east", "stations": 2}, {"region": "west", "stations": 1}]


async def test_the_object_is_really_in_the_bucket_and_not_on_the_worker(
    ctx: FakeContext, config: S3StorageConfig
) -> None:
    """What duckdb wrote is an object the storage backend reads, not a file beside the run."""
    from dirigent_storage_s3 import S3StorageBackend

    target = f"{ctx.scratch}/written.parquet"
    await write(ctx, "COPY (SELECT 1 AS n) TO :target (FORMAT parquet)", params={"target": target})

    landed = await S3StorageBackend(config).stat(target)
    assert landed is not None and landed.size > 0
    assert not list(ctx.work.rglob("*.parquet")), "nothing was staged on the worker's own disk"


async def test_a_bucket_uri_is_refused_when_no_connection_is_bound_to_the_scheme(ctx: FakeContext) -> None:
    """The credential comes from the scheme binding, so a missing one is named rather than guessed."""
    ctx.storage_connections.clear()
    with pytest.raises(BlockFailure) as raised:
        await read(ctx, "SELECT * FROM read_parquet(:source)", params={"source": f"{ctx.scratch}/absent.parquet"})
    assert "DIRIGENT_STORAGE_CONNECTIONS" in str(raised.value)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_query_that_names_no_bucket_needs_no_extension(ctx: FakeContext) -> None:
    """The extension is loaded only where a statement or a value asks for it."""
    ctx.storage_connections.clear()
    assert (await read(ctx, "SELECT 1 AS n")).rows == [{"n": 1}]
