-- What the warehouse in infra/compose.sql.yaml holds: two roles and the table the sql
-- examples on this shelf query. The stack mounts this file; nothing else reads it.
--
-- Run by the postgres image's entrypoint on first start, connected to the warehouse database
-- as its superuser. \getenv reads each role's password from the environment, so no password
-- is written here.

\getenv reader_password WAREHOUSE_READER_PASSWORD
\getenv writer_password WAREHOUSE_WRITER_PASSWORD

-- The shape examples/sql/sql-postgres-readonly.yaml selects: one row per reading, narrowed by
-- site and by the run's window.
CREATE TABLE reading (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site text NOT NULL,
    seen timestamptz NOT NULL,
    value double precision NOT NULL
);

-- Seeded relative to now, so a run whose window is the last hour or the last day finds rows
-- however long ago the volume was created.
INSERT INTO reading (site, seen, value) VALUES
    ('north', now() - interval '3 hours', 11.5),
    ('north', now() - interval '2 hours', 12.25),
    ('north', now() - interval '1 hour', 10.75),
    ('north', now() - interval '20 minutes', 13.0),
    ('south', now() - interval '90 minutes', 8.5),
    ('south', now() - interval '30 minutes', 9.25);

-- SELECT and nothing else. A statement that writes through this role is refused by the
-- database itself, whatever the connection or the document asks for.
CREATE ROLE reader LOGIN PASSWORD :'reader_password';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO reader;

-- The role a loading pipeline uses: the four statements, and the sequence an identity column
-- draws from.
CREATE ROLE writer LOGIN PASSWORD :'writer_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO writer;
