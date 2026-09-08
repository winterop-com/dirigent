"""What only a real PostgreSQL can prove about the sql family: read-only sessions and timeouts."""

import decimal
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url

from dirigent_blocks.sql import (
    SqlConnectionConfig,
    SqlConnectionKind,
    SqlExecuteConfig,
    SqlExecuteOperator,
    SqlQueryConfig,
    SqlQueryOperator,
    SqlQueryOutput,
)
from dirigent_testing import FakeContext

pytestmark = pytest.mark.postgres

POSTGRES_IMAGE = "postgres:17-alpine"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start a real PostgreSQL for the session, and hand back an asyncpg URL."""
    postgres = pytest.importorskip("testcontainers.community.postgres")
    with postgres.PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture
def sealed(postgres_url: str) -> tuple[str, str]:
    """The container's URL with its password taken out, and the password on its own.

    A url carrying a password inline is exactly what the connection kind refuses, so a test
    that connects has to split it the way a person creating the connection would.
    """
    url = make_url(postgres_url)
    assert url.password is not None
    bare = URL.create(
        url.drivername,
        username=url.username,
        host=url.host,
        port=url.port,
        database=url.database,
    )
    return bare.render_as_string(), url.password


@pytest.fixture
async def table(sealed: tuple[str, str], block_ctx: FakeContext) -> FakeContext:
    """A context with a writable connection and one table of odd column kinds in it."""
    url, password = sealed
    block_ctx.connections["db"] = SqlConnectionConfig(url=url, password=SecretStr(password))
    await SqlExecuteOperator().execute(
        SqlExecuteConfig(
            connection="db",
            statements=[
                "DROP TABLE IF EXISTS reading",
                "CREATE TABLE reading (id uuid PRIMARY KEY, seen date, amount numeric(10,2), payload bytea)",
                # asyncpg infers a parameter's type from where it sits, so a JSON string bound straight
                # into a uuid, date or numeric column is refused; cast it to text first and let
                # PostgreSQL do the conversion it knows how to do.
                "INSERT INTO reading VALUES ("
                "CAST(CAST(:id AS text) AS uuid), "
                "CAST(CAST(:seen AS text) AS date), "
                "CAST(CAST(:amount AS text) AS numeric), "
                ":payload)",
            ],
            params={
                "id": "0f6dc0b6-6f4a-4a5d-9f36-5f1f0f16b2f6",
                "seen": "2026-09-06",
                "amount": "1.25",
                "payload": b"\x00\x01\x02",
            },
        ),
        block_ctx.as_context(),
    )
    return block_ctx


async def query(ctx: FakeContext, sql: str, *, timeout: timedelta = timedelta(minutes=5)) -> SqlQueryOutput:
    """Run one query through the real operator."""
    output = await SqlQueryOperator().execute(
        SqlQueryConfig(connection="db", sql=sql, timeout=timeout),
        ctx.as_context(),
    )
    assert isinstance(output, SqlQueryOutput)
    return output


def read_only(ctx: FakeContext, sealed: tuple[str, str]) -> None:
    """Point the context's connection at the same database, read-only."""
    url, password = sealed
    ctx.connections["db"] = SqlConnectionConfig(url=url, password=SecretStr(password), read_only=True)


async def test_a_read_only_connection_refuses_a_write_in_the_database_itself(
    table: FakeContext, sealed: tuple[str, str]
) -> None:
    read_only(table, sealed)
    with pytest.raises(Exception, match="read-only transaction"):
        await query(table, "DELETE FROM reading")
    read_write = table.connections["db"]
    assert isinstance(read_write, SqlConnectionConfig)


async def test_a_read_only_connection_still_reads(table: FakeContext, sealed: tuple[str, str]) -> None:
    read_only(table, sealed)
    assert (await query(table, "SELECT count(*) AS n FROM reading")).rows == [{"n": 1}]


async def test_execute_is_refused_before_it_reaches_a_read_only_database(
    table: FakeContext, sealed: tuple[str, str]
) -> None:
    read_only(table, sealed)
    with pytest.raises(Exception, match="read_only"):
        await SqlExecuteOperator().execute(
            SqlExecuteConfig(connection="db", statements=["DELETE FROM reading"]),
            table.as_context(),
        )


async def test_the_deadline_is_set_as_the_database_s_own_statement_timeout(table: FakeContext) -> None:
    output = await query(table, "SHOW statement_timeout", timeout=timedelta(milliseconds=250))
    assert output.rows == [{"statement_timeout": "250ms"}]


async def test_a_statement_past_its_deadline_ends_the_step(table: FakeContext) -> None:
    with pytest.raises(Exception, match="statement timeout|canceling statement|^$"):
        await query(table, "SELECT pg_sleep(30)", timeout=timedelta(milliseconds=500))


async def test_a_date_a_decimal_a_uuid_and_bytes_arrive_in_the_house_json_spelling(table: FakeContext) -> None:
    output = await query(table, "SELECT id, seen, amount, payload FROM reading")
    assert output.rows == [
        {
            "id": str(uuid.UUID("0f6dc0b6-6f4a-4a5d-9f36-5f1f0f16b2f6")),
            "seen": "2026-09-06",
            "amount": str(decimal.Decimal("1.25")),
            "payload": "AAEC",
        }
    ]


async def test_a_check_of_a_real_database_is_green(sealed: tuple[str, str]) -> None:
    url, password = sealed
    report = await SqlConnectionKind().check(SqlConnectionConfig(url=url, password=SecretStr(password)))
    assert report.healthy
    assert report.detail == "postgresql answered"
