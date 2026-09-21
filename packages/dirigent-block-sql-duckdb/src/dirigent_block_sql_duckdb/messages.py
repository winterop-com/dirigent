"""Every refusal the duckdb engine makes, catalogued under the ``sql.duckdb`` prefix."""

from dirigent_common import Catalogue

DUCKDB = Catalogue("sql.duckdb")

PARAMETER_NAMES_STORAGE = DUCKDB.define(
    "parameter_names_storage",
    "parameter {name} names {scheme}:// storage, and duckdb reads a file through the "
    "worker's own filesystem here; copy it into the run's scratch space with storage.copy first",
)

PARAMETER_OUTSIDE_THE_RUN = DUCKDB.define(
    "parameter_outside_the_run",
    "parameter {name} names {uri}, which is outside this run's own directories ({named}); a "
    "query reads and writes the files of the run it belongs to",
)

NO_STORAGE_CONNECTION = DUCKDB.define(
    "no_storage_connection",
    "this statement names {scheme}:// storage and no connection is bound to the {scheme} scheme, so "
    "duckdb has no endpoint or credential to open it with; set DIRIGENT_STORAGE_CONNECTIONS",
)

NO_HTTPFS = DUCKDB.define(
    "no_httpfs",
    "duckdb could not load its {extension} extension, which is what reads {scheme}:// here; install "
    "it once on this worker with duckdb -c 'INSTALL {extension}'",
)

STATEMENT_OUTSIDE_THE_RUN = DUCKDB.define(
    "statement_outside_the_run",
    "this statement names a file outside the run's own directories ({named}), which is all a "
    "statement reads and writes here; copy it into the run's scratch space with storage.copy first",
)

STATEMENT_LOADS_AN_EXTENSION = DUCKDB.define(
    "statement_loads_an_extension",
    "this statement loads a duckdb extension, and a session carries only the extensions it "
    "was opened with; a bucket a statement names is opened through its storage connection",
)

CONNECT_TIMED_OUT = DUCKDB.define("connect_timed_out", "the database did not answer within {timeout}")


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

READ_ONLY_IN_MEMORY = DUCKDB.define(
    "read_only_in_memory",
    "read_only has no meaning on duckdb:///:memory:, which duckdb refuses to open at all: "
    "an in-memory database starts empty and a read-only one can never be filled, so the "
    "connection would open on nothing; name a duckdb file, or drop read_only",
)
