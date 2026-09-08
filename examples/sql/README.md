# SQL examples

The `sql.*` family reads from and writes to a database. `sql.query` runs one statement and
hands its rows on; `sql.execute` runs a list of statements as one transaction.
[docs/sql.md](../../docs/sql.md) is the family's home.

Both are **ordinary** blocks: they run no command a document supplies and reach nothing but the
database their connection names, so no id has to be allowlisted to run them.

```bash
dg run --local examples/sql/sql-sqlite-roundtrip.yaml
dg run --local examples/sql/sql-query-to-storage.yaml
```

Those two need nothing at all -- no network, no daemon, no server. Each builds a SQLite
database in the run's own scratch space, so the whole example is self-contained. The DuckDB one
needs the engine (`dirigent-blocks[duckdb]`) and the parquet pack, and nothing else; the last
names a real PostgreSQL and says so in its own header.

```bash
dg run --local examples/sql/duckdb-parquet-to-report.yaml --keep
```

The rule the whole family turns on: **a value is bound, never interpolated**. The statement is
a constant in the document, every value is a named `:parameter`, and a `${...}` reference
resolves into `params` and never into the SQL text. A parameter that reads as SQL is compared
as a string and matches nothing.

The first two documents carry their `sql` connection in a `connections:` section, because a
`--local` run has no instance to hold one. On a server the connection is created once and the
document names it, with the password set as its own sealed field:

```bash
dg connection create sql warehouse-read \
  --set url=postgresql+asyncpg://reader@db.example:5432/warehouse \
  --set password=... \
  --set read_only=true
```

On the compose stack that database is the `infra/compose.sql.yaml` overlay
(`make docker-run-sql`), seeded with the `reading` table the third document queries, and the
connection names it as `reader@warehouse:5432/warehouse`.

## Pipelines

| File | What it teaches |
| --- | --- |
| [sql-sqlite-roundtrip.yaml](sql-sqlite-roundtrip.yaml) | The family end to end: a table created and filled in one transaction, read back with a bound parameter, and the rows referenced by a downstream step. |
| [sql-query-to-storage.yaml](sql-query-to-storage.yaml) | The large-result rule: `save_to` streams the rows to storage as NDJSON instead of inlining them, and the header says where the line between the two sits. |
| [duckdb-parquet-to-report.yaml](duckdb-parquet-to-report.yaml) | The engine that reads files: a parquet artifact queried by DuckDB through a bound `read_parquet(:source)`, and the answer copied out as a csv artifact. Needs the `dirigent-blocks[duckdb]` extra and the parquet pack. |
| [sql-postgres-readonly.yaml](sql-postgres-readonly.yaml) | A referenced PostgreSQL connection with `read_only: true` and its password sealed separately, queried inside the run's window. Validates offline; it cannot run without an instance. |
| [warehouse.sql](warehouse.sql) | Not a pipeline: the roles and the one table the compose stack's warehouse is seeded with, mounted by `infra/compose.sql.yaml` |
