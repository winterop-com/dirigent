# SQL

The `sql.*` family reads from and writes to a database. It is two blocks:

- [`sql.query`](blocks.md#sqlquery) runs one statement and hands its rows on as the step's
  output.
- [`sql.execute`](blocks.md#sqlexecute) runs a list of statements as one transaction.

Reading a table and writing a table are the two most common things a pipeline does, and until
these blocks the answer was `shell.run` with `psql`: an unsafe block, a credential on a command
line, and a result that arrives as text somebody has to parse.

The blocks' fields are the generated [block reference](blocks.md); this page is the family: the
connection kind that holds the database, how a value reaches a statement, what `max_rows`
bounds and how a result becomes a file, and which engines are covered. The engine is the
connection's URL and nothing else: PostgreSQL and SQLite over an async driver, and DuckDB,
where a table may be a parquet or csv file rather than a table at all.

## These are ordinary blocks

Neither block declares `local_execution`, so no instance has to allowlist them. That is a claim
about the grant, not a convenience: a step runs no command a document supplies, inherits no
worker environment, writes nothing to the worker's filesystem, and reaches nothing but the
database its connection names. "Can edit pipelines" therefore does not become "can run code on
the worker".

It does become "can run SQL against the databases this instance holds connections for", which
is what the connection is for: an instance gives a pipeline the reach it should have by
choosing which connections exist, and `read_only` narrows that further.

## The `sql` connection kind

A step names a connection and never a URL. The connection carries the database and, sealed
beside it, the password that opens it.

| Field | For |
| --- | --- |
| `url` | The database as a SQLAlchemy async URL, driver included: `postgresql+asyncpg://dirigent@db:5432/warehouse`. |
| `password` | The password, on its own and sealed: encrypted at rest, redacted in every API response. |
| `read_only` | Refuse every write through this connection. |
| `connect_timeout` | How long opening a connection may take; past it the step fails as transient. |

```bash
dg connection create sql warehouse \
  --set url=postgresql+asyncpg://reader@db.example:5432/warehouse \
  --set password=... \
  --set read_only=true
dg connection check warehouse
```

A check opens a connection and runs `SELECT 1`, which is the smallest thing that proves both
reach and credential.

**The password is never in the URL.** A URL carrying `user:secret@host` is refused when the
connection is written, because that field is not sealed: it would sit in the database in
plaintext and come back out of the API. The password goes in `password`, and the two are put
together in memory, at connect time, and nowhere else.

**The URL names its driver.** `postgresql://` is refused; `postgresql+asyncpg://` is what these
blocks speak. `postgresql+asyncpg` and `sqlite+aiosqlite` work out of the box. Any other
dialect needs its driver installed on the worker, and a step whose driver is absent fails with
the package to add rather than an import error.

**DuckDB is the exception, because it has no async driver at all.** `duckdb:///warehouse.duckdb`
and `duckdb:///:memory:` name it with no driver written, and the engine runs in a worker thread
instead of over an async one. It is the [engine that reads files](#sql-over-files-duckdb).

A `--local` run has no instance to hold a connection, so a document run that way carries one in
its own `connections:` section -- which is what the
[examples](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/sql) do.

## Values are bound, never interpolated

Nothing a document writes ever reaches the SQL text. The statement is a constant, every value
is a named bind parameter written `:name`, and the parameters go to the database beside the
statement:

```yaml
steps:
  recent:
    block: sql.query
    config:
      connection: warehouse
      sql: SELECT id, site, value FROM reading WHERE site = :site AND seen >= :since
      params:
        site: "${params.site}"
        since: "${run.window.start}"
```

A `${...}` reference resolves into a **value in `params`**, and never into the SQL. That is the
whole rule, and it is what makes a pipeline safe to hand to somebody who writes documents but
not code: a parameter that reads as `'; DROP TABLE reading --` is compared against the `site`
column and matches nothing.

It also means a table or a column name cannot come from a parameter, because those are not
values. A pipeline that needs to read two tables writes two steps.

One statement per field. A `;` outside a string, an identifier, a comment or a dollar-quoted
body ends the statement, so anything but whitespace and comments after one is a second
statement and the document is refused when it is applied. `sql.execute` is where several
statements go, one per entry, and they run in one transaction.

!!! note "PostgreSQL infers a parameter's type from where it sits"

    A JSON document has strings, numbers, booleans and null, and asyncpg binds each of those
    as itself. A string bound straight into a `date`, `uuid` or `numeric` column is refused by
    the driver before it reaches the server. Cast it in the statement --
    `CAST(CAST(:seen AS text) AS date)` -- and let PostgreSQL do the conversion it knows.

## A query hands rows on, and a file is one more hop

`sql.query` has one answer: `rows`, an array of objects keyed by column name, in the step's
output. A transform maps them, a `validate.schema` checks them, and a reference names them,
all without a URI anywhere.

`max_rows` is `1000` by default, and a query returning more than that **fails the step**. It is
not truncated: half an answer is not a smaller answer, and a step acting on it would be acting
on something the database never said. The bound is about memory, and it applies whatever
becomes of the rows afterwards: an output is stored with the run and read back whole, so a
hundred thousand rows in one is a hundred thousand rows in the database and in every read of
that run. A result too large to carry is one the query narrows -- with a `GROUP BY`, a
`LIMIT`, or a `WHERE` the database evaluates instead of the worker.

Rows that belong in a file go to `storage.write`, which is the only way a value leaves a run,
and a conversion reads the object that step wrote:

```yaml
steps:
  extract:
    block: sql.query
    config:
      connection: warehouse
      sql: SELECT * FROM reading
      max_rows: 5000

  save:
    block: storage.write
    depends_on: [extract]
    config:
      target: "${run.scratch}/reading.json"
      value: "${steps.extract.output.rows}"

  to_parquet:
    block: convert.arrow
    depends_on: [save]
    config:
      source: "${steps.save.output.uri}"
      from: json
      to: parquet
      target: "${run.scratch}/reading.parquet"
```

The line between the two shapes: the rows stay in the output when the next step reads them as
a value, and get a write of their own when something outside the run reads them as a file. A
few hundred rows a transform maps is the first; a table an export produces is the second.
[`examples/sql/sql-query-to-storage.yaml`](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/sql)
is the second, hop by hop.

## SQL over files: DuckDB

DuckDB is the second engine of the family, and the one whose tables can be files. The blocks,
the fields and the rules are the same; the connection's URL is what changes:

```yaml
connections:
  analysis:
    kind: sql
    config:
      # A query engine with no state of its own, opened and dropped inside each step.
      url: "duckdb:///:memory:"
```

`duckdb:///warehouse.duckdb` names a file instead, and, like sqlite, a relative path is
resolved against the run's [work directory](operations.md#scratch-and-work). DuckDB ships as
an extra rather than as a hard dependency, because its engine binary is larger than every
other driver put together:

```bash
uv pip install 'dirigent-blocks[duckdb]'
```

**Reading a file.** `read_parquet` and `read_csv_auto` take the file as a **bound parameter**,
the same way a `WHERE` clause takes a value, so the family's one rule holds here too:

```yaml
  summarise:
    block: sql.query
    depends_on: [store]
    config:
      connection: analysis
      sql: >
        SELECT region, COUNT(*) AS stations, ROUND(AVG(celsius), 2) AS mean_celsius
        FROM read_parquet(:source) GROUP BY region ORDER BY region
      params:
        source: "${steps.store.output.target}"
```

**Writing a file.** `COPY ... TO` names its target the same way, and the answer becomes an
artifact rather than rows. It writes, so it is `sql.execute`:

```yaml
  report:
    block: sql.execute
    depends_on: [store]
    config:
      connection: analysis
      statements:
        - COPY (SELECT * FROM read_parquet(:source)) TO :target (FORMAT csv, HEADER)
      params:
        source: "${steps.store.output.target}"
        target: "${run.scratch}/regions.csv"
```

`(FORMAT parquet)` there writes a typed artifact the next pipeline reads back with
`read_parquet`. [`examples/sql/duckdb-parquet-to-report.yaml`](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/sql)
is both directions in one run.

**A parameter that is a storage URI becomes a path.** On a duckdb connection, and on no other,
a `file://` value in `params` is resolved to the path duckdb opens. The run's own directories
are the boundary: a URI outside them is refused, so a query reads and writes the files of the
run it belongs to and nothing else on the worker.

**`s3://` duckdb opens itself.** Where a parameter or a statement names an `s3://` object, the
step loads duckdb's `httpfs` extension and gives it the endpoint, region, credential and
addressing style of the connection the `s3` scheme is configured from -- the same
[`DIRIGENT_STORAGE_CONNECTIONS`](operations.md#storage-and-artifacts) binding the storage
facade itself uses. So `read_parquet` of a bucket object opens it, and `COPY ... TO
's3://...'` writes back, with no local copy in the document. On an instance whose artifact
root is a bucket, `${run.scratch}/readings.parquet` is one of those objects, which is what
lets the example above run unchanged there. A step that names `s3://` with no connection bound
to the scheme is refused, because there is no credential to open it with.

!!! note "httpfs is installed once, never mid-run"

    A step **loads** the extension; it never installs it, because fetching a binary from the
    internet in the middle of a run is not something a worker should do. The container image
    installs it at build time. A bare install -- and any air-gapped worker -- needs the same
    one-time install, as the user the worker runs as:

    ```bash
    python -c "import duckdb; duckdb.connect().execute('INSTALL httpfs')"
    ```

    Without it the step is refused, naming this command. `gs://` and `azure://` have no
    equivalent here yet and are still copied in with `storage.copy` first.

## Values are JSON

A row is an object keyed by column name, and every value is JSON. What has no JSON spelling of
its own gets the one every block in dirigent uses, so a date out of a database and a date out
of a parquet file read the same:

| Column | In a document |
| --- | --- |
| `date`, `time`, `timestamp` | ISO 8601 text |
| `numeric`, `decimal` | its exact digits, as text -- a float would round it |
| `uuid` | its canonical text |
| `bytea`, `blob` | standard base64 |
| `NaN`, `Infinity` | `null`, JSON having no spelling for either |

## Read-only

`read_only: true` on a connection is enforced by the database, not by a check here:

- **PostgreSQL** runs every session as `SET TRANSACTION READ ONLY`, so a write is refused by
  the server with `cannot execute ... in a read-only transaction`.
- **SQLite** sets `PRAGMA query_only = 1`, which does the same for that file.
- **DuckDB** opens the database file itself read-only, so the refusal comes from the engine
  before a statement is parsed. It needs a file that exists, and `duckdb:///:memory:` cannot be
  `read_only` at all -- DuckDB refuses to open an in-memory database read-only, because one
  starts empty and a read-only one could never be filled -- so that connection is refused when
  it is written.

`sql.execute` refuses a `read_only` connection outright, before it opens anything, because that
block exists to write. And a connection on a dialect with no read-only mode cannot be marked
`read_only` at all: the connection is refused when it is written, rather than accepted and left
quietly writable.

The pattern this is for: one connection per role. A `warehouse-read` connection every reporting
pipeline names, and a `warehouse-write` one only the pipelines that load data name.

## Deadlines

`timeout` is `5m` by default on both blocks. On `sql.query` it covers running the statement and
reading its rows; on `sql.execute` it covers the whole transaction, every statement together.
On PostgreSQL it is also set as the session's own `statement_timeout`, so the server cancels
the work rather than leaving it running after the worker has stopped waiting. On DuckDB the
deadline interrupts the engine, which is the same thing by another name: the query runs in a
worker thread, and a thread that is no longer waited on would otherwise keep running. On a
dialect with neither the deadline is enforced on the worker alone.

`connect_timeout` on the connection is the separate deadline for opening the connection, and a
database that does not answer in time fails the step as **transient**, so the retry policy
applies. A database that answers and refuses is **rejected**, and is not retried.

## Dialects

| Dialect | Driver | Ships with dirigent | Read-only | Statement timeout |
| --- | --- | --- | --- | --- |
| PostgreSQL | `postgresql+asyncpg` | yes | yes | yes |
| SQLite | `sqlite+aiosqlite` | yes | yes | no, the worker's deadline only |
| DuckDB | `duckdb`, in a worker thread | with the `duckdb` extra | yes, the file is opened read-only | yes, by interrupt |
| Anything else | its own async driver | no | no | no |

A SQLite or DuckDB database written with a **relative** path -- `sqlite+aiosqlite:///demo.db`,
`duckdb:///demo.duckdb` -- is resolved against the run's
[work directory](operations.md#scratch-and-work), which is where a database a pipeline builds
for itself belongs. That directory is local to the worker that made it, so a later step
reading the database must run on the same worker, and a connection like that cannot be checked
outside a run because outside a run there is nothing there yet. An absolute path
(`sqlite+aiosqlite:////var/lib/data.db`) is used as written.

Another dialect is a driver away: install its async driver on the worker and write it in the
URL. Nothing in these blocks is PostgreSQL-specific beyond the two rows above, and a dialect
without them is refused where it would otherwise be silently weaker.

## On the compose stack

`infra/compose.sql.yaml` starts a second PostgreSQL, `warehouse`, on the [compose
stack's](operations.md) own network. The stack's own `postgres` is dirigent's database and
never a warehouse; this one holds data a pipeline reads. It is an overlay, layered on the base
stack with another `-f`:

```bash
make docker-run-sql   # docker compose ... -f infra/compose.sql.yaml up
```

`examples/sql/warehouse.sql` seeds it on first start with a `reader` role holding SELECT and
nothing else, a `writer` role, and the `reading` table
[`examples/sql/sql-postgres-readonly.yaml`](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/sql)
queries. The two connections name the service:

```bash
dg connection create sql warehouse-read \
  --set url=postgresql+asyncpg://reader@warehouse:5432/warehouse \
  --set password=$WAREHOUSE_READER_PASSWORD \
  --set read_only=true
dg connection create sql warehouse-write \
  --set url=postgresql+asyncpg://writer@warehouse:5432/warehouse \
  --set password=$WAREHOUSE_WRITER_PASSWORD
```

One role per connection is the pattern the family is built for: `read_only` is what the
connection promises, and the role's grants are what the database enforces.

## The limits

- **No schema introspection.** There is no block that lists tables or describes a column. A
  pipeline that needs the shape of a table queries the catalog like anything else.
- **No result set larger than `max_rows`.** The rows are carried in the step's output, so the
  bound is the worker's memory and the run's own database, and writing them to a file
  afterwards does not raise it. A bigger table is read in narrower queries, or by the engine
  that already holds it -- a DuckDB `COPY ... TO` never brings the rows through the worker at
  all.
- **`sql.execute` is not idempotent.** Two attempts run the statements twice. A step that must
  survive a retry writes statements that can: `INSERT ... ON CONFLICT DO NOTHING`, a `MERGE`,
  an idempotent `UPDATE`.
- **One transaction, one connection.** `sql.execute`'s statements share a transaction; two
  steps do not. There is no cross-step transaction and there will not be one: a run is not a
  session.
