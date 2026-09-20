# dirigent-block-sql-duckdb

The DuckDB engine of dirigent's `sql` family. Install it beside `dirigent-block-sql` and a
`sql` connection whose url is `duckdb:///warehouse.duckdb` or `duckdb:///:memory:` works like
any other: the same two blocks, the same fields, the same rules.

```bash
uv pip install dirigent-block-sql-duckdb
```

It registers under the `dirigent.sql.engines.v1` entry-point group, so the family finds it with
no configuration, and a worker that never runs a `duckdb://` url carries none of it -- the
engine binary is larger than every other driver the family speaks to put together.

DuckDB has no async driver at all, so every call runs in a worker thread, and a deadline that
passes interrupts the engine rather than leaving a statement running behind a step that has
already failed.

## Files, and what holds them in

A statement here reads and writes the parquet and csv files a run holds: `read_parquet(:source)`
and `COPY ... TO :target` take a file the same way a `WHERE` clause takes a value, and a
`file://` storage URI in `params` arrives as the path duckdb opens.

The boundary is duckdb's own, not a check on the parameters. A session is opened, given the
run's work directory and its local scratch space as its `allowed_directories`, and then closed
around them: `enable_external_access` goes off, which is what makes those roots the only paths
the engine will open, and `lock_configuration` goes on, which refuses the `SET` that would give
any of it back. So a path written straight into the `sql` is refused the same way a parameter
outside the run is, and a statement cannot `LOAD` or `INSTALL` a further extension to reach past
the boundary. Spilled intermediates and duckdb's secret store are pointed inside the run's work
directory for the same reason.

Where a parameter or a statement names an `s3://` object, the session loads duckdb's `httpfs`
extension and is given the endpoint, region, credential and addressing style of the connection
the `s3` scheme is configured from, and that scheme stays reachable beside the run's own
directories. The extension is loaded, never installed, at run time; a bare install does it once:

```bash
python -c "import duckdb; duckdb.connect().execute('INSTALL httpfs')"
```

[docs/sql.md](https://github.com/winterop-com/dirigent/blob/main/docs/sql.md) is the family's
home, and its DuckDB section is the worked example.
