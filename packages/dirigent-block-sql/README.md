# dirigent-block-sql

The SQL block family: `sql.query` reads rows and `sql.execute` writes them, both against the
database a `sql` connection names.

The connection kind holds the URL and its credential, and the driver is SQLAlchemy's, so any
dialect with an async driver the worker has installed is addressable.

Engines are packages. A backend that needs more than a driver implements `SqlEngine` and
registers under the `dirigent.sql.engines.v1` entry-point group, and the family asks it what a
valid connection to that backend is, where a database written as a relative path lands, what a
parameter becomes, how a check reaches it, and what a session on it is.
`dirigent-block-sql-duckdb` is the first, and `duckdb:///warehouse.duckdb` works once it is
installed.
