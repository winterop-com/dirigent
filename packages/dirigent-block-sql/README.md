# dirigent-block-sql

The SQL block family: `sql.query` reads rows and `sql.execute` writes them, both against the
database a `sql` connection names.

The connection kind holds the URL and its credential, and the driver is SQLAlchemy's, so any
dialect the worker has installed is addressable. DuckDB is the one exception the family ships
itself, behind the `duckdb` extra: `pip install 'dirigent-block-sql[duckdb]'` carries the
engine and its dialect for a worker that runs a `duckdb://` url.
